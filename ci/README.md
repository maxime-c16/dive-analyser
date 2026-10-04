# Local CI

The existing pre-push design stays: no CI server, daemon, test matrix, or idle
memory use. Checks run sequentially at low CPU priority on the box that also
serves the app. A shared lock prevents concurrent gates across worktrees;
Vitest uses one worker, Node's heap defaults to 768 MB, numerical libraries
use one thread, and each test/build command has a 15-minute timeout.

```bash
ci/install-hooks.sh      # install/update the shared Git pre-push hook
ci/gate.sh               # all correctness checks (no image builds)
ci/gate.sh fast          # cheapest checks only
ci/gate.sh frontend      # frontend tests + TypeScript + production bundle
ci/gate.sh backend       # API/service tests against isolated SQLite
ci/gate.sh agent         # portable Mac-agent logic on Linux
ci/gate.sh images        # build production images without deploying
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

Docs-only pushes run `fast`. Frontend changes add `frontend`; backend/layer2
changes add `backend`; Mac-agent changes add `agent`. Compose changes add
backend/frontend/images. Changes under `ci/` rerun every correctness tier.
Dockerfile and dependency changes also build images.

The hook examines all commits introduced by a new branch, not just its tip.
Existing refs use the old/new tree diff, including force pushes. Unknown ranges
run all tiers. Deleting a ref needs no tests. Filenames are read with NUL
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

- Wall-clock performance/load tests: run separately on a quiet box with
  `pytest tests/test_performance_sync.py tests/test_load_concurrent.py -m performance --asyncio-mode=auto`.
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

The existing `ci/deploy.sh` is preserved from the original pipeline. This
change does not deploy the app or modify running containers.

## Validation on this box (2026-10-04)

- Backend: **685 passed**, 6 explicit live-DB skips, 23 performance tests
  deselected; zero failures/errors.
- Agent: **272 passed**, including catalog and media safety; zero skips/failures.
- Frontend: **126 passed** across 11 test files; TypeScript/Vite production build passed.
- Gate/hook regression suite: **14 passed**; source syntax and whitespace checks passed.

The updated shared pre-push hook is installed and verified against `ci/pre-push`.
Its push-range and clean-tree checks are active. Worktrees on branches without
`ci/` must merge these files before pushing; missing gates now block pushes.
