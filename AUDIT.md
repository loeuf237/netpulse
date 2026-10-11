# Analyse et corrections de NetPulse — 10 octobre 2026

## Complément du 11 octobre 2026

L'erreur d'activation `RTNETLINK answers: No such device` est reproduite dans le
test de copie des routes directes : `ip route show dev INTERFACE` peut omettre le
champ `dev` dans sa sortie. La copie vers la table 200 rétablit désormais
explicitement l'interface si elle est absente, sans la dupliquer si elle existe.
Les lignes vides sont ignorées et une erreur de copie indique l'étape et l'interface.
Le correctif a été réinstallé et l'activation du forçage proxy a été confirmée par
l'utilisateur. Les contrôleurs installés, la GUI, le moniteur et l'unité systemd
correspondent aux fichiers corrigés du dépôt.

- La sauvegarde GUI refuse une configuration existante invalide au lieu de la
  remplacer par les valeurs par défaut. Les paramètres numériques des fonctions
  récentes et l'URL HTTPS sont validés au chargement pour éviter les erreurs GTK.
- Les diagnostics sont invalidés lorsque le tunnel, le serveur, l'URL HTTPS ou leur
  activation changent. Un résultat en cours pour l'ancienne connexion est ignoré,
  et la prochaine sonde démarre sans attendre l'intervalle normal. Les échecs de
  serveurs différents ne sont plus cumulés pour déclencher une alerte.
- Les identifiants de profils absents, vides ou dupliqués produisent une erreur de
  validation. Une URL de diagnostic qui n'est pas du texte ou utilise le port zéro
  est refusée proprement.
- La GUI demande aussi une confirmation lorsque le moniteur préserve le tunnel
  après une mise à jour, même si la configuration est déverrouillée.
- Une réinstallation redémarre effectivement le moniteur déjà actif. L'unité
  systemd reprend les statistiques récentes et préserve le tunnel existant ; la mise
  à jour à chaud réutilise cette unité sans dupliquer ses arguments.

Validation locale : **96 tests Python/Bash et 9 tests JavaScript réussis**, cohérence
des exécutables générés, syntaxe Python/Bash/JavaScript et `git diff --check`.
Le paquet `netpulse-1.1.0-py3-none-any.whl` a été construit sans téléchargement de
dépendances et son contenu vérifié. Le test complet des widgets avec Xvfb n'a pas
été exécuté localement : Xvfb est absent ; le workflow GitHub conserve cette vérification.

L'analyse a couvert les sources Python et Bash, leurs copies exécutables dans `bin/`, l'extension GNOME, les scripts d'installation et de désinstallation, le packaging, les fichiers desktop/systemd et la documentation. Le binaire tiers `tun2socks` a été vérifié par son aide ; son code source n'est pas présent dans ce dépôt.

Les modifications locales présentes au départ ont été conservées. Leur copie préalable est disponible dans `/tmp/netpulse-audit-original` pour la durée de vie de cet environnement. Aucun service NetPulse n'a été arrêté, aucune interface TUN créée ou supprimée et aucune règle réseau réelle modifiée pendant cette intervention. Les corrections sont enregistrées dans le dépôt ; l'installation active n'a pas été remplacée.

## Défauts corrigés

| Composant | Défaut constaté | Correction |
| --- | --- | --- |
| Moniteur | Les sommes de compteurs par PID provoquaient des pics lorsque des sockets disparaissaient ou étaient remplacées. | Suivi par inode/socket avant agrégation par PID. |
| Moniteur | Certaines lignes `ss` conservaient le propriétaire de la socket précédente ; plusieurs descripteurs du même PID doublaient les octets. | Réinitialisation du propriétaire à chaque ligne de socket et déduplication. |
| Moniteur | L'ajout ou le retrait d'une interface modifiait artificiellement les différences de compteurs globaux. | Différences par interface, sans importer les octets antérieurs d'une nouvelle interface. |
| Moniteur | Les changements d'horloge faussaient le débit et la durée. | Intervalles et durée calculés avec l'horloge monotone. |
| Moniteur | La remise à zéro conservait les anciens compteurs d'interface. | Nouvelle référence au moment de la remise à zéro. |
| Moniteur | Les totaux revenaient à zéro sans activité et pouvaient être hérités par un PID réutilisé. | Conservation des totaux d'un processus vivant et identification par date de création. |
| Moniteur | Les applications bloquées disparaissaient lorsque leurs connexions étaient fermées. | Ajout des processus bloqués, même sans sockets. |
| Moniteur | Le split tunneling pouvait déplacer un processus hors du pare-feu. | Priorité au blocage, vérifiée également par le contrôleur. |
| Moniteur | Un fichier PID périmé empêchait le démarrage ; plusieurs démons pouvaient écrire les mêmes statistiques. | Vérification du processus côté GUI et verrou exclusif côté démon. |
| Moniteur | Un changement de fréquence n'était appliqué qu'au redémarrage ; certaines valeurs invalides provoquaient des erreurs. | Programmation du prochain relevé à partir de la configuration rechargée et validation de l'intervalle. |
| Moniteur | Les résolutions DNS pouvaient lancer un nombre illimité de threads et ignoraient les IPv6 mappées en IPv4. | Limite de huit résolutions simultanées, cache borné et validation par `ipaddress`. |
| Interface | La recherche par PID était inversée. | Recherche du texte saisi dans le PID. |
| Interface | Les détails de connexion ne changeaient que si le nombre de sockets changeait. | Rafraîchissement lorsque leur contenu change. |
| Interface | Une liste vide d'hôtes ignorés n'était pas sauvegardée. | Sauvegarde explicite du tableau vide. |
| Interface | Le chargement du SVG dépendait d'un chargeur d'images externe ; son échec interrompait le rafraîchissement. | Rendu en mémoire avec librsvg/Cairo ; une erreur de graphique n'empêche plus les données de s'afficher. |
| Interface | Les premiers points du graphique étaient placés loin de « Maintenant » et l'axe supposait une seconde entre tous les relevés. | Placement suivant les horodatages et fenêtre de soixante secondes. |
| Interface | La lecture de statut exécutait une commande potentiellement lente dans le thread GTK. | Lecture en arrière-plan avec limite de temps et prévention des doublons. |
| Interface | Des commandes échouées affichaient une confirmation de succès. | Vérification du code de retour, message d'erreur et resynchronisation. |
| Interface | Les paramètres d'affichage pouvaient écraser un mode de routage modifié ailleurs. | Sauvegarde des seuls champs modifiés, après relecture du fichier, avec remplacement atomique. |
| Contrôleur | L'ajout d'une clé dans `{}` produisait un JSON invalide. | Lecture/écriture JSON structurée, remplacement atomique et conservation des champs existants. |
| Contrôleur | Un mode ou une destination invalide pouvait retourner le code de succès. | Propagation des erreurs jusqu'au dispatch CLI. |
| Contrôleur | Le retrait d'une application conservait son cgroup et donc son ancien routage. | Réconciliation des deux groupes avec la liste souhaitée, y compris en mode global. |
| Contrôleur | Les marques FTP et proxy pouvaient rester actives simultanément. | Mise à jour exclusive des deux bits NetPulse via le masque `0x3000`, sans remplacer les autres bits. |
| Contrôleur | Les règles de routage étaient ajoutées plusieurs fois lors des synchronisations. | Vérification de leur présence avant ajout. |
| Contrôleur | Les cgroups d'origine étaient perdus et des services système étaient replacés dans la session utilisateur. | Mémorisation/restauration des groupes d'origine pour les nouvelles affectations. |
| Contrôleur | `ss -K -p pid=...` utilisait un filtre non pris en charge. | Recherche des propriétaires TCP puis destruction avec filtres d'extrémités. |
| Contrôleur | Un blocage pouvait réussir en apparence alors que les règles ou le déplacement échouaient. | Initialisation du pare-feu à la demande et vérification des étapes essentielles. |
| Contrôleur | La remise à zéro du pare-feu conservait la liste persistante, réappliquée ensuite par le moniteur. | Effacement de cette liste pendant la remise à zéro. |
| Contrôleur | Les noms d'applications étaient traités comme des expressions régulières et les noms longs mal reconnus. | Comparaison littérale du nom et du binaire, normalisation commune et refus des sauts de ligne. |
| Contrôleur | Le JSON de statut cassait avec des guillemets dans une URL ; le compteur d'une liste vide pouvait contenir deux zéros. | Sérialisation JSON et compteur `awk`. |
| Contrôleur | L'activation modifiait le réseau avant de vérifier le binaire ou l'URL. | Prévalidation du binaire, de l'interface, du schéma, du port et de la résolution IPv4. |
| Contrôleur | Les URL authentifiées ou les noms DNS laissaient des routes incorrectes au nettoyage. | Résolution préalable et enregistrement de la route effectivement créée. |
| Contrôleur | Le NAT et le MSS pouvaient modifier ou retirer des règles utilisées par d'autres logiciels. | Portée limitée aux paquets/interface NetPulse et commentaires identifiant les nouvelles règles. |
| Extension | Les préférences d'affichage étaient ignorées. | Publication des préférences dans les statistiques et application dans le panneau. |
| Extension | Les chemins contenant des espaces étaient interprétés comme des commandes ; l'authentification GUI n'était pas activée. | Lancement par tableau d'arguments et drapeau de demande d'authentification sur le clic. |
| Extension | Des lectures asynchrones continuaient après destruction et pouvaient se chevaucher. | Annulation, protection contre les lectures simultanées et contrôle avant modification des widgets. |
| Installation | La règle sudo autorisait un contrôleur modifiable par l'utilisateur. | Installation du contrôleur et du binaire root dans `/usr/local/libexec/netpulse/`, règle validée par `visudo`. |
| Installation | Les fichiers temporaires du proxy privilégié pouvaient être précréés dans `/tmp`. | Déplacement dans `/run/netpulse/`, appartenant à root. |
| Installation | Toutes les icônes PNG conservaient la taille du SVG original. | Rendu séparé pour chacune des huit tailles. |
| Installation | Dépendances graphiques manquantes, lanceur incorrect pour les chemins avec espaces, contrôleur absent du paquet Python. | Déclaration des dépendances, URL Exec citée, inclusion du script CLI dans la wheel. |
| Désinstallation | Le binaire `tun2socks` et les nouveaux composants privilégiés restaient installés. | Suppression explicite des binaires installés. |

## Validation

- **49 tests Python/Bash** : scénarios de compteurs, changements d'interfaces/horloge, réutilisation de PID, pare-feu/split simulés, erreurs JSON, recherche GUI, rendu SVG, dimensions réelles des PNG et protection de la mise à jour à chaud.
- **5 tests JavaScript** réussis avec les API GNOME simulées : préférences, chemins, état du switch et cycle de vie des lectures.
- Sept scénarios exécutés contre la copie initiale reproduisent les défauts ciblés : recherche PID, détails de connexion, liste d'hôtes ignorés, PID périmé, JSON vide, retrait d'applications et code de retour invalide.
- Vérifications de syntaxe Python, Bash et JavaScript, cohérence des sources avec `bin/` et `git diff --check`.
- Construction du paquet Python sans téléchargement de dépendances.

Commandes reproductibles :

```bash
python3 -m unittest discover -s tests -v
node tests/test_extension.cjs
bash -n install.sh uninstall.sh src/netpulse/ctl.sh
python3 -m py_compile src/netpulse/*.py bin/netpulse-gui bin/netpulse-monitor
node --input-type=module --check < extension/extension.js
```

## Limites de vérification

Les nouvelles règles de pare-feu/routage n'ont pas été appliquées au tunnel en cours. Leurs
comportements noyau restent à vérifier lors d'une maintenance autorisant une reconnexion.
L'interface GTK corrigée a été démarrée dans la session graphique ; GNOME Shell n'a pas été
redémarré. Le binaire tiers n'a pas de sources dans ce dépôt.

Le TUN configuré reste IPv4. Les compteurs individuels restent limités au TCP visible lors des échantillons. Les sockets sont rattachées au cgroup de leur création : le changement de routage des connexions existantes peut nécessiter une reconnexion, et la fermeture TCP ne couvre pas les sockets UDP existantes. Le fonctionnement de plusieurs sessions utilisateur simultanées n'est pas isolé.

Références techniques vérifiées : [filtres de `ss` dans iproute2](https://raw.githubusercontent.com/iproute2/iproute2/main/misc/ssfilter.y), [association des sockets aux cgroups dans iptables](https://raw.githubusercontent.com/rtchack/iptables/master/extensions/libxt_cgroup.man), [formats du chargeur GDK](https://docs.gtk.org/gdk4/ctor.Texture.new_from_bytes.html).

## Mise à jour à chaud

`live-upgrade.py` sauvegarde l'installation et remplace atomiquement ses scripts. La commande
`install-runtime` migre les fichiers d'état historiques vers `/run/netpulse/` et installe le
contrôleur root, sans relancer le tunnel ni modifier le routage. Le moniteur reprend les compteurs
récents et diffère ses commandes réseau automatiques tant que le tunnel initial garde la même
identité. L'interface corrigée peut être ouverte avec `--new-instance`, en gardant l'ancienne.

Les tests couvrent la reprise des statistiques, la réutilisation de PID, le refus des anciens
fichiers d'état non sûrs et les contrôles de conservation du tunnel/routes. Le chargement de
l'extension GNOME est différé à la prochaine session pour ne pas redémarrer GNOME Shell.

La migration du 10 octobre 2026 a conservé le tunnel PID `1627222` et son heure de création,
ainsi que les routes IPv4, les règles de routage et les paramètres de l'interface TUN.
Le moniteur est actif sous `netpulse-monitor.service`, les compteurs ont été repris et des
requêtes HTTPS vers GitHub ont réussi avant et après l'opération. La sauvegarde locale et
le rapport JSON se trouvent dans `~/.local/state/netpulse/backups/20261010-090347/`.
