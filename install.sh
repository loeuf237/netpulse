#!/usr/bin/env bash
# =====================================================================
# NetPulse - Script d'installation automatique
# =====================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_USER="$(whoami)"
HOME_DIR="$HOME"
BIN_DIR="$HOME_DIR/.local/bin"
APP_DIR="$HOME_DIR/.local/share/applications"
ICON_DIR="$HOME_DIR/.local/share/icons/hicolor"
SYSTEMD_USER_DIR="$HOME_DIR/.config/systemd/user"
EXT_DIR="$HOME_DIR/.local/share/gnome-shell/extensions/force-proxy@paulin"

echo "=========================================================="
echo "    Installation de NetPulse — Moniteur Réseau & Pare-feu "
echo "=========================================================="
echo

# 1. Vérification des dépendances système
echo "[1/7] Vérification et installation des paquets requis..."
MISSING_PKGS=()
for pkg in python3-psutil gir1.2-adw-1 gir1.2-gtk-4.0 gir1.2-dbusmenu-glib-0.4 iptables iproute2; do
    if ! dpkg -s "$pkg" >/dev/null 2>&1; then
        MISSING_PKGS+=("$pkg")
    fi
done

if [ ${#MISSING_PKGS[@]} -gt 0 ]; then
    echo "Installation des dépendances manquantes : ${MISSING_PKGS[*]}..."
    sudo apt-get update -qq
    sudo apt-get install -y -qq "${MISSING_PKGS[@]}"
else
    echo "Toutes les dépendances requises sont déjà installées."
fi

# 2. Installation des exécutables
echo "[2/7] Installation des exécutables dans $BIN_DIR..."
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
echo "[3/7] Installation des icônes NetPulse..."
mkdir -p "$ICON_DIR/scalable/apps"
cp "$SCRIPT_DIR/icons/netpulse.svg" "$ICON_DIR/scalable/apps/netpulse.svg"

python3 -c "
import os
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk, GLib

svg_file = '$ICON_DIR/scalable/apps/netpulse.svg'
if os.path.exists(svg_file):
    svg_data = open(svg_file).read()
    b = GLib.Bytes.new(svg_data.encode('utf-8'))
    tex = Gdk.Texture.new_from_bytes(b)
    for s in [16, 24, 32, 48, 64, 128, 256, 512]:
        p = os.path.expanduser(f'~/.local/share/icons/hicolor/{s}x{s}/apps')
        os.makedirs(p, exist_ok=True)
        tex.save_to_png(os.path.join(p, 'netpulse.png'))
" 2>/dev/null || true

gtk-update-icon-cache -f -t "$ICON_DIR" 2>/dev/null || true

# 4. Installation du lanceur d'application (.desktop)
echo "[4/7] Enregistrement du lanceur de bureau..."
mkdir -p "$APP_DIR"
cp "$SCRIPT_DIR/desktop/netpulse.desktop" "$APP_DIR/netpulse.desktop"
update-desktop-database "$APP_DIR" 2>/dev/null || true

# 5. Configuration des droits sans mot de passe (sudoers) pour le pare-feu et le TUN
echo "[5/7] Configuration des privilèges réseau (Sudoers)..."
"$BIN_DIR/netpulse-ctl" update-sudoers 2>/dev/null || true

# 6. Installation de l'extension GNOME Shell (Indicateur barre supérieure)
echo "[6/7] Installation de l'extension GNOME Shell..."
if [ -d "$SCRIPT_DIR/extension" ]; then
    mkdir -p "$EXT_DIR"
    cp -r "$SCRIPT_DIR/extension/"* "$EXT_DIR/"
    gnome-extensions enable force-proxy@paulin 2>/dev/null || true
fi

# 7. Activation du service d'arrière-plan (systemd user)
echo "[7/7] Démarrage du service d'arrière-plan..."
mkdir -p "$SYSTEMD_USER_DIR"
cp "$SCRIPT_DIR/systemd/netpulse-monitor.service" "$SYSTEMD_USER_DIR/netpulse-monitor.service"
systemctl --user daemon-reload
systemctl --user enable --now netpulse-monitor.service

echo
echo "=========================================================="
echo "    Installation terminée avec succès !"
echo "=========================================================="
echo "Vous pouvez désormais :"
echo "  • Lancer l'application graphique : tapez 'netpulse' ou ouvrez 'NetPulse' depuis vos applications."
echo "  • Utiliser la ligne de commande : 'netpulse-ctl status', 'netpulse-ctl block-app <nom>'."
echo "=========================================================="
