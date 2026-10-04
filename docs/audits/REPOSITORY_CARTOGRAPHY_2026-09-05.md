# REPOSITORY CARTOGRAPHY — Dive Analyser / DiveSensei

Date: 2026-09-05
Scope: read-only reconnaissance. No production code, data, media or configuration was modified.
Author: local reconnaissance agent (fresh thread, evidence-first).

---

## 1. Executive summary

Dive Analyser ("DiveSensei") is a **two-machine, two-tier personal diving-analytics platform**:

- **Machine B** (older Intel MacBook, macOS 15.1.1, `192.168.1.19`) runs a Python
  launchd agent that polls the macOS Photos library, parses user-authored captions
  into structured dive metadata, syncs that metadata (JSON only, no video) to the
  server, and serves as a *media node*: on demand it exports assets from Photos,
  transcodes posters/proxies with ffmpeg, and uploads the renditions to the server.
  Original video bytes for new dives **never leave the Mac** (source-vault design).
- **Machine A** (Debian 12 home server, `192.168.1.57`) runs the live stack via
  docker compose in `~/dive-analyser`: PostgreSQL 16 (44 tables), FastAPI backend
  (20 routers, ~21k service LOC), React 18/Vite frontend, nginx reverse proxy,
  adminer. It holds **no originals for new dives** — only a rendition cache
  (~840 MB) plus 82 legacy originals (14 GB) from a June 2026 upload era, mixed
  with 94 zero-byte placeholder files.

The system is **in production use**: 2,803 dives / 168 sessions / 23 divers in DB;
agent has run continuously since 2026-08-05.

Analysis today is **user-authored metadata + deterministic aggregation + DB heuristics**.
There is **no computer vision, no pose estimation, no ML**. `execution_analyzer.py`
is a hardcoded stub; the FINA "execution" sprint added a fault-detector rule engine
whose inputs (`ExecutionMetrics`) are supplied manually via API, not computed.

The most urgent findings: the API-key authentication is a **stub accepting any
string ≥ 10 chars**; Mac→server traffic is **plain HTTP on the LAN**; the docker
compose file mounts a **macOS Photos-library path on a Linux host** (dead legacy);
the mac-agent source in the server repo has **drifted from the deployed agent**.

## 2. Evidence and methodology

Inspect → trace → cross-check loop over:

- local repo `~/.perso/diveanalyzer` (partial copy; byte-diff verified, see §26)
- Machine A over SSH: `~/dive-analyser` tree, git, docker ps/inspect, live Postgres
  **read-only** queries (`\dt`, counts, `\d media_jobs`), nginx config, docs/
- Machine B over SSH: deployed agent code, launchd plist, config.yaml (secrets
  redacted), logs directory listing, media-node layout
- No tests were executed; no heavy commands; no writes on either machine.

Evidence labels: **PROVEN** (direct artifact), **STRONGLY INFERRED** (multiple
consistent artifacts, no runtime verification), **UNKNOWN** (not determinable).

## 3. Repository identity

| Item | Value |
|---|---|
| Local repo path | `/Users/maximecauchy/.perso/diveanalyzer` |
| Local git | **not a git repository** (no `.git`) |
| Canonical repo | `mcauchy@192.168.1.57:~/dive-analyser` |
| Branch | `uiux-overhaul-pro-app` |
| HEAD | `7ae8b0186d21bd040c0af2caf675cd6080e365a3` — 2026-02-03 "Restructure: Move app code from diving-analyser/ to dive-analyser/ …" |
| History | **single squashed commit**; `.git.clawdbot` directory also present |
| Remotes | none configured (PROVEN: `git remote -v` empty) |
| Working tree | dirty: many staged docs (`DD_*`, `PHASE_*`), deleted `BOOTSTRAP.md`, modified `.env` |
| Footprint | backend 5.1 MB, frontend 208 MB (incl. node_modules/dist/playwright artifacts), media 15 GB (data, not code), mac-agent 176 KB |
| Submodules / LFS | none (PROVEN) |
| Languages | Python (backend + agent), TypeScript/React (frontend), SQL (migrations), Bash (ops scripts) |
| Build systems | Dockerfile (backend), docker compose, npm/Vite (frontend), setuptools/pyproject (agent) |

Historical siblings on Machine A (evidence of iteration, all non-canonical):
`~/divesensei` (git, Mar 2026), `~/divesensei-app` (git monorepo + analysis
benchmarks/outputs, Apr–May 2026), `~/diving-video-upload` (Feb 2026, iOS
Shortcut/iCloud/Dropbox upload experiments), `~/diving-analyser.old-removed`,
`~/tmp_divesensei` (empty), `~/divesesensei-r41-check` (empty).

## 4. Repository structure (canonical, `~/dive-analyser`)

```
backend/            FastAPI app (app/api/v1 20 routers, app/models 24 files,
                    app/services ~60 modules ≈ 21k LOC), migrations/ (21 .sql),
                    tests/ (30+ files), legacy_scripts mount of ./src
frontend/           React/Vite app (src/pages 9+, src/components 20), e2e/, tests/
mac-agent/          STALE copy of agent source (10 src modules) + deploy/, tests/
media/videos/       176 files: 82 real originals (Jun 9 2026, incl. 7.3 GB) + 94 × 0-byte
media/cache/        rendition cache 854 MB
nginx/              nginx.conf + conf.d/default.conf + ssl/
docs/               15 curated ops/design docs (media node, DD, ingestion) — good quality
backups/            database/, frontend-source/, mac-media-01/, media-manifests/, staging/
ops/ logs/ reports/ src/ (legacy mount) memory/ test-results/
~90 root-level .md status/phase/ticket reports (Feb 2026 agent-session debris)
```

## 5. Physical deployment architecture

```text
+----------------------------------+          +------------------------------------------+
| Machine B: older MacBook (x86_64)|          | Machine A: deb-serv (Debian 12,          |
| 192.168.1.19  user divesensei    |          | 192.168.1.57  user mcauchy)              |
|                                  |          |                                          |
| macOS Photos library             |          | nginx :6090 (HTTP) / :6443 (TLS)         |
|  (manual trim + caption)         |          |   ├─ /api/  → FastAPI backend :6002      |
| launchd com.diveanalyzer.agent   |          |   ├─ /      → frontend :6001             |
|  → python -m src.main            |   HTTP   |   ├─ /adminer → adminer :8080            |
|  sync loop      every 600 s      | +X-API-  |   └─ /health                             |
|  media job loop every 30 s       |   Key    | docker compose (network diving_network)  |
|  catalog loop + heartbeat 300 s  | -------> |  ├─ postgres:16-alpine :5433 (44 tables) |
|  ffmpeg (vendored bin)           |          |  ├─ backend  (uvicorn, 2 workers)        |
| source vault:                    |          |  ├─ frontend (dive-analyser-frontend)    |
|  /Users/Shared/services/data/    |          |  ├─ adminer                              |
|  media-node/sources/by_uuid      |          |  └─ (v2-candidate containers :6003/      |
|  (ORIGINALS STAY HERE)           |          |      6091/6092 — experiments, up)        |
|  renditions (tmp) → upload       |          | media/cache 854 MB + media/videos 14 GB  |
+----------------------------------+          +------------------------------------------+
```

Agent process (PROVEN, ps): `/Users/Shared/services/data/diveanalyzer/venv/bin/python
-m src.main --config .../state/config.yaml`, started 2026-08-05, ~1117 CPU-minutes.

## 6. Logical architecture

Backend routers (`app/api/v1/`): analytics, dd_operations, dive_analysis, dive_codes,
divers, dives, execution, health, import_data, journey, media, personal_dive_value,
psychology, scoring, sessions, training_periods, videos, ws_sync (WebSocket sync
status), + `__init__` aggregator. Service layer holds the domain logic.

Key services: `import_service` (JSON bulk import + startup auto-import w/ pg advisory
lock), `dive_code_parser/validator`, `dd_*` (DD engine + lookups + auto-assign +
`world_aquatics_dd` official provenance), `performance_scorer`, `fina_validator`,
`journey_service` + `milestones` (post-sync hooks), `fear_analyzer`,
`execution_fault_detector`, `personal_dive_value`, `dive_analysis_service`,
`media_agents/media_jobs/media_cache/media_recall/media_catalog/
representative_media/media_resolution_upgrade/sync_status`.

## 7. Component inventory

| Component | Purpose | Location | Lang | Entry | Machine | Startup | State | Active | Confidence |
|---|---|---|---|---|---|---|---|---|---|
| mac-agent | Photos poll, caption parse, metadata sync, media-node jobs, catalog, heartbeat | deployed `/Users/Shared/services/data/diveanalyzer/code` (canonical source on B; stale copy in server repo `mac-agent/`) | Py 3.12 | `src.main` | B | launchd (KeepAlive≠0 exit, RunAtLoad) | `~/.diveanalyzer/{sync_state.json,queue.json}`; media-node dirs | YES | PROVEN |
| FastAPI backend | REST API, ingestion, analysis services, video streaming | `~/dive-analyser/backend` | Py 3.11 | `uvicorn app.main:app` | A (docker) | compose, restart unless-stopped | Postgres + media/cache | YES (healthy 3 wk) | PROVEN |
| PostgreSQL 16 | all relational state | docker volume | SQL | — | A | compose | postgres_data | YES | PROVEN |
| Frontend | UI (Dashboard, Dives, Sessions, Journey, Analytics, DiveAnalysis, MediaRecall, RepresentativeMedia, Admin) | `~/dive-analyser/frontend` | TS/React | nginx serve dist | A | compose | — | YES | PROVEN |
| nginx proxy | routing, 2 GB upload limit, WS upgrade, TLS configured | `~/dive-analyser/nginx` | — | — | A | compose | ssl/ | YES | PROVEN |
| Adminer | DB admin UI | — | — | — | A | compose | — | YES (exposed :8080) | PROVEN |
| v2-candidate stack | old candidate builds | docker images v2-candidate | — | — | A | compose-era images | — | running, purpose UNKNOWN | STRONGLY INFERRED (orphan experiments) |
| import JSON pipeline | bulk import from `reports/*.json` at startup | `import_service.py` | Py | lifespan hook | A | on backend start | — | yes (AUTO_IMPORT=true) | PROVEN (code); data source UNKNOWN |
| Server-side Photos access | legacy LEGACY_MODE paths (`/photos_library`, `PHOTOS_LIBRARY_PATH`) | compose + config.py | Py | — | A | — | empty dir on Linux | DEAD on Linux | PROVEN (empty dir `/Users/mcauchy/...` root-owned) |

## 8. Mac Photos ingestion (deep inspection)

**Change detection**: polling, not FSEvents. Every `sync.interval_seconds=600` the
extractor re-opens `osxphotos.PhotosDB(library_path)` **fresh** each scan — the code
comments explain that reusing the handle hides newly-captioned videos (PROVEN:
`photos_reader.py::_refresh_database`). Health probes use a bounded read-only
SQLite query `SELECT count(*) FROM ZASSET WHERE ZKIND = 1` with 2 s timeout
(PROVEN: `main.py::_probe_photos_database`) → coupling to the undocumented
Photos `ZASSET` schema is real but shallow.

**Photos access**: via `osxphotos==0.76.1` (pinned) reading `Photos.sqlite`
read-only. iCloud download is *forbidden* (`allow_icloud_download: false`).
Optional PhotoKit single-asset materialization (`materialization_use_photokit: true`).

**Clip identification**: a movie is eligible if it has a **description (caption)**
(`photos_reader.py: db.photos(images=False, movies=True)` filtered on
`photo.description`). No caption → ignored. The user pre-trims clips manually in
Photos before captioning (packet context; consistent with parser).

**Metadata encoding — the caption grammar** (PROVEN: `src/metadata.py`, 396 LOC):
space-separated tokens, order-flexible after the first:

```
caption   := dive_code [perf] [height] [SYNC|SYNCHRO] [SMACK|BELLY] [drill] [PersonName]
dive_code := \d{3,4}[A-D]            ("201BO" → normalized to "201B")
perf      := [F B M G P 0-4] | p1/p2 (two-phase: "G/P" or "3/4"; F=B M G P ↔ 0..4)
height    := (1|3|5|7|10) m [p]      ("5mp" = 5 m platform); default "1m" if absent
drill     := SD | DB | HU            (standing dive, double-bounce, hurdle — stored as dive_modifiers)
person    := ^[A-Z][A-Za-z'-]{1,19}$ (capitalized name)
```

Single-token captions parse as `video_labels` (person / drill labels), never fake
dives. Failure mode: unparseable caption → `None` → clip silently not synced
(exists only in Photos; logged at most as count).

**State tracking on Mac** (PROVEN: `extractor.py`):
- `~/.diveanalyzer/sync_state.json` — atomic-write set of synced UUIDs (legacy
  `checkpoint.json` fallback; if absent, dedupe relies on server 409s — explicit
  design comment).
- `~/.diveanalyzer/queue.json` — pending queue, atomic writes.
- Media jobs: **server-driven leases** (`media_jobs` table: status queued →
  claimed/exporting/transcoding/uploading/verifying → done; `claimed_until`
  lease + 45 s heartbeats; max_attempts 5; partial-unique `uq_active_media_job`).
- Source vault on B: `incoming/` (1198 entries), `checksums/`, `manifests/`,
  `quarantine/`, `recalled_sources/`, per-class quotas (permanent 8 GiB,
  recent 8 GiB, temporary 3 GiB, 30-day recent retention) with pause/stop
  thresholds for internal-disk free space (PROVEN: config.yaml).

Durable and idempotent at the metadata level; original-material retention on the
Mac is governed by quotas that can **delete recalled sources** after retention —
the server marks `recalled_media_sources` accordingly (STRONGLY INFERRED from
`media_recall.py` + retention docs).

## 9. Mac→server communication

- Protocol: **plain HTTP** to `http://192.168.1.57:6090` (nginx) — no TLS in the
  agent config (TLS port 6443 exists but unused by agent). LAN-only; no VPN/Tailscale
  dependency found (PROVEN: config; caddy on :24443 belongs to other projects).
- Auth: `X-API-Key` header; key stored in `config.yaml` (mode 0600). **Server-side
  verification is a stub** (§19, R-01).
- Endpoints used by agent (PROVEN, `sync_client.py`):
  `POST /api/v1/videos/sync` (JSON metadata; 201/409), `POST /api/v1/videos/label`,
  `POST /api/v1/videos/batch`, media jobs `lease|heartbeat|fail|upload|finalize`,
  `POST /api/v1/media/agents/heartbeat`, `.../agents/sources/report`,
  `POST /api/v1/media/catalog/runs/lease|{id}/chunks|complete|fail`,
  `upload_media_artifact` via curl multipart.
- Retry model: max 3 retries with backoff for 5xx/timeout; **400/401/403/409 are
  terminal** (409 counted as duplicate — dedup signal, PROVEN `sync_client.py`).
- Timeouts: 30 s (`timeout_seconds`); catalog chunks and media uploads use curl
  subprocess with per-call timeouts.
- Payload: metadata JSON; media artifacts multipart with sha256 checksum +
  size, verified at finalize (PROVEN: media_jobs columns `output_checksum_sha256`).
- Hardcoded values: server IP in config (config file, acceptable), media keys
  `media_keys.py` (17 LOC).

## 10. End-to-end dive lifecycle (observed)

```text
[User on Mac B] trim clip in Photos → write caption (grammar §8)
   ↓ (600 s poll)
agent: fresh PhotosDB scan → captioned movies
   ↓ local filter: sync_state.json
   ↓ parse_dive_caption → DiveMetadata | VideoLabel | None
   ↓ queue.json (atomic)
POST /api/v1/videos/sync  {dive_code, height, performance|phase1/2,
                           is_sync, is_smack, person_name, modifiers[],
                           video_uuid, filename, datetime, raw_caption…}
   ↓ server (videos.py): _get_or_create_session (by date) → _upsert_photos_asset
      → _upsert_synced_dive (video_uuid UNIQUE; re-sync = 409 → counted dup)
      → _replace_dive_modifiers → journey/milestone hooks → optional media jobs
   ↓ (30 s media loop; only if jobs queued / NEW_VIDEO_AUTO_MEDIA_ENABLED)
lease job → resolve asset (vault → Photos local → PhotoKit materialize; never iCloud)
   ↓ ffmpeg → poster.jpg / proxy_360p.mp4 / proxy_720p.mp4 (media_tmp)
   ↓ multipart upload → finalize (checksum, size) → media_cache_entries + media/cache
   ↓ source cleanup per retention class
[UI] dive detail → GET /api/v1/videos/{uuid}
   → if dive.video_path & file exists in /videos|/photos_library → FileResponse (82 legacy)
   → elif proxy_360p cached → 307 to cached playback (most new dives)
   → elif poster cached → 202 {poster_url, can_request} → queues job on Mac
   → else 404
```

- Idempotence: metadata sync idempotent (UNIQUE + 409); media jobs idempotent per
  (media_key, active-status) partial unique index.
- Orphaning: caption edit after sync is **not re-synced** (UUID already in state)
  unless state is reset — caption fixes require manual intervention (STRONGLY INFERRED;
  no update path found in extractor). UNKNOWN: whether a re-caption flow exists elsewhere.
- Transactionality: dive+asset+modifiers inserted in one request; journey hooks run
  in-request; media upload/finalize is two-phase with checksum.

## 11. Data model (live DB, PROVEN via psql — 44 tables)

Core: `sessions` (date UNIQUE, denormalized stats kept fresh by plpgsql trigger
`trigger_update_session_stats`), `dives` (FK session CASCADE; performance F/B/M/G/P +
numeric; phase1/phase2 since Jan 2026; height, platform_type, is_lineup/is_sync/
is_smack; raw_caption; person_name; video_uuid UNIQUE; dive_datetime; synced_at),
`photos_assets` (1:1 with dives by UUID, 2,803 rows), `dive_modifiers` (SD/DB/HU),
`video_labels`, `divers` + `diver_aliases` + `training_periods`,
`captioned_media_catalog` (2,920), `media_agents` (2), `media_jobs` (4,357),
`media_cache_entries` (1,691), `media_catalog_runs/population_runs/
resolution_upgrade_runs` (+ items), `recalled_media_sources`,
`representative_media_selections`, `journeys` + `journey_milestones`,
`emotional_states`, `execution_faults`, FINA set (`fina_dive_codes`,
`fina_scoring_rules`, `dd_lookups`, `dd_component_reference`),
competition set (events/heats/rounds/entries/scores/competitors, `judge_panels`,
`judge_scores`), `analytics_cache`, `visualization_presets`, `jobs`, `audit_log`,
`migration_logs`, `recovery_plans`.

Migrations: 21 hand-rolled SQL files in `backend/migrations/` applied by
docker-entrypoint init + manual runs; Alembic is a dependency but
`app/migrations/versions/` exists alongside — **two migration mechanisms** (PROVEN).
Derived vs authored: session aggregates = derived (trigger); DD = derived w/
official provenance; performance letters = user-authored; faults = API-supplied.

## 12. Media storage

- Server canonical rendition cache: `~/dive-analyser/media/cache` → `media_cache_entries`
  (poster 796 / 115 MB; proxy_360p 239 / 60 MB; proxy_720p 656 / 665 MB). 50 GB cap
  configured (`MEDIA_CACHE_MAX_BYTES`), eviction in `media_cache.py` (STRONGLY INFERRED).
- Legacy originals: `media/videos` 14 GB — IMG_*.MOV, 82 real (all dated Jun 9 2026,
  largest 7,294,485,222 B), 94 zero-byte placeholders (same date) — served by
  `/videos` mount; **not covered by any GC** (PROVEN).
- Originals for new dives: Mac only (Photos + source vault by UUID, quota-managed,
  retention classes permanent/recent/temporary/diagnostic).
- Streaming path fallback order includes `/tmp/dive_downloads/{uuid}/*` (legacy).
- Mac machine-specific absolute paths everywhere in agent config (by design, single node).

## 13. Current analysis layer (classified)

**A. User-authored**: caption fields (code, perf, phases, height, modifiers, person,
SYNC/SMACK); notes; emotional states; judge/competition scores; representative-media
choices; `ExecutionMetrics` supplied to fault detector via `POST /api/v1/execution*`.

**B. Deterministic**: DD calculation + lookups + auto-assign with provenance flags
(`world_aquatics_dd.py`, `add_official_dd_provenance.sql`); performance normalization;
session aggregates (SQL trigger); personal dive value V1 (`personal_dive_value.py`,
"deterministic, personal-only"); FINA scoring math (`performance_scorer`,
`results_aggregator`); analytics cache with TTL; `dive_analysis_service`
(filtered, attempt-traceable per dive code).

**C. Heuristic over DB (no pixels)**: `fear_analyzer` (avoidance/plateau detection
from attempt history + emotional states); `milestones` (831 LOC milestone detection);
`journey_service` (post-sync narrative updates); `execution_fault_detector` (10 fault
codes UR/OR/LE/EE/LS/LH/PH/SA/LK/SK with severity weights — runs on **manually
supplied** metrics); `representative_media` (selection of best poster/proxy per dive
code); `media_resolution_upgrade` runs.

**D. Learned/ML**: **none**. `execution_analyzer.py` returns constants (7.5/8.0/7.0)
and is still exposed via API; no CV/pose/embedding code exists anywhere in the repo
(PROVEN: full service inventory + imports).

Executed automatically: session triggers, journey/milestone hooks on sync, analytics
cache fill, DD auto-assign, media job scheduling. None touch video pixels server-side.

## 14. Statistics

Mixed model: SQL aggregates + trigger-maintained session stats; `analytics_cache`
JSONB with TTL (computed in backend on demand); frontend charts (recharts) over API;
no batch jobs, no materialized views (they exist commented-out in init.sql —
disabled after ROUND() compatibility issues, PROVEN). Surfaced metrics: per-session
totals/avg/success-rate; per-direction, per-height, per-code performance; DD
progression; personal dive value; fear/avoidance; milestones/journey; FINA scores.
Metric formulas live **scattered** across services + SQL + frontend (no metric layer).

## 15. Dependencies

Backend (`backend/requirements.txt`, pinned): fastapi 0.104.1, uvicorn[standard],
sqlalchemy 2.0.23, psycopg2-binary, alembic 1.12.1, pydantic v2, numpy/pandas,
plotly/matplotlib/seaborn, requests, aiofiles, pytest/httpx (dev, same file — no split).
No lockfile (pip only). plotly/matplotlib/seaborn: no server-side usage found
(STRONGLY INFERRED unused — plotting lives in frontend/recharts).

Mac agent (`pyproject`): osxphotos 0.76.1 (pinned), pyyaml 6.0.1, httpx ≥0.27,
python-dateutil 2.8.2; vendored ffmpeg/ffprobe binaries; system `curl` used for
multipart upload (PROVEN: `_curl_post` shells out to curl).

Frontend: react 18, react-router 6, recharts 2, zustand 4, axios, date-fns,
lucide-react, tailwind 3, vite 5, typescript 5, vitest, playwright, testing-library.
Lockfile: package-lock present in sibling project only — `frontend/package-lock.json`
presence UNKNOWN (node_modules committed to tree, 208 MB).

Infra: postgres:16-alpine, nginx:alpine, adminer, docker compose v2.

## 16. Build / run / deploy model

Reproduction is **partially possible**: `docker compose up -d` on the server builds
backend (bind-mounted source), pulls frontend image (prebuilt — Dockerfile for
frontend not found in compose; build context UNKNOWN), initializes Postgres from
`migrations/init.sql` **only on first boot** (the other 20 migration SQL files must
be applied by hand — undocumented order). Mac agent install: `install.sh` in agent
code + launchd plist + "DiveSensei Python Runtime.app" wrapper (purpose: keep Aqua
session). Docs are extensive but scattered: `docs/` (15 curated files) vs ~90 root
`*.md` status reports that contradict each other; `AGENTS.md` present.
Discrepancies: docs say keep `NEW_VIDEO_AUTO_MEDIA_ENABLED=false` until verified —
`.env` now has it `true` (PROVEN drift). A clean-machine rebuild would hit: dead
macOS bind mount, prebuilt frontend image, manual migrations, missing agent
source sync from Machine B.

## 17. Testing

Backend: `backend/tests/` — 30+ pytest files incl. e2e sync-to-UI, mac-agent
integration, media node, FINA sprints 1–8, load/concurrent, recovery plans;
fixtures + mock_server. Frontend: vitest component tests (DiveVideoPlayer,
PersonalDiveValuePanel, DiveAnalysis, Dives, MediaRecall, RepresentativeMedia) +
Playwright e2e (reports + test-results committed). Agent: `tests/` on Machine B +
`.pytest_cache` present (tests were run at some point). No CI found (`.github/`
only in sibling divesensei-app). Tests requiring real Photos library/server: the
agent integration test uses a mock server (STRONGLY INFERRED from mock_server.py).
None executed in this task.

## 18. Observability / failure recovery

- Backend: stdout logging (compose logs), slow-request/slow-query middleware,
  `audit_log` + `migration_logs` tables, `operations_status.py`, `sync_status`
  WS broadcast, health endpoints (`/health`, `mac/status`).
- Agent: rotating logs `/Users/Shared/services/logs/diveanalyzer/{application,agent.error}.log`
  (~11 MB each), launchd KeepAlive, crash_recovery + error_recovery modules,
  heartbeat with photos-access status + vault free-space to server, storage
  thresholds pause processing, failed_diagnostics/ quarantine dirs.
- Server-down 24 h: metadata queue persists in `queue.json` with retries; media
  jobs simply remain queued (leases expire via `claimed_until`) → no data loss
  expected (STRONGLY INFERRED).
- Same clip twice: local state prevents; if state lost → 409 terminal, counted
  as duplicate (PROVEN).
- Transfer ok / metadata fail or vice versa: media upload is separate from
  metadata sync; a rendition can exist for an asset only if `photos_assets` row
  exists (FK) — orphan renditions impossible by FK; metadata-without-rendition
  is the normal steady state (PROVEN schema).
- No alerting; monitoring = node-exporter/prometheus on the host (other projects'
  scope; not dive-specific).

## 19. Security / privacy boundaries

- `verify_api_key` (`app/security.py`): **stub** — accepts any non-empty key ≥ 10
  chars, TODO comments admit no DB check (PROVEN). Which routers depend on it:
  sync/media routers; most analytics routers appear **unauthenticated** (STRONGLY INFERRED).
- CORS `allow_origins=["*"]` with `allow_credentials=True` (PROVEN).
- Transport: HTTP LAN; API key cleartext; TLS key material exists in `nginx/ssl/`.
- Postgres :5433 exposed on LAN with a weak password stored in `.env`
  (referenced only by name: `POSTGRES_PASSWORD`); Adminer :8080 LAN-exposed.
- Compose `.env` lives in repo dir but the repo has no remote; local-only leak risk.
- Videos can only leave local infra if Photos does iCloud sync (user-level
  setting, UNKNOWN). Client secrets for unrelated Google projects sit in home
  dir (out of scope, flagged).

## 20. Source-of-truth matrix

| Concept | Authority | Competing/notes |
|---|---|---|
| Original video (new dives) | Mac Photos + source vault | server 0-byte stubs; 82 legacy originals only on server |
| Original video (legacy dives) | server `media/videos` (Jun 9 2026) | nothing on Mac side guarantees these |
| Dive metadata | Postgres `dives` | caption in Photos is origin; edits don't propagate |
| Performance (1 vs 2-phase) | `dives.performance` vs `phase1/phase2` | both live; dual legacy path |
| Caption text | `dives.raw_caption` + Photos | duplicate |
| Sync state | Mac `sync_state.json` + server `synced_at`/409 | reconcilable, but Mac file is fragile |
| Processing state (media) | `media_jobs` (server) | leases trusted over Mac claims |
| DD | `dd_lookups` + provenance cols | computed vs official |
| Statistics | trigger-maintained columns vs on-demand aggregates | two paths, can drift |
| Athlete identity | `person_name` string + `divers`/aliases | weak FK (string match) |

## 21. Technical-debt findings (ranked)

| ID | Severity | Finding | Evidence |
|---|---|---|---|
| R-01 | CRITICAL | Auth stub: any ≥10-char X-API-Key accepted; most API unauthenticated, LAN-wide exposure incl. Adminer | `app/security.py` |
| R-02 | HIGH | Plain-HTTP transport for media + keys; CORS `*`+credentials | agent config, `main.py` |
| R-03 | HIGH | Dead macOS bind mount in compose on Linux; legacy stream paths depend on `/photos_library` (403/404 at runtime for legacy dives without local file) | docker-compose.yml, `videos.py:604+` |
| R-04 | HIGH | mac-agent source drift: server repo copy missing ~11 deployed modules | diff of file lists |
| R-05 | MEDIUM | Analysis facade: stub `execution_analyzer` + fault detector w/o metric producer | services |
| R-06 | MEDIUM | 94 zero-byte video stubs + 82 legacy originals with no GC/lifecycle | `media/videos` listing |
| R-07 | MEDIUM | Caption edits after sync never re-synced (state file) | extractor design |
| R-08 | MEDIUM | Two migration systems (SQL files vs Alembic); init.sql only on first boot | migrations/ |
| R-09 | LOW | 90+ contradictory root-level status docs; doc drift (NEW_VIDEO_AUTO_MEDIA flag) | tree, `.env` vs docs |
| R-10 | LOW | requirements without lockfiles; plotting deps unused; node_modules/playwright artifacts in tree | manifests |
| R-11 | LOW | Candidate container graveyard (v2-candidate ×3, up 8 wks) | docker ps |
| R-12 | LOW | Secrets adjacent: `.env` with real password in project dir; API key in agent config (0600, fine) | `.env` |

## 22. Analysis-Layer-2 readiness

Supports: clean separation of Mac (bytes) and server (metadata); stable per-asset
UUID keying; `media_jobs` pattern (lease/heartbeat/finalize + attempts) is a ready
template for analysis jobs; `analytics_cache` + JSONB for derived results;
`captioned_media_catalog` for asset inventory; checksum discipline; rendition
versioning keys (`MEDIA_TRANSFORM_VERSION=ffmpeg-h264-v1`) show a versioning idiom;
docs/ contains ops runbooks; 1,691 cached renditions = decent proxy corpus for CV.

Blocks/missing: no per-frame artifact store; no job result versioning/model version
columns; analysis results today are heuristics over manual metrics (tables like
`execution_faults` exist but lack provenance); streaming from Mac proxies means
server-side CV would need recall of originals (source vault design anticipates
`recalled_media_sources` — actually a good seam); no GPU on server (host has
none evidenced); single-worker media concurrency (`max_jobs: 1`) would serialize
heavy analysis; no queue system besides `media_jobs` table.

## 23. Risk register

| ID | Subsystem | Finding | Severity | Likelihood | Consequence | Before Layer-2? |
|---|---|---|---|---|---|---|
| R-01 | API auth | stub verification | CRITICAL | certain (LAN) | any LAN device can read/mutate/delete dive data | Yes — fix before exposing analysis APIs |
| R-02 | transport | HTTP + CORS * | HIGH | medium | key/metadata interception | No (LAN), but yes if ever exposed |
| R-03 | storage | dead mount / legacy paths | HIGH | medium | legacy dives unplayable; confusing failures | Yes — clarify media authority |
| R-04 | agent | source drift | HIGH | high | unreproducible agent, bad patches | Yes |
| R-06 | media | stub/legacy files unmaintained | MEDIUM | medium | silent broken playback | Yes |
| R-07 | ingestion | caption edit gap | MEDIUM | medium | metadata permanently stale | Yes |
| R-08 | DB | dual migrations | MEDIUM | medium | unreproducible DB | Yes |
| R-05 | analysis | stub facade | MEDIUM | n/a | misleading UX | Yes |
| R-09–R-12 | hygiene | docs/deps/containers/secrets-adjacent | LOW | — | friction | No |

## 24. Unknowns

- Frontend image build provenance (`dive-analyser-frontend:latest` — Dockerfile location UNKNOWN).
- Who authored competition/judge data (import JSON in `reports/` — origin UNKNOWN).
- `media_population_runs` / catalog Stage-2 completion state (docs describe gates; current run state not queried).
- Whether any external exposure exists beyond LAN (duckdns/caddy present on host for other projects; not tied to dive stack — UNKNOWN).
- iCloud sync settings of the Photos library (privacy boundary UNKNOWN).
- v2-candidate container purpose/retirement.

## 25. Recommended supervisor decisions (options, not decisions)

1. Authentication: implement real key store vs network-level isolation first?
2. TLS for Mac→server (nginx 6443 already configured) — enable now or fold into redesign?
3. Media authority: retire server legacy originals (or migrate into vault model)?
4. Agent source of truth: relocate canonical agent code into server repo (or new repo) and re-sync from Machine B?
5. Migration strategy: consolidate on Alembic vs curated SQL?
6. Remove stub execution endpoints before Layer-2 work to avoid false confidence?
7. Caption-edit reconciliation flow: full resync command vs server-side diff?
8. Decide target for analysis job execution: server CPU on proxies vs Mac recall of originals?
9. Container graveyard + doc sprawl cleanup as first supervised chore?
10. Define metric-definition layer before Layer-2 so heuristics and future CV share one contract?

## 26. Evidence appendix

Key commands executed (all read-only):
- local: `ls`, `find`, `du`, `diff` (5 files byte-identical to server copies)
- Machine A: `git log/branch/remote/status`; `docker ps`; `docker inspect` (candidate image);
  `psql -c '\dt'`, counts (`dives 2803, sessions 168, photos_assets 2803,
  captioned_media_catalog 2920, media_agents 2, media_jobs 4357, divers 23,
  video_labels 260`), `media_cache_entries` by rendition, `\d media_jobs`;
  `cat docker-compose.yml .env nginx/*.conf backend/requirements.txt
  backend/app/{main,config,security}.py backend/app/api/v1/{videos,media,ws_sync}.py
  backend/app/services/{execution_analyzer,execution_fault_detector,fear_analyzer,import_service}.py
  backend/migrations/init.sql`; `docs/` listing; `media/videos` file-size census.
- Machine B: `ps aux`, launchd plist, `state/config.yaml` (secret redacted),
  deployed `src/` listing + selected files (`metadata.py` full, `photos_reader.py`,
  `main.py`, `sync_client.py` endpoints, `transcoder.py`, `media_jobs.py`,
  `media_exporter.py`, `extractor.py` state handling, `queue.py`),
  media-node directory listing.

No writes were performed on either machine. Local writes: this report and
`docs/PROJECT_STATE.md` only.

---

## RESOLUTION ADDENDUM — 2026-09-05 (source-authority reconciliation)

Historical statements above were written before reconciliation and are preserved as
evidence. Updated findings:

- **R-04 (mac-agent source drift) is RESOLVED.** The deployed agent source at
  `/Users/Shared/services/data/diveanalyzer/code` (Machine B) was canonicalized into the
  server repo `mac-agent/` (96 files, byte-parity md5-verified for all 37 source/config
  files). Exclusions and rationale:
  `docs/audits/SOURCE_AUTHORITY_RECONCILIATION_2026-09-05.md`.
- The line "mac-agent/ STALE copy of agent source (10 src modules)" no longer holds:
  the repo copy now mirrors the deployed tree (20 src modules, tests, build/deploy
  files, docs). Deployed `code/` is now a mirror of repo `mac-agent/` plus runtime-only
  items (state/config.yaml, bin/ binaries, venv, caches).
- Machine identity note: SSH access is now key-based from Maxime's MacBook Air only
  (aliases `diveanalyzer-server` / `diveanalyzer-mac`).
- All other risks listed above remain open and were intentionally not addressed.
