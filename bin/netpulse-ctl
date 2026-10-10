#!/usr/bin/env bash
# force-proxy-ctl: Management script for transparent TUN proxy routing

TUN_NAME="tun-proxy"
PID_FILE="/run/netpulse/tun2socks.pid"
STATE_FILE="/run/netpulse/proxy.txt"
LOG_FILE="/run/netpulse/tun2socks.log"
REAL_SCRIPT="$(readlink -f "$0")"
ROOT_CTL="/usr/local/libexec/netpulse/netpulse-ctl"

# Détection dynamique de l'utilisateur cible (propriétaire de la session)
if [ -n "$SUDO_USER" ] && [ "$SUDO_USER" != "root" ]; then
    TARGET_USER="$SUDO_USER"
elif [ -n "$PKEXEC_UID" ]; then
    TARGET_USER="$(id -un "$PKEXEC_UID" 2>/dev/null)"
elif [ "$(id -u)" -ne 0 ]; then
    TARGET_USER="$(id -un)"
else
    TARGET_USER="$(stat -c %U "$REAL_SCRIPT" 2>/dev/null)"
fi
[ -z "$TARGET_USER" ] && TARGET_USER="root"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
[ -z "$TARGET_HOME" ] && TARGET_HOME="/home/$TARGET_USER"
TUN2SOCKS_BIN="/usr/local/libexec/netpulse/tun2socks"
USER_BIN="$TARGET_HOME/.local/bin"

# Supprime de manière sûre la ligne exacte $2 du fichier $1 (aucune interprétation par sed/regex)
remove_exact_line() {
    local file="$1" line="$2" tmp result
    [ -f "$file" ] || return 0
    tmp="$(mktemp "${file}.XXXXXX")" || return 1
    grep -vxF -- "$line" "$file" > "$tmp"
    result=$?
    if [ "$result" -gt 1 ]; then rm -f "$tmp"; return "$result"; fi
    chmod --reference="$file" "$tmp" || { rm -f "$tmp"; return 1; }
    chown --reference="$file" "$tmp" 2>/dev/null || true
    mv -f "$tmp" "$file"
}

SPLIT_DIR="$TARGET_HOME/.config/force-proxy"
SPLIT_FILE="$SPLIT_DIR/split_apps.txt"
CONFIG_FILE="$SPLIT_DIR/config.json"
CGROUP_PROXY="/sys/fs/cgroup/net_proxy"
CGROUP_DIRECT="/sys/fs/cgroup/net_direct"
CGROUP_BLOCKED="/sys/fs/cgroup/net_blocked"
ORIGINAL_CGROUP_DIR="/run/netpulse/original-cgroups"
PROXY_ROUTE_FILE="/run/netpulse/proxy-route"

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
  install-runtime          Installer le contrôleur privilégié et adopter le tunnel existant sans le relancer
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
        case "$mode" in disabled|include|exclude) echo "$mode"; return 0 ;; esac
    fi
    echo "disabled"
}

save_json_setting() {
    local key="$1" value="$2"
    mkdir -p "$SPLIT_DIR" || return 1
    python3 - "$CONFIG_FILE" "$key" "$value" <<'PYJSON'
import json, os, sys, tempfile
path, key, value = sys.argv[1:]
try:
    try:
        with open(path, encoding="utf-8") as stream:
            config = json.load(stream)
    except FileNotFoundError:
        config = {}
    if not isinstance(config, dict):
        raise ValueError("la configuration doit être un objet JSON")
    config[key] = json.loads(value)
    fd, temporary = tempfile.mkstemp(dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(config, stream, indent=2)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
except (OSError, ValueError) as exc:
    print(f"Erreur de configuration : {exc}", file=sys.stderr)
    sys.exit(1)
PYJSON
    local result=$?
    [ "$result" -eq 0 ] || return "$result"
    chown "$TARGET_USER:$(id -gn "$TARGET_USER")" "$CONFIG_FILE" 2>/dev/null || true
}

save_split_mode() {
    save_json_setting split_tunnel_mode "\"$1\""
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
    local bool_str=true
    case "$1" in 0|off|false) bool_str=false ;; esac
    save_json_setting bypass_ftp "$bool_str"
}

normalize_app_name() {
    python3 - "$1" <<'PYNAME'
import sys
name = sys.argv[1].strip().lower()
if not name or "\n" in name or "\r" in name:
    sys.exit(1)
print(name)
PYNAME
}

find_app_pids() {
    # pgrep traite son argument comme une expression régulière et tronque les noms longs.
    python3 - "$1" <<'PYPIDS'
import glob, os, sys
name = sys.argv[1].lower()
for directory in glob.glob("/proc/[0-9]*"):
    try:
        with open(directory + "/comm", encoding="utf-8") as stream:
            comm = stream.read().strip().lower()
        with open(directory + "/cmdline", "rb") as stream:
            argv0 = os.fsdecode(stream.read().split(b"\0")[0])
        if name in (comm, os.path.basename(argv0).lower()):
            print(os.path.basename(directory))
    except (OSError, UnicodeError):
        continue
PYPIDS
}

# Commandes exécutables immédiatement sans droits root
case "$1" in
    ""|-h|--help|help)
        show_help
        exit 0
        ;;
    gui|open)
        gtk-launch netpulse 2>/dev/null || nohup "$USER_BIN/netpulse-gui" >/dev/null 2>&1 &
        exit 0
        ;;
    reset-session|reset)
        "$USER_BIN/netpulse-monitor" --reset 2>/dev/null || "$USER_BIN/force-proxy-monitor" --reset 2>/dev/null || true
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
        [ -f "$SPLIT_FILE" ] && app_count=$(awk 'NF {n++} END {print n+0}' "$SPLIT_FILE")
        proxy_pids_count=0
        [ -f "$CGROUP_PROXY/cgroup.procs" ] && proxy_pids_count=$(wc -l < "$CGROUP_PROXY/cgroup.procs" 2>/dev/null || echo 0)
        direct_pids_count=0
        [ -f "$CGROUP_DIRECT/cgroup.procs" ] && direct_pids_count=$(wc -l < "$CGROUP_DIRECT/cgroup.procs" 2>/dev/null || echo 0)

        if [ "$2" = "--json" ]; then
            apps_json="[]"
            if [ -f "$SPLIT_FILE" ]; then
                apps_json=$(python3 -c 'import json,sys; print(json.dumps([line.strip().lower() for line in open(sys.argv[1], encoding="utf-8") if line.strip()]))' "$SPLIT_FILE" 2>/dev/null || echo "[]")
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

print_status_json() {
    python3 - "$1" "$2" "$TUN_NAME" "$3" "$4" <<'PYSTATUS'
import json, sys
active, proxy, device, mode, ftp = sys.argv[1:]
print(json.dumps(dict(active=active == "true", proxy=proxy, device=device,
                      split_mode=mode, bypass_ftp=ftp == "1")))
PYSTATUS
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
            print_status_json true "$curr_proxy" "$split_mode" "$bypass_ftp"
            exit 0
        else
            gnome_proxy=$(read_gnome_proxy)
            print_status_json false "$gnome_proxy" "$split_mode" "$bypass_ftp"
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
    if ip rule show 2>/dev/null | grep -q "fwmark 0x2000/0x2000.*lookup 200"; then
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
    if [ ! -x "$ROOT_CTL" ]; then
        echo "NetPulse: Le contrôleur privilégié est absent. Lancez ./install.sh depuis le projet." >&2
        exit 1
    fi
    # 1. Try passwordless sudo first (configured via /etc/sudoers.d/netpulse)
    if sudo -n "$ROOT_CTL" check-sudo >/dev/null 2>&1; then
        exec sudo "$ROOT_CTL" "$@"
    fi

    # 2. If running interactively in a terminal, prompt via sudo in the terminal
    if [ -t 0 ] || [ -t 1 ]; then
        exec sudo "$ROOT_CTL" "$@"
    fi

    # 3. If explicitly requested with GUI prompt flag (from interactive GUI click)
    if [ "$NETPULSE_ALLOW_GUI_PROMPT" = "1" ]; then
        exec pkexec "$ROOT_CTL" "$@"
    fi

    # 4. In background / daemon / boot mode, NEVER pop up graphical pkexec prompts!
    echo "NetPulse: Privilèges root requis pour cette commande, mais la session est non-interactive et sudo sans mot de passe n'est pas encore actif." >&2
    exit 1
fi

# -------------------------------------------------------------
# 3. ACTIONS EXECUTED AS ROOT & SPLIT TUNNELING HELPERS
# -------------------------------------------------------------

get_net_info() {
    # Priorité absolue aux interfaces physiques réelles (WiFi, Ethernet, LTE)
    def_line=$(ip -4 route show default 2>/dev/null | grep -E "dev (wl|en|eth|ww)" | head -n 1)
    [ -z "$def_line" ] && def_line=$(ip -4 route show 2>/dev/null | grep -E "dev (wl|en|eth|ww)" | grep -E "via|default" | head -n 1)
    [ -z "$def_line" ] && def_line=$(ip -4 route show default 2>/dev/null | grep -v -E "tun|tap|proton|wg|zivpn|docker|veth|br-|lxc" | head -n 1)
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

ensure_policy_rule() {
    local mark="$1" table="$2" priority="$3"
    ip -4 rule show priority "$priority" | grep -Fq "fwmark $mark lookup $table" ||
        ip rule add fwmark "$mark" table "$table" priority "$priority"
}

split_setup_rules() {
    get_net_info
    mkdir -p "$CGROUP_PROXY" "$CGROUP_DIRECT" "$CGROUP_BLOCKED" || return 1

    # Les bits NetPulse sont exclusifs ; les autres bits de la marque sont préservés.
    iptables -t mangle -C OUTPUT -m cgroup --path "net_proxy" -j MARK --set-xmark 0x1000/0x3000 2>/dev/null || \
        iptables -t mangle -A OUTPUT -m cgroup --path "net_proxy" -j MARK --set-xmark 0x1000/0x3000 || return 1
    iptables -t mangle -C OUTPUT -m cgroup --path "net_direct" -j MARK --set-xmark 0x2000/0x3000 2>/dev/null || \
        iptables -t mangle -A OUTPUT -m cgroup --path "net_direct" -j MARK --set-xmark 0x2000/0x3000 || return 1

    ip6tables -t mangle -C OUTPUT -m cgroup --path "net_proxy" -j MARK --set-xmark 0x1000/0x3000 2>/dev/null || \
        ip6tables -t mangle -A OUTPUT -m cgroup --path "net_proxy" -j MARK --set-xmark 0x1000/0x3000 2>/dev/null || true
    ip6tables -t mangle -C OUTPUT -m cgroup --path "net_direct" -j MARK --set-xmark 0x2000/0x3000 2>/dev/null || \
        ip6tables -t mangle -A OUTPUT -m cgroup --path "net_direct" -j MARK --set-xmark 0x2000/0x3000 2>/dev/null || true

    # Les priorités restent après les règles usuelles des VPN ; elles ne les remplacent pas.
    ensure_policy_rule 0x1000/0x1000 100 10040 || return 1
    ensure_policy_rule 0x2000/0x2000 200 10050 || return 1

    # 3. routing table 100 -> proxy tun
    ip route replace default dev "${TUN_NAME}" table 100 || return 1

    # Copier les routes physiques avant d'installer la passerelle de la table 200.
    if [ -n "$default_if" ]; then
        while IFS= read -r route; do
            [[ "$route" == default* ]] && continue
            read -r -a route_args <<< "$route"
            ip route replace "${route_args[@]}" table 200 || return 1
        done < <(ip -4 route show dev "$default_if")
    fi
    if [ -n "$default_gw" ] && [ -n "$default_if" ]; then
        local source_args=()
        [ -n "$default_ip" ] && source_args=(src "$default_ip")
        ip route replace default via "$default_gw" dev "$default_if" "${source_args[@]}" table 200 || return 1
    elif [ -n "$default_if" ]; then
        ip route replace default dev "$default_if" table 200 || return 1
    else
        return 1
    fi

    # 5. FTP Traffic Exemption (Bypass FTP)
    if [ "$(read_bypass_ftp)" = "1" ]; then
        modprobe nf_conntrack_ftp 2>/dev/null || true

        iptables -t raw -C OUTPUT -p tcp -m multiport --dports 21,990 -j CT --helper ftp 2>/dev/null || \
            iptables -t raw -A OUTPUT -p tcp -m multiport --dports 21,990 -j CT --helper ftp 2>/dev/null || true
        ip6tables -t raw -C OUTPUT -p tcp -m multiport --dports 21,990 -j CT --helper ftp 2>/dev/null || \
            ip6tables -t raw -A OUTPUT -p tcp -m multiport --dports 21,990 -j CT --helper ftp 2>/dev/null || true

        # Marque 0x2000/0x2000 pour que le trafic FTP soit acheminé via la table 200
        iptables -t mangle -C OUTPUT -p tcp -m multiport --dports 20,21,989,990 -j MARK --set-xmark 0x2000/0x3000 2>/dev/null || \
            iptables -t mangle -A OUTPUT -p tcp -m multiport --dports 20,21,989,990 -j MARK --set-xmark 0x2000/0x3000
        iptables -t mangle -C OUTPUT -p tcp -m multiport --sports 20,21,989,990 -j MARK --set-xmark 0x2000/0x3000 2>/dev/null || \
            iptables -t mangle -A OUTPUT -p tcp -m multiport --sports 20,21,989,990 -j MARK --set-xmark 0x2000/0x3000
        iptables -t mangle -C OUTPUT -m helper --helper ftp -j MARK --set-xmark 0x2000/0x3000 2>/dev/null || \
            iptables -t mangle -A OUTPUT -m helper --helper ftp -j MARK --set-xmark 0x2000/0x3000
        iptables -t mangle -C OUTPUT -p tcp -m conntrack --ctstate RELATED -m helper --helper ftp -j MARK --set-xmark 0x2000/0x3000 2>/dev/null || \
            iptables -t mangle -A OUTPUT -p tcp -m conntrack --ctstate RELATED -m helper --helper ftp -j MARK --set-xmark 0x2000/0x3000

        ip6tables -t mangle -C OUTPUT -p tcp -m multiport --dports 20,21,989,990 -j MARK --set-xmark 0x2000/0x3000 2>/dev/null || \
            ip6tables -t mangle -A OUTPUT -p tcp -m multiport --dports 20,21,989,990 -j MARK --set-xmark 0x2000/0x3000 2>/dev/null || true
        ip6tables -t mangle -C OUTPUT -p tcp -m multiport --sports 20,21,989,990 -j MARK --set-xmark 0x2000/0x3000 2>/dev/null || \
            ip6tables -t mangle -A OUTPUT -p tcp -m multiport --sports 20,21,989,990 -j MARK --set-xmark 0x2000/0x3000 2>/dev/null || true
        ip6tables -t mangle -C OUTPUT -m helper --helper ftp -j MARK --set-xmark 0x2000/0x3000 2>/dev/null || \
            ip6tables -t mangle -A OUTPUT -m helper --helper ftp -j MARK --set-xmark 0x2000/0x3000 2>/dev/null || true
    fi

    # 6. Masquerade uniquement si routage direct actif
    if [ -n "$default_if" ]; then
        iptables -t nat -C POSTROUTING -o "$default_if" -m mark --mark 0x2000/0x2000 -m comment --comment netpulse -j MASQUERADE 2>/dev/null || \
            iptables -t nat -A POSTROUTING -o "$default_if" -m mark --mark 0x2000/0x2000 -m comment --comment netpulse -j MASQUERADE 2>/dev/null || true
    fi
}

split_cleanup_rules() {
    for cg in "$CGROUP_PROXY" "$CGROUP_DIRECT"; do
        if [ -f "$cg/cgroup.procs" ]; then
            for p in $(cat "$cg/cgroup.procs"); do
                restore_cgroup "$p" || return 1
            done
        fi
    done

    # Retrait des règles iptables mangle NetPulse (avec et sans masque pour nettoyer tout résidu)
    for _mask in "0x1000/0x3000" "0x1000/0x1000" "0x1000/0xffffffff" "0x1000"; do
        iptables -t mangle -D OUTPUT -m cgroup --path "net_proxy" -j MARK --set-xmark "$_mask" 2>/dev/null || true
        ip6tables -t mangle -D OUTPUT -m cgroup --path "net_proxy" -j MARK --set-xmark "$_mask" 2>/dev/null || true
    done
    for _mask in "0x2000/0x3000" "0x2000/0x2000" "0x2000/0xffffffff" "0x2000"; do
        iptables -t mangle -D OUTPUT -m cgroup --path "net_direct" -j MARK --set-xmark "$_mask" 2>/dev/null || true
        ip6tables -t mangle -D OUTPUT -m cgroup --path "net_direct" -j MARK --set-xmark "$_mask" 2>/dev/null || true
    done

    # Retrait des règles FTP bypass
    iptables -t raw -D OUTPUT -p tcp -m multiport --dports 21,990 -j CT --helper ftp 2>/dev/null || true
    ip6tables -t raw -D OUTPUT -p tcp -m multiport --dports 21,990 -j CT --helper ftp 2>/dev/null || true
    for _mask in "0x2000/0x3000" "0x2000/0x2000" "0x2000/0xffffffff" "0x2000"; do
        iptables -t mangle -D OUTPUT -p tcp -m multiport --dports 20,21,989,990 -j MARK --set-xmark "$_mask" 2>/dev/null || true
        iptables -t mangle -D OUTPUT -p tcp -m multiport --sports 20,21,989,990 -j MARK --set-xmark "$_mask" 2>/dev/null || true
        iptables -t mangle -D OUTPUT -m helper --helper ftp -j MARK --set-xmark "$_mask" 2>/dev/null || true
        iptables -t mangle -D OUTPUT -p tcp -m conntrack --ctstate RELATED -m helper --helper ftp -j MARK --set-xmark "$_mask" 2>/dev/null || true
        ip6tables -t mangle -D OUTPUT -p tcp -m multiport --dports 20,21,989,990 -j MARK --set-xmark "$_mask" 2>/dev/null || true
        ip6tables -t mangle -D OUTPUT -p tcp -m multiport --sports 20,21,989,990 -j MARK --set-xmark "$_mask" 2>/dev/null || true
        ip6tables -t mangle -D OUTPUT -m helper --helper ftp -j MARK --set-xmark "$_mask" 2>/dev/null || true
    done

    # Nettoyage de toutes les ip rules NetPulse (anciennes et nouvelles priorités)
    ip rule del fwmark 0x1000/0x1000 table 100 priority 10040 2>/dev/null || true
    ip rule del fwmark 0x2000/0x2000 table 200 priority 10050 2>/dev/null || true
    ip rule del fwmark 0x1000/0x1000 table 100 priority 50 2>/dev/null || true
    ip rule del fwmark 0x2000/0x2000 table 200 priority 50 2>/dev/null || true
    ip rule del not fwmark 0/0xffffffff table 200 priority 55 2>/dev/null || true

    for _p in 40; do
        ip rule del ipproto tcp dport 21 table 200 priority $_p 2>/dev/null || true
        ip rule del ipproto tcp dport 990 table 200 priority $_p 2>/dev/null || true
        ip rule del ipproto tcp dport 20 table 200 priority $_p 2>/dev/null || true
        ip rule del ipproto tcp sport 20 table 200 priority $_p 2>/dev/null || true
        ip rule del ipproto tcp dport 989 table 200 priority $_p 2>/dev/null || true
        ip rule del ipproto tcp sport 989 table 200 priority $_p 2>/dev/null || true
    done

    ip route flush table 100 2>/dev/null || true
    ip route flush table 200 2>/dev/null || true

    get_net_info
    if [ -n "$default_if" ]; then
        iptables -t nat -D POSTROUTING -o "$default_if" -m mark --mark 0x2000/0x2000 -m comment --comment netpulse -j MASQUERADE 2>/dev/null || true
    fi
}

remember_cgroup() {
    local pid="$1" current
    current=$(awk -F: '$1 == "0" {print $3}' "/proc/$pid/cgroup") || return 1
    case "$current" in /net_proxy|/net_direct|/net_blocked) return 0 ;; esac
    install -d -m 700 "$ORIGINAL_CGROUP_DIR" || return 1
    printf '%s\n' "$current" > "$ORIGINAL_CGROUP_DIR/$pid"
}

restore_cgroup() {
    local pid="$1" original="" target_uid
    if [ ! -d "/proc/$pid" ]; then
        rm -f "$ORIGINAL_CGROUP_DIR/$pid"
        return 0
    fi
    if [ -f "$ORIGINAL_CGROUP_DIR/$pid" ]; then
        original=$(cat "$ORIGINAL_CGROUP_DIR/$pid")
    fi
    if [ -n "$original" ] && [ -d "/sys/fs/cgroup$original" ]; then
        printf '%s\n' "$pid" > "/sys/fs/cgroup$original/cgroup.procs" || return 1
    else
        target_uid=$(stat -c %u "/proc/$pid") || return 1
        # Les tranches systemd intermédiaires contiennent des contrôleurs et refusent les processus.
        local fallback="/sys/fs/cgroup/user.slice/user-${target_uid}.slice/user@${target_uid}.service/app.slice"
        [ -d "$fallback" ] || fallback="/sys/fs/cgroup"
        mkdir -p "$fallback/netpulse-restored" || return 1
        printf '%s\n' "$pid" > "$fallback/netpulse-restored/cgroup.procs" || return 1
    fi
    rm -f "$ORIGINAL_CGROUP_DIR/$pid"
}

split_assign_pid() {
    local target_pid="$1" destination="$2" current target
    [[ "$target_pid" =~ ^[1-9][0-9]*$ ]] && [ -d "/proc/$target_pid" ] || return 1
    current=$(awk -F: '$1 == "0" {print $3}' "/proc/$target_pid/cgroup")
    # Le routage ne doit jamais retirer un processus du pare-feu.
    [ "$current" = "/net_blocked" ] && return 0
    case "$destination" in
        proxy) target="$CGROUP_PROXY" ;;
        direct) target="$CGROUP_DIRECT" ;;
        default)
            case "$current" in /net_proxy|/net_direct) restore_cgroup "$target_pid" ;; *) return 0 ;; esac
            return $?
            ;;
        *) echo "Destination de routage invalide : $destination" >&2; return 1 ;;
    esac
    [ "$current" = "${target#/sys/fs/cgroup}" ] && return 0
    remember_cgroup "$target_pid" || return 1
    mkdir -p "$target" || return 1
    printf '%s\n' "$target_pid" > "$target/cgroup.procs"
}

split_sync() {
    local mode bypass_ftp pid app destination
    mode=$(read_split_mode)
    bypass_ftp=$(read_bypass_ftp)
    local -A destinations=()
    if [ "$mode" != "disabled" ] && [ -f "$SPLIT_FILE" ]; then
        while IFS= read -r app || [ -n "$app" ]; do
            app=$(normalize_app_name "$app") || continue
            while IFS= read -r pid; do
                [ -n "$pid" ] || continue
                if [ "$mode" = "include" ]; then destinations[$pid]=proxy; else destinations[$pid]=direct; fi
            done < <(find_app_pids "$app")
        done < "$SPLIT_FILE"
    fi
    if [ "$bypass_ftp" = "1" ]; then
        for app in filezilla lftp ftp ncftp gvfsd-ftp kio_ftp cyberduck tftp vsftpd proftpd pure-ftpd; do
            while IFS= read -r pid; do
                [ -n "$pid" ] && destinations[$pid]=direct
            done < <(find_app_pids "$app")
        done
    fi
    # Restaurer aussi les applications retirées de la liste, quel que soit le mode.
    for group in "$CGROUP_PROXY" "$CGROUP_DIRECT"; do
        [ -f "$group/cgroup.procs" ] || continue
        while IFS= read -r pid; do
            [ -n "$pid" ] || continue
            destination=${destinations[$pid]:-default}
            if ! split_assign_pid "$pid" "$destination"; then
                [ -d "/proc/$pid" ] && return 1
            fi
            unset 'destinations[$pid]'
        done < "$group/cgroup.procs"
    done
    for pid in "${!destinations[@]}"; do
        if ! split_assign_pid "$pid" "${destinations[$pid]}"; then
            [ -d "/proc/$pid" ] && return 1
        fi
    done
    return 0
}

firewall_init() {
    mkdir -p "$CGROUP_BLOCKED" || return 1
    iptables -C OUTPUT -m cgroup --path net_blocked -j REJECT 2>/dev/null ||
        iptables -I OUTPUT -m cgroup --path net_blocked -j REJECT || return 1
    ip6tables -C OUTPUT -m cgroup --path net_blocked -j REJECT 2>/dev/null ||
        ip6tables -I OUTPUT -m cgroup --path net_blocked -j REJECT || return 1
}

kill_pid_sockets() {
    # ss ne possède pas de filtre pid : sélectionner les sockets puis filtrer leurs extrémités.
    python3 - "$1" <<'PYSOCKETS'
import re, subprocess, sys
pid = int(sys.argv[1])
result = subprocess.run(["ss", "-Htnp"], capture_output=True, text=True, timeout=3, check=True)
for line in result.stdout.splitlines():
    if pid not in {int(value) for value in re.findall(r"pid=(\d+)", line)}:
        continue
    fields = line.split()
    if len(fields) >= 5:
        subprocess.run(["ss", "-K", "-t", "src", fields[3], "dst", fields[4]],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3, check=True)
PYSOCKETS
}

split_set_mode() {
    local new_mode="$1"
    if [ "$new_mode" != "disabled" ] && [ "$new_mode" != "include" ] && [ "$new_mode" != "exclude" ]; then
        echo "Erreur: Mode invalide '$new_mode'. Choix possibles : disabled, include, exclude" >&2
        return 1
    fi

    save_split_mode "$new_mode" || return 1

    if get_status; then
        split_setup_rules || return 1
        if [ "$new_mode" = "include" ]; then
            ip route del 0.0.0.0/1 dev "${TUN_NAME}" metric 10 2>/dev/null || true
            ip route del 128.0.0.0/1 dev "${TUN_NAME}" metric 10 2>/dev/null || true
        else
            ip route replace 0.0.0.0/1 dev "${TUN_NAME}" metric 10 || return 1
            ip route replace 128.0.0.0/1 dev "${TUN_NAME}" metric 10 || return 1
        fi
        split_sync || return 1
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

        if [ ! -x "$TUN2SOCKS_BIN" ]; then
            echo "Erreur: Binaire tun2socks introuvable à $TUN2SOCKS_BIN" >&2
            exit 1
        fi
        get_net_info
        if [ -z "$default_if" ]; then
            echo "Erreur: Aucune interface réseau disponible." >&2
            exit 1
        fi
        proxy_ip=$(python3 - "$proxy_arg" <<'PYPROXY'
import socket, sys
from urllib.parse import urlsplit
try:
    proxy = urlsplit(sys.argv[1])
    if proxy.scheme not in ("socks5", "socks4", "http") or not proxy.hostname or not proxy.port:
        raise ValueError("URL attendue : socks5://hôte:port, socks4://hôte:port ou http://hôte:port")
    print(socket.getaddrinfo(proxy.hostname, proxy.port, socket.AF_INET, socket.SOCK_STREAM)[0][4][0])
except (OSError, ValueError) as exc:
    print(f"Erreur de proxy : {exc}", file=sys.stderr)
    sys.exit(1)
PYPROXY
        ) || exit 1

        install -d -o root -g root -m 755 /run/netpulse || exit 1

        echo "Configuration du proxy forcé..."
        echo "Proxy: $proxy_arg"
        echo "Interface réseau physique: $default_if (GW: $default_gw)"

        if get_status; then
            "$REAL_SCRIPT" stop || exit 1
        fi
        # 1. Clean previous state completely
        pkill -9 -f "tun2socks.*${TUN_NAME}" 2>/dev/null || true
        sleep 0.3
        ip link set dev "${TUN_NAME}" down 2>/dev/null || true
        ip tuntap del dev "${TUN_NAME}" mode tun 2>/dev/null || true

        # 2. Add explicit route to proxy server via physical gateway to avoid routing loops
        if [ -n "$default_gw" ] && [ -n "$default_if" ] && [ -n "$proxy_ip" ] && [ "$proxy_ip" != "$default_gw" ] && [[ "$proxy_ip" != 127.* ]] && [ "$proxy_ip" != "localhost" ]; then
            install -d -o root -g root -m 755 /run/netpulse || exit 1
            ip route add "$proxy_ip/32" via "$default_gw" dev "$default_if" metric 5 || exit 1
            printf '%s %s %s\n' "$proxy_ip" "$default_gw" "$default_if" > "$PROXY_ROUTE_FILE"
        fi

        # 3. Create TUN interface with optimized MTU for mobile hotspot / VPN encapsulation
        # MTU 1400 prevents packet fragmentation on WireGuard/OpenVPN phone tunnels
        ip tuntap add dev "${TUN_NAME}" mode tun || { "$REAL_SCRIPT" stop; exit 1; }
        ip addr add 198.18.0.1/15 dev "${TUN_NAME}" || { "$REAL_SCRIPT" stop; exit 1; }
        ip link set dev "${TUN_NAME}" mtu 1400 up || { "$REAL_SCRIPT" stop; exit 1; }

        # Apply TCP MSS clamping to prevent PMTU blackholes
        iptables -t mangle -C POSTROUTING -o "$TUN_NAME" -p tcp --tcp-flags SYN,RST SYN -m comment --comment netpulse -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null || iptables -t mangle -A POSTROUTING -o "$TUN_NAME" -p tcp --tcp-flags SYN,RST SYN -m comment --comment netpulse -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null || true
        iptables -t mangle -C OUTPUT -o "$TUN_NAME" -p tcp --tcp-flags SYN,RST SYN -m comment --comment netpulse -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null || iptables -t mangle -A OUTPUT -o "$TUN_NAME" -p tcp --tcp-flags SYN,RST SYN -m comment --comment netpulse -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null || true

        # Optimize kernel TCP stack for proxy throughput and mobile network jitter
        sysctl -q -w net.ipv4.tcp_mtu_probing=1 2>/dev/null || true
        sysctl -q -w net.core.rmem_max=16777216 2>/dev/null || true
        sysctl -q -w net.core.wmem_max=16777216 2>/dev/null || true
        sysctl -q -w net.ipv4.tcp_rmem="4096 87380 16777216" 2>/dev/null || true
        sysctl -q -w net.ipv4.tcp_wmem="4096 65536 16777216" 2>/dev/null || true
        sysctl -q -w net.ipv4.tcp_window_scaling=1 2>/dev/null || true
        sysctl -q -w net.ipv4.tcp_fastopen=3 2>/dev/null || true

        # DNS : on ne modifie plus systemd-resolved (le DNS DHCP/VPN reste intact).
        # Les requêtes DNS transitent déjà par le TUN comme tout le trafic.

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
        chgrp "$(id -gn "$TARGET_USER")" "$STATE_FILE" || exit 1
        chmod 640 "$STATE_FILE"
        chmod 600 "$LOG_FILE"

        # Wait a moment for interface initialization
        sleep 0.5

        if ! kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
            echo "Erreur: tun2socks n'a pas démarré. Consultez $LOG_FILE." >&2
            "$REAL_SCRIPT" stop >/dev/null 2>&1
            exit 1
        fi

        # 5. Route IPv4 traffic according to Split Tunneling mode
        split_setup_rules || { "$REAL_SCRIPT" stop; exit 1; }
        split_mode=$(read_split_mode)

        if [ "$split_mode" != "include" ]; then
            ip route replace 0.0.0.0/1 dev "${TUN_NAME}" metric 10 || { "$REAL_SCRIPT" stop; exit 1; }
            ip route replace 128.0.0.0/1 dev "${TUN_NAME}" metric 10 || { "$REAL_SCRIPT" stop; exit 1; }
        else
            ip route del 0.0.0.0/1 dev "${TUN_NAME}" metric 10 2>/dev/null || true
            ip route del 128.0.0.0/1 dev "${TUN_NAME}" metric 10 2>/dev/null || true
        fi

        split_sync || { "$REAL_SCRIPT" stop; exit 1; }

        # 6. Propagate environment variables into user systemd session (HTTP/HTTPS only, NO all_proxy to preserve FTP!)
        # Le TUN force déjà tout le trafic : on n'exporte plus http(s)_proxy (une URL socks5:// dans ces
        # variables fait échouer Proton VPN, requests, pip...). On nettoie d'anciennes valeurs éventuelles.
        sudo -u "$TARGET_USER" systemctl --user unset-environment http_proxy https_proxy all_proxy ALL_PROXY ftp_proxy FTP_PROXY 2>/dev/null || true

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

        # 1. Supprimer immédiatement les routes TUN 0.0.0.0/1 et 128.0.0.0/1
        # C'est la priorité absolue : le trafic repasse instantanément sur la route par défaut (WiFi/Ethernet/VPN) SANS AUCUNE COUPURE
        ip route del 0.0.0.0/1 dev "${TUN_NAME}" metric 10 2>/dev/null || true
        ip route del 128.0.0.0/1 dev "${TUN_NAME}" metric 10 2>/dev/null || true

        # Retirer uniquement la route créée par cette instance (y compris hôtes DNS et authentification).
        if [ -f "$PROXY_ROUTE_FILE" ]; then
            read -r prev_ip prev_gateway prev_interface < "$PROXY_ROUTE_FILE"
            ip route del "$prev_ip/32" via "$prev_gateway" dev "$prev_interface" metric 5 2>/dev/null || true
            rm -f "$PROXY_ROUTE_FILE"
        fi

        # 3. Arrêter tun2socks
        pkill -9 -f "tun2socks.*${TUN_NAME}" 2>/dev/null || true
        rm -f "$PID_FILE" "$STATE_FILE"

        # 4. Supprimer l'interface TUN
        ip link set dev "${TUN_NAME}" down 2>/dev/null || true
        ip tuntap del dev "${TUN_NAME}" mode tun 2>/dev/null || true

        # 5. Nettoyer les règles de Split Tunneling, tables de routage 100/200 et cgroups
        split_cleanup_rules || exit 1

        # 6. Retirer le MSS clamping
        iptables -t mangle -D POSTROUTING -o "$TUN_NAME" -p tcp --tcp-flags SYN,RST SYN -m comment --comment netpulse -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null || true
        iptables -t mangle -D OUTPUT -o "$TUN_NAME" -p tcp --tcp-flags SYN,RST SYN -m comment --comment netpulse -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null || true

        # 7. DNS : Ne JAMAIS exécuter "resolvectl revert" (qui vide le Link DNS et coupe la connexion !)
        # Au besoin, si le DNS de l'interface physique est vide, réappliquer la configuration NetworkManager
        get_net_info
        if [ -n "$default_if" ] && command -v nmcli >/dev/null 2>&1; then
            if ! resolvectl dns "$default_if" 2>/dev/null | grep -qE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+|:'; then
                nmcli device reapply "$default_if" 2>/dev/null || true
            fi
        fi

        # 8. Nettoyage strict des variables d'environnement de session (garantit que Proton VPN n'est pas pollué)
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
        iptables -t mangle -C POSTROUTING -o "$TUN_NAME" -p tcp --tcp-flags SYN,RST SYN -m comment --comment netpulse -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null || iptables -t mangle -A POSTROUTING -o "$TUN_NAME" -p tcp --tcp-flags SYN,RST SYN -m comment --comment netpulse -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null || true
        iptables -t mangle -C OUTPUT -o "$TUN_NAME" -p tcp --tcp-flags SYN,RST SYN -m comment --comment netpulse -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null || iptables -t mangle -A OUTPUT -o "$TUN_NAME" -p tcp --tcp-flags SYN,RST SYN -m comment --comment netpulse -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null || true

        # 3. Kernel TCP optimizations
        sysctl -q -w net.ipv4.tcp_mtu_probing=1 2>/dev/null || true
        sysctl -q -w net.core.rmem_max=16777216 2>/dev/null || true
        sysctl -q -w net.core.wmem_max=16777216 2>/dev/null || true
        sysctl -q -w net.ipv4.tcp_rmem="4096 87380 16777216" 2>/dev/null || true
        sysctl -q -w net.ipv4.tcp_wmem="4096 65536 16777216" 2>/dev/null || true
        sysctl -q -w net.ipv4.tcp_window_scaling=1 2>/dev/null || true
        sysctl -q -w net.ipv4.tcp_fastopen=3 2>/dev/null || true

        # 4. DNS : laissé tel quel (géré par NetworkManager / VPN)

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
        [[ "$target_pid" =~ ^[1-9][0-9]*$ ]] && [ -d "/proc/$target_pid" ] || exit 1
        firewall_init || exit 1
        remember_cgroup "$target_pid" || exit 1
        printf '%s\n' "$target_pid" > "$CGROUP_BLOCKED/cgroup.procs" || exit 1
        kill_pid_sockets "$target_pid" || exit 1
        echo "PID $target_pid bloqué avec succès."
        exit 0
        ;;

    unblock)
        target_pid="$2"
        [[ "$target_pid" =~ ^[1-9][0-9]*$ ]] && [ -d "/proc/$target_pid" ] || exit 1
        current=$(awk -F: '$1 == "0" {print $3}' "/proc/$target_pid/cgroup")
        if [ "$current" = "/net_blocked" ]; then
            restore_cgroup "$target_pid" || exit 1
        fi
        echo "PID $target_pid débloqué avec succès."
        exit 0
        ;;

    block-app)
        app_name="$(normalize_app_name "$2")" || exit 1
        if [ -n "$app_name" ]; then
            firewall_init || exit 1
            BLOCKED_DIR="$TARGET_HOME/.config/force-proxy"
            mkdir -p "$BLOCKED_DIR"
            BLOCKED_FILE="$BLOCKED_DIR/blocked_apps.txt"
            touch "$BLOCKED_FILE"
            if ! grep -Fxq -- "$app_name" "$BLOCKED_FILE" 2>/dev/null; then
                echo "$app_name" >> "$BLOCKED_FILE"
            fi
            chown -R "$TARGET_USER:$TARGET_USER" "$BLOCKED_DIR" 2>/dev/null || true
            # Block all running instances matching exact process name
            pids=$(find_app_pids "$app_name")
            for p in $pids; do
                "$REAL_SCRIPT" block "$p" || exit 1
            done
            echo "Application $app_name bloquée."
            exit 0
        fi
        exit 1
        ;;

    unblock-app)
        app_name="$(normalize_app_name "$2")" || exit 1
        if [ -n "$app_name" ]; then
            BLOCKED_FILE="$TARGET_HOME/.config/force-proxy/blocked_apps.txt"
            remove_exact_line "$BLOCKED_FILE" "$app_name" || exit 1
            # Unblock all running instances matching exact process name
            pids=$(find_app_pids "$app_name")
            for p in $pids; do
                "$REAL_SCRIPT" unblock "$p" || exit 1
            done
            echo "Application $app_name débloquée."
            exit 0
        fi
        exit 1
        ;;

    firewall-init)
        firewall_init || exit 1
        echo "Pare-feu applicatif initialisé avec succès."
        exit 0
        ;;

    firewall-reset)
        if [ -f "$CGROUP_BLOCKED/cgroup.procs" ]; then
            for p in $(cat "$CGROUP_BLOCKED/cgroup.procs"); do
                restore_cgroup "$p" || exit 1
            done
        fi
        blocked_file="$SPLIT_DIR/blocked_apps.txt"
        if [ -f "$blocked_file" ]; then
            : > "$blocked_file" || exit 1
        fi
        iptables -D OUTPUT -m cgroup --path net_blocked -j REJECT 2>/dev/null || true
        ip6tables -D OUTPUT -m cgroup --path net_blocked -j REJECT 2>/dev/null || true
        rmdir "$CGROUP_BLOCKED" 2>/dev/null || true
        echo "Règles de pare-feu réinitialisées."
        exit 0
        ;;

    update-sudoers)
        # sudo ne doit autoriser qu'un script installé appartenant à root.
        if [ "$REAL_SCRIPT" != "$ROOT_CTL" ] || [ "$(stat -c %u "$ROOT_CTL")" != "0" ]; then
            echo "Erreur: Installez d'abord le contrôleur root avec ./install.sh." >&2
            exit 1
        fi
        sudoers_tmp=$(mktemp) || exit 1
        printf '%s ALL=(root) NOPASSWD: %s\n' "$TARGET_USER" "$ROOT_CTL" > "$sudoers_tmp"
        if ! visudo -cf "$sudoers_tmp"; then
            rm -f "$sudoers_tmp"
            exit 1
        fi
        install -o root -g root -m 440 "$sudoers_tmp" /etc/sudoers.d/netpulse || exit 1
        rm -f "$sudoers_tmp" /etc/sudoers.d/force-proxy
        echo "Configuration sudoers mise à jour avec succès."
        exit 0
        ;;

    install-runtime)
        # Installation de fichiers uniquement : ne lance aucune commande de routage ou de pare-feu.
        install -d -o root -g root -m 755 /usr/local/libexec/netpulse /run/netpulse || exit 1
        install -o root -g root -m 755 "$REAL_SCRIPT" "$ROOT_CTL.next" || exit 1
        mv -f "$ROOT_CTL.next" "$ROOT_CTL" || exit 1
        if [ ! -x "$TUN2SOCKS_BIN" ]; then
            install -o root -g root -m 755 "$USER_BIN/tun2socks" "$TUN2SOCKS_BIN" || exit 1
        fi
        python3 - "$TARGET_USER" <<'PYMIGRATE'
import os, pwd, stat, sys, tempfile
account = pwd.getpwnam(sys.argv[1])
runtime = "/run/netpulse"
def trusted_read(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "r", encoding="utf-8") as stream:
        info = os.fstat(stream.fileno())
        if info.st_uid != 0 or info.st_mode & 0o022 or not stat.S_ISREG(info.st_mode):
            raise ValueError(f"Fichier de migration non sûr : {path}")
        return stream.read()
if not os.path.exists(runtime + "/tun2socks.pid") and os.path.exists("/tmp/force-proxy.pid"):
    pid = int(trusted_read("/tmp/force-proxy.pid").strip())
    with open(f"/proc/{pid}/comm", encoding="utf-8") as stream:
        if stream.read().strip() != "tun2socks":
            raise ValueError("Le PID historique n'appartient pas à tun2socks")
    proxy = trusted_read("/tmp/force-proxy-current.txt").strip()
    # Le PID sert de marqueur de migration terminée, publié après le proxy.
    for name, content, mode in (("proxy.txt", proxy, 0o640), ("tun2socks.pid", str(pid), 0o644)):
        fd, temporary = tempfile.mkstemp(dir=runtime)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(content + "\n")
                os.fchmod(stream.fileno(), mode)
                os.fchown(stream.fileno(), 0, account.pw_gid)
            os.replace(temporary, runtime + "/" + name)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    print(f"Tunnel existant adopté, PID {pid}, sans redémarrage.")
else:
    print("Contrôleur installé ; état du tunnel conservé.")
PYMIGRATE
        [ "$?" -eq 0 ] || exit 1
        "$ROOT_CTL" update-sudoers || exit 1
        exit 0
        ;;

    split-mode)
        new_mode="$2"
        if [ -z "$new_mode" ]; then
            read_split_mode
            exit 0
        fi
        split_set_mode "$new_mode"
        exit $?
        ;;

    split-add)
        app_name="$(normalize_app_name "$2")" || exit 1
        if [ -n "$app_name" ]; then
            mkdir -p "$SPLIT_DIR"
            touch "$SPLIT_FILE"
            app_lower="$app_name"
            if ! grep -Fxq -- "$app_lower" "$SPLIT_FILE" 2>/dev/null; then
                echo "$app_lower" >> "$SPLIT_FILE"
            fi
            chown -R "$TARGET_USER:$TARGET_USER" "$SPLIT_DIR" 2>/dev/null || true
            if get_status; then split_sync || exit 1; fi
            echo "Application '$app_lower' ajoutée au Split Tunneling."
            exit 0
        fi
        echo "Usage: $CMD_NAME split-add <nom_application>" >&2
        exit 1
        ;;

    split-del)
        app_name="$(normalize_app_name "$2")" || exit 1
        if [ -n "$app_name" ]; then
            app_lower="$app_name"
            remove_exact_line "$SPLIT_FILE" "$app_lower" || exit 1
            if get_status; then split_sync || exit 1; fi
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
            exit $?
        fi
        echo "Usage: $CMD_NAME split-assign <pid> <proxy|direct|default>" >&2
        exit 1
        ;;

    split-sync)
        if get_status; then split_sync || exit 1; fi
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
                save_bypass_ftp 1 || exit 1
                if get_status; then
                    split_setup_rules || exit 1
                    if get_status; then split_sync || exit 1; fi
                fi
                echo "Contournement FTP activé avec succès."
                exit 0
                ;;
            off|disable|false|0)
                save_bypass_ftp 0 || exit 1
                if get_status; then
                    # Retirer les règles spécifiques FTP
                    iptables -t raw -D OUTPUT -p tcp -m multiport --dports 21,990 -j CT --helper ftp 2>/dev/null || true
                    ip6tables -t raw -D OUTPUT -p tcp -m multiport --dports 21,990 -j CT --helper ftp 2>/dev/null || true
                    iptables -t mangle -D OUTPUT -p tcp -m multiport --dports 20,21,989,990 -j MARK --set-xmark 0x2000/0x3000 2>/dev/null || true
                    iptables -t mangle -D OUTPUT -p tcp -m multiport --sports 20,21,989,990 -j MARK --set-xmark 0x2000/0x3000 2>/dev/null || true
                    iptables -t mangle -D OUTPUT -m helper --helper ftp -j MARK --set-xmark 0x2000/0x3000 2>/dev/null || true
                    iptables -t mangle -D OUTPUT -p tcp -m conntrack --ctstate RELATED -m helper --helper ftp -j MARK --set-xmark 0x2000/0x3000 2>/dev/null || true

                    ip6tables -t mangle -D OUTPUT -p tcp -m multiport --dports 20,21,989,990 -j MARK --set-xmark 0x2000/0x3000 2>/dev/null || true
                    ip6tables -t mangle -D OUTPUT -p tcp -m multiport --sports 20,21,989,990 -j MARK --set-xmark 0x2000/0x3000 2>/dev/null || true
                    ip6tables -t mangle -D OUTPUT -m helper --helper ftp -j MARK --set-xmark 0x2000/0x3000 2>/dev/null || true

                    ip rule del ipproto tcp dport 21 table 200 priority 40 2>/dev/null || true
                    ip rule del ipproto tcp dport 990 table 200 priority 40 2>/dev/null || true
                    ip rule del ipproto tcp dport 20 table 200 priority 40 2>/dev/null || true
                    ip rule del ipproto tcp sport 20 table 200 priority 40 2>/dev/null || true
                    ip rule del ipproto tcp dport 989 table 200 priority 40 2>/dev/null || true
                    ip rule del ipproto tcp sport 989 table 200 priority 40 2>/dev/null || true
                    if get_status; then split_sync || exit 1; fi
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
