# Global historical media migration (HQ / light / poster)

## Mission brief (copied verbatim from the parent thread, 2026-10-22)

> Mission : construire puis lancer la migration globale historique HQ/light/poster comme service persistant SUR LE SERVEUR, autonome sans laptop/conversation, et porter la PR jusqu'au déploiement vérifié.
> Autorisation Maxime : « okay lance un thread opus 5.5 pour faire tout le travail. puis PR et babysit juqu'au deploiement ». Aucun GO routinier, implémentation+push+PR+corrections+merge+serveur/Mac déploiements nécessaires+activation/migration autorisés. Une PR groupée autant que possible. Aucun autre agent/chantier concurrent.
> Lis AGENTS.md, docs/REPO_WORKFLOW.md, docs/CD.md, docs/RELEASE_NOTES.md et skills babysit-pr/t3-deleguer. Copie ce brief dans docs/design/media-global-migration.md et tiens un checkpoint privé sans secrets.
> Contexte parent détaillé : /private/tmp/dive-media-overnight-20261021.md (lire les dernières sections surtout). Runtime serveur/frontend/Mac 64f417f48ffb926d349ee2c3ed139050a526a5e6 PR148 merged/APPROVE+CI et déployée, auto nouveaux médias active depuis 2026-10-22T11:38:09.055998+00:00, REQUIRE_LEASE_TOKEN=true/master=true/AUTO=true. Respecter tout descendant plus récent.
> Inventaire brut récent : 2998 dives video_uuid, 2992 UUID avec révision originale enregistrée (PAS preuve exacte tous exploitables), 5 packages READY/15dérivés. 4 canary PROVEN avec SHA B2/originaux/Range/expiry/formats/cadence; 5e privé MAT user1 interdit accepté comme nonPROVEN. Ne modifier AUCUN accès/auth/visibilité pour migration. Maxime Safari clip3017 lecture complète switchLight/HQ~1s (observation utilisateur).
> But complet : inventorier EXACT les sources canoniques PROD vérifiées, ignorer packages déjà valides SHA+transform, produire historique progressivement via encodeur et publication existants, état/progression durable DB, contrôle pause/reprise/status, erreurs bloquées visibles, service/timer conteneur/host serveur géré et restart-safe (pas script local/nohup laptop/T3 scheduler).
> Réutiliser services existants derivative_publisher/web_packages/media_jobs/automatic_packages/derivative_read, D2 fencing, globalONEpackage. Les modèles MediaPopulationRun/Item et representative_population existent mais anciens poster/proxy720; réutiliser seulement si bon contrat sans casser ancien.
> Inspecter migration originale Mac ingest/migration_full.py et outils existants; ne pas ré-uploader originaux B2 déjà vérifiés. Sources manquantes/inconnues doivent être explicitement bloquées/réparées par pipeline approprié, jamais faussement terminées. Traiter aussi changements source/version et HQalias autoritatif. Ne déclarer terminé qu'après ledger+PROD durables et lecture compatible. Pas browser/evaluation cutover non nécessaire.
> Admission petite file/replenishment, priorité fond>=60 (préférer70 derrière nouveau60), max_attempts2, ONE conversion fleet; interactive non affamée. Pause servercache<25GiB/Macscratch<8GiB ou memorypressure!=0/unknown, erreursrépétées; original/cache/vault/pins/grace/thresholds ne jamais purger/renommer/supprimer. Ressources récentes Mac15GiB/servercache36GiB. PR148 automatic_packages contient guardsserver+breaker2fails; Mac media_jobs probe offloop avantlease. Ne pas bypass breaker via nouveaux IDs/réinitialisation aveugle. Prévoir métriques réelles objets/bytes/erreurs, budget de migration explicite opérationnel (2GiB était canary-only, pas plafond global implicitement).
> Tests significatifs reprise/crash/idempotence/concurrence PG réelle/locks/cap/budget/source drift/pause/legacy et compteurs honnêtes, source sansB2 non mislabeledready. CItiers inclure nouveauxPGtests dans ci/postgres.sh. Venv local backend utilisable (cache dive-ci); Mac osxphotos stub local tests; hostedCIauthoritative.
> PR: link_pull_request immédiatement, native watch puis FINtour paspollCI; APPROVE explicite exactHEAD+allCI+threads before guarded --match-head-commit squash, pas override. Chaque reviewround vérifier toutesfindingsensemble. UserveutPRs/revuesgroupées pouraller vite.
> Déploiement seulement ci/ship.sh status/dryrun/normal depuisCURRENTMERGED DEVcheckout, paslive edits. Ancienparent9322dc0 ship ESTDANGEREUX ne sourcepas media-jobs.env. Serveurdev existant /tmp/media-canary-ship-3d0126d @64f417f, laptopdev merged /private/tmp/dive-auto-ship-64f417f. SSH diveanalyzer-server(mcauchy deb-serv), diveanalyzer-mac(divesensei). Serveurlive ~/dive-analyser jamaiseditcheckoutmanual, Maclive /Users/Shared/services/data/diveanalyzer/code. Managedserverenv ~/.config/diveanalyzer/media-jobs.env0600 preserveREQUIRE/AUTO/SINCE. RunshipONSERVERdevelopmentcheckout envpreserved. SQLmanual additive backup/apply ordered/idempotent avantdeploy, proxies2reload/checkhealth selonactualdelta, locks respectés. Macship autorisé si nécessaire dryrun+PIDstable20s.
> Ne pas dump secrets/env/session/signedURLs. No authmint/reset/cookiesexport. La migration est système administratif, ne dépend pas session opérateur personnelle. Reprise service doitcontinuer serveur+Mac même tousclientsfermés. Pas contactextérieur/notificationsutilisateurs.
> Fin après CIAPPROVEmerge deploy et démarrage prouvé petit premier lot historique (pas milliersqueue) : mesurer jobs réellementtraités, ledger/B2/formats/source intacts, progression persistante et processus/service actifenserveur, configuration+pause/status exacts. Ne pas attendre fin3000clips pour livrer, mais ne pas prétendre autonomie si seulementoutil inert. Donner PR/mergeSHA/liveSHAs/runID/compteurs/commande suivi/pause/limites/reste. Lier parent thread et signaler le résultat via outil de message thread si disponible; parent te supervise.

## What it does

A server-side controller converts every historical clip to the durable
`hq` / `light` / `poster` package, one clip at a time, with the pipeline
that already serves new ingests:

```
systemd timer (deb-serv, every minute)
  -> ops/media-migration.sh -> docker compose exec backend python scripts/media_migration.py tick
     -> app/services/media_migration.py  (DB state: media_migration_runs / _items)
        -> create_or_reuse_media_job(web_package, reason=historical_migration, priority 70, max_attempts 2)
           -> Mac lease (D2 token, global ONE package, Mac disk/memory gate)
           -> fenced slot publish (D3b2) -> derivative_publisher (B2 PUT + full GET verify + ledger)
        <- completion judged by the D5 read contract (resolve_clip_derivatives)
```

Nothing new encodes, uploads, signs, deletes or renames. Originals are
never re-uploaded: the package job reads the already-verified canonical
PROD original (`resolve_canonical_source_revision`). No access, auth or
visibility rule is consulted or changed: storage is administrative.

### State (durable, PostgreSQL)

`media_migration_runs` (one open run at a time, enforced by a partial
unique index): `status` active/paused/cancelled + `pause_reason`, pinned
`transform_version`, `priority` (>= 60, default 70), `max_attempts` 2,
`queue_depth` (1..5, default 2), explicit `budget_bytes`, optional
`admission_cap`, `admitted_jobs`, sweep cursor, `last_tick` JSON.

`media_migration_items`, one per `dives.video_uuid`:
`pending` -> `queued` (job id, owned or adopted) -> `complete`, or
`skipped_complete` (valid package already existed), `blocked` (reason),
`failed` (reason + last error). Published bytes/objects, settled budget
charge and source-change count are recorded per item.

### Tick (bounded, idempotent, one transaction)

1. `pg_try_advisory_xact_lock(73125, 20)`: a concurrent tick returns `busy`.
2. Sync: up to 500 not-yet-tracked dives (newest first) get a `pending` item;
   inserted items are excluded next time, so the library converges in a few
   ticks and each tick stays bounded (`status` reports `unsynced_dives`).
3. Refresh queued items from their job: `ready` + read contract complete
   -> `complete`; ready but not servable -> `failed ready_job_not_servable`
   (never a false "complete"); `failed`/`unavailable` -> `failed` with the
   job error; cancelled -> `pending`; a terminal job whose pinned source no
   longer matches the canonical source -> `pending` (source drift). A queued
   job whose canonical source vanished is withdrawn and the item blocked
   (the lease would otherwise skip it forever).
4. Sweep 100 settled items per tick (rotating): complete items whose source
   or transform drifted go back to `pending`; blocked items whose source was
   repaired are unblocked; failed items with a new source are retried.
5. Gates (all must pass, otherwise nothing is admitted and the reason is
   in `last_tick.blocked_gates`): run active; `MEDIA_WEB_PACKAGES_ENABLED`;
   current derivative transform == run transform; a healthy package-capable
   worker; fresh Mac facts (scratch >= 8 GiB, `vm.memory_pressure == 0`;
   unknown or older than 15 min blocks); server cache >= 25 GiB; package
   breaker closed (two consecutive terminal package failures stop
   everything, including new-ingest packages); budget; admission cap.
6. Admission, under the lease lock `(73125, 1)` shared with every other
   package creator: fill up to `queue_depth` active jobs created by the
   migration, newest dives first. Each candidate is re-classified at
   admission: package already valid for the current source + transform ->
   `skipped_complete`; no canonical verified PROD source -> `blocked
   no_canonical_source`; unknown dims/duration -> `blocked`; an active
   package job from another path -> adopted (no duplicate, no priority
   change, no charge); a terminal package for the same source + transform
   already failed -> `failed prior_package_failed` (no silent retry).

### Priorities and fairness

Lease order is priority ascending: interactive (5/6) < new ingest packages
(60) < migration (70). The global one-package cap means an interactive or
new-ingest package waits at most for the package in flight. Legacy poster /
proxy jobs are not affected (separate capability slots).

### Complete means durable and readable

An item is `complete` only when the D5 read contract serves light, poster
and hq for the CURRENT canonical source and transform: ledger row `ready`,
`derived_*` backbone revision, exactly one verified PROD B2 replica in the
allowlisted bucket. The small-source hq alias counts only when the ready
producer job's pin (`hq_aliased_to = light`, same source + transform)
confirms it. A job marked ready without that durable proof is reported as
failed, never complete. Sources without a verified B2 original are blocked,
never labelled ready.

### Budget (explicit, conservative)

The run carries an explicit byte budget for NEW derivative objects in B2.
An in-flight job reserves `worst_case_package_bytes(source) * max_attempts`;
a finished job settles `published + estimate * (attempts - 1)` (ready) or
`max(estimate * attempts, published)` (failed/cancelled: orphan uploads
possible). Pre-existing packages and adopted jobs are not charged. The 2 GiB
canary ledger is unrelated and unchanged. The budget only stops admission;
it never deletes anything.

### Mac facts

The Mac heartbeat now reports `storage_status.package_resources`
(`scratch_free_bytes`, `memory_pressure`, `available`, `measured_at`): the
same measurement as its pre-lease package gate, so the server status names
a Mac-side pause. The Mac keeps gating its own lease; this is visibility
plus an admission gate, not a replacement.

### Failures and the breaker

Failures are visible in `status` (reason, job id, error). Nothing retries
silently; `retry-item` is an explicit per-item operator action and every
gate, including the breaker, still applies. When the breaker is open (two
consecutive REAL terminal package failures) all package leasing stops (PR148
contract) and the migration admits nothing; recovery needs an
investigation and a reviewed decision, there is no reset command.

Infra failures are different: a package killed by the platform (lease
expiry, transport status 0, gateway 502/503/504, e.g. a backend restart
during a deploy) says nothing about the clip. They are skipped by the
breaker streak and the clip is re-admitted automatically with a fresh job,
at most `INFRA_RETRY_LIMIT` (3) times per clip, after which it stays
`failed`. A storm of infra failures (>= 3 within 30 min) opens the breaker
too, and it closes by itself once the platform has been quiet for 30 min.

## Inventory before activation (PROD, read-only, 2026-10-22)

2998 clips (distinct `dives.video_uuid`): 5 already complete (the canary
packages, including the private MAT clip — durable, access-independent),
7 blocked `no_canonical_source` (no verified PROD original), 2986 to
convert. Source bytes to convert 65.6 GB (61 GiB); worst-case estimate
224 GB (reservation formula, not expected usage). Canary packages measured
about 0.9x source bytes, so the expected B2 growth is around 55-60 GB.

## Operations (deb-serv)

All commands run in the backend container from `~/dive-analyser`:

```bash
M='docker compose exec -T backend python scripts/media_migration.py'
$M status            # run, items, gates, budget, throughput, active jobs, failures
$M status --json
$M inventory [--limit N]  # read-only exact classification, batched (about 2 s on PROD)
$M pause --reason "..."   # stop admitting, withdraw not-yet-leased jobs
$M resume
$M set --budget-gib 80 | --queue-depth 2 | --admission-cap 5 | --no-admission-cap
$M retry-item --video-uuid <uuid> --reason "..."
$M cancel --reason "..."
journalctl -u dive-media-migration.service -n 20 --no-pager   # tick JSON lines
systemctl list-timers dive-media-migration.timer
```

Hard stop without touching the DB: `sudo systemctl stop dive-media-migration.timer`
(already leased jobs finish; queued jobs stay queued at priority 70 until
the timer or a `pause` withdraws them).

## Deployment

1. Merge after CI + APPROVE on the exact head.
2. Back up, then apply `backend/migrations/add_media_migration_runs.sql`
   twice (idempotent, additive; old code ignores the tables) BEFORE the
   server deploy.
3. From a CURRENT merged development checkout on deb-serv:
   `ci/ship.sh status`, `ci/ship.sh server --dry-run`, `ci/ship.sh server`
   (managed `media-jobs.env` is sourced; REQUIRE/AUTO/SINCE preserved).
4. `ci/ship.sh mac --dry-run`, `ci/ship.sh mac` (heartbeat facts); check
   the agent PID is stable and the next heartbeat carries
   `package_resources`.
5. Install the timer (not done by ship):
   `sudo install -m 0644 ops/systemd/dive-media-migration.{service,timer} /etc/systemd/system/`
   from the live checkout, `sudo systemctl daemon-reload`,
   `sudo systemctl enable --now dive-media-migration.timer`.
   Without an open run a tick is a no-op (`no_run`).
6. `inventory`, then `start --budget-gib 80 --queue-depth 2 --priority 70
   --admission-cap 3` for a proven first lot; verify jobs, ledger, B2
   objects, formats and source integrity; then `set --no-admission-cap`.

Rollback: `pause` (or stop the timer). Code rollback with
`ci/ship.sh server --ref <previous>` is safe: the tables stay and old code
ignores them. Nothing is purged; produced packages stay valid.

Release notes: none — background operational migration; the user-visible
playback contract already shipped (durable-library-playback).

### Grid posters

The Library grid serves posters from the local cache only (nginx X-Accel,
browser-cacheable, no B2 grant/HEAD/302 per tile). Measured 2026-10-25: a
B2 poster tile would cost a cold provider HEAD (~2.2 s), a ~0.4 s B2 GET and
an uncacheable `no-store` redirect on every visit. Each `tick` therefore also
copies up to 40 durable posters (D5-servable, trusted replica, SHA-256
verified against the ledger) into the cache as pinned `poster` rows, once
per clip, without ever replacing an existing poster row and only while the
cache filesystem keeps more than 26 GiB free
(`app/services/durable_poster_cache.py`).
