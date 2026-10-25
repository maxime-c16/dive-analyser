# Lot 1 — gel média et radiographie

25 octobre 2026. Mesures initiales sur `af90ba9` (backend de production audité
`18543d1`). Rebasé sans conflit sur `origin/master` = `a3dffafa`, incluant #158.
Le commit d'implémentation initial est devenu `7623d98b` et le compte rendu
`6f9ec737`. Aucun push, PR, merge, appel à ship.sh, accès SSH ou changement de
production. La révision ci-dessous couvre l'interaction avec #158 sans modifier D5.

## Résultat

- **P0-1** : `active_job_for_key` et `latest_active_job_for_asset` font uniquement
  des lectures. GET status et batch ne réclament plus de jobs ni de verrou.
  Les évaluations utilisaient déjà un SELECT direct (`evaluation_access._active_job`) :
  leur préparation explicite conserve la création de jobs, distincte du statut.
  Lease et création conservent la sérialisation et la reprise des expirés ; les
  passes de maintenance qui créent des jobs gardent cette même voie.
- **P0-2** : dépendance globale `member_access_context` synchrone, avec son même
  `db.info` installé puis retiré. Lectures de `media.py`, request/lease/viewed,
  `/auth/me`, grant et lectures de `media_playback.py` en `def`. Le grant conserve
  son rollback avant HEAD et sa revalidation après HEAD ; aucun changement de
  sélection D5, de signature ou de durée de vie des grants.
- **P1-3** : mise à jour conditionnelle atomique `last_accessed_at <= now - 1h`
  (ou NULL), donc une seule écriture par entrée et par heure, y compris entre
  processus. Commit seulement si une ligne a changé. Cache privé immuable un an
  côté backend seulement pour une URL dont `v` correspond au checksum courant ;
  les deux locations nginx internal-media-cache préservent ce choix. Versions
  absentes/anciennes et checksum inconnu : `private, no-cache`.
- **P1-4** : router WebSocket séparé, monté hors des dépendances SQL du routeur v1.
  Authentification admin dans une courte session dédiée exécutée en threadpool.
- **Radiographie** : échantillonneur de lag à 100 ms, logs et compteurs admins ;
  `Server-Timing: auth, db, app` ; logs nginx avec request/connect/upstream time ;
  surcouche admin `?xray=1`, cascade de ressources et timings autorisés, sans
  identifiants, URLs, paramètres, descriptions serveur ou stockage/export.

Choix simples : timeout de verrou de **500 ms** dans la transaction de création,
avec **503 + Retry-After: 1** en cas de contention ; granularité cache d'une heure ;
compteurs par worker, réinitialisés au redémarrage. Les spans auth/db/app se
recouvrent : app est le temps total avant en-têtes. Les requêtes bloquées dans
le pool ne sont pas comptées comme temps SQL. Une session SQL n'est jamais
utilisée simultanément par plusieurs threads dans ces chemins.

Le cache privé demandé accepte que des posters/proxies déjà en cache navigateur
restent visibles après révocation jusqu'à éviction. Les autres routes d'écriture
async hors périmètre peuvent encore faire du SQL synchrone : ce lot ne prétend
pas éliminer toute source de lag du backend.

## Avant/après mesurés localement

Environnement : Python 3.11.15, dépendances exactes de backend/requirements.txt,
httpx 0.25.2 (<0.28), Postgres 16 local jetable dans `/tmp/media-lot1-pg`, socket
`/tmp`, port 18543, `idle_in_transaction_session_timeout=5000`. Aucun média réel.

| Expérience | Avant | Après |
|---|---|---|
| Sonde advisory, 3 status + 1 lease, timeout idle 5 s | 15 020 et 10 040 ms, 2/2 rounds >1 s ; 5 kills idle-in-tx | Variante fixed : 7–33 ms, 6/6 <1 s, aucune réponse non-200 |
| Vrais handlers status + lease, HTTP via uvicorn et vraies sessions PG | Mécanisme initial reproduit par la sonde ci-dessus | 41,95 / 18,04 / 14,83 / 8,55 / 11,70 / 11,02 ms ; **0 kill** dans la tranche de log du test |
| Modèle event-loop, 15 posters, SELECT 1 ms / COMMIT 39 ms : dernier poster | 778,5 ms | 84,5 ms en threadpool avec COMMIT ; 44,9 ms en cache chaud sans COMMIT par vue |
| Même modèle : /me pendant la rafale | 763,8 ms | 22,6 ms en threadpool ; 31,6 ms en cache chaud |
| Fonction cache réelle, 15 lectures séquentielles, SQLite jetable | **15 commits**, fonction extraite de `af90ba9` | **1 commit** |
| Fonction cache réelle, 15 lectures concurrentes, PG | Ancienne fonction écrivait à chaque vue (mesure séquentielle ci-dessus) | **1 commit** |
| 4 WebSockets authentifiées simultanées | Session du routeur retenue par construction (audit initial) | **0 connexion empruntée** avant déconnexion |
| Création interactive avec verrou détenu par une autre session PG | Attente non bornée par lock_timeout local | 503 en environ 500 ms, assertion <1 s |

Preuves numériques :

- [lot1-advisory-lock-probe.json](lot1-advisory-lock-probe.json) : reproduction
  initiale, threadpool et suppression du reclaim, deux rounds chacun.
- [lot1-advisory-lock-fixed.json](lot1-advisory-lock-fixed.json) : six rounds avec
  dépendance et handlers sync, statuts sans verrou.
- [lot1-real-handler-probe.json](lot1-real-handler-probe.json) : six rounds de la
  régression PG contre les fonctions réelles, vérification des verrous et du log.
- [lot1-event-loop-probe.json](lot1-event-loop-probe.json) : modèle avant/après,
  cinq rafales par variante ; mesures de scheduling, pas des handlers prod.
- [lot1-cache-access-probe.json](lot1-cache-access-probe.json) : commits réellement
  émis par l'ancienne et la nouvelle fonction sur un poster synthétique.

**Limites** : le disque local n'est pas le HDD de production. Aucun nouveau temps
poster, LCP ou démarrage vidéo en production n'est revendiqué. Les 1,08 s médians
et gels de 30 s+ restent les références avant de l'audit ; leur après devra être
mesuré lors d'un futur déploiement autorisé. Les chiffres WebSocket et contention
sont vérifiés par assertions, pas ajoutés artificiellement aux JSON de rafales.

## Vérifications après revue

- **253 tests backend ciblés passent après rebase et correction de revue**, dont **5 intégrations PG** : concurrence
  HTTP avec vrais status/lease, absence de kills/transactions idle, sessions rendues
  pendant les WebSockets admin, timeout de création, accès cache concurrent, auth
  SQL hors du thread event-loop et conservation/nettoyage du contexte `db.info`.
- Les 6 tests propres au lot passent aussi après la dernière sécurisation de la
  lecture concurrente des compteurs de lag. Le test du lag bloque volontairement
  la boucle et vérifie le compteur >=100 ms.
- Sans `MEDIA_STARTUP_TEST_DATABASE_URL`, les **5 tests PG sont skipped**.
- **770 tests frontend / 94 fichiers passent** après `npm ci` et la commande
  demandée `NODE_OPTIONS=--no-experimental-webstorage npx vitest run`.
- **`npm run build` passe** (TypeScript + Vite + service worker).
- `git diff --check` passe. Tous les schémas JSON locaux des release notes sont
  valides, nouvelle note utilisateur incluse.
- Après rebase, `python ci/release-notes.py validate` **passe**. La note
  `library-durable-posters.json` de #158 est présente ; le décalage de base
  signalé lors de la première passe est résolu. Aucune note publiée modifiée.
- Aucun exécutable nginx/Docker local : syntaxe des configurations à vérifier
  dans les conteneurs cibles avant leur future application.

Régressions backend exécutées : `test_postgres_media_startup_lot1`,
`test_media_startup_lot1`, `test_library_media_payloads`, `test_media_job_fencing_d2`,
`test_p6_playback_default`, `test_p5_auth_playback`, `test_evaluation_sessions`,
`test_audit_regressions`, `test_session_diver_scope`, `test_media_node`,
`test_media_preparation_status`, `test_media_reclaim_drain_batch`,
`test_media_offload_cancellation`, `test_media_catalog`.

## Révision après #158 : contenu versionné

Correction locale : `ade87e14`. Rebase effectué après `git fetch origin`, sans
conflit, sur `a3dffafa` (#158).
`git merge-base --is-ancestor origin/master HEAD` confirme la nouvelle base.
Le validateur des release notes et le build ont été relancés avec succès.

`playback_url` prend désormais **l'entrée complète**, sans SQL supplémentaire, et
produit `/api/v1/media/cache/{id}/play?v=<sha256[:12]>`. Le checksum doit être un
SHA-256 hexadécimal valide ; il est normalisé en minuscules. Sans checksum connu,
l'URL reste sans version et la réponse reste revalidatable. Une version absente
ou différente renvoie les **octets courants avec `private, no-cache`**, sans
redirection. Seule la version courante obtient `private, max-age=31536000, immutable`.
Cela couvre GET, HEAD, Range et les réponses X-Accel.

Tous les producteurs ont été migrés : status et ses cache_entries, batch, réponse
de finalisation, vidéos, analyse, représentants, messages et profils (via le helper
de grille). La bibliothèque n'embarque pas de champ média à cette base : son
contrat de grille passe par batch. Aucun format d'URL signé n'a changé.

Les URLs de transport d'évaluation utilisent la même version de contenu, y compris
après `?rendition=...` via `&v=...`. Leur autorisation reste spécifique aux
évaluations ; elles conservent leur cache privé de **300 s** si la version correspond,
et passent en **no-cache** sinon. Elles ne deviennent pas immuables un an.

Les deux nginx ne forcent plus Cache-Control dans internal-media-cache : ils
préservent celui de la réponse backend lors de X-Accel. Un ancien lien ne peut donc
pas recevoir immutable via une surcharge nginx. Les anciennes réponses déjà fraîches
dans un navigateur ne peuvent pas être révoquées rétroactivement ; les nouvelles
URLs versionnées évitent de réutiliser leur clé de cache.

Audit des écritures de contenu (app, scripts, ops et migrations versionnés) :

- `durable_poster_cache._refresh` réécrit bien path + checksum sur le même id.
  Le changement de checksum change maintenant l'URL ; le contenu identique garde
  la même version, même si source/transform/path changent.
- `media_cache.finalize_cache_entry` réutilise une entrée déjà ready sans remplacer
  ses octets, ou crée une nouvelle entrée avec checksum vérifié. Les resolution
  upgrades passent par ce finaliseur et de nouveaux jobs/entrées ; ils ne modifient
  pas les octets d'une entrée en place. Le helper versionne également ces entrées.
- `browser_upload` enregistre de nouvelles entrées **sans checksum** : aucun cache
  immuable pour elles. Pas de hash de fichier ajouté au chemin de lecture.
- Pinning, `last_accessed_at`, nettoyage et migrations de protection ne changent
  pas les octets/checksums. Aucune autre réparation versionnée de MediaCacheEntry
  ne réécrit path/checksum ; `analysis_artifacts` modifie une autre table.
- Toute réparation future qui remplace les octets doit actualiser le checksum :
  la même règle centrale couvre alors automatiquement le changement de contenu.

Preuves supplémentaires après rebase :

- Refresh réel de poster durable : même id, nouveau checksum, nouvelles URLs
  status/batch ; l'ancienne URL répond 200 avec no-cache, la nouvelle est immutable.
- 24 cas GET/HEAD/Range, X-Accel activé/désactivé, versions correcte/ancienne/absente
  et checksum inconnu ; test des query strings déjà présentes et SHA invalide.
- Transport d'évaluation : versions poster/play/preview, cache privé court,
  mutation en place et revalidation de l'ancienne URL.
- **253 tests backend passent**, dont les 5 PG ; **770 tests frontend passent** ;
  **build TypeScript/Vite et validation release notes passent**. Les tests ajoutés
  sont dans `test_cache_content_version`, `test_durable_poster_cache` et
  `test_evaluation_requests`. Les régressions ont aussi couvert les upgrades,
  représentants, profils, messages, analyse et le parcours bibliothèque borné.
- [lot1-review-real-handler-probe.json](lot1-review-real-handler-probe.json) :
  19,35 / 6,07 / 6,28 / 6,17 / 6,08 / 6,21 ms pour 3 status + 1 lease ;
  **0 kill idle-in-tx**. Le cluster PG local a ensuite été arrêté proprement.

## Rejouer

Depuis la racine, après création d'un cluster PG jetable et de la base locale
`calendar_test_media_lot1` (aucune base existante n'est supprimée par la sonde) :

```sh
uv venv --python 3.11 /tmp/media-lot1-venv
uv pip install --python /tmp/media-lot1-venv/bin/python -r backend/requirements.txt 'httpx<0.28'
export PYTHONPATH=backend
export MEDIA_STARTUP_TEST_DATABASE_URL='postgresql+psycopg2://USER@/calendar_test_media_lot1?host=/tmp&port=18543'
export MEDIA_STARTUP_PG_LOG=/tmp/media-lot1-pg.log
/tmp/media-lot1-venv/bin/python -m pytest backend/tests/test_postgres_media_startup_lot1.py backend/tests/test_media_startup_lot1.py -q -s
/tmp/media-lot1-venv/bin/python docs/audits/media-startup-opus/advisory_lock_probe.py 'postgresql+psycopg2://USER@/postgres?host=/tmp&port=18543' --variants fixed --rounds 6
/tmp/media-lot1-venv/bin/python docs/audits/media-startup-opus/event_loop_probe.py
DATABASE_URL='sqlite:///:memory:' /tmp/media-lot1-venv/bin/python docs/audits/media-startup-opus/cache_access_probe.py --baseline-ref a3dffafa
```

La régression transforme la forme de la sonde advisory en test PG optionnel,
avec vrais handlers et sessions. Seule l'auth machine du lease y est neutralisée ;
la logique de lease, reprise, verrou, commit et statut est réelle. Le test refuse
les bases hors `calendar_test_*` et les hôtes non locaux ; chaque cas utilise un
schéma jetable propre. Le cluster local a été arrêté proprement après vérification.

## Reste à appliquer manuellement

Voir [MEDIA_STARTUP_XRAY.md](../../MEDIA_STARTUP_XRAY.md) pour le détail et les
limites d'interprétation des timings.

1. Lors d'une **future release autorisée**, livrer backend + frontend ; aucune
   migration SQL ni mise à jour Mac nécessaire pour ce lot.
2. Valider avec `nginx -t`, puis appliquer/recharger les **deux front doors** :
   config LAN `nginx/` et projet Funnel `ops/tailscale/`. Ces changements ne sont
   **pas automatiquement appliqués par ship.sh**. Vérifier headers et log formats.
3. **Propositions uniquement, non appliquées** : Postgres `log_lock_waits=on`,
   `track_io_timing=on`, `track_wal_io_timing=on`. Revoir coût et activation avec
   l'opérateur ; aucun ALTER SYSTEM, reload ou restart n'a été fait.
4. Comparer ensuite les kills, lag p99, timings posters et /auth/me, p50/p95 nginx
   et commits sur un chargement normal de /dives, avec et sans migration active.

Release note utilisateur : `media-startup-responsiveness` (backend + frontend),
car la correction des gels et le cache navigateur changent le comportement visible.
Les URLs signées, ThumbHash, production de vignettes et sélection D5 restent hors lot.

## Fichiers touchés

- `backend/app/api/v1/auth.py`
- `backend/app/api/v1/evaluations.py`
- `backend/app/api/v1/media.py`
- `backend/app/api/v1/media_playback.py`
- `backend/app/api/v1/messages.py`
- `backend/app/api/v1/videos.py`
- `backend/app/api/v1/ws_sync.py`
- `backend/app/database.py`
- `backend/app/main.py`
- `backend/app/services/dive_access.py`
- `backend/app/services/dive_analysis_service.py`
- `backend/app/services/evaluation_access.py`
- `backend/app/services/media_cache.py`
- `backend/app/services/media_jobs.py`
- `backend/app/services/representative_media.py`
- `backend/app/services/sessions.py`
- `backend/app/services/xray.py`
- `backend/release-notes/media-startup-responsiveness.json`
- `backend/tests/test_audit_regressions.py`
- `backend/tests/test_cache_content_version.py`
- `backend/tests/test_durable_poster_cache.py`
- `backend/tests/test_evaluation_requests.py`
- `backend/tests/test_library_bounded_player_flow.py`
- `backend/tests/test_media_startup_lot1.py`
- `backend/tests/test_postgres_media_startup_lot1.py`
- `docs/MEDIA_STARTUP_XRAY.md`
- `docs/audits/media-startup-opus/advisory_lock_probe.py`
- `docs/audits/media-startup-opus/cache_access_probe.py`
- `docs/audits/media-startup-opus/event_loop_probe.py`
- `docs/audits/media-startup-opus/lot1-advisory-lock-fixed.json`
- `docs/audits/media-startup-opus/lot1-advisory-lock-probe.json`
- `docs/audits/media-startup-opus/lot1-cache-access-probe.json`
- `docs/audits/media-startup-opus/lot1-event-loop-probe.json`
- `docs/audits/media-startup-opus/lot1-real-handler-probe.json`
- `docs/audits/media-startup-opus/lot1-result.md`
- `docs/audits/media-startup-opus/lot1-review-real-handler-probe.json`
- `frontend/src/App.tsx`
- `frontend/src/components/XrayOverlay.test.tsx`
- `frontend/src/components/XrayOverlay.tsx`
- `nginx/conf.d/default.conf`
- `nginx/nginx.conf`
- `ops/tailscale/nginx.conf`
