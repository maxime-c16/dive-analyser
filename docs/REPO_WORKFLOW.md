# Repo, sync & deploy workflow

**Read this before touching git, pushing, or deploying.** It applies to humans
and agents alike, on every machine in the fleet.

## The rules

1. **GitHub is the single source of truth.**
   `https://github.com/maxime-c16/dive-analyser`, default branch `master`.
   Every checkout's `origin` points at GitHub. No machine pushes to or pulls
   from another machine.
2. **Work on a branch, merge through a PR, deploy from `master`.**
   `ci/ship.sh` refuses to deploy a commit that is not on `origin/master`
   unless you pass `--allow-unmerged`.
3. **Never edit, commit, or run `git checkout` in the live directories.**
   - Server: `deb-serv:~/dive-analyser` is what docker-compose runs. It sits on
     a *detached HEAD* at the deployed commit, and only `ci/ship.sh` changes it.
   - Mac: `/Users/Shared/services/data/diveanalyzer/code` is what the agent
     runs. It isn't a git repo, and only `ci/ship.sh mac` changes it.
4. **Deploy with `ci/ship.sh`**, never by hand (`git pull` in the live dir,
   copying files, `docker build` ...).
5. **Never put data in git.** That includes media, `runs/`, model weights,
   `.env` files and Photos exports. `.gitignore` covers the known paths. If
   you create a new data directory, add it there.
6. **Don't use bare `git stash` / `git stash pop`.** Worktrees share one stash
   stack. Make a WIP commit on your branch instead.

## Machines

| Machine | ssh alias | Role | Checkouts |
|---|---|---|---|
| MacBook Air (`macbook-air-de-maxime4`) | — | Main dev machine | `~/.perso/t3/dive-analyser` + t3 worktrees under `~/.t3/worktrees/dive-analyser/` |
| `deb-serv` 192.168.1.57, user `mcauchy` | `diveanalyzer-server` | App host: Postgres, FastAPI, frontend, nginx (6090/6443), Tailscale Funnel proxy (6091) | **live:** `~/dive-analyser` · dev worktrees: `~/.t3/worktrees/dive-analyser/*`, `~/dive-analyser-worktrees/*` |
| `mac-server` 192.168.1.19, user `divesensei` (`mac-media-01`) | `diveanalyzer-mac` | Media worker: Photos ingest, posters/proxies, source vault | **live:** `/Users/Shared/services/data/diveanalyzer/code` · no dev clone yet (see below) |

The ssh aliases are defined in `~/.ssh/config` on the MacBook Air (key
`~/.ssh/qwokka`). `ci/ship.sh` uses them. You can override them with
`DIVE_SERVER_SSH` / `DIVE_MAC_SSH`.

## Day-to-day

### Start a change (any machine)

```bash
git fetch origin
git worktree add ../dive-analyser-worktrees/<topic> -b <topic> origin/master
cd ../dive-analyser-worktrees/<topic>
```

On the server, create worktrees from `~/dive-analyser` (they share its
`.git`). Don't edit `~/dive-analyser` itself. t3 creates its own worktrees
under `~/.t3/worktrees/`, which is fine.

### Finish a change

```bash
git push -u origin <topic>          # pre-push hook runs ci/gate.sh if installed
gh pr create --fill                 # then merge on GitHub
```

Other machines pick the change up with `git fetch origin`. Nothing else needs
syncing: no mirrors, no copying.

### Deploy

```bash
ci/ship.sh status                   # what runs where vs origin/master
ci/ship.sh server --dry-run         # plan + warnings, changes nothing
ci/ship.sh server                   # app stack on deb-serv
ci/ship.sh mac                      # media agent on mac-media-01
ci/ship.sh all                      # server, then mac (mac skipped if server fails)
```

Run it from any checkout that can fetch GitHub: the MacBook Air or
`deb-serv`. It can't run on the Mac worker until that machine has GitHub
credentials (see below).

User-visible PRs include a small immutable note in `backend/release-notes/`.
`ship.sh server --dry-run` previews eligible notes; successful deployment
publishes the catalog automatically after health checks, using the running
service SHA labels. The app groups updates into a dismissible hint with a
24-hour cooldown and keeps a manual history. Schema, partial deployments,
rollback, and internal-only PRs: `docs/RELEASE_NOTES.md`.

**Continuous deployment** is available but opt-in: native auto-merge + the
release workflow tag each merge `vX.Y.Z`, and `ops/auto-deploy.sh` (cron on
`deb-serv`) pulls and ships it via `ci/ship.sh server`, reusing the same
`deploy.lock`. The catalog now carries a `version` shown in "What's new".
Full setup and rationale: `docs/CD.md`.

**Server deploy** (`ci/ship.sh server`):

1. Refuses if the live checkout has *any* local change or untracked file,
   or if its HEAD isn't on GitHub (that would lose work).
2. Takes a lock (`~/.cache/dive-ci/deploy.lock`), then
   `git checkout --detach <sha>` in `~/dive-analyser`.
3. Picks the scope: only the frontend if nothing outside `frontend/` changed
   since the running backend's commit, only the backend if `frontend/` and
   `docker-compose.yml` are unchanged since the running frontend's commit,
   otherwise both (`--full` forces both).
4. Runs that commit's `ci/deploy.sh`: gate (fast + frontend tiers; fast only
   for a backend-only deploy), build images tagged `sha-<sha>`, recreate the
   backend and/or frontend containers, reload both nginx front doors (LAN `dive-analyser-nginx-1` and Funnel
   `dive-funnel-funnel-proxy-1`; they cache container IPs), and health-check
   over HTTPS. The server gate is skipped when GitHub's required `gate`
   check already passed on a commit with the *identical tree* (normally the
   merged PR's head; see `ci/gate-proof.py`). If the tree differs, the check
   is missing or red, or GitHub can't be reached, the server runs the gate as
   before. `--server-gate` forces it.
5. If anything fails, it restores the previous checkout. If the failure came
   after the containers were swapped, it also restores the previous images
   and recreates the backend: the backend bind-mounts `./backend`, so source
   and image have to roll back together. A gate or build failure restarts
   nothing.
6. Appends a line to `~/.cache/dive-ci/deploys.log`.

**Mac deploy** (`ci/ship.sh mac`):

1. Streams `git archive <sha> mac-agent` to the Mac over ssh. The Mac
   doesn't need GitHub access for this.
2. Backs up the current `code/` dir to
   `/Users/Shared/services/data/diveanalyzer/releases/code-backup-*.tgz`
   (keeps the last 5).
3. Syncs `mac-agent/src/` exactly and updates the top-level files. Leaves
   `logs/` and old local backups alone. Reinstalls dependencies only if
   `requirements.txt` changed.
4. Restarts the `com.diveanalyzer.agent` LaunchAgent and checks that the pid
   stays stable for 20 s. If not, it restores the backup and restarts again.
5. Writes `code/.deployed-sha` and appends to `releases/deploys.log`.

### Not automatic: `ship.sh` warns, you act

| Changed path | Action needed after a server deploy |
|---|---|
| `backend/migrations/*.sql` | Apply by hand against Postgres. There's no migration runner. |
| `docker-compose.yml`, `nginx/` | `docker-compose up -d nginx` (or `docker-compose exec nginx nginx -s reload`) |
| `ops/tailscale/` | `docker-compose -f ops/tailscale/docker-compose.yml -p dive-funnel up -d --force-recreate` |
| `mac-agent/` | `ci/ship.sh mac` |
| `ops/*.sh` | Nothing to do. Cron runs them from `~/dive-analyser`, so the server deploy updates them. |

### Rollback

Deploy the previous commit. It's still on `master`, so no extra flags:

```bash
ci/ship.sh status                       # or: ssh diveanalyzer-server tail ~/.cache/dive-ci/deploys.log
ci/ship.sh server --ref <previous-sha>
ci/ship.sh mac    --ref <previous-sha>
```

## Working on the Mac worker

The Mac has no working clone yet, and no GitHub credentials (the repo is
**private**). To work there, set up access once and clone fresh:

```bash
gh auth login                      # or add an SSH key to GitHub
git clone https://github.com/maxime-c16/dive-analyser.git ~/src/dive-analyser
```

(`~/dive-analyser` on the Mac is a legacy *bare* mirror of the server, not a
working copy. Don't use it.) Never edit
`/Users/Shared/services/data/diveanalyzer/code` directly.

`mac-agent/install.sh` and `mac-agent/upgrade.sh` target `~/.diveanalyzer`
(a personal install). They aren't used for `mac-media-01`, which lives under
`/Users/Shared/services/...`. Use `ci/ship.sh mac`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `live dir has local changes` | Someone edited the live checkout. Move the work to a worktree: tracked edits → commit on a branch there; untracked data → somewhere outside the repo or `.gitignore`. Then `git checkout -- . && git clean` *only what you moved*. |
| `another deploy holds ... deploy.lock` | Check no deploy is running (`ps`), then `rmdir` the lock. |
| `is not on origin/master` | Merge the PR, or `--allow-unmerged` for a deliberate branch deploy. |
| `this host cannot reach GitHub` | Server: `gh auth status`. Mac: no credentials, so run `ship.sh` from the laptop. |
| Gate fails with `npm ci` `EACCES` in `frontend/node_modules` | Files left root-owned by an old dev container: `sudo chown -R mcauchy:mcauchy ~/dive-analyser/frontend/node_modules` (fixed once on 2026-10-04). |
| `ship.sh status` shows image sha `unlabeled` | The image was built before `ci/deploy.sh` existed. The next deploy labels it. |

## Legacy: do not use

These came from the pre-GitHub era. They're kept only as backups:

- Mac bare repos: `~/dive-analyser` (mirror of the server) and
  `/Users/Shared/services/data/diveanalyzer-source-backups/dive-analyser-2026-09-05.git`
  (+ `sanitized-current.bundle`).
- MacBook Air `~/.perso/diveanalyzer-perception(.git)` and `~/.perso/diveanalyzer`.
- Branch `uiux-overhaul-pro-app`. It was the old "canonical" branch; `master`
  has superseded it.

## One-time migration (2026-10-04)

Already done. Recorded here so the state of each host can be explained:

- Server `~/dive-analyser`: remote `github` renamed to `origin`, and
  `mac-mirror` removed. Month-old untracked leftovers (landmark-pilot scripts,
  `D5_ANNOTATION_BATCH/frames`, two `runs/` dirs) moved to
  `~/dive-analyser-archive/live-dir-leftovers-2026-10-04/`. Five tracked files
  that had been deleted in the working tree were restored. `ops/tailscale/`
  (live Funnel proxy config) was committed to git.
- Mac: nothing changed. Its git copies are legacy bare mirrors, all of whose
  commits are on GitHub.
- Verified before migrating: every commit on the server and the Mac was
  already on GitHub except local branch `hurdle-identity-v2` (1 commit), which
  was pushed.

### Browser video uploads

The backend needs `ffmpeg`/`ffprobe` (included in its image) and a dedicated
B2 credential with write/read access to the selected media bucket:
`B2_UPLOAD_KEY_ID`, `B2_UPLOAD_KEY_SECRET`, `B2_UPLOAD_REGION`, optional
`B2_UPLOAD_ENDPOINT_URL`, and `B2_UPLOAD_ENVIRONMENT=prod` in production
(default: `dev`). Keep these in the deployment environment, never in Git.
On the server, store these values in `~/.config/diveanalyzer/browser-upload.env`
with mode `600`. `ci/ship.sh server` loads this file for deployment and rollback,
so secrets stay outside the live checkout. The existing playback credential remains read-only. Browser imports fail
without publishing a dive if B2 upload or full-byte verification fails.
Originals are registered in the existing media backbone; pinned local
originals, H.264 previews and posters live in the persistent media-cache volume.
Each clip is capped at 1 GB. No SQL migration is required.

### Deposit batches ("Récupérer mes plongeons")

Clips deposited for another account stay private + pending until the owner
accepts them. The deploy that ships this feature needs
`backend/migrations/add_deposit_batches.sql`:

0. **Before** `ci/ship.sh server`, apply the SQL by hand against Postgres
   (idempotent; the new backend reads the added tables and columns, so
   deploying first fails requests until it is applied). Backward compatible:
   the previous backend keeps working with the migrated schema.
   Admin confirmation for auto-ingested clips additionally needs
   `backend/migrations/add_batch_email_hold.sql` (same rule: before the deploy).
   With `INGEST_DEPOSITOR_EMAIL` set, every machine-ingested session for another
   owner parks one email per diver as `held`; an admin confirms it in
   Administration > Emails (Send / Send all / Skip), and cron then sends it.
   Admin browser deposits on behalf of someone are explicit, so they skip the hold.
1. `~/.config/diveanalyzer/email.env` (mode `600`, same pattern as
   `browser-upload.env`): `INGEST_DEPOSITOR_EMAIL` (operator account credited
   for mac-agent ingestion), `SMTP_HOST/PORT/USER/PASSWORD` (free Gmail SMTP
   maintainer account, 2FA + app password), `EMAIL_FROM`, `APP_PUBLIC_URL`
   (absolute public URL for email buttons), optional
   `BATCH_EMAIL_DELAY_MINUTES` (default 45). Sourced by `ci/ship.sh server`
   for the backend container and by `ops/send-batch-emails.sh` for cron.
   Empty `SMTP_HOST` disables sending (outbox stays pending, inbox + push
   unaffected).
2. Cron on deb-serv (runs from `~/dive-analyser`, like the other `ops/*.sh`):
   `*/15 * * * * /home/mcauchy/dive-analyser/ops/send-batch-emails.sh`.

### Calendar pilot (default off)

Calendar needs all four `add_calendar_*.sql` migrations in order **before**
the dependent backend, private persistent source/artifact storage, and an
explicitly installed/healthy alerts timer. `ship.sh` does not install the timer
or import club data. Server deployments and rollback source
`~/.config/diveanalyzer/calendar.env` (0600) for the existing `CALENDAR_ENABLED`
flag; Compose defaults false. A same-SHA activation requires `--force`
(dry-run first). Enabling is global to authenticated app users, while event
visibility remains authorization-filtered. The preparation release note is
admin-only and does not prove worker installation.

Review [pilot gates](design/calendar/PILOT_RELEASE_CHECKLIST.md) and
[exact rollout/backout commands](design/calendar/PILOT_ROLLOUT.md) before
activation. Keep the additive schema/data on app rollback; disable the timer
and feature first. No Mac service is required.

### Evaluation media rollout

See [the media playback runbook](MEDIA_PLAYBACK.md) for measurements, worker
concurrency, DNS validation, staged rollout, and rollback.

### Personal dive series

Apply `backend/migrations/add_dive_series.sql` **before** deploying the
backend and frontend for this feature. Startup does not create this table.
The calendar schema is optional for standalone sheets. No Mac service or
worker is required. Details: [series implementation](design/series/IMPLEMENTATION.md).

### Opt-in Photos cleanup

Post-ingest cleanup needs both the backend eligibility endpoint and the Mac
worker, plus explicit UI grants/Keychain setup for unattended operation. Keep
cleanup off during deployment; use dry-run first. No SQL migration is needed.
See [setup, activation and rollback](PHOTOS_CLEANUP_PERMISSIONS.md). Optional
automation dependencies and permissions are not installed by `ship.sh`.

### Synchro participants

Apply `backend/migrations/add_dive_sync_pairs.sql` before deploying the backend.
The private review import is separate and defaults to dry-run. Deploy Mac after
backend for the new cleanup revision checks. See [rollout](SYNC_PARTICIPANTS.md).

### Shared sessions (default off)

Spec and implementation: [SHARED_SESSIONS.md](features/SHARED_SESSIONS.md).

1. **Before** `ci/ship.sh server`, apply
   `backend/migrations/add_session_videos.sql` (idempotent, additive; needs
   `add_dive_sharing.sql`). The tables are migration-only: startup never
   creates them.
2. Create `~/.config/diveanalyzer/sessions.env` on deb-serv (mode `600`,
   loaded by `ci/ship.sh` for deploy and rollback, wired in
   `docker-compose.yml`):
   `SHARED_SESSIONS_ENABLED=true`, `SHARED_SESSIONS_OWNER_EMAIL` (Maxime's
   account), `SESSIONS_B2_KEY_ID` / `SESSIONS_B2_KEY_SECRET` (a **read-only**
   key — `listFiles`, `readFiles` — scoped to `diveanalyzer-sessions`; never
   the prefix-locked `B2_UPLOAD_*` media key), optional
   `SESSIONS_B2_REGION` (default `eu-central-003`), `SESSIONS_B2_EVENT_SECRET`
   (the rule's signing secret), `SESSIONS_TELEGRAM_BOT_TOKEN` /
   `SESSIONS_TELEGRAM_CHAT_ID` (same values as `/etc/dive-funnel-watchdog.env`;
   empty = no Telegram). `APP_PUBLIC_URL` (email.env) builds the links.
   A same-SHA activation needs `--force`.
3. Reload the Funnel proxy (new public route
   `/api/v1/session-videos/b2-events`):
   `docker-compose -f ops/tailscale/docker-compose.yml -p dive-funnel up -d --force-recreate`,
   then `python3 ops/tailscale/check_guest_routes.py https://dive-analyser.tail32dd14.ts.net`.
4. In the B2 console, bucket `diveanalyzer-sessions` → Event Notifications →
   new rule: event types `b2:ObjectCreated:*` (Upload, MultipartUpload, Copy),
   prefix `inbox/`, target
   `https://dive-analyser.tail32dd14.ts.net/api/v1/session-videos/b2-events`,
   with an HMAC-SHA256 signing secret equal to `SESSIONS_B2_EVENT_SECRET`.
   Use “Test rule” (expects 200). Without the rule, the 10-minute
   reconciliation still ingests every upload.
5. No Mac service, no timer: the reconciliation runs inside the backend.
   Rollback: set `SHARED_SESSIONS_ENABLED=false` and redeploy with `--force`;
   keep the tables.

### Shared-session calendar

After the calendar and shared-session migrations, apply
`backend/migrations/add_session_calendar.sql` before updating backend and
frontend. It preserves RSVP history, replaces global session-date uniqueness
with fallback-day uniqueness, and adds occurrence identity plus notification
progress. No Mac service or new timer/secrets are needed. Keep the schema/data
on backout; A's backend cannot safely handle multiple session rows per date.
See [PR C operations](features/SHARED_SESSIONS.md#pr-c--implementation-and-operations).
