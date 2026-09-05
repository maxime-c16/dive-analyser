# PROJECT_STATE.md — Dive Analyser / DiveSensei

> Durable project handoff. Last verified: **2026-09-05** (canonical runtime source baseline, P0.5).
> Latest audit: `docs/audits/CANONICAL_RUNTIME_SOURCE_BASELINE_2026-09-05.md`
> Previous: `docs/audits/SOURCE_AUTHORITY_RECONCILIATION_2026-09-05.md`, `docs/audits/REPOSITORY_CARTOGRAPHY_2026-09-05.md`
> Supervisor gate: **`SUPERVISOR_REVIEW_AFTER_CANONICAL_RUNTIME_SOURCE_BASELINE`**
>
> **WARNING: Repository history currently contains historical live credential
> material. Do not create or push a remote until P0.6 secret rotation and history
> sanitization are complete.**

## Canonical repository

- **`mcauchy@192.168.1.57:~/dive-analyser`** (Debian 12, host `deb-serv`) — the ONLY
  canonical Git repository. Branch `uiux-overhaul-pro-app`. No remotes.
- HEAD: **`178c68e`** (2026-09-05, "Canonical baseline of server application source
  currently running (P0.5)"). History: `7ae8b01` (Feb-2026 squashed restructure) →
  Mac-agent source-authority commits (`a243fad`, `ee68f34`, `20fafa0`, `a155019`) →
  `178c68e` (server app source baseline).
- **Working tree is CLEAN** (`git status --short` empty; 19k+ paths intentionally
  ignored via `.gitignore`). Pre-existing staged state was fully classified and
  reconciled — see the P0.5 audit; the raw pre-reconciliation status is archived in
  `docs/audits/evidence-2026-09-05-preflight/`.
- Local Mac working copy `~/.perso/diveanalyzer` is **NOT a git repo** — only a
  partial reference slice; never treat it as canonical.
- SSH (passwordless from Maxime's MacBook Air): aliases `diveanalyzer-server`
  (= `mcauchy@192.168.1.57`), `diveanalyzer-mac` (= `divesensei@192.168.1.19`).

## Exact canonical HEAD

`178c68e` — verify with `git rev-parse HEAD` on the server; if it has moved, read
`git log` and the latest audit before trusting this file.

## Mac-agent authority

- Git: `mac-agent/` (byte-identical to deployed; 37 source/config files md5-verified
  in the 2026-09-05 reconciliation). Runtime: `/Users/Shared/services/data/diveanalyzer/`
  on Machine B (`code/`, `state/config.yaml` secrets, `bin/` vendored ffmpeg, `venv/`).
- Parity: **PASS** (unchanged by P0.5). Known stale test: `tests/test_sync_client.py`
  (15 failures, pre-rewrite API; 54 other tests pass).
- Do NOT reopen reconciliation or deploy to the Mac without new contradictory evidence.

## Backend authority

- Git: `backend/` @ `178c68e` — PASS. The backend container bind-mounts
  `./backend:/app`, so the committed working tree **is** the running code
  (FastAPI, 18 routers, 60+ services, 22 SQL migrations, tests, Dockerfile).
- Verified: all 154 Python files parse (0 syntax errors); removed-before-this-task
  DD-component files are recorded as deletions and are absent from the router registry.

## Frontend authority

- Git: `frontend/` @ `178c68e` — PASS. Deployed artifact: baked image
  `dive-analyser-frontend:latest` (`0d5288564a3c`, built 2026-08-12 via
  `frontend/Dockerfile.deploy`).
- **Deployed-build parity PROVEN**: rebuilding from the committed tree reproduces the
  served bundle byte-for-byte (`index-w_MhTRQ8.js`, `index-CzED_XRX.css`,
  `index.html` md5-identical; sourcemap differs only by embedded paths).

## Infra authority

- Git: `docker-compose.yml`, `nginx/nginx.conf`, `nginx/conf.d/default.conf`
  (bind-mounted into the nginx container = running config), backend/frontend
  Dockerfiles, `frontend/nginx.conf`, `ops/icloud-video-sync.sh` +
  `icloud-video-cache-prune.sh` + env template. PASS.
- Known debt: compose defaults differ from live DB names (harmless while `.env`
  supplies values); dead macOS Photos bind mount; `frontend/Dockerfile` is a
  dev-server variant superseded by `Dockerfile.deploy`.

## Runtime configuration authority

- Server: `/home/mcauchy/dive-analyser/.env` (POSTGRES_*; contains the live DB
  password) and `ops/icloud-video-sync.env`. **Not in Git** (`.env` untracked +
  ignored in P0.5; runtime file preserved untouched). Template: `backend/.env.example`
  (sanitized) and `ops/icloud-video-sync.env.example`.
- Mac agent: `state/config.yaml` on Machine B (0600). Template: `mac-agent/config.example.yaml`.
- `nginx/ssl/` TLS material: host-only, ignored.

## Production data authority

| Concern | Location | In Git? |
|---|---|---|
| Metadata (2803 dives / 168 sessions) | Postgres 16 volume on Machine A | never |
| Media originals (legacy, 82 real + 94 zero-byte stubs) | `~/dive-analyser/media/videos` on A | never (ignored) |
| Rendition cache (~840 MB) | `~/dive-analyser/media/cache` on A | never (ignored) |
| Originals (new dives) + source vault | Mac B Photos + `/Users/Shared/services/data/media-node/` | never |
| DB dumps / backups | `~/dive-analyser/backups/`, `divesensei-pre-media-rollout.dump` | never (ignored; archival relocation is a future chore) |
| Import data | `~/dive-analyser/reports/` (bind-mounted, AUTO_IMPORT) | never (ignored) |

## Current analysis capabilities

Unchanged (see cartography audit for depth):
- A. User-authored: caption grammar → structured dive metadata; notes; emotional states; judge scores.
- B. Deterministic: DD engine + provenance, session aggregates (SQL trigger), personal dive value V1, FINA scoring.
- C. Heuristic (no pixels): fear/plateau, milestones, journey, execution fault detector over supplied metrics.
- D. ML/CV: none. `execution_analyzer.py` remains a stub. Analysis Layer 2 intentionally not introduced.

## Known security debt

1. **Live DB credential persists in Git history** (and in three on-disk session-report
   MDs, `backend/migrations/00_init_user_and_db.sql.bak`, and the Mac's
   `docs/archive/DEPLOYMENT_READY.md`). Current HEAD tree is clean; rotation +
   history scrub = **P0.6**. No remote until then.
2. API-key auth is a stub (any header ≥ 10 chars accepted); LAN-exposed API effectively unauthenticated.
3. Plain HTTP Mac→server; CORS `allow_origins=["*"]`.
4. Postgres :5433 and Adminer :8080 LAN-exposed.
5. Weak/legacy password defaults remain visible in old compose versions in history.

## Most recent audit/report

- `docs/audits/CANONICAL_RUNTIME_SOURCE_BASELINE_2026-09-05.md` (canonical, P0.5).
- `docs/audits/evidence-2026-09-05-preflight/` (raw pre-reconciliation git status).
- `docs/audits/SOURCE_AUTHORITY_RECONCILIATION_2026-09-05.md`, `docs/audits/REPOSITORY_CARTOGRAPHY_2026-09-05.md` (previous).

## Current supervisor gate

`SUPERVISOR_REVIEW_AFTER_CANONICAL_RUNTIME_SOURCE_BASELINE`
