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

## PR #178 — revue bot du 2026-10-28 (run `40743134485`, head `f1cbf721`)

| ID | Source / SHA examiné | Décision et chemins | Correction / preuve |
| --- | --- | --- | --- |
| R07 | Revue OpenCode, run `40743134485`, SHA `f1cbf721` — High `session_videos.py:484` | `confirmed` : `signup()` enregistrait un échec `friend-register` avant même l'issue, donc chaque inscription réussie consommait le budget per-IP (`auth._register_rate_limited` ne compte que `success=False`, cf. `auth.py:176-182`) ; un groupe derrière une IP partagée pouvait se verrouiller après 10 inscriptions | Contrats alignés sur `register` (`auth.py:429-461`) : échec enregistré sur chaque rejet (groupe invalide, email pris, nom vide, conflit commit), succès après commit. `test_successful_signup_consumes_no_failure_budget` échoue sur l'ancien code (1 échec compté) et passe corrigé |
| R08 | Même run — Medium `session_videos.py:373` | `confirmed` : le curseur `before` (id de session) ne filtrait que sur `date < date(before)`, donc une page coupée au milieu des N sessions d'un même jour (2 entraînements/jour, PR C) sautait les sessions restantes du jour | Keyset `(date, session_id)` accordé à l'ordre `date DESC, session_id DESC`. `test_feed_pagination_keeps_same_day_sessions` (22 sessions liées à 22 occurrences le même jour, pages 20+2) échoue sur l'ancien prédicat et passe corrigé |
| R09 | Même run — Medium `session_images.py:73` | `confirmed` : dérivés `session-images/` sous `media_cache_root` hors comptabilité et hors `cleanup_cache` (`media_cache.py:718-745`, `cleanup_orphan_thumbnails` limité aux namespaces `thumb`/`animated`) ; le plafond du media-cache ne les bornait pas | `cleanup_session_images()` (orphelins bornés : vidéos supprimées ou ids sans ligne ; cachées conservées car réversibles ; staging `*.tmp` jamais matché, publication atomique) branché dans `cleanup_cache`. `test_session_image_cleanup_removes_only_dead_videos` échoue sans la fonction et passe avec |
| R10 | CI `40740491642`/`40742154460`, job `postgres` | `confirmed`, cause branche (pas produit) : `test_postgres_migration_matches_models` couvre toutes les tables `sql_migration_only`, dont les 5 nouvelles tables session, mais `MIGRATIONS` ne listait pas les 3 migrations session ; `dive_guests` (table legacy créée au startup) manquait au seed | `MIGRATIONS` étendue (`add_session_videos` → `add_shared_sessions_v2` → `add_session_calendar`), `dive_guests` au seed. Parité + contraintes + concurrence vertes sur Postgres jetable local ; job `postgres` CI vert au run `40743142683` |
| R11 | Revue OpenCode, run `40745084443`, head `c8439d41` — High `session_videos.py:347` | `confirmed` : `session_payloads()` renvoyait date + titre d'une séance sans aucune vidéo visible pour le lecteur (tout cachée/supprimée), via un id deviné ; le test `test_later_videos…` encodait même ce comportement (visite 200 après suppression de l'ancre) | `session_payload()` 404 quand `after == 0`, zéro vidéo et pas `can_manage` ; proprios/admins gardent leur vue, pages suivantes (`after > 0`) inchangées. Les 2 tests échouent garde désactivée, passent avec |
| R12 | Même run — Medium `session_videos.py:419` | `confirmed` : réconciliation repartait du début à chaque passe et s'arrêtait à 2 000 clés ; l'inbox n'est jamais vidée (B2 jamais écrit), donc tout objet trié au-delà devenait invisible au filet de sécurité | Curseur rotatif `_reconcile_start_after` (`StartAfter` S3, wrap en fin de liste, convergence multi-processus par le claim idempotent). `test_reconciliation_rotates_past_the_key_budget` (3 objets, budget 2) échoue sans rotation, passe avec |
| R13 | Même run — Medium `session_images.py:151` (suite R09) | `confirmed` : dérivés des séances actives hors quota d'octets du media-cache | Même pattern que `orphan_animation_disk_bytes` : `session_image_disk_bytes()` ajouté à `_cache_size()`, donc le plafond borne le reste du cache en tenant compte des séances ; orphelins nettoient le reste (R09). Pas d'éviction des posters vivants (aucune régénération à la demande) |
| R14 | Même run — Medium `session_images.py:109` | `confirmed` : mon `cleanup_session_images` chargeait tous les ids non supprimés en un `.all()` (mémoire non bornée) | Vivacité vérifiée par lots de 100 ids assortis aux fichiers candidats ; test de cleanup borné à ≤ 1 requête pour 5 fichiers |
| R15 | Revue OpenCode, run `40746269338`, head `040d834c` — Medium `session_images.py:167` (suite R09/R13) | `confirmed` : compter les dérivés dans `_cache_size()` ne les plafonnait pas puisque le cleanup ne déloge jamais les posters vivants ; l'extraction publiait sans budget | `publish_images()` : budget persistant `SESSION_IMAGES_MAX_BYTES` (1 Gio, ~2 000 séances) vérifié sur le staging avant `os.replace` ; au-delà, staging jeté + RuntimeError → vidéo prête sans posters (état toléré existant). `test_session_image_publish_respects_disk_budget` échoue sans la garde, passe avec |
| R16 | Revue OpenCode, run `40747526761`, head `24c510f7` — Medium `session_videos.py:348` | `confirmed` : les totaux excluaient toujours les cachées alors que la liste les montre au proprio/admin (compte/durée/octets incohérents vs spec « totaux visibles ») | Prédicat de visibilité partagé entre la requête vidéos et l'agrégation. `test_owner_totals_include_hidden_viewer_totals_exclude` échoue sur l'ancien total, passe corrigé |
| R17 | Même run — Medium `session_images.py:145` (suite R14) | `confirmed` : mon scan loti parcourait quand même toute la collection avec une requête par lot de 100 | Curseur rotatif `_scan_cursor` + `scan_budget` (200 répertoires/passe, wrap) ; au plus 2 requêtes de vivacité par passe. `test_session_image_cleanup_rotates_scan` (3 dirs, budget 1 → 200/200/200/0) échoue sans budget, passe avec |
| R18 | Même run — Medium `notification_service.py:66` | `confirmed` : `session_video` exposé dans les prefs génériques (`_pref_defaults`/`set_pref`) alors que la spec interdit tout toggle pour l'alerte proprio | `_NON_EDITABLE_TYPES` : exclu de l'API (PUT → 422), défaut conservé, `is_enabled` ignore les lignes existantes. `test_owner_alert_has_no_preference_toggle` échoue sans, passe avec. Le toggle e-mail de groupe (`/session-preferences`, PR C) est séparé et inchangé |
| R19 | Même run — Medium `session_videos.py:573` | `confirmed` : file admin limitée aux 100 premières sans pagination (collisions suivantes inaccessibles) | Curseur `after` + `next_after` (`{items, next_after}`, miroir des pages d'enregistrements) ; `SignupReviews.tsx` suit les pages. `test_signup_review_queue_paginates` (101 files → 100 + 1) échoue sur l'ancien endpoint, passe avec |
| R20 | Même run — Medium `b2_setup.py:93` | `confirmed` : clé lab à portée du bucket entier (write+delete), seul le gate applicatif la cantonnait à `lab/` ; en cas de fuite, écrasement des originaux `inbox/` possible | Création avec `namePrefix: lab/`, réutilisation refusée si le préfixe déborde (`lab_prefix_ok`, testé : 7 cas). Script uniquement, jamais exécuté (zéro appel B2) |
