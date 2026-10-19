# Club administration

Administration → Clubs is available to app administrators even when the member
calendar is closed. Club managers still use the member club page for their own
club; they do not gain access to this application administration screen.

The administrator can create a club, opt in to self-declared affiliation at
signup, appoint its first manager, attach existing app accounts, create training
groups, change roles and coach permissions, and assign groups with an effective
date. Last-manager protection and assignment history remain enforced. Member
pages have keyset pagination; account search is capped at 20 results.

Batch actions are first-class: select individual members or the current page
(up to100), then assign a group/effective date, set a role/coach permissions or
remove the selection. Changing pages clears the selection; hidden pages are
never included. The confirmation names the action, target and count. Existing
accounts can be selected across multiple bounded searches and attached in one
batch (up to100). Every batch is one transaction, uses the club lock, validates
all target memberships belong to this club, and retains last-manager checks.
An error refuses the whole batch; no partial-success guessing or repeated
per-account browser requests. A failed action keeps the selection for correction.
Account search excludes users already attached to the club and deactivated
accounts, so selecting a whole result page does not routinely include duplicates.

## Deployment prerequisites

Apply `backend/migrations/add_calendar_admin.sql` after the four calendar
migrations, before deploying. It is additive/idempotent. It inserts a singleton
with a NULL launch switch, preserving the existing CALENDAR_ENABLED default.
Startup does not create this table. Missing migration returns 503 on the
administration endpoints; it does not expose member calendar APIs.

Compose adds a private backend-only bind mount:
`~/.local/share/diveanalyzer/calendar-private` → `/app/calendar-private`.
Create it with mode 0700 (files 0600), accessible to the backend container user.
Never stage private source documents under media/cache: nginx serves that
volume. Back up calendar-private alongside the database. No nginx mount is
added. Local development can set CALENDAR_PRIVATE_ROOT to another private dir.

Sources are prepared with the existing source reader, reviewed, then staged as
`inbox/<identifier>/bundle.json` plus `inbox/<identifier>/sources/<original-name>`.
The identifier is lowercase letters/digits/hyphens, max64. Stage at most100
bundles. The UI cannot select a filesystem path or fetch arbitrary URLs. It
requires existing target groups and an explicit season-start date. Preview
shows creates/updates/conflicts/missing rows and the affected sessions; apply
requires its persisted batch/hash and rechecks the source and database. A
changed plan requires another preview. Competitions remain unpublished drafts.
Attachments are preserved content-addressed in `artifacts/`. Initial staging is
an operator action; this screen does not parse arbitrary PDF/Excel uploads.

## Opening and pausing

Once an administrator sets the launch switch, the database singleton is the
authority shared by member API gates, auth features/signup, notification
preferences and the worker. The environment variable is only the legacy
default while that switch is NULL. Changing calendar.env does **not** override
an explicit UI choice. No backend recreation is required for UI opening/pausing.
Other already-open browser tabs refresh their auth features on reload.

Install the existing systemd timer separately. While disabled, the scheduled
worker only records a schema observation in the launch singleton: it never
plans, dispatches or sends calendar notifications. CLI status exits successfully
in recent disabled standby; HTTP alert readiness stays false. Two observations
at least45seconds apart and less than15minutes old are required for launch.
They do not prove timer installation: the admin must separately attest actual
installation and two scheduled runs. Launch also requires a manager, groups,
published sessions and no active plain member without a current group in the
selected pilot club, no dead letters, and explicit source/roles/device/retention
checks. Tests on physical iPhone/VoiceOver/calendar clients are human checks,
never inferred from automated tests.

The switch is global, clearly stated in the UI: all authenticated users gain
the Calendar tab; club/group/event authorization still limits actual content.
Activation may start eligible notifications. Closing always works without
readiness checks, retains data, hides member endpoints before authentication,
and suppresses subsequent sends; a send already in flight may finish.
Actions are audited without credentials or source attachment contents.

Emergency pause if the UI is inaccessible, from the operator's DB connection:
`UPDATE calendar_launch_control SET enabled=false WHERE id=1;`
Then stop the timer if required. Rolling back to pre-admin code reverts to
the CALENDAR_ENABLED environment flag: explicitly keep that false before any
rollback. Additive tables and imported data are retained.

No live rollout, source staging, memberships, timer installation, notifications
or calendar activation are performed by developing this feature.
