import importlib.util
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('netpulse_live_test', ROOT / 'live-upgrade.py')
live = importlib.util.module_from_spec(spec)
spec.loader.exec_module(live)


class LiveUpgradeTests(unittest.TestCase):
    def test_zombie_child_cannot_prevent_live_update(self):
        process, child = Mock(), Mock()
        process.children.return_value = [child]
        child.status.return_value = live.psutil.STATUS_ZOMBIE
        self.assertFalse(live.busy_children(process))
        child.status.return_value = live.psutil.STATUS_RUNNING
        self.assertTrue(live.busy_children(process))

    def test_verification_detects_replaced_tunnel_and_changed_routes(self):
        process = Mock()
        process.is_running.return_value = True
        process.create_time.return_value = 1
        with patch.object(live, 'network_snapshot', return_value={'routes': ['old']}):
            live.verify_network(process, 1, {'routes': ['old']})
            with self.assertRaises(RuntimeError):
                live.verify_network(process, 2, {'routes': ['old']})
            with self.assertRaises(RuntimeError):
                live.verify_network(process, 1, {'routes': ['changed']})

    def test_stats_gate_requires_active_protected_tunnel_and_new_sample(self):
        sample = '{"timestamp":11,"proxy_active":true,"network_actions_deferred":true}'
        with patch.object(live.STATS.__class__, 'read_text', return_value=sample):
            self.assertEqual(live.wait_for_stats(10)['timestamp'], 11)
        with patch.object(live.time, 'monotonic', side_effect=[0, 0, 20]), \
             patch.object(live.time, 'sleep'), \
             patch.object(live.STATS.__class__, 'read_text', return_value=sample):
            with self.assertRaises(RuntimeError):
                live.wait_for_stats(11)


if __name__ == '__main__':
    unittest.main()
