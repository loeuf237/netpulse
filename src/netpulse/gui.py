#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NetPulse - Moniteur Réseau & Pare-feu (GlassWire + Internet Speed Meter Lite)
Interface GTK4 / Libadwaita moderne à 3 onglets :
1. Trafic & Applications (Graphique temps réel vectoriel, Pare-feu applicatif 1-clic, Hôtes et IPs)
2. Serveur Mandataire & Forçage TUN
3. Paramètres de l'Indicateur
"""

import os
import sys
import json
import subprocess
import threading
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('Gio', '2.0')
gi.require_version('GLib', '2.0')
gi.require_version('GObject', '2.0')
gi.require_version('Gdk', '4.0')

from gi.repository import Gtk, Adw, Gio, GLib, GObject, Gdk

CONFIG_PATH = os.path.expanduser("~/.config/force-proxy/config.json")
BLOCKED_FILE = os.path.expanduser("~/.config/force-proxy/blocked_apps.txt")
STATS_PATH = "/tmp/netpulse_stats.json"


def load_config():
    default_cfg = {
        "refresh_interval": 1,
        "unit_mode": "auto",
        "show_download": True,
        "show_upload": True,
        "show_session_total": True,
        "autostart": True
    }
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return {**default_cfg, **json.load(f)}
    except Exception:
        pass
    return default_cfg


def save_config(cfg):
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        print(f"Error saving config: {e}", file=sys.stderr)


def format_bytes(b):
    if b < 1024:
        return f"{b:.0f} o"
    elif b < 1024 * 1024:
        return f"{b / 1024:.1f} Ko"
    elif b < 1024 * 1024 * 1024:
        return f"{b / (1024 * 1024):.1f} Mo"
    else:
        return f"{b / (1024 * 1024 * 1024):.2f} Go"


def format_speed(bps):
    return f"{format_bytes(bps)}/s"


def generate_svg_graph(history, width=720, height=130):
    if not history or len(history) < 2:
        return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
            <rect width="{width}" height="{height}" fill="#161821" rx="10" stroke="#262938" stroke-width="1"/>
            <text x="{width//2}" y="{height//2}" fill="#6b7280" font-family="sans-serif" font-size="12" text-anchor="middle">Acquisition du trafic en cours...</text>
        </svg>"""

    max_rate = max(max(d.get('rx', 0), d.get('tx', 0)) for d in history)
    max_rate = max(max_rate, 40 * 1024) * 1.25

    margin_l = 70
    margin_r = 15
    margin_t = 15
    margin_b = 20
    plot_w = max(width - margin_l - margin_r, 10)
    plot_h = max(height - margin_t - margin_b, 10)

    n_pts = len(history)
    step_x = plot_w / max(59, n_pts - 1)

    rx_pts = []
    tx_pts = []
    for i, d in enumerate(history):
        x = margin_l + i * step_x
        y_rx = margin_t + plot_h - (min(d.get('rx', 0), max_rate) / max_rate) * plot_h
        y_tx = margin_t + plot_h - (min(d.get('tx', 0), max_rate) / max_rate) * plot_h
        rx_pts.append((x, y_rx))
        tx_pts.append((x, y_tx))

    rx_poly = f"{margin_l},{margin_t+plot_h} " + " ".join(f"{x:.1f},{y:.1f}" for x, y in rx_pts) + f" {rx_pts[-1][0]:.1f},{margin_t+plot_h}"
    tx_poly = f"{margin_l},{margin_t+plot_h} " + " ".join(f"{x:.1f},{y:.1f}" for x, y in tx_pts) + f" {tx_pts[-1][0]:.1f},{margin_t+plot_h}"

    rx_line = " ".join(f"{x:.1f},{y:.1f}" for x, y in rx_pts)
    tx_line = " ".join(f"{x:.1f},{y:.1f}" for x, y in tx_pts)

    y_mid = margin_t + plot_h / 2.0
    top_spd = format_speed(max_rate)
    mid_spd = format_speed(max_rate / 2.0)

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
      <defs>
        <linearGradient id="gRx" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#2ecc71" stop-opacity="0.38"/>
          <stop offset="100%" stop-color="#2ecc71" stop-opacity="0.0"/>
        </linearGradient>
        <linearGradient id="gTx" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#3498db" stop-opacity="0.38"/>
          <stop offset="100%" stop-color="#3498db" stop-opacity="0.0"/>
        </linearGradient>
      </defs>

      <rect width="{width}" height="{height}" fill="#161821" rx="10" stroke="#262938" stroke-width="1"/>

      <!-- Grid lines -->
      <line x1="{margin_l}" y1="{margin_t}" x2="{width-margin_r}" y2="{margin_t}" stroke="#2e3347" stroke-width="1" stroke-dasharray="3,3"/>
      <line x1="{margin_l}" y1="{y_mid:.1f}" x2="{width-margin_r}" y2="{y_mid:.1f}" stroke="#2e3347" stroke-width="1" stroke-dasharray="3,3"/>
      <line x1="{margin_l}" y1="{margin_t+plot_h}" x2="{width-margin_r}" y2="{margin_t+plot_h}" stroke="#2e3347" stroke-width="1"/>

      <!-- Y Labels -->
      <text x="8" y="{margin_t+3}" fill="#8b949e" font-family="sans-serif" font-size="9">{top_spd}</text>
      <text x="8" y="{y_mid+3:.1f}" fill="#8b949e" font-family="sans-serif" font-size="9">{mid_spd}</text>
      <text x="8" y="{margin_t+plot_h+3}" fill="#8b949e" font-family="sans-serif" font-size="9">0 o/s</text>

      <!-- Curves -->
      <polygon points="{rx_poly}" fill="url(#gRx)"/>
      <polyline points="{rx_line}" fill="none" stroke="#2ecc71" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>

      <polygon points="{tx_poly}" fill="url(#gTx)"/>
      <polyline points="{tx_line}" fill="none" stroke="#3498db" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>

      <!-- X Labels -->
      <text x="{margin_l}" y="{height-6}" fill="#6b7280" font-family="sans-serif" font-size="9">-60s</text>
      <text x="{margin_l + plot_w*0.5:.1f}" y="{height-6}" fill="#6b7280" font-family="sans-serif" font-size="9" text-anchor="middle">-30s</text>
      <text x="{width-margin_r}" y="{height-6}" fill="#6b7280" font-family="sans-serif" font-size="9" text-anchor="end">Maintenant</text>
    </svg>"""
    return svg


class NetPulseWindow(Adw.ApplicationWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.set_title("NetPulse")
        self.set_icon_name("netpulse")
        self.set_default_size(940, 850)

        self.config = load_config()
        self.settings = Gio.Settings.new("org.gnome.system.proxy")
        self.http_settings = Gio.Settings.new("org.gnome.system.proxy.http")
        self.https_settings = Gio.Settings.new("org.gnome.system.proxy.https")
        self.socks_settings = Gio.Settings.new("org.gnome.system.proxy.socks")

        self.ctl_bin = GLib.find_program_in_path("netpulse-ctl") or GLib.find_program_in_path("force-proxy-ctl") or f"{GLib.get_home_dir()}/.local/bin/netpulse-ctl"
        self.mon_bin = GLib.find_program_in_path("netpulse-monitor") or GLib.find_program_in_path("force-proxy-monitor") or f"{GLib.get_home_dir()}/.local/bin/netpulse-monitor"

        self.updating_switch = False
        self.is_busy = False
        self.search_filter = ""
        self.filter_blocked_only = False
        self.current_processes = []
        self.history_data = []

        # Tracking state to prevent expander rows from collapsing
        self.expanded_pids = set()
        self.row_widgets = {}  # pid -> dict of widgets
        self.empty_row = None

        self._build_ui()
        self._load_gsettings()
        self._refresh_tun_status()

        # Start background monitor if not running
        self._ensure_monitor_running()

        # Polling timer for UI updates
        GLib.timeout_add_seconds(1, self._poll_stats)

    def _ensure_monitor_running(self):
        if not os.path.exists("/tmp/netpulse_monitor.pid"):
            try:
                subprocess.Popen([self.mon_bin], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass

    def _build_ui(self):
        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        toolbar_view = Adw.ToolbarView()
        self.toast_overlay.set_child(toolbar_view)

        header = Adw.HeaderBar()
        self.view_stack = Adw.ViewStack()

        switcher_title = Adw.ViewSwitcherTitle()
        switcher_title.props.stack = self.view_stack
        switcher_title.props.title = "NetPulse"
        header.set_title_widget(switcher_title)

        toolbar_view.add_top_bar(header)
        toolbar_view.set_content(self.view_stack)

        view_switcher_bar = Adw.ViewSwitcherBar()
        view_switcher_bar.set_stack(self.view_stack)
        switcher_title.bind_property("title-visible", view_switcher_bar, "reveal",
                                     GObject.BindingFlags.SYNC_CREATE)
        toolbar_view.add_bottom_bar(view_switcher_bar)

        # Build the 3 Tabs
        self._build_glasswire_tab()
        self._build_proxy_tab()
        self._build_settings_tab()

    # -----------------------------------------------------------------
    # ONGLET 1 : TRAFIC & APPLICATIONS (STYLE GLASSWIRE)
    # -----------------------------------------------------------------
    def _build_glasswire_tab(self):
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        main_box.set_margin_start(16)
        main_box.set_margin_end(16)
        main_box.set_margin_top(14)
        main_box.set_margin_bottom(14)

        # 1. Overview Cards Grid
        cards_grid = Gtk.Grid()
        cards_grid.set_column_spacing(10)
        cards_grid.set_row_spacing(10)
        cards_grid.set_hexpand(True)

        def make_card(icon_name, title, default_val, css_color):
            frame = Gtk.Frame()
            frame.add_css_class("card")
            frame.set_hexpand(True)

            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            box.set_margin_start(12)
            box.set_margin_end(12)
            box.set_margin_top(8)
            box.set_margin_bottom(8)

            top_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            icon = Gtk.Image.new_from_icon_name(icon_name)
            lbl_title = Gtk.Label(label=title, xalign=0)
            lbl_title.add_css_class("dim-label")
            lbl_title.add_css_class("caption")
            top_box.append(icon)
            top_box.append(lbl_title)

            lbl_val = Gtk.Label(label=default_val, xalign=0)
            lbl_val.add_css_class("title-3")
            if css_color:
                lbl_val.add_css_class(css_color)

            box.append(top_box)
            box.append(lbl_val)
            frame.set_child(box)
            return frame, lbl_val

        card_down, self.lbl_card_down = make_card("go-down-symbolic", "RÉCEPTION (PHYSIQUE)", "0 Ko/s", "success")
        card_up, self.lbl_card_up = make_card("go-up-symbolic", "ENVOI (PHYSIQUE)", "0 Ko/s", "accent")
        card_total, self.lbl_card_total = make_card("network-workgroup-symbolic", "TOTAL SESSION", "↓ 0 o • ↑ 0 o", None)
        card_conns, self.lbl_card_conns = make_card("network-wired-symbolic", "CONNEXIONS", "0 actives", None)

        cards_grid.attach(card_down, 0, 0, 1, 1)
        cards_grid.attach(card_up, 1, 0, 1, 1)
        cards_grid.attach(card_total, 2, 0, 1, 1)
        cards_grid.attach(card_conns, 3, 0, 1, 1)
        main_box.append(cards_grid)

        # 2. Graphique Visuel Temps Réel (Style GlassWire Vector Graph)
        graph_frame = Gtk.Frame()
        graph_frame.add_css_class("card")
        graph_frame.set_hexpand(True)

        graph_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        graph_box.set_margin_start(10)
        graph_box.set_margin_end(10)
        graph_box.set_margin_top(8)
        graph_box.set_margin_bottom(8)

        legend_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)

        lbl_graph_title = Gtk.Label(label="Activité Réseau en Direct (Dernière minute)")
        lbl_graph_title.add_css_class("heading")
        lbl_graph_title.set_hexpand(True)
        lbl_graph_title.set_xalign(0)
        legend_box.append(lbl_graph_title)

        lg_down = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        dot_down = Gtk.Label(label="●", css_classes=["success"])
        lbl_lg_down = Gtk.Label(label="Réception (↓)")
        lbl_lg_down.add_css_class("caption")
        lg_down.append(dot_down)
        lg_down.append(lbl_lg_down)
        legend_box.append(lg_down)

        lg_up = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        dot_up = Gtk.Label(label="●", css_classes=["accent"])
        lbl_lg_up = Gtk.Label(label="Envoi (↑)")
        lbl_lg_up.add_css_class("caption")
        lg_up.append(dot_up)
        lg_up.append(lbl_lg_up)
        legend_box.append(lg_up)

        graph_box.append(legend_box)

        # Vector Picture for SVG Graph
        self.graph_picture = Gtk.Picture()
        self.graph_picture.set_can_shrink(True)
        self.graph_picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        self.graph_picture.set_size_request(-1, 130)
        graph_box.append(self.graph_picture)

        graph_frame.set_child(graph_box)
        main_box.append(graph_frame)

        # 3. Filter & Search Bar + Firewall Filter
        search_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text("Filtrer par nom, PID ou hôte distant (ex: google.com, snapcraft)...")
        self.search_entry.set_hexpand(True)
        self.search_entry.connect("search-changed", self._on_search_changed)
        search_box.append(self.search_entry)

        self.btn_filter_blocked = Gtk.ToggleButton(label="Bloqués (Pare-feu)")
        self.btn_filter_blocked.set_tooltip_text("Afficher uniquement les applications bloquées par le pare-feu")
        self.btn_filter_blocked.connect("toggled", self._on_filter_blocked_toggled)
        search_box.append(self.btn_filter_blocked)

        btn_reset = Gtk.Button(icon_name="view-refresh-symbolic")
        btn_reset.set_tooltip_text("Réinitialiser les compteurs de session")
        btn_reset.connect("clicked", self._on_reset_session_clicked)
        search_box.append(btn_reset)

        main_box.append(search_box)

        # 4. Applications List (Scrolled)
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)

        self.proc_listbox = Gtk.ListBox()
        self.proc_listbox.add_css_class("boxed-list")
        self.proc_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        scrolled.set_child(self.proc_listbox)

        main_box.append(scrolled)

        self.view_stack.add_titled_with_icon(
            main_box,
            "applications",
            "Trafic & Applications",
            "utilities-system-monitor-symbolic"
        )

    def _on_search_changed(self, entry):
        self.search_filter = entry.get_text().strip().lower()
        self._render_process_list()

    def _on_filter_blocked_toggled(self, btn):
        self.filter_blocked_only = btn.get_active()
        self._render_process_list()

    def _on_reset_session_clicked(self, btn):
        try:
            subprocess.run([self.mon_bin, "--reset"], check=False)
            toast = Adw.Toast.new("Compteurs de session réinitialisés.")
            self.toast_overlay.add_toast(toast)
        except Exception:
            pass

    # -----------------------------------------------------------------
    # RENDU STABLE DES PROCESSUS SANS REFERMER LES EXPANDERS
    # -----------------------------------------------------------------
    def _render_process_list(self):
        def match_process(p):
            if self.filter_blocked_only and not p.get("is_blocked"):
                return False
            if not self.search_filter:
                return True
            q = self.search_filter
            if q in p["name"].lower() or str(p["pid"]) in q:
                return True
            for host in p.get("contacted_hosts", []):
                if q in host.lower():
                    return True
            for c in p.get("connections", []):
                if q in c.get("remote_ip", "").lower() or q in c.get("remote_host", "").lower():
                    return True
            return False

        filtered = [p for p in self.current_processes if match_process(p)]
        filtered_pids = set(p["pid"] for p in filtered)

        # Remove rows for processes that disappeared
        for pid in list(self.row_widgets.keys()):
            if pid not in filtered_pids:
                row_data = self.row_widgets.pop(pid)
                self.proc_listbox.remove(row_data["row"])

        if not filtered:
            if not self.empty_row:
                self.empty_row = Adw.ActionRow()
                self.empty_row.set_title("Aucune application correspondante")
                self.empty_row.set_subtitle("Modifiez les filtres de recherche ou vérifiez vos connexions réseau.")
                self.proc_listbox.append(self.empty_row)
            return
        elif self.empty_row:
            self.proc_listbox.remove(self.empty_row)
            self.empty_row = None

        for p in filtered:
            pid = p["pid"]
            pname = p["name"]
            is_blocked = p.get("is_blocked", False)

            hosts_list = p.get("contacted_hosts", [])
            hosts_str = ", ".join(hosts_list[:3])
            hosts_info = f" • 🌐 Hôtes : {hosts_str}" if hosts_str else ""
            subtitle_text = f"PID: {pid} • {p['status']} • Total: ↓ {p['total_rx_formatted']} | ↑ {p['total_tx_formatted']}{hosts_info}"

            # ---------------------------------------------------------
            # UPDATE EXISTING ROW IN-PLACE (DOES NOT COLLAPSE EXPANDER)
            # ---------------------------------------------------------
            if pid in self.row_widgets:
                w = self.row_widgets[pid]
                expander = w["row"]
                expander.set_subtitle(subtitle_text)

                w["down_lbl"].set_label(f"↓ {p['rx_speed_formatted']}")
                w["down_lbl"].set_css_classes(["caption", "success" if p["rx_speed"] > 1024 else "dim-label"])

                w["up_lbl"].set_label(f"↑ {p['tx_speed_formatted']}")
                w["up_lbl"].set_css_classes(["caption", "accent" if p["tx_speed"] > 1024 else "dim-label"])

                btn_block = w["btn_block"]
                if is_blocked:
                    btn_block.set_label("Bloqué")
                    btn_block.set_css_classes(["destructive-action"])
                    btn_block.set_tooltip_text(f"Cliquer pour autoriser à nouveau l'accès internet à {pname}")
                else:
                    btn_block.set_label("Bloquer")
                    btn_block.set_css_classes([])
                    btn_block.set_tooltip_text(f"Couper immédiatement tout accès internet à {pname} (Pare-feu)")

                # If expanded, update sub-rows only if connection count changed
                conns = p.get("connections", [])
                if expander.get_expanded() and len(conns) != len(w.get("sub_rows", [])):
                    for sr in w.get("sub_rows", []):
                        expander.remove(sr)
                    new_sub_rows = self._build_socket_subrows(expander, conns)
                    w["sub_rows"] = new_sub_rows

            # ---------------------------------------------------------
            # CREATE NEW ROW
            # ---------------------------------------------------------
            else:
                expander = Adw.ExpanderRow()
                expander.set_title(pname)
                expander.set_subtitle(subtitle_text)

                # Track expanded state cleanly
                expander.connect("notify::expanded", self._on_expander_toggled, pid)
                if pid in self.expanded_pids:
                    expander.set_expanded(True)

                img = Gtk.Image.new_from_icon_name(p.get("icon", "application-x-executable"))
                img.set_pixel_size(28)
                expander.add_prefix(img)

                suffix_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
                suffix_box.set_valign(Gtk.Align.CENTER)

                rate_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
                rate_box.set_valign(Gtk.Align.CENTER)

                down_lbl = Gtk.Label(label=f"↓ {p['rx_speed_formatted']}")
                down_lbl.set_css_classes(["caption", "success" if p["rx_speed"] > 1024 else "dim-label"])

                up_lbl = Gtk.Label(label=f"↑ {p['tx_speed_formatted']}")
                up_lbl.set_css_classes(["caption", "accent" if p["tx_speed"] > 1024 else "dim-label"])

                rate_box.append(down_lbl)
                rate_box.append(up_lbl)
                suffix_box.append(rate_box)

                btn_block = Gtk.Button()
                if is_blocked:
                    btn_block.set_label("Bloqué")
                    btn_block.add_css_class("destructive-action")
                    btn_block.set_tooltip_text(f"Cliquer pour autoriser à nouveau l'accès internet à {pname}")
                else:
                    btn_block.set_label("Bloquer")
                    btn_block.set_tooltip_text(f"Couper immédiatement tout accès internet à {pname} (Pare-feu)")

                btn_block.connect("clicked", self._on_toggle_app_block, pname, pid)
                suffix_box.append(btn_block)

                expander.add_suffix(suffix_box)

                # Populate socket rows inside expander
                sub_rows = self._build_socket_subrows(expander, p.get("connections", []))

                self.proc_listbox.append(expander)
                self.row_widgets[pid] = {
                    "row": expander,
                    "down_lbl": down_lbl,
                    "up_lbl": up_lbl,
                    "btn_block": btn_block,
                    "sub_rows": sub_rows
                }

    def _build_socket_subrows(self, expander, conns):
        sub_rows = []
        if conns:
            for c in conns:
                sub_row = Adw.ActionRow()
                proto = c.get("proto", "TCP")
                r_host = c.get("remote_host", "-")
                r_ip = c.get("remote_ip", "-")
                r_port = c.get("remote_port", 0)
                local = c.get("local", "-")
                status = c.get("status", "ACTIVE")

                if r_host and r_host != "-" and r_host != r_ip:
                    sub_row.set_title(f"🌐 {r_host}")
                    sub_row.set_subtitle(f"{proto} • Distant: {r_ip}:{r_port} ➔ Local: {local} • {status}")
                elif r_ip and r_ip != "-":
                    sub_row.set_title(f"🌐 {r_ip}:{r_port}")
                    sub_row.set_subtitle(f"{proto} • Local: {local} • {status}")
                else:
                    sub_row.set_title(f"{proto} : {local}")
                    sub_row.set_subtitle(f"Écoute locale ({status})")

                icon = Gtk.Image.new_from_icon_name("network-server-symbolic")
                sub_row.add_prefix(icon)
                expander.add_row(sub_row)
                sub_rows.append(sub_row)
        else:
            empty_sub = Adw.ActionRow()
            empty_sub.set_title("Aucune socket active actuellement")
            expander.add_row(empty_sub)
            sub_rows.append(empty_sub)
        return sub_rows

    def _on_expander_toggled(self, expander, param, pid):
        if expander.get_expanded():
            self.expanded_pids.add(pid)
        else:
            self.expanded_pids.discard(pid)

    def _on_toggle_app_block(self, btn, app_name, pid):
        w = self.row_widgets.get(pid)
        currently_blocked = False
        if w and w["btn_block"].get_label() == "Bloqué":
            currently_blocked = True

        action = "unblock-app" if currently_blocked else "block-app"
        try:
            subprocess.run([self.ctl_bin, action, app_name], check=False)
            if not currently_blocked:
                toast = Adw.Toast.new(f"Application « {app_name} » bloquée par le pare-feu.")
            else:
                toast = Adw.Toast.new(f"Application « {app_name} » débloquée.")
            self.toast_overlay.add_toast(toast)
            self._poll_stats()
        except Exception as e:
            print(f"Error toggling block: {e}", file=sys.stderr)

    # -----------------------------------------------------------------
    # ONGLET 2 : SERVEUR MANDATAIRE & FORÇAGE TUN
    # -----------------------------------------------------------------
    def _build_proxy_tab(self):
        page = Adw.PreferencesPage()

        # Groupe 1 : Forçage Global
        group_force = Adw.PreferencesGroup()
        group_force.set_title("Forçage global du système (Mode TUN)")
        group_force.set_description(
            "Redirige 100% du trafic réseau de toutes les applications de ce PC vers votre proxy, "
            "y compris les applications qui ignorent les proxys standards (terminaux, snap-store, jeux, daemons)."
        )
        page.add(group_force)

        self.force_switch_row = Adw.SwitchRow()
        self.force_switch_row.set_title("Forcer toutes les applications du PC")
        self.force_switch_row.set_subtitle("Interception réseau niveau noyau via interface virtuelle TUN")
        self.force_switch_row.connect("notify::active", self._on_force_switch_toggled)
        group_force.add(self.force_switch_row)

        self.tun_status_row = Adw.ActionRow()
        self.tun_status_row.set_title("État du routage global")
        self.tun_status_row.set_subtitle("Vérification en cours...")
        self.tun_badge = Gtk.Label(label="Inactif", css_classes=["dim-label"])
        self.tun_status_row.add_suffix(self.tun_badge)
        group_force.add(self.tun_status_row)

        # Groupe 2 : Paramètres Proxy GNOME
        group_proxy = Adw.PreferencesGroup()
        group_proxy.set_title("Configuration du serveur mandataire")
        page.add(group_proxy)

        self.enable_proxy_row = Adw.SwitchRow()
        self.enable_proxy_row.set_title("Serveur mandataire du réseau")
        self.enable_proxy_row.connect("notify::active", self._on_proxy_enable_toggled)
        group_proxy.add(self.enable_proxy_row)

        # SOCKS
        self.socks_host_entry = Adw.EntryRow()
        self.socks_host_entry.set_title("Hôte SOCKS")
        group_proxy.add(self.socks_host_entry)

        self.socks_port_spin = Adw.SpinRow.new_with_range(1, 65535, 1)
        self.socks_port_spin.set_title("Port SOCKS")
        group_proxy.add(self.socks_port_spin)

        # HTTP
        self.http_host_entry = Adw.EntryRow()
        self.http_host_entry.set_title("Hôte HTTP")
        group_proxy.add(self.http_host_entry)

        self.http_port_spin = Adw.SpinRow.new_with_range(1, 65535, 1)
        self.http_port_spin.set_title("Port HTTP")
        group_proxy.add(self.http_port_spin)

        # HTTPS
        self.https_host_entry = Adw.EntryRow()
        self.https_host_entry.set_title("Hôte HTTPS")
        group_proxy.add(self.https_host_entry)

        self.https_port_spin = Adw.SpinRow.new_with_range(1, 65535, 1)
        self.https_port_spin.set_title("Port HTTPS")
        group_proxy.add(self.https_port_spin)

        # Ignored Hosts
        self.ignore_entry = Adw.EntryRow()
        self.ignore_entry.set_title("Hôtes ignorés")
        group_proxy.add(self.ignore_entry)

        # Groupe 3 : Actions
        group_actions = Adw.PreferencesGroup()
        group_actions.set_title("Actions")
        page.add(group_actions)

        save_row = Adw.ActionRow()
        save_row.set_title("Enregistrer la configuration")
        save_row.set_subtitle("Met à jour les paramètres système GNOME")
        save_btn = Gtk.Button(label="Enregistrer", css_classes=["suggested-action"])
        save_btn.connect("clicked", lambda b: self._save_gsettings(show_toast=True))
        save_row.add_suffix(save_btn)
        group_actions.add(save_row)

        self.view_stack.add_titled_with_icon(
            page,
            "proxy",
            "Serveur Mandataire",
            "network-vpn-symbolic"
        )

    # -----------------------------------------------------------------
    # ONGLET 3 : PARAMÈTRES DE L'INDICATEUR (SPEED METER)
    # -----------------------------------------------------------------
    def _build_settings_tab(self):
        page = Adw.PreferencesPage()

        grp_display = Adw.PreferencesGroup()
        grp_display.set_title("Affichage dans la barre supérieure")
        grp_display.set_description("Personnalisez les informations visibles directement dans le panneau supérieur.")
        page.add(grp_display)

        self.sw_show_down = Adw.SwitchRow()
        self.sw_show_down.set_title("Afficher le débit de réception (↓)")
        self.sw_show_down.set_active(self.config.get("show_download", True))
        self.sw_show_down.connect("notify::active", self._on_indicator_setting_changed)
        grp_display.add(self.sw_show_down)

        self.sw_show_up = Adw.SwitchRow()
        self.sw_show_up.set_title("Afficher le débit d'envoi (↑)")
        self.sw_show_up.set_active(self.config.get("show_upload", True))
        self.sw_show_up.connect("notify::active", self._on_indicator_setting_changed)
        grp_display.add(self.sw_show_up)

        self.row_units = Adw.ComboRow()
        self.row_units.set_title("Format des unités de débit")
        unit_model = Gtk.StringList()
        unit_model.append("Automatique en octets (Ko/s, Mo/s)")
        unit_model.append("En bits réseau (Kbps, Mbps)")
        self.row_units.set_model(unit_model)
        self.row_units.set_selected(1 if self.config.get("unit_mode") == "bits" else 0)
        self.row_units.connect("notify::selected", self._on_indicator_setting_changed)
        grp_display.add(self.row_units)

        self.row_interval = Adw.ComboRow()
        self.row_interval.set_title("Fréquence de rafraîchissement")
        int_model = Gtk.StringList()
        int_model.append("1 seconde (Temps réel fluide)")
        int_model.append("2 secondes")
        int_model.append("3 secondes (Économie d'énergie)")
        self.row_interval.set_model(int_model)
        cur_int = self.config.get("refresh_interval", 1)
        self.row_interval.set_selected(cur_int - 1 if 1 <= cur_int <= 3 else 0)
        self.row_interval.connect("notify::selected", self._on_indicator_setting_changed)
        grp_display.add(self.row_interval)

        grp_sys = Adw.PreferencesGroup()
        grp_sys.set_title("Système")
        page.add(grp_sys)

        self.sw_autostart = Adw.SwitchRow()
        self.sw_autostart.set_title("Démarrer le moniteur automatiquement avec la session")
        self.sw_autostart.set_subtitle("Géré par le service d'arrière-plan systemd utilisateur")
        self.sw_autostart.set_active(self.config.get("autostart", True))
        self.sw_autostart.connect("notify::active", self._on_autostart_changed)
        grp_sys.add(self.sw_autostart)

        self.view_stack.add_titled_with_icon(
            page,
            "settings",
            "Paramètres Indicateur",
            "preferences-other-symbolic"
        )

    def _on_indicator_setting_changed(self, *args):
        self.config["show_download"] = self.sw_show_down.get_active()
        self.config["show_upload"] = self.sw_show_up.get_active()
        self.config["unit_mode"] = "bits" if self.row_units.get_selected() == 1 else "auto"
        self.config["refresh_interval"] = self.row_interval.get_selected() + 1
        save_config(self.config)

    def _on_autostart_changed(self, row, param):
        enabled = self.sw_autostart.get_active()
        self.config["autostart"] = enabled
        save_config(self.config)
        action = "enable" if enabled else "disable"
        try:
            subprocess.run(["systemctl", "--user", action, "force-proxy-monitor.service"], check=False)
        except Exception:
            pass

    # -----------------------------------------------------------------
    # DONNÉES EN TEMPS RÉEL (POLLING & GRAPH UPDATE)
    # -----------------------------------------------------------------
    def _poll_stats(self):
        if not self.is_busy:
            self._refresh_tun_status()

        if os.path.exists(STATS_PATH):
            try:
                with open(STATS_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)

                rx_fmt = data.get("rx_speed_formatted", "0 o/s")
                tx_fmt = data.get("tx_speed_formatted", "0 o/s")
                tot_rx = data.get("session_rx_formatted", "0 o")
                tot_tx = data.get("session_tx_formatted", "0 o")
                conns_cnt = data.get("active_connections_count", 0)

                self.lbl_card_down.set_label(rx_fmt)
                self.lbl_card_up.set_label(tx_fmt)
                self.lbl_card_total.set_label(f"↓ {tot_rx} • ↑ {tot_tx}")
                self.lbl_card_conns.set_label(f"{conns_cnt} sockets")

                # Update live SVG graph
                self.history_data = data.get("history", [])
                svg_data = generate_svg_graph(self.history_data, width=720, height=130)
                bytes_data = GLib.Bytes.new(svg_data.encode("utf-8"))
                tex = Gdk.Texture.new_from_bytes(bytes_data)
                self.graph_picture.set_paintable(tex)

                self.current_processes = data.get("processes", [])
                self._render_process_list()
            except Exception:
                pass

        return GLib.SOURCE_CONTINUE

    # -----------------------------------------------------------------
    # LOGIQUE PROXY & TUN
    # -----------------------------------------------------------------
    def _load_gsettings(self):
        mode = self.settings.get_string("mode")
        self.enable_proxy_row.set_active(mode == "manual")

        socks_h = self.socks_settings.get_string("host")
        socks_p = self.socks_settings.get_int("port")
        self.socks_host_entry.set_text(socks_h)
        self.socks_port_spin.set_value(socks_p if socks_p > 0 else 1080)

        http_h = self.http_settings.get_string("host")
        http_p = self.http_settings.get_int("port")
        self.http_host_entry.set_text(http_h)
        self.http_port_spin.set_value(http_p if http_p > 0 else 8080)

        https_h = self.https_settings.get_string("host")
        https_p = self.https_settings.get_int("port")
        self.https_host_entry.set_text(https_h)
        self.https_port_spin.set_value(https_p if https_p > 0 else 8080)

        ignore = self.settings.get_strv("ignore-hosts")
        self.ignore_entry.set_text(", ".join(ignore))

    def _save_gsettings(self, show_toast=False):
        try:
            if self.enable_proxy_row.get_active():
                self.settings.set_string("mode", "manual")
            else:
                self.settings.set_string("mode", "none")

            self.socks_settings.set_string("host", self.socks_host_entry.get_text().strip())
            self.socks_settings.set_int("port", int(self.socks_port_spin.get_value()))

            self.http_settings.set_string("host", self.http_host_entry.get_text().strip())
            self.http_settings.set_int("port", int(self.http_port_spin.get_value()))

            self.https_settings.set_string("host", self.https_host_entry.get_text().strip())
            self.https_settings.set_int("port", int(self.https_port_spin.get_value()))

            raw_ignore = [x.strip() for x in self.ignore_entry.get_text().split(",") if x.strip()]
            if raw_ignore:
                self.settings.set_strv("ignore-hosts", raw_ignore)

            if show_toast:
                toast = Adw.Toast.new("Paramètres du serveur mandataire enregistrés.")
                self.toast_overlay.add_toast(toast)
        except Exception as e:
            print(f"Error saving gsettings: {e}", file=sys.stderr)

    def _on_proxy_enable_toggled(self, row, param):
        if not self.enable_proxy_row.get_active() and self.force_switch_row.get_active():
            self.force_switch_row.set_active(False)

    def _on_force_switch_toggled(self, row, param):
        if self.updating_switch or self.is_busy:
            return

        want_active = self.force_switch_row.get_active()
        self._save_gsettings(show_toast=False)

        action = "start" if want_active else "stop"
        self.is_busy = True
        self.tun_status_row.set_subtitle("Activation du mode TUN..." if want_active else "Désactivation...")

        def run_action():
            try:
                subprocess.run([self.ctl_bin, action], check=False)
            finally:
                def finish():
                    self.is_busy = False
                    self._refresh_tun_status()
                GLib.idle_add(finish)

        threading.Thread(target=run_action, daemon=True).start()

    def _refresh_tun_status(self):
        if self.is_busy:
            return
        try:
            res = subprocess.run([self.ctl_bin, "status", "--json"], capture_output=True, text=True, timeout=2)
            if res.stdout:
                data = json.loads(res.stdout)
                is_active = bool(data.get("active"))
                proxy_target = data.get("proxy", "Inconnu")

                if self.force_switch_row.get_active() != is_active:
                    self.updating_switch = True
                    self.force_switch_row.set_active(is_active)
                    self.updating_switch = False

                if is_active:
                    self.tun_status_row.set_subtitle(f"Toutes les applications sont routées vers {proxy_target}")
                    self.tun_badge.set_label("Actif (TUN)")
                    self.tun_badge.set_css_classes(["success", "heading"])
                else:
                    self.tun_status_row.set_subtitle("Le trafic réseau emprunte le chemin normal (par application)")
                    self.tun_badge.set_label("Inactif")
                    self.tun_badge.set_css_classes(["dim-label"])
        except Exception:
            pass


class NetPulseApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id="org.antigravity.NetPulse",
                         flags=Gio.ApplicationFlags.FLAGS_NONE)

    def do_activate(self):
        Gtk.Window.set_default_icon_name("netpulse")
        win = self.props.active_window
        if not win:
            win = NetPulseWindow(application=self)
        win.present()


def main():
    app = NetPulseApp()
    sys.exit(app.run(sys.argv))


if __name__ == "__main__":
    main()
