#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NetPulse Monitor Daemon (GlassWire + Internet Speed Meter Engine)
- Mesure le débit global sur l'interface physique réelle (ex: wlp0s20f3) pour éviter le double/triple comptage avec TUN et loopback.
- Extrait les statistiques réseau réelles de chaque socket par PID via tcp_info (ss -tipn).
- Résolution asynchrone DNS inverse pour afficher les adresses IP ET les noms d'hôtes de serveurs.
- Surveillance du pare-feu applicatif (application killswitch).
- Publication StatusNotifierItem (icône système / notifications) et fichier JSON.
"""

import os
import sys
import time
import json
import socket
import subprocess
import signal
import threading
import re
from collections import deque
import psutil

import gi
gi.require_version('Gio', '2.0')
gi.require_version('GLib', '2.0')
gi.require_version('Dbusmenu', '0.4')
from gi.repository import Gio, GLib, Dbusmenu

CONFIG_DIR = os.path.expanduser("~/.config/force-proxy")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
BLOCKED_FILE = os.path.join(CONFIG_DIR, "blocked_apps.txt")
STATS_PATH = "/tmp/netpulse_stats.json"
RESET_FLAG_PATH = "/tmp/netpulse_reset_flag"
PID_FILE = "/tmp/netpulse_monitor.pid"
CTL_BIN = os.path.expanduser("~/.local/bin/netpulse-ctl") if os.path.exists(os.path.expanduser("~/.local/bin/netpulse-ctl")) else os.path.expanduser("~/.local/bin/force-proxy-ctl")
GUI_BIN = os.path.expanduser("~/.local/bin/netpulse-gui") if os.path.exists(os.path.expanduser("~/.local/bin/netpulse-gui")) else os.path.expanduser("~/.local/bin/force-proxy-gui")

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
    "refresh_interval": 1,
    "unit_mode": "auto",
    "show_download": True,
    "show_upload": True,
    "show_session_total": True,
    "autostart": True
}


def get_physical_interface():
    """Détecte l'interface réseau physique réelle (passerelle par défaut)."""
    try:
        out = subprocess.check_output(['ip', '-4', 'route', 'show', 'default'], text=True)
        parts = out.split()
        if 'dev' in parts:
            idx = parts.index('dev')
            dev = parts[idx + 1]
            if dev != 'tun-proxy' and dev != 'lo':
                return dev
    except Exception:
        pass
    for nic in psutil.net_io_counters(pernic=True).keys():
        if nic != 'lo' and not nic.startswith('tun'):
            return nic
    return 'wlp0s20f3'


def load_config():
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return {**DEFAULT_CONFIG, **json.load(f)}
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
            return f"{b:.0f} o"
        elif b < 1024 * 1024:
            return f"{b / 1024:.1f} Ko"
        elif b < 1024 * 1024 * 1024:
            return f"{b / (1024 * 1024):.1f} Mo"
        else:
            return f"{b / (1024 * 1024 * 1024):.2f} Go"


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


def resolve_icon(name):
    lower = name.lower()
    if "chrome" in lower:
        return "google-chrome"
    elif "edge" in lower or "msedge" in lower:
        return "microsoft-edge"
    elif "firefox" in lower:
        return "firefox"
    elif "telegram" in lower:
        return "org.telegram.desktop"
    elif "steam" in lower:
        return "steam"
    elif "antigravity" in lower:
        return "antigravity-ide"
    elif "code" in lower or "vscode" in lower:
        return "code"
    elif "snap-store" in lower or "app-center" in lower:
        return "snap-store"
    elif "vlc" in lower:
        return "vlc"
    elif "python" in lower:
        return "text-x-python"
    elif "bash" in lower or "sh" in lower or "ptyxis" in lower:
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
    if not ip or ip == "-" or ip.startswith("127.") or ip.startswith("0.0.") or ip.startswith("::") or ip == "localhost":
        return
    with DNS_LOCK:
        if ip in DNS_CACHE or ip in PENDING_DNS:
            return
        PENDING_DNS.add(ip)

    def worker():
        try:
            host = socket.gethostbyaddr(ip)[0]
        except Exception:
            host = ip
        with DNS_LOCK:
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
        out = subprocess.check_output(['ss', '-tipn'], text=True)
    except Exception:
        return {}

    lines = out.splitlines()
    proc_bytes = {}
    cur_pids = []

    for line in lines:
        if line.startswith('ESTAB') or line.startswith('CLOSE-WAIT'):
            pids = re.findall(r'pid=(\d+)', line)
            names = re.findall(r'\"([^\"]+)\"', line)
            cur_pids = list(zip(pids, names)) if pids else []
        elif cur_pids and ('bytes_sent:' in line or 'bytes_received:' in line):
            bs_m = re.search(r'bytes_sent:(\d+)', line)
            br_m = re.search(r'bytes_received:(\d+)', line)
            bs = int(bs_m.group(1)) if bs_m else 0
            br = int(br_m.group(1)) if br_m else 0
            for pid_str, name in cur_pids:
                pid = int(pid_str)
                prev = proc_bytes.get(pid, {'name': name, 'sent': 0, 'recv': 0})
                prev['sent'] += bs
                prev['recv'] += br
                proc_bytes[pid] = prev

    return proc_bytes


class NetPulseEngine:
    def __init__(self):
        self.config = load_config()
        self.physical_if = get_physical_interface()

        self.session_start = time.time()
        self.last_time = self.session_start

        # Measure starting bytes strictly on physical interface
        cur_pernic = psutil.net_io_counters(pernic=True)
        self.last_phys_io = cur_pernic.get(self.physical_if) or psutil.net_io_counters()

        self.session_rx = 0
        self.session_tx = 0

        # Per-process tracking: pid -> {'last_recv': int, 'last_sent': int, 'tot_rx': int, 'tot_tx': int}
        self.proc_traffic_history = {}
        self.proxy_active = False

        # Bandwidth history buffer: 60 data points (60 seconds)
        self.history = deque(maxlen=60)

        self.cur_rx_formatted = "0 o/s"
        self.cur_tx_formatted = "0 o/s"
        self.cur_tot_rx_formatted = "0 o"
        self.cur_tot_tx_formatted = "0 o"
        self.cur_duration_str = "00m 00s"

        # Initialize firewall rules
        self._init_firewall()

        # DBus setup
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self._init_dbus_sni()

    def _init_firewall(self):
        try:
            subprocess.Popen([CTL_BIN, "firewall-init"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    def reset_session(self):
        self.session_start = time.time()
        self.session_rx = 0
        self.session_tx = 0
        self.proc_traffic_history.clear()
        self.history.clear()
        if os.path.exists(RESET_FLAG_PATH):
            try:
                os.remove(RESET_FLAG_PATH)
            except Exception:
                pass

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
                    f"📥 Réception : {self.cur_rx_formatted}\n"
                    f"📤 Envoi : {self.cur_tx_formatted}\n"
                    f"📊 Session : ↓ {self.cur_tot_rx_formatted} | ↑ {self.cur_tot_tx_formatted}\n"
                    f"⏱️ Durée : {self.cur_duration_str}"
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
        self.menu_server = Dbusmenu.Server.new("/MenuBar")
        self.menu_root = Dbusmenu.Menuitem.new()

        self.mi_down = Dbusmenu.Menuitem.new()
        self.mi_down.property_set("label", "📥 Réception : 0 o/s")
        self.mi_down.property_set_bool("enabled", False)
        self.menu_root.child_append(self.mi_down)

        self.mi_up = Dbusmenu.Menuitem.new()
        self.mi_up.property_set("label", "📤 Envoi : 0 o/s")
        self.mi_up.property_set_bool("enabled", False)
        self.menu_root.child_append(self.mi_up)

        sep1 = Dbusmenu.Menuitem.new()
        sep1.property_set("type", "separator")
        self.menu_root.child_append(sep1)

        self.mi_tot_rx = Dbusmenu.Menuitem.new()
        self.mi_tot_rx.property_set("label", "Total reçu : 0 o")
        self.mi_tot_rx.property_set_bool("enabled", False)
        self.menu_root.child_append(self.mi_tot_rx)

        self.mi_tot_tx = Dbusmenu.Menuitem.new()
        self.mi_tot_tx.property_set("label", "Total envoyé : 0 o")
        self.mi_tot_tx.property_set_bool("enabled", False)
        self.menu_root.child_append(self.mi_tot_tx)

        self.mi_dur = Dbusmenu.Menuitem.new()
        self.mi_dur.property_set("label", "Durée : 00:00")
        self.mi_dur.property_set_bool("enabled", False)
        self.menu_root.child_append(self.mi_dur)

        sep2 = Dbusmenu.Menuitem.new()
        sep2.property_set("type", "separator")
        self.menu_root.child_append(sep2)

        self.mi_proxy = Dbusmenu.Menuitem.new()
        self.mi_proxy.property_set("label", "⚡ Forcer le Proxy (Mode TUN) : Inactif")
        self.mi_proxy.connect("item-activated", lambda mi, ts: self.toggle_proxy())
        self.menu_root.child_append(self.mi_proxy)

        sep3 = Dbusmenu.Menuitem.new()
        sep3.property_set("type", "separator")
        self.menu_root.child_append(sep3)

        mi_open = Dbusmenu.Menuitem.new()
        mi_open.property_set("label", "🖥️ Ouvrir NetPulse...")
        mi_open.connect("item-activated", lambda mi, ts: self.open_gui())
        self.menu_root.child_append(mi_open)

        mi_reset = Dbusmenu.Menuitem.new()
        mi_reset.property_set("label", "🔄 Réinitialiser les compteurs de session")
        mi_reset.connect("item-activated", lambda mi, ts: self.reset_session())
        self.menu_root.child_append(mi_reset)

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
        except Exception as e:
            print(f"Watcher registration warning: {e}", file=sys.stderr)

    def open_gui(self):
        try:
            subprocess.Popen([GUI_BIN], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    def toggle_proxy(self):
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
                proxy_name = data.get("proxy", "TUN")
                if self.proxy_active:
                    self.mi_proxy.property_set("label", f"⚡ Forcer le Proxy : ACTIF ({proxy_name})")
                else:
                    self.mi_proxy.property_set("label", "⚡ Forcer le Proxy (Mode TUN) : Inactif")

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
        dt = max(now - self.last_time, 0.001)

        # -------------------------------------------------------------
        # 1. Global network I/O: STRICTLY ON PHYSICAL INTERFACE
        # (Avoids double/triple counting tun-proxy and loopback)
        # -------------------------------------------------------------
        cur_pernic = psutil.net_io_counters(pernic=True)
        cur_phys_io = cur_pernic.get(self.physical_if)
        if not cur_phys_io:
            self.physical_if = get_physical_interface()
            cur_phys_io = cur_pernic.get(self.physical_if) or psutil.net_io_counters()

        rx_diff = max(cur_phys_io.bytes_recv - self.last_phys_io.bytes_recv, 0)
        tx_diff = max(cur_phys_io.bytes_sent - self.last_phys_io.bytes_sent, 0)

        rx_speed = rx_diff / dt
        tx_speed = tx_diff / dt

        self.session_rx += rx_diff
        self.session_tx += tx_diff

        self.last_phys_io = cur_phys_io
        self.last_time = now

        # Add to historical buffer for graph
        self.history.append({
            "rx": rx_speed,
            "tx": tx_speed,
            "t": now
        })

        # Reload config and blocked apps list
        self.config = load_config()
        unit_mode = self.config.get("unit_mode", "auto")
        blocked_apps = load_blocked_apps()

        session_duration = max(int(now - self.session_start), 1)

        self.cur_rx_formatted = format_speed(rx_speed, unit_mode)
        self.cur_tx_formatted = format_speed(tx_speed, unit_mode)
        self.cur_tot_rx_formatted = format_bytes(self.session_rx, unit_mode)
        self.cur_tot_tx_formatted = format_bytes(self.session_tx, unit_mode)
        self.cur_duration_str = format_duration(session_duration)

        # -------------------------------------------------------------
        # 2. Extract Real Network Sockets Traffic Per PID (ss -tipn)
        # -------------------------------------------------------------
        current_socket_traffic = parse_socket_traffic()

        # Update per-process rates and cumulative session stats
        proc_live_rates = {}
        for pid, sinfo in current_socket_traffic.items():
            hist = self.proc_traffic_history.get(pid, {
                'last_recv': sinfo['recv'],
                'last_sent': sinfo['sent'],
                'tot_rx': 0,
                'tot_tx': 0
            })

            # Calculate byte delta since last check
            p_rx_diff = max(sinfo['recv'] - hist['last_recv'], 0)
            p_tx_diff = max(sinfo['sent'] - hist['last_sent'], 0)

            p_rx_speed = p_rx_diff / dt
            p_tx_speed = p_tx_diff / dt

            p_tot_rx = hist['tot_rx'] + p_rx_diff
            p_tot_tx = hist['tot_tx'] + p_tx_diff

            self.proc_traffic_history[pid] = {
                'last_recv': sinfo['recv'],
                'last_sent': sinfo['sent'],
                'tot_rx': p_tot_rx,
                'tot_tx': p_tot_tx
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
        current_pids = set(grouped_conns.keys())

        # Clean terminated processes from history
        for pid in list(self.proc_traffic_history.keys()):
            if pid not in current_pids:
                del self.proc_traffic_history[pid]

        # Read currently blocked cgroup PIDs
        cgroup_blocked_pids = set()
        try:
            if os.path.exists("/sys/fs/cgroup/net_blocked/cgroup.procs"):
                with open("/sys/fs/cgroup/net_blocked/cgroup.procs", "r") as f:
                    cgroup_blocked_pids = set(int(line.strip()) for line in f if line.strip())
        except Exception:
            pass

        for pid, c_list in grouped_conns.items():
            try:
                proc = psutil.Process(pid)
                pname = proc.name()
                cmdline = " ".join(proc.cmdline()[:3]) if proc.cmdline() else pname

                is_app_blocked = (pname.lower() in blocked_apps) or (pid in cgroup_blocked_pids)
                if pname.lower() in blocked_apps and pid not in cgroup_blocked_pids:
                    subprocess.Popen([CTL_BIN, "block", str(pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

                # Real socket rates
                prate = proc_live_rates.get(pid, {'rx_speed': 0.0, 'tx_speed': 0.0, 'tot_rx': 0, 'tot_tx': 0})
                p_rx_speed = prate['rx_speed']
                p_tx_speed = prate['tx_speed']
                p_tot_rx = prate['tot_rx']
                p_tot_tx = prate['tot_tx']

                statuses = set(c.status for c in c_list if c.status)
                if is_app_blocked:
                    status_text = "🚫 Bloqué (Pare-feu)"
                elif "ESTABLISHED" in statuses:
                    status_text = f"Connecté ({len(c_list)})"
                elif "LISTEN" in statuses:
                    status_text = "En écoute"
                elif statuses:
                    status_text = f"{list(statuses)[0]} ({len(c_list)})"
                else:
                    status_text = f"Actif ({len(c_list)})"

                # Detailed socket connections list & DNS reverse resolution
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
                    "name": pname,
                    "cmdline": cmdline,
                    "icon": resolve_icon(pname),
                    "is_blocked": is_app_blocked,
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

        # Sort by live rate, then total transferred, then connections count
        process_list.sort(key=lambda x: (x["rx_speed"] + x["tx_speed"], x["total_rx"] + x["total_tx"], x["connections_count"]), reverse=True)

        payload = {
            "timestamp": now,
            "session_start": self.session_start,
            "session_duration_sec": session_duration,
            "physical_interface": self.physical_if,
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

        # Save JSON atomically
        tmp_target = f"{STATS_PATH}.tmp"
        try:
            with open(tmp_target, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            os.replace(tmp_target, STATS_PATH)
        except Exception as e:
            print(f"Error saving stats: {e}", file=sys.stderr)

        # Update DBus menu
        self.mi_down.property_set("label", f"📥 Réception : {self.cur_rx_formatted}")
        self.mi_up.property_set("label", f"📤 Envoi : {self.cur_tx_formatted}")
        self.mi_tot_rx.property_set("label", f"Total reçu : {self.cur_tot_rx_formatted}")
        self.mi_tot_tx.property_set("label", f"Total envoyé : {self.cur_tot_tx_formatted}")
        self.mi_dur.property_set("label", f"Durée de session : {self.cur_duration_str}")

        self.check_proxy_status()

        # Emit NewToolTip
        try:
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
                os.remove(PID_FILE)
            except Exception:
                pass
            sys.exit(0)

        signal.signal(signal.SIGTERM, handle_term)
        signal.signal(signal.SIGINT, handle_term)

        interval = max(self.config.get("refresh_interval", 1), 1)
        GLib.timeout_add_seconds(interval, self.collect)
        self.collect()

        loop = GLib.MainLoop()
        loop.run()


def main():
    if "--reset" in sys.argv:
        with open(RESET_FLAG_PATH, "w") as f:
            f.write("1")
        print("Demande de réinitialisation envoyée au moniteur.")
        sys.exit(0)

    engine = NetPulseEngine()
    engine.run()


if __name__ == "__main__":
    main()
