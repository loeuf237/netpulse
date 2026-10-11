"""Local history, read-only diagnostics, alerts and explicitly activated profiles."""
import csv
from contextlib import contextmanager
import fcntl
import datetime as dt
import json
import math
import os
import queue
import socket
import sqlite3
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

FEATURE_DEFAULTS = {
    "connection_protected": True,
    "diagnostics_enabled": True,
    "diagnostic_url": "https://github.com",
    "diagnostic_interval": 60,
    "history_retention_days": 90,
    "alert_server_down": True,
    "alert_daily_mib": 0,
    "alert_app_rate_mib": 0,
    "alert_notifications": True,
    "alert_cooldown_sec": 600,
}

FEATURE_LIMITS = {
    "diagnostic_interval": (30, 600),
    "history_retention_days": (1, 365),
    "alert_daily_mib": (0, 10_000_000),
    "alert_app_rate_mib": (0, 100_000),
    "alert_cooldown_sec": (30, 86400),
}


def state_dir():
    return Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "netpulse"


def atomic_file(path, content, mode=0o600):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            os.fchmod(stream.fileno(), mode)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def bounded_number(config, key, minimum, maximum):
    try:
        value = float(config.get(key, FEATURE_DEFAULTS[key]))
        return max(minimum, min(maximum, value)) if math.isfinite(value) else FEATURE_DEFAULTS[key]
    except (ValueError, TypeError):
        return FEATURE_DEFAULTS[key]


def normalize_feature_config(config):
    config = dict(config)
    for key, (minimum, maximum) in FEATURE_LIMITS.items():
        config[key] = bounded_number(config, key, minimum, maximum)
    try:
        validate_diagnostic_url(config.get("diagnostic_url", FEATURE_DEFAULTS["diagnostic_url"]))
    except ValueError:
        config["diagnostic_url"] = FEATURE_DEFAULTS["diagnostic_url"]
    return config


def proxy_display(url):
    """Never expose credentials in diagnostics, profile descriptions or history."""
    try:
        parsed = urllib.parse.urlsplit(url)
        host = parsed.hostname or ""
        host = "[" + host + "]" if ":" in host else host
        return f"{parsed.scheme}://{host}:{parsed.port}" if host and parsed.port else "Non configuré"
    except (ValueError, TypeError):
        return "Non configuré"


def validate_proxy(url):
    if not isinstance(url, str) or len(url) > 2048 or any(c.isspace() for c in url):
        raise ValueError("L'URL du proxy est invalide.")
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("socks5", "socks4", "http") or not parsed.hostname or not parsed.port:
        raise ValueError("Utiliser socks5://hôte:port, socks4://hôte:port ou http://hôte:port.")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("Le proxy ne doit pas contenir de chemin, de requête ou de fragment.")
    return url


def validate_diagnostic_url(url):
    if not isinstance(url, str):
        raise ValueError("Le diagnostic nécessite une URL HTTPS sans identifiants.")
    parsed = urllib.parse.urlsplit(url)
    if (len(url) > 2048 or any(c.isspace() for c in url) or parsed.scheme != "https"
            or not parsed.hostname or parsed.username is not None or parsed.password is not None):
        raise ValueError("Le diagnostic nécessite une URL HTTPS sans identifiants.")
    if parsed.port == 0:
        raise ValueError("Le port HTTPS doit être compris entre 1 et 65535.")
    return url


class HistoryStore:
    """Minute buckets: global traffic and sampled TCP traffic per application."""
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else state_dir() / "history.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS usage(
                    bucket INTEGER NOT NULL, app TEXT NOT NULL,
                    rx INTEGER NOT NULL, tx INTEGER NOT NULL,
                    PRIMARY KEY(bucket, app));
                CREATE TABLE IF NOT EXISTS events(
                    id INTEGER PRIMARY KEY, timestamp REAL NOT NULL,
                    kind TEXT NOT NULL, event_key TEXT NOT NULL, message TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS event_lookup ON events(kind, event_key, timestamp);
                CREATE INDEX IF NOT EXISTS usage_app_bucket ON usage(app, bucket);
            """)
        self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=2)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def record(self, timestamp, rx, tx, applications, retention=90):
        bucket = int(timestamp) // 60 * 60
        rows = [(bucket, "", max(int(rx), 0), max(int(tx), 0))]
        rows += [(bucket, name, max(int(a_rx), 0), max(int(a_tx), 0))
                 for name, a_rx, a_tx in applications if name and (a_rx > 0 or a_tx > 0)]
        with self.connect() as db:
            db.executemany("""INSERT INTO usage VALUES(?,?,?,?)
                ON CONFLICT(bucket,app) DO UPDATE SET rx=rx+excluded.rx, tx=tx+excluded.tx""", rows)
            # Prune only once per hour, independent of the refresh interval.
            if getattr(self, "_pruned_hour", None) != bucket // 3600:
                retention = max(1, min(int(retention), 365))
                cutoff = int(timestamp - retention * 86400)
                db.execute("DELETE FROM usage WHERE bucket < ?", (cutoff,))
                db.execute("DELETE FROM events WHERE timestamp < ?", (cutoff,))
                self._pruned_hour = bucket // 3600

    @staticmethod
    def period_start(days=1, now=None):
        now = dt.datetime.now().astimezone() if now is None else now
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return (start - dt.timedelta(days=max(int(days), 1) - 1)).timestamp()

    def summary(self, days=1, now=None):
        start = self.period_start(days, now)
        end = time.time() if now is None else now.timestamp()
        with self.connect() as db:
            totals = db.execute("SELECT COALESCE(SUM(rx),0) rx, COALESCE(SUM(tx),0) tx "
                                "FROM usage WHERE app='' AND bucket BETWEEN ? AND ?", (start, end)).fetchone()
            apps = db.execute("SELECT app, SUM(rx) rx, SUM(tx) tx FROM usage "
                              "WHERE app<>'' AND bucket BETWEEN ? AND ? GROUP BY app "
                              "ORDER BY SUM(rx+tx) DESC LIMIT 100", (start, end)).fetchall()
            daily = db.execute("SELECT strftime('%Y-%m-%d',bucket,'unixepoch','localtime') day, "
                               "SUM(rx) rx, SUM(tx) tx FROM usage WHERE app='' AND bucket BETWEEN ? AND ? "
                               "GROUP BY day ORDER BY day", (start, end)).fetchall()
        return {"rx": totals["rx"], "tx": totals["tx"],
                "applications": [dict(row) for row in apps], "days": [dict(row) for row in daily]}

    def daily_total(self):
        with self.connect() as db:
            return db.execute("SELECT COALESCE(SUM(rx+tx),0) FROM usage WHERE app='' "
                              "AND bucket BETWEEN ? AND ?", (self.period_start(), time.time())).fetchone()[0]

    def add_event(self, kind, key, message, timestamp=None, cooldown=0):
        timestamp = time.time() if timestamp is None else timestamp
        with self.connect() as db:
            # Deduplication survives monitor restarts.
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT MAX(timestamp) FROM events WHERE kind=? AND event_key=?",
                                  (kind, key)).fetchone()[0]
            if previous is not None and timestamp - previous < cooldown:
                return None
            cursor = db.execute("INSERT INTO events(timestamp,kind,event_key,message) VALUES(?,?,?,?)",
                                (timestamp, kind, key, message))
            return {"id": cursor.lastrowid, "timestamp": timestamp, "kind": kind, "message": message}

    def recent_events(self, limit=30):
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT id,timestamp,kind,message FROM events ORDER BY id DESC LIMIT ?", (limit,))]

    def export_csv(self, path, days=30):
        start = self.period_start(days)
        with self.connect() as db:
            rows = db.execute("SELECT bucket,app,rx,tx FROM usage WHERE bucket BETWEEN ? AND ? "
                              "ORDER BY bucket,app", (start, time.time())).fetchall()
        # A temporary file prevents a failed export from truncating a previous one.
        path = Path(path)
        fd, temporary = tempfile.mkstemp(dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["date_locale", "portee", "application", "octets_recus", "octets_envoyes"])
                for row in rows:
                    name = row["app"]
                    if name.startswith(("=", "+", "-", "@", "\t", "\r")):
                        name = "'" + name
                    writer.writerow([dt.datetime.fromtimestamp(row["bucket"]).astimezone().isoformat(),
                                     "TCP echantillonne" if row["app"] else "Global TCP+UDP",
                                     name or "Toutes les interfaces physiques", row["rx"], row["tx"]])
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return len(rows)


class HttpsRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_diagnostic_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class DiagnosticProbe:
    """Observes connectivity; never starts/stops a tunnel or changes DNS/routes."""
    def run(self, proxy_active, proxy_url, url="https://github.com"):
        result = {"timestamp": time.time(),
                  "tunnel": {"state": "ok" if proxy_active else "inactive",
                             "detail": "Tunnel actif" if proxy_active else "Tunnel inactif"}}
        try:
            url = validate_diagnostic_url(url)
        except (ValueError, TypeError):
            result["dns"] = result["internet"] = {"state": "error", "detail": "URL HTTPS invalide"}
            result["server"] = {"state": "unknown", "detail": "Diagnostic non effectué"}
            return result
        host = urllib.parse.urlsplit(url).hostname
        try:
            socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            result["dns"] = {"state": "ok", "detail": f"{host} résolu"}
        except OSError:
            result["dns"] = {"state": "error", "detail": f"Résolution de {host} impossible"}
        result["server"] = {"state": "unknown", "detail": "Aucun serveur actif"}
        if proxy_active and proxy_url:
            try:
                parsed = urllib.parse.urlsplit(validate_proxy(proxy_url))
                start = time.monotonic()
                with socket.create_connection((parsed.hostname, parsed.port), timeout=3):
                    pass
                result["server"] = {"state": "ok", "detail": proxy_display(proxy_url),
                                    "latency_ms": round((time.monotonic() - start) * 1000, 1)}
            except (OSError, ValueError):
                result["server"] = {"state": "error", "detail": "Serveur proxy TCP inaccessible"}
        start = time.monotonic()
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), HttpsRedirect())
            with opener.open(urllib.request.Request(url, method="HEAD"), timeout=5) as response:
                status = response.status
            result["internet"] = {"state": "ok", "detail": f"HTTPS : HTTP {status}"}
        except urllib.error.HTTPError as exc:
            # A HTTP response proves HTTPS connectivity, even if the endpoint rejects HEAD.
            result["internet"] = {"state": "warning", "detail": f"HTTPS répond : HTTP {exc.code}"}
        except (OSError, ValueError):
            result["internet"] = {"state": "error", "detail": "La requête HTTPS a échoué"}
        result["internet"]["latency_ms"] = round((time.monotonic() - start) * 1000, 1)
        result["endpoint"] = url
        return result


def rule_state(desired, actual, deferred=False, failed=False):
    if failed and desired != actual:
        return {"state": "error", "label": "En erreur", "detail": "La commande a échoué ; l'affectation reste différente."}
    if desired != actual:
        return {"state": "pending", "label": "En attente",
                "detail": "Connexion protégée : affectation différée." if deferred else "Affectation pas encore constatée."}
    return {"state": "applied", "label": "Appliquée",
            "detail": "Affectation constatée dans le noyau. Les sockets déjà ouvertes peuvent garder leur trajet."}


class AlertEngine:
    def __init__(self):
        self.server_failures = 0
        self.server_sample = None
        self.app_samples = {}

    def evaluate(self, payload, diagnostics, daily_total, config):
        events = []
        if not payload.get("proxy_active") or not diagnostics:
            self.server_failures = 0
            self.server_sample = None
        fresh = diagnostics.get("timestamp") is not None and diagnostics.get("timestamp") != self.server_sample
        if fresh:
            self.server_sample = diagnostics.get("timestamp")
            failed = payload.get("proxy_active") and diagnostics.get("server", {}).get("state") == "error"
            self.server_failures = self.server_failures + 1 if failed else 0
        cooldown = bounded_number(config, "alert_cooldown_sec", 30, 86400)
        if fresh and config.get("alert_server_down", True) and self.server_failures >= 2:
            events.append(("server", "proxy", "Le serveur proxy est inaccessible sur deux diagnostics successifs.", cooldown))
        quota = bounded_number(config, "alert_daily_mib", 0, 10_000_000) * 1024**2
        if quota and daily_total >= quota:
            day = dt.datetime.fromtimestamp(payload["timestamp"]).astimezone().date().isoformat()
            events.append(("quota", day, "Le seuil de consommation quotidienne a été atteint.", 86400))
        threshold = bounded_number(config, "alert_app_rate_mib", 0, 100_000) * 1024**2
        rates = {}
        for process in payload.get("processes", []):
            name = process["name"]
            rates[name] = rates.get(name, 0) + process.get("rx_speed", 0) + process.get("tx_speed", 0)
        for name in set(self.app_samples) | set(rates):
            self.app_samples[name] = self.app_samples.get(name, 0) + 1 if threshold and rates.get(name, 0) >= threshold else 0
            if self.app_samples[name] >= 3:
                events.append(("rate", name, f"Débit TCP inhabituel pour « {name} » sur trois relevés successifs.", cooldown))
            if not self.app_samples[name]:
                self.app_samples.pop(name, None)
        return events


class FeatureService:
    """Serial disk worker + one diagnostic worker; neither blocks the GTK/GLib loop."""
    def __init__(self, store=None, notify=None):
        self.store = store
        self.notify = notify
        self.alerts = AlertEngine()
        self.jobs = queue.Queue(maxsize=120)
        self.lock = threading.Lock()
        self.diagnostics = {}
        self.events = []
        self.error = ""
        self._probe_running = False
        self._last_probe = None
        self._probe_context = None
        self._generation = 0
        self._request_key = None
        self._connection_state = None
        self._alert_context = None
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def submit(self, payload, rx, tx, applications, config, proxy_url=""):
        enabled = config.get("diagnostics_enabled", True)
        url = config.get("diagnostic_url", "https://github.com")
        context = (enabled, bool(payload["proxy_active"]), proxy_url, url)
        with self.lock:
            if context != self._probe_context:
                self._probe_context = context
                self.diagnostics = {}
                self._generation += 1
                self._last_probe = None
        try:
            self.jobs.put_nowait((payload, rx, tx, applications, dict(config), context))
        except queue.Full:
            with self.lock:
                self.error = "L'historique n'a pas pu enregistrer certains relevés : file saturée."
        interval = bounded_number(config, "diagnostic_interval", 30, 600)
        with self.lock:
            if not enabled:
                return
            request = config.get("diagnostic_request")
            force = request is not None and request != self._request_key
            if self._probe_running or (self._last_probe is not None and
                    time.monotonic() - self._last_probe < (5 if force else interval)):
                return
            self._request_key = request
            self._probe_running = True
            self._last_probe = time.monotonic()
            generation = self._generation
        def probe():
            try:
                result = DiagnosticProbe().run(context[1], proxy_url, url)
                with self.lock:
                    if generation == self._generation:
                        self.diagnostics = result
            finally:
                with self.lock:
                    self._probe_running = False
        threading.Thread(target=probe, daemon=True).start()

    def _worker(self):
        while True:
            job = self.jobs.get()
            try:
                if job is None:
                    return
                if self.store is None:
                    self.store = HistoryStore()
                payload, rx, tx, apps, config, context = job
                retention = bounded_number(config, "history_retention_days", 1, 365)
                self.store.record(payload["timestamp"], rx, tx, apps, retention)
                active = bool(payload["proxy_active"])
                if self._connection_state is not None and active != self._connection_state:
                    self.store.add_event("tunnel", str(active),
                                         "Tunnel devenu actif." if active else "Tunnel devenu inactif.",
                                         payload["timestamp"])
                self._connection_state = active
                with self.lock:
                    diagnostics = dict(self.diagnostics) if context == self._probe_context else {}
                if context != self._alert_context:
                    self.alerts.server_failures = 0
                    self.alerts.server_sample = None
                    self._alert_context = context
                daily_total = self.store.daily_total() if bounded_number(config, "alert_daily_mib", 0, 10_000_000) else 0
                for kind, key, message, cooldown in self.alerts.evaluate(
                        payload, diagnostics, daily_total, config):
                    event = self.store.add_event(kind, key, message, payload["timestamp"], cooldown)
                    if event and self.notify and config.get("alert_notifications", True):
                        try:
                            self.notify(event)
                        except Exception:
                            pass
                events = self.store.recent_events()
                with self.lock:
                    self.events = events
            except Exception as exc:
                with self.lock:
                    self.error = "Historique indisponible : " + type(exc).__name__
            finally:
                self.jobs.task_done()

    def snapshot(self):
        with self.lock:
            return {"diagnostics": dict(self.diagnostics), "alerts": list(self.events), "storage_error": self.error}

    def close(self):
        try:
            self.jobs.put(None, timeout=1)
            self.thread.join(timeout=2)
        except queue.Full:
            pass


class ProfileStore:
    def __init__(self, path=None):
        self.path = Path(path) if path else Path.home() / ".config/force-proxy/profiles.json"
        self.lock = threading.Lock()

    @staticmethod
    def validate(profile):
        if not isinstance(profile, dict):
            raise ValueError("Le profil doit être un objet JSON.")
        if not isinstance(profile.get("name"), str) or not isinstance(profile.get("proxy_url"), str):
            raise ValueError("Le nom et l'URL du profil doivent être du texte.")
        name = profile["name"].strip()
        if not name or len(name) > 80 or any(ord(c) < 32 for c in name):
            raise ValueError("Le nom du profil doit contenir 1 à 80 caractères.")
        proxy = validate_proxy(profile.get("proxy_url", "").strip())
        mode = profile.get("split_mode", "disabled")
        if mode not in ("disabled", "include", "exclude"):
            raise ValueError("Mode de split tunneling invalide.")
        apps = profile.get("split_apps", [])
        if not isinstance(apps, list) or len(apps) > 2000:
            raise ValueError("Liste d'applications invalide.")
        normalized = []
        for app in apps:
            if not isinstance(app, str) or not app.strip() or len(app) > 256 or any(ord(c) < 32 for c in app):
                raise ValueError("Nom d'application invalide.")
            normalized.append(app.strip().lower())
        bypass = profile.get("bypass_ftp", True)
        if type(bypass) is not bool:
            raise ValueError("L'exemption FTP doit être un booléen.")
        return {"name": name, "proxy_url": proxy, "split_mode": mode,
                "split_apps": sorted(set(normalized)), "bypass_ftp": bypass}

    def list(self):
        try:
            data = json.loads(self.path.read_text())
        except FileNotFoundError:
            return []
        if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("profiles"), list):
            raise ValueError("Le fichier de profils est invalide.")
        result = []
        ids = set()
        for profile in data["profiles"]:
            valid = self.validate(profile)
            valid["id"] = profile.get("id")
            if (not isinstance(valid["id"], str) or not valid["id"] or len(valid["id"]) > 64
                    or valid["id"] in ids):
                raise ValueError("Identifiant de profil invalide.")
            ids.add(valid["id"])
            result.append(valid)
        return result

    def save(self, profile, profile_id=None):
        valid = self.validate(profile)
        with self.locked():
            profiles = self.list()
            if any(p["name"].casefold() == valid["name"].casefold() and p["id"] != profile_id for p in profiles):
                raise ValueError("Un profil porte déjà ce nom.")
            if profile_id is not None and not any(p["id"] == profile_id for p in profiles):
                raise ValueError("Ce profil n'existe plus.")
            valid["id"] = profile_id or uuid.uuid4().hex
            profiles = [p for p in profiles if p["id"] != valid["id"]] + [valid]
            atomic_file(self.path, json.dumps({"version": 1, "profiles": profiles}, ensure_ascii=False, indent=2).encode())
        return valid

    def delete(self, profile_id):
        with self.locked():
            profiles = [p for p in self.list() if p["id"] != profile_id]
            atomic_file(self.path, json.dumps({"version": 1, "profiles": profiles}, ensure_ascii=False).encode())

    @contextmanager
    def locked(self):
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd = os.open(str(self.path) + ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                yield
            finally:
                os.close(fd)


def activate_profile(profile, config_path, split_path, execute, current_proxy=""):
    """Only invoked after a GUI confirmation. Save failures never invoke network commands."""
    profile = ProfileStore.validate(profile)
    config_path, split_path = Path(config_path), Path(split_path)
    previous = {p: (p.read_bytes() if p.exists() else None) for p in (config_path, split_path)}
    config = json.loads(previous[config_path]) if previous[config_path] is not None else {}
    if not isinstance(config, dict):
        raise ValueError("Configuration JSON invalide.")
    config.update(split_tunnel_mode=profile["split_mode"], bypass_ftp=profile["bypass_ftp"])
    try:
        atomic_file(config_path, json.dumps(config, indent=2).encode())
        atomic_file(split_path, ("\n".join(profile["split_apps"]) + "\n").encode())
        if current_proxy != profile["proxy_url"]:
            execute(["start", profile["proxy_url"]])
        # Reconcile rules even when the server can be reused without restarting it.
        execute(["split-mode", profile["split_mode"]])
        execute(["ftp-bypass", "on" if profile["bypass_ftp"] else "off"])
    except Exception:
        for path, contents in previous.items():
            if contents is None:
                path.unlink(missing_ok=True)
            else:
                atomic_file(path, contents)
        # Deliberately no automatic tunnel restart/rollback after a failed explicit activation.
        raise
