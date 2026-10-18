# Task 04 — Recurrent schedules and camps

Status: implemented locally, default off (`CALENDAR_ENABLED=false`). Local commit only: no push, PR, deploy, live DB/schema write or Task05. Base 644553b (reviewed Task03). Real camp context: `KCPM_CAMP_SOURCE.md` (Présidence KCPM email “STAGE FEVRIER KCPM”, 17 Oct 2026).

## Contract

Migration `backend/migrations/add_calendar_task04.sql`, applied manually after `add_calendar_task03.sql` (additive, idempotent, one transaction): `calendar_event_recurrences` (ISO weekday bitmask, local start/end time, first/until date ≤400 days, `pattern_from`), `calendar_recurrence_exclusions` (durable skipped dates), `event_occurrences.series_date` + `detached`, `event_itinerary_items`. The schema gate now requires `calendar_recurrence_exclusions` (flag on without the migration → 503).

Weekly series (`backend/app/services/calendar_recurrence.py`): `POST /calendar/events` accepts `recurrence {weekdays, until_date, excluded_dates}`. The first session's local times are the pattern. All dates are materialized at save: at most 200 sessions, 400 days and 120 exclusions, with no rolling horizon and no worker. Generation uses Europe/Paris (event IANA) wall time, so 19:00 stays 19:00 across both clock changes. If any date falls in a DST gap/overlap, the whole pattern is refused with `dst_local_time`, listing the dates and suggesting exclusion or another time. Camps/all-day events cannot repeat.

Scoped edits: `POST /calendar/events/{id}/schedule/preview` → `{plan, plan_hash, summary}`; `POST …/schedule/apply` with the same body + `plan_hash`. Publisher rights and visibility come from the Task02/03 predicates (404 hidden, 403 non-publisher; Origin-checked).
- `one`: this session only (time, date, venue or cancel). The row becomes `detached`; later pattern edits keep it.
- `future`: the selected session and following ones (never before today).
- `all`: every upcoming session; past sessions remain history.
Regeneration pairs existing rows with new dates (same slot, then same ISO week). Moved rows keep their id, key, interest, absence reports and dive links. Leftover rows are cancelled, never deleted. New dates are created. Cancelled and individually edited rows are kept and occupy their slot, so regeneration neither resurrects cancellations nor overwrites edits. Removing an exclusion only restores dates that were never materialized. Apply locks the event and its occurrences and checks the event version (`stale_version`). It recomputes the plan and refuses `stale_preview` if anything other than response counts changed. Writes go to the change log in one transaction (per-occurrence `time_changed`/`venue_changed`/`cancelled`/`created` + event `updated`). The whole-event PATCH can no longer change a series' times.

Imported KCPM schedules remain the authoritative 116 explicit dates (`series_date` null, no pattern). `future`/`all` return `409 imported_series` with a plain explanation. Single-session changes/cancel remain and mark `locally_overridden`. No weekly rule is synthesized, holidays are not filled and the importer is unchanged.

Camps: one all-day multi-day occurrence = one whole-camp interest. The optional itinerary (≤20 informational blocks with day/time/venue, inside the camp dates) is not separately bookable. Shrinking the dates while blocks fall outside → 422. An optional external `registration_url` (resource kind `registration`) is shown with “registration and payment happen on the organizer’s site; interest is not a registration”. Occurrences expose inclusive `local_end_date`; month view shows the camp on every covered day (continuation marker), agenda keeps an ongoing camp, and windows overlap month boundaries. No capacity, waitlist, payment, attendance, youth or notification work was added.

Frontend: the create form has “Se répète chaque semaine” (weekday toggles, season end, excluded-date chips and a session estimate) and camp programme/registration fields. `ScheduleEditor` (`/calendar/o/:id/schedule`) offers plain-language FR/EN scope choices, previews moved/cancelled/created/kept dates with interested/maybe/absence counts, and applies. On stale data it reloads the version and keeps inputs. The detail page shows the series summary, the “changed individually” badge, the camp date range/day count and the programme. New controls use the existing `keepFocusOnPress`. The live run reproduced first-tap loss on the repeat checkbox after typing in a time field, and this fix corrected it.

## Validation evidence (18 Oct 2026)

- SQLite: `tests/test_calendar_task04.py` 11 passed (PG race + private-bundle cases skipped); calendar + signup/invite/admin/auth/messages/notifications regressions **214 passed, 6 skipped**.
- Disposable PostgreSQL 16: Task04 + migration parity + real bundle **14 passed**. This covers migrations applied twice (idempotence), the concurrent apply of one preview (one 200, one 409), spring/fall DST, same wall times, one/future/all, stale previews, moved IDs and retained responses, durable exclusions/cancellations without resurrection, bounds, permissions and imported refusal. Real-bundle regression `test_real_kcpm_116_dates_stay_exact_and_refuse_pattern_edits` passed on SQLite and PG: 116 keys/start times/status unchanged and a re-preview creates 0. Full PG calendar suites once at the end (Task02+03+04 with the real bundle, migrations applied twice per test): **58 passed** in 21m34s. This was slow because every test recreates the schema over a 60 ms SSH tunnel to a loaded host. pg_stat_activity showed active schema rebuilds, not lock waits.
- Frontend: typecheck clean; vitest **645 passed / 84 files**; mocked calendar Playwright **15 passed** (Task03 navigation/feature-off/first-tap cases unchanged); build private-data check PASS. Release-note validation passed.
- Live browser (built frontend :5174 + backend :8017 + disposable seeded DB with real 116-date import), `playwright.calendar-task04.config.ts` **5 passed**:
  1. Phone 390: the coach creates a weekly series with a holiday; the first tap saves while a field is focused; dates/times cross the clock change at 19:00.
  2. Phone member sets interest. Desktop coach previews “this and following” Tue→Wed (shows 1 interested, “1 responses stay attached”) and applies; the member sees the moved Wednesday session still marked interested.
  3. Two publishers (one live session per account): the older preview is refused with the stale message and inputs are kept.
  4. Imported KCPM session: only “this session”, with explanation.
  5. Phone coach enters the real February camp (19–21 Feb 2027, five blocks, INSEP/CAO, HelloAsso link). The date range shows 3 days; desktop month view shows it on 19/20/21; the member registers whole-camp interest.
  Screenshots: `/tmp/calendar-task04-live-shots/`. Chromium only; physical iPhone/VoiceOver not verified.
- Feature off: unchanged Task03 checks (router/navigation tests, backend 404 gate) pass.

Live-runner notes: the server keeps one live session per account, so use distinct accounts per concurrent page and close contexts after each case. Reseeding with a backend still running left an idle-in-transaction connection that blocked `DROP SCHEMA` and exhausted the dev pool. The 60 ms SSH tunnel also saturated the default 5+2 pool. The fix stops the backend, terminates the DB sessions, reseeds, then starts the backend with `DATABASE_POOL_SIZE=15 DATABASE_MAX_OVERFLOW=10` (local env only; no code/production change).

Commands: from `backend/`: `python -m pytest tests/test_calendar_task04.py` (add `CALENDAR_TEST_DATABASE_URL=postgresql://…/calendar_test_*` and `CALENDAR_IMPORT_BUNDLE=…/reports/calendar/kcpm-2026-2027/import-bundle.json` for PG/private cases). Live: seed a disposable DB (accounts admin/manager/coach/alice/bruno@dev.test, KCPM import, coach grants, groups), serve the build with `PREVIEW_PROXY_TARGET`, set backend `CORS_ALLOW_ORIGINS` to the preview origin, then `CALENDAR_LIVE_PASSWORD=… npx playwright test -c playwright.calendar-task04.config.ts`. The Task03 live config ignores this spec.

## Limits and remaining

- Weekly only (no interval/monthly), timed sessions only, no overnight sessions in a series, maximum 200 sessions/400 days. Moves pair within an ISO week; a cancelled session cannot be restored (create a separate event). Restricting “all” to upcoming sessions is a deliberate history choice.
- Pattern edits on imported schedules are refused, not converted. Corrections stay per session or via a reviewed re-import.
- Itinerary blocks are informational; no per-block interest/booking. The May 2027 camp is not entered (times unconfirmed). The camp was entered only in disposable test data; nothing was published for real.
- Change-log rows are ready for the Task05 outbox. No notifications/reminders (Task05), ICS/rollout/flag activation (Task06), capacity, payments, attendance or guardian support.
- Rollout: back up, apply the three migrations in order, keep the flag off until the pilot gate.

## Cleanup (done after the final PG run)

Stopped and verified: deb-serv container `caltask04-pg` removed (`docker ps -a` shows none; tmpfs data gone with it, including databases `calendar_test_task04`/`calendar_live_task04`), SSH tunnel 55436 closed, local backend 8017, preview 5174 and dev server 5173 stopped. Deleted `/tmp/caltask04-pgpw`, `/tmp/caltask04-live/` (seed script, test password, artifact copies, logs) and `/tmp/calendar-task04-live` (Playwright traces/error snapshots, which contained the disposable test password). Kept: `/tmp/calendar-task04-live-shots/` (7 calendar screenshots with no credentials). Private originals/bundle under `reports/calendar/kcpm-2026-2027/` and the Task03 persistent artifact copies are untouched. The live `dive-analyser-postgres-1` and the live checkouts were never accessed.

## Parent review correction

After cf5ecf4, parent review found that direct occurrence edits and scope-one previews could shrink a camp outside its saved itinerary, bypassing the event-edit guard. Both now validate the prospective date range before changing rows. Added regression covers both APIs and verifies dates stay unchanged after rejection. Supplemental SQLite Task04:12 passed,2 skipped(PG-only/private input); diff and release-note checks passed. Original58 PostgreSQL/645 frontend/5 live results apply to cf5ecf4; no frontend changes in this correction. Cleanup independently verified: disposable container absent, ports closed, temporary credentials removed. Physical iPhone/VoiceOver remains unverified.
