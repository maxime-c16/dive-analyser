# dive-analyser

Dive tracking for clubs and coaches: FastAPI backend, React/Vite frontend,
media pipeline driven by a Mac worker. Deploys continuously from `master`
(`docs/CD.md`). Agents: start at `AGENTS.md`; this file is the shared index.

## Doc map

| Need | Read |
|---|---|
| Agent workspace rules + the loop | `AGENTS.md` |
| Git, hosts, deploy authority | `docs/REPO_WORKFLOW.md` |
| CI matrix, tiers, what must be tested | `ci/README.md` |
| Auto-deploy, versioning, merge protection | `docs/CD.md` |
| Engineering checks before changing code | `docs/AGENT_ENGINEERING.md` |
| Scores, notes, success rates, colour bands | `docs/SCORING.md` |
| Release-note schema | `docs/RELEASE_NOTES.md` |
| Concrete environment notes (ssh, secrets, quirks) | `TOOLS.md` |
| System snapshot / chronicle (verify dates) | `docs/PROJECT_STATE.md` |

## The loop (works today)

```bash
ci/checkhost.sh                     # what this box can run (docker? ssh aliases?)
ci/gate.sh fast                     # docs / release-note JSON only (~seconds)
ci/gate.sh frontend                 # frontend tests + TypeScript + production build
ci/gate.sh backend                  # API/service tests on isolated SQLite
ci/gate.sh agent                    # portable Mac-agent logic
ci/gate.sh tiers -- <paths>         # which tiers your changed paths need
ci/gate.sh                          # fast + frontend + backend + agent (no images)
```

- Frontend iteration: `cd frontend && npm run --silent test:ci`. **Never plain
  `npm test` — vitest watch mode hangs the session.** Build check:
  `npm run --silent build`.
- Backend iteration (deps installed):
  `cd backend && DATABASE_URL=sqlite:///:memory: AUTO_IMPORT=false DB_TEST=0
  PYTHONPATH="$(pwd):$(pwd)/.." python3 -m pytest tests/ -m "not performance"
  --asyncio-mode=auto -q`. Otherwise bless it with `ci/gate.sh backend`.
- Image builds and proxy checks run on **deb-serv** (`ci/ship.sh`) or hosted
  CI; the laptop's Docker daemon being off is normal.
- `ci/ship.sh` reaches the hosts through the `diveanalyzer-server` /
  `diveanalyzer-mac` ssh aliases (see `TOOLS.md`, override with
  `DIVE_SERVER_SSH` / `DIVE_MAC_SSH`).

## Deploy

```bash
ci/ship.sh status            # what runs where, vs origin/master
ci/ship.sh server --dry-run  # plan + warnings, changes nothing
ci/ship.sh server            # app stack (also automatic: docs/CD.md)
```

Rules that bite if ignored (full list: `docs/REPO_WORKFLOW.md`): never edit
the live dirs, deploy only via `ci/ship.sh`, SQL migrations are applied by
hand, merges to `master` are picked up by the release tag + auto-deploy cron.
