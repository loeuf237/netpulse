#!/usr/bin/env python3
"""Mettre à jour une installation existante sans relancer le tunnel ni fermer sa GUI."""
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parent
HOME_DIR = Path.home()
BIN = HOME_DIR / ".local/bin"
STATS = Path("/tmp/netpulse_stats.json")
MONITOR_PID = Path("/tmp/netpulse_monitor.pid")
PRIVILEGED = Path("/usr/local/libexec/netpulse/netpulse-ctl")


def command(*args, env=None):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=15, env=env).stdout


def atomic_write(path, content, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            os.fchmod(stream.fileno(), mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def active_tunnel():
    for path in (Path("/run/netpulse/tun2socks.pid"), Path("/tmp/force-proxy.pid")):
        try:
            process = psutil.Process(int(path.read_text().strip()))
            if process.name() == "tun2socks" and process.is_running():
                return process
        except (OSError, ValueError, psutil.Error):
            pass
    raise RuntimeError("Aucun tunnel actif : utiliser install.sh pour une installation normale.")


def network_snapshot():
    # Seulement les paramètres stables, jamais les compteurs de trafic ou l'URL du proxy.
    link = json.loads(command("ip", "-j", "link", "show", "dev", "tun-proxy"))[0]
    return {
        "routes": json.loads(command("ip", "-j", "-4", "route", "show", "table", "all")),
        "rules": json.loads(command("ip", "-j", "-4", "rule", "show")),
        "tun": {key: link.get(key) for key in ("ifindex", "ifname", "mtu", "flags", "operstate")},
    }


def verify_network(tunnel, identity, baseline):
    if not tunnel.is_running() or tunnel.create_time() != identity:
        raise RuntimeError("Le processus du tunnel a changé pendant la mise à jour.")
    if network_snapshot() != baseline:
        raise RuntimeError("Les routes, règles ou paramètres TUN ont changé ; aucune restauration réseau automatique.")


def wait_for_stats(old_timestamp, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            data = json.loads(STATS.read_text())
            if (data["timestamp"] > old_timestamp and data["proxy_active"]
                    and data.get("network_actions_deferred")):
                return data
        except (OSError, ValueError, KeyError):
            pass
        time.sleep(0.2)
    raise RuntimeError("Le nouveau moniteur n'a pas publié de statistiques protégées.")


def busy_children(process):
    for child in process.children(recursive=True):
        try:
            if child.status() not in (psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD):
                return True
        except psutil.NoSuchProcess:
            continue
    return False


def main():
    if os.getuid() == 0:
        raise RuntimeError("Lancer avec l'utilisateur de session, pas avec sudo.")
    tunnel = active_tunnel()
    identity = tunnel.create_time()
    baseline = network_snapshot()
    old_monitor = psutil.Process(int(MONITOR_PID.read_text().strip()))
    if (old_monitor.uids().real != os.getuid() or old_monitor.name() != "netpulse-mon"
            or str(BIN / "netpulse-monitor") not in old_monitor.cmdline()):
        raise RuntimeError("Le PID du moniteur ne correspond pas à l'installation attendue.")
    guis = []
    for process in psutil.process_iter(["name", "cmdline", "uids"]):
        if (process.info["name"] == "netpulse" and process.info["uids"].real == os.getuid()
                and str(BIN / "netpulse-gui") in (process.info["cmdline"] or [])):
            guis.append(process)
    env = os.environ.copy()
    if guis:
        session_env = guis[0].environ()
        for key in ("DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS"):
            if key in session_env:
                env[key] = session_env[key]

    helper = PRIVILEGED if PRIVILEGED.exists() else BIN / "netpulse-ctl"
    if PRIVILEGED.exists() and PRIVILEGED.read_bytes() != (ROOT / "bin/netpulse-ctl").read_bytes():
        raise RuntimeError("Installer d'abord le contrôleur root mis à jour avec sudo install, sans relancer le proxy.")
    command("sudo", "-n", str(helper), "check-sudo", env=env)
    command("bash", "-n", str(ROOT / "bin/netpulse-ctl"))
    for name in ("netpulse-monitor", "netpulse-gui"):
        compile((ROOT / "bin" / name).read_bytes(), str(ROOT / "bin" / name), "exec")
    command("python3", "-c", "import gi,cairo,psutil; gi.require_version('Gtk','4.0'); "
            "gi.require_version('Adw','1'); gi.require_version('Rsvg','2.0'); "
            "from gi.repository import Gtk,Adw,Rsvg", env=env)
    old_stats = json.loads(STATS.read_text())
    backup = HOME_DIR / ".local/state/netpulse/backups" / time.strftime("%Y%m%d-%H%M%S")
    backup.mkdir(parents=True, mode=0o700)
    unit = HOME_DIR / ".config/systemd/user/netpulse-monitor.service"
    desktop = HOME_DIR / ".local/share/applications/netpulse.desktop"
    extension = HOME_DIR / ".local/share/gnome-shell/extensions/force-proxy@paulin"
    targets = [BIN / name for name in ("netpulse-ctl", "netpulse-monitor", "netpulse-gui")]
    targets += [unit, desktop] + [extension / p.name for p in (ROOT / "extension").iterdir() if p.is_file()]
    manifest = {}
    for index, target in enumerate(targets):
        if target.exists():
            saved = backup / str(index)
            shutil.copy2(target, saved)
            manifest[str(target)] = str(saved)
        else:
            manifest[str(target)] = None
    (backup / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (backup / "network-before.json").write_text(json.dumps(baseline, indent=2))
    (backup / "stats-before.json").write_text(json.dumps(old_stats))
    print(f"Sauvegarde : {backup}", flush=True)
    print(f"Tunnel conservé : PID {tunnel.pid}. Mise à jour du moniteur uniquement.", flush=True)

    monitor_stopped = False
    service_started = False
    try:
        # Arrêter le moniteur avant de remplacer le ctl : l'ancien ne doit pas utiliser les nouvelles règles.
        deadline = time.monotonic() + 5
        while busy_children(old_monitor) and time.monotonic() < deadline:
            time.sleep(0.1)
        if busy_children(old_monitor):
            raise RuntimeError("Une commande du moniteur est en cours ; réessayer après sa fin.")
        unit_pid = int(command("systemctl", "--user", "show", "-p", "MainPID", "--value",
                               "netpulse-monitor.service", env=env).strip())
        if unit_pid == old_monitor.pid:
            if any(line.startswith(("ExecStop=", "ExecStopPost=")) for line in unit.read_text().splitlines()):
                raise RuntimeError("Le service contient une commande d'arrêt personnalisée : mise à jour interrompue.")
            command("systemctl", "--user", "stop", "netpulse-monitor.service", env=env)
        else:
            old_monitor.terminate()
        old_monitor.wait(timeout=5)
        monitor_stopped = True
        verify_network(tunnel, identity, baseline)
        atomic_write(BIN / "netpulse-ctl", (ROOT / "bin/netpulse-ctl").read_bytes(), 0o755)
        command("sudo", "-n", str(helper), "install-runtime", env=env)
        verify_network(tunnel, identity, baseline)
        for name in ("netpulse-monitor", "netpulse-gui"):
            atomic_write(BIN / name, (ROOT / "bin" / name).read_bytes(), 0o755)
        # La protection reste présente si systemd doit relancer le moniteur.
        service = (ROOT / "systemd/netpulse-monitor.service").read_text().replace(
            "ExecStart=%h/.local/bin/netpulse-monitor",
            "ExecStart=%h/.local/bin/netpulse-monitor --resume-session --preserve-active-tunnel")
        atomic_write(unit, service.encode())
        executable = str(BIN / "netpulse-gui")
        for old, new in (("\\", "\\\\"), ('"', '\\"'), ("`", "\\`"), ("$", "\\$"), ("%", "%%")):
            executable = executable.replace(old, new)
        launcher = "\n".join(f'Exec="{executable}"' if line.startswith("Exec=") else line
                             for line in (ROOT / "desktop/netpulse.desktop").read_text().splitlines()) + "\n"
        atomic_write(desktop, launcher.encode())
        for source in (ROOT / "extension").iterdir():
            if source.is_file():
                atomic_write(extension / source.name, source.read_bytes())
        command("systemctl", "--user", "daemon-reload", env=env)
        command("systemctl", "--user", "start", "netpulse-monitor.service", env=env)
        service_started = True
        stats = wait_for_stats(old_stats["timestamp"])
        new_pid = int(MONITOR_PID.read_text().strip())
        if new_pid == old_monitor.pid:
            raise RuntimeError("Le moniteur n'a pas changé de processus.")
        if stats["session_start"] != old_stats["session_start"]:
            raise RuntimeError("La session de statistiques n'a pas été reprise.")
        verify_network(tunnel, identity, baseline)
    except Exception:
        # Revenir aux fichiers précédents, sans aucune commande proxy/pare-feu/routage.
        if service_started:
            command("systemctl", "--user", "stop", "netpulse-monitor.service", env=env)
        for target, saved in manifest.items():
            if saved:
                path = Path(saved)
                atomic_write(Path(target), path.read_bytes(), path.stat().st_mode & 0o777)
            else:
                Path(target).unlink(missing_ok=True)
        command("systemctl", "--user", "daemon-reload", env=env)
        if monitor_stopped:
            # Même en cas d'échec, le moniteur de secours respecte le tunnel actif.
            with open(backup / "recovery-monitor.log", "ab") as log:
                subprocess.Popen([str(ROOT / "bin/netpulse-monitor"), "--resume-session",
                                  "--preserve-active-tunnel"], env=env, stdout=log, stderr=log,
                                 start_new_session=True)
        raise

    # Aucune ancienne fenêtre n'est fermée. GNOME Shell n'est pas rechargé.
    if guis:
        gui_unit = "netpulse-gui-live-" + str(time.time_ns())
        arguments = ["systemd-run", "--user", "--unit=" + gui_unit, "--collect"]
        arguments.extend("--setenv=" + key + "=" + env[key] for key in
                         ("DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS") if key in env)
        command(*arguments, str(BIN / "netpulse-gui"), "--new-instance", env=env)
        time.sleep(2)
        if command("systemctl", "--user", "is-active", gui_unit, env=env).strip() != "active":
            raise RuntimeError(f"L'interface mise à jour n'a pas démarré ; diagnostic : journalctl --user -u {gui_unit}")
    for gui in guis:
        if not gui.is_running():
            raise RuntimeError("Une ancienne interface a été fermée pendant la mise à jour.")
    verify_network(tunnel, identity, baseline)
    report = {"tunnel_pid": tunnel.pid, "tunnel_create_time": identity, "monitor_pid": new_pid,
              "old_gui_pids": [gui.pid for gui in guis], "routes_unchanged": True,
              "automatic_network_actions_deferred": True, "extension_reload_deferred": True}
    (backup / "result.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
