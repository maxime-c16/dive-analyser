# Registre des findings de review

## Utilisation

Une entrée suit une cause sur une PR, même si plusieurs runs la répètent.
Ajouter la source et le SHA effectivement examiné, puis distinguer :
`confirmed`, `rejected`, `duplicate`, `already-fixed`, `outside-diff`, `unresolved`.
Une sévérité de bot n'est pas une adjudication. Un APPROVE ne suffit pas à
classer une correction comme prouvée. Ne pas stocker de tokens, URL signées,
corps privés ou exceptions brutes. Les preuves renvoient aux tests versionnés.

## Audit ciblé du 28 octobre 2026

Base du code inspecté : `cf2de2c24bf0417a94f0ca31c832dedaf8e46389` (master).
Périmètre : contrats d'accès, identités et alias, caches Library/community,
AuthContext et agrégations du classement. Cet audit n'est pas une validation
exhaustive de chaque famille de la cartographie ni de la production.

| ID | Source / SHA examiné | Décision et chemins | Correction / preuve |
| --- | --- | --- | --- |
| R01 | [#173, alias](https://github.com/maxime-c16/dive-analyser/pull/173#issuecomment-6467104600), run `40675337585`, SHA `39ece0088e92ad02624f6ab187695c1e61e27732` | `already-fixed` sur la base auditée : `sync_participants.matching_diver_ids` utilise `SELECT DISTINCT id LIMIT 2`, partagé par le script de migration | `test_sync_participants.py` et `test_photos_cleanup.py` ; pas de nouvelle correction de requête |
| R02 | [#172, limite sur jointure](https://github.com/maxime-c16/dive-analyser/pull/172#issuecomment-6452271505), run `40574238164`, SHA `21e7fa4c7c56417b39ba3fa287c870878d30b2ef` | `already-fixed` sur la base auditée : déduplication SQL des identités avant la limite dans `photos_cleanup.py` | Tests d'ambiguïté/alias existants exécutés ; ne pas réintroduire une limite sur les lignes jointes |
| R03 | [#166, cache lecteur](https://github.com/maxime-c16/dive-analyser/pull/166#issuecomment-6403091676), run `40232526038`, SHA `fc70445aae85374409c941c2a9e05bf640b57c0a` | `already-fixed` pour la clé : `codeSummariesApi` et `codeCommunityApi` incluent le lecteur ; les appelants passent `libraryKey(user)` | Tests de séparation des lecteurs existants exécutés. Ceci ne prouve pas toutes les transitions AuthContext : voir R06 |
| R04 | [#34, friend read-only](https://github.com/maxime-c16/dive-analyser/pull/34#issuecomment-6002560080), SHA historique non collecté | `rejected` comme règle actuelle : `write_guard.py` et `dive_access.py` autorisent les écritures de plongeons par ownership ; statut historique non adjugé | En-tête de `test_friend_access.py` corrigé ; portée historique indiquée dans `USER_AUTHORIZATION_V1.md`. Prompt bot conserve son exception explicite |
| R05 | [#168, matérialisation](https://github.com/maxime-c16/dive-analyser/pull/168#issuecomment-6404503639), SHA historique non collecté ; reproduction sur la base auditée | `confirmed` : `community_leaderboard.py` lit les comptes, histogrammes et jours de toute la communauté avant son top 10 | Correction produit : classement, médianes et semaines consécutives en SQL ; au plus 41 comptes matérialisés. `test_leaderboard_bounds.py` compare le résultat complet à une référence indépendante sur SQLite et PostgreSQL. L'ancien code charge 73 comptes et fait échouer la borne |
| R06 | Audit actuel, base ci-dessus ; famille des réponses périmées [#76](https://github.com/maxime-c16/dive-analyser/pull/76#issuecomment-6036991079) | `confirmed`, nouveau cas : dans `AuthContext.tsx`, un ancien `/me` peut remplacer le compte plus récent ou revenir après le début du logout | Correction produit : génération des opérations, gardes succès/erreur/finally, déconnexion locale immédiate, invalidation des caches dérivés. Les 5 tests de `AuthContext.test.tsx` échouent sur l'ancien code et passent avec la correction |

R05 et R06 sont des causes indépendantes : PR produit séparées, avec notes de
version et validation adaptées. Leur état ici décrit une correction préparée,
pas un déploiement. Les liens de PR permettent de suivre le SHA final et la CI.

- R05 : [PR #175](https://github.com/maxime-c16/dive-analyser/pull/175),
  head initial `7a7fbdef` (backend).
- R06 : [PR #174](https://github.com/maxime-c16/dive-analyser/pull/174),
  head initial `1913aff3` (frontend).

## Validation de cette passe

- 45 liens de la cartographie retrouvés dans le corpus GitHub collecté.
- Deux skills validés avec `skill-creator/scripts/quick_validate.py` et copiés
  sans modification dans le répertoire personnel de skills.
- 53 tests CI internes passent ; YAML de workflow vérifié séparément.
- Frontend : 820 tests passent et build TypeScript/Vite/PWA réussi.
- Audit backend ciblé : 64 tests passent, incluant les nouveaux cas SQLite et
  PostgreSQL. Le test de borne échoue sur l'ancienne implémentation du classement.
- Suite backend complète sur les corrections combinées : 1 812 passés, 83
  ignorés, 28 désélectionnés, 3 échecs. Ces trois échecs (conversion HDR et
  WebP) se reproduisent sur la base master inchangée ci-dessus ; le FFmpeg
  local ne fournit ni `zscale` ni encodeur WebP. Aucun baseline de tolérance
  ajouté : la CI Linux reste nécessaire.
- Le wrapper local `ci/gate.sh` ne peut pas démarrer sans `flock` sur ce Mac ;
  les vérifications ci-dessus ont été lancées directement. Cela ne vaut pas
  exécution complète du gate ni vérification des images/proxies Linux.
- Node local 26 nécessite `NODE_OPTIONS=--no-experimental-webstorage` pour que
  les tests utilisent le stockage jsdom ; GitHub CI utilise Node 20.
