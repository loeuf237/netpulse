import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class GeneratedTests(unittest.TestCase):
    def test_committed_executables_match_the_only_editable_sources(self):
        result = subprocess.run([sys.executable, str(ROOT / "tools/build_executables.py"), "--check"],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_standalone_monitor_embeds_features_without_installed_python_package(self):
        # Loading with a non-main name checks the bundle without starting its daemon.
        command = "import runpy; m=runpy.run_path(%r,run_name='bundle_test'); " \
                  "assert m['FeatureService'].__module__=='netpulse.features'" % str(ROOT / "bin/netpulse-monitor")
        result = subprocess.run([sys.executable, "-I", "-c", command], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
