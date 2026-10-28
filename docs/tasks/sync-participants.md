# Binômes synchro — périmètre convenu

## Caption et attribution

- `SYNC MAT` ou `MAT SYNC` : Maxime + Mat.
- `SYNC MAT+SARA` : Mat + Sara ; ordre des participants indifférent.
- `SYNC` : Maxime + partenaire inconnu, à compléter.
- Résoudre les participants vers les profils et alias, sans créer un profil de binôme.
- Conserver la caption Photos source séparément du binôme effectif.
- Une validation manuelle dans l'app prime sur les prochains imports, y compris
  les renvois après perte de l'état Mac. Une nouvelle caption contradictoire
  signale un conflit sans écraser la validation. Les autres métadonnées restent
  actualisables depuis Photos.

## Reprise de l'historique

Comptage production du 28 octobre 2026 : 118 synchros, dont 32 avec un nom connu
(28 Mat, 3 Sara, 1 Fanny), 83 sans nom et 3 anciennes attributions RIP.
Les 32 permettent une proposition automatique Maxime + personne nommée ;
les 86 autres demandent une revue. Ces propositions ne prouvent pas à elles
seules la présence réelle de Maxime dans les anciennes vidéos.

Prévoir une mini UI vidéo + caption source + deux participants + validation
et passage au suivant. Installer la protection contre les écrasements avant
toute migration.

## Conservation et nettoyage des originaux Photos

Inclure l'adaptation de `backend/app/services/photos_cleanup.py` et du contrat
avec le worker Mac dans le même chantier. Aujourd'hui, le nettoyage refuse
tous les synchros (`person_not_exclusive`) : conserver ce comportement tant
que la nouvelle résolution des participants n'est pas en place.

- Maxime parmi les participants effectifs : conserver dans Photos.
- Deux autres participants identifiés sans ambiguïté, sans Maxime : candidat
  au nettoyage uniquement si toutes les garanties existantes passent.
- Binôme incomplet, identité ambiguë ou conflit caption/validation : conserver.
- Pour les nouveaux imports, appliquer la convention ; pour l'historique
  ambigu, ne pas déduire une autorisation de suppression d'une simple migration.
- Conserver les vérifications de sauvegarde B2, hash, taille, version Photos,
  révisions et permissions ; ne pas utiliser le seul `diver_id` historique.
- Invalider toute autorisation de nettoyage devenue obsolète après modification
  du binôme ; revérifier côté serveur avant suppression, y compris pour une
  entrée déjà en file. Le binôme validé doit faire partie de cette fraîcheur.
- La correction des 118 synchros ne doit pas créer de suppressions rétroactives :
  la file reste limitée aux nouveaux ingests continus admissibles.

Validation à prévoir : moi + partenaire conservé, deux tiers admissibles sous
toutes les garanties, inconnu/conflit conservé, correction manuelle résistante
à un renvoi Mac, changement de binôme invalidant une décision en file.

Ce document décrit le travail à implémenter ; aucun comportement déployé changé.
