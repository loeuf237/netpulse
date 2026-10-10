import csv
import datetime as dt
import json
import os
import socket
import sys
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from netpulse.features import (AlertEngine, DiagnosticProbe, FeatureService, HistoryStore,
                              ProfileStore, activate_profile, atomic_file, bounded_number,
                              proxy_display, rule_state, validate_diagnostic_url)


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.store = HistoryStore(self.directory / "history.db")
        self.now = dt.datetime.now().astimezone()

    def test_global_and_application_counts_are_independent_and_aggregate_pids(self):
        timestamp = self.now.timestamp()
        self.store.record(timestamp, 100, 20, [("browser", 50, 10), ("browser", 25, 5)])
        self.store.record(timestamp + 0.01, 20, 5, [("browser", 5, 1)])
        data = self.store.summary(1, self.now + dt.timedelta(seconds=1))
        self.assertEqual((data["rx"], data["tx"]), (120, 25))
        self.assertEqual(data["applications"], [{"app": "browser", "rx": 80, "tx": 16}])

    def test_history_survives_restart_and_session_reset(self):
        self.store.record(self.now.timestamp(), 100, 20, [])
        restarted = HistoryStore(self.directory / "history.db")
        self.assertEqual(restarted.summary(now=self.now)["rx"], 100)
        self.assertEqual((self.directory / "history.db").stat().st_mode & 0o777, 0o600)

    def test_periods_do_not_include_older_days(self):
        self.store.record(self.now.timestamp() - 2 * 86400, 30, 5, [])
        self.store.record(self.now.timestamp(), 100, 20, [])
        self.assertEqual(self.store.summary(1, self.now)["rx"], 100)
        self.assertEqual(self.store.summary(7, self.now)["rx"], 130)

    def test_retention_removes_ancient_rows_and_events(self):
        old = self.now.timestamp() - 100 * 86400
        self.store.record(old, 30, 5, [], retention=365)
        self.store.add_event("server", "proxy", "Ancien incident", old)
        self.store.record(self.now.timestamp(), 100, 20, [], retention=90)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM usage").fetchone()[0], 1)
        self.assertEqual(self.store.recent_events(), [])

    def test_alert_deduplication_survives_restart(self):
        timestamp = self.now.timestamp()
        first = self.store.add_event("server", "proxy", "Indisponible", timestamp, 600)
        self.assertIsNotNone(first)
        restarted = HistoryStore(self.directory / "history.db")
        self.assertIsNone(restarted.add_event("server", "proxy", "Indisponible", timestamp + 30, 600))
        self.assertIsNotNone(restarted.add_event("server", "proxy", "Indisponible", timestamp + 601, 600))

    def test_csv_preserves_scopes_and_prevents_formula_injection(self):
        self.store.record(self.now.timestamp(), 100, 20, [("=danger", 30, 5)])
        destination = self.directory / "export.csv"
        self.assertEqual(self.store.export_csv(destination), 2)
        with destination.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual({r["portee"] for r in rows}, {"Global TCP+UDP", "TCP echantillonne"})
        self.assertIn("'=danger", [r["application"] for r in rows])


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.store = ProfileStore(self.directory / "profiles.json")
        self.profile = {"name": "Mobile", "proxy_url": "socks5://user:password@127.0.0.1:1080",
                        "split_mode": "include", "split_apps": [" Browser ", "browser"],
                        "bypass_ftp": True}

    def test_create_edit_delete_profiles_without_network_calls(self):
        saved = self.store.save(self.profile)
        self.assertEqual(saved["split_apps"], ["browser"])
        self.assertEqual(self.store.path.stat().st_mode & 0o777, 0o600)
        edited = self.store.save(dict(self.profile, name="Travail"), saved["id"])
        self.assertEqual(edited["id"], saved["id"])
        self.assertEqual(self.store.list()[0]["name"], "Travail")
        self.store.delete(saved["id"])
        self.assertEqual(self.store.list(), [])

    def test_duplicate_names_and_invalid_app_names_are_rejected(self):
        self.store.save(self.profile)
        with self.assertRaises(ValueError):
            self.store.save(dict(self.profile, name="mobile"))
        with self.assertRaises(ValueError):
            self.store.save(dict(self.profile, split_apps=["browser\nother"]))

    def test_invalid_urls_and_modes_never_replace_profiles(self):
        self.store.save(self.profile)
        original = self.store.path.read_bytes()
        for values in ({"proxy_url": None}, {"name": None}, {"proxy_url": "file:///etc/passwd"}, {"proxy_url": "http://127.0.0.1:99999"},
                       {"split_mode": "broken"}, {"bypass_ftp": "false"}):
            with self.assertRaises(ValueError):
                self.store.save(dict(self.profile, **values))
            self.assertEqual(self.store.path.read_bytes(), original)

    def test_atomic_failure_keeps_previous_profiles_and_removes_temporary_file(self):
        self.store.save(self.profile)
        original = self.store.path.read_bytes()
        with patch("netpulse.features.os.replace", side_effect=OSError):
            with self.assertRaises(OSError):
                self.store.save(dict(self.profile, name="Autre"))
        self.assertEqual(self.store.path.read_bytes(), original)
        self.assertEqual({p.name for p in self.directory.iterdir()}, {"profiles.json", "profiles.json.lock"})

    def test_credentials_are_removed_from_proxy_descriptions(self):
        display = proxy_display(self.profile["proxy_url"])
        self.assertEqual(display, "socks5://127.0.0.1:1080")
        self.assertNotIn("password", display)

    def test_activation_same_server_does_not_restart_tunnel(self):
        config, apps = self.directory / "config.json", self.directory / "apps.txt"
        config.write_text('{"custom":"keep","connection_protected":true}')
        execute = Mock()
        activate_profile(self.profile, config, apps, execute, self.profile["proxy_url"])
        self.assertEqual([call.args[0] for call in execute.call_args_list],
                         [["split-mode", "include"], ["ftp-bypass", "on"]])
        self.assertEqual(json.loads(config.read_text())["custom"], "keep")
        self.assertTrue(json.loads(config.read_text())["connection_protected"])
        self.assertEqual(apps.read_text(), "browser\n")

    def test_activation_network_failure_restores_previous_settings(self):
        config, apps = self.directory / "config.json", self.directory / "apps.txt"
        config.write_text('{"custom":"keep"}')
        apps.write_text("previous\n")
        execute = Mock(side_effect=RuntimeError("controller failure"))
        with self.assertRaises(RuntimeError):
            activate_profile(self.profile, config, apps, execute)
        self.assertEqual(config.read_text(), '{"custom":"keep"}')
        self.assertEqual(apps.read_text(), "previous\n")
        execute.assert_called_once_with(["start", self.profile["proxy_url"]])

    def test_activation_storage_failure_never_calls_network(self):
        config, apps = self.directory / "config.json", self.directory / "apps.txt"
        config.write_text("{}")
        execute = Mock()
        original = atomic_file
        def write(path, data, mode=0o600):
            if Path(path) == apps:
                raise OSError("disk failure")
            return original(path, data, mode)
        with patch("netpulse.features.atomic_file", side_effect=write):
            with self.assertRaises(OSError):
                activate_profile(self.profile, config, apps, execute)
        execute.assert_not_called()
        self.assertEqual(config.read_text(), "{}")


class DiagnosticTests(unittest.TestCase):
    def test_probe_observes_all_layers_and_uses_current_routes_without_env_proxy(self):
        opener = Mock()
        opener.open.return_value.__enter__ = Mock(return_value=Mock(status=200))
        opener.open.return_value.__exit__ = Mock()
        connection = Mock()
        connection.__enter__ = Mock()
        connection.__exit__ = Mock()
        with patch("netpulse.features.socket.getaddrinfo", return_value=[]), \
             patch("netpulse.features.socket.create_connection", return_value=connection) as connect, \
             patch("netpulse.features.urllib.request.build_opener", return_value=opener) as build:
            result = DiagnosticProbe().run(True, "socks5://secret:password@127.0.0.1:1080")
        self.assertEqual({result[k]["state"] for k in ("server", "tunnel", "dns", "internet")}, {"ok"})
        self.assertEqual(build.call_args.args[0].proxies, {})
        connect.assert_called_once_with(("127.0.0.1", 1080), timeout=3)
        self.assertNotIn("password", json.dumps(result))

    def test_failure_states_are_separate(self):
        with patch("netpulse.features.socket.getaddrinfo", side_effect=socket.gaierror), \
             patch("netpulse.features.socket.create_connection", side_effect=OSError), \
             patch("netpulse.features.urllib.request.build_opener") as build:
            build.return_value.open.side_effect = urllib.error.URLError("unreachable")
            result = DiagnosticProbe().run(True, "socks5://127.0.0.1:1080")
        self.assertEqual(result["tunnel"]["state"], "ok")
        self.assertEqual([result[k]["state"] for k in ("dns", "server", "internet")], ["error"] * 3)

    def test_https_http_error_still_proves_connectivity(self):
        with patch("netpulse.features.socket.getaddrinfo", return_value=[]), \
             patch("netpulse.features.urllib.request.build_opener") as build:
            build.return_value.open.side_effect = urllib.error.HTTPError("https://example.org", 405, "HEAD", {}, None)
            result = DiagnosticProbe().run(False, "", "https://example.org")
        self.assertEqual(result["internet"]["state"], "warning")
        self.assertEqual(result["tunnel"]["state"], "inactive")

    def test_rejects_non_https_and_credentialed_endpoints(self):
        for url in ("http://example.org", "file:///etc/passwd", "https://user:secret@example.org"):
            with self.assertRaises(ValueError):
                validate_diagnostic_url(url)


class AlertTests(unittest.TestCase):
    def test_server_alert_requires_two_distinct_failed_diagnostics(self):
        engine = AlertEngine()
        payload = {"timestamp": time.time(), "proxy_active": True}
        failure = {"timestamp": 1, "server": {"state": "error"}}
        self.assertEqual(engine.evaluate(payload, failure, 0, {}), [])
        self.assertEqual(engine.evaluate(payload, failure, 0, {}), [])
        failure["timestamp"] = 2
        self.assertEqual(engine.evaluate(payload, failure, 0, {})[0][0], "server")
        self.assertEqual(engine.evaluate(payload, failure, 0, {}), [])

    def test_disabled_or_inactive_server_never_alerts(self):
        for config, active in (({"alert_server_down": False}, True), ({}, False)):
            engine = AlertEngine()
            for timestamp in (1, 2, 3):
                events = engine.evaluate({"timestamp": time.time(), "proxy_active": active},
                                         {"timestamp": timestamp, "server": {"state": "error"}}, 0, config)
                self.assertEqual(events, [])

    def test_quota_and_sustained_app_rate_are_alerts_only(self):
        engine = AlertEngine()
        payload = {"timestamp": time.time(), "processes": [{"name": "browser", "rx_speed": 1024**2, "tx_speed": 0}]}
        config = {"alert_daily_mib": 1, "alert_app_rate_mib": 1}
        for _ in range(2):
            self.assertEqual([e[0] for e in engine.evaluate(payload, {}, 1024**2, config)], ["quota"])
        self.assertEqual([e[0] for e in engine.evaluate(payload, {}, 1024**2, config)], ["quota", "rate"])
        payload["processes"] = []
        self.assertEqual([e[0] for e in engine.evaluate(payload, {}, 0, config)], [])

    def test_rules_report_observed_assignment_and_failure(self):
        self.assertEqual(rule_state("proxy", "default", True)["state"], "pending")
        self.assertEqual(rule_state("proxy", "default", False, True)["state"], "error")
        self.assertEqual(rule_state("proxy", "proxy", True, True)["state"], "applied")

    def test_malformed_numeric_settings_are_bounded(self):
        for value in (None, "wrong", float("nan"), float("inf")):
            self.assertEqual(bounded_number({"alert_cooldown_sec": value}, "alert_cooldown_sec", 30, 86400), 600)


class ServiceTests(unittest.TestCase):
    def test_quota_uses_global_history_and_deduplication_survives_service_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            store = HistoryStore(Path(directory) / "history.db")
            notify = Mock()
            config = {"diagnostics_enabled": False, "alert_daily_mib": 3}
            payload = {"timestamp": time.time(), "proxy_active": True}
            service = FeatureService(store=store, notify=notify)
            service.submit(payload, 1024**2, 0, [("app", 8 * 1024**2, 0)], config)
            service.close()
            notify.assert_not_called()
            service = FeatureService(store=store, notify=notify)
            service.submit(payload, 3 * 1024**2, 0, [], config)
            service.close()
            notify.assert_called_once()
            service = FeatureService(store=store, notify=notify)
            service.submit(payload, 0, 0, [], config)
            service.close()
            notify.assert_called_once()

    def test_background_worker_flushes_pending_history_before_close(self):
        store = Mock()
        store.summary.return_value = {"rx": 10, "tx": 20}
        store.recent_events.return_value = []
        service = FeatureService(store=store)
        service.submit({"timestamp": time.time(), "proxy_active": True}, 10, 20, [("browser", 5, 1)],
                       {"diagnostics_enabled": False})
        service.close()
        store.record.assert_called_once()
        self.assertFalse(service.thread.is_alive())

    def test_disk_failure_is_reported_without_stopping_monitor(self):
        store = Mock()
        store.record.side_effect = OSError("disk")
        service = FeatureService(store=store)
        service.submit({"timestamp": time.time(), "proxy_active": True}, 10, 20, [], {"diagnostics_enabled": False})
        service.close()
        self.assertIn("OSError", service.snapshot()["storage_error"])


if __name__ == "__main__":
    unittest.main()
