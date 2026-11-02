#!/usr/bin/env python3
"""Run explicit compatibility tiers without importing unavailable GUI libraries."""
import argparse
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--suite', choices=('core', 'monitor', 'full'), default='full')
args = parser.parse_args()
files = ['test_ctl.py', 'test_features.py', 'test_release.py', 'test_english.py']
if args.suite in ('monitor', 'full'):
    files += ['test_monitor.py', 'test_live_upgrade.py', 'test_generated.py', 'test_install.py']
if args.suite == 'full':
    files += ['test_gui.py']
suite = unittest.TestSuite()
for name in files:
    suite.addTests(unittest.defaultTestLoader.discover(str(ROOT / 'tests'), pattern=name))
if not suite.countTestCases():
    raise SystemExit('No tests collected')
print('Compatibility tier: ' + args.suite, flush=True)
raise SystemExit(not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful())
