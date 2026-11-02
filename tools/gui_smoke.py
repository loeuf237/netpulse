#!/usr/bin/env python3
"""Exercise real GTK widgets with temporary data and every network action mocked."""
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ["GSETTINGS_BACKEND"] = "memory"

with tempfile.TemporaryDirectory() as temporary:
    directory = Path(temporary)
    os.environ["XDG_STATE_HOME"] = str(directory / "state")
    from netpulse import gui
    from netpulse.features import HistoryStore, ProfileStore
    store = ProfileStore(directory / "profiles.json")
    store.save({"name": "Mobile", "proxy_url": "socks5://127.0.0.1:1080",
                "split_mode": "include", "split_apps": ["browser"], "bypass_ftp": True})
    history = HistoryStore()
    history.record(time.time(), 10485760, 2097152, [("browser", 6291456, 1048576)])
    with patch.object(gui, "CONFIG_PATH", str(directory / "config.json")), \
         patch.object(gui, "SPLIT_APPS_FILE", str(directory / "apps.txt")), \
         patch.object(gui, "STATS_PATH", str(directory / "missing-stats.json")), \
         patch.object(gui, "ProfileStore", return_value=store), \
         patch.object(gui.NetPulseWindow, "_ensure_monitor_running"), \
         patch.object(gui.NetPulseWindow, "_refresh_tun_status"), \
         patch.object(gui.NetPulseWindow, "_execute_ctl_action"), \
         patch.object(gui.NetPulseWindow, "_perform_force_change"), \
         patch.object(gui.NetPulseWindow, "_activate_profile"):
        app = gui.NetPulseApp(new_instance=True)
        app.register(None)
        window = gui.NetPulseWindow(application=app)
        window.present()
        payload = {"proxy_active": True, "connection_protected": True, "network_actions_deferred": True,
                   "diagnostics": {"timestamp": time.time(), "server": {"state": "ok", "detail": "socks5://127.0.0.1:1080"},
                                   "tunnel": {"state": "ok", "detail": "Tunnel active"},
                                   "dns": {"state": "ok", "detail": "Hôte résolu"},
                                   "internet": {"state": "ok", "detail": "HTTPS: HTTP 200", "latency_ms": 85.2}},
                   "alerts": [{"id": 1, "timestamp": time.time(), "message": "Exemple d'événement enregistré", "kind": "quota"}]}
        window.latest_stats = payload
        window._apply_tun_status({"active": True, "proxy": "socks5://127.0.0.1:1080"})
        window._update_feature_status(payload)
        assert window.protection_banner.get_revealed()
        callback = Mock()
        window._confirm_network_action("Test", callback)
        window._network_dialog.response("cancel")
        callback.assert_not_called()
        window._confirm_network_action("Test", callback)
        window._network_dialog.response("apply")
        callback.assert_called_once()
        window._edit_profile(store.list()[0])
        for top in gui.Gtk.Window.get_toplevels():
            if isinstance(top, gui.Adw.MessageDialog):
                top.response("cancel")
        window._refresh_history(force=True)
        window.history_period.set_selected(1)
        window.current_processes = [
            {"pid": index + 100, "name": name, "status": "Connecté", "routing": "proxy",
             "total_rx_formatted": "10 MiB", "total_tx_formatted": "1 MiB",
             "rx_speed_formatted": "1 MiB/s", "tx_speed_formatted": "0 B/s",
             "rx_speed": 1048576, "tx_speed": 0, "is_blocked": False,
             "rule_status": {"state": state, "label": label, "detail": "Affectation observée"}}
            for index, (name, state, label) in enumerate(
                (("browser", "applied", "Applied"), ("chat", "pending", "Pending"),
                 ("download", "error", "Error")))]
        window._render_process_list()
        assert len(window.row_widgets) == 3
        for page in ("applications", "proxy", "diagnostic", "history", "settings"):
            window.view_stack.set_visible_child_name(page)
            assert window.view_stack.get_visible_child_name() == page
            deadline = time.monotonic() + 0.4
            context = gui.GLib.MainContext.default()
            while time.monotonic() < deadline:
                while context.pending():
                    context.iteration(False)
                time.sleep(0.01)
        assert "10.0 MiB" in window.history_totals_row.get_subtitle()
        window.close()
print("GTK interface verified: 5 tabs, protection, profile editor and history.")
