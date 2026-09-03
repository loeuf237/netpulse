#!/usr/bin/env bash
# =====================================================================
# NetPulse - Script de désinstallation
# =====================================================================

set -e

TARGET_USER="$(whoami)"
HOME_DIR="$HOME"
BIN_DIR="$HOME_DIR/.local/bin"
APP_DIR="$HOME_DIR/.local/share/applications"
ICON_DIR="$HOME_DIR/.local/share/icons/hicolor"
SYSTEMD_USER_DIR="$HOME_DIR/.config/systemd/user"
EXT_DIR="$HOME_DIR/.local/share/gnome-shell/extensions/force-proxy@paulin"

echo "=========================================================="
echo "    Désinstallation de NetPulse"
echo "=========================================================="
echo

# 1. Arrêt du proxy et du pare-feu s'ils sont actifs
if [ -x "$BIN_DIR/netpulse-ctl" ]; then
    echo "Arrêt des services réseau et réinitialisation du pare-feu..."
    "$BIN_DIR/netpulse-ctl" stop 2>/dev/null || true
    "$BIN_DIR/netpulse-ctl" firewall-reset 2>/dev/null || true
fi

# 2. Arrêt du service systemd
echo "Arrêt et désactivation du service systemd utilisateur..."
systemctl --user stop netpulse-monitor.service 2>/dev/null || true
systemctl --user stop force-proxy-monitor.service 2>/dev/null || true
systemctl --user disable netpulse-monitor.service 2>/dev/null || true
systemctl --user disable force-proxy-monitor.service 2>/dev/null || true
rm -f "$SYSTEMD_USER_DIR/netpulse-monitor.service"
rm -f "$SYSTEMD_USER_DIR/force-proxy-monitor.service"
systemctl --user daemon-reload

# 3. Suppression des exécutables
echo "Suppression des exécutables dans $BIN_DIR..."
rm -f "$BIN_DIR/netpulse"
rm -f "$BIN_DIR/netpulse-gui"
rm -f "$BIN_DIR/netpulse-monitor"
rm -f "$BIN_DIR/netpulse-ctl"
rm -f "$BIN_DIR/force-proxy-gui"
rm -f "$BIN_DIR/force-proxy-monitor"
rm -f "$BIN_DIR/force-proxy-ctl"

# 4. Suppression des raccourcis et icônes
echo "Suppression du lanceur et des icônes..."
rm -f "$APP_DIR/netpulse.desktop"
rm -f "$APP_DIR/force-proxy-settings.desktop"
update-desktop-database "$APP_DIR" 2>/dev/null || true

rm -f "$ICON_DIR/scalable/apps/netpulse.svg"
for s in 16 24 32 48 64 128 256 512; do
    rm -f "$ICON_DIR/${s}x${s}/apps/netpulse.png"
done
gtk-update-icon-cache -f -t "$ICON_DIR" 2>/dev/null || true

# 5. Suppression de la règle sudoers
echo "Suppression de la règle sudoers..."
sudo rm -f /etc/sudoers.d/netpulse
sudo rm -f /etc/sudoers.d/force-proxy

# 6. Suppression de l'extension GNOME
echo "Désactivation et suppression de l'extension GNOME..."
gnome-extensions disable force-proxy@paulin 2>/dev/null || true
rm -rf "$EXT_DIR"

echo
echo "NetPulse a été complètement désinstallé de votre système."
