# NetPulse

[![CI/CD](https://github.com/loeuf237/netpulse/actions/workflows/validate.yml/badge.svg)](https://github.com/loeuf237/netpulse/actions/workflows/validate.yml)
[![Latest release](https://img.shields.io/github/v/release/loeuf237/netpulse)](https://github.com/loeuf237/netpulse/releases)

NetPulse is a Linux desktop network monitor, application firewall and IPv4 TUN
proxy controller. Its GTK4/Libadwaita interface shows physical network traffic,
application activity, routing assignments, connection diagnostics and local usage
history. A GNOME Shell indicator displays live speeds in the top bar.

The interface, notifications, command-line messages and documentation use English.

## Features

- **Live traffic:** download/upload graphs, physical interface totals, application
  TCP samples, remote addresses and asynchronous reverse DNS lookups.
- **Application firewall:** persistent application block lists and kernel cgroup
  assignments, with applied, pending and failed states.
- **TUN proxy routing:** IPv4 routing through SOCKS4, SOCKS5 or HTTP proxies using
  tun2socks; global, include and exclude modes; optional FTP bypass.
- **Protected connections:** enabled by default. Automatic assignments are deferred
  while a protected tunnel is active, and desktop network changes require confirmation.
  Protected indicator/tray shortcuts open the interface to confirm changes.
- **Read-only diagnostics:** proxy TCP reachability, tunnel state, DNS and HTTPS
  response time. A TCP connection does not verify proxy credentials, and the HTTPS
  probe follows the current route rather than forcing a particular proxy.
- **Local history:** today, seven-day and thirty-day views, daily totals,
  application rankings and CSV export, with configurable retention.
- **Alerts:** two failed server checks, a daily quota or sustained application TCP
  speed. Alerts never restart the proxy or change network configuration.
- **Profiles:** create, edit and delete server/routing profiles locally. Activation
  is explicit; the tunnel is reused when the proxy URL is unchanged.

## Ubuntu compatibility and CI coverage

| Ubuntu | Automated tests | Desktop with stock packages |
| --- | --- | --- |
| **18.04** | Controller and history/diagnostics/profile logic; syntax and wheel build, using managed Python 3.10 | Unsupported: Python 3.6 and no required GTK4/Libadwaita stack |
| **22.04** | Core, monitor, migration, generated executable and installer tests; wheel build with Python 3.10 | Unsupported: stock GTK/Libadwaita are older than the interface requires |
| **26.04** | Full Python suite, real GTK widgets in Xvfb, syntax and wheel build | Supported desktop target |

The desktop requires **Python 3.10+, GTK 4.8+, Libadwaita 1.4+, librsvg 2.46+**,
PyGObject, Pycairo, psutil, systemd, iproute2, iptables with cgroup support and a
working cgroup v2 hierarchy. The GNOME extension declares Shell versions 46–50.
The bundled tun2socks executable targets **Linux x86_64**.

Each Ubuntu matrix entry uses its actual Ubuntu container userspace on a hosted
runner. Checkout and other Node-based actions run on the host so Ubuntu 18.04's
older glibc does not prevent workflow startup. Containers share the host kernel;
these tests do not certify old kernels, live firewall behavior, an interactive
GNOME session or an end-to-end proxy server. Network-changing calls are mocked.
Testing selected components on an old Ubuntu release does not make its desktop
stack supported.

## Install

Download the Linux x86_64 bundle and `SHA256SUMS` from
[GitHub Releases](https://github.com/loeuf237/netpulse/releases/latest).
For version 1.2.0:

```bash
# Check the selected archive against the published checksum.
grep '  netpulse-1.2.0-linux-x86_64.tar.gz$' SHA256SUMS | sha256sum -c -
tar -xzf netpulse-1.2.0-linux-x86_64.tar.gz
cd netpulse-1.2.0
./install.sh
```

Run the installer as your desktop user. It installs required Ubuntu packages,
user launchers/icons, a systemd user service and the GNOME extension. It also
installs a root-owned controller and tun2socks under `/usr/local/libexec/netpulse`,
with a scoped sudoers entry for privileged network operations.

Open **NetPulse** from your applications or run `netpulse`. Configure the proxy in
**Proxy Server**. Starting a tunnel or activating a profile requires an explicit
confirmation when connection protection is enabled. A change to another server
can interrupt existing connections.

The Python wheel and source distribution are also published. `pip install` alone
does not install the network helper, sudoers rule, systemd service, icons, GNOME
extension or tun2socks; use the installable bundle for the desktop application.

## Upgrade while keeping an active connection

Extract the new bundle without deleting the existing installation. If the
privileged controller differs, update that file first; this only replaces an
executable and does not invoke network commands:

```bash
sudo install -o root -g root -m 755 bin/netpulse-ctl /usr/local/libexec/netpulse/netpulse-ctl
python3 live-upgrade.py
```

The upgrade script checks the active tunnel, backs up installed files, replaces
and restarts the monitor with session-resume/protection flags, and opens the new
interface while leaving existing windows open. It verifies the tunnel identity,
routes and TUN parameters. It does not activate a profile or reload GNOME Shell.
The updated extension is loaded in the next GNOME session. The script requires
an existing active tunnel; use the normal installer for a fresh installation.

Saved profile names and historical event text remain as originally entered or
recorded. New events and interface labels use English. Session counters and the
history database are preserved. Avoid uninstalling as part of an active upgrade:
uninstall stops the proxy and removes its network rules.

## Data and measurement semantics

| Location | Content |
| --- | --- |
| `~/.config/force-proxy/config.json` | Preferences, thresholds and protection settings |
| `~/.config/force-proxy/profiles.json` | Local profiles, potentially including proxy credentials; mode `0600` |
| `~/.config/force-proxy/blocked_apps.txt` | Persistent application block list |
| `~/.config/force-proxy/split_apps.txt` | Selected split tunneling applications |
| `~/.local/state/netpulse/history.sqlite3` | Local history and events; honors `XDG_STATE_HOME` |
| `/tmp/netpulse_stats.json` | Current monitor snapshot consumed by the interface and indicator |
| `/run/netpulse/` | Privileged tunnel PID, state and routing metadata |
| `~/.local/state/netpulse/backups/` | Backups and verification reports from live upgrades |

History starts when recording is enabled; it does not reconstruct earlier usage.
Global totals count TCP+UDP on physical interfaces. Application totals are sampled
TCP counters and must not be added to global totals. Applied assignments indicate
the observed kernel cgroup; sockets opened earlier may retain their old route.
Byte units use powers of 1024 (`KiB`, `MiB`); bit units use powers of 1000.
Resetting a session does not erase history. Retention defaults to 90 days.

Diagnostics default to an HTTPS HEAD request to `https://github.com` every 60
seconds; both URL and interval are configurable. Daily and application-speed alerts
are disabled until their thresholds are set above zero. Credentials are masked in
profile descriptions and omitted from history exports.

## Command line

```bash
netpulse-ctl status --json
netpulse-ctl split-status --json
netpulse-ctl ftp-status
netpulse-ctl help
```

Commands such as `start`, `stop`, `quit`, `split-mode`, `block-app`, `ftp-bypass`
and `optimize` can change or stop the current connection. CLI commands are explicit
administrative actions and do not show the GTK confirmation dialog.

## Development

`src/netpulse/` is authoritative. Regenerate the standalone executables after
changing the Python sources or controller:

```bash
python3 tools/build_executables.py
python3 tools/build_executables.py --check
python3 tools/run_tests.py --suite full
node tests/test_extension.cjs
GSETTINGS_BACKEND=memory GTK_A11Y=none GSK_RENDERER=cairo \
  dbus-run-session -- xvfb-run -a python3 tools/gui_smoke.py
python3 -m build
python3 tools/check_wheel.py dist/*.whl
python3 tools/release.py --dist dist
```

The full suite needs the desktop libraries above, `python3-gi-cairo`,
`gsettings-desktop-schemas`, Xvfb and a D-Bus session. The `core` and `monitor`
tiers are available through `tools/run_tests.py --suite ...`; the core tier uses
only Python's standard library and Bash. `tools/ci_ubuntu.sh` installs test
dependencies **inside a disposable container**, and is not a host setup script.

## CI/CD and releases

[GitHub Actions](https://github.com/loeuf237/netpulse/actions/workflows/validate.yml)
runs on pushes, pull requests and manual dispatch. It checks generated executables,
syntax, Python/Bash tests in the three Ubuntu userspaces, GNOME extension tests,
GTK widgets, wheel contents and version consistency. Tested wheels are retained as
workflow artifacts. The packaging job produces an installable Linux bundle,
Python wheel, source distribution and `SHA256SUMS`.

To publish a release, update the version in `pyproject.toml`, `setup.py` and
`src/netpulse/__init__.py`, write `releases/vX.Y.Z.md`, regenerate executables,
commit and push an annotated `vX.Y.Z` tag. All test jobs must pass before CD
publishes the curated notes and verified artifacts. Ordinary pushes and pull
requests never publish a release. Workflow access is read-only except for the
release job's `contents: write` permission; no production network is deployed.

See [CHANGELOG.md](CHANGELOG.md), [1.2.0 notes](releases/v1.2.0.md) and
[1.1.0 notes](releases/v1.1.0.md). Earlier audit documents are preserved as
historical reports.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE). The bundled tun2socks executable uses
the MIT license; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
