# 🌐 NetPulse — Moniteur Réseau, Pare-feu Applicatif & Forçage Proxy TUN

**NetPulse** est une suite moderne de surveillance et de contrôle réseau pour Linux (Ubuntu / GNOME), combinant les fonctionnalités d'analyse visuelle de **GlassWire**, la légèreté d'un **Internet Speed Meter** dans la barre supérieure, et la puissance d'interception d'un **routeur TUN transparent**.

Conçu avec les technologies les plus récentes de l'écosystème Linux (**GTK4**, **Libadwaita**, **cgroups v2**, **iptables**, et **systemd**).

---

## ✨ Fonctionnalités principales

### 1. 📈 Graphique d'activité réseau en direct (Style GlassWire)
- Visualisation fluide et vectorielle (SVG) des débits sur une fenêtre glissante de **60 secondes**.
- Deux courbes distinctes avec dégradés néon :
  - 🟢 **Courbe verte** : Débit de réception (téléchargement / ↓).
  - 🔵 **Courbe bleue** : Débit d'envoi (téléversement / ↑).
- Échelle dynamique auto-adaptative (calibrée sur le débit de pointe) et repères temporels (`-60s`, `-30s`, `Maintenant`).

### 2. 🛑 Pare-feu applicatif en 1 clic (« Killswitch » par application)
- Bouton **« Bloquer »** / **« Bloqué »** direct en face de chaque application et service.
- **Coupure instantanée au niveau du noyau** :
  - Déplacement immédiat du processus dans un groupe de contrôle Linux (`cgroup v2` : `/sys/fs/cgroup/net_blocked`).
  - Blocage strict des paquets sortants via `iptables -m cgroup --path net_blocked -j REJECT`.
  - Rupture immédiate de tous les sockets actifs ouverts (`ss -K`).
- **Persistance** : Si l'application est fermée puis relancée, le moniteur réapplique automatiquement l'interdiction réseau.
- Filtre rapide **« Bloqués (Pare-feu) »** pour visualiser d'un clic les applications sous restriction.

### 3. 🌐 Découverte des serveurs distants (Hôtes & Adresses IP)
- **Résolution DNS inverse asynchrone** en arrière-plan avec cache ultra-rapide (sans aucun gel de l'interface).
- **Dans la liste principale** : aperçu synthétique des domaines contactés par chaque application (`🌐 Hôtes : api.snapcraft.io, google.com...`).
- **Dans la vue détaillée (au clic sur une application)** :
  - Chaque connexion active affiche le **nom d'hôte résolu** (ex : `🌐 vesta.web.telegram.org`).
  - Informations de connexion complètes : **Protocole (TCP/UDP)**, **IP distante : Port** ➔ **IP locale : Port**, et **État du socket** (`ESTABLISHED`, `LISTEN`...).

### 4. ⚡ Forçage global du proxy système (Mode TUN transparent)
- Interception de **100 % du trafic réseau** de la machine via une interface virtuelle noyau (`tun-proxy`).
- Redirige toutes les applications qui ignorent habituellement les proxys GNOME standards (commandes terminal `curl`/`wget`, paquets Snap, jeux, daemons système).
- Prévention native des boucles de routage vers la passerelle physique.

### 5. 📟 Indicateur de vitesse dans la barre supérieure (Speed Meter)
- Affichage direct du débit en temps réel dans le panneau supérieur de GNOME (`↓ 1.2 Mo/s  ↑ 250 Ko/s`).
- Menu déroulant contextuel :
  - Débits instantanés.
  - Totaux de données échangées depuis le début de la session.
  - Bascule rapide du proxy TUN en 1 clic.
  - Raccourci vers l'interface graphique NetPulse.
- Entièrement paramétrable (unités en octets `Ko/s, Mo/s` ou en bits `Kbps, Mbps`, fréquence d'actualisation de 1 à 3 secondes).

---

## 🏗️ Architecture technique

```
┌────────────────────────────────────────────────────────┐
│                   NetPulse GUI                         │
│       (Interface moderne GTK4 / Libadwaita)            │
└──────────────────────────┬─────────────────────────────┘
                           │ Consomme
                           ▼
┌────────────────────────────────────────────────────────┐
│                 netpulse-monitor                       │
│    (Démon systemd utilisateur en arrière-plan)         │
│  - Lecture tcp_info des sockets via ss -tipn           │
│  - Mesure exacte sur l'interface physique (wlp0s...)   │
│  - Résolution asynchrone DNS inverse                   │
│  - Publication StatusNotifierItem & JSON (/tmp)        │
└──────────────┬──────────────────────────┬──────────────┘
               │                          │
               ▼                          ▼
┌──────────────────────────────┐   ┌─────────────────────┐
│       GNOME Shell Ext.       │   │    netpulse-ctl     │
│   (Indicateur de panneau)    │   │ (Contrôleur système)│
└──────────────────────────────┘   └──────────┬──────────┘
                                              │
                      ┌───────────────────────┴───────────────────────┐
                      ▼                                               ▼
     ┌──────────────────────────────────┐            ┌──────────────────────────────────┐
     │      Pare-feu Applicatif         │            │       Routage Forcé TUN          │
     │  - cgroups v2 /net_blocked       │            │  - Interface tun-proxy           │
     │  - iptables / ip6tables REJECT   │            │  - tun2socks (Go)                │
     │  - ss -K (kill sockets)          │            │  - Routage 0.0.0.0/1 & 128.0.0.0/1│
     └──────────────────────────────────┘            └──────────────────────────────────┘
```

---

## 📦 Structure des fichiers

```text
netpulse/
├── install.sh                  # Script d'installation automatique
├── uninstall.sh                # Script de désinstallation propre
├── README.md                   # Documentation complète
├── bin/
│   ├── netpulse-gui            # Interface utilisateur GTK4 / Libadwaita
│   ├── netpulse-monitor        # Démon de surveillance d'arrière-plan
│   ├── netpulse-ctl            # Outil de commande système (TUN, pare-feu)
│   └── tun2socks               # Binaire de routage réseau TUN transparent
├── desktop/
│   └── netpulse.desktop        # Lanceur de bureau XDG
├── icons/
│   └── netpulse.svg            # Icône vectorielle officielle NetPulse
├── systemd/
│   └── netpulse-monitor.service# Définition du service systemd utilisateur
└── extension/
    ├── extension.js            # Extension GNOME Shell (indicateur barre du haut)
    └── metadata.json           # Métadonnées de l'extension
```

---

## 🚀 Installation

### Prérequis
- **Système d'exploitation** : Ubuntu 22.04+, 24.04+, Debian 12+, ou toute distribution Linux moderne avec GNOME.
- **Python** : 3.10 ou supérieur.
- **Droits d'administration** (`sudo`) pour la configuration initiale du réseau.

### Installation automatique en une commande
Depuis le dossier du projet :
```bash
chmod +x install.sh
./install.sh
```

Le script `install.sh` s'occupe de tout :
1. Installe les dépendances nécessaires (`python3-psutil`, `gir1.2-adw-1`, `gir1.2-gtk-4.0`, `iptables`, `iproute2`...).
2. Installe les exécutables dans `~/.local/bin/`.
3. Configure l'icône système multi-résolutions (16x16 à 512x512 et SVG scalable) et le lanceur d'applications.
4. Configure la règle `sudoers` pour permettre le contrôle sans mot de passe intempestif.
5. Active l'indicateur GNOME Shell dans votre barre supérieure.
6. Démarre automatiquement le service d'arrière-plan `netpulse-monitor.service`.

---

## 💻 Utilisation

### 1. Interface graphique (GUI)
Vous pouvez lancer NetPulse :
- En le recherchant dans le **menu des applications** d'Ubuntu sous le nom **NetPulse**.
- Ou en lançant simplement dans un terminal :
  ```bash
  netpulse
  ```

L'application s'organise en 3 onglets :
* **Trafic & Applications** : Graphique de débit en direct, liste des processus, statistiques exactes (Ko/s, Mo/s), détails des serveurs contactés et boutons de pare-feu applicatif.
* **Serveur Mandataire** : Forçage global TUN en un interrupteur, configuration des hôtes/ports SOCKS5, HTTP, HTTPS.
* **Paramètres Indicateur** : Personnalisation de l'affichage dans la barre supérieure, sélection des unités (octets ou bits), fréquence de rafraîchissement.

---

### 2. Ligne de commande (CLI : `netpulse-ctl`)

NetPulse fournit un contrôleur puissant en ligne de commande :

#### État du routage
```bash
netpulse-ctl status          # Affiche l'état du routage TUN et du proxy
netpulse-ctl status --json   # Format JSON pour scripts
```

#### Contrôle du pare-feu applicatif
```bash
# Bloquer immédiatement tout accès internet à une application (par nom)
netpulse-ctl block-app chrome
netpulse-ctl block-app steam

# Débloquer l'application
netpulse-ctl unblock-app chrome
netpulse-ctl unblock-app steam

# Bloquer un PID précis
netpulse-ctl block 12345
netpulse-ctl unblock 12345

# Réinitialiser toutes les règles du pare-feu
netpulse-ctl firewall-reset
```

#### Gestion du forçage Proxy (TUN)
```bash
# Démarrer le forçage avec le proxy système configuré dans GNOME
netpulse-ctl start

# Démarrer avec une URL proxy spécifique
netpulse-ctl start socks5://192.168.43.1:1180

# Stopper le forçage
netpulse-ctl stop

# Basculer l'état
netpulse-ctl toggle
```

#### Raccourcis généraux
```bash
netpulse-ctl gui             # Ouvre l'interface graphique
netpulse-ctl reset-session   # Réinitialise les compteurs de session
netpulse-ctl --help          # Affiche l'aide
```

---

## 🗑️ Désinstallation

Pour supprimer proprement NetPulse et restaurer la configuration réseau d'origine :
```bash
chmod +x uninstall.sh
./uninstall.sh
```

---

## 🛡️ Confidentialité et Sécurité

* **100 % local** : NetPulse ne transmet aucune donnée télémétrique vers des serveurs externes.
* Les requêtes DNS inverses sont effectuées directement par le résolveur système de votre machine.
* Le filtrage réseau est assuré localement par le sous-système officiel `cgroup v2` du noyau Linux.
