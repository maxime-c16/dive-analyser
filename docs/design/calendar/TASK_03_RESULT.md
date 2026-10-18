# Task 03 — Working calendar and KCPM import

Status: implemented locally, default off; parent took over after user requested stopping the Opus thread to conserve tokens. No push, PR, migration on live DB or deployment.

## Delivered

Production React calendar replaces the development prototype: flag-driven five-icon navigation, agenda/month/date navigation and detail routes, URL filters/back behavior, FR/EN, create/edit/cancel, existing-account invitations/revocation, event/calendar follows, interest/maybe/declined, independent absence reporting, own-dive links, club-account roster/group assignment/coach grants/removal/leave. Both signup flows offer optional self-declared club selection. Membership does not imply group assignment or elevated permissions.

Backend writes reuse the Task02 visibility/publishing predicates. Event/occurrence edits lock rows and check expected versions (409); creates accept actor-scoped idempotency keys including concurrent retry recovery. Cancellation preserves history and responses. Time/venue changes preserve responses. Changes are logged transactionally; no notification worker or reminder delivery is implemented. Declined invitations retain read access until revoked so invitees can change their minds. Dive links are private to the linking account and do not grant media access.

Migration: `backend/migrations/add_calendar_task03.sql`, after `add_calendar_domain.sql`. Adds event follows, idempotency keys, private dive links and import review status. Calendar schema readiness includes Task03 tables. Keep CALENDAR_ENABLED=false until the later pilot gate. Feature off preserves four labelled mobile tabs, redirects /calendar to Library, returns calendar API 404 and hides the signup club selector (verified against real backend).

## Reviewed import

`backend/scripts/import_calendar_bundle.py`: explicit database URL required, validate -> preview with plan hash/batch -> apply transaction; review/resolve commands. `prepare_calendar_sources.py` is the reproducible source reader. No source fetching/crawling runs.

Supplied PDFs import exactly 58+58 training dates. Source keys exclude time/venue; responses and IDs survive corrections. Missing dates are flagged for review, never silently cancelled. Local overrides survive; source acceptance requires review. Parent correction locks imported events/occurrences before recomputing the reviewed plan, preventing a stale snapshot from overwriting a concurrent manual edit.

Real isolated PostgreSQL import evidence: first run created 116 occurrences, 11 unpublished competition drafts, 29 historical/review mappings, 14 club resources and 32 upstream link inventory records. Second run created/updated nothing. Competition candidates remain unpublished; malformed/undated rows stay in review. Private WhatsApp links are club resources, excluded from crawls and production bundles. Source dates are initial provenance, not verified live feeds.

Private originals/bundle remain ignored at `reports/calendar/kcpm-2026-2027/`. Content-addressed artifact copies are stored at `/Users/maximecauchy/.dive-analyser-private/calendar-artifacts/` (files0600), referenced in DB by calendar-artifacts:<hash path>. Before production import, copy these artifacts/bundle securely to private persistent server storage, set --artifact-dir explicitly, back up DB and review a fresh target-specific plan; Mac paths are not production storage. Disposable development data is not a production import.

## Validation evidence

Opus completed before interruption: PostgreSQL calendar suites44 passed (including concurrent create/manager changes, migration parity, real bundle exactness/import twice); frontend643 tests across84 files, typecheck, mocked calendar15 cases, navigation26 cases;5 real multi-account browser flows against built frontend+isolated backend. Browser coverage includes group isolation, grants, unassigned state, interest/absence, invitations, retained responses, stale edits, cancellation, dive linking and signup. Feature-off live checks pass. Screenshot evidence: /tmp/calendar-task03-live-shots/. Browser runner is Chromium; physical iPhone/VoiceOver remains unverified.

The live test initially suffered dev-server/module loading and tunnel latency issues. Final successful run used built frontend and a freshly seeded disposable DB. Mobile first-tap Save/Invite loss was reproduced and corrected in calendar action buttons without changing shell keyboard policy; tests use direct first taps. Stale-version reload disables saving while loading and retains inputs. Test accounts/passwords are only in temporary local files, never git.

Parent validation: SQLite calendar+signup/invitation105 passed/3 PostgreSQL skips, followed by Task03 with real bundle19 passed/1 PG skip after import-lock fix and regression addition. PostgreSQL supplemental import checks and final cleanup are recorded below.

## Remaining and operational limits

No capacity/waitlists, actual attendance, recurrence editing (Task04), notification delivery/reminders (Task05), rollout/ICS (Task06), youth/guardian support or automatic source sync. Initial club creation/manager appointment/legacy association retain the existing administrator API; club page handles member-level administration. Import review is operator CLI, not a manager review screen. Source artifacts need production persistence/backup at rollout. Calendar remains disabled and must not be announced as a public feature; the included release note is admin-only preparation status.

The importer does not fetch upstream links and deliberately leaves ambiguous competition corrections for reviewed reconciliation. No automatic date/group-key move reconciliation. Roster/dive result limits inherited from bounded APIs remain. No claim of physical device validation or reliable alerts.

## Parent final checks and cleanup

After the import-lock correction: Task03 SQLite19 passed/1 PG-only skip; PostgreSQL supplemental import/apply suite5 passed (including real116-date bundle and stale-preview refusal); frontend typecheck and production private-data exclusion check passed. Release-note schema validation and git diff --check passed. An initial added regression assertion used a detached ORM object's id after fixture teardown; saving its integer id before the request corrected the test, and both reruns passed.

Parent inspected migration, write authorization paths, source conflict handling, production gate and mobile screenshot. Original44 PostgreSQL and643 frontend results predate only the parent import-lock change; affected importer cases were rerun as above. No frontend changes after the recorded full browser runs.

Stopped local dev backend8017, Vite5173, built preview5174, disposable caltask03-pg container and SSH tunnel55433. These preview URLs are no longer live. Private source originals and persistent artifact copies retained; temporary evidence remains under /tmp. Opus thread confirmed interrupted at the user's request; parent monitor disabled. No Task04 or additional agents started.
