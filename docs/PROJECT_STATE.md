# PROJECT_STATE.md — Dive Analyser / DiveSensei

> Durable project handoff. Last verified: **2026-09-05** (source-authority reconciliation).
> Latest audit: `docs/audits/SOURCE_AUTHORITY_RECONCILIATION_2026-09-05.md`
> Previous: `docs/audits/REPOSITORY_CARTOGRAPHY_2026-09-05.md`
> Supervisor gate: **`SUPERVISOR_REVIEW_AFTER_SOURCE_AUTHORITY_RECONCILIATION`**

## Project purpose

Personal diving-analysis platform for a single athlete (Maxime) and training partners.
Divers manually pre-trim clips in macOS Photos and caption them with a compact grammar
(dive code, performance, height, modifiers). The system ingests those clips + captions,
stores structured metadata, computes statistics/insights, and serves a web UI.
Long-term goal: a second, deeper analysis layer (phase timing, takeoff/entry
characteristics, athlete-vs-self comparison). **Not implemented yet — direction only.**

## Canonical repository

- **`mcauchy@192.168.1.57:~/dive-analyser`** (Debian 12, host `deb-serv`) — the ONLY
  canonical Git repository. Branch `uiux-overhaul-pro-app`. As of 2026-09-05 a single
  squashed commit `7ae8b0186d21bd040c0af2caf675cd6080e365a3` (2026-02-03) plus a
  source-authority reconciliation commit (see `git log`, 2026-09-05). No remotes.
- Local Mac working copy `~/.perso/diveanalyzer` is **NOT a git repo** — only a partial
  reference slice; never treat it as canonical.
- The working tree carries a large amount of **pre-existing uncommitted work** (staged
  backend/frontend changes from the media-rollout era, doc sprawl, `._*` AppleDouble
  files tracked in HEAD, a DB dump `divesensei-pre-media-rollout.dump`, `backups/`,
  `media/`). Do not sweep these into unrelated commits; use path-limited commits.
- SSH access (passwordless from Maxime's MacBook Air only): key `~/.ssh/qwokka`
  installed in both hosts' `authorized_keys`; aliases in `~/.ssh/config`:
  `ssh diveanalyzer-server` (= `mcauchy@192.168.1.57`),
  `ssh diveanalyzer-mac` (= `divesensei@192.168.1.19`).

## Current deployment topology

Two machines on a LAN:

| Machine | Host | Role |
|---|---|---|
| Machine A | Debian 12 server `deb-serv` @ `192.168.1.57` (user `mcauchy`) | App host: Postgres 16, FastAPI backend, React frontend (nginx), reverse proxy (6090/6443), adminer. Canonical repo at `~/dive-analyser`. |
| Machine B | Intel MacBook, macOS 15.1.1, `mac-server.home` @ `192.168.1.19` (user `divesensei`) | Ingestion + media edge: watches the Photos library, parses captions, syncs metadata, exports/transcodes/uploads posters & proxies, manages a source vault for originals. |

Verified counts (2026-09-05, read-only): 2803 dives, 168 sessions, 2803 photos_assets,
4357 media_jobs. Rendition cache ≈ 840 MB.

## Canonical source authorities

| Concern | Authoritative source | Runtime copy/state | Reproducible from Git? | Drift status |
|---|---|---|---|---|
| Backend | server repo `backend/` (**uncommitted working tree** — see risks) | bind-mounted `./backend:/app` in backend container | partially (HEAD is stale; working tree not committed) | UNCOMMITTED — supervisor decision needed |
| Frontend | server repo `frontend/src` (same caveat as backend) | built into `dive-analyser-frontend:latest` image | partially | UNCOMMITTED — supervisor decision needed |
| Mac agent | server repo `mac-agent/` — **reconciled 2026-09-05, byte-identical to deployed** (37 files verified via md5) | `/Users/Shared/services/data/diveanalyzer/code` on Machine B | YES | RESOLVED (byte parity for all source/config; exceptions documented in audit) |
| DB schema | `backend/migrations/*.sql` (init.sql + additive .sql files) | live Postgres 16 `diving_analyzer_db` (44 tables) | partially (migration ordering/consolidation unresolved) | known issue, do-not-touch |
| Runtime config (server) | `.env` + `docker-compose.yml` on Machine A | live containers | NO (contains secrets) | out of Git by design |
| Runtime config (Mac agent) | `state/config.yaml` on Machine B | read by agent at startup | NO — template only: `mac-agent/config.example.yaml` | template committed, values never |
| Media originals (new dives) | Mac source vault `/Users/Shared/services/data/media-node/` on B | data | never | DATA — excluded |
| Media originals (legacy) | `~/dive-analyser/media/videos` on A (82 real + 94 zero-byte stubs) | data | never | DATA — excluded |
| Derived renditions | `~/dive-analyser/media/cache` on A (~840 MB) | data, regenerable | never | DATA — excluded |
| Metadata | PostgreSQL DB | data | never | DATA — excluded |

## Mac-agent deployment relationship

- Canonical source: `mac-agent/` in the server repo (20 modules in `src/`, 6 test files,
  `config.example.yaml`, `pyproject.toml`, `requirements.txt`, install/upgrade scripts,
  `deploy/com.diveanalyzer.agent.mac-media-01.plist`, full `docs/` incl. archive).
- Deployed runtime: `/Users/Shared/services/data/diveanalyzer/` on Machine B:
  - `code/` — the deployed source tree (mirrored byte-exact into repo `mac-agent/`);
  - `state/config.yaml` — runtime config (secrets; NOT in Git; template = `config.example.yaml`);
  - `bin/` — vendored ffmpeg 8.1.2-tessus / ffprobe / uv (NOT in Git; versions pinned in `requirements.txt`/docs);
  - `venv/` — Python 3.12.13, osxphotos 0.76.1 (agent installed editable from `code/`).
- Reconciled: YES (2026-09-05). Byte parity verified for all 37 source/config files.
- Intentional exclusions (documented in the reconciliation audit): `docs/archive/DEPLOYMENT_READY.md`
  (contains a hardcoded credential — left on the Mac, kept out of Git), `__pycache__`,
  `.DS_Store`, `._*`, `.pytest_cache`, `*.egg-info`, `logs/`, stray duplicate
  `code/mac-agent/src/photos_reader.py`.
- How future agents must compare them: md5/rsync the deployed `code/` tree (excluding
  runtime junk) against repo `mac-agent/`; the audit lists exact per-file md5s used.

## Current dataflow (summary)

```
Photos library (Mac B, manual trim + caption by user)
  → poll (600 s): osxphotos PhotosDB re-opened fresh each scan
  → local dedupe: ~/.diveanalyzer/sync_state.json
  → parse caption grammar (src/metadata.py)
  → POST /api/v1/videos/sync (JSON metadata only; X-API-Key)
  → media-job loop (30 s): /api/v1/media/jobs/lease → export asset (no iCloud dl)
      → ffmpeg poster/proxy_360p/proxy_720p → multipart upload → finalize (sha256)
  → catalog loop: /api/v1/media/catalog/runs/lease → chunked captioned catalog
  → heartbeat: /api/v1/media/agents/heartbeat ; sources report
  → ORIGINALS NEVER LEAVE THE MAC for new dives (source vault)
```

## Current analysis capabilities

- **A. User-authored**: caption grammar → dive_code, position, height, platform,
  performance letters F/B/M/G/P (single or two-phase), modifiers SD/DB/HU,
  SYNC/SMACK flags, person_name; notes, emotional states, judge scores.
- **B. Deterministic**: DD engine with official provenance, session aggregates via SQL
  triggers, analytics cache, personal dive value V1, FINA scoring rules, results aggregation.
- **C. Heuristic (no video analysis)**: fear/plateau analyzer, milestones, journey
  service, execution fault detector over *supplied* ExecutionMetrics.
- **D. ML/CV: none.** `execution_analyzer.py` is a stub returning hardcoded values.

## Important runtime dependencies

- Backend: fastapi 0.104.1, sqlalchemy 2.0.23, psycopg2, alembic, pydantic v2 (Py 3.11 container).
- Mac agent: Python 3.12.13 venv; osxphotos 0.76.1 (pinned), pyyaml, httpx, python-dateutil;
  ffmpeg/ffprobe 8.1.2 vendored in `bin/`; launchd `com.diveanalyzer.agent`
  (wrapper app "DiveSensei Python Runtime.app" → `venv/bin/python -m src.main --config state/config.yaml`).
- Frontend: react 18, vite 5, vitest + playwright.
- Infra: docker compose (postgres:16-alpine, nginx:alpine, adminer).

## Known risks (top)

1. API-key auth is a stub (any header ≥ 10 chars accepted); LAN-exposed API effectively unauthenticated.
2. Plain HTTP Mac→server (API key in cleartext); CORS `allow_origins=["*"]`.
3. Large uncommitted working tree in the canonical repo (backend/frontend media-rollout
   work + doc sprawl); repo hygiene (AppleDouble `._` files tracked, DB dump present).
4. Stale agent test file: `mac-agent/tests/test_sync_client.py` (15 failures) predates the
   SyncClient rewrite — tests are stale, runtime is not broken (54 other tests pass).
5. State-file fragile sync (Mac dedupe via local JSON; server 409 path exists).
6. Analysis layer heuristic-only; stub `execution_analyzer` still wired into API.
7. Legacy media split-brain (server legacy mount vs Mac vault); zero-byte stubs.
8. `docs/archive/DEPLOYMENT_READY.md` (Mac) contains a hardcoded credential — excluded
   from Git; should be scrubbed on a future maintenance pass.

## Current unresolved questions

- Commit strategy for the pre-existing uncommitted backend/frontend work (needs supervisor).
- Migration-system consolidation; which SQL files are actually authoritative.
- v2-candidate containers' purpose/retirement; legacy `/photos_library` mount cleanup.
- Whether legacy server-side originals are still needed for serving old dives.

## Most recent audit/report

- `docs/audits/SOURCE_AUTHORITY_RECONCILIATION_2026-09-05.md` (canonical, in repo).
- `docs/audits/REPOSITORY_CARTOGRAPHY_2026-09-05.md` (canonical, with resolution addendum).

## Current supervisor gate

`SUPERVISOR_REVIEW_AFTER_SOURCE_AUTHORITY_RECONCILIATION`
