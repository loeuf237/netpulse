#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NetPulse Monitor Daemon (GlassWire + Internet Speed Meter Engine)
- Mesure le débit global sur toutes les interfaces physiques réelles (exclut TUN et loopback).
- Fonctionne en permanence que le mode TUN soit activé ou non.
- Extrait les statistiques réseau réelles de chaque socket par PID via tcp_info (ss -tipn).
- Résolution asynchrone DNS inverse pour afficher les adresses IP ET les noms d'hôtes de serveurs.
- Surveillance du pare-feu applicatif (application killswitch).
- Publication des métriques dans /tmp/netpulse_stats.json avec écriture atomique sécurisée.
- Mode tray (StatusNotifierItem) activable optionnellement via --tray (désactivé par défaut pour éviter les doublons).
"""

import os
import sys
import time
import json
import math
import socket
import subprocess
import signal
import threading
import re
import ctypes
import fcntl
import ipaddress
from collections import deque
import psutil
from netpulse.features import FEATURE_DEFAULTS, FeatureService, normalize_feature_config, proxy_display, rule_state

# Nom de processus propre pour GNOME System Monitor ("Ressources")
try:
    libc = ctypes.CDLL(None)
    libc.prctl(15, b"netpulse-mon", 0, 0, 0)
except Exception:
    pass

import gi
gi.require_version('Gio', '2.0')
gi.require_version('GLib', '2.0')
from gi.repository import Gio, GLib

GLib.set_prgname("netpulse-monitor")
GLib.set_application_name("NetPulse Monitor")

CONFIG_DIR = os.path.expanduser("~/.config/force-proxy")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
BLOCKED_FILE = os.path.join(CONFIG_DIR, "blocked_apps.txt")
SPLIT_APPS_FILE = os.path.join(CONFIG_DIR, "split_apps.txt")
STATS_PATH = "/tmp/netpulse_stats.json"
RESET_FLAG_PATH = "/tmp/netpulse_reset_flag"
PID_FILE = "/tmp/netpulse_monitor.pid"
LOCK_FILE = "/tmp/netpulse_monitor.lock"
CTL_BIN = os.path.expanduser("~/.local/bin/netpulse-ctl") if os.path.exists(os.path.expanduser("~/.local/bin/netpulse-ctl")) else os.path.expanduser("~/.local/bin/force-proxy-ctl")
GUI_BIN = os.path.expanduser("~/.local/bin/netpulse-gui") if os.path.exists(os.path.expanduser("~/.local/bin/netpulse-gui")) else os.path.expanduser("~/.local/bin/force-proxy-gui")

FTP_KNOWN_APPS = {
    "filezilla", "ftp", "lftp", "ncftp", "gvfsd-ftp", "kio_ftp", "cyberduck", "tftp", "vsftpd", "proftpd", "pure-ftpd"
}
FTP_PORTS = {20, 21, 989, 990}

SNI_XML = """
<node>
  <interface name="org.kde.StatusNotifierItem">
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="WindowId" type="i" access="read"/>
    <property name="IconThemePath" type="s" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="OverlayIconName" type="s" access="read"/>
    <property name="AttentionIconName" type="s" access="read"/>
    <property name="AttentionMovieName" type="s" access="read"/>
    <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
    <method name="ContextMenu">
      <arg name="x" type="i" direction="in"/>
      <arg name="y" type="i" direction="in"/>
    </method>
    <method name="Activate">
      <arg name="x" type="i" direction="in"/>
      <arg name="y" type="i" direction="in"/>
    </method>
    <method name="SecondaryActivate">
      <arg name="x" type="i" direction="in"/>
      <arg name="y" type="i" direction="in"/>
    </method>
    <method name="Scroll">
      <arg name="delta" type="i" direction="in"/>
      <arg name="orientation" type="s" direction="in"/>
    </method>
    <signal name="NewTitle"/>
    <signal name="NewIcon"/>
    <signal name="NewToolTip"/>
  </interface>
</node>
"""

DEFAULT_CONFIG = {
    **FEATURE_DEFAULTS,
    "refresh_interval": 1,
    "unit_mode": "auto",
    "show_download": True,
    "show_upload": True,
    "show_session_total": True,
    "autostart": True,
    "split_tunnel_mode": "disabled",
    "bypass_ftp": True
}


def get_network_io(per_interface=False):
    """Calcule le trafic total cumulé sur toutes les interfaces physiques réelles.
    Exclut strictement loopback ('lo') et les interfaces de tunnels/conteneurs ('tun*', 'tap*', 'docker*').
    Fonctionne en tout temps, que le mode TUN soit actif ou non.
    """
    pernic = psutil.net_io_counters(pernic=True)
    tot_recv = 0
    tot_sent = 0
    interfaces = {}
    for nic, stat in pernic.items():
        if nic == "lo" or nic.startswith(("tun", "tap", "veth", "docker", "virbr", "br-", "proton", "pvpn", "wg", "zivpn", "lxc", "waydroid")):
            continue
        tot_recv += stat.bytes_recv
        tot_sent += stat.bytes_sent
        interfaces[nic] = (stat.bytes_recv, stat.bytes_sent)
    return interfaces if per_interface else (tot_recv, tot_sent)


def load_config():
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                config = {**DEFAULT_CONFIG, **json.load(f)}
                interval = config.get("refresh_interval")
                if type(interval) is not int or interval not in (1, 2, 3):
                    config["refresh_interval"] = 1
                return normalize_feature_config(config)
    except Exception:
        pass
    return DEFAULT_CONFIG.copy()


def load_blocked_apps():
    try:
        if os.path.exists(BLOCKED_FILE):
            with open(BLOCKED_FILE, "r", encoding="utf-8") as f:
                return set(line.strip().lower() for line in f if line.strip())
    except Exception:
        pass
    return set()


def load_split_apps():
    try:
        if os.path.exists(SPLIT_APPS_FILE):
            with open(SPLIT_APPS_FILE, "r", encoding="utf-8") as f:
                return set(line.strip().lower() for line in f if line.strip())
    except Exception:
        pass
    return set()


def is_app_in_split_list(pname, cmdline, split_apps):
    """Correspondance exacte sur le nom du processus ou le binaire (argv[0]) uniquement.
    Évite les faux positifs d'une recherche par sous-chaîne (ex: 'sh', 'python')."""
    if not split_apps:
        return False
    p_low = pname.lower()
    argv0 = os.path.basename(cmdline[0] if isinstance(cmdline, (list, tuple)) else cmdline.split(" ")[0]).lower() if cmdline else ""
    for app in split_apps:
        if app == p_low or (argv0 and app == argv0):
            return True
    return False


def format_bytes(b, unit_mode="auto"):
    if unit_mode == "bits":
        bits = b * 8
        if bits < 1000:
            return f"{bits:.0f} bps"
        elif bits < 1_000_000:
            return f"{bits / 1000:.1f} Kbps"
        elif bits < 1_000_000_000:
            return f"{bits / 1_000_000:.1f} Mbps"
        else:
            return f"{bits / 1_000_000_000:.2f} Gbps"
    else:
        if b < 1024:
            return f"{b:.0f} B"
        elif b < 1024 * 1024:
            return f"{b / 1024:.1f} KiB"
        elif b < 1024 * 1024 * 1024:
            return f"{b / (1024 * 1024):.1f} MiB"
        else:
            return f"{b / (1024 * 1024 * 1024):.2f} GiB"


def format_speed(bps, unit_mode="auto"):
    if unit_mode == "bits":
        return format_bytes(bps, "bits")
    else:
        return f"{format_bytes(bps, 'auto')}/s"


def format_duration(sec):
    hrs = sec // 3600
    mins = (sec % 3600) // 60
    s = sec % 60
    if hrs > 0:
        return f"{hrs:02d}h {mins:02d}m {s:02d}s"
    return f"{mins:02d}m {s:02d}s"


SHELL_NAMES = {"bash", "sh", "zsh", "fish", "dash", "ksh", "tcsh", "ptyxis", "gnome-terminal", "gnome-terminal-server", "konsole", "xterm", "kitty", "alacritty"}


def resolve_icon(name):
    lower = name.lower()
    # Cas spécifiques d'abord, du plus précis au plus générique
    if "antigravity" in lower:
        return "antigravity-ide"
    elif "chrome" in lower:
        return "google-chrome"
    elif "msedge" in lower or lower.startswith("microsoft-edge") or lower == "edge":
        return "microsoft-edge"
    elif "firefox" in lower:
        return "firefox"
    elif "telegram" in lower:
        return "org.telegram.desktop"
    elif "steam" in lower:
        return "steam"
    elif "snap-store" in lower or "app-center" in lower:
        return "snap-store"
    elif "vlc" in lower:
        return "vlc"
    elif lower == "code" or lower.startswith("code-") or "vscode" in lower:
        return "code"
    elif "python" in lower:
        return "text-x-python"
    elif lower in SHELL_NAMES:
        return "utilities-terminal"
    else:
        return "application-x-executable"


# ---------------------------------------------------------------------
# Asynchronous DNS Reverse Lookup Cache
# ---------------------------------------------------------------------
DNS_CACHE = {}
PENDING_DNS = set()
DNS_LOCK = threading.Lock()


def async_resolve_ip(ip):
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return
    if address.is_loopback or address.is_unspecified:
        return
    with DNS_LOCK:
        if ip in DNS_CACHE or ip in PENDING_DNS or len(PENDING_DNS) >= 8:
            return
        PENDING_DNS.add(ip)

    def worker():
        try:
            host = socket.gethostbyaddr(ip)[0]
        except Exception:
            host = ip
        with DNS_LOCK:
            if len(DNS_CACHE) >= 2048:
                DNS_CACHE.pop(next(iter(DNS_CACHE)))
            DNS_CACHE[ip] = host
            PENDING_DNS.discard(ip)

    threading.Thread(target=worker, daemon=True).start()


def get_resolved_host(ip):
    if not ip or ip == "-":
        return "-"
    with DNS_LOCK:
        return DNS_CACHE.get(ip, ip)


def parse_socket_traffic():
    """Extrait le trafic réseau réel de chaque socket (octets reçus et envoyés par PID) via ss -tipn."""
    try:
        out = subprocess.check_output(['ss', '-tHienp'], text=True, timeout=3, stderr=subprocess.DEVNULL)
    except Exception:
        return {}

    lines = out.splitlines()
    proc_bytes = {}
    cur_pids = []
    socket_key = None

    for line in lines:
        if line and not line[0].isspace():
            # Les propriétaires et l'inode sont propres à chaque socket, quel que soit son état.
            cur_pids = {(int(pid), name) for name, pid in re.findall(r'\("([^\"]+)",pid=(\d+)', line)}
            inode = re.search(r'\bino:(\d+)', line)
            fields = line.split()
            socket_key = inode.group(1) if inode else tuple(fields[3:5])
        elif cur_pids and ('bytes_sent:' in line or 'bytes_received:' in line):
            bs_m = re.search(r'bytes_sent:(\d+)', line)
            br_m = re.search(r'bytes_received:(\d+)', line)
            bs = int(bs_m.group(1)) if bs_m else 0
            br = int(br_m.group(1)) if br_m else 0
            for pid, name in cur_pids:
                prev = proc_bytes.get(pid, {'name': name, 'sent': 0, 'recv': 0, 'sockets': {}})
                prev['sent'] += bs
                prev['recv'] += br
                prev['sockets'][socket_key] = {'sent': bs, 'recv': br}
                proc_bytes[pid] = prev

    return proc_bytes


class NetPulseEngine:
    def __init__(self, enable_tray=False, resume_session=False, preserve_active_tunnel=False, enable_features=False):
        self.config = load_config()
        self.enable_tray = enable_tray

        self.session_start = time.time()
        self.last_time = self.session_start
        self.last_monotonic = time.monotonic()
        self.session_monotonic = self.last_monotonic

        # Starting bytes across all physical interfaces
        self.last_interfaces = get_network_io(per_interface=True)
        self.last_rx = sum(value[0] for value in self.last_interfaces.values())
        self.last_tx = sum(value[1] for value in self.last_interfaces.values())

        self.session_rx = 0
        self.session_tx = 0

        # Per-process tracking
        self.proc_traffic_history = {}
        self.proxy_active = False

        # Bandwidth history buffer: 60 data points (60 seconds)
        self.history = deque(maxlen=60)
        self._protected_tunnel = self._tunnel_identity() if preserve_active_tunnel or self.config.get("connection_protected", True) else None
        self._protection_config = bool(self.config.get("connection_protected", True))
        self._ctl_results = {}
        self._feature_service = FeatureService(notify=self._notify_alert) if enable_features else None
        self.proxy_url = ""

        if resume_session:
            self._restore_session()

        self.cur_rx_formatted = "0 B/s"
        self.cur_tx_formatted = "0 B/s"
        self.cur_tot_rx_formatted = "0 B"
        self.cur_tot_tx_formatted = "0 B"
        self.cur_duration_str = "00m 00s"

        # Initialize firewall rules
        self._init_firewall()

        # Only initialize DBus SNI tray icon if explicitly requested via --tray
        if self.enable_tray:
            try:
                gi.require_version('Dbusmenu', '0.4')
                from gi.repository import Dbusmenu
                self.Dbusmenu = Dbusmenu
                self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
                self._init_dbus_sni()
            except Exception as e:
                print(f"Tray initialization note: {e}", file=sys.stderr)
                self.enable_tray = False

    # Délai minimal avant de relancer une même commande ctl (évite le spam de processus root)
    CTL_RETRY_DELAY = 30.0

    @staticmethod
    def _notify_alert(event):
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        bus.call_sync("org.freedesktop.Notifications", "/org/freedesktop/Notifications",
                      "org.freedesktop.Notifications", "Notify",
                      GLib.Variant("(susssasa{sv}i)", ("NetPulse", 0, "netpulse",
                                    "NetPulse alert", event["message"], [], {}, 8000)),
                      None, Gio.DBusCallFlags.NONE, 1500, None)

    def _refresh_protection(self):
        configured = bool(self.config.get("connection_protected", True))
        if configured:
            self._protected_tunnel = self._tunnel_identity()
        elif self._protection_config:
            self._protected_tunnel = None
        elif self._protected_tunnel and self._tunnel_identity() != self._protected_tunnel:
            self._protected_tunnel = None
        self._protection_config = configured

    def _reap_ctl_jobs(self):
        now = time.time()
        for key, (process, started) in list(getattr(self, "_ctl_jobs", {}).items()):
            result = process.poll()
            if result is not None:
                self._ctl_results[key] = result
                if now - started >= self.CTL_RETRY_DELAY:
                    del self._ctl_jobs[key]
        if len(self._ctl_results) > 256:
            self._ctl_results = dict(list(self._ctl_results.items())[-128:])

    @staticmethod
    def _tunnel_identity():
        for path in ("/run/netpulse/tun2socks.pid", "/tmp/force-proxy.pid"):
            try:
                with open(path, encoding="utf-8") as stream:
                    pid = int(stream.read().strip())
                process = psutil.Process(pid)
                if process.name() == "tun2socks" and process.is_running():
                    return pid, process.create_time()
            except (OSError, ValueError, psutil.Error):
                continue
        return None

    def _restore_session(self):
        try:
            with open(STATS_PATH, encoding="utf-8") as stream:
                data = json.load(stream)
            age = time.time() - data["timestamp"]
            if not 0 <= age <= 15:
                return
            session_rx, session_tx = int(data["session_rx"]), int(data["session_tx"])
            duration = max(int(data.get("session_duration_sec", 0)), 0)
            session_start = float(data["session_start"])
            if session_rx < 0 or session_tx < 0 or not math.isfinite(session_start):
                return
            self.session_rx, self.session_tx = session_rx, session_tx
            self.session_start = session_start
            self.session_monotonic = self.last_monotonic - duration
            for item in data.get("history", []):
                if not isinstance(item, dict):
                    continue
                values = [item.get(key) for key in ("t", "rx", "tx")]
                if all(isinstance(value, (int, float)) and math.isfinite(value) for value in values):
                    if time.time() - 60 <= values[0] <= time.time() and min(values[1:]) >= 0:
                        self.history.append(item)
            for item in data.get("processes", []):
                try:
                    pid = int(item["pid"])
                    process = psutil.Process(pid)
                    identity = process.create_time()
                    if "create_time" in item:
                        if item["create_time"] != identity:
                            continue
                    elif process.name() != item.get("name"):
                        continue
                    self.proc_traffic_history[pid] = {
                        "identity": identity, "sockets": {}, "last_recv": 0, "last_sent": 0,
                        "tot_rx": max(int(item["total_rx"]), 0),
                        "tot_tx": max(int(item["total_tx"]), 0)
                    }
                except (KeyError, ValueError, TypeError, psutil.Error):
                    continue
        except (OSError, ValueError, TypeError, KeyError, OverflowError):
            return

    def _ctl_async(self, *args):
        """Lance une commande netpulse-ctl sans doublons : pas de relance tant que la
        précédente tourne ou pendant le délai de retry. Récolte les processus terminés."""
        self._reap_ctl_jobs()
        protected = getattr(self, "_protected_tunnel", None)
        if protected:
            if self._tunnel_identity() == protected:
                return False
            self._protected_tunnel = None
        if not hasattr(self, "_ctl_jobs"):
            self._ctl_jobs = {}
        now = time.time()
        # Récolte des processus terminés (évite les zombies)
        key = tuple(args)
        job = self._ctl_jobs.get(key)
        if job is not None:
            return False
        try:
            proc = subprocess.Popen([CTL_BIN, *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._ctl_results.pop(key, None)
            self._ctl_jobs[key] = (proc, now)
            return True
        except Exception:
            return False

    def _init_firewall(self):
        self._ctl_async("firewall-init")

    def reset_session(self):
        self.session_start = time.time()
        self.session_rx = 0
        self.session_tx = 0
        self.last_interfaces = get_network_io(per_interface=True)
        self.last_rx = sum(value[0] for value in self.last_interfaces.values())
        self.last_tx = sum(value[1] for value in self.last_interfaces.values())
        self.last_time = self.session_start
        self.last_monotonic = time.monotonic()
        self.session_monotonic = self.last_monotonic
        self.proc_traffic_history.clear()
        self.history.clear()
        if os.path.exists(RESET_FLAG_PATH):
            try:
                os.remove(RESET_FLAG_PATH)
            except Exception:
                pass

    def quit(self):
        """Ferme NetPulse proprement."""
        try:
            if os.path.exists(PID_FILE):
                os.remove(PID_FILE)
        except Exception:
            pass
        sys.exit(0)

    def _init_dbus_sni(self):
        node = Gio.DBusNodeInfo.new_for_xml(SNI_XML)
        self.sni_iface = node.interfaces[0]

        def handle_get_prop(conn, sender, path, iface, prop):
            if prop == "Category":
                return GLib.Variant("s", "ApplicationStatus")
            elif prop == "Id":
                return GLib.Variant("s", "NetPulse")
            elif prop == "Title":
                return GLib.Variant("s", "NetPulse")
            elif prop == "Status":
                return GLib.Variant("s", "Active")
            elif prop == "WindowId":
                return GLib.Variant("i", 0)
            elif prop == "IconThemePath":
                return GLib.Variant("s", "")
            elif prop == "Menu":
                return GLib.Variant("o", "/MenuBar")
            elif prop == "ItemIsMenu":
                return GLib.Variant("b", True)
            elif prop == "IconName":
                return GLib.Variant("s", "netpulse")
            elif prop in ("OverlayIconName", "AttentionIconName", "AttentionMovieName"):
                return GLib.Variant("s", "")
            elif prop == "ToolTip":
                tooltip_body = (
                    f"📥 Download: {self.cur_rx_formatted}\n"
                    f"📤 Upload: {self.cur_tx_formatted}\n"
                    f"📊 Session : ↓ {self.cur_tot_rx_formatted} | ↑ {self.cur_tot_tx_formatted}\n"
                    f"⏱️ Duration: {self.cur_duration_str}"
                )
                return GLib.Variant("(sa(iiay)ss)", ("netpulse", [], "NetPulse", tooltip_body))
            return None

        def handle_method_call(conn, sender, path, iface, method, params, invocation):
            if method in ("Activate", "SecondaryActivate"):
                self.open_gui()
                invocation.return_value(None)
            elif method == "ContextMenu":
                invocation.return_value(None)
            else:
                invocation.return_value(None)

        self.reg_id = self.bus.register_object(
            "/StatusNotifierItem",
            self.sni_iface,
            handle_method_call,
            handle_get_prop,
            None
        )

        # Dbusmenu Server
        self.menu_server = self.Dbusmenu.Server.new("/MenuBar")
        self.menu_root = self.Dbusmenu.Menuitem.new()

        self.mi_down = self.Dbusmenu.Menuitem.new()
        self.mi_down.property_set("label", "📥 Download: 0 B/s")
        self.mi_down.property_set_bool("enabled", False)
        self.menu_root.child_append(self.mi_down)

        self.mi_up = self.Dbusmenu.Menuitem.new()
        self.mi_up.property_set("label", "📤 Upload: 0 B/s")
        self.mi_up.property_set_bool("enabled", False)
        self.menu_root.child_append(self.mi_up)

        sep1 = self.Dbusmenu.Menuitem.new()
        sep1.property_set("type", "separator")
        self.menu_root.child_append(sep1)

        self.mi_tot_rx = self.Dbusmenu.Menuitem.new()
        self.mi_tot_rx.property_set("label", "Total received: 0 B")
        self.mi_tot_rx.property_set_bool("enabled", False)
        self.menu_root.child_append(self.mi_tot_rx)

        self.mi_tot_tx = self.Dbusmenu.Menuitem.new()
        self.mi_tot_tx.property_set("label", "Total sent: 0 B")
        self.mi_tot_tx.property_set_bool("enabled", False)
        self.menu_root.child_append(self.mi_tot_tx)

        self.mi_dur = self.Dbusmenu.Menuitem.new()
        self.mi_dur.property_set("label", "Duration: 00:00")
        self.mi_dur.property_set_bool("enabled", False)
        self.menu_root.child_append(self.mi_dur)

        sep2 = self.Dbusmenu.Menuitem.new()
        sep2.property_set("type", "separator")
        self.menu_root.child_append(sep2)

        self.mi_proxy = self.Dbusmenu.Menuitem.new()
        self.mi_proxy.property_set("label", "⚡ Route through proxy (TUN mode): Inactive")
        self.mi_proxy.connect("item-activated", lambda mi, ts: self.toggle_proxy())
        self.menu_root.child_append(self.mi_proxy)

        sep3 = self.Dbusmenu.Menuitem.new()
        sep3.property_set("type", "separator")
        self.menu_root.child_append(sep3)

        mi_open = self.Dbusmenu.Menuitem.new()
        mi_open.property_set("label", "🖥️ Open NetPulse...")
        mi_open.connect("item-activated", lambda mi, ts: self.open_gui())
        self.menu_root.child_append(mi_open)

        mi_reset = self.Dbusmenu.Menuitem.new()
        mi_reset.property_set("label", "🔄 Reset session data")
        mi_reset.connect("item-activated", lambda mi, ts: self.reset_session())
        self.menu_root.child_append(mi_reset)

        sep4 = self.Dbusmenu.Menuitem.new()
        sep4.property_set("type", "separator")
        self.menu_root.child_append(sep4)

        mi_quit = self.Dbusmenu.Menuitem.new()
        mi_quit.property_set("label", "🛑 Quit NetPulse")
        mi_quit.connect("item-activated", lambda mi, ts: self.quit())
        self.menu_root.child_append(mi_quit)

        self.menu_server.set_root(self.menu_root)

        # Register with watcher
        try:
            watcher = Gio.DBusProxy.new_sync(
                self.bus,
                Gio.DBusProxyFlags.NONE,
                None,
                "org.kde.StatusNotifierWatcher",
                "/StatusNotifierWatcher",
                "org.kde.StatusNotifierWatcher",
                None
            )
            watcher.RegisterStatusNotifierItem("(s)", "/StatusNotifierItem")
        except Exception:
            pass

    def open_gui(self):
        try:
            subprocess.Popen([GUI_BIN], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    def toggle_proxy(self):
        if self.config.get("connection_protected", True) or getattr(self, "_protected_tunnel", None):
            self.open_gui()
            return
        action = "stop" if self.proxy_active else "start"
        try:
            subprocess.Popen([CTL_BIN, action], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    def check_proxy_status(self):
        try:
            res = subprocess.run([CTL_BIN, "status", "--json"], capture_output=True, text=True, timeout=2)
            if res.stdout:
                data = json.loads(res.stdout)
                was_active = self.proxy_active
                self.proxy_active = bool(data.get("active"))
                self.proxy_url = data.get("proxy", "") if self.proxy_active else ""
                proxy_name = proxy_display(data.get("proxy", ""))
                if self.enable_tray and hasattr(self, "mi_proxy"):
                    if self.config.get("connection_protected", True) or getattr(self, "_protected_tunnel", None):
                        self.mi_proxy.property_set("label", "🔒 Connection protected: confirm in NetPulse")
                    elif self.proxy_active:
                        self.mi_proxy.property_set("label", f"⚡ Proxy routing: ACTIVE ({proxy_name})")
                    else:
                        self.mi_proxy.property_set("label", "⚡ Route through proxy (TUN mode): Inactive")

                    if was_active != self.proxy_active:
                        self.bus.emit_signal(
                            None,
                            "/StatusNotifierItem",
                            "org.kde.StatusNotifierItem",
                            "NewIcon",
                            None
                        )
        except Exception:
            pass

    def collect(self):
        if os.path.exists(RESET_FLAG_PATH):
            self.reset_session()

        now = time.time()
        monotonic_now = time.monotonic()
        dt = max(monotonic_now - self.last_monotonic, 0.001)

        # -------------------------------------------------------------
        # 1. Global network I/O: ALL PHYSICAL INTERFACES (Excludes TUN & lo)
        # -------------------------------------------------------------
        current_interfaces = get_network_io(per_interface=True)
        rx_diff = sum(max(value[0] - self.last_interfaces.get(nic, value)[0], 0)
                      for nic, value in current_interfaces.items())
        tx_diff = sum(max(value[1] - self.last_interfaces.get(nic, value)[1], 0)
                      for nic, value in current_interfaces.items())
        cur_rx = sum(value[0] for value in current_interfaces.values())
        cur_tx = sum(value[1] for value in current_interfaces.values())

        rx_speed = rx_diff / dt
        tx_speed = tx_diff / dt

        self.session_rx += rx_diff
        self.session_tx += tx_diff

        self.last_rx = cur_rx
        self.last_tx = cur_tx
        self.last_time = now
        self.last_monotonic = monotonic_now
        self.last_interfaces = current_interfaces

        while self.history and self.history[0]["t"] < now - 60:
            self.history.popleft()

        # Add to historical buffer for graph
        self.history.append({
            "rx": rx_speed,
            "tx": tx_speed,
            "t": now
        })

        # Reload config and blocked apps list
        self.config = load_config()
        self._refresh_protection()
        self._reap_ctl_jobs()
        unit_mode = self.config.get("unit_mode", "auto")
        blocked_apps = load_blocked_apps()

        session_duration = max(int(monotonic_now - self.session_monotonic), 0)

        self.cur_rx_formatted = format_speed(rx_speed, unit_mode)
        self.cur_tx_formatted = format_speed(tx_speed, unit_mode)
        self.cur_tot_rx_formatted = format_bytes(self.session_rx, unit_mode)
        self.cur_tot_tx_formatted = format_bytes(self.session_tx, unit_mode)
        self.cur_duration_str = format_duration(session_duration)

        # -------------------------------------------------------------
        # 2. Extract Real Network Sockets Traffic Per PID (ss -tipn)
        # -------------------------------------------------------------
        current_socket_traffic = parse_socket_traffic()

        proc_live_rates = {}
        for pid, sinfo in current_socket_traffic.items():
            try:
                identity = psutil.Process(pid).create_time()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            hist = self.proc_traffic_history.get(pid, {
                'last_recv': sinfo['recv'],
                'last_sent': sinfo['sent'],
                'tot_rx': 0,
                'tot_tx': 0
            })
            if hist.get('identity', identity) != identity:
                hist = {'tot_rx': 0, 'tot_tx': 0, 'sockets': {}}

            old_sockets = hist.get('sockets', {})
            p_rx_diff = sum(max(sample['recv'] - old_sockets.get(key, sample)['recv'], 0)
                            for key, sample in sinfo['sockets'].items())
            p_tx_diff = sum(max(sample['sent'] - old_sockets.get(key, sample)['sent'], 0)
                            for key, sample in sinfo['sockets'].items())

            p_rx_speed = p_rx_diff / dt
            p_tx_speed = p_tx_diff / dt

            p_tot_rx = hist['tot_rx'] + p_rx_diff
            p_tot_tx = hist['tot_tx'] + p_tx_diff

            self.proc_traffic_history[pid] = {
                'last_recv': sinfo['recv'],
                'last_sent': sinfo['sent'],
                'tot_rx': p_tot_rx,
                'tot_tx': p_tot_tx,
                'sockets': sinfo['sockets'],
                'identity': identity
            }

            proc_live_rates[pid] = {
                'rx_speed': p_rx_speed,
                'tx_speed': p_tx_speed,
                'tot_rx': p_tot_rx,
                'tot_tx': p_tot_tx
            }

        # -------------------------------------------------------------
        # 3. Scan Network Connections & Endpoints
        # -------------------------------------------------------------
        try:
            conns = psutil.net_connections(kind="inet")
        except Exception:
            conns = []

        grouped_conns = {}
        for c in conns:
            if c.pid:
                grouped_conns.setdefault(c.pid, []).append(c)

        process_list = []
        application_deltas = []
        for traffic_pid, sample in current_socket_traffic.items():
            rate = proc_live_rates.get(traffic_pid, {})
            application_deltas.append((sample["name"], round(rate.get("rx_speed", 0) * dt),
                                       round(rate.get("tx_speed", 0) * dt)))
        # Un processus bloqué doit rester visible, même après la fermeture de ses sockets.
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            if is_app_in_split_list(proc.info.get('name') or '', proc.info.get('cmdline') or [], blocked_apps):
                grouped_conns.setdefault(proc.pid, [])
        current_pids = set(grouped_conns.keys())

        # Clean terminated processes from history
        for pid in list(self.proc_traffic_history.keys()):
            if not psutil.pid_exists(pid):
                del self.proc_traffic_history[pid]
            elif pid not in current_socket_traffic:
                self.proc_traffic_history[pid]['sockets'] = {}

        # Read currently blocked cgroup PIDs
        cgroup_blocked_pids = set()
        try:
            if os.path.exists("/sys/fs/cgroup/net_blocked/cgroup.procs"):
                with open("/sys/fs/cgroup/net_blocked/cgroup.procs", "r") as f:
                    cgroup_blocked_pids = set(int(line.strip()) for line in f if line.strip())
        except Exception:
            pass

        # Split Tunneling state & cgroups
        split_apps = load_split_apps()
        split_mode = self.config.get("split_tunnel_mode", "disabled")
        cgroup_proxy_pids = set()
        try:
            if os.path.exists("/sys/fs/cgroup/net_proxy/cgroup.procs"):
                with open("/sys/fs/cgroup/net_proxy/cgroup.procs", "r") as f:
                    cgroup_proxy_pids = set(int(line.strip()) for line in f if line.strip())
        except Exception:
            pass

        cgroup_direct_pids = set()
        try:
            if os.path.exists("/sys/fs/cgroup/net_direct/cgroup.procs"):
                with open("/sys/fs/cgroup/net_direct/cgroup.procs", "r") as f:
                    cgroup_direct_pids = set(int(line.strip()) for line in f if line.strip())
        except Exception:
            pass

        for pid in cgroup_blocked_pids:
            grouped_conns.setdefault(pid, [])

        self.check_proxy_status()
        for pid, c_list in grouped_conns.items():
            try:
                proc = psutil.Process(pid)
                pname = proc.name()
                argv = proc.cmdline()
                cmdline = " ".join(argv[:3]) if argv else pname

                matches_blocked = is_app_in_split_list(pname, argv, blocked_apps)
                is_app_blocked = pid in cgroup_blocked_pids
                block_requested = matches_blocked or is_app_blocked
                if matches_blocked and pid not in cgroup_blocked_pids:
                    self._ctl_async("block", str(pid))

                # Split Tunneling & FTP routing determination
                is_in_split = is_app_in_split_list(pname, argv, split_apps)
                is_ftp = (pname.lower() in FTP_KNOWN_APPS) or any(
                    (getattr(c, 'raddr', None) and getattr(c.raddr, 'port', None) in FTP_PORTS) or
                    (getattr(c, 'laddr', None) and getattr(c.laddr, 'port', None) in FTP_PORTS)
                    for c in c_list
                )

                if self.proxy_active:
                    if is_ftp and self.config.get("bypass_ftp", True):
                        route_mode = "direct"
                    elif split_mode == "include":
                        if is_in_split:
                            route_mode = "proxy"
                        else:
                            route_mode = "direct"
                    elif split_mode == "exclude":
                        if is_in_split:
                            route_mode = "direct"
                        else:
                            route_mode = "proxy"
                    else:  # disabled
                        route_mode = "proxy"
                else:
                    route_mode = "direct"

                if self.proxy_active and not is_app_blocked and not block_requested:
                    destination = "default"
                    if route_mode == "direct" and (split_mode != "include" or is_ftp and self.config.get("bypass_ftp", True)):
                        destination = "direct"
                    elif route_mode == "proxy" and split_mode == "include":
                        destination = "proxy"
                    if ((destination == "proxy" and pid not in cgroup_proxy_pids) or
                        (destination == "direct" and pid not in cgroup_direct_pids) or
                        (destination == "default" and pid in cgroup_proxy_pids | cgroup_direct_pids)):
                        self._ctl_async("split-assign", str(pid), destination)
                actual_group = ("blocked" if is_app_blocked else "proxy" if pid in cgroup_proxy_pids
                                else "direct" if pid in cgroup_direct_pids else "default")
                desired_group = "blocked" if block_requested else "default"
                if not block_requested and self.proxy_active:
                    if route_mode == "direct" and (split_mode != "include" or is_ftp and self.config.get("bypass_ftp", True)):
                        desired_group = "direct"
                    elif route_mode == "proxy" and split_mode == "include":
                        desired_group = "proxy"
                command_key = (("block", str(pid)) if block_requested else
                               ("split-assign", str(pid), desired_group))
                rule = rule_state(desired_group, actual_group, bool(self._protected_tunnel),
                                  self._ctl_results.get(command_key, 0) != 0)

                hist = self.proc_traffic_history.get(pid, {})
                prate = proc_live_rates.get(pid, {'rx_speed': 0.0, 'tx_speed': 0.0,
                                                 'tot_rx': hist.get('tot_rx', 0), 'tot_tx': hist.get('tot_tx', 0)})
                p_rx_speed = prate['rx_speed']
                p_tx_speed = prate['tx_speed']
                p_tot_rx = prate['tot_rx']
                p_tot_tx = prate['tot_tx']

                statuses = set(c.status for c in c_list if c.status)
                if is_app_blocked:
                    status_text = "🚫 Blocked (Firewall)"
                elif "ESTABLISHED" in statuses:
                    status_text = f"Connected ({len(c_list)})"
                elif "LISTEN" in statuses:
                    status_text = "Listening"
                elif statuses:
                    status_text = f"{list(statuses)[0]} ({len(c_list)})"
                else:
                    status_text = f"Active ({len(c_list)})"

                conn_details = []
                contacted_hosts = set()

                for c in c_list[:25]:
                    laddr = f"{c.laddr.ip}:{c.laddr.port}" if c.laddr else "-"
                    r_ip = c.raddr.ip if c.raddr else "-"
                    r_port = c.raddr.port if c.raddr else 0
                    proto = "TCP" if c.type == socket.SOCK_STREAM else "UDP"

                    if r_ip and r_ip != "-":
                        async_resolve_ip(r_ip)
                        r_host = get_resolved_host(r_ip)
                        if r_host != r_ip:
                            contacted_hosts.add(r_host)
                    else:
                        r_host = "-"

                    conn_details.append({
                        "proto": proto,
                        "local": laddr,
                        "remote_ip": r_ip,
                        "remote_port": r_port,
                        "remote_host": r_host,
                        "status": c.status or "ACTIVE"
                    })

                process_list.append({
                    "pid": pid,
                    "create_time": proc.create_time(),
                    "name": pname,
                    "cmdline": cmdline,
                    "icon": resolve_icon(pname),
                    "is_blocked": is_app_blocked,
                    "block_requested": block_requested,
                    "actual_group": actual_group,
                    "desired_group": desired_group,
                    "rule_status": rule,
                    "routing": route_mode,
                    "is_in_split": is_in_split,
                    "is_ftp": is_ftp,
                    "status": status_text,
                    "connections_count": len(c_list),
                    "rx_speed": p_rx_speed,
                    "tx_speed": p_tx_speed,
                    "rx_speed_formatted": format_speed(p_rx_speed, unit_mode),
                    "tx_speed_formatted": format_speed(p_tx_speed, unit_mode),
                    "total_rx": p_tot_rx,
                    "total_tx": p_tot_tx,
                    "total_rx_formatted": format_bytes(p_tot_rx, unit_mode),
                    "total_tx_formatted": format_bytes(p_tot_tx, unit_mode),
                    "contacted_hosts": sorted(list(contacted_hosts))[:5],
                    "connections": conn_details
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        process_list.sort(key=lambda x: (x["rx_speed"] + x["tx_speed"], x["total_rx"] + x["total_tx"], x["connections_count"]), reverse=True)

        payload = {
            "timestamp": now,
            "session_start": self.session_start,
            "session_duration_sec": session_duration,
            "proxy_active": self.proxy_active,
            "network_actions_deferred": bool(getattr(self, "_protected_tunnel", None)),
            "connection_protected": bool(self.config.get("connection_protected", True)),
            "bypass_ftp": self.config.get("bypass_ftp", True),
            "show_download": self.config.get("show_download", True),
            "show_upload": self.config.get("show_upload", True),
            "show_session_total": self.config.get("show_session_total", True),
            "split_tunnel_mode": split_mode,
            "split_apps": sorted(list(split_apps)),
            "proxy_pids_count": len(cgroup_proxy_pids),
            "direct_pids_count": len(cgroup_direct_pids),
            "rx_speed": rx_speed,
            "tx_speed": tx_speed,
            "rx_speed_formatted": self.cur_rx_formatted,
            "tx_speed_formatted": self.cur_tx_formatted,
            "session_rx": self.session_rx,
            "session_tx": self.session_tx,
            "session_rx_formatted": self.cur_tot_rx_formatted,
            "session_tx_formatted": self.cur_tot_tx_formatted,
            "active_connections_count": len(conns),
            "active_processes_count": len(process_list),
            "history": list(self.history),
            "processes": process_list
        }
        if self._feature_service:
            self._feature_service.submit(payload, rx_diff, tx_diff, application_deltas,
                                         self.config, self.proxy_url)
            payload.update(self._feature_service.snapshot())

        # Écriture atomique avec fichier temporaire unique par PID (évite les conflits)
        tmp_target = f"{STATS_PATH}.{os.getpid()}.tmp"
        try:
            with open(tmp_target, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            os.replace(tmp_target, STATS_PATH)
        except Exception as e:
            print(f"Error saving stats: {e}", file=sys.stderr)

        if self.enable_tray:
            try:
                self.mi_down.property_set("label", f"📥 Download: {self.cur_rx_formatted}")
                self.mi_up.property_set("label", f"📤 Upload: {self.cur_tx_formatted}")
                self.mi_tot_rx.property_set("label", f"Total received: {self.cur_tot_rx_formatted}")
                self.mi_tot_tx.property_set("label", f"Total sent: {self.cur_tot_tx_formatted}")
                self.mi_dur.property_set("label", f"Session duration: {self.cur_duration_str}")

                self.bus.emit_signal(
                    None,
                    "/StatusNotifierItem",
                    "org.kde.StatusNotifierItem",
                    "NewToolTip",
                    None
                )
            except Exception:
                pass

        return True

    def run(self):
        with open(PID_FILE, "w") as f:
            f.write(str(os.getpid()))

        def handle_term(sig, frame):
            try:
                if os.path.exists(PID_FILE):
                    os.remove(PID_FILE)
            except Exception:
                pass
            sys.exit(0)

        signal.signal(signal.SIGTERM, handle_term)
        signal.signal(signal.SIGINT, handle_term)

        self._schedule_collect()
        self.collect()

        loop = GLib.MainLoop()
        loop.run()

    def _schedule_collect(self):
        interval = self.config.get("refresh_interval", 1)
        def tick():
            try:
                self.collect()
            finally:
                self._schedule_collect()
            return GLib.SOURCE_REMOVE
        GLib.timeout_add_seconds(interval, tick)


def main():
    if "--reset" in sys.argv:
        with open(RESET_FLAG_PATH, "w") as f:
            f.write("1")
        print("Reset request sent to the monitor.")
        sys.exit(0)

    enable_tray = "--tray" in sys.argv
    # Le verrou reste ouvert pendant toute la vie du démon ; un PID périmé ne le bloque pas.
    lock_fd = os.open(LOCK_FILE, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(lock_fd)
        return
    engine = NetPulseEngine(enable_tray=enable_tray, resume_session="--resume-session" in sys.argv,
                            preserve_active_tunnel="--preserve-active-tunnel" in sys.argv, enable_features=True)
    try:
        engine.run()
    finally:
        if engine._feature_service:
            engine._feature_service.close()
        os.close(lock_fd)


if __name__ == "__main__":
    main()
