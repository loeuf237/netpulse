#!/usr/bin/env bash
# force-proxy-ctl: Management script for transparent TUN proxy routing

TUN_NAME="tun-proxy"
PID_FILE="/tmp/force-proxy.pid"
STATE_FILE="/tmp/force-proxy-current.txt"
LOG_FILE="/tmp/tun2socks.log"
TARGET_USER="paulin"
TUN2SOCKS_BIN="/home/paulin/.local/bin/tun2socks"
REAL_SCRIPT="$(readlink -f "$0")"

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
  help, -h, --help         Afficher cette aide

Exemples :
  $CMD_NAME status
  $CMD_NAME start socks5://192.168.43.1:1180
  $CMD_NAME block-app steam
  $CMD_NAME unblock-app steam
EOF
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
        /home/paulin/.local/bin/force-proxy-monitor --reset
        exit 0
        ;;
esac

get_status() {
    local running=1
    if pgrep -f "tun2socks.*${TUN_NAME}" >/dev/null 2>&1 && ip link show "${TUN_NAME}" >/dev/null 2>&1 && ip route show 0.0.0.0/1 2>/dev/null | grep -q "${TUN_NAME}"; then
        running=0
    fi
    return $running
}

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
    fi
}

# -------------------------------------------------------------
# 1. STATUS: DOES NOT REQUIRE ROOT PRIVILEGES (NEVER CALL SUDO/PKEXEC)
# -------------------------------------------------------------
if [ "$1" = "status" ]; then
    if [ "$2" = "--json" ]; then
        if get_status; then
            curr_proxy=$(cat "$STATE_FILE" 2>/dev/null || read_gnome_proxy)
            echo "{\"active\": true, \"proxy\": \"$curr_proxy\", \"device\": \"$TUN_NAME\"}"
            exit 0
        else
            gnome_proxy=$(read_gnome_proxy)
            echo "{\"active\": false, \"proxy\": \"$gnome_proxy\", \"device\": \"$TUN_NAME\"}"
            exit 0
        fi
    else
        if get_status; then
            curr_proxy=$(cat "$STATE_FILE" 2>/dev/null || read_gnome_proxy)
            echo "Proxy forcé actif sur ${TUN_NAME} -> ${curr_proxy}"
            exit 0
        else
            echo "Proxy forcé inactif"
            exit 0
        fi
    fi
fi

# -------------------------------------------------------------
# 2. PRIVILEGE ESCALATION ONLY FOR START / STOP / TOGGLE
# -------------------------------------------------------------
if [ "$(id -u)" -ne 0 ]; then
    if sudo -n "$REAL_SCRIPT" check-sudo >/dev/null 2>&1; then
        exec sudo "$REAL_SCRIPT" "$@"
    else
        exec pkexec "$REAL_SCRIPT" "$@"
    fi
fi

# -------------------------------------------------------------
# 3. ACTIONS EXECUTED AS ROOT
# -------------------------------------------------------------
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

        # Extract gateway & default physical interface
        def_line=$(ip -4 route show default | head -n 1)
        default_if=$(echo "$def_line" | awk '{for(i=1;i<=NF;i++) if($i=="dev") print $(i+1); exit}')
        default_gw=$(echo "$def_line" | awk '{for(i=1;i<=NF;i++) if($i=="via") print $(i+1); exit}')
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
            ip route add "$proxy_ip" via "$default_gw" dev "$default_if" metric 5 2>/dev/null || true
        fi

        # 3. Create TUN interface
        ip tuntap add dev "${TUN_NAME}" mode tun
        ip addr add 198.18.0.1/15 dev "${TUN_NAME}"
        ip link set dev "${TUN_NAME}" up

        # 4. Start tun2socks with correct double-dash flags
        if [ ! -x "$TUN2SOCKS_BIN" ]; then
            echo "Erreur: Binaire tun2socks introuvable à $TUN2SOCKS_BIN" >&2
            exit 1
        fi

        nohup "$TUN2SOCKS_BIN" --device "tun://${TUN_NAME}" --proxy "$proxy_arg" --interface "$default_if" --loglevel info > "$LOG_FILE" 2>&1 &
        echo $! > "$PID_FILE"
        echo "$proxy_arg" > "$STATE_FILE"

        # Wait a moment for interface initialization
        sleep 0.5

        # 5. Route all IPv4 traffic through the TUN interface
        ip route add 0.0.0.0/1 dev "${TUN_NAME}" metric 10
        ip route add 128.0.0.0/1 dev "${TUN_NAME}" metric 10

        # 6. Propagate environment variables into user systemd session
        sudo -u "$TARGET_USER" systemctl --user set-environment http_proxy="$proxy_arg" https_proxy="$proxy_arg" all_proxy="$proxy_arg" 2>/dev/null || true

        
        # Configure snap daemon proxy and refresh store
        if [ -n "$http_host" ] && [ -n "$http_port" ]; then
            snap set system proxy.http="http://${http_host}:${http_port}" proxy.https="http://${http_host}:${http_port}" 2>/dev/null || true
        fi
        pkill -f "/snap/snap-store" 2>/dev/null || true

        bash /tmp/test_snapd.sh
        echo "Succès: Tout le trafic du PC est désormais forcé vers $proxy_arg"
        exit 0
        ;;

    stop)
        echo "Désactivation du forçage proxy..."

        # Read previous proxy IP to clean route
        if [ -f "$STATE_FILE" ]; then
            prev_proxy=$(cat "$STATE_FILE")
            prev_ip=$(echo "$prev_proxy" | sed -E 's|.*://([^:/]+).*|\1|')
            def_line=$(ip -4 route show default | head -n 1)
            default_if=$(echo "$def_line" | awk '{for(i=1;i<=NF;i++) if($i=="dev") print $(i+1); exit}')
            default_gw=$(echo "$def_line" | awk '{for(i=1;i<=NF;i++) if($i=="via") print $(i+1); exit}')
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

        # Remove TUN device
        ip link set dev "${TUN_NAME}" down 2>/dev/null || true
        ip tuntap del dev "${TUN_NAME}" mode tun 2>/dev/null || true

        # Unset user environment
        sudo -u "$TARGET_USER" systemctl --user unset-environment http_proxy https_proxy all_proxy 2>/dev/null || true

        
        snap unset system proxy.http proxy.https 2>/dev/null || true

        echo "Succès: Forçage proxy désactivé. Le routage standard est restauré."
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
            if [ -n "$orig_cg" ] && [ -d "/sys/fs/cgroup$orig_cg" ]; then
                echo "$target_pid" > "/sys/fs/cgroup$orig_cg/cgroup.procs" 2>/dev/null || true
            else
                echo "$target_pid" > /sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/cgroup.procs 2>/dev/null || \
                echo "$target_pid" > /sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/cgroup.procs 2>/dev/null || true
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
            # Block all running instances
            for p in $(pgrep -f "$app_name" 2>/dev/null); do
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
            # Unblock all running instances
            for p in $(pgrep -f "$app_name" 2>/dev/null); do
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
        echo "paulin ALL=(ALL) NOPASSWD: /home/paulin/.local/bin/force-proxy-ctl, /home/paulin/.local/bin/netpulse-ctl" > /etc/sudoers.d/force-proxy
        chmod 440 /etc/sudoers.d/force-proxy
        echo "Configuration sudoers mise à jour avec succès."
        exit 0
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
