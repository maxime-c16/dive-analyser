# TOOLS.md - This box and this repo (concrete environment notes)

Skills define *how* things work. This file is *what is actually here* — the
per-repo setup facts. Versioned in the repo so every checkout reads the same
truth. Last verified: 2026-11-09.

## The fleet (single list of host facts)

| Host | ssh alias | Reach | Role |
|---|---|---|---|
| MacBook Air (dev laptop) | — | local | code, t3 worktrees, `ci/gate.sh`, `ci/ship.sh` |
| `deb-serv` | `diveanalyzer-server` | 192.168.1.57, user `mcauchy` | app host: Postgres, FastAPI, frontend, nginx 6090/6443, Funnel proxy 6091 |
| `mac-server` (`mac-media-01`) | `diveanalyzer-mac` | 192.168.1.19, user `divesensei` | media worker: Photos ingest, posters/proxies, source vault |

- Ssh key: `~/.ssh/qwokka`; both aliases are defined in the laptop's
  `~/.ssh/config`. Verify any box at a glance: `ci/checkhost.sh`.
- Overrides: `DIVE_SERVER_SSH` / `DIVE_MAC_SSH`.

## Live dirs (deploy targets — never edit, only `ci/ship.sh` writes them)

- `deb-serv:~/dive-analyser` — app code, HEAD detached at the deployed commit.
- `/Users/Shared/services/data/diveanalyzer/code` (mac worker) — not a git
  repo; agent logs land in `/Users/Shared/services/logs/diveanalyzer/`.

## Server-side secrets (0600, never in git)

On deb-serv: `~/.config/diveanalyzer/{browser-upload,email,calendar,sessions,
media-jobs}.env` — sourced by compose during `ci/ship.sh server` and rollback.
Never echo their contents in logs, proof artifacts or replies. The Mac worker
keeps its sync config under `/Users/Shared/services/data/diveanalyzer/`.

## Laptop quirks (this MacBook Air)

- Docker daemon is usually OFF: image builds and proxy checks are
  server-side. `ci/gate.sh images` fails fast with a readable message.
- GNU `timeout/sha256sum/nproc/flock` exist through Homebrew
  (`brew install coreutils flock`) — without them the gate cannot run.
- Not installed **and not required** by `ci/*` or `ops/*`: `mysql`, `yq`,
  `go`, `duckdb`, `wrangler`. Do not chase them if a task mentions them —
  grep first.

## Who runs what

- PR flow: worktree → `git push -u origin <branch>` → `gh pr create --fill`
  → babysit reviews/CI → merge (auto-merge + release tag + auto-deploy cron
  on deb-serv, `docs/CD.md`).
- Media worker rollout only when `mac-agent/` changed: `ci/ship.sh mac`
  (never manual rsync/pip on the worker).
