#!/usr/bin/env bash
# force-proxy-ctl: Management script for transparent TUN proxy routing

TUN_NAME="tun-proxy"
PID_FILE="/tmp/force-proxy.pid"
STATE_FILE="/tmp/force-proxy-current.txt"
LOG_FILE="/tmp/tun2socks.log"
TARGET_USER="paulin"
TUN2SOCKS_BIN="/home/paulin/.local/bin/tun2socks"
REAL_SCRIPT="$(readlink -f "$0")"

SPLIT_DIR="/home/$TARGET_USER/.config/force-proxy"
SPLIT_FILE="$SPLIT_DIR/split_apps.txt"
CONFIG_FILE="$SPLIT_DIR/config.json"
CGROUP_PROXY="/sys/fs/cgroup/net_proxy"
CGROUP_DIRECT="/sys/fs/cgroup/net_direct"
CGROUP_BLOCKED="/sys/fs/cgroup/net_blocked"

# Quick check command for sudo validation
if [ "$1" = "check-sudo" ]; then
    exit 0
fi

CMD_NAME="$(basename "$0")"
if [ "$CMD_NAME" = "force-proxy-ctl" ] || [ "$CMD_NAME" = "bash" ]; then
    CMD_NAME="netpulse-ctl"
fi

show_help() {
    cat << EOF
NetPulse CLI - Contrôleur Réseau, Forçage Proxy TUN & Pare-feu Applicatif

Utilisation :
  $CMD_NAME <commande> [options]

Gestion du Forçage Proxy (Mode TUN) :
  status [--json]          Afficher l'état du routage TUN et du proxy configuré
  start [proxy_url]        Activer le forçage TUN global (ex: socks5://127.0.0.1:1080)
  stop                     Désactiver le forçage TUN et rétablir la connexion normale
  toggle [proxy_url]       Basculer l'état du forçage TUN (démarrer / arrêter)

Routage Sélectif (Split Tunneling) :
  split-status [--json]    Afficher l'état du split tunneling et les applications actives
  split-mode [mode]        Définir ou afficher le mode : disabled, include, exclude
  split-add <nom>          Ajouter une application à la liste (ex: telegram, steam, chrome)
  split-del <nom>          Retirer une application de la liste
  split-list               Lister toutes les applications configurées
  split-assign <pid> <dst> Assigner un PID vers un routage (proxy, direct, default)
  split-sync               Synchroniser tous les processus actifs selon le mode

Contournement FTP (Protection des transferts de fichiers) :
  ftp-status               Afficher l'état du contournement FTP et des règles de routage
  ftp-bypass [on|off]      Activer ou désactiver l'exemption automatique du trafic FTP (actif par défaut)

Pare-feu Applicatif (GlassWire Killswitch) :
  block-app <nom>          Bloquer tout accès réseau pour une application (ex: steam, chrome)
  unblock-app <nom>        Débloquer une application et rétablir son accès internet
  block <pid>              Bloquer immédiatement les sockets et paquets d'un PID
  unblock <pid>            Débloquer un PID
  firewall-init            Initialiser les règles noyau cgroup v2 & iptables
  firewall-reset           Réinitialiser et supprimer toutes les règles de filtrage

Général :
  gui, open                Ouvrir l'interface graphique NetPulse
  reset-session            Réinitialiser les compteurs de session réseau (débits / volumes)
  quit, exit               Fermer complètement NetPulse (démon, interface et proxy)
  help, -h, --help         Afficher cette aide

Exemples :
  $CMD_NAME status
  $CMD_NAME split-mode include
  $CMD_NAME split-add telegram
  $CMD_NAME split-status
EOF
}

get_status() {
    local running=1
    if pgrep -f "tun2socks.*${TUN_NAME}" >/dev/null 2>&1 && ip link show "${TUN_NAME}" >/dev/null 2>&1; then
        if ip route show 0.0.0.0/1 2>/dev/null | grep -q "${TUN_NAME}" || ip route show table 100 2>/dev/null | grep -q "${TUN_NAME}"; then
            running=0
        fi
    fi
    return $running
}

read_split_mode() {
    if [ -f "$CONFIG_FILE" ]; then
        mode=$(grep -oP '"split_tunnel_mode"\s*:\s*"\K[^"]+' "$CONFIG_FILE" 2>/dev/null)
        if [ -n "$mode" ]; then
            echo "$mode"
            return 0
        fi
    fi
    echo "disabled"
}

save_split_mode() {
    local new_mode="$1"
    mkdir -p "$SPLIT_DIR"
    if [ ! -f "$CONFIG_FILE" ]; then
        echo "{ \"split_tunnel_mode\": \"$new_mode\" }" > "$CONFIG_FILE"
    else
        if grep -q '"split_tunnel_mode"' "$CONFIG_FILE" 2>/dev/null; then
            sed -i -E "s/\"split_tunnel_mode\"\s*:\s*\"[^\"]*\"/\"split_tunnel_mode\": \"$new_mode\"/" "$CONFIG_FILE"
        else
            sed -i -E "s/(\s*)\}\s*$/,\n\1  \"split_tunnel_mode\": \"$new_mode\"\n}/" "$CONFIG_FILE"
        fi
    fi
    chown "$TARGET_USER:$TARGET_USER" "$CONFIG_FILE" 2>/dev/null || true
}

read_bypass_ftp() {
    if [ -f "$CONFIG_FILE" ]; then
        val=$(grep -oP '"bypass_ftp"\s*:\s*\K(true|false)' "$CONFIG_FILE" 2>/dev/null)
        if [ "$val" = "false" ]; then
            echo "0"
            return 0
        fi
    fi
    echo "1" # Actif par défaut
}

save_bypass_ftp() {
    local enabled="$1" # 1 ou 0
    local bool_str="true"
    [ "$enabled" = "0" ] || [ "$enabled" = "off" ] || [ "$enabled" = "false" ] && bool_str="false"
    mkdir -p "$SPLIT_DIR"
    if [ ! -f "$CONFIG_FILE" ]; then
        echo "{ \"bypass_ftp\": $bool_str }" > "$CONFIG_FILE"
    else
        if grep -q '"bypass_ftp"' "$CONFIG_FILE" 2>/dev/null; then
            sed -i -E "s/\"bypass_ftp\"\s*:\s*(true|false)/\"bypass_ftp\": $bool_str/" "$CONFIG_FILE"
        else
            sed -i -E "s/(\s*)\}\s*$/,\n\1  \"bypass_ftp\": $bool_str\n}/" "$CONFIG_FILE"
        fi
    fi
    chown "$TARGET_USER:$TARGET_USER" "$CONFIG_FILE" 2>/dev/null || true
}

# Commandes exécutables immédiatement sans droits root
case "$1" in
    ""|-h|--help|help)
        show_help
        exit 0
        ;;
    gui|open)
        gtk-launch netpulse 2>/dev/null || nohup /home/paulin/.local/bin/force-proxy-gui >/dev/null 2>&1 &
        exit 0
        ;;
    reset-session|reset)
        /home/paulin/.local/bin/netpulse-monitor --reset 2>/dev/null || /home/paulin/.local/bin/force-proxy-monitor --reset 2>/dev/null || true
        exit 0
        ;;
    quit|exit)
        echo "Fermeture complète de NetPulse..."
        systemctl --user stop netpulse-monitor.service 2>/dev/null || true
        systemctl --user stop force-proxy-monitor.service 2>/dev/null || true
        pkill -f netpulse-gui 2>/dev/null || true
        pkill -f force-proxy-gui 2>/dev/null || true
        if get_status; then
            "$REAL_SCRIPT" stop 2>/dev/null || true
        fi
        echo "NetPulse arrêté avec succès."
        exit 0
        ;;
    split-list)
        if [ -f "$SPLIT_FILE" ]; then
            cat "$SPLIT_FILE"
        fi
        exit 0
        ;;
    split-mode)
        if [ -z "$2" ]; then
            read_split_mode
            exit 0
        fi
        ;;
    split-status)
        mode=$(read_split_mode)
        app_count=0
        [ -f "$SPLIT_FILE" ] && app_count=$(grep -cv '^\s*$' "$SPLIT_FILE" 2>/dev/null || echo 0)
        proxy_pids_count=0
        [ -f "$CGROUP_PROXY/cgroup.procs" ] && proxy_pids_count=$(wc -l < "$CGROUP_PROXY/cgroup.procs" 2>/dev/null || echo 0)
        direct_pids_count=0
        [ -f "$CGROUP_DIRECT/cgroup.procs" ] && direct_pids_count=$(wc -l < "$CGROUP_DIRECT/cgroup.procs" 2>/dev/null || echo 0)

        if [ "$2" = "--json" ]; then
            apps_json="[]"
            if [ -f "$SPLIT_FILE" ]; then
                apps_json=$(python3 -c "import json; print(json.dumps([l.strip().lower() for l in open('$SPLIT_FILE') if l.strip()]))" 2>/dev/null || echo "[]")
            fi
            echo "{\"mode\": \"$mode\", \"apps_count\": $app_count, \"proxy_pids\": $proxy_pids_count, \"direct_pids\": $direct_pids_count, \"apps\": $apps_json}"
            exit 0
        fi

        echo "--- État du Split Tunneling NetPulse ---"
        echo "Mode actuel : $mode"
        case "$mode" in
            include)
                echo "Comportement : Mode Inclusif (Seules les $app_count applications configurées transitent par le proxy TUN)"
                ;;
            exclude)
                echo "Comportement : Mode Exclusif (Tout le PC transite par le proxy SAUF les $app_count applications configurées)"
                ;;
            disabled|*)
                echo "Comportement : Désactivé (Tout le trafic de l'ordinateur transite par le proxy TUN)"
                ;;
        esac
        echo "Processus routés vers Proxy (cgroup net_proxy) : $proxy_pids_count"
        echo "Processus routés vers Direct (cgroup net_direct) : $direct_pids_count"
        if [ -f "$SPLIT_FILE" ] && [ "$app_count" -gt 0 ]; then
            echo "Applications enregistrées :"
            sed 's/^/  - /' "$SPLIT_FILE"
        else
            echo "Aucune application enregistrée."
        fi
        exit 0
        ;;
esac

read_gnome_proxy() {
    local socks_host socks_port http_host http_port
    if [ "$(id -u)" -eq 0 ]; then
        socks_host=$(sudo -u "$TARGET_USER" dconf read /system/proxy/socks/host 2>/dev/null | tr -d "'")
        socks_port=$(sudo -u "$TARGET_USER" dconf read /system/proxy/socks/port 2>/dev/null)
        http_host=$(sudo -u "$TARGET_USER" dconf read /system/proxy/http/host 2>/dev/null | tr -d "'")
        http_port=$(sudo -u "$TARGET_USER" dconf read /system/proxy/http/port 2>/dev/null)
    else
        socks_host=$(gsettings get org.gnome.system.proxy.socks host 2>/dev/null | tr -d "'")
        socks_port=$(gsettings get org.gnome.system.proxy.socks port 2>/dev/null)
        http_host=$(gsettings get org.gnome.system.proxy.http host 2>/dev/null | tr -d "'")
        http_port=$(gsettings get org.gnome.system.proxy.http port 2>/dev/null)
    fi

    if [ -n "$socks_host" ] && [ -n "$socks_port" ] && [ "$socks_port" -gt 0 ] 2>/dev/null; then
        echo "socks5://${socks_host}:${socks_port}"
    elif [ -n "$http_host" ] && [ -n "$http_port" ] && [ "$http_port" -gt 0 ] 2>/dev/null; then
        echo "http://${http_host}:${http_port}"
    elif [ -f "$STATE_FILE" ]; then
        cat "$STATE_FILE" 2>/dev/null
    fi
}

# -------------------------------------------------------------
# 1. STATUS: DOES NOT REQUIRE ROOT PRIVILEGES (NEVER CALL SUDO/PKEXEC)
# -------------------------------------------------------------
if [ "$1" = "status" ]; then
    split_mode=$(read_split_mode)
    bypass_ftp=$(read_bypass_ftp)
    ftp_desc="Désactivé"
    [ "$bypass_ftp" = "1" ] && ftp_desc="Actif"
    if [ "$2" = "--json" ]; then
        if get_status; then
            curr_proxy=$(cat "$STATE_FILE" 2>/dev/null || read_gnome_proxy)
            echo "{\"active\": true, \"proxy\": \"$curr_proxy\", \"device\": \"$TUN_NAME\", \"split_mode\": \"$split_mode\", \"bypass_ftp\": $([ "$bypass_ftp" = "1" ] && echo true || echo false)}"
            exit 0
        else
            gnome_proxy=$(read_gnome_proxy)
            echo "{\"active\": false, \"proxy\": \"$gnome_proxy\", \"device\": \"$TUN_NAME\", \"split_mode\": \"$split_mode\", \"bypass_ftp\": $([ "$bypass_ftp" = "1" ] && echo true || echo false)}"
            exit 0
        fi
    else
        if get_status; then
            curr_proxy=$(cat "$STATE_FILE" 2>/dev/null || read_gnome_proxy)
            echo "Proxy forcé actif sur ${TUN_NAME} -> ${curr_proxy} (Split Tunneling: ${split_mode}, Contournement FTP: ${ftp_desc})"
            exit 0
        else
            echo "Proxy forcé inactif (Contournement FTP: ${ftp_desc})"
            exit 0
        fi
    fi
fi

if [ "$1" = "ftp-status" ]; then
    bypass_ftp=$(read_bypass_ftp)
    rules_active="Non"
    if ip rule show 2>/dev/null | grep -q "dport 21.*lookup 200"; then
        rules_active="Oui"
    fi
    ct_loaded="Non"
    if lsmod 2>/dev/null | grep -q "nf_conntrack_ftp"; then
        ct_loaded="Oui"
    fi
    direct_pids=0
    if [ -f "$CGROUP_DIRECT/cgroup.procs" ]; then
        direct_pids=$(wc -l < "$CGROUP_DIRECT/cgroup.procs" 2>/dev/null || echo 0)
    fi

    if [ "$2" = "--json" ]; then
        echo "{\"bypass_ftp\": $([ "$bypass_ftp" = "1" ] && echo true || echo false), \"routing_rules_active\": $([ "$rules_active" = "Oui" ] && echo true || echo false), \"conntrack_helper\": $([ "$ct_loaded" = "Oui" ] && echo true || echo false), \"direct_pids\": $direct_pids}"
        exit 0
    fi

    echo "--- État du Contournement FTP NetPulse ---"
    if [ "$bypass_ftp" = "1" ]; then
        echo "Exemption FTP : Activée (Les flux FTP sont automatiquement acheminés hors du proxy)"
    else
        echo "Exemption FTP : Désactivée"
    fi
    echo "Règles de routage noyau actives : $rules_active"
    echo "Module conntrack FTP chargé : $ct_loaded"
    echo "Ports exemptés : 20 (données actives), 21 (contrôle FTP), 989/990 (FTPS), ports passifs dynamiques"
    echo "Applications FTP surveillées : FileZilla, gvfsd-ftp (Nautilus), lftp, ncftp, ftp, cyberduck"
    echo "Processus en mode direct (cgroup net_direct) : $direct_pids"
    exit 0
fi

# -------------------------------------------------------------
# 2. PRIVILEGE ESCALATION ONLY FOR ACTIONS REQUIRING ROOT
# -------------------------------------------------------------
if [ "$(id -u)" -ne 0 ]; then
    # 1. Try passwordless sudo first (configured via /etc/sudoers.d/netpulse)
    if sudo -n "$REAL_SCRIPT" check-sudo >/dev/null 2>&1; then
        exec sudo "$REAL_SCRIPT" "$@"
    fi

    # 2. If running interactively in a terminal, prompt via sudo in the terminal
    if [ -t 0 ] || [ -t 1 ]; then
        exec sudo "$REAL_SCRIPT" "$@"
    fi

    # 3. If explicitly requested with GUI prompt flag (from interactive GUI click)
    if [ "$NETPULSE_ALLOW_GUI_PROMPT" = "1" ]; then
        exec pkexec "$REAL_SCRIPT" "$@"
    fi

    # 4. In background / daemon / boot mode, NEVER pop up graphical pkexec prompts!
    echo "NetPulse: Privilèges root requis pour cette commande, mais la session est non-interactive et sudo sans mot de passe n'est pas encore actif." >&2
    exit 1
fi

# -------------------------------------------------------------
# 3. ACTIONS EXECUTED AS ROOT & SPLIT TUNNELING HELPERS
# -------------------------------------------------------------

get_net_info() {
    def_line=$(ip -4 route show default 2>/dev/null | grep -v "${TUN_NAME}" | head -n 1)
    [ -z "$def_line" ] && def_line=$(ip -4 route show 2>/dev/null | grep -v "${TUN_NAME}" | grep -E "via|default" | head -n 1)
    [ -z "$def_line" ] && def_line=$(ip -4 route show default 2>/dev/null | head -n 1)

    default_if=$(echo "$def_line" | awk '{for(i=1;i<=NF;i++) if($i=="dev") print $(i+1); exit}')
    default_gw=$(echo "$def_line" | awk '{for(i=1;i<=NF;i++) if($i=="via") print $(i+1); exit}')
    if [ -z "$default_gw" ] && [ -n "$default_if" ]; then
        default_gw=$(ip -4 route show dev "$default_if" 2>/dev/null | awk '/default via/ {print $3}' | head -n 1)
    fi
    if [ -n "$default_if" ]; then
        default_ip=$(ip -4 addr show dev "$default_if" 2>/dev/null | awk '/inet / {print $2}' | cut -d/ -f1 | head -n 1)
    fi
}

split_setup_rules() {
    get_net_info
    mkdir -p "$CGROUP_PROXY" "$CGROUP_DIRECT" "$CGROUP_BLOCKED"
    chown -R "$TARGET_USER:$TARGET_USER" "$CGROUP_PROXY" "$CGROUP_DIRECT" "$CGROUP_BLOCKED" 2>/dev/null || true

    # 1. iptables mangle OUTPUT marks
    iptables -t mangle -C OUTPUT -m cgroup --path "net_proxy" -j MARK --set-mark 0x1000 2>/dev/null || \
        iptables -t mangle -A OUTPUT -m cgroup --path "net_proxy" -j MARK --set-mark 0x1000
    iptables -t mangle -C OUTPUT -m cgroup --path "net_direct" -j MARK --set-mark 0x2000 2>/dev/null || \
        iptables -t mangle -A OUTPUT -m cgroup --path "net_direct" -j MARK --set-mark 0x2000

    ip6tables -t mangle -C OUTPUT -m cgroup --path "net_proxy" -j MARK --set-mark 0x1000 2>/dev/null || \
        ip6tables -t mangle -A OUTPUT -m cgroup --path "net_proxy" -j MARK --set-mark 0x1000 2>/dev/null || true
    ip6tables -t mangle -C OUTPUT -m cgroup --path "net_direct" -j MARK --set-mark 0x2000 2>/dev/null || \
        ip6tables -t mangle -A OUTPUT -m cgroup --path "net_direct" -j MARK --set-mark 0x2000 2>/dev/null || true

    # 2. ip rule policy routing
    ip rule add fwmark 0x1000/0x1000 table 100 priority 50 2>/dev/null || true
    ip rule add fwmark 0x2000/0x2000 table 200 priority 50 2>/dev/null || true

    # 3. routing table 100 -> proxy tun
    ip route replace default dev "${TUN_NAME}" table 100 2>/dev/null || true

    # 4. routing table 200 -> direct physical gateway & non-TUN routes
    if [ -n "$default_gw" ] && [ -n "$default_if" ]; then
        if [ -n "$default_ip" ]; then
            ip route replace default via "$default_gw" dev "$default_if" src "$default_ip" table 200 2>/dev/null || true
        else
            ip route replace default via "$default_gw" dev "$default_if" table 200 2>/dev/null || true
        fi
    elif [ -n "$default_if" ]; then
        ip route replace default dev "$default_if" table 200 2>/dev/null || true
    fi
    # Copy existing subnets and direct routes to table 200 (LAN subnets, local interfaces)
    ip -4 route show 2>/dev/null | grep -v "${TUN_NAME}" | grep -v "0.0.0.0/1" | grep -v "128.0.0.0/1" | while read -r r; do
        ip route replace $r table 200 2>/dev/null || true
    done

    # 5. FTP Traffic Exemption (Bypass FTP)
    if [ "$(read_bypass_ftp)" = "1" ]; then
        # Load netfilter FTP conntrack helper
        modprobe nf_conntrack_ftp 2>/dev/null || true

        # Raw CT helper for FTP control traffic (ports 21, 990)
        iptables -t raw -C OUTPUT -p tcp -m multiport --dports 21,990 -j CT --helper ftp 2>/dev/null || \
            iptables -t raw -A OUTPUT -p tcp -m multiport --dports 21,990 -j CT --helper ftp 2>/dev/null || true
        ip6tables -t raw -C OUTPUT -p tcp -m multiport --dports 21,990 -j CT --helper ftp 2>/dev/null || \
            ip6tables -t raw -A OUTPUT -p tcp -m multiport --dports 21,990 -j CT --helper ftp 2>/dev/null || true

        # Mangle FTP bypass rules: mark with 0x2000 (direct table 200)
        iptables -t mangle -C OUTPUT -p tcp -m multiport --dports 20,21,989,990 -j MARK --set-mark 0x2000 2>/dev/null || \
            iptables -t mangle -A OUTPUT -p tcp -m multiport --dports 20,21,989,990 -j MARK --set-mark 0x2000
        iptables -t mangle -C OUTPUT -p tcp -m multiport --sports 20,21,989,990 -j MARK --set-mark 0x2000 2>/dev/null || \
            iptables -t mangle -A OUTPUT -p tcp -m multiport --sports 20,21,989,990 -j MARK --set-mark 0x2000
        iptables -t mangle -C OUTPUT -m helper --helper ftp -j MARK --set-mark 0x2000 2>/dev/null || \
            iptables -t mangle -A OUTPUT -m helper --helper ftp -j MARK --set-mark 0x2000
        iptables -t mangle -C OUTPUT -p tcp -m conntrack --ctstate RELATED -m helper --helper ftp -j MARK --set-mark 0x2000 2>/dev/null || \
            iptables -t mangle -A OUTPUT -p tcp -m conntrack --ctstate RELATED -m helper --helper ftp -j MARK --set-mark 0x2000

        ip6tables -t mangle -C OUTPUT -p tcp -m multiport --dports 20,21,989,990 -j MARK --set-mark 0x2000 2>/dev/null || \
            ip6tables -t mangle -A OUTPUT -p tcp -m multiport --dports 20,21,989,990 -j MARK --set-mark 0x2000 2>/dev/null || true
        ip6tables -t mangle -C OUTPUT -p tcp -m multiport --sports 20,21,989,990 -j MARK --set-mark 0x2000 2>/dev/null || \
            ip6tables -t mangle -A OUTPUT -p tcp -m multiport --sports 20,21,989,990 -j MARK --set-mark 0x2000 2>/dev/null || true
        ip6tables -t mangle -C OUTPUT -m helper --helper ftp -j MARK --set-mark 0x2000 2>/dev/null || \
            ip6tables -t mangle -A OUTPUT -m helper --helper ftp -j MARK --set-mark 0x2000 2>/dev/null || true

        # IP policy rules for FTP socket routing (priority 40, before priority 50)
        ip rule add ipproto tcp dport 21 table 200 priority 40 2>/dev/null || true
        ip rule add ipproto tcp dport 990 table 200 priority 40 2>/dev/null || true
        ip rule add ipproto tcp dport 20 table 200 priority 40 2>/dev/null || true
        ip rule add ipproto tcp sport 20 table 200 priority 40 2>/dev/null || true
        ip rule add ipproto tcp dport 989 table 200 priority 40 2>/dev/null || true
        ip rule add ipproto tcp sport 989 table 200 priority 40 2>/dev/null || true
    fi

    # 6. Masquerade on physical interface so rerouted direct packets have correct source IP
    if [ -n "$default_if" ]; then
        iptables -t nat -C POSTROUTING -o "$default_if" -j MASQUERADE 2>/dev/null || \
            iptables -t nat -A POSTROUTING -o "$default_if" -j MASQUERADE 2>/dev/null || true
    fi
}

split_cleanup_rules() {
    # Move processes out of cgroups
    target_uid=$(id -u "$TARGET_USER" 2>/dev/null || echo 1000)
    for cg in "$CGROUP_PROXY" "$CGROUP_DIRECT"; do
        if [ -f "$cg/cgroup.procs" ]; then
            for p in $(cat "$cg/cgroup.procs" 2>/dev/null); do
                echo "$p" > "/sys/fs/cgroup/user.slice/user-${target_uid}.slice/user@${target_uid}.service/app.slice/cgroup.procs" 2>/dev/null || \
                echo "$p" > "/sys/fs/cgroup/cgroup.procs" 2>/dev/null || true
            done
        fi
    done

    # Remove iptables mangle rules
    iptables -t mangle -D OUTPUT -m cgroup --path "net_proxy" -j MARK --set-mark 0x1000 2>/dev/null || true
    iptables -t mangle -D OUTPUT -m cgroup --path "net_direct" -j MARK --set-mark 0x2000 2>/dev/null || true
    ip6tables -t mangle -D OUTPUT -m cgroup --path "net_proxy" -j MARK --set-mark 0x1000 2>/dev/null || true
    ip6tables -t mangle -D OUTPUT -m cgroup --path "net_direct" -j MARK --set-mark 0x2000 2>/dev/null || true

    # Remove FTP bypass rules
    iptables -t raw -D OUTPUT -p tcp -m multiport --dports 21,990 -j CT --helper ftp 2>/dev/null || true
    ip6tables -t raw -D OUTPUT -p tcp -m multiport --dports 21,990 -j CT --helper ftp 2>/dev/null || true
    iptables -t mangle -D OUTPUT -p tcp -m multiport --dports 20,21,989,990 -j MARK --set-mark 0x2000 2>/dev/null || true
    iptables -t mangle -D OUTPUT -p tcp -m multiport --sports 20,21,989,990 -j MARK --set-mark 0x2000 2>/dev/null || true
    iptables -t mangle -D OUTPUT -m helper --helper ftp -j MARK --set-mark 0x2000 2>/dev/null || true
    iptables -t mangle -D OUTPUT -p tcp -m conntrack --ctstate RELATED -m helper --helper ftp -j MARK --set-mark 0x2000 2>/dev/null || true

    ip6tables -t mangle -D OUTPUT -p tcp -m multiport --dports 20,21,989,990 -j MARK --set-mark 0x2000 2>/dev/null || true
    ip6tables -t mangle -D OUTPUT -p tcp -m multiport --sports 20,21,989,990 -j MARK --set-mark 0x2000 2>/dev/null || true
    ip6tables -t mangle -D OUTPUT -m helper --helper ftp -j MARK --set-mark 0x2000 2>/dev/null || true

    # Remove FTP ip rules
    ip rule del ipproto tcp dport 21 table 200 priority 40 2>/dev/null || true
    ip rule del ipproto tcp dport 990 table 200 priority 40 2>/dev/null || true
    ip rule del ipproto tcp dport 20 table 200 priority 40 2>/dev/null || true
    ip rule del ipproto tcp sport 20 table 200 priority 40 2>/dev/null || true
    ip rule del ipproto tcp dport 989 table 200 priority 40 2>/dev/null || true
    ip rule del ipproto tcp sport 989 table 200 priority 40 2>/dev/null || true

    # Remove routing rules & tables
    ip rule del fwmark 0x1000/0x1000 table 100 priority 50 2>/dev/null || true
    ip rule del fwmark 0x2000/0x2000 table 200 priority 50 2>/dev/null || true
    ip route flush table 100 2>/dev/null || true
    ip route flush table 200 2>/dev/null || true

    # Remove masquerade rule
    get_net_info
    if [ -n "$default_if" ]; then
        iptables -t nat -D POSTROUTING -o "$default_if" -j MASQUERADE 2>/dev/null || true
    fi
}

split_assign_pid() {
    local target_pid="$1"
    local destination="$2" # proxy, direct, default
    [ -z "$target_pid" ] || [ ! -d "/proc/$target_pid" ] && return 1

    target_uid=$(id -u "$TARGET_USER" 2>/dev/null || echo 1000)
    case "$destination" in
        proxy)
            mkdir -p "$CGROUP_PROXY"
            echo "$target_pid" > "$CGROUP_PROXY/cgroup.procs" 2>/dev/null || true
            ;;
        direct)
            mkdir -p "$CGROUP_DIRECT"
            echo "$target_pid" > "$CGROUP_DIRECT/cgroup.procs" 2>/dev/null || true
            ;;
        default)
            echo "$target_pid" > "/sys/fs/cgroup/user.slice/user-${target_uid}.slice/user@${target_uid}.service/app.slice/cgroup.procs" 2>/dev/null || \
            echo "$target_pid" > "/sys/fs/cgroup/user.slice/user-${target_uid}.slice/user@${target_uid}.service/cgroup.procs" 2>/dev/null || \
            echo "$target_pid" > "/sys/fs/cgroup/cgroup.procs" 2>/dev/null || true
            ;;
    esac
}

split_sync() {
    local mode
    mode=$(read_split_mode)
    local bypass_ftp
    bypass_ftp=$(read_bypass_ftp)

    # Function to ensure FTP applications are routed direct
    sync_ftp_apps() {
        if [ "$bypass_ftp" = "1" ]; then
            local ftp_apps=("filezilla" "lftp" "ftp" "ncftp" "gvfsd-ftp" "kio_ftp" "cyberduck" "tftp" "vsftpd" "proftpd" "pure-ftpd")
            for fapp in "${ftp_apps[@]}"; do
                local fpids
                fpids=$(pgrep -i "$fapp" 2>/dev/null || true)
                for p in $fpids; do
                    [ -d "/proc/$p" ] && split_assign_pid "$p" "direct"
                done
            done
        fi
    }

    # If mode is disabled, empty proxy cgroup, keep only FTP apps in direct cgroup
    if [ "$mode" = "disabled" ]; then
        if [ -f "$CGROUP_PROXY/cgroup.procs" ]; then
            for p in $(cat "$CGROUP_PROXY/cgroup.procs" 2>/dev/null); do
                split_assign_pid "$p" "default"
            done
        fi
        if [ "$bypass_ftp" != "1" ]; then
            if [ -f "$CGROUP_DIRECT/cgroup.procs" ]; then
                for p in $(cat "$CGROUP_DIRECT/cgroup.procs" 2>/dev/null); do
                    split_assign_pid "$p" "default"
                done
            fi
        else
            sync_ftp_apps
        fi
        return 0
    fi

    # Read configured split apps
    local apps=()
    if [ -f "$SPLIT_FILE" ]; then
        while IFS= read -r line; do
            line=$(echo "$line" | tr -d '\r\n' | tr '[:upper:]' '[:lower:]' | xargs)
            [ -n "$line" ] && apps+=("$line")
        done < "$SPLIT_FILE"
    fi

    # If mode is include:
    if [ "$mode" = "include" ]; then
        # Empty net_direct
        if [ -f "$CGROUP_DIRECT/cgroup.procs" ]; then
            for p in $(cat "$CGROUP_DIRECT/cgroup.procs" 2>/dev/null); do
                split_assign_pid "$p" "default"
            done
        fi
        # Find all PIDs matching any split app and assign to proxy
        for app in "${apps[@]}"; do
            pids=$(pgrep -i "$app" 2>/dev/null || true)
            for p in $pids; do
                [ -d "/proc/$p" ] && split_assign_pid "$p" "proxy"
            done
        done
        sync_ftp_apps
    fi

    # If mode is exclude:
    if [ "$mode" = "exclude" ]; then
        # Empty net_proxy
        if [ -f "$CGROUP_PROXY/cgroup.procs" ]; then
            for p in $(cat "$CGROUP_PROXY/cgroup.procs" 2>/dev/null); do
                split_assign_pid "$p" "default"
            done
        fi
        # Find all PIDs matching any split app and assign to direct
        for app in "${apps[@]}"; do
            pids=$(pgrep -i "$app" 2>/dev/null || true)
            for p in $pids; do
                [ -d "/proc/$p" ] && split_assign_pid "$p" "direct"
            done
        done
        sync_ftp_apps
    fi
}

split_set_mode() {
    local new_mode="$1"
    if [ "$new_mode" != "disabled" ] && [ "$new_mode" != "include" ] && [ "$new_mode" != "exclude" ]; then
        echo "Erreur: Mode invalide '$new_mode'. Choix possibles : disabled, include, exclude" >&2
        return 1
    fi

    save_split_mode "$new_mode"

    if get_status; then
        split_setup_rules
        if [ "$new_mode" = "include" ]; then
            ip route del 0.0.0.0/1 dev "${TUN_NAME}" metric 10 2>/dev/null || true
            ip route del 128.0.0.0/1 dev "${TUN_NAME}" metric 10 2>/dev/null || true
        else
            ip route replace 0.0.0.0/1 dev "${TUN_NAME}" metric 10 2>/dev/null || true
            ip route replace 128.0.0.0/1 dev "${TUN_NAME}" metric 10 2>/dev/null || true
        fi
        split_sync
    fi
    echo "Mode Split Tunneling défini sur : $new_mode"
}

case "$1" in
    start)
        proxy_arg="$2"
        if [ -z "$proxy_arg" ]; then
            proxy_arg=$(read_gnome_proxy)
        fi

        if [ -z "$proxy_arg" ]; then
            echo "Erreur: Aucune adresse de proxy n'a été spécifiée ou trouvée dans GNOME Settings." >&2
            exit 1
        fi

        # Extract physical gateway & interface, ignoring virtual tun/tap/wireguard interfaces
        def_line=$(ip -4 route show default | grep -E "dev (wl|en|eth|wlan|lan)" | head -n 1)
        if [ -z "$def_line" ]; then
            def_line=$(ip -4 route show | grep -E "dev (wl|en|eth|wlan|lan)" | grep -E "via|default" | head -n 1)
        fi
        if [ -z "$def_line" ]; then
            def_line=$(ip -4 route show default | head -n 1)
        fi
        default_if=$(echo "$def_line" | awk '{for(i=1;i<=NF;i++) if($i=="dev") print $(i+1); exit}')
        default_gw=$(echo "$def_line" | awk '{for(i=1;i<=NF;i++) if($i=="via") print $(i+1); exit}')
        if [ -z "$default_gw" ] && [ -n "$default_if" ]; then
            default_gw=$(ip -4 route show dev "$default_if" 2>/dev/null | awk '/default via/ {print $3}' | head -n 1)
        fi
        proxy_ip=$(echo "$proxy_arg" | sed -E 's|.*://([^:/]+).*|\1|')

        echo "Configuration du proxy forcé..."
        echo "Proxy: $proxy_arg"
        echo "Interface réseau physique: $default_if (GW: $default_gw)"

        # 1. Clean previous state completely
        pkill -9 -f "tun2socks.*${TUN_NAME}" 2>/dev/null || true
        sleep 0.3
        ip link set dev "${TUN_NAME}" down 2>/dev/null || true
        ip tuntap del dev "${TUN_NAME}" mode tun 2>/dev/null || true

        # 2. Add explicit route to proxy server via physical gateway to avoid routing loops
        if [ -n "$default_gw" ] && [ -n "$default_if" ] && [ -n "$proxy_ip" ]; then
            ip route replace "$proxy_ip" via "$default_gw" dev "$default_if" metric 5 2>/dev/null || true
        fi

        # 3. Create TUN interface with optimized MTU for mobile hotspot / VPN encapsulation
        # MTU 1400 prevents packet fragmentation on WireGuard/OpenVPN phone tunnels
        ip tuntap add dev "${TUN_NAME}" mode tun 2>/dev/null || true
        ip addr add 198.18.0.1/15 dev "${TUN_NAME}" 2>/dev/null || true
        ip link set dev "${TUN_NAME}" mtu 1400 up

        # Apply TCP MSS clamping to prevent PMTU blackholes
        iptables -t mangle -C POSTROUTING -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null || iptables -t mangle -A POSTROUTING -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null || true
        iptables -t mangle -C OUTPUT -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null || iptables -t mangle -A OUTPUT -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null || true

        # Optimize kernel TCP stack for proxy throughput and mobile network jitter
        sysctl -q -w net.ipv4.tcp_mtu_probing=1 2>/dev/null || true
        sysctl -q -w net.core.rmem_max=16777216 2>/dev/null || true
        sysctl -q -w net.core.wmem_max=16777216 2>/dev/null || true
        sysctl -q -w net.ipv4.tcp_rmem="4096 87380 16777216" 2>/dev/null || true
        sysctl -q -w net.ipv4.tcp_wmem="4096 65536 16777216" 2>/dev/null || true
        sysctl -q -w net.ipv4.tcp_window_scaling=1 2>/dev/null || true
        sysctl -q -w net.ipv4.tcp_fastopen=3 2>/dev/null || true

        # Configure DNS: Route DNS queries to the phone hotspot gateway for 40ms resolution
        if [ -n "$default_gw" ] && [ -n "$default_if" ]; then
            resolvectl dns "$default_if" "$default_gw" 2>/dev/null || true
            resolvectl default-route "$default_if" yes 2>/dev/null || true
        fi

        # 4. Start tun2socks with high-throughput auto-tuning & large netstack buffers
        if [ ! -x "$TUN2SOCKS_BIN" ]; then
            echo "Erreur: Binaire tun2socks introuvable à $TUN2SOCKS_BIN" >&2
            exit 1
        fi

        nohup "$TUN2SOCKS_BIN" \
            --device "tun://${TUN_NAME}" \
            --proxy "$proxy_arg" \
            --interface "$default_if" \
            --mtu 1400 \
            --tcp-auto-tuning \
            --tcp-rcvbuf 4m \
            --tcp-sndbuf 4m \
            --udp-timeout 30s \
            --loglevel info > "$LOG_FILE" 2>&1 &
        echo $! > "$PID_FILE"
        echo "$proxy_arg" > "$STATE_FILE"

        # Wait a moment for interface initialization
        sleep 0.5

        # 5. Route IPv4 traffic according to Split Tunneling mode
        split_setup_rules
        split_mode=$(read_split_mode)

        if [ "$split_mode" != "include" ]; then
            ip route replace 0.0.0.0/1 dev "${TUN_NAME}" metric 10
            ip route replace 128.0.0.0/1 dev "${TUN_NAME}" metric 10
        else
            ip route del 0.0.0.0/1 dev "${TUN_NAME}" metric 10 2>/dev/null || true
            ip route del 128.0.0.0/1 dev "${TUN_NAME}" metric 10 2>/dev/null || true
        fi

        split_sync

        # 6. Propagate environment variables into user systemd session (HTTP/HTTPS only, NO all_proxy to preserve FTP!)
        sudo -u "$TARGET_USER" systemctl --user set-environment http_proxy="$proxy_arg" https_proxy="$proxy_arg" 2>/dev/null || true
        sudo -u "$TARGET_USER" systemctl --user unset-environment all_proxy ALL_PROXY ftp_proxy FTP_PROXY 2>/dev/null || true

        # Configure snap daemon proxy if HTTP proxy is used
        if echo "$proxy_arg" | grep -qE '^https?://'; then
            snap set system proxy.http="$proxy_arg" proxy.https="$proxy_arg" 2>/dev/null || true
        fi
        pkill -f "/snap/snap-store" 2>/dev/null || true

        echo "Succès: Tout le trafic du PC est désormais forcé vers $proxy_arg (Split Tunneling: $split_mode)"
        exit 0
        ;;

    stop)
        echo "Désactivation du forçage proxy..."

        # Clean up Split Tunneling rules, tables and cgroups
        split_cleanup_rules

        # Read previous proxy IP to clean route
        if [ -f "$STATE_FILE" ]; then
            prev_proxy=$(cat "$STATE_FILE")
            prev_ip=$(echo "$prev_proxy" | sed -E 's|.*://([^:/]+).*|\1|')
            def_line=$(ip -4 route show default | grep -E "dev (wl|en|eth|wlan|lan)" | head -n 1)
            [ -z "$def_line" ] && def_line=$(ip -4 route show | grep -E "dev (wl|en|eth|wlan|lan)" | grep -E "via|default" | head -n 1)
            [ -z "$def_line" ] && def_line=$(ip -4 route show default | head -n 1)
            default_if=$(echo "$def_line" | awk '{for(i=1;i<=NF;i++) if($i=="dev") print $(i+1); exit}')
            default_gw=$(echo "$def_line" | awk '{for(i=1;i<=NF;i++) if($i=="via") print $(i+1); exit}')
            if [ -z "$default_gw" ] && [ -n "$default_if" ]; then
                default_gw=$(ip -4 route show dev "$default_if" 2>/dev/null | awk '/default via/ {print $3}' | head -n 1)
            fi
            if [ -n "$default_gw" ] && [ -n "$default_if" ] && [ -n "$prev_ip" ]; then
                ip route del "$prev_ip" via "$default_gw" dev "$default_if" metric 5 2>/dev/null || true
            fi
        fi

        # Remove TUN routes
        ip route del 0.0.0.0/1 dev "${TUN_NAME}" metric 10 2>/dev/null || true
        ip route del 128.0.0.0/1 dev "${TUN_NAME}" metric 10 2>/dev/null || true

        # Kill tun2socks
        pkill -9 -f "tun2socks.*${TUN_NAME}" 2>/dev/null || true
        rm -f "$PID_FILE" "$STATE_FILE"

        # Remove TCP MSS clamping
        iptables -t mangle -D POSTROUTING -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null || true
        iptables -t mangle -D OUTPUT -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null || true

        # Revert DNS to default DHCP
        def_line=$(ip -4 route show default | head -n 1)
        default_if=$(echo "$def_line" | awk '{for(i=1;i<=NF;i++) if($i=="dev") print $(i+1); exit}')
        if [ -n "$default_if" ]; then
            resolvectl revert "$default_if" 2>/dev/null || true
        fi

        # Remove TUN device
        ip link set dev "${TUN_NAME}" down 2>/dev/null || true
        ip tuntap del dev "${TUN_NAME}" mode tun 2>/dev/null || true

        # Unset user environment
        sudo -u "$TARGET_USER" systemctl --user unset-environment http_proxy https_proxy all_proxy ALL_PROXY ftp_proxy FTP_PROXY 2>/dev/null || true

        
        snap unset system proxy.http proxy.https 2>/dev/null || true

        echo "Succès: Forçage proxy désactivé. Le routage standard est restauré."
        exit 0
        ;;

    optimize|tune)
        echo "Application des optimisations de débit pour Every Proxy / Hotspot mobile..."
        def_line=$(ip -4 route show default | head -n 1)
        default_if=$(echo "$def_line" | awk '{for(i=1;i<=NF;i++) if($i=="dev") print $(i+1); exit}')
        default_gw=$(echo "$def_line" | awk '{for(i=1;i<=NF;i++) if($i=="via") print $(i+1); exit}')

        # 1. Update MTU on tun-proxy
        if ip link show "${TUN_NAME}" >/dev/null 2>&1; then
            ip link set dev "${TUN_NAME}" mtu 1400 2>/dev/null || true
        fi

        # 2. MSS clamping
        iptables -t mangle -C POSTROUTING -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null || iptables -t mangle -A POSTROUTING -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null || true
        iptables -t mangle -C OUTPUT -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null || iptables -t mangle -A OUTPUT -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null || true

        # 3. Kernel TCP optimizations
        sysctl -q -w net.ipv4.tcp_mtu_probing=1 2>/dev/null || true
        sysctl -q -w net.core.rmem_max=16777216 2>/dev/null || true
        sysctl -q -w net.core.wmem_max=16777216 2>/dev/null || true
        sysctl -q -w net.ipv4.tcp_rmem="4096 87380 16777216" 2>/dev/null || true
        sysctl -q -w net.ipv4.tcp_wmem="4096 65536 16777216" 2>/dev/null || true
        sysctl -q -w net.ipv4.tcp_window_scaling=1 2>/dev/null || true
        sysctl -q -w net.ipv4.tcp_fastopen=3 2>/dev/null || true

        # 4. Direct DNS via phone gateway
        if [ -n "$default_gw" ] && [ -n "$default_if" ]; then
            resolvectl dns "$default_if" "$default_gw" 2>/dev/null || true
            resolvectl default-route "$default_if" yes 2>/dev/null || true
        fi

        # 5. Hot-reload tun2socks seamlessly if running
        if [ -f "$STATE_FILE" ] && ip link show "${TUN_NAME}" >/dev/null 2>&1; then
            curr_proxy=$(cat "$STATE_FILE")
            pkill -9 -f "tun2socks.*${TUN_NAME}" 2>/dev/null || true
            nohup "$TUN2SOCKS_BIN" \
                --device "tun://${TUN_NAME}" \
                --proxy "$curr_proxy" \
                --interface "$default_if" \
                --mtu 1400 \
                --tcp-auto-tuning \
                --tcp-rcvbuf 4m \
                --tcp-sndbuf 4m \
                --udp-timeout 30s \
                --loglevel info > "$LOG_FILE" 2>&1 &
            echo $! > "$PID_FILE"
        fi

        echo "Optimisations appliquées avec succès."
        exit 0
        ;;

    block)
        target_pid="$2"
        if [ -n "$target_pid" ] && [ -d "/proc/$target_pid" ]; then
            mkdir -p /sys/fs/cgroup/net_blocked
            mkdir -p /tmp/net_blocked_orig_cg
            orig_cg=$(cat /proc/$target_pid/cgroup 2>/dev/null | head -n 1 | cut -d: -f3)
            if [ -n "$orig_cg" ] && [ "$orig_cg" != "/net_blocked" ]; then
                echo "$orig_cg" > "/tmp/net_blocked_orig_cg/$target_pid"
            fi
            echo "$target_pid" > /sys/fs/cgroup/net_blocked/cgroup.procs 2>/dev/null || true
            if command -v ss >/dev/null 2>&1; then
                ss -K -p "pid=$target_pid" 2>/dev/null || true
            fi
            echo "PID $target_pid bloqué avec succès."
            exit 0
        fi
        exit 1
        ;;

    unblock)
        target_pid="$2"
        if [ -n "$target_pid" ] && [ -d "/proc/$target_pid" ]; then
            orig_cg=""
            if [ -f "/tmp/net_blocked_orig_cg/$target_pid" ]; then
                orig_cg=$(cat "/tmp/net_blocked_orig_cg/$target_pid")
                rm -f "/tmp/net_blocked_orig_cg/$target_pid"
            fi
            target_uid=$(id -u "$TARGET_USER" 2>/dev/null || echo 1000)
            if [ -n "$orig_cg" ] && [ -d "/sys/fs/cgroup$orig_cg" ]; then
                echo "$target_pid" > "/sys/fs/cgroup$orig_cg/cgroup.procs" 2>/dev/null || true
            else
                echo "$target_pid" > "/sys/fs/cgroup/user.slice/user-${target_uid}.slice/user@${target_uid}.service/app.slice/cgroup.procs" 2>/dev/null || \
                echo "$target_pid" > "/sys/fs/cgroup/user.slice/user-${target_uid}.slice/user@${target_uid}.service/cgroup.procs" 2>/dev/null || true
            fi
            echo "PID $target_pid débloqué avec succès."
            exit 0
        fi
        exit 1
        ;;


    block-app)
        app_name="$2"
        if [ -n "$app_name" ]; then
            BLOCKED_DIR="/home/$TARGET_USER/.config/force-proxy"
            mkdir -p "$BLOCKED_DIR"
            BLOCKED_FILE="$BLOCKED_DIR/blocked_apps.txt"
            touch "$BLOCKED_FILE"
            if ! grep -Fxq "$app_name" "$BLOCKED_FILE" 2>/dev/null; then
                echo "$app_name" >> "$BLOCKED_FILE"
            fi
            chown -R "$TARGET_USER:$TARGET_USER" "$BLOCKED_DIR" 2>/dev/null || true
            # Block all running instances matching exact process name
            pids=$(pgrep -x "$app_name" 2>/dev/null || pgrep "$app_name" 2>/dev/null)
            for p in $pids; do
                "$REAL_SCRIPT" block "$p" >/dev/null 2>&1 || true
            done
            echo "Application $app_name bloquée."
            exit 0
        fi
        exit 1
        ;;

    unblock-app)
        app_name="$2"
        if [ -n "$app_name" ]; then
            BLOCKED_FILE="/home/$TARGET_USER/.config/force-proxy/blocked_apps.txt"
            if [ -f "$BLOCKED_FILE" ]; then
                sed -i "/^$app_name$/d" "$BLOCKED_FILE" 2>/dev/null || true
            fi
            # Unblock all running instances matching exact process name
            pids=$(pgrep -x "$app_name" 2>/dev/null || pgrep "$app_name" 2>/dev/null)
            for p in $pids; do
                "$REAL_SCRIPT" unblock "$p" >/dev/null 2>&1 || true
            done
            echo "Application $app_name débloquée."
            exit 0
        fi
        exit 1
        ;;

    firewall-init)
        mkdir -p /sys/fs/cgroup/net_blocked
        chown -R "$TARGET_USER:$TARGET_USER" /sys/fs/cgroup/net_blocked 2>/dev/null || true
        iptables -C OUTPUT -m cgroup --path "net_blocked" -j REJECT 2>/dev/null || iptables -I OUTPUT -m cgroup --path "net_blocked" -j REJECT
        ip6tables -C OUTPUT -m cgroup --path "net_blocked" -j REJECT 2>/dev/null || ip6tables -I OUTPUT -m cgroup --path "net_blocked" -j REJECT 2>/dev/null || true
        echo "Pare-feu applicatif initialisé avec succès."
        exit 0
        ;;

    firewall-reset)
        if [ -f /sys/fs/cgroup/net_blocked/cgroup.procs ]; then
            for p in $(cat /sys/fs/cgroup/net_blocked/cgroup.procs 2>/dev/null); do
                echo "$p" > /sys/fs/cgroup/cgroup.procs 2>/dev/null || true
            done
        fi
        iptables -D OUTPUT -m cgroup --path "net_blocked" -j REJECT 2>/dev/null || true
        ip6tables -D OUTPUT -m cgroup --path "net_blocked" -j REJECT 2>/dev/null || true
        rmdir /sys/fs/cgroup/net_blocked 2>/dev/null || true
        echo "Règles de pare-feu réinitialisées."
        exit 0
        ;;

    update-sudoers)
        echo "$TARGET_USER ALL=(ALL) NOPASSWD: /home/$TARGET_USER/.local/bin/netpulse-ctl, /home/$TARGET_USER/.local/bin/force-proxy-ctl" > /etc/sudoers.d/netpulse
        echo "$TARGET_USER ALL=(ALL) NOPASSWD: /home/$TARGET_USER/.local/bin/netpulse-ctl, /home/$TARGET_USER/.local/bin/force-proxy-ctl" > /etc/sudoers.d/force-proxy
        chmod 440 /etc/sudoers.d/netpulse /etc/sudoers.d/force-proxy 2>/dev/null || true
        echo "Configuration sudoers mise à jour avec succès."
        exit 0
        ;;

    split-mode)
        new_mode="$2"
        if [ -z "$new_mode" ]; then
            read_split_mode
            exit 0
        fi
        split_set_mode "$new_mode"
        exit 0
        ;;

    split-add)
        app_name="$2"
        if [ -n "$app_name" ]; then
            mkdir -p "$SPLIT_DIR"
            touch "$SPLIT_FILE"
            app_lower=$(echo "$app_name" | tr '[:upper:]' '[:lower:]' | xargs)
            if ! grep -Fxq "$app_lower" "$SPLIT_FILE" 2>/dev/null; then
                echo "$app_lower" >> "$SPLIT_FILE"
            fi
            chown -R "$TARGET_USER:$TARGET_USER" "$SPLIT_DIR" 2>/dev/null || true
            split_sync
            echo "Application '$app_lower' ajoutée au Split Tunneling."
            exit 0
        fi
        echo "Usage: $CMD_NAME split-add <nom_application>" >&2
        exit 1
        ;;

    split-del)
        app_name="$2"
        if [ -n "$app_name" ]; then
            app_lower=$(echo "$app_name" | tr '[:upper:]' '[:lower:]' | xargs)
            if [ -f "$SPLIT_FILE" ]; then
                sed -i "/^$app_lower$/d" "$SPLIT_FILE" 2>/dev/null || true
            fi
            split_sync
            echo "Application '$app_lower' retirée du Split Tunneling."
            exit 0
        fi
        echo "Usage: $CMD_NAME split-del <nom_application>" >&2
        exit 1
        ;;

    split-assign)
        target_pid="$2"
        target_dest="$3"
        if [ -n "$target_pid" ] && [ -n "$target_dest" ]; then
            split_assign_pid "$target_pid" "$target_dest"
            exit 0
        fi
        echo "Usage: $CMD_NAME split-assign <pid> <proxy|direct|default>" >&2
        exit 1
        ;;

    split-sync)
        split_sync
        echo "Synchronisation du Split Tunneling terminée."
        exit 0
        ;;

    ftp-bypass)
        action="$2"
        if [ -z "$action" ]; then
            curr=$(read_bypass_ftp)
            if [ "$curr" = "1" ]; then
                echo "Contournement FTP actif (les transferts FTP contournent automatiquement le proxy)."
            else
                echo "Contournement FTP inactif."
            fi
            exit 0
        fi
        case "$action" in
            on|enable|true|1)
                save_bypass_ftp 1
                if get_status; then
                    split_setup_rules
                    split_sync
                fi
                echo "Contournement FTP activé avec succès."
                exit 0
                ;;
            off|disable|false|0)
                save_bypass_ftp 0
                if get_status; then
                    # Retirer les règles spécifiques FTP
                    iptables -t raw -D OUTPUT -p tcp -m multiport --dports 21,990 -j CT --helper ftp 2>/dev/null || true
                    ip6tables -t raw -D OUTPUT -p tcp -m multiport --dports 21,990 -j CT --helper ftp 2>/dev/null || true
                    iptables -t mangle -D OUTPUT -p tcp -m multiport --dports 20,21,989,990 -j MARK --set-mark 0x2000 2>/dev/null || true
                    iptables -t mangle -D OUTPUT -p tcp -m multiport --sports 20,21,989,990 -j MARK --set-mark 0x2000 2>/dev/null || true
                    iptables -t mangle -D OUTPUT -m helper --helper ftp -j MARK --set-mark 0x2000 2>/dev/null || true
                    iptables -t mangle -D OUTPUT -p tcp -m conntrack --ctstate RELATED -m helper --helper ftp -j MARK --set-mark 0x2000 2>/dev/null || true

                    ip6tables -t mangle -D OUTPUT -p tcp -m multiport --dports 20,21,989,990 -j MARK --set-mark 0x2000 2>/dev/null || true
                    ip6tables -t mangle -D OUTPUT -p tcp -m multiport --sports 20,21,989,990 -j MARK --set-mark 0x2000 2>/dev/null || true
                    ip6tables -t mangle -D OUTPUT -m helper --helper ftp -j MARK --set-mark 0x2000 2>/dev/null || true

                    ip rule del ipproto tcp dport 21 table 200 priority 40 2>/dev/null || true
                    ip rule del ipproto tcp dport 990 table 200 priority 40 2>/dev/null || true
                    ip rule del ipproto tcp dport 20 table 200 priority 40 2>/dev/null || true
                    ip rule del ipproto tcp sport 20 table 200 priority 40 2>/dev/null || true
                    ip rule del ipproto tcp dport 989 table 200 priority 40 2>/dev/null || true
                    ip rule del ipproto tcp sport 989 table 200 priority 40 2>/dev/null || true
                    split_sync
                fi
                echo "Contournement FTP désactivé."
                exit 0
                ;;
            *)
                echo "Usage: $CMD_NAME ftp-bypass [on|off]" >&2
                exit 1
                ;;
        esac
        ;;

    toggle)
        if get_status; then
            "$0" stop
        else
            "$0" start "$2"
        fi
        ;;

    *)
        show_help
        exit 1
        ;;
esac
