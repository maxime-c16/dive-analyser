# CANONICAL RUNTIME SOURCE BASELINE — 2026-09-05

Task: P0.5 source-authority reconciliation of the server application.
Scope: Git source authority only. **No container was rebuilt or restarted, no
deployment changed, production DB and media untouched, no remote configured or
pushed.**

Status: **GREEN**

---

## 1. Starting repository state (preflight, recorded before any mutation)

- Repository: `mcauchy@192.168.1.57:~/dive-analyser` (host `deb-serv`, Debian 12)
- Branch: `uiux-overhaul-pro-app`
- Starting HEAD: `a155019ad804df0414ae3e150992bda71fb851ef` (verified, matches packet)
- History: 5 commits (`7ae8b01` squashed restructure of 2026-02-03 + 4 source-authority commits from the Mac-agent reconciliation)
- Remotes: none (verified)
- Working tree: 574 status entries —
  - staged: **123** paths (mixed: real Feb-2026 DD-era source + `.env` + 60 `__pycache__` `.pyc` + 20+ session-report MDs + `reports/dive_metadata_20260126.json` + `test-results/.last-run.json`)
  - unstaged tracked: **279** (≈230 AppleDouble `._*`/deletions, pycache, plus real modified backend/frontend/nginx/compose files)
  - untracked: **19,175** (frontend/node_modules 16,667; media/cache 1,691; media/videos 176; backups/ ~370; **backend/app + tests + migrations source files 117**; frontend/src/e2e 48; logs, docs, debris)
- Disk usage: 15 GB (of which media ≈ 15 GB data, not code)
- No `.gitignore` existed; `.env` was **tracked** in HEAD.
- **260 AppleDouble `._*` files were tracked in HEAD**, plus 169 tracked `__pycache__` `.pyc` files.
- Raw pre-reconciliation status archived at
  `docs/audits/evidence-2026-09-05-preflight/` (staged / unstaged / untracked / status-short).

## 2. Running deployment relationship (verified via `docker inspect`)

| Service | Image | Source relationship |
|---|---|---|
| backend `dive-analyser-backend-1` | `dive-analyser-backend` (611e1035965a, built 2026-07-25) | **Bind mount `./backend:/app` (rw)** — the working tree IS the running code. Also mounts `./src:/app/legacy_scripts:ro` (empty dir), `./reports`, `./logs`, `./media/videos:/videos:ro`, `./media/cache:/app/media-cache`, dead macOS Photos mount. Cmd: `uvicorn app.main:app --workers 2`. Up 3 weeks, healthy. |
| frontend `dive-analyser-frontend-1` | `dive-analyser-frontend:latest` (0d5288564a3c, built 2026-08-12 13:32) | **No mounts — baked image** serving `/usr/share/nginx/html` via nginx (`CMD nginx -g daemon off;`). Built by `frontend/Dockerfile.deploy` (node:20-alpine `npm ci` + `npm run build` → nginx:1.27-alpine). |
| nginx `dive-analyser-nginx-1` | nginx:alpine | Bind mounts `./nginx/nginx.conf`, `./nginx/conf.d/`, `./nginx/ssl/` (ro) — **repo nginx/ IS the runtime config**. |
| postgres `dive-analyser-postgres-1` | postgres:16-alpine | Docker volume `postgres_data`; `./backend/migrations/init.sql` mounted as first-boot init only. Up 6 weeks, healthy. |
| adminer | adminer:latest | stateless. |

Compose: `docker-compose.yml` in repo root (v2, network `diving_network`).
`.env` (untracked) supplies `POSTGRES_*` via compose variable substitution.

## 3. Backend source authority

**Authority = repo working tree `backend/` = the running code (bind mount).** The
commit `178c68e` therefore canonicalizes exactly what runs:

- Added 84 previously-untracked source files: routers (`media.py`, `dive_analysis.py`,
  `divers.py`, `personal_dive_value.py`, `training_periods.py`), 12 models, media
  schemas, 20 services (media_agents/jobs/cache/catalog/recall/resolution_upgrade,
  dive_analysis*, personal_dive_value, world_aquatics_dd, representative_*, …),
  14 migrations, 13 tests, 2 scripts.
- Committed all tracked-modified files (routers, services, config, database, main,
  migrations `init.sql` + `00_init_user_and_db.sql`, Dockerfile, conftest, 10 tests).
- Recorded as deletions the DD-component files **already removed from the runtime
  tree** before this task (verified missing on disk AND absent from the router
  registry `backend/app/api/v1/__init__.py`): `api/v1/dd_calc.py`,
  `api/v1/dd_components.py`, `services/dd_component_loader.py`,
  `schemas/dd_components.py`, `models/dd_component_reference.py`,
  `data/diving_dd_components.json`, `scripts/init_dd_components.py`,
  `scripts/populate_dd_lookups.py`, `scripts/populate_fina_codes.py`, 3 test files,
  `BOOTSTRAP.md`.
- Stale-index note: the pre-existing staged index was a **Feb-2026 snapshot** that
  still contained the DD-component files as additions even though they were later
  deleted from disk. Working-tree truth (what the container actually executes) won.
  The complete pre-existing staged list is preserved in the evidence archive.
- Not canonicalized (ignored, left on disk): `backend/media_cache.py` and
  `backend/media_resolution_upgrade.py` (obsolete root-level duplicates of
  `app.services` modules — nothing imports them),
  `backend/add_media_resolution_upgrade_runs.sql` (byte-identical duplicate of the
  `migrations/` copy, md5-verified), `backend/migrations/00_init_user_and_db.sql.bak`
  (backup of the pre-sanitization bootstrap SQL; password inside differs from the
  live one).

**Backend authority: PASS** (every file the running container executes is committed;
syntax-validated).

## 4. Frontend source authority

- Source tree `frontend/`: committed all tracked-modified files (App/page/component
  sources, `package.json`, `package-lock.json`, `vite.config.ts`, `Dockerfile`) plus
  36 previously-untracked files (`Dockerfile.deploy`, `nginx.conf`, `.dockerignore`,
  pages MediaRecall/RepresentativeMedia/DiveAnalysis/Admin + tests, services,
  DDWorkspace, e2e suite, `src/test/setup.ts`).
- Recorded as deletions the components already removed from the runtime tree
  (verified unused: `router.tsx` imports none of them): CompetitionEventSetup,
  CompetitionResults, CompetitionScoring, ComplianceDashboard,
  DegreeOfDifficultyDisplay, DiveCodeInfo, MentalBlockAnalysis,
  RecoveryPlanDisplay, CompetitionHub, `capture-errors.js`, root `index.css`,
  `e2e/console-errors.spec.ts`.
- **Deployed-build parity PROVEN** (not merely assumed): a fresh `vite build` from
  the committed tree (host node v24.12.0, existing node_modules filled in with
  `npm install`, build output written to `/tmp` and deleted afterwards) reproduced
  the deployed image bundle **byte-for-byte**:
  - `assets/index-w_MhTRQ8.js` md5 `3b25b5926415be1d4a89a0fa837eb228` == image
  - `assets/index-CzED_XRX.css` md5 `d6191ba262c2b665d4e5cb994ee667b0` == image
  - `index.html` md5 `fc22ba6e290b784b3c6a5cc61c416298` == image
  - (sourcemap differs — expected; sourcemaps embed absolute build paths)
- Ignored as generated: `frontend/node_modules/`, `frontend/dist/`,
  `frontend/test-results/`.
- Left untracked+ignored: `frontend/.codex-desktop.mjs`, `.codex-ui-capture.mjs`
  (agent-session playwright tooling, not app source).

**Frontend authority: PASS — SOURCE_AUTHORITY_PASS and DEPLOYED_BUILD_PARITY PASS.**

## 5. Infrastructure source authority

Committed as currently running:

- `docker-compose.yml` (working-tree version: adds media-cache mount, tuning env
  vars, `NEW_VIDEO_AUTO_MEDIA_ENABLED` substitution; removes `env_file:` —
  substitution reads `.env` from the project dir anyway).
- `nginx/nginx.conf`, `nginx/conf.d/default.conf` (bind-mounted runtime config;
  worktree versions are what nginx serves).
- `backend/Dockerfile`, `frontend/Dockerfile`, `frontend/Dockerfile.deploy`,
  `frontend/nginx.conf`.
- `ops/` (new): `icloud-video-sync.sh`, `icloud-video-cache-prune.sh`,
  `icloud-video-sync.env.example` (template). The machine-specific
  `ops/icloud-video-sync.env` (no passwords; contains container names, paths,
  icloudpd username) was kept out of Git as runtime config.
- Root `Dockerfile` (tracked since HEAD; dev-server variant, kept as-is).

Ignored: `nginx/ssl/` (TLS key material — host only), `media/`, `backups/`,
`reports/`, `logs/`.

**Infra authority: PASS.**

## 6. Staged-change classification (the pre-existing 123 paths)

| Class | What the staged state actually was | Action |
|---|---|---|
| Current runtime source | backend/frontend/infra files that exist on disk (Dockerfiles, compose, DD-engine modules, frontend sources) | committed |
| Already-deleted-from-runtime source | DD-component files + removed frontend components staged in a stale Feb-2026 index, deleted from disk afterwards; not referenced by the runtime router registry / router.tsx | staged additions dropped; deletions committed (worktree truth) |
| RUNTIME_SECRET_CONFIG | `.env` (staged `MM`, contains the live DB password) | untracked (`git rm --cached`), ignored; runtime file untouched |
| GENERATED | 60 staged `__pycache__/*.pyc` | untracked, ignored |
| Documentation debris | ~22 staged root-level session-report MDs (DD_*, PHASE_*, TICKET*, PSYCHOLOGY_*, TROUBLESHOOTING, …); 3 of them tracked in HEAD contain the live DB password (DEPLOYMENT_SUCCESS.md, FIXES_APPLIED.md, ROOT_CAUSE_ANALYSIS.md) | untracked (including untracking the 3 credential-bearing ones), ignored by root-anchored patterns; files remain on disk |
| DATABASE_OR_DUMP | `reports/dive_metadata_20260126.json` (import source for AUTO_IMPORT) | untracked, `reports/` ignored |
| Test artifacts | `test-results/.last-run.json`, `playwright-psychology-test.spec.ts`, `test-*.sh/py/js` | untracked, ignored |

## 7. Files excluded from source control (and why)

- `.env` — live runtime secret (POSTGRES_PASSWORD). **Physical file untouched on disk.**
- `media/` — 14 GB legacy originals + rendition cache: DATA, never source.
- `backups/` — database dumps, frontend-source snapshots, mac-media-01,
  media-catalog-runs, media-manifests, staging: archival data.
- `reports/` — runtime import data (bind-mounted into backend).
- `logs/` — runtime logs.
- `frontend/node_modules/`, `frontend/dist/`, test artifacts — generated/reproducible.
- `.__*`/`._*`, `.DS_Store` — AppleDouble/metadata.
- `divesensei-pre-media-rollout.dump`, `nginx-pre-media-rollout.txt`,
  `.codex-backup-*/` — dumps/backups at repo root.
- `backend/media_cache.py`, `backend/media_resolution_upgrade.py`,
  `backend/add_media_resolution_upgrade_runs.sql`,
  `frontend/src/pages/index.css.transfer-check` — obsolete duplicates/copies.
- `ops/icloud-video-sync.env` — machine-specific runtime config.
- Root session-report debris MDs/TXTs (~48 files) — historical session reports.

Nothing was deleted from disk in this task; the only disk writes were: `.gitignore`
(new), sanitization of 2 credential-bearing source files, removal of the **empty**
directory `backend/migrations/00_init_user_and_db.sql/` (it was an empty dir blocking
the tracked file path), and the evidence archive + docs. `npm install` added
missing dev dependencies to the ignored `frontend/node_modules/` and touched
`frontend/package-lock.json`, which was then restored to the committed state.

## 8. `.gitignore` decisions

New root `.gitignore` covers: `.env*`, `._*`/`.DS_Store`, `__pycache__/`/`*.pyc`,
`.pytest_cache/`, `*.egg-info/`, `node_modules/`, `/frontend/dist/`, test
artifacts, `/logs/`, `/backups/`, `/media/`, `/reports/`, `/memory/`, `*.dump`,
`*.bak`, `.codex-backup-*/`, `*.transfer-check`, `/nginx/ssl/`, root-anchored
session-debris patterns (`/*.md`, `/*.txt`, `/test-*`, `/*.spec.ts`),
`/ops/*.env`, `frontend/.codex-*`, and the three obsolete duplicate files listed
above. Root-anchored patterns were chosen so `docs/` and subdirectory sources are
never accidentally ignored. Tracked files are unaffected by ignore rules.

## 9. Secret containment

- The live DB password existed in tracked/staged content of: `.env` (tracked in
  HEAD), `backend/.env.example`, `backend/migrations/00_init_user_and_db.sql`
  (tracked in HEAD; on disk it had been replaced by an empty directory +
  `.bak`), and three root session-report MDs.
- Actions taken (authorized by the packet; no rotation):
  1. `.env` removed from the Git index (runtime file preserved, mode/content unchanged), ignored.
  2. `backend/.env.example`: credential → `CHANGE_ME_USE_RUNTIME_ENV`.
  3. `backend/migrations/00_init_user_and_db.sql`: rewritten as a sanitized
     bootstrap template (`CHANGE_ME_USE_RUNTIME_ENV`); the empty directory that
     had replaced the file on disk was removed (it was empty). Postgres already
     runs from its volume; first-boot init never re-executes — zero runtime impact.
  4. Credential-bearing session-report MDs untracked (kept on disk).
- Full-commit-diff scan for the live credential and generic secret patterns: the
  only remaining occurrences are removals (`-` lines) and placeholder fixtures
  (`test-api-key-long-enough`). No newly introduced secret in the commit.
- **The credential remains in Git history** (HEAD~… and earlier commits). No remote
  exists; rotation + history sanitization remain P0.6.

## 10. Runtime parity findings

- Backend: working tree = bind-mounted runtime (PROVEN via `docker inspect`).
  Committing the tree commits the running code. Runtime-parity PASS by construction.
- Frontend: byte-exact rebuild parity PROVEN (§4).
- nginx: repo configs are the bind-mounted runtime configs (PROVEN).
- Mac agent: unchanged in this task (byte parity PASS from the previous
  reconciliation, HEAD `a155019` still contains it).
- DB schema: live Postgres (44 tables) vs 22 hand-rolled SQL migrations —
  ordering/consolidation still unresolved (known issue, do-not-touch; unchanged).

## 11. Validation

- Backend: AST-parsed all 154 real `backend/**/*.py` files — **0 syntax errors**
  (11 non-UTF8 hits were AppleDouble `._` files, i.e. binary metadata, ignored).
- Frontend: `tsc --noEmit` — all 34 errors are confined to test files
  (`vitest`/`@testing-library` were missing from the server's partial
  node_modules before the fill-in; no app-source errors).
  `vite build` — success; output reproduced the deployed bundle exactly.
  `vitest run` — 43/44 real tests pass. 2 surface failures, both pre-existing and
  not caused by this task: vitest scanning AppleDouble `._DiveAnalysis.test.tsx`
  (junk file, not source) and one `MediaRecall.test.tsx` assertion
  ("multiple elements with text 103B"). Not fixed: behavior changes are out of scope.
- Build outputs were written to `/tmp` and deleted; `frontend/package-lock.json`
  touched by `npm install` was restored; `node_modules` (ignored) retains the
  filled-in dev deps.

## 12. Resulting Git state

- Branch `uiux-overhaul-pro-app`, HEAD **`178c68e`** ("Canonical baseline of server
  application source currently running (P0.5)", parent `a155019`).
- Single commit; 627 files changed (+43,795/−6,300 incl. evidence archive).
- `git status --short` → **empty** (0 staged, 0 unstaged, 0 visible untracked;
  19k+ paths ignored by design).
- Remotes: none. Nothing pushed.
- History note: historical live credential material persists in old commits —
  P0.6 (rotation + history sanitization) still required before any remote.

## 13. Unresolved discrepancies / knowns

1. Live DB credential in Git history (P0.6: rotate + scrub; also present in three
   on-disk session-report MDs and `backend/migrations/00_init_user_and_db.sql.bak`,
   and in the Mac's `docs/archive/DEPLOYMENT_READY.md`).
2. `docker-compose.yml` defaults (`diving_analytics`/`diver`/
   non-live placeholder password) differ from the live DB names; harmless while
   `.env` supplies the real values, but a fresh-machine compose boot would create
   a wrong-default DB. Documentation-level debt; do not change topology now.
3. Migration consolidation (SQL files vs Alembic; manual application order) — open.
4. `frontend/Dockerfile` (dev server, port 3000) does not reflect the deployed
   build path; `frontend/Dockerfile.deploy` is the real one. Kept both; a later
   task may consolidate.
5. 1 pre-existing vitest failure (`MediaRecall.test.tsx`); stale Mac-agent
   `test_sync_client.py` (15 failures) — both out of scope.
6. ~48 root-level session-report MDs + `.codex-*` tooling + obsolete duplicates
   remain on disk, ignored. Archival relocation is a future supervised chore.
7. `backend/media_cache.py` / `backend/media_resolution_upgrade.py` root-level
   modules: no importer found; classified obsolete. If any out-of-repo tooling
   imports them, revisit.
8. Dead macOS Photos bind mount + legacy `/photos_library` paths in compose/config:
   unchanged (documented in cartography as R-03).

## Authority matrix

| Concern | Git authority | Runtime location | Parity | Notes |
|---|---|---|---|---|
| Mac agent | `mac-agent/` @ `178c68e` | `/Users/Shared/services/data/diveanalyzer/code` (Machine B) | PASS (byte parity, prior task) | unchanged here |
| Backend | `backend/` @ `178c68e` | bind mount `./backend:/app` in backend container | PASS (identity) | working tree = running code |
| Frontend | `frontend/` @ `178c68e` | baked `dive-analyser-frontend:latest` image (0d5288564a3c) | PASS (byte-exact rebuild of JS/CSS/html) | built via `frontend/Dockerfile.deploy` |
| nginx | `nginx/nginx.conf`, `nginx/conf.d/` @ `178c68e` | bind mounts into nginx container | PASS (identity) | `nginx/ssl/` host-only |
| Compose | `docker-compose.yml` @ `178c68e` | compose project on Machine A | PASS (identity) | `.env` supplies secrets |
| DB schema | `backend/migrations/*.sql` | live Postgres 16 volume | PARTIAL (consolidation/ordering unresolved) | do-not-touch |
| Runtime env | NOT in Git (ignored) | `/home/mcauchy/dive-analyser/.env` + `ops/icloud-video-sync.env` | N/A | contains live credential |
| Mac agent runtime config | NOT in Git (template: `mac-agent/config.example.yaml`) | Machine B `state/config.yaml` | N/A | secrets |
| Media originals (legacy) | NOT in Git | `media/videos` (82 real + 94 stubs) | N/A | DATA |
| Renditions | NOT in Git | `media/cache` (~840 MB) | N/A | derived data |
| DB dumps/backups | NOT in Git | `backups/`, `*.dump` | N/A | archival data |
