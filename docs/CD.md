# Continuous deployment

This repo deploys continuously: merge to `master` → tagged release → the server
picks it up and ships it, with the same lock and rollback behaviour as a manual
`ci/ship.sh server`. Nothing new was invented; the existing `ci/ship.sh` /
`ci/deploy.sh` pipeline is the deployer, and the existing `deploy.lock` keeps
every path serialized.

```
PR opened ──► review bot + hosted CI ──► auto-merge (native) ──► push to master
                                                                    │
                                  ┌─────────────────────────────────┤
                                  ▼                                 ▼
                    release workflow (tag + Release)     server cron (ops/auto-deploy.sh)
                                  │                                 │
                                  └────────── fetch tag ────────────┘
                                                          ▼
                                              ci/ship.sh server (lock, gate, swap, verify, rollback)
```

## 1. Merge (native auto-merge)

Merges are automatic but still human-in-the-loop: a person enables auto-merge
on the PR; GitHub merges it once the required checks pass. Set this up once.

Branch protection on `master` (repo settings → Branches):

- Require a pull request before merging.
- Require approvals: **1**.
- Require status checks to pass: **CI / gate** (from `.github/workflows/ci.yml`).
- (Optional) Require branches to be up to date before merging.

Then enable auto-merge per repo (Settings → General → Pull Requests → *Allow
auto-merge*). On each PR, click **Enable auto-merge** (choose *Squash*). The
review bot's verdict is advisory; the human still presses the button. This is
deliberate: the deployer is unchanged, only the trigger is new.

The hosted CI check is the same gate the pre-push hook runs (fast + frontend +
backend + agent, no image builds), so `master` never merges code whose gate
failed on GitHub — even if someone bypassed the hook with `DIVE_CI_SKIP=1`.

## 2. Versioning

`ci/version.py` derives a semantic version from conventional-commit prefixes in
the commits since the last `v*` tag:

- `feat:` → minor bump
- `fix:` / `chore:` / anything else → patch bump
- `BREAKING CHANGE:` or `type!:` → major bump

The first release is `v1.0.0`. On every merge to `master`, the release workflow
runs it, tags the commit `vX.Y.Z`, and publishes a GitHub Release whose body is
the release notes added since the previous tag. A version only exists for
commits that are on `master`; the deploy poller only ships a commit that already
carries a tag, so the app always has a version to show.

## 3. Deploy (pull)

`.github/workflows/release.yml` never reaches the server (a hosted runner cannot
see `192.168.1.57`). The server instead pulls: `ops/auto-deploy.sh` runs from
cron on `deb-serv`, fetches `origin/master`, and — once the target commit has a
release tag — runs `ci/ship.sh server`. It no-ops when the live checkout is
already at that commit.

Install:

```bash
# on deb-serv, as mcauchy
crontab -e
# add (polls every 10 minutes):
*/10 * * * * /home/mcauchy/dive-analyser/ops/auto-deploy.sh
```

Concurrency is the same as always: `ci/ship.sh` takes `~/.cache/dive-ci/deploy.lock`,
so an auto-deploy can never overlap a manual `ci/ship.sh server` or another
tick. A target without a tag (the release workflow hasn't finished) is skipped
until the next tick. Logs: `~/.cache/dive-ci/auto-deploy.log`.

Rollback is unchanged — `ci/ship.sh server --ref <previous-sha>` (the previous
commit still has its tag on `master`).

## 4. What the user sees

`ci/release-notes.py build` now emits a `version` field on the catalog, derived
from `git describe --tags --exact-match` on the running frontend SHA. The
backend passes it through `/api/v1/updates`, and the "What's new" panel renders
"Version vX.Y.Z" under its title. Older deployments (no tag) simply show no
version; nothing breaks.

## Files

- `.github/workflows/ci.yml` — hosted gate status check.
- `.github/workflows/release.yml` — tag + GitHub Release on merge.
- `ci/version.py` — semver computation and release body.
- `ops/auto-deploy.sh` — server-side pull poller.
- `ci/release-notes.py`, `backend/app/api/v1/updates.py`, `frontend/src/components/WhatsNew.tsx` — version plumbing.
