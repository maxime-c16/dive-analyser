# PROJECT_STATE.md - Dive Analyser / DiveSensei

Last verified: 2026-09-05, after foundation hardening and Layer-2 readiness design.
Latest audit: `docs/audits/FOUNDATION_HARDENING_AND_LAYER2_READINESS_2026-09-05.md`.
Layer-2 design: `docs/design/ANALYSIS_LAYER_2_FOUNDATION_PROPOSAL_2026-09-05.md`.
Supervisor gate: `SUPERVISOR_REVIEW_AFTER_FOUNDATION_HARDENING_AND_LAYER2_DESIGN`.

## Canonical Repository

Canonical source is `mcauchy@192.168.1.57:~/dive-analyser` on host `deb-serv`, branch `uiux-overhaul-pro-app`. History was rewritten on 2026-09-05 to remove historical live DB credential material and tracked `.env`. The expected post-rewrite pre-final-commit HEAD was `42e8f82814ccb2a381d0cfd98ae54d10ab97d9f6`; verify current HEAD with `git rev-parse HEAD` because the final hardening commit occurs after this file is edited.

The Mac local workspace `/Users/maximecauchy/.perso/diveanalyzer` is not a Git repository and is not source authority.

## Backup Authority

A sanitized off-host bare mirror exists on the Mac at `/Users/Shared/services/data/diveanalyzer-source-backups/dive-analyser-2026-09-05.git`. It is source-only, outside the deployed Mac-agent tree, mode 0700, and must have HEAD equal to the canonical repository after each final commit.

## Runtime Topology

Debian server `192.168.1.57` runs Docker Compose: PostgreSQL 16, FastAPI backend, React/Vite frontend image, nginx, and Adminer. Mac `192.168.1.19` runs launchd `com.diveanalyzer.agent` from `/Users/Shared/services/data/diveanalyzer/`.

nginx is the LAN entrypoint: `http://192.168.1.57:6090` and `https://192.168.1.57:6443`. The Mac agent uses verified HTTPS on 6443 with `/Users/Shared/services/data/diveanalyzer/state/diveanalyzer-ca.pem`. The SSH login banner also lists `https://192.168.1.57:6443`.

Direct service bindings are loopback-only: Postgres `127.0.0.1:5433`, backend `127.0.0.1:6002`, frontend `127.0.0.1:6001`, Adminer `127.0.0.1:8080`. Use SSH tunnels for direct DB/Adminer access. The three old v2/mac-media candidate containers were removed.

## Runtime Configuration Authority

Server runtime secrets live in `/home/mcauchy/dive-analyser/.env` and are ignored. This file now contains the rotated PostgreSQL credential, the dedicated Mac machine API key, and explicit CORS origins. nginx TLS private key material lives under ignored `nginx/ssl/` on the server. The public CA certificate is copied to the Mac state directory.

Mac runtime config is `/Users/Shared/services/data/diveanalyzer/state/config.yaml` (0600). It contains the Mac machine API key, HTTPS server URL, and CA certificate path. Deployed Mac code is `/Users/Shared/services/data/diveanalyzer/code`.

## Source Authorities

- backend: Git `backend/`; runtime bind mount `/app`; PASS.
- frontend: Git `frontend/`; deployed image must be rebuilt for application source changes. This hardening changed test/config files only; runtime app remains served through nginx.
- infra: Git `docker-compose.yml`, `nginx/`; nginx config is bind-mounted; PASS.
- Mac agent: Git `mac-agent/` plus deployed Mac code. CA-supporting `config.py`, `sync_client.py`, and repaired `test_sync_client.py` were deployed to the Mac runtime during hardening; keep parity when committing.

## Security Status

- DB credential rotation: PASS. Existing DB role `diving` was rotated; production counts preserved.
- Git sanitization: PASS. Reachable history no longer contains tracked `.env` or the obsolete DB credential; `git fsck --strict` passed after rewrite.
- Machine API auth: PASS. `verify_api_key` validates runtime configured keys with secure comparison and fails closed. Media-agent DB allow-list still enforces per-agent hash/capabilities for media routes.
- TLS: PASS for Mac agent. Local CA/server certificate covers `192.168.1.57`, `127.0.0.1`, `deb-serv`, `deb-serv.local`, and `diveanalyzer-server`. Browser trust is not installed globally.
- CORS: explicit runtime origin list, no wildcard with credentials.
- LAN exposure: direct DB/Adminer/backend/frontend ports are loopback-only; nginx remains LAN-facing.

## Production Data Authority

PostgreSQL Docker volume remains the production metadata authority. Server `media/videos` holds legacy originals/stubs; `media/cache` holds derived renditions. Mac Photos and `/Users/Shared/services/data/media-node/` remain the authority for new originals/source vault. No production DB rows, media originals, or Photos assets were deleted by hardening.

## Tests And Validation

Focused backend security/sync/media tests: 21 passed. Frontend MediaRecall: 3 passed after stale duplicate-text assertion repair. Mac deployed SyncClient: 5 passed. Backend/frontend/nginx/Postgres health checks passed after restarts. HTTPS verification from Mac succeeded with CA and failed without CA.

Server-host Mac-agent async tests skip unless `pytest-asyncio` dev dependency is installed; deployed Mac venv has the dependency and passes.

## Current Analysis Capabilities

Current analysis remains user-authored metadata plus deterministic/statistical/heuristic backend logic: caption parsing, DD lookup/provenance, session aggregates, two-phase self ratings, Personal Dive Value V1, Journey/fear/plateau heuristics, media readiness, and representative-media workflows. No CV/ML/pose/trajectory/entry detector has been implemented.

## Layer-2 Design Status

Layer-2 is design-only. The proposal recommends new versioned analysis entities, separate `analysis_jobs`, artifact metadata in PostgreSQL, heavy artifacts on local filesystem, a shared metric registry, first-class comparison outputs, and a first-slice order of temporal segmentation, pairwise alignment, takeoff/trajectory feasibility, entry detection, then pose/keypoints.

## Remaining Engineering Debt

1. Migration-system consolidation remains deferred.
2. DB role privileges remain broad; rotation preserved current architecture.
3. Browser/system trust for the local CA is not installed; Mac agent trust is explicit.
4. No private GitHub/GitLab remote is proven; Mac mirror is the current off-host backup.
5. Frontend image should be rebuilt on the next user-facing frontend source change.
6. Historical ignored archives still exist outside the repo and should remain local/private.
7. PostgreSQL/Adminer direct access now requires SSH tunneling.

## Supervisor Decisions Required

See `docs/design/ANALYSIS_LAYER_2_FOUNDATION_PROPOSAL_2026-09-05.md`, section 18.

## Current Gate

`SUPERVISOR_REVIEW_AFTER_FOUNDATION_HARDENING_AND_LAYER2_DESIGN`
