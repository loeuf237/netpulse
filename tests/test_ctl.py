import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'src/netpulse/ctl.sh').read_text()
# Charger uniquement les fonctions Bash, jamais le dispatch des commandes privilégiées.
FUNCTIONS = '\n'.join(re.findall(r'^\w+\(\) \{\n.*?^\}', SOURCE, re.M | re.S))


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.config = self.directory / 'config.json'
        self.split = self.directory / 'split.txt'
        self.proxy = self.directory / 'proxy'
        self.direct = self.directory / 'direct'
        self.blocked = self.directory / 'blocked'
        for group in (self.proxy, self.direct, self.blocked):
            group.mkdir()
            (group / 'cgroup.procs').write_text('')

    def run_functions(self, commands, *, check=True):
        variables = {'CONFIG_FILE': str(self.config), 'SPLIT_DIR': str(self.directory), 'SPLIT_FILE': str(self.split),
                     'CGROUP_PROXY': str(self.proxy), 'CGROUP_DIRECT': str(self.direct), 'CGROUP_BLOCKED': str(self.blocked),
                     'TARGET_USER': 'not-a-real-user', 'TUN_NAME': 'tun-proxy', 'ORIGINAL_CGROUP_DIR': str(self.directory / 'original')}
        prefix = '\n'.join(f'{key}={shlex.quote(value)}' for key, value in variables.items())
        # Le faux chown évite tout changement de propriétaire, même dans les dossiers temporaires.
        result = subprocess.run(['bash', '-c', FUNCTIONS + '\n' + prefix + '\nchown() { :; }; id() { echo nobody; };\n' + commands],
                                capture_output=True, text=True, timeout=10)
        if check:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def test_save_mode_on_empty_object_preserves_valid_json(self):
        self.config.write_text('{}')
        self.run_functions('save_split_mode include')
        self.assertEqual(json.loads(self.config.read_text()), {'split_tunnel_mode': 'include'})

    def test_save_ftp_preserves_nested_config(self):
        self.config.write_text('{"nested":{"keep":true},"refresh_interval":3}')
        self.run_functions('save_bypass_ftp 0')
        self.assertEqual(json.loads(self.config.read_text()), {'nested': {'keep': True}, 'refresh_interval': 3, 'bypass_ftp': False})

    def test_malformed_config_fails_without_overwriting(self):
        self.config.write_text('{broken')
        result = self.run_functions('save_split_mode include', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.config.read_text(), '{broken')

    def test_invalid_mode_is_failure(self):
        self.assertNotEqual(self.run_functions('split_set_mode invalid', check=False).returncode, 0)

    def test_dispatch_propagates_invalid_mode_failure(self):
        dispatch = SOURCE[SOURCE.index('\ncase "$1" in\n    start)'):]
        self.assertNotEqual(self.run_functions('set -- split-mode invalid;\n' + dispatch, check=False).returncode, 0)

    def test_invalid_destination_and_pid_are_failures(self):
        self.assertNotEqual(self.run_functions('split_assign_pid $$ invalid', check=False).returncode, 0)
        self.assertNotEqual(self.run_functions('split_assign_pid ../1 proxy', check=False).returncode, 0)

    def test_remove_literal_name_preserves_similar_regex_name_and_permissions(self):
        self.split.write_text('browser.x\nbrowserax\n-other\n')
        self.split.chmod(0o640)
        self.run_functions('remove_exact_line "$SPLIT_FILE" browser.x')
        self.assertEqual(self.split.read_text(), 'browserax\n-other\n')
        self.assertEqual(self.split.stat().st_mode & 0o777, 0o640)
        self.run_functions('remove_exact_line "$SPLIT_FILE" -other')
        self.assertEqual(self.split.read_text(), 'browserax\n')

    def test_status_json_escapes_quotes_and_newlines(self):
        result = self.run_functions('print_status_json true $\'socks5://user:"pass"@example:1080\\n\' include 1')
        data = json.loads(result.stdout)
        self.assertEqual(data['proxy'], 'socks5://user:"pass"@example:1080\n')
        self.assertTrue(data['active'])

    def test_app_name_is_literal_and_rejects_line_injection(self):
        result = self.run_functions('normalize_app_name "  Browser.x  "')
        self.assertEqual(result.stdout, 'browser.x\n')
        self.assertNotEqual(self.run_functions("normalize_app_name $'browser\\nother'", check=False).returncode, 0)
        self.assertNotEqual(self.run_functions('normalize_app_name " "', check=False).returncode, 0)

    def test_sync_removed_app_restores_both_groups(self):
        for mode in ('include', 'exclude', 'disabled'):
            with self.subTest(mode=mode):
                self.config.write_text(json.dumps({'split_tunnel_mode': mode, 'bypass_ftp': False}))
                (self.proxy / 'cgroup.procs').write_text('42\n')
                (self.direct / 'cgroup.procs').write_text('43\n')
                self.split.write_text('')
                result = self.run_functions('split_assign_pid() { echo "$1:$2"; }; split_sync')
                self.assertEqual(set(result.stdout.splitlines()), {'42:default', '43:default'})

    def test_sync_ftp_overrides_include_without_leaving_stale_routes(self):
        self.config.write_text('{"split_tunnel_mode":"include","bypass_ftp":true}')
        self.split.write_text('filezilla\nbrowser\n')
        (self.proxy / 'cgroup.procs').write_text('42\n44\n')
        commands = '''find_app_pids() { case "$1" in filezilla) echo 42;; browser) echo 43;; esac; };
        split_assign_pid() { echo "$1:$2"; }; split_sync'''
        result = self.run_functions(commands)
        self.assertEqual(set(result.stdout.splitlines()), {'42:direct', '43:proxy', '44:default'})

    def test_policy_setup_does_not_duplicate_existing_rule(self):
        commands = '''ip() { if [ "$1" = "-4" ]; then echo "10040: from all fwmark 0x1000/0x1000 lookup 100"; else echo added; fi; };
        ensure_policy_rule 0x1000/0x1000 100 10040'''
        self.assertEqual(self.run_functions(commands).stdout, '')

    def test_direct_routes_keep_interface_when_filtered_ip_output_omits_dev(self):
        self.config.write_text('{"bypass_ftp":false}')
        commands = '''get_net_info() { default_if=wlp0s20f3; default_gw=192.168.43.1; default_ip=192.168.43.226; };
        iptables() { :; }; ip6tables() { :; }; ensure_policy_rule() { :; };
        ip() {
            if [ "$*" = "-4 route show dev wlp0s20f3" ]; then
                printf '%s\\n' 'default via 192.168.43.1 proto dhcp src 192.168.43.226 metric 600' \
                              '192.168.43.0/24 proto kernel scope link src 192.168.43.226 metric 600';
            elif [ "$1 $2" = "route replace" ]; then
                if [[ " $* " != *" dev "* ]]; then
                    echo 'RTNETLINK answers: No such device' >&2; return 1;
                fi
                printf '%s\\n' "$*";
            fi
        };
        split_setup_rules'''
        result = self.run_functions(commands)
        self.assertIn('route replace 192.168.43.0/24 proto kernel scope link src 192.168.43.226 metric 600 dev wlp0s20f3 table 200',
                      result.stdout.splitlines())

    def test_direct_routes_do_not_duplicate_explicit_interface(self):
        self.config.write_text('{"bypass_ftp":false}')
        commands = '''get_net_info() { default_if=wlp0s20f3; default_gw=192.168.43.1; default_ip=192.168.43.226; };
        iptables() { :; }; ip6tables() { :; }; ensure_policy_rule() { :; };
        ip() {
            if [ "$*" = "-4 route show dev wlp0s20f3" ]; then
                echo '192.168.43.0/24 dev wlp0s20f3 proto kernel scope link src 192.168.43.226';
            elif [ "$1 $2" = "route replace" ]; then printf '%s\\n' "$*"; fi
        };
        split_setup_rules'''
        result = self.run_functions(commands)
        self.assertIn('route replace 192.168.43.0/24 dev wlp0s20f3 proto kernel scope link src 192.168.43.226 table 200',
                      result.stdout.splitlines())

    def test_kill_sockets_uses_exact_owner_and_endpoint_filters(self):
        mock_bin = self.directory / 'bin'
        mock_bin.mkdir()
        log = self.directory / 'ss_calls.jsonl'
        fake_ss = mock_bin / 'ss'
        fake_ss.write_text('#!' + sys.executable + '''
import json,sys
if '-K' not in sys.argv:
    print('ESTAB 0 0 192.0.2.1:1234 198.51.100.1:443 users:(("app",pid=42,fd=3))')
    print('ESTAB 0 0 192.0.2.1:1235 198.51.100.2:443 users:(("app",pid=142,fd=3))')
else:
    with open(''' + repr(str(log)) + ''', 'a') as stream: stream.write(json.dumps(sys.argv[1:])+'\\n')
''')
        fake_ss.chmod(0o755)
        self.run_functions(f'export PATH={shlex.quote(str(mock_bin))}:"$PATH"; kill_pid_sockets 42')
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertEqual(calls, [['-K', '-t', 'src', '192.0.2.1:1234', 'dst', '198.51.100.1:443']])

    def migration(self):
        code = SOURCE.split("<<'PYMIGRATE'\n", 1)[1].split('\nPYMIGRATE', 1)[0]
        runtime = self.directory / 'runtime'
        runtime.mkdir(exist_ok=True)
        legacy_pid = self.directory / 'legacy.pid'
        legacy_proxy = self.directory / 'legacy.proxy'
        proc_dir = self.directory / 'proc' / '42'
        proc_dir.mkdir(parents=True, exist_ok=True)
        (proc_dir / 'comm').write_text('tun2socks\n')
        legacy_pid.write_text('42')
        legacy_proxy.write_text('socks5://127.0.0.1:1080')
        legacy_pid.chmod(0o644)
        legacy_proxy.chmod(0o644)
        code = code.replace('/run/netpulse', str(runtime)).replace('/tmp/force-proxy.pid', str(legacy_pid))
        code = code.replace('/tmp/force-proxy-current.txt', str(legacy_proxy)).replace('/proc/', str(self.directory / 'proc') + '/')
        return code, runtime, legacy_proxy

    def test_live_migration_adopts_pid_and_rejects_unsafe_legacy_state(self):
        code, runtime, proxy = self.migration()
        original_stat = os.fstat
        def root_stat(fd):
            info = original_stat(fd)
            return SimpleNamespace(st_uid=0, st_mode=info.st_mode)
        with patch('sys.argv', ['migration', 'user']), \
             patch('pwd.getpwnam', return_value=SimpleNamespace(pw_gid=os.getgid())), \
             patch('os.fstat', side_effect=root_stat), patch('os.fchown'):
            exec(compile(code, '<isolated migration>', 'exec'), {})
            self.assertEqual((runtime / 'tun2socks.pid').read_text().strip(), '42')
            self.assertEqual((runtime / 'proxy.txt').read_text().strip(), proxy.read_text())
            self.assertEqual((runtime / 'proxy.txt').stat().st_mode & 0o777, 0o640)
            # Une seconde migration conserve l'état déjà publié.
            exec(compile(code, '<isolated migration>', 'exec'), {})
            (runtime / 'tun2socks.pid').unlink()
            proxy.chmod(0o666)
            with self.assertRaises(ValueError):
                exec(compile(code, '<isolated migration>', 'exec'), {})
        self.assertFalse((runtime / 'tun2socks.pid').exists())

    def test_migration_has_no_network_mutation_commands(self):
        branch = SOURCE.split('\n    install-runtime)\n', 1)[1].split('\n        ;;', 1)[0]
        self.assertNotRegex(branch, r'\b(?:ip|iptables|ip6tables|pkill|sysctl|split_sync|firewall_init)\b')


if __name__ == '__main__':
    unittest.main()
