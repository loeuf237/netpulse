#!/usr/bin/env bash
# =====================================================================
# NetPulse - Script d'installation automatique
# =====================================================================

set -e

if [ "$(id -u)" -eq 0 ]; then
    echo "Run ./install.sh as your desktop user; sudo is used when needed." >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_USER="$(whoami)"
HOME_DIR="$HOME"
BIN_DIR="$HOME_DIR/.local/bin"
APP_DIR="$HOME_DIR/.local/share/applications"
ICON_DIR="$HOME_DIR/.local/share/icons/hicolor"
ROOT_BIN_DIR="/usr/local/libexec/netpulse"
SYSTEMD_USER_DIR="$HOME_DIR/.config/systemd/user"
EXT_DIR="$HOME_DIR/.local/share/gnome-shell/extensions/force-proxy@paulin"

echo "=========================================================="
echo "    NetPulse Installation — Network Monitor & Firewall "
echo "=========================================================="
echo

# 1. Vérification des dépendances système
echo "[1/7] Checking and installing required packages..."
MISSING_PKGS=()
for pkg in python3-gi python3-cairo python3-gi-cairo gir1.2-rsvg-2.0 python3-psutil gir1.2-adw-1 gir1.2-gtk-4.0 gir1.2-dbusmenu-glib-0.4 gsettings-desktop-schemas iptables iproute2; do
    if ! dpkg -s "$pkg" >/dev/null 2>&1; then
        MISSING_PKGS+=("$pkg")
    fi
done

if [ ${#MISSING_PKGS[@]} -gt 0 ]; then
    echo "Installing missing dependencies: ${MISSING_PKGS[*]}..."
    sudo apt-get update -qq
    sudo apt-get install -y -qq "${MISSING_PKGS[@]}"
else
    echo "All required dependencies are already installed."
fi

# 2. Installation des exécutables
echo "[2/7] Installing executables in $BIN_DIR..."
mkdir -p "$BIN_DIR"

install -m 755 "$SCRIPT_DIR/bin/netpulse-gui" "$BIN_DIR/netpulse-gui"
install -m 755 "$SCRIPT_DIR/bin/netpulse-monitor" "$BIN_DIR/netpulse-monitor"
install -m 755 "$SCRIPT_DIR/bin/netpulse-ctl" "$BIN_DIR/netpulse-ctl"
if [ -f "$SCRIPT_DIR/bin/tun2socks" ]; then
    install -m 755 "$SCRIPT_DIR/bin/tun2socks" "$BIN_DIR/tun2socks"
fi

chmod +x "$BIN_DIR/netpulse-gui"
chmod +x "$BIN_DIR/netpulse-monitor"
chmod +x "$BIN_DIR/netpulse-ctl"
chmod +x "$BIN_DIR/tun2socks" 2>/dev/null || true

# Symlinks pratiques et rétrocompatibilité
ln -sf "$BIN_DIR/netpulse-gui" "$BIN_DIR/netpulse"
ln -sf "$BIN_DIR/netpulse-gui" "$BIN_DIR/force-proxy-gui"
ln -sf "$BIN_DIR/netpulse-monitor" "$BIN_DIR/force-proxy-monitor"
ln -sf "$BIN_DIR/netpulse-ctl" "$BIN_DIR/force-proxy-ctl"

# 3. Installation des icônes (Vectoriel SVG + PNG multi-résolutions)
echo "[3/7] Installing NetPulse icons..."
mkdir -p "$ICON_DIR/scalable/apps"
cp "$SCRIPT_DIR/icons/netpulse.svg" "$ICON_DIR/scalable/apps/netpulse.svg"

python3 - "$ICON_DIR" <<'PYICONS'
import os, sys, cairo, gi
gi.require_version("Rsvg", "2.0")
from gi.repository import Rsvg
icon_dir = sys.argv[1]
handle = Rsvg.Handle.new_from_file(os.path.join(icon_dir, "scalable/apps/netpulse.svg"))
for size in (16, 24, 32, 48, 64, 128, 256, 512):
    destination = os.path.join(icon_dir, f"{size}x{size}", "apps")
    os.makedirs(destination, exist_ok=True)
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    viewport = Rsvg.Rectangle()
    viewport.x, viewport.y, viewport.width, viewport.height = 0, 0, size, size
    handle.render_document(cairo.Context(surface), viewport)
    surface.write_to_png(os.path.join(destination, "netpulse.png"))
PYICONS

gtk-update-icon-cache -f -t "$ICON_DIR" 2>/dev/null || true

# 4. Installation du lanceur d'application (.desktop)
echo "[4/7] Registering the desktop launcher..."
mkdir -p "$APP_DIR"
cp "$SCRIPT_DIR/desktop/netpulse.desktop" "$APP_DIR/netpulse.desktop"
python3 - "$APP_DIR/netpulse.desktop" "$BIN_DIR/netpulse-gui" <<'PYDESKTOP'
import pathlib, sys
path = pathlib.Path(sys.argv[1])
executable = sys.argv[2].replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$").replace("%", "%%")
path.write_text("\n".join(f'Exec="{executable}"' if line.startswith("Exec=") else line
                          for line in path.read_text().splitlines()) + "\n")
PYDESKTOP
update-desktop-database "$APP_DIR" 2>/dev/null || true

# 5. Configuration des droits sans mot de passe (sudoers) pour le pare-feu et le TUN
echo "[5/7] Configuring network privileges (sudoers)..."
sudo install -d -o root -g root -m 755 "$ROOT_BIN_DIR"
sudo install -o root -g root -m 755 "$SCRIPT_DIR/bin/netpulse-ctl" "$ROOT_BIN_DIR/netpulse-ctl"
sudo install -o root -g root -m 755 "$SCRIPT_DIR/bin/tun2socks" "$ROOT_BIN_DIR/tun2socks"
sudo "$ROOT_BIN_DIR/netpulse-ctl" update-sudoers

# 6. Installation de l'extension GNOME Shell (Indicateur barre supérieure)
echo "[6/7] Installing the GNOME Shell extension..."
if [ -d "$SCRIPT_DIR/extension" ]; then
    mkdir -p "$EXT_DIR"
    cp -r "$SCRIPT_DIR/extension/"* "$EXT_DIR/"
    gnome-extensions enable force-proxy@paulin 2>/dev/null || true
fi

# 7. Activation du service d'arrière-plan (systemd user)
echo "[7/7] Starting the background service..."
mkdir -p "$SYSTEMD_USER_DIR"
systemctl --user stop force-proxy-monitor.service 2>/dev/null || true
systemctl --user disable force-proxy-monitor.service 2>/dev/null || true
rm -f "$SYSTEMD_USER_DIR/force-proxy-monitor.service"
rm -f "$SYSTEMD_USER_DIR/default.target.wants/force-proxy-monitor.service"

cp "$SCRIPT_DIR/systemd/netpulse-monitor.service" "$SYSTEMD_USER_DIR/netpulse-monitor.service"
systemctl --user daemon-reload
systemctl --user enable netpulse-monitor.service
systemctl --user restart netpulse-monitor.service

echo
echo "=========================================================="
echo "    Installation completed successfully!"
echo "=========================================================="
echo "You can now:"
echo "  • Launch the interface: run 'netpulse' or open 'NetPulse' from your applications."
echo "  • Use the command line: 'netpulse-ctl status', 'netpulse-ctl block-app <name>'."
echo "=========================================================="
