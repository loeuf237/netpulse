#!/usr/bin/env bash
# Run inside an unprivileged Docker container, never against the desktop network.
set -euo pipefail
expected_release="${1:?Ubuntu release required}"
. /etc/os-release
if [ "$ID" != ubuntu ] || [ "$VERSION_ID" != "$expected_release" ]; then
    echo "Unexpected test OS: $PRETTY_NAME (expected Ubuntu $expected_release)" >&2
    exit 1
fi
export DEBIAN_FRONTEND=noninteractive
export LANG=C.UTF-8 LC_ALL=C.UTF-8
export GSETTINGS_BACKEND=memory GTK_A11Y=none GSK_RENDERER=cairo
apt-get update -qq
apt-get install -y --no-install-recommends ca-certificates curl git iproute2
case "$expected_release" in
    18.04)
        # Stock 3.6 cannot execute this project's Python >=3.10 sources.
        # uv's x86_64 Linux builds support Bionic's glibc 2.27.
        curl --fail --silent --show-error --location --retry 3 \
            https://astral.sh/uv/0.9.7/install.sh -o /tmp/install-uv.sh
        UV_INSTALL_DIR=/opt/uv UV_NO_MODIFY_PATH=1 sh /tmp/install-uv.sh
        /opt/uv/uv python install 3.10
        /opt/uv/uv venv --python 3.10 /opt/netpulse-ci
        /opt/uv/uv pip install --python /opt/netpulse-ci/bin/python build
        test_suite=core
        ;;
    22.04|26.04)
        apt-get install -y --no-install-recommends python3 python3-venv python3-gi \
            python3-cairo python3-gi-cairo python3-psutil gir1.2-rsvg-2.0 \
            gsettings-desktop-schemas
        if [ "$expected_release" = 26.04 ]; then
            apt-get install -y --no-install-recommends gir1.2-gtk-4.0 gir1.2-adw-1 xvfb xauth dbus-x11
            test_suite=full
        else
            test_suite=monitor
        fi
        /usr/bin/python3 -m venv --system-site-packages /opt/netpulse-ci
        /opt/netpulse-ci/bin/python -m pip install build
        ;;
    *) echo "Unsupported CI release: $expected_release" >&2; exit 1 ;;
esac
export PATH="/opt/netpulse-ci/bin:$PATH"
python --version
python tools/build_executables.py --check
bash -n install.sh uninstall.sh src/netpulse/ctl.sh bin/netpulse-ctl
python -m compileall -q src tests tools live-upgrade.py
python -m py_compile bin/netpulse-gui bin/netpulse-monitor
python tools/run_tests.py --suite "$test_suite"
if [ "$test_suite" = full ]; then
    dbus-run-session -- xvfb-run -a python tools/gui_smoke.py
fi
python -m build --wheel --outdir "/artifacts/$expected_release"
python tools/check_wheel.py "/artifacts/$expected_release/"*.whl
printf 'Ubuntu %s: %s suite and packaging passed.\n' "$expected_release" "$test_suite"
