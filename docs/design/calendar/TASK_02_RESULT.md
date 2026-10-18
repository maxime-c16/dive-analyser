# Task 02 result: calendar domain, permissions and read APIs

Status: implemented and committed locally on `t3code/calendar-domain` (base 9dc4682). Not pushed, not deployed, not activated. No live DB writes. Release notes: none. This is a backend foundation behind `CALENDAR_ENABLED=false` and has no user-visible behavior.

## What was added

| Layer | File |
|---|---|
| SQL migration (additive, idempotent, one transaction) | `backend/migrations/add_calendar_domain.sql` |
| SQLAlchemy models (16 tables, tagged `sql_migration_only`) | `backend/app/models/calendar.py` |
| Pydantic contracts | `backend/app/schemas/calendar.py` |
| Authorization contract + SQL policy/query builders | `backend/app/services/calendar_access.py` |
| Club/membership/group writes (flush-only, caller commits) | `backend/app/services/calendar_membership.py` |
| API router `/api/v1/calendar/...` | `backend/app/api/v1/calendar.py` |
| Signup club choice (both flows) | `backend/app/api/v1/auth.py`, `backend/app/services/diver_invites.py` (`before_commit` hook) |
| Feature flag `CALENDAR_ENABLED` (default false) | `backend/app/config.py` |
| `init_db` skips migration-only tables | `backend/app/database.py` |
| Tests (SQLite default, PostgreSQL opt-in) | `backend/tests/test_calendar_domain.py` |

Startup runs `Base.metadata.create_all`. Without the `sql_migration_only` exclusion, deploying this code would have silently created the calendar tables. A test checks that `init_db` creates none of them.

## Schema

| Table | Purpose / key constraints |
|---|---|
| `clubs` | slug unique, IANA timezone, `self_join_enabled`, archival (no delete). |
| `club_memberships` | One row per membership period. Role is member/coach/manager. `can_publish` and `can_assign_groups` are per-club coach grants. Status active/left/removed, and `ended_at` is NULL exactly when status is active. Source signup/admin_legacy/manager. **Partial unique: one active membership per (club, user).** User CASCADE, club RESTRICT. |
| `training_groups` | unique (club, slug); unique (id, club_id) to support composite FKs. |
| `training_group_memberships` | Effective-dated, `effective_to` exclusive. **Composite FKs (group_id, club_id) and (club_membership_id, club_id)**, so a cross-club pairing cannot be stored. Partial unique: one open assignment per (club, user). Check `to > from`. |
| `calendars` | kind club/group/personal/federal, with a check fixing the owner columns for each kind. Composite FK from group to its club. One club calendar per club and one calendar per group (partial unique indexes). |
| `calendar_subscriptions` | Following only. Grants nothing. |
| `calendar_events` | One canonical event with source calendar, organizer, type (training/camp/outing/competition/other), audience (group/club/community/invited) and status (draft/published/cancelled, with a `cancelled_at` check). Also venue, IANA tz, `recurrence_rule` (metadata only), `version`, and `scoring_competition_id` (optional, deliberately no FK). |
| `event_occurrences` | Stable `occurrence_key`, unique per event. Timed occurrences store UTC `starts_at`/`ends_at`. All-day occurrences store local `start_date`/`end_date` (exclusive end). A check forbids mixing the two forms. `window_start`/`window_end` (UTC) give one indexed range query for both forms. Status scheduled/cancelled. `filmed_session_id` links to `sessions` with SET NULL and grants no video access. `version`. |
| `event_invitations` | unique (event, invitee). pending/accepted/declined/revoked, with a `revoked_at` check. |
| `occurrence_interests` | PK (occurrence, user). State interested/maybe/declined. No capacity or reservation. |
| `occurrence_absence_reports` | PK (occurrence, user). Independent of interest. No free text, so no health data is collected. |
| `calendar_sources` | Source inventory: workbook/pdf_schedule/organizer_page/federation_page/manual. `parent_source_id` models links embedded in the workbook. Stores sha256 and a private `storage_ref`, never raw data. |
| `calendar_import_runs` | Import versions: source sha, parser version, previewed/applied/failed, summary. |
| `event_resources` | Typed links (official_info, registration, dive_sheets, results, club_chat, rules, other). Deadline kind (club_cutoff/official_entry/dive_sheet), `due_at`, edition label, verification date. Each row is owned by an event XOR a club. `restricted_to_club` keeps a chat invitation private even on a community event. |
| `calendar_source_mappings` | unique (source, target_type, external_key) → event/occurrence/resource (SET NULL). Holds `locally_overridden`, provenance JSON, and the last import run. |
| `calendar_change_log` | Versioned audit (created/published/updated/time_changed/venue_changed/cancelled/imported). It is the planned source for the future notification outbox. No worker exists and existing notification transactions are unchanged. |

## Authorization matrix (enforced in SQL before LIMIT; direct IDs return 404, identical to missing)

| Actor → sees | Own group cal/events | Other group (same club) | Club-audience | Community | Invited event | Drafts | Roster | Other members' groups |
|---|---|---|---|---|---|---|---|---|
| Assigned member | ✅ | ❌ 404 | ✅ | ✅ | only if invited (pending/accepted) | ❌ | ✅ names/roles | ❌ |
| Unassigned member | (“not assigned”, `group: null`) | ❌ | ✅ | ✅ | if invited | ❌ | ✅ | ❌ |
| Coach / manager (own club) | ✅ both groups | ✅ | ✅ | ✅ | if invited | publishers only | ✅ | ✅ |
| Staff of another club | ❌ | ❌ | ❌ | ✅ | if invited | ❌ | ❌ 404 | ❌ |
| Departed member | ❌ | ❌ | ❌ | ✅ | club invited-only invitations revoked on leave | ❌ | ❌ 404 | ❌ |
| App admin (non-member) | ❌ | ❌ | ❌ | ✅ | if invited | ❌ | ❌ | ❌ |
| Inactive account | 401 (session rejected); policy helpers also return no rows | | | | | | | |

Write contract (`calendar_access`). Publishing to club and group calendars requires a manager, or a coach the manager granted `can_publish`, in that club. A personal calendar can be written only by its owner. Federal calendars are written by app admins (curators). Group assignment requires a manager or a coach with `can_assign_groups`. Only app admins create clubs, link legacy accounts and appoint or demote managers. `is_admin` grants no club powers. Removing or demoting the last manager is refused with 409 `last_manager`. Roles and groups are always read from the database and never from the client. `ALLOWED_AUDIENCES` fixes which audiences each calendar kind may publish (for Task03).

## API

| Method & path | Who | Notes |
|---|---|---|
| `GET /api/v1/auth/signup-clubs` | public | Self-join clubs: id/name/short_name only. Lives under `/auth` because the v1-wide session dependency exempts only auth paths. |
| `POST /api/v1/auth/register`, `/register-invite` | public | Optional `club_id`. Validated before any account or invite is consumed. Creates an active `member` membership with `source=signup` in the same transaction, with no role and no group. If omitted, behavior is identical to before. |
| `GET /calendar/me` | member | Active clubs, membership, current group or `null`, `self_declared`. |
| `GET /calendar/calendars` | user | Visible calendars plus a `following` flag. |
| `GET /calendar/occurrences?from&to[&calendar_id][&limit][&cursor]` | user | Overlap with `[from,to)`. Window ≤100 days. limit 1–200 (default 100). Keyset cursor on (window_start, id). Returns only the caller's own interest/absence. |
| `GET /calendar/occurrences/{id}`, `GET /calendar/events/{id}` | user | Authorized detail plus filtered resources and own invitation. 404 otherwise. |
| `GET /calendar/clubs/{id}/members`, `/resources` | active member | App accounts only. Groups shown to staff only. |
| `POST /calendar/admin/clubs` | app admin | Also creates the club calendar. |
| `POST /calendar/admin/clubs/{id}/memberships` | app admin | Legacy association or manager appointment. 409 if already a member. 422 if the target is inactive. |
| `PATCH /calendar/clubs/{id}/memberships/{mid}` | manager (admin only for manager role) | Role and coach grants. Demoting to member clears the grants. |
| `POST /calendar/clubs/{id}/memberships/{mid}/end`, `POST /calendar/clubs/{id}/leave` | manager/admin, self | Keeps history, closes the open group assignment, revokes club invited-only invitations. |
| `POST /calendar/clubs/{id}/groups` | manager or admin | Also creates the group calendar. |
| `PUT /calendar/clubs/{id}/group-assignment` | manager or authorized coach | `{user_id, group_id|null, effective_from}`. A transfer ends the current row on the date the new one starts. Backdating before the current start returns 422. A cross-club group or non-member returns 422. |

All writes check Origin (403 for a foreign Origin). When disabled, every `/calendar` route and `signup-clubs` return 404 (anonymous callers get 401 first from the existing session boundary), and signup refuses `club_id` with 422 `club_unavailable`. If the flag is enabled before the migration is applied, routes return 503 `Calendar schema not installed`.

## Test evidence (18 Oct 2026)

Venv: `uv venv -p 3.12 /tmp/da-venv-cal && uv pip install -r backend/requirements.txt pytest httpx`.

| Command (from `backend/`) | Result |
|---|---|
| `python -m pytest tests/test_calendar_domain.py` (SQLite, FK pragma on) | **22 passed, 1 skipped** (PG parity test) |
| `CALENDAR_TEST_DATABASE_URL=postgresql://…/calendar_test_task02 python -m pytest tests/test_calendar_domain.py` | **23 passed** in 101 s |
| `python -m pytest tests/test_friend_access.py tests/test_diver_invites.py tests/test_p8_user_admin.py tests/test_admin_users_api.py tests/test_p5_auth_playback.py tests/test_direct_messages.py tests/test_member_dive_visibility.py tests/test_notifications.py` | **162 passed** (existing signup/invite/admin/auth regressions) |

PostgreSQL target: a disposable `postgres:16-alpine` container (same image as live) on deb-serv. It used tmpfs storage, was bound to `127.0.0.1:55432`, was reached through an SSH tunnel, and was removed afterwards. The live `dive-analyser-postgres-1` was not touched. For each test, the fixture drops and recreates the public schema, creates only the pre-calendar tables (closure of the auth/divers/sessions/invites tables), then applies `add_calendar_domain.sql` **twice** to show it is idempotent. The parity test compares, for every calendar table, columns, nullability, named indexes/uniques, check constraints and FK targets with `ON DELETE` rules against the models.

Covered: own group vs other group in list, calendar filter and direct detail. Coach sees both groups in their own club and nothing private in another club. Unassigned member. Signup self-join without elevation or group, for both flows, with a refused club leaving no account and no consumed invite. Independent signup. Admin legacy link, duplicate, inactive target, manager appointment. Admin is neither publisher nor private reader. No self-elevation. Last-manager guard. Effective-dated transfer, including a future-dated one checked with `on=tomorrow`. Leave and removal revoke access and keep history. Invitation grant and revocation. Following grants nothing. Restricted resources and club resources. Roster without group leakage. Window and limit bounds. Filtering before pagination (6 earlier private rows do not consume the page). Duplicate memberships, open assignments, interest, absence, invitations and occurrence keys. Cross-club composite FKs. Time-form checks. Pre-migration app: signup works, 404 when the flag is off, 503 when it is on. Origin guard. `init_db` exclusion.

## Rollout (not performed)

1. Deploy the code with `CALENDAR_ENABLED` unset (false). No schema prerequisite, and the existing signup is unchanged.
2. Apply the migration manually on the server (ship.sh does not apply SQL), after a backup:
   `docker exec -i dive-analyser-postgres-1 psql -U diving -d diving_analyzer_db -v ON_ERROR_STOP=1 < backend/migrations/add_calendar_domain.sql`
3. Create the club and appoint managers through the admin API (not done; no real members were changed). Set `self_join_enabled` only when the signup UI exists (Task03).
4. Set `CALENDAR_ENABLED=true` in the runtime `.env` and restart the backend. Activation stays off until Task03 and the pilot gate.

Rollback: set `CALENDAR_ENABLED=false` and restart. Keep the tables and rows for investigation. There is no down migration. An emergency drop would be `DROP TABLE` of the 16 tables in reverse dependency order, and only with explicit approval.

## Limits / not done

- Group access uses the **current** assignment. After a transfer, a member stops seeing the previous group's past sessions. The history rows are kept for audit and future attendance views.
- No DB exclusion constraint against overlapping closed assignment periods (that would need btree_gist). The service serializes on the open row (`FOR UPDATE`) and only ever splits it, so overlaps cannot arise through the API.
- Interest/absence/invitation write endpoints, event create/edit/cancel, subscriptions API, recurrence expansion, import service/CLI, notifications/outbox/worker and the signup UI are not built (Task03+). The change-log rows are not written yet because no event writes exist.
- `ALLOWED_AUDIENCES` and `can_publish_to_calendar` are defined and tested but are not yet called by any endpoint.
- Roster list is capped at 500 and the occurrence list in event detail at 200, with no pagination.
- `signup-clubs` lists club names publicly when enabled. This is acceptable for a selection list.

## Handoff for Task03

- Reuse `calendar_access.event_visible_clause` / `visible_occurrences` for every new read, export, search and notification eligibility check. Use `can_publish_to_calendar` + `ALLOWED_AUDIENCES` for event writes. Use `active_membership` for interest/absence (absence only for group/club training occurrences the user can see).
- Event writes: bump `calendar_events.version` / `event_occurrences.version` and insert `calendar_change_log` in the same transaction. Time and venue edits update the occurrence in place so interests (keyed by occurrence id) are retained. Cancel sets status and `cancelled_at`. Never delete.
- Import: create `calendar_sources` (workbook as parent, embedded links as children). Run validate → preview (`calendar_import_runs.status=previewed`) → apply in one transaction, upserting via `calendar_source_mappings(source_id, target_type, external_key)`. The stable training key excludes time and venue. Respect `locally_overridden`. Keep the private bundle out of Git.
- Frontend: signup club selector from `/api/v1/auth/signup-clubs` (self-declared wording), the “group not assigned” state from `/calendar/me`, and agenda via `/calendar/occurrences` with ≤100-day windows and cursor paging.
