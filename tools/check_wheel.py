#!/usr/bin/env python3
"""Check that packaging includes the source-backed features and controller."""
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
with zipfile.ZipFile(sys.argv[1]) as wheel:
    for name in ("features.py", "gui.py", "monitor.py", "constants.py"):
        assert wheel.read("netpulse/" + name) == (ROOT / "src/netpulse" / name).read_bytes(), name
    script = next(name for name in wheel.namelist() if name.endswith(".data/scripts/netpulse-ctl"))
    assert wheel.read(script) == (ROOT / "src/netpulse/ctl.sh").read_bytes()
print("Wheel contents verified.")
