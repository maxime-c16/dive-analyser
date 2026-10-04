# dive-analyser CI/CD

A deliberately small pipeline. There is no CI provider for this repo — the only
git remote is an SSH bare repo on a LAN Mac — so there is no hosted runner to
delegate to. The enforcement point is a git `pre-push` hook calling
`ci/gate.sh`. No daemon, no idle memory cost, nothing to keep alive.

Everything is sized for the host it runs on: **2 CPUs, ~1.9 GB free RAM, with
the production dive-analyser stack co-resident**. Long jobs are `nice`d so they
do not starve the running app.

## Quick start

```bash
ci/install-hooks.sh      # install the pre-push gate (must be re-run after cloning)
ci/gate.sh               # fast + frontend + backend
ci/gate.sh all           # everything incl. docker image builds
ci/deploy.sh --dry-run   # rehearse a deploy without changing anything
```

## Layout

| File | Role |
| --- | --- |
| `ci/gate.sh` | CI. Tiered checks, ordered by cost. |
| `ci/deploy.sh` | CD. Build, swap, health-verify, roll back on failure. |
| `ci/lib.sh` | Shared helpers: logging, caching, HTTP waits. |
| `ci/install-hooks.sh` | Installs/removes the `pre-push` hook. |
| `ci/baseline/backend-failures.txt` | The known-failure ratchet (see below). |
| `~/.cache/dive-ci/` | Caches: backend venv, logs. Outside the repo on purpose. |

## Tiers

Cost-ordered, so a typo fails in seconds rather than after the three-minute
backend suite. Each tier aborts the run on failure — no point finishing the
suite once the build is already broken.

| Tier | Cost | What it does |
| --- | --- | --- |
| `fast` | ~0.3 s | Shell syntax, `docker-compose config`, compose build contexts exist, no tracked secrets. |
| `frontend` | ~50 s | `vitest run` (126 tests) + `tsc --noEmit`. |
| `backend` | ~3.5 min | `pytest tests/ -m "not performance"` against the baseline. |
| `images` | ~3 min | `docker build` of the two deployable images. |

## The pre-push hook only runs what changed

The hook reads the ref updates git feeds on stdin and maps changed paths to
tiers. Measured on this host:

| Push touches | Tiers run | Wall clock |
| --- | --- | --- |
| `docs/**` only | `fast` | **0.33 s** |
| `backend/**` only | `fast backend` | ~3.5 min |
| `frontend/**` only | `fast frontend` | ~1 min |
| `docker-compose.yml` | all | ~8 min |

Escape hatches:

```bash
DIVE_CI_SKIP=1 git push ...                    # bypass entirely
DIVE_CI_TIERS='fast' git push ...               # force a tier set
```

## The backend baseline is a ratchet, not an excuse

`backend/tests/` has **31 pre-existing failures** (17 failed + 14 errors). These
are real product drift, not infrastructure noise — for example
`ResultsAggregator.__init__()` grew a required `db` argument while its tests
still construct it the old way, and some FINA fixtures re-insert dive codes
that `conftest.py` has already seeded, tripping a UNIQUE constraint.

Gating on pytest's raw exit code would mean a permanently red pipeline that
everyone learns to ignore, which is worse than no pipeline. So `ci/gate.sh`
treats the baseline as a **ratchet**:

* a test that is broken **and not listed** → CI fails, naming the test;
* a test that is listed **and now passes** → CI warns, so the list can shrink;
* fixing a test and deleting its line is a normal, reviewable act.

The set was verified **deterministic** — identical 31 ids across three
independent full runs — so the ratchet cannot flap. If a test ever starts
failing intermittently, do *not* baseline it; delete it from the gate or mark
it properly. That is how `test_performance_sync.py` was handled (below).

### One test-file fix this required

`tests/test_performance_sync.py` contains 34 wall-clock latency assertions
(`duration < 0.5`) and every class in it is named `TestPerformance*`, but it
carried **no `performance` marker**. So the documented
`pytest -m "not performance"` filter never excluded it, and those load-sensitive
assertions ran inside the correctness gate — where they flaked depending on how
busy the box was (they pass in isolation, fail under load).

`pytestmark = pytest.mark.performance` was added at module level. The marker was
already registered in `conftest.py`; it simply had never been applied. Run them
explicitly with `pytest tests/test_performance_sync.py -m performance`.

## Fail-safe, not fail-open

If pytest cannot start at all (bad interpreter, crash, missing plugin) it emits
no `FAILED`/`ERROR` lines, which would compare equal to a clean run and report
a **false green**. This was a real bug during development, caught by testing.

`ci/gate.sh` therefore refuses to report a pass unless:
1. pytest exited `0` or `1` (any other code means it never ran properly), and
2. the log contains a recognisable summary line.

## Deploys

`ci/deploy.sh` is deliberately cautious:

1. refuses a **dirty** working tree — an uncommitted deploy cannot be rolled
   back to a known state;
2. requires a green gate (`--skip-gate` exists and is reported loudly);
3. tags the incoming image with the git SHA and remembers the **currently
   running** image id *before* swapping;
4. waits for real HTTP 200s from the backend and through nginx — not merely for
   containers to exist;
5. on failure, restores the previous image and re-verifies, then exits non-zero.

Only the last two images are retained, so the build does not creep away under
the 172 GB free disk.

`DIVE_DEPLOY_ROOT` selects the deployment directory (default
`/home/mcauchy/dive-analyser`, where the live compose project lives).

> The repo's existing `./health-check.sh` and `./diagnostics.sh` are **not** used
> by this pipeline. `health-check.sh` curls `:6090/api/v1/health`, but
> `nginx/conf.d/default.conf:18` 301-redirects port 80 to HTTPS `:6443`, so it
> reports a false failure. `diagnostics.sh` ends with `exit $?` after an `echo`
> (always 0), and its `fix_permissions` does `chmod -R 777` — it is unsafe to
> run unattended.

## Deliberately not gated

| Item | Why |
| --- | --- |
| `npm run lint` | `eslint` is in neither `devDependencies` nor the lockfile and there is no config, so the script cannot run. Adding it would produce a large permanently-red gate. |
| `experiments/**` tests | ~40 ML research tests needing torch/ultralytics/GPU and real media. |
| `mac-agent` | Needs macOS + Python 3.12 (`osxphotos`); this host has 3.11. |
| Playwright E2E | Needs a live deployment and real credentials (`E2E_TEST_EMAIL`/`PASSWORD`); `playwright.config.ts` hardcodes a LAN IP. Gate it nightly once wired to a sandbox stack. |
| Root `Dockerfile` | Cannot build (`COPY package*.json` with no root `package.json`). Reported as a non-blocking warning by the `fast` tier. |
| `layer2/tests/` | Self-contained and cheap — worth adding to the `backend` tier later. |

## Notification policy

The pipeline **does not** notify anyone on success. It writes
`~/.cache/dive-ci/logs/*.log` and prints a summary to the terminal. Escalate to
a human only when:

* the gate is red and stays red (i.e. a real regression, not a flake), or
* a deploy failed **and** rollback did not restore health, or
* `images`/`backend` runtime regresses badly (a sign the box is overloaded).

Escape hatch for a bad day: `DIVE_CI_SKIP=1 git push`.