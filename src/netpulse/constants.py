"""
Constantes et chemins de configuration pour NetPulse.
"""

import os

APP_ID = "org.antigravity.NetPulse"
CONFIG_DIR = os.path.expanduser("~/.config/force-proxy")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
BLOCKED_FILE = os.path.join(CONFIG_DIR, "blocked_apps.txt")
SPLIT_APPS_FILE = os.path.join(CONFIG_DIR, "split_apps.txt")
STATS_PATH = "/tmp/netpulse_stats.json"
RESET_FLAG_PATH = "/tmp/netpulse_reset_flag"
PID_FILE = "/tmp/netpulse_monitor.pid"

DEFAULT_CONFIG = {
    "refresh_interval": 1,
    "unit_mode": "auto",
    "show_download": True,
    "show_upload": True,
    "show_session_total": True,
    "autostart": True,
    "split_tunnel_mode": "disabled"
}

