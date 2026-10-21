# Local CI

GitHub is the authoritative correctness gate. The pre-push hook runs `fast`
by default so the developer does not wait for the same suites twice. Opt in
to changed-component local checks with `DIVE_CI_LOCAL_FULL=1`, or choose tiers
with `DIVE_CI_TIERS`. Clean-tree, pushed-commit and missing-gate guards remain.

Hosted CI selects suites from the complete PR base/head diff, validates cheap
static guards first, then runs independent frontend/backend/agent/image tiers
in parallel with `ci/gate.sh --tier <name>` (without repeating static guards). PostgreSQL has its own disposable service. A final check named
`gate` rejects any failed/cancelled selected job or failed plan. Docs and
release-note-only changes still produce this check. Unknown paths and changes
to CI/workflows select all checks. Superseded CI/review runs are cancelled;
OpenCode review has a 15-minute timeout. Its green action status means execution
completed, not that the comment verdict is APPROVE; findings remain reviewable.

Local/deployment gates stay sequential and use a shared lock: they can run on
the small server alongside production. Hosted Python environments are cached
by OS, architecture, Python version, dependency content and environment setup;
pip/npm download caches are also enabled. Per-tier logs and Python JUnit
reports are retained as Actions artifacts for seven days.

```bash
ci/install-hooks.sh      # install/update the shared Git pre-push hook
ci/gate.sh               # all correctness checks (no image builds)
ci/gate.sh fast          # cheapest checks only
ci/gate.sh frontend      # frontend tests + TypeScript + production bundle
ci/gate.sh backend       # API/service tests against isolated SQLite
ci/gate.sh agent         # portable Mac-agent logic on Linux
ci/gate.sh images        # parse both nginx configs + build production images
CALENDAR_TEST_DATABASE_URL=postgresql://.../calendar_test_ci ci/postgres.sh
ci/gate.sh all           # correctness checks + images
```

## What the app needs tested

| Area | Checks |
| --- | --- |
| Dive ingestion | Caption parsing, two-phase scores, API-key auth, retry/idempotency, sync-to-analytics flow |
| Analytics | Formula DD, execution kept separate from difficulty, diver/session scoping, training periods and personal values |
| Competitions | Persisted event lifecycle, judge panels, round/event standings and CSV/JSON exports |
| Access and playback | Session login/revocation, ownership isolation, media revisions, presigned playback and fallback behavior |
| Media ingestion | Content addressing, queue/retry state, source-vault safety, storage capacity and migration guards |
| UI | Routing, filters/URL state, sync status, library/recall, clip viewer and video player; production build |
| Gate itself | Push range selection, missing gate, dirty/different pushed tree, malformed/crashed/incomplete test reports |

The backend suite has **no allowed-failure baseline**. Every failing test or
fixture blocks the push. Structured results also reject incomplete runs and
stale reports. Async tests execute with pytest-asyncio auto mode; an async test
silently skipped because its plugin is missing is an error.

The stale competition and DD tests now exercise current persisted services and
formula-backed DD instead of removed APIs and seeded compatibility values.
The old simulated E2E suite was replaced with a real API sync/retry/analytics
flow. Runtime audit logs remain ignored by Git.

## Push selection and reproducibility

Hosted path selection lives in `ci/select-tiers.py`, also used by opted-in
local checks. Docs and JSON release notes need only `fast`; frontend changes
add frontend, backend/layer2 changes add backend and PostgreSQL, Mac-agent
changes add agent. Compose/nginx changes add image/proxy checks and dependent
suites. Dependency/Dockerfile changes build images. CI/workflow/unknown code
changes select all tiers. A note JSON under `backend/release-notes/` does not
by itself select the backend suite.

PostgreSQL checks execute the production activity UNION builder, apply all five
calendar migrations twice, compare SQL schema/model constraints, and exercise
real row-lock/idempotency/outbox races. They require a disposable PostgreSQL
`calendar_test_*` database and never use the application DB. Opted-in local
pushes omit this tier unless its explicit URL is set. This is targeted coverage,
not proof of every historical migration or a production rollout.

The hook examines all commits introduced by a new branch, not just its tip.
Existing refs use the old/new tree diff, including force pushes. Unknown ranges
run all local tiers when `DIVE_CI_LOCAL_FULL=1`; the default remains `fast`. Deleting a ref needs no tests. Filenames are read with NUL
separators. Annotated tags are peeled to their commit before checking HEAD. A push must
match HEAD in a clean worktree so checks test the actual
pushed code. The hook blocks if its gate is absent.

Hooks are shared by all worktrees. Install this hook after merging `ci/` into
branches you push from; other branches without `ci/` will be blocked. The
installer preserves unrelated hooks and uses atomic replacement. Uninstall
moves the managed hook aside rather than deleting it.

Python dependencies live in separate backend/agent venvs keyed by requirements
content and interpreter identity. Changing or removing dependencies creates a
fresh environment; switching back reuses the matching cache. Agent tests
use their own compatible HTTPX dependency without installing native osxphotos.
Frontend installs use `npm ci`; cache stamps live inside that worktree's
node_modules and cover both manifests plus the Node version. Caches/logs are
under `~/.cache/dive-ci/` (`DIVE_CI_CACHE` overrides this).

## Explicitly outside the default gate

- Wall-clock performance/load tests (including WebSocket timing variants): run separately on a quiet box with
  `pytest tests/test_performance_sync.py tests/test_load_concurrent.py tests/test_websocket_sync.py -m performance --asyncio-mode=auto`.
- Layer-2 live database probes: opt in with `DB_TEST=1`; they use Docker and
  host data. The local gate forces `DB_TEST=0` and never probes production.
- Real Photos-library access: portable tests use readers/fakes and a Linux
  native import boundary that raises if accessed. Catalog and media-safety
  tests are included; actual Photos integration still needs the Mac.
- Browser E2E: the existing Playwright configuration requires a live deployment
  and credentials. Unit tests and the API flow remain isolated.
- ML/research experiments: need media, model weights, and heavier dependencies.
- ESLint: the existing lint script has no installed ESLint or configuration;
  TypeScript and build checks provide the current static frontend gate.

These exclusions describe integration/resource boundaries, not exceptions for
known failing tests. The unused root Dockerfile still gets a static warning;
`images` builds `frontend/Dockerfile.deploy` and `backend/Dockerfile`.

Escape hatches are explicit and printed: `DIVE_CI_SKIP=1 git push` bypasses the
hook; `DIVE_CI_TIERS='fast' git push` overrides tier selection. Increase a
command timeout with `DIVE_CI_TIMEOUT` (seconds), or override `NODE_OPTIONS`
when running on a larger machine.

## Deploys

Deploy only through `ci/ship.sh` (`status | server | mac | all`, `--dry-run`
first). It ships exact commits from GitHub `origin/master`, checks the commit
out in the live server dir, and calls `ci/deploy.sh`, which runs the
`fast frontend` gate (skipped when `ci/gate-proof.py` shows GitHub's `gate`
already passed on the identical tree), builds SHA-labelled images for the
side(s) that changed, swaps containers, reloads
both nginx proxies, health-checks (LAN and public Funnel) and rolls back on
failure. Rules, hosts and rollback: `docs/REPO_WORKFLOW.md`.

## Validation on this box (2026-10-04)

- Backend: **685 passed**, 6 explicit live-DB skips, 23 performance tests
  deselected; zero failures/errors.
- Agent: **272 passed**, including catalog and media safety; zero skips/failures.
- Frontend: **126 passed** across 11 test files; TypeScript/Vite production build passed.
- Gate/hook regression suite: **14 passed**; source syntax and whitespace checks passed.

The updated shared pre-push hook is installed and verified against `ci/pre-push`.
Its push-range and clean-tree checks are active. Worktrees on branches without
`ci/` must merge these files before pushing; missing gates now block pushes.

## Merge protection and deployment

Use `gate` as the single required GitHub Actions status check on `master`.
Do not require individual matrix jobs: they are intentionally skipped for
unrelated changes. Requiring an up-to-date branch is a separate policy choice,
not needed to enforce the latest-head gate.

The deployment still performs its environment-specific health checks, proxy
reload, rollback and frontend validation. It reuses GitHub's gate result only
with provenance: the deployed commit's tree must be identical to a commit whose
`gate` check passed (`ci/gate-proof.py`). Without that proof the server runs
its own gate. Reusing tested build *artifacts* (images built in Actions and
pulled by the server) is still deferred. No application deploy or manual SQL is needed for this CI-only change.
