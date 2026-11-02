import importlib.util
import json
import tempfile
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
spec = importlib.util.spec_from_file_location('netpulse_gui_test', ROOT / 'src/netpulse/gui.py')
gui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gui)


class GuiTests(unittest.TestCase):
    def test_protected_action_waits_for_explicit_response_and_cancel_does_not_execute(self):
        fake = SimpleNamespace(config={"connection_protected": True}, latest_stats={"proxy_active": True},
                               _last_tun_active=True, _network_dialog=None, _closed=False, _poll_stats=Mock())
        callback, dialog = Mock(), Mock()
        with patch.object(gui.Adw.MessageDialog, "new", return_value=dialog):
            gui.NetPulseWindow._confirm_network_action(fake, "Changer le réseau", callback)
        callback.assert_not_called()
        response = dialog.connect.call_args.args[1]
        response(dialog, "cancel")
        callback.assert_not_called()
        self.assertIsNone(fake._network_dialog)

    def test_protected_action_executes_only_after_apply_response(self):
        fake = SimpleNamespace(config={"connection_protected": True}, latest_stats={"proxy_active": True},
                               _last_tun_active=True, _network_dialog=None, _closed=False, _poll_stats=Mock())
        callback, dialog = Mock(), Mock()
        with patch.object(gui.Adw.MessageDialog, "new", return_value=dialog):
            gui.NetPulseWindow._confirm_network_action(fake, "Changer le réseau", callback)
        dialog.connect.call_args.args[1](dialog, "apply")
        callback.assert_called_once()

    def test_profile_activation_is_confirmed_even_with_inactive_tunnel(self):
        fake = SimpleNamespace(config={"connection_protected": False}, latest_stats={"proxy_active": False},
                               _last_tun_active=False, _network_dialog=None, _closed=False, _poll_stats=Mock())
        callback = Mock()
        with patch.object(gui.Adw.MessageDialog, "new", return_value=Mock()):
            gui.NetPulseWindow._confirm_network_action(fake, "Profil", callback, always=True)
        callback.assert_not_called()

    def test_new_instance_does_not_replace_existing_application(self):
        app = gui.NetPulseApp(new_instance=True)
        self.assertTrue(app.get_flags() & gui.Gio.ApplicationFlags.NON_UNIQUE)

    def test_svg_renders_without_display_or_image_loader_process(self):
        for history in ([], [{'t': 10, 'rx': 200, 'tx': 10}, {'t': 13, 'rx': 400, 'tx': 20}]):
            texture = gui.render_svg_texture(gui.generate_svg_graph(history), 720, 130)
            self.assertEqual((texture.get_width(), texture.get_height()), (720, 130))

    def test_graph_latest_sample_is_at_now_even_before_sixty_samples(self):
        svg = gui.generate_svg_graph([{'t': 10, 'rx': 10, 'tx': 0}, {'t': 13, 'rx': 20, 'tx': 0}])
        self.assertIn('705.0,', svg)
        self.assertIn('673.2,', svg)

    def test_search_accepts_partial_pid_and_rejects_query_containing_pid(self):
        process = {'pid': 12345, 'name': 'browser', 'status': 'Connected', 'total_rx_formatted': '0 B',
                   'total_tx_formatted': '0 B', 'rx_speed_formatted': '0 B/s', 'tx_speed_formatted': '0 B/s',
                   'rx_speed': 0, 'tx_speed': 0}
        fake = SimpleNamespace(filter_blocked_only=False, search_filter='123', current_processes=[process],
                               row_widgets={12345: {'row': Mock(), 'down_lbl': Mock(), 'up_lbl': Mock(),
                                                  'btn_block': Mock(), 'connections': []}},
                               empty_row=None, proc_listbox=Mock())
        with patch.object(gui.Adw, 'ActionRow', return_value=Mock()):
            gui.NetPulseWindow._render_process_list(fake)
        self.assertIn(12345, fake.row_widgets)
        fake.search_filter = '9123459'
        with patch.object(gui.Adw, 'ActionRow', return_value=Mock()):
            gui.NetPulseWindow._render_process_list(fake)
        self.assertNotIn(12345, fake.row_widgets)

    def test_connection_details_refresh_when_same_count_changes(self):
        old = [{'remote_host': '198.51.100.1'}]
        new = [{'remote_host': 'server.example'}]
        process = {'pid': 42, 'name': 'browser', 'status': 'Connected', 'connections': new,
                   'total_rx_formatted': '0 B', 'total_tx_formatted': '0 B', 'rx_speed_formatted': '0 B/s',
                   'tx_speed_formatted': '0 B/s', 'rx_speed': 0, 'tx_speed': 0}
        fake = SimpleNamespace(filter_blocked_only=False, search_filter='', current_processes=[process],
                               row_widgets={42: {'row': Mock(), 'down_lbl': Mock(), 'up_lbl': Mock(),
                                                  'btn_block': Mock(), 'connections': old, 'sub_rows': [Mock()]}},
                               empty_row=None, proc_listbox=Mock(), _build_socket_subrows=Mock(return_value=[Mock()]))
        gui.NetPulseWindow._render_process_list(fake)
        fake._build_socket_subrows.assert_called_once_with(fake.row_widgets[42]['row'], new)

    def test_config_patch_preserves_routing_and_atomic_failure(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(gui, 'CONFIG_PATH', str(Path(directory) / 'config.json')):
            path = Path(gui.CONFIG_PATH)
            path.write_text('{"split_tunnel_mode":"exclude","custom":"keep"}')
            self.assertTrue(gui.save_config({'refresh_interval': 3}))
            self.assertEqual(json.loads(path.read_text())['split_tunnel_mode'], 'exclude')
            original = path.read_text()
            with patch.object(gui.os, 'replace', side_effect=OSError('simulated')):
                self.assertFalse(gui.save_config({'refresh_interval': 2}))
            self.assertEqual(path.read_text(), original)
            self.assertEqual(len(list(Path(directory).iterdir())), 1)

    def test_config_save_preserves_malformed_existing_file(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(gui, 'CONFIG_PATH', str(Path(directory) / 'config.json')):
            path = Path(gui.CONFIG_PATH)
            for content in ('{broken', '[]', 'null'):
                path.write_text(content)
                self.assertFalse(gui.save_config({'refresh_interval': 2}))
                self.assertEqual(path.read_text(), content)

    def test_deferred_tunnel_requires_confirmation_even_with_unlocked_config(self):
        fake = SimpleNamespace(config={'connection_protected': False},
                               latest_stats={'network_actions_deferred': True},
                               _network_dialog=None, _closed=False, _poll_stats=Mock())
        callback = Mock()
        with patch.object(gui.Adw.MessageDialog, 'new', return_value=Mock()) as create:
            gui.NetPulseWindow._confirm_network_action(fake, 'Tunnel conservé', callback)
        callback.assert_not_called()
        create.assert_called_once()

    def test_invalid_numeric_feature_settings_are_normalized_on_load(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(gui, 'CONFIG_PATH', str(Path(directory) / 'config.json')):
            path = Path(gui.CONFIG_PATH)
            for value in (None, 'bad', 'NaN', 'Infinity'):
                path.write_text(json.dumps({'diagnostic_interval': value, 'alert_daily_mib': value,
                                            'diagnostic_url': value}))
                config = gui.load_config()
                self.assertEqual(config['diagnostic_interval'], 60)
                self.assertEqual(config['alert_daily_mib'], 0)
                self.assertEqual(config['diagnostic_url'], 'https://github.com')

    def test_stale_monitor_pid_starts_monitor(self):
        fake = SimpleNamespace(mon_bin='/test/netpulse-monitor')
        with patch.object(gui.os.path, 'exists', return_value=True), \
             patch('builtins.open', side_effect=FileNotFoundError), \
             patch.object(gui.subprocess, 'Popen') as spawn:
            gui.NetPulseWindow._ensure_monitor_running(fake)
        spawn.assert_called_once()

    def test_empty_ignore_list_is_saved(self):
        fake = SimpleNamespace(enable_proxy_row=Mock(), settings=Mock(), socks_settings=Mock(),
                               http_settings=Mock(), https_settings=Mock(), ignore_entry=Mock())
        fake.ignore_entry.get_text.return_value = ''
        for proto in ('socks', 'http', 'https'):
            setattr(fake, proto + '_host_entry', Mock())
            spin = Mock()
            spin.get_value.return_value = 1080
            setattr(fake, proto + '_port_spin', spin)
        gui.NetPulseWindow._save_gsettings(fake)
        fake.settings.set_strv.assert_called_once_with('ignore-hosts', [])


if __name__ == '__main__':
    unittest.main()
