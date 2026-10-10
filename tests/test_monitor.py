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
spec = importlib.util.spec_from_file_location('netpulse_monitor_test', ROOT / 'src/netpulse/monitor.py')
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)


def socket_sample(*sockets):
    samples = {key: {'recv': recv, 'sent': sent} for key, recv, sent in sockets}
    return {42: {'name': 'browser', 'recv': sum(x['recv'] for x in samples.values()),
                 'sent': sum(x['sent'] for x in samples.values()), 'sockets': samples}}


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        for name in ('CONFIG_PATH', 'BLOCKED_FILE', 'SPLIT_APPS_FILE', 'STATS_PATH', 'RESET_FLAG_PATH', 'PID_FILE', 'LOCK_FILE'):
            patcher = patch.object(monitor, name, str(Path(self.temp.name) / name))
            patcher.start()
            self.addCleanup(patcher.stop)

    def engine(self):
        with patch.object(monitor.NetPulseEngine, '_init_firewall'), patch.object(monitor, 'get_network_io', return_value={'eth0': (100, 200)}):
            engine = monitor.NetPulseEngine()
        engine.check_proxy_status = Mock()
        engine._ctl_async = Mock(return_value=True)
        engine.session_start = 0
        engine.last_time = 1
        engine.last_monotonic = 1
        engine.session_monotonic = 0
        return engine

    def test_live_update_blocks_automatic_commands_for_same_tunnel(self):
        with patch.object(monitor.NetPulseEngine, '_tunnel_identity', return_value=(10, 123)), \
             patch.object(monitor, 'get_network_io', return_value={}), \
             patch.object(monitor.subprocess, 'Popen') as spawn:
            engine = monitor.NetPulseEngine(preserve_active_tunnel=True)
            self.assertFalse(engine._ctl_async('split-assign', '42', 'direct'))
            self.assertFalse(engine._ctl_async('block', '42'))
        spawn.assert_not_called()

    def test_network_actions_resume_after_original_tunnel_is_replaced(self):
        engine = self.engine()
        engine._protected_tunnel = (10, 123)
        with patch.object(monitor.NetPulseEngine, '_tunnel_identity', return_value=(10, 456)), \
             patch.object(monitor.subprocess, 'Popen') as spawn:
            self.assertTrue(monitor.NetPulseEngine._ctl_async(engine, 'firewall-init'))
        self.assertIsNone(engine._protected_tunnel)
        spawn.assert_called_once()

    def test_configured_protection_follows_tunnel_and_explicit_unlock_releases_it(self):
        engine = self.engine()
        with patch.object(monitor.NetPulseEngine, '_tunnel_identity', return_value=(20, 456)):
            engine._refresh_protection()
        self.assertEqual(engine._protected_tunnel, (20, 456))
        engine.config["connection_protected"] = False
        engine._refresh_protection()
        self.assertIsNone(engine._protected_tunnel)

    def test_failed_command_is_reported_before_retry_delay_expires(self):
        engine = self.engine()
        process = Mock()
        process.poll.return_value = 1
        engine._ctl_jobs = {("block", "42"): (process, 100)}
        with patch.object(monitor.time, 'time', return_value=101):
            engine._reap_ctl_jobs()
        self.assertEqual(engine._ctl_results[("block", "42")], 1)
        self.assertIn(("block", "42"), engine._ctl_jobs)

    def test_resume_recent_session_without_recounting_socket_bytes(self):
        data = {'timestamp': 100, 'session_start': 10, 'session_rx': 500, 'session_tx': 200,
                'session_duration_sec': 90, 'history': [{'t': 99, 'rx': 1, 'tx': 2}],
                'processes': [{'pid': 42, 'name': 'browser', 'create_time': 5,
                               'total_rx': 300, 'total_tx': 100}]}
        Path(monitor.STATS_PATH).write_text(json.dumps(data))
        process = Mock()
        process.create_time.return_value = 5
        with patch.object(monitor.NetPulseEngine, '_init_firewall'), \
             patch.object(monitor, 'get_network_io', return_value={}), \
             patch.object(monitor.time, 'time', return_value=102), \
             patch.object(monitor.time, 'monotonic', return_value=1000), \
             patch.object(monitor.psutil, 'Process', return_value=process):
            engine = monitor.NetPulseEngine(resume_session=True)
        self.assertEqual((engine.session_rx, engine.session_tx, engine.session_start), (500, 200, 10))
        self.assertEqual(engine.session_monotonic, 910)
        self.assertEqual(engine.proc_traffic_history[42]['tot_rx'], 300)
        self.assertEqual(engine.proc_traffic_history[42]['sockets'], {})
        self.assertEqual(list(engine.history), data['history'])

    def test_resume_skips_old_session_and_invalid_history(self):
        for timestamp, expected in ((0, 0), (100, 500)):
            Path(monitor.STATS_PATH).write_text(json.dumps({
                'timestamp': timestamp, 'session_start': 10, 'session_rx': 500, 'session_tx': 200,
                'history': [{'t': 'invalid'}, {'t': 99, 'rx': -1, 'tx': 0}, {'t': 999, 'rx': 0, 'tx': 0}]}))
            engine = self.engine()
            with patch.object(monitor.time, 'time', return_value=102):
                engine._restore_session()
            self.assertEqual(engine.session_rx, expected)
            self.assertEqual(list(engine.history), [])

    def test_resume_does_not_transfer_totals_to_reused_pid(self):
        Path(monitor.STATS_PATH).write_text(json.dumps({
            'timestamp': 100, 'session_start': 10, 'session_rx': 500, 'session_tx': 200,
            'processes': [{'pid': 42, 'create_time': 5, 'total_rx': 300, 'total_tx': 100}]}))
        engine = self.engine()
        process = Mock()
        process.create_time.return_value = 6
        with patch.object(monitor.time, 'time', return_value=102), \
             patch.object(monitor.psutil, 'Process', return_value=process):
            engine._restore_session()
        self.assertNotIn(42, engine.proc_traffic_history)

    def collect(self, engine, snapshot, now, *, proxy=False, blocked=False, connections=True, network=None, identity=1, monotonic_now=None):
        process = Mock()
        process.name.return_value = 'browser'
        process.cmdline.return_value = ['/usr/bin/browser']
        process.info = {'pid': 42, 'name': 'browser', 'cmdline': ['/usr/bin/browser']}
        process.pid = 42
        process.create_time.return_value = identity
        engine.proxy_active = proxy
        conn = SimpleNamespace(pid=42, status='ESTABLISHED', type=1,
                               laddr=SimpleNamespace(ip='192.0.2.1', port=1234),
                               raddr=SimpleNamespace(ip='198.51.100.1', port=443))
        with patch.object(monitor.time, 'time', return_value=now), \
             patch.object(monitor.time, 'monotonic', return_value=now if monotonic_now is None else monotonic_now), \
             patch.object(monitor, 'get_network_io', return_value={'eth0': (100, 200)} if network is None else network), \
             patch.object(monitor, 'parse_socket_traffic', return_value=snapshot), \
             patch.object(monitor.psutil, 'net_connections', return_value=[conn] if connections else []), \
             patch.object(monitor.psutil, 'process_iter', return_value=[process]), \
             patch.object(monitor.psutil, 'Process', return_value=process), \
             patch.object(monitor.psutil, 'pid_exists', return_value=True), \
             patch.object(monitor, 'load_blocked_apps', return_value={'browser'} if blocked else set()), \
             patch.object(monitor, 'async_resolve_ip'):
            engine.collect()
        return json.loads(Path(monitor.STATS_PATH).read_text())

    def test_parse_resets_owner_for_every_state_and_deduplicates_fds(self):
        output = '''ESTAB 0 0 192.0.2.1:1 198.51.100.1:443 users:(("browser",pid=42,fd=3),("browser",pid=42,fd=4)) ino:10
  bytes_sent:100 bytes_received:200
FIN-WAIT-1 0 0 192.0.2.1:2 198.51.100.2:443 ino:11
  bytes_sent:999 bytes_received:999
CLOSE-WAIT 0 0 192.0.2.1:3 198.51.100.3:443 users:(("other",pid=43,fd=3)) ino:12
  bytes_sent:10 bytes_received:20'''
        with patch.object(monitor.subprocess, 'check_output', return_value=output):
            result = monitor.parse_socket_traffic()
        self.assertEqual(result[42]['recv'], 200)
        self.assertEqual(result[42]['sent'], 100)
        self.assertEqual(result[43]['recv'], 20)

    def test_no_false_spike_when_socket_closes(self):
        engine = self.engine()
        self.collect(engine, socket_sample(('a', 100, 0), ('b', 10000, 0)), 2)
        self.collect(engine, socket_sample(('a', 120, 0)), 3)
        payload = self.collect(engine, socket_sample(('a', 150, 0)), 4)
        self.assertEqual(payload['processes'][0]['rx_speed'], 30)
        self.assertEqual(payload['processes'][0]['total_rx'], 50)

    def test_new_socket_does_not_reuse_old_socket_counter(self):
        engine = self.engine()
        self.collect(engine, socket_sample(('old', 100, 0)), 2)
        payload = self.collect(engine, socket_sample(('new', 9000, 0)), 3)
        self.assertEqual(payload['processes'][0]['rx_speed'], 0)

    def test_blocked_process_remains_visible_without_connections(self):
        payload = self.collect(self.engine(), {}, 2, blocked=True, connections=False)
        self.assertEqual(len(payload['processes']), 1)
        self.assertTrue(payload['processes'][0]['block_requested'])
        self.assertFalse(payload['processes'][0]['is_blocked'])
        self.assertEqual(payload['processes'][0]['rule_status']['state'], 'pending')

    def test_routing_never_reassigns_a_blocked_process(self):
        engine = self.engine()
        engine.config = dict(monitor.DEFAULT_CONFIG, split_tunnel_mode='include')
        with patch.object(monitor, 'load_config', return_value=engine.config), \
             patch.object(monitor, 'load_split_apps', return_value={'browser'}):
            self.collect(engine, {}, 2, proxy=True, blocked=True)
        self.assertNotIn('split-assign', [call.args[0] for call in engine._ctl_async.call_args_list])

    def test_totals_survive_idle_periods(self):
        engine = self.engine()
        self.collect(engine, socket_sample(('a', 100, 0)), 2)
        self.collect(engine, socket_sample(('a', 125, 0)), 3)
        payload = self.collect(engine, {}, 4)
        self.assertEqual(payload['processes'][0]['total_rx'], 25)
        self.assertEqual(payload['processes'][0]['rx_speed'], 0)

    def test_new_interface_does_not_add_pre_session_traffic(self):
        engine = self.engine()
        payload = self.collect(engine, {}, 2, network={'eth0': (110, 220), 'wlan0': (9000000, 5000000)})
        self.assertEqual(payload['rx_speed'], 10)
        self.assertEqual(payload['session_tx'], 20)

    def test_interface_removal_does_not_mask_traffic_on_remaining_interface(self):
        engine = self.engine()
        engine.last_interfaces = {'eth0': (100, 200), 'wlan0': (9000, 1000)}
        payload = self.collect(engine, {}, 2, network={'eth0': (130, 210)})
        self.assertEqual(payload['rx_speed'], 30)

    def test_clock_change_uses_monotonic_interval(self):
        payload = self.collect(self.engine(), {}, 100000, network={'eth0': (110, 220)}, monotonic_now=2)
        self.assertEqual(payload['rx_speed'], 10)
        self.assertEqual(payload['session_duration_sec'], 2)

    def test_reused_pid_starts_with_fresh_totals(self):
        engine = self.engine()
        self.collect(engine, socket_sample(('a', 100, 0)), 2)
        self.collect(engine, socket_sample(('a', 150, 0)), 3)
        payload = self.collect(engine, socket_sample(('b', 200, 0)), 4, identity=2)
        self.assertEqual(payload['processes'][0]['total_rx'], 0)

    def test_duplicate_daemon_does_not_initialize_firewall(self):
        import fcntl
        with open(monitor.LOCK_FILE, 'w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with patch.object(monitor.sys, 'argv', ['netpulse-monitor']), \
                 patch.object(monitor, 'NetPulseEngine') as engine:
                monitor.main()
                engine.assert_not_called()

    def test_reset_sets_new_network_baseline(self):
        engine = self.engine()
        with patch.object(monitor, 'get_network_io', return_value={'eth0': (900, 800)}), \
             patch.object(monitor.time, 'time', return_value=20):
            engine.reset_session()
        self.assertEqual((engine.last_rx, engine.last_tx, engine.last_time), (900, 800, 20))

    def test_invalid_interval_recovers(self):
        for interval in ('3', None, -1, True, 100):
            Path(monitor.CONFIG_PATH).write_text(json.dumps({'refresh_interval': interval}))
            self.assertEqual(monitor.load_config()['refresh_interval'], 1)

    def test_split_matching_uses_exact_binary_with_spaces(self):
        self.assertTrue(monitor.is_app_in_split_list('short', ['/opt/my apps/browser', '--arg'], {'browser'}))
        self.assertFalse(monitor.is_app_in_split_list('bash', ['/bin/bash', 'browser'], {'browser'}))

    def test_dns_lookup_allows_ipv4_mapped_ipv6_but_is_bounded(self):
        with patch.dict(monitor.DNS_CACHE, clear=True), patch.object(monitor, 'PENDING_DNS', set()), \
             patch.object(monitor.threading, 'Thread') as thread:
            monitor.async_resolve_ip('::ffff:192.0.2.1')
            thread.assert_called_once()
            monitor.PENDING_DNS.update(str(i) for i in range(8))
            monitor.async_resolve_ip('198.51.100.2')
            self.assertEqual(thread.call_count, 1)

    def test_refresh_interval_is_read_each_time(self):
        engine = self.engine()
        engine.config['refresh_interval'] = 3
        with patch.object(monitor.GLib, 'timeout_add_seconds') as timer:
            engine._schedule_collect()
            self.assertEqual(timer.call_args.args[0], 3)


if __name__ == '__main__':
    unittest.main()
