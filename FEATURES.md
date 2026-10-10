# NetPulse 1.1 : connexion protégée, observation et profils

Les fonctionnalités de priorité 1 à 6 sont implémentées dans le moniteur et l'interface.
Le contrôleur privilégié reste identique ; aucune nouvelle règle réseau n'est nécessaire
pour le diagnostic, l'historique, les alertes ou la préparation des profils.

| Fonction | Mise en œuvre | Vérification |
| --- | --- | --- |
| Connexion protégée | Configuration activée par défaut, bandeau GTK, report des commandes automatiques et confirmation des actions GUI | Annulation sans exécution, déverrouillage explicite et suivi de l'identité du tunnel |
| Diagnostic | Sonde indépendante DNS/TCP/HTTPS, délai configurable, état daté et contrôle des redirections HTTPS | Sondes simulées, erreurs séparées et exclusion des identifiants |
| État réel des affectations | Comparaison entre cgroups désirés et constatés, erreurs des commandes asynchrones | Processus bloqué demandé mais pas encore affecté, échec avant délai de reprise |
| Historique | SQLite par minute, agrégation quotidienne, détail par application, rétention et CSV atomique | Reprise, périodes, conservation, unités distinctes et protection des cellules CSV |
| Alertes | Seuils configurables, incidents de tunnel, serveur indisponible confirmé et déduplication persistante | Deux sondes distinctes, trois relevés de débit, aucun changement réseau |
| Profils | Validation des URL/listes, fichier privé verrouillé, activation confirmée et restauration des paramètres en cas d'échec | Création/modification/suppression sans réseau, absence de redémarrage pour le même serveur |
| Validation GitHub | Workflow sur push/PR/lancement manuel, génération de bin/, tests, GTK isolé et wheel | Même suite exécutée localement, exécution GitHub vérifiée après publication |

La collecte de fichiers et les sondes fonctionnent dans des threads indépendants.
La file de stockage est bornée ; ses erreurs sont affichées dans Diagnostic.
La fermeture du moniteur laisse un délai borné pour terminer les écritures en attente.
Les erreurs des notifications de bureau n'arrêtent ni le stockage ni le moniteur.

L'historique représente les mesures disponibles depuis l'activation de la version 1.1.
Il distingue les octets physiques TCP+UDP des octets TCP échantillonnés par application.
Les compteurs de session ne sont pas importés comme une consommation historique.
Les profils ne s'activent jamais automatiquement. Une activation vers un autre serveur
peut interrompre les connexions ; elle reste une action confirmée de l'utilisateur.
En cas d'échec, les fichiers de configuration précédents sont restaurés et le diagnostic
est proposé, sans nouvelle tentative automatique de redémarrage du tunnel.
