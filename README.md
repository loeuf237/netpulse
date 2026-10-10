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
- **Blocage au niveau du noyau** :
  - Déplacement immédiat du processus dans un groupe de contrôle Linux (`cgroup v2` : `/sys/fs/cgroup/net_blocked`).
  - Blocage strict des paquets sortants via `iptables -m cgroup --path net_blocked -j REJECT`.
  - Rupture immédiate de tous les sockets actifs ouverts (`ss -K`, avec sélection explicite des extrémités TCP).
- **Persistance** : Si l'application est fermée puis relancée, le moniteur réapplique automatiquement l'interdiction réseau.
- Filtre rapide **« Bloqués (Pare-feu) »** pour visualiser d'un clic les applications sous restriction.

### 3. 🌐 Découverte des serveurs distants (Hôtes & Adresses IP)
- **Résolution DNS inverse asynchrone** en arrière-plan avec cache ultra-rapide (sans aucun gel de l'interface).
- **Dans la liste principale** : aperçu synthétique des domaines contactés par chaque application (`🌐 Hôtes : api.snapcraft.io, google.com...`).
- **Dans la vue détaillée (au clic sur une application)** :
  - Chaque connexion active affiche le **nom d'hôte résolu** (ex : `🌐 vesta.web.telegram.org`).
  - Informations de connexion complètes : **Protocole (TCP/UDP)**, **IP distante : Port** ➔ **IP locale : Port**, et **État du socket** (`ESTABLISHED`, `LISTEN`...).

### 4. ⚡ Forçage global du proxy système (Mode TUN transparent)
- Interception du **trafic IPv4** de la machine, avec les exemptions configurées, via une interface virtuelle noyau (`tun-proxy`).
- Redirige toutes les applications qui ignorent habituellement les proxys GNOME standards (commandes terminal `curl`/`wget`, paquets Snap, jeux, daemons système).
- Prévention native des boucles de routage vers la passerelle physique.

### 5. 🔀 Routage sélectif par application (Split Tunneling Avancé)
- **Triage intelligent du trafic** : choisissez au cas par cas quelles applications transitent par le proxy et lesquelles utilisent votre connexion internet directe.
- **3 modes de routage** :
  - **Mode Global (Désactivé)** : Le trafic IPv4 transite par le proxy TUN, avec les exemptions configurées.
  - **Mode Inclusif (Whitelist)** : Seules les applications sélectionnées (ex: `telegram`, `chrome`, `steam`) sont forcées via le proxy TUN. Tout le reste du système emprunte la connexion directe normale.
  - **Mode Exclusif (Bypass / Blacklist)** : Tout le PC transite par le proxy TUN, **sauf** les applications sélectionnées qui contournent le proxy et accèdent directement à internet.
- **Gestion hybride GUI & CLI** :
  - Badges visuels en temps réel (`⚡ Proxy` / `🌐 Direct`) sur chaque ligne de processus dans l'onglet Trafic.
  - Bouton 1-clic pour ajouter/retirer une application active du Split Tunneling.
  - Gestionnaire de liste dédié dans l'onglet Serveur Mandataire.
  - Commandes CLI `netpulse-ctl split-*`.
- **Routage noyau haute performance** : basé sur `cgroups v2` (`net_proxy`, `net_direct`), marquage de paquets `iptables mangle` (`fwmark 0x1000` / `0x2000`) et tables de routage multiples Linux policy routing (`table 100` et `table 200`).

### 6. 📟 Indicateur de vitesse dans la barre supérieure (Speed Meter)
- Affichage direct du débit en temps réel dans le panneau supérieur de GNOME (`↓ 1.2 Mo/s  ↑ 250 Ko/s`).
- Menu déroulant contextuel :
  - Débits instantanés.
  - Totaux de données échangées depuis le début de la session.
  - Bascule rapide du proxy TUN en 1 clic.
  - Raccourci vers l'interface graphique NetPulse.
- Entièrement paramétrable (unités en octets `Ko/s, Mo/s` ou en bits `Kbps, Mbps`, fréquence d'actualisation de 1 à 3 secondes).

---

## Nouveautés de la version 1.1

- **Connexion protégée**, activée par défaut : bandeau pendant un tunnel actif,
  affectations automatiques différées et confirmation avant les changements réseau depuis
  l'interface. Désactiver cette protection autorise explicitement les automatismes.
- **Diagnostic** : disponibilité TCP du serveur, état du tunnel, résolution DNS et requête
  HTTPS avec temps de réponse. Les sondes utilisent les routes existantes, sans les modifier.
  L'URL HTTPS par défaut est `https://github.com`, avec un intervalle de 60 secondes réglable.
  Le test TCP ne valide pas les identifiants du proxy ; une réponse HTTP d'erreur reste
  distinguée d'une impossibilité d'établir HTTPS.
- **État des affectations** : badges « Appliquée », « En attente » et « En erreur », fondés
  sur les cgroups constatés et les résultats des commandes. Une affectation appliquée ne
  signifie pas que les sockets déjà ouvertes ont changé de trajet.
- **Historique local** : consommation d'aujourd'hui, des 7 ou 30 derniers jours, détail
  quotidien et classement des applications, export CSV. Les données commencent avec
  l'activation de cette version ; aucune consommation antérieure n'est reconstruite.
- **Alertes** : serveur indisponible sur deux sondes successives, seuil quotidien en Mio
  et débit TCP inhabituel par application sur trois relevés. Les deux seuils sont
  désactivés par défaut (`0`). Notifications et délai de répétition sont configurables ;
  les alertes n'effectuent aucun changement réseau.
- **Profils** : créer, modifier, supprimer et activer un serveur avec sa liste de split
  tunneling et son exemption FTP. La préparation est locale ; l'activation nécessite
  une confirmation. Le tunnel est réutilisé si l'URL du serveur est identique.

Les paramètres se trouvent dans **Paramètres Indicateur**. L'historique SQLite est stocké
dans `~/.local/state/netpulse/history.sqlite3` (ou sous `XDG_STATE_HOME`), avec 90 jours
de conservation par défaut, réglables de 1 à 365 jours. Les profils restent dans
`~/.config/force-proxy/profiles.json`, avec des permissions `0600`. Ils peuvent contenir
les identifiants du serveur ; ceux-ci sont masqués dans les descriptions et ne sont
jamais exportés dans l'historique.

Les totaux globaux incluent TCP et UDP sur les interfaces physiques. Les totaux par
application restent des mesures TCP échantillonnées ; ils ne doivent pas être additionnés
au total global. La remise à zéro de la session n'efface pas l'historique.

## Développement et validation GitHub

Modifier les fichiers de `src/netpulse/`, puis régénérer les exécutables autonomes :

```bash
python3 tools/build_executables.py
python3 tools/build_executables.py --check
python3 -m unittest discover -s tests -v
node tests/test_extension.cjs
```

Le workflow `.github/workflows/validate.yml` valide chaque push, pull request et lancement
manuel : cohérence des exécutables générés, syntaxe, tests Python/Bash/JavaScript,
construction des widgets GTK dans un affichage Xvfb isolé et contenu du paquet Python.
Les tests utilisent des doubles des processus et commandes réseau ; aucun proxy réel
n'est lancé ou arrêté. Le workflow utilise uniquement la permission GitHub `contents: read`.

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
│  - Mesure sur les interfaces physiques (wlp0s...)   │
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
├── src/                        # Code source Python modulaire du projet
│   └── netpulse/
│       ├── __init__.py         # Initialisation du module et métadonnées de version
│       ├── constants.py        # Chemins et paramètres par défaut
│       ├── gui.py              # Code source de l'interface GTK4 / Libadwaita
│       ├── monitor.py          # Code source du moteur d'analyse réseau
│       └── ctl.sh              # Code source du script de contrôle système
├── pyproject.toml              # Fichier de packaging Python moderne
├── setup.py                    # Script d'installation de paquet standard
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
- **Système d'exploitation** : Ubuntu 24.04+, Debian 13+, ou une distribution fournissant GTK 4.8+, Libadwaita 1.4+ et librsvg 2.46+. L’extension requiert GNOME Shell 46 à 50.
- **Python** : 3.10 ou supérieur.
- **Droits d'administration** (`sudo`) pour la configuration initiale du réseau.

### Installation automatique en une commande
Depuis le dossier du projet :
```bash
chmod +x install.sh
./install.sh
```

Le script `install.sh` s'occupe de tout :
1. Installe les dépendances nécessaires (`python3-psutil`, `python3-gi`, `python3-cairo`, `python3-gi-cairo`, `gir1.2-rsvg-2.0`, `gir1.2-adw-1`, `gir1.2-gtk-4.0`, `iptables`, `iproute2`...).
2. Installe les exécutables dans `~/.local/bin/`.
3. Configure l'icône système multi-résolutions (16x16 à 512x512 et SVG scalable) et le lanceur d'applications.
4. Installe le contrôleur et tun2socks dans `/usr/local/libexec/netpulse/`, appartenant à root, puis valide la règle `sudoers` avec `visudo`. Les fichiers du proxy sont conservés dans `/run/netpulse/`.
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

#### Routage sélectif (Split Tunneling)
```bash
# Afficher l'état du Split Tunneling, mode actif et processus assignés
netpulse-ctl split-status
netpulse-ctl split-status --json

# Définir le mode de routage (disabled, include, exclude)
netpulse-ctl split-mode include     # Seules les applications listées vont au proxy
netpulse-ctl split-mode exclude     # Tout va au proxy SAUF les applications listées
netpulse-ctl split-mode disabled    # Mode global (tout le PC via le proxy)

# Ajouter une application à la liste de tri
netpulse-ctl split-add telegram
netpulse-ctl split-add steam
netpulse-ctl split-add chrome

# Retirer une application de la liste
netpulse-ctl split-del chrome

# Lister les applications actuellement configurées
netpulse-ctl split-list

# Resynchroniser immédiatement tous les processus actifs
netpulse-ctl split-sync
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


## Vérification des corrections

Depuis la racine du projet, avec les dépendances système installées :

```bash
python3 -m unittest discover -s tests -v
node tests/test_extension.cjs
bash -n install.sh uninstall.sh src/netpulse/ctl.sh
```

Les tests simulent les processus et commandes réseau ; ils ne démarrent ni n'arrêtent le proxy actif.
Le détail de l'analyse se trouve dans [AUDIT.md](AUDIT.md).

### Mise à jour avec un tunnel actif

Pour migrer une installation existante en conservant la connexion et les fenêtres ouvertes :

```bash
python3 live-upgrade.py
```

La procédure sauvegarde les fichiers installés dans `~/.local/state/netpulse/backups/`,
remplace les scripts atomiquement, adopte le PID du tunnel historique dans `/run/netpulse/`
et relance uniquement le moniteur avec reprise de sa session. Elle vérifie que le PID,
l'heure de création du tunnel, les routes IPv4, les règles de routage et l'interface TUN
restent identiques. Une nouvelle fenêtre affiche les corrections sans fermer l'ancienne.
Les fichiers de l'extension GNOME sont mis à jour ; leur chargement attend la prochaine session.

Le moniteur est lancé avec `--resume-session --preserve-active-tunnel` : ses actions automatiques
de pare-feu et de split tunneling sont différées pendant la vie du tunnel présent au lancement.
Les commandes manuelles restent disponibles ; les automatismes reprennent lorsque ce tunnel
est arrêté ou remplacé. Ce mode privilégie la stabilité de la connexion pendant la migration.

La migration initiale utilise l'autorisation sudo déjà configurée. Si un contrôleur root
plus ancien est déjà installé, le mettre à jour avant de lancer la procédure, sans arrêter le proxy :

```bash
sudo install -o root -g root -m 755 bin/netpulse-ctl /usr/local/libexec/netpulse/netpulse-ctl
```

### Portée des mesures et du routage

- Le débit global comprend TCP et UDP sur les interfaces physiques. Les débits par processus proviennent de compteurs TCP échantillonnés ; UDP et les sockets ouvertes puis fermées entre deux relevés ne sont pas comptabilisés individuellement.
- Un moniteur non privilégié peut ne pas connaître le PID de certaines connexions appartenant à d'autres utilisateurs.
- Le proxy transparent configure les routes IPv4. Les règles IPv6 du pare-feu sont installées séparément ; elles ne constituent pas un routage TUN IPv6.
- Un changement de cgroup s'applique aux sockets créées ensuite. Pour les connexions déjà ouvertes, le split tunneling peut nécessiter une reconnexion de l'application. Le blocage ferme les sockets TCP que le noyau permet de détruire ; il ne garantit pas la destruction des sockets UDP déjà ouvertes.
- Les cgroups et les fichiers de statistiques actuels sont partagés à l'échelle de la machine : le fonctionnement simultané de plusieurs sessions utilisateur reste à isoler.
