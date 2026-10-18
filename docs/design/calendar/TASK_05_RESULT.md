# Task 05 — Reliable calendar alerts

Status: implemented locally, default off (`CALENDAR_ENABLED=false`, worker not installed anywhere). Local commit only: no push, PR, deploy, live DB/schema write, cron or Task06. Base 56a9bb0 (Task04 cf5ecf4 + parent itinerary-bounds fix).

## Contract

Migration `backend/migrations/add_calendar_task05.sql`, applied manually after `add_calendar_task04.sql` (needs `notifications` from `add_notifications.sql`). Additive, idempotent, one transaction:
- `calendar_alert_outbox`: one row per event per writing transaction.
- `calendar_change_log.outbox_id`: nullable, `ON DELETE SET NULL`.
- `calendar_alert_deliveries`: one row per recipient alert. `delivery_key` is unique, and `notification_id` is unique so a delivery can own at most one inbox row.
- `calendar_worker_state`: leased singleton holding the heartbeat and counters.

The schema gate now requires `calendar_alert_deliveries`: with the flag on and this migration missing, `/calendar` answers 503. No existing table or column changes meaning. `notifications` is untouched. Calendar rows reuse it with generic titles.

**Outbox (write side).** `calendar_events.log_change` attaches every change-log row to `calendar_alerts.outbox_for(db, event)`. This is cached per root transaction, and a row discarded by a rolled-back savepoint is replaced. `invite()` records newly created or renewed invitees on the same row. All of this is flush-only inside the caller's transaction: the API's single commit stores the event write, its change log and its outbox together. A rollback or a refused write (409, 422) leaves no outbox row. The importer, recurrence edits and every Task03/04 path go through `log_change` unchanged.

**Transaction-aware inbox path.** `notification_service.stage()` adds and flushes an inbox row without committing, checking preferences or pushing. `create()` and `notify_owners_for_diver()` keep their self-committing contracts. Push uses the existing `push_service.fanout_for_rows`. A row may carry a prepared `_push_payload`; other rows are byte-identical.

**Alert rules.** Alerts are sent only for published events with upcoming occurrences. The actor never receives their own alert.

| Trigger | Recipients | Type (preference) | Default |
|---|---|---|---|
| Invitation (at invite, or at publish for invitations made while draft) | invitee | `calendar_invitation` | on |
| Time change, venue change, session or event cancellation | interested/maybe on the affected session, pending/accepted invitees, assigned group members (group training) or active members (club-wide training) | `calendar_change` | on |
| Same, for people who only follow the event | event followers | `calendar_follow` | on |
| New event published in a followed calendar (never from an import) | calendar followers | `calendar_follow` | on |
| Previous-day reminder at `CALENDAR_REMINDER_HOUR` (default 18:00, event timezone) | members who marked "Interested" | `calendar_reminder` | on |
| Previous-day reminder for every assigned group session | assigned members who opted in | `calendar_group_reminder` | **off** |

- **One alert per transaction.** A transaction produces at most one change or cancellation alert per recipient, listing up to 10 sessions plus a total. A series edit moving 20 sessions is therefore one alert, not 20.
- **Pending alerts are merged.** An older pending alert for the same event is merged into the newer one: kinds are combined, keeping the first old time and the latest new time. The older alert is marked `superseded`.
- **Ignored change kinds.** Title/description edits (`updated`), creations and imports (`created`, `imported`) send nothing.
- **Imports.** An imported correction notifies only the participants of the affected upcoming session. It never notifies calendar followers, and there is no global blast. The initial 116-date import produced zero deliveries.

**Group-session default (proposed and implemented).** Assigned group sessions are routine, two or three a week, and members are not asked to respond.
- **Changes and cancellations** of their group's upcoming sessions reach assigned members by default: training goes ahead without RSVP, so a cancellation must not be missed.
- **Day-before reminders** for every group session are opt-in (`calendar_group_reminder`, default off). A member who marked "Interested" gets the normal reminder.
- **Absences.** A reminder is suppressed if the member reported an absence for that session. No absence nags and no coach-side absence alerts in V1. Group assignment remains distinct from interest.

**Worker** (`scripts/calendar_alerts_worker.py run`, one bounded run; `app/services/calendar_alerts.run_once`):
1. **Overlapping-run exclusion.** A run first leases `calendar_worker_state` with a conditional UPDATE (lease 5 min). A concurrent run returns `busy`. A crashed run's lease expires and the next run resumes.
2. **Expand.** Pending outbox rows are claimed by row lease (conditional UPDATE, ascending ids, lease 2 min, batch ≤ 100, max 500). Each is expanded into deliveries (insert only if the key is absent) and marked `done` in one transaction.
   - Rows older than 7 days are closed without alerts. Alerts expire at `min(written + 7 days, end of the affected session)`.
   - A time change or cancellation also suppresses pending reminders of that session (`changed`).
3. **Plan reminders.** Sessions starting within 48 h whose reminder is due now get a delivery: due ≤ now < due + 6 h, and before the start.
   - The key includes the start time (`r<occ>:<start>:u<user>`).
   - Nothing older than the 6 h grace window is ever planned, so downtime never replays old reminders.
4. **Dispatch.** Due deliveries are claimed by row lease, then re-checked in this order:
   - expiry (`stale`)
   - inactive account
   - unpublished event
   - current Task02 visibility (`no_access`): covers membership or group loss and revoked invitations
   - for reminders: occurrence status, version and start (`cancelled` / `changed`), interest still "Interested" or still assigned, and no absence report
   - for invitations: still pending (`revoked` / `answered`)
   - preference (`pref_off`)

   Otherwise the inbox row is staged. A conditional update `pending → delivered` held by the lease owner attaches it, and both commit together. A lost race rolls the inbox row back.
5. **Push.** Web Push runs only after that commit and is best-effort (`push_state` `sent` / `skipped`). A push interrupted by a crash is retried for 15 minutes, then marked `expired`.
6. **Failures.** A failure rolls back, increments `attempts`, records the exception type only, and backs off 30 s × 2ⁿ (cap 1 h). After 6 attempts the row is `dead`. `requeue-dead` is an explicit operator action, and a requeued but stale alert is still suppressed. Exactly-once applies to the inbox only; external push can be duplicated in a crash window.

**Read side and privacy.**
- **Generic storage.** Inbox rows store only a generic title (e.g. "Calendar event changed"). `details` holds change kinds and old/new times, never free text.
- **Visible rows.** `/notifications` and `/notifications/{id}/read` resolve calendar rows for the reader at read time. The reader gets the current event title, timezone, venue, status, changes and the authorized deep link `/calendar/o/<occurrence>`, which itself 404s for anyone else.
- **Redacted rows.** When the reader can no longer see the session, or the feature or schema is off, the row becomes `{"title": "Calendar update", "calendar": {"redacted": true}}` with no link. Non-calendar rows are unchanged.
- **Push previews.** For anything other than a community event the push body is "Open the app to see the details." The title is the generic kind and the URL is the deep link.
- **Preferences API.** The calendar types are listed and accepted only when `CALENDAR_ENABLED`. With the flag off, GET returns exactly the eight previous types and PUT on a calendar type returns 422.

**Monitoring.**
- `GET /api/v1/calendar/admin/alerts/health` (app admin only, 403 otherwise) returns counts only and answers 503 until a worker run has succeeded within `CALENDAR_ALERTS_STALE_MINUTES` (default 10).
- Problems it reports: `schema_missing`, `worker_never_succeeded`, `worker_stale`, `*_dead_letters`, `feature_disabled`.
- Queue figures: status counts, `oldest_due_age_seconds`, `retrying`, `retry_attempts`, suppression reasons, and `last_success_at` / `last_error`.
- `status` in the CLI prints the same plus the dead-letter list and exits 2 when not ready.

**Frontend.**
- The inbox renders calendar alerts in FR/EN: kind · current title, "Déplacé : … → …" in the event timezone, new place, cancellation, "+N autres séances", and an "Ouvrir l’événement" link only when visible. A redacted row shows only the type label and an unavailability sentence.
- Account → Notifications shows an "Agenda" group of five toggles only when `features.calendar`. Its note says lock-screen previews stay generic.
- The service worker is unchanged: it already opens `payload.url`.

## Evidence (18 Oct 2026)

- **SQLite.**
  - `tests/test_calendar_task05.py`: 17 passed, 2 skipped (PostgreSQL-only concurrency and private bundle).
  - Full backend `python -m pytest tests/ -m "not performance"`: 1119 passed, 17 skipped, 2 failed. The two failures are `test_browser_upload.py::test_ten_bit_video_becomes_browser_compatible_sdr[smpte2084|arib-std-b67]`: this Mac's Homebrew ffmpeg has no `zscale` filter (`ffmpeg -filters | grep -c zscale` → 0). They are unrelated to this change.
- **Disposable PostgreSQL 16** (deb-serv `postgres:16-alpine` on tmpfs, SSH tunnel):
  - Task05 file: 16 passed, 1 skipped (SQLite-only schema-missing case). This includes the real-bundle test (116 dates, 0 deliveries, unchanged, re-preview creates 0).
  - Two dispatchers on the same deliveries, bypassing the run lease: each delivery key delivered once, inbox rows = delivered rows. Two full runs started together: one run lease or nothing left. Rerun 3/3 green.
  - Migration/model parity passed with the new tables and column. Every test applies all four migrations twice (idempotence).
  - Full calendar suites (Task02+03+04+05 with the real bundle, `tests/test_calendar_domain.py tests/test_calendar_task03.py tests/test_calendar_task04.py tests/test_calendar_task05.py`) run once at the end: **77 passed, 1 skipped** (SQLite-only schema-missing case) in 10m19s.
- **Requirements covered** (`tests/test_calendar_task05.py`):

| Requirement | Covered by |
|---|---|
| Rollback / refused write → no outbox row | outbox atomicity case |
| One inbox row per delivery key | rerun gives 0 new rows and keys stay unique; PG race case |
| Worker restart and retry/backoff | dead run lease → `busy` → resumes after expiry; one failure → backoff 30 s → delivered |
| Dead letters | permanent failure → `dead` after 6 → health problem, dead-letter list, requeue |
| Move/cancel invalidate reminders | planned reminders suppressed `changed`; the new slot gets exactly one reminder; the cancelled one none |
| No replay after downtime | nothing planned past the grace window; outbox older than 7 days announced nothing |
| Revoked access | revoked invitation → `no_access`; club membership ended between expansion and dispatch → `no_access`, and the delivered row is redacted at read time |
| Preferences | `pref_off`; group reminder opt-in; absence suppression; preferences API gated by flag |
| Deep link authorization | link 200 for recipient, 404 for others; private event → generic push body |
| Imports never blast followers | import case |
| Feature off unchanged | worker `disabled`; calendar rows redacted; legacy preferences |
| Health | 503 → 200 → stale |
| Missing schema | `schema_missing` |

- **Frontend.**
  - Typecheck clean; vitest **648 passed / 84 files**. New cases: calendar change rendering in the event timezone with deep link, redacted row, calendar toggles only with the feature.
  - Mocked calendar Playwright **15 passed**; navigation Playwright **52 passed**.
  - Release-note validation and `git diff --check` clean.
- **Live browser** (built frontend :5174 + backend :8017 on a disposable seeded database, the seed running the real write paths and the worker), `playwright.calendar-task05.config.ts` **4 passed**:
  1. Phone 390: alice's inbox shows "Événement modifié · Entraînement Débutants — Déplacé : mer. 21 oct., 19:00 → 20:00 · Nouveau lieu : Piscine Maurice Thorez". Tapping "Ouvrir l’événement" opens the session detail.
  2. Phone: una's revoked invitation shows only "Cette notification d’agenda ne vous est plus accessible.", no title and no link. The guessed URL shows nothing.
  3. Desktop: the Agenda section lists the five toggles with their defaults. Group reminder enabled and persisted after reload.
  4. Desktop: the deep link works with a pointer.

  Screenshots are in `/tmp/calendar-task05-live-shots/`. Chromium only; physical iPhone/VoiceOver not verified.

**Commands.** From `backend/`:
- `python -m pytest tests/test_calendar_task05.py`.
- For the PostgreSQL and private cases, add `CALENDAR_TEST_DATABASE_URL=postgresql://…/calendar_test_*` and `CALENDAR_IMPORT_BUNDLE=…/reports/calendar/kcpm-2026-2027/import-bundle.json`. The full PostgreSQL calendar run uses `tests/test_calendar_domain.py tests/test_calendar_task03.py tests/test_calendar_task04.py tests/test_calendar_task05.py`.
- Live: seed a `calendar_live_*` database with the four migrations, accounts and alerts produced by the worker. Run the backend with `CALENDAR_ENABLED=true USER_AUTH_ENABLED=true AUTH_COOKIE_SECURE=false CORS_ALLOW_ORIGINS=http://127.0.0.1:5174 DATABASE_POOL_SIZE=15 DATABASE_MAX_OVERFLOW=10` (startup `create_all` skipped by a local launcher, because the tables come from the seed). Serve the build with `PREVIEW_PROXY_TARGET`, then `CALENDAR_LIVE_PASSWORD=… npx playwright test -c playwright.calendar-task05.config.ts`.
- The Task03 live config now ignores the Task04 and Task05 specs.

## Worker runbook (Task06 activation; nothing installed here)

1. **Back up and migrate.** Back up the database, then apply the migrations in order: `add_calendar_domain` → `task03` → `task04` → `task05`. Re-running is safe.
2. **Deploy the backend.** The flag stays off. With the flag off, `run` prints `{"status": "disabled"}` and touches nothing.
3. **Install the schedule.** This is an explicit operational action; `ci/ship.sh` does not do it. Every minute, inside the backend container:
   `docker compose exec -T backend python scripts/calendar_alerts_worker.py run` (cron or systemd timer on deb-serv).
   - Each run is bounded (≤ 100 rows per phase by default) and safe to overlap.
   - Output is one JSON line of counts. Exit code 1 means failure; 2 means schema missing.
4. **Verify.** `python scripts/calendar_alerts_worker.py status` must report `ready=True worker=ok`. The admin endpoint `/api/v1/calendar/admin/alerts/health` must return 200. Watch `oldest_due_age_seconds`, `retrying` and dead letters.
5. **Dead letters.** Inspect `status --json` (exception type only), fix the cause, then run `requeue-dead --table delivery|outbox [--id N]`. Stale alerts will still be suppressed, not replayed.
6. **Rollback.** Remove the schedule and set `CALENDAR_ENABLED=false`. Keep every row; there is no down migration. Calendar inbox rows then read as redacted. Pending rows older than 7 days are never announced after re-enabling, and reminders past their grace window are never planned.
7. **VAPID.** Push needs VAPID configured, as for existing push. Without it, the inbox is unaffected and `push_state=skipped`.

## Limits

- **Exactly-once.** The inbox is exactly-once per delivery key. Web Push is at-least-once within a crash window and best-effort overall. There is no email (no V1 promise).
- **Language.** Push text is English and generic: no stored user locale, matching existing pushes. In-app rendering is FR/EN.
- **Reminders.** One configurable hour (`CALENDAR_REMINDER_HOUR`), not per user. Reminders cover sessions starting within 48 h, planned at most 500 sessions per run.
- **Delivery limits.**
  - Recipients per alert are capped at 2000, and an alert lists at most 10 sessions.
  - Interest removed after an alert was queued does not cancel a change alert. Reminders do re-check interest.
  - Title/description edits and audience changes send nothing. Audience narrowing is handled by visibility suppression.
- **Retention.** Delivered and suppressed rows are kept; there is no pruning yet. Personal data in deliveries is limited to user ids and change times. Redaction happens at read time; stored generic inbox rows remain until a retention policy exists.
- **Redacted rows** still show the type label (e.g. "Invitation agenda") but no event detail.
- **Health endpoint** is admin-only and requires the flag on. Before activation use the CLI `status`.
- **Not verified:** physical iPhone/VoiceOver. Real push delivery was not exercised: the sender was injected in tests and VAPID is unset locally.

## Remaining for Task06

Feature flag rollout and pilot enablement, one-off ICS export, installing and monitoring the worker schedule on deb-serv (operational acceptance gate), applying the four migrations in production with backup, smoke tests and rollback drill, physical iPhone check, wider release notes. Reliable reminders must not be announced before the worker gate is verified.

## Cleanup

Done and verified after the final PostgreSQL run:
- deb-serv container `caltask05-pg` stopped (`--rm`, tmpfs): `docker ps -a` lists no `caltask05-pg`. Its databases `calendar_test_task05` and `calendar_live_task05` went with it. `dive-analyser-postgres-1` was only listed by name, never accessed.
- SSH tunnel 55437 closed (no process left). Local backend 8017, preview 5174 and dev server 5173 stopped (no listeners).
- Deleted `/tmp/caltask05-pgpw` (DB password), `/tmp/caltask05-live/` (seed, launcher, test password, logs), `/tmp/calendar-task05-live` (Playwright traces/error context), `/tmp/calendar-task03-tests` and the temporary logs.
- Deleted this worktree's ignored copy `reports/calendar/kcpm-2026-2027/`. The private originals in the `calendar-recurrence` worktree are untouched.
- Kept `/tmp/calendar-task05-live-shots/`: 5 screenshots, no credentials.
- Live checkouts and the live database were never accessed.
