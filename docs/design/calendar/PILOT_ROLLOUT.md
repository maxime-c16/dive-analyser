# Calendar operational handoff

Commands are for the parent/operator **after release authorization**. This implementation thread did not deploy, install a timer, change live env/data/membership, or send notifications. Follow `docs/REPO_WORKFLOW.md`; never edit the live checkout. Shell examples run on deb-serv as mcauchy from an approved staged GitHub checkout unless stated. Resolve `<merged-sha>`/`<previous-sha>` from reviewed release inputs, not this worktree's unpushed branch.

## Backup, migration and storage

Use the existing Compose project and runtime DB identity (examples use the repository defaults; substitute the deployed identity without printing credentials). Disable calendar and stop its timer before maintenance. Keep a private backup directory outside Git, mode0700:

```bash
backup="$HOME/.local/share/diveanalyzer/calendar-backups/$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 700 "$backup"
cd "$HOME/dive-analyser"
umask 077
docker-compose exec -T postgres pg_dump -U diving -d diving_analyzer_db -Fc > "$backup/database.dump"
tar -czf "$backup/calendar-sources.tgz" -C "$HOME/.local/share/diveanalyzer" calendar-sources calendar-artifacts
```

Back up existing artifacts before overwriting any staged input; on first import, archive the staged bundle/original attachments instead. `pg_dump` is consistent without stopping PostgreSQL; retain backup checksum/off-host backup per operator policy. A DB dump does not contain the private files referenced by `calendar_sources.storage_ref`.

Stage a GitHub archive of the approved commit outside the live checkout. From that staging directory, before deployment, apply in order (all four are additive/idempotent):

```bash
for migration in add_calendar_domain add_calendar_task03 add_calendar_task04 add_calendar_task05; do
  docker-compose -f "$HOME/dive-analyser/docker-compose.yml" exec -T postgres \
    psql -X -v ON_ERROR_STOP=1 -U diving -d diving_analyzer_db < "backend/migrations/$migration.sql"
done
```

Restore drill: create a **disposable PostgreSQL16 instance**, `createdb` a new empty DB, `pg_restore --exit-on-error -d <disposable-db> database.dump`; restore the artifact archive into a separate private directory, verify SHA256 against DB metadata, reapply migrations twice, compare import keys/start instants/status + camp itinerary, run flag-off/worker health checks. Never test restoration on the live DB. Task06 performed this against its own seeded disposable data; production backup restoration is still a release gate.

Private source inputs now exist locally at ignored `reports/calendar/kcpm-2026-2027/`; preserve originals. Persistent content-addressed copies: `~/.dive-analyser-private/calendar-artifacts-task06/` (alongside earlier Task03 copies). Target storage recommendation: `$HOME/.local/share/diveanalyzer/calendar-sources/kcpm-2026-2027/` and `calendar-artifacts/`, directories0700/files0600. Copy securely only after authorization; do not put them in Git, frontend assets, public media or the release note. DB storage refs are relative `calendar-artifacts:<hash path>`; `--artifact-dir` must point to the backed-up target directory, not a Mac path.

Run importer from approved backend environment with target DATABASE_URL loaded privately (no xtrace). Preview writes source/import metadata and copies artifacts, so this is a real data operation requiring the parent's authorization:

```bash
python scripts/import_calendar_bundle.py validate --bundle "$bundle"
python scripts/import_calendar_bundle.py preview --bundle "$bundle" --database-url "$DATABASE_URL" \
  --club kcpm --group beginners=groupe-a:Débutants --group advanced=groupe-b:Confirmés \
  --artifact-dir "$artifact_dir" --plan-out "$private_plan"
# Existing club/groups must match approved target mapping. Do not create a second club.
python scripts/import_calendar_bundle.py apply --bundle "$bundle" --database-url "$DATABASE_URL" \
  --club kcpm --group beginners=groupe-a:Débutants --group advanced=groupe-b:Confirmés \
  --artifact-dir "$artifact_dir" --plan-hash <reviewed-target-hash> --batch <reviewed-target-batch>
python scripts/import_calendar_bundle.py review --database-url "$DATABASE_URL" --club kcpm
# Repeat preview: create=0/update=0 for unchanged source; inspect review/conflicts.
```

Set `bundle`, `artifact_dir`, `private_plan` to the above private target paths. Review the target plan and account/group IDs; hashes/batches from disposable databases are invalid rollout inputs. Exactly116 explicit training dates; no synthesized weekly dates. Candidate competitions remain drafts/review until official source verification. The workbook's private links stay club-only. February camp is a separate whole-camp event with five blocks from `KCPM_CAMP_SOURCE.md`; May block times remain unknown.

## Deploy and activate

`ci/ship.sh` now sources `$HOME/.config/diveanalyzer/calendar.env` on the server before Compose, including rollback. The existing `CALENDAR_ENABLED` is the sole feature switch. Its Compose default is false. Parent creates this private runtime file (0600) with `CALENDAR_ENABLED=false`; no production file was written here. Do not change production pool tuning for test tunnel latency.

Deploy approved merged commit via ship.sh dry-run then normal server deploy; verify the feature-off smoke before enabling. The SQL migrations must already be present. Both frontend and backend are required, not the Mac media agent. No additional queue service; PostgreSQL outbox and one-shot backend worker are used. The immutable note is admin preparation wording because catalog eligibility cannot prove an installed timer. A public launch note must follow actual operational acceptance.

After review, parent changes calendar.env to `CALENDAR_ENABLED=true` and uses `ci/ship.sh server --ref <merged-sha> --force` (dry-run first) to recreate the backend with the runtime flag. `--force` is required when the same SHA is already deployed; merely editing the env file does not change a running container. This exposes Calendar globally to authenticated users, with server authorization still limiting data. Install the timer before this activation; its health check will be non-ready while disabled. Do not invite pilot users until the scheduled-worker gate succeeds.

## Timer installation, health and removal

Supplied files are templates for the documented deb-serv paths/user. Docker access must already work for mcauchy. Installation is explicit and **not performed here**:

```bash
sudo install -m 644 ops/systemd/dive-calendar-alerts.service /etc/systemd/system/
sudo install -m 644 ops/systemd/dive-calendar-alerts.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now dive-calendar-alerts.timer
systemctl list-timers dive-calendar-alerts.timer
journalctl -u dive-calendar-alerts.service --since '-10 minutes' --no-pager
# After activation: wait for two scheduled runs (roughly 2 minutes), inspect both.
systemctl show dive-calendar-alerts.service -p Result -p ExecMainStatus
cd "$HOME/dive-analyser"
docker-compose exec -T backend python scripts/calendar_alerts_worker.py status --json
```

`ops/calendar-alerts.sh` runs `run` then `status --json`, propagating failures. It supports Docker Compose v2 or legacy docker-compose, uses the running container's env and never installs anything. Worker leases bound overlaps; the timer does not replay missed ticks. `TimeoutStartSec=90` bounds hung calls; expired leases recover on later runs. Health requires a success within10 minutes, no dead letters and a ready schema; inspect oldest due age, attempts/retry counts and suppression reasons. HTTP equivalent: authenticated app-admin `GET /api/v1/calendar/admin/alerts/health` must return200; non-admin403, flag off404, missing schema503. Stale heartbeat alone cannot prove timer installation, hence two actual scheduled runs are required.

Failure: inspect journal/status, repair cause; only then explicitly `requeue-dead --table delivery|outbox [--id N]` inside backend. Old reminders/access/preference-ineligible pushes remain suppressed, including retries from reviewed6bbc652. Inbox is durable; external push is best effort and may duplicate in a crash window. No calendar emails. Group reminders are opt-in, assigned-group changes/cancellations on. VAPID is existing infrastructure; do not test real sends without separate recipient authorization.

Backout (parent authorized operations):

```bash
sudo systemctl disable --now dive-calendar-alerts.timer
sudo systemctl stop dive-calendar-alerts.service
sudo rm /etc/systemd/system/dive-calendar-alerts.timer /etc/systemd/system/dive-calendar-alerts.service
sudo systemctl daemon-reload
sudo systemctl reset-failed
# Set calendar.env CALENDAR_ENABLED=false, then:
ci/ship.sh server --ref <previous-sha> --dry-run
ci/ship.sh server --ref <previous-sha> --force
```

Keep additive schema and data; do not run a down migration or restore over live data for an application rollback. Verify four mobile tabs, signup selector absent, calendar/API deep link unavailable, redacted calendar inbox rows and CLI `run` disabled on a calendar-capable rollback build. An older pre-calendar build has no calendar CLI; the removed timer must remain removed. No unauthorized recipient or media exposure. Re-enable only after the same gates; expired jobs are suppressed, not replayed. Restore DB/files only under a separate incident recovery decision.

### Scheduled worker network budget

The CLI commits inbox batches independently and attempts one recipient push fan-out per run (oldest first). Pending push attempts expire after15 minutes; inbox rows remain available even under push backlog. The service timeout is600s, row lease10min, run lease12min and default stale-worker threshold15min. Monitor queue age and push expiry during the adult pilot; do not describe Web Push as guaranteed. The service/timer do not install themselves.
