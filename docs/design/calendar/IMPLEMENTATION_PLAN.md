# Community calendar — implementation plan

Status: proposed implementation, 18 October 2026. No application code deployed. Based on the local checkout, not a live-production audit. Supersedes the delivery ordering in PROPOSAL.md where they differ.

## KCPM pilot scope — latest user decisions

These decisions supersede earlier assumptions below. The pilot helps members organize, and brings club schedules plus federal dates into the app. Actual attendance management is deferred because the app does not represent the full club roster.

- Club affiliation is captured at account creation; app admins associate legacy accounts. Confirmed: selecting KCPM immediately creates active club membership; no approval or club code. This grants club-level access only. It does not grant coach/manager roles or assignment to a training group. Managers can correct/remove membership. Explain that club membership is self-declared, not a verified paid affiliation. Update both existing registration flows where applicable, without breaking invitations/account creation. The club selection should allow no club for independent divers.
- Club managers and coaches they authorize publish club events. Any adult member can organize an invited-only informal outing.
- Only club events explicitly shared with the app community are discoverable outside the club.
- Going means interest, never a reserved place, official registration or pool booking. Use “Interested” / “Ça m’intéresse” where this avoids confusion. Confirmed: capacity, place allocation and waiting lists are deferred. Interest has no place limit; no reservation language, full state or timed offers in the first release.
- Coaches assign regular training groups, and members report session absences. Group assignment is not an RSVP and not proof of actual attendance. Non-responders remain “no absence reported”, never “present”. Do not invent accounts for missing divers. Basic group membership is needed now; actual attendance dashboards come later. Absence reporting must not penalize members or imply a complete roster.
- Launch includes club page, member list of actual app accounts, roles and separate group calendars. A member list must not imply a complete club roster.
- Invitations, changes/cancellations to accepted events and a day-before reminder are notification defaults. For assigned group sessions, reminder/absence behavior still needs a defined default; interest remains separate from group assignment.
- Federal dates are initially curated by app administrators with official source links. Broader international meet resources supplied by the user also belong in the app; not all competitions are FFN events.
- Explicit linking of existing dives after an event belongs in the initial scope, with existing video permissions unchanged.
- KCPM Montreuil is the real pilot, with two supplied 2026–2027 schedules and a competition/resources workbook. Import data must persist in the application database at implementation, not live only in fixtures or the prototype. Current preparation has not loaded production or created calendar tables.

### Data preparation and import delivery

Reproducible reader: `backend/scripts/prepare_calendar_sources.py` (pymupdf/openpyxl). Private runtime bundle and copied source attachments: `reports/calendar/kcpm-2026-2027/`, ignored by Git under existing /reports/ rule. Keep private source data and invitation links out of source control. The bundle preserves source hashes/page/row/cell/hyperlinks, 116 explicit training dates, competition candidates and resources. The stable training source key excludes time and venue so a time/location correction can update the existing occurrence. Date/group reassignment still requires reconciliation; do not assume a missing old row means cancellation. Workbook row keys identify a snapshot only, not a durable identity across sorting; database mappings need canonical meet IDs and reviewed reconciliation.

Add an idempotent import service/CLI as part of domain implementation: validate -> preview changes/review queue -> apply in a transaction -> record import version and source mapping. Rerunning the same source must not duplicate records. Separate “source unchanged” from “fetch failed”. Store source artifacts in private persistent storage with metadata in PostgreSQL. Explicit supplied dates are authoritative for initial import; do not synthesize weekly sessions through breaks. Preserve past dates as history without scheduling old reminders. Local manual overrides survive refresh; source conflicts require review. No hardcoded fixture-only release.

Extend schema with training_groups, effective-dated training_group_memberships, calendar/group associations, occurrence_absence_reports, event_resources and resource_versions. Date-effective group changes must preserve historical assignment. Group membership and club membership are separate relationships. Membership loss and group changes affect access/reminders server-side. Competition resources need typed links (official info, registration, dive sheets, results, club chat), multiple deadlines (club cutoff, official entry deadline, dive sheet deadline), source verification and category/eligibility notes. Historical rules documents must be labelled by edition and never overwrite the scoring engine's current rules automatically. Shared live-results URLs can be reused for later meets; retain source/date context and avoid treating an old “live meet” URL as a permanent result archive.

Confirmed: use the resource and organizer links INSIDE the workbook as the upstream source inventory. Do not depend on finding or refreshing the original spreadsheet. Preserve the attachment as initial provenance only. Investigate the linked federation/organizer calendars, meet pages and documents individually; support scheduled fetch only for sources with a validated extraction method, validators/ETag/hash where available, parser/schema checks, last-success/stale status and review queue. A readable resource link is not automatically a usable feed. Keep resource-link checking distinct from event-data synchronization. Successful checks of organizer pages do not establish an API/ICS feed. Public external fetches require allowlisted source configuration, timeouts/size limits and redirect/private-network checks. WhatsApp invitations from the workbook are private club resources, excluded from public cards and automated crawls.

Suggested source precedence: club schedules from club-approved source; meet dates from relevant organizer/federation; imported notes/deadlines retained with provenance. Source conflicts are proposed corrections, not silent rewrites. A manager sees the proposed old/new values, accepts changes, then affected members are notified. Do not copy an old competition into a new year merely because an annual event recurs.

## Product decisions

- Dedicated authenticated /calendar destination on desktop and mobile.
- Five equal mobile targets: Library, Messages, Community, Calendar, Evaluations. Preserve current destinations and unread messages. Standard calendar icon with binding rings and date grid, distinct from Evaluations clipboard. Decision: icons only on mobile, with accessible names, current-page state and recognizable icons; no visible labels. Validate recognition and accessibility on iPhone.
- Agenda default on phone; month available. Desktop agenda + detail panel. Mobile event detail gets a proper route with Back, rather than only a modal. Date and source filters survive navigation and reload through URL parameters.
- One canonical event shared across calendar, community and notification links. Existing filmed sessions remain separate. No automatic access to videos from participation.
- V1 supports club training, camps, informal outings and curated federal dates. Following a calendar, following an event, receiving an invitation and attending are different states.
- V1 is authenticated, with invited-only, club-members and app-community audiences. App-community does not mean indexed public Internet access. Default informal outing audience: invited-only.
- RSVP expresses intention. Pool bookings, payment, official competition registration and attendance certification are external unless explicitly built later.

## Proposed pull-request sequence

| Step | Scope | Completion evidence |
|---|---|---|
| 1. Navigation and UI prototype | Dev-only React prototype using existing shell, five targets, agenda/month/detail/create screens, fixtures and FR/EN. No empty production tab. Include keyboard, safe inset, landscape, unread badges, large text and back behavior. | Browser review at 320/375/390/430 widths; actual iPhone Safari/PWA check before release. Existing navigation behavior preserved. |
| 2. Calendar domain and authorization | Additive SQL migration, SQLAlchemy models, bounded read APIs, personal/club/federal sources, memberships and roles, event/occurrence model, invitation and response uniqueness, venue fields, change versions and authorization matrix. | Backend integration tests on PostgreSQL: cross-club and direct-ID access, no private roster leakage, migration works with old app. |
| 3. Working calendar | Connect React to APIs; event creation/edit/cancel; invite existing users; follow sources/events; interest responses and absence reporting; empty/loading/error states; group assignment and dive linking. No capacity/waitlists. Basic club admin workflow. | Complete flow with two accounts; interest and absence state tests; retry does not duplicate event/RSVP/invitation; no state lost on validation failure. |
| 4. Recurrent schedules and camps | Weekly schedules with end date and excluded dates, stable occurrence IDs, edit one/future/whole series, timezone-aware recurrence, all-day and multi-day events. | DST transition, moved occurrence retains responses, removed occurrence cancellation, overlapping events and holidays tested. |
| 5. Reliable alerts | Calendar notification targets/types/preferences and translations; durable changes/reminders outbox; resumable server worker; retry/backoff and monitoring; revoked access and stale reminders suppressed. | Worker restart/retry/concurrency tests; one inbox row per delivery key; move/cancel invalidates obsolete reminders; authorized notification deep links. |
| 6. Pilot and rollout | Small admin-managed club pilot, curated federal entries with official source, one-off ICS export, feature flag, deployment/runbook, immutable release notes, then wider enablement. | Frontend/backend CI gate, SQL applied before dependent code, worker installed and healthy, smoke tests and rollback drill. |

Steps are review boundaries, not separately usable public releases. First public calendar release requires steps 1–6, real KCPM data import and source review, so training schedules and reliable cancellation notices ship together. No calendar table or cron job is assumed to exist today.

## Rules needed before coding endpoints

### Ownership and authorization

App administrators initially create clubs and appoint a responsible member. Responsible members manage club membership and designated event editors; coaches publish only where granted. Members RSVP and create informal personal outings; federal source editing belongs to designated curators. The UI hides unavailable actions, and the server enforces every operation independently.

Read eligibility is evaluated for the event, occurrence, roster, invitation and linked media separately. Following a source grants no club membership. Invitation access can be revoked. Leaving a club removes access to club-only future events and suppresses pending alerts. Historical membership/participation records can remain for audit under the retention policy without granting former members roster access. Private notifications must not retain sensitive event details after access is revoked; resolve/redact them at read time and use generic push previews for private events.

Allow organizer transfer; do not orphan a club when its last responsible member leaves. Account deactivation/deletion, event cancellation and club archival need explicit service behavior. Do not reuse the app-global administrator role as the club role. Participation removal by organizer is recorded and communicated to the affected member.

### Event lifecycle

Draft -> published -> cancelled; published content has a version and audit trail. Cancel preserves the event and its responses. Physical deletion is limited to unused drafts/defined retention cleanup. Event updates use optimistic concurrency (version/If-Match); successful creates accept an idempotency key scoped to actor and payload.

Separate event type (training/camp/outing/competition) from publishing source (club/personal/federation). Support title, description, source, organizer, venue/address and optional map link, audience, date/time, timezone, capacity and response deadline. Stage registration is for the whole camp initially; separately bookable camp sessions are deferred. Venue is reusable but starts with lightweight structured fields; access instructions can be restricted. No pool availability or coach qualification guarantee is implied.

Interest states: interested, maybe, declined. Invitations have pending/accepted/declined/revoked states, separate from interest. No place reservation follows from interest. Capacity and waiting lists are deferred entirely. Do not implement allocation, timed offers or booking claims in the first release. Actual attendance is deferred.

Publish changes to time, venue, audience or cancellation with a change summary. Decision: changes to time or venue preserve accepted interest responses. Notify affected participants with the old and new details and a direct action to change their response. Do not require reconfirmation or automatically remove accepted participants. Invitation revocation removes its access grant and related active participation when no other grant remains. Document these transitions before implementing.

### Recurrence and time

Weekly recurrence only initially; bounded season and rolling materialization horizon. Preserve timezone IANA and stable occurrence keys across moves; UTC timestamps for timed occurrences, local dates with exclusive end date for all-day ranges. Generate by local wall time to preserve club schedules through DST. Edit single/future/all scope must preview impact on existing responses. Exceptions/cancellations are durable, not lost during regeneration. Ambiguous or nonexistent local times require an explicit selection/correction. Show event timezone if different from viewer timezone. Multi-day events show inclusive human-readable dates without off-by-one errors.

### Alerts and operations

Inbox is the durable reference, Web Push a best-effort channel. Existing notification creation commits itself: introduce a transaction-aware calendar path without changing existing callers' contracts. Persist event write plus outbox atomically; worker commits idempotent inbox creation before attempting push, with explicit retry state. External push delivery cannot be exactly-once. Do not replay very old reminders after downtime; re-check current occurrence version, eligibility, preferences and status before dispatch. Source-follow alerts and participation reminders need separate controls; no global blast on every imported edit. Default reminder proposed: previous day for going members, configurable/off; always surface changes/cancellations in the event, honor channel preferences for notifications. No calendar email promise in V1.

Worker needs overlapping-run exclusion/row leases, bounded batches, dead-letter visibility, last-success timestamp, oldest due-job age and retry counters. Health/readiness must detect missing schema and worker installation. Cron provisioning is a separate explicit deployment action, not something ship.sh currently guarantees. Use existing PostgreSQL and backend code; no additional queue service initially.

### Federal sources

Begin with manually curated entries, official link, source identifier, verification date, curator and tentative/confirmed/cancelled status. Deduplicate by source/external identifier where supplied. An unofficial entry must not present an official verification badge. Following is not FFN registration. Automatic sync is a separate connector investigation: source format, discipline filter, permissions, freshness, changed dates and duplicate reconciliation. Remote disappearance must not silently erase a followed date. No current FFN dates need to be fabricated for implementation.

### UX details and community integration

Calendar opens near today with a Today action, date navigation, filters for following/club/federal/outings and search by title/place. Filter empty state differs from no events. Show conflict warning, cancellation, pending invitation, waitlist and changed-event states. Event details display source, organizer, visibility and response meaning. Create form preserves inputs on failed save and prevents accidental loss. Refresh on focus and after mutations; handle stale cached responses and connectivity errors honestly. Offline editing is out of scope initially. Exclude private API data from shared/service-worker caches; clear account-scoped state on logout/account switch.

Community gets a club directory/membership entry and upcoming event links, not a second independent calendar. Profile event visibility stays opt-in/permission-filtered. Sharing initially copies an app deep link; login preserves the intended authorized event destination. No public bearer-link invitation or email guest invitation in V1. Existing messaging remains direct; event URLs can be sent, while rich event cards and group chats are later work. Prevent link previews from exposing private event data. New group messaging needs its own membership/history rules.

Icons keep accessible names and current-page state even without visible labels. Verify VoiceOver, keyboard focus, 200% text, contrast, unread badges and reduced motion. A long-press tooltip alone is not adequate onboarding. If recognition fails, revise the icons and test again; visible mobile labels are not the selected design. Preserve tab scroll memory, deep links and overlay/action-bar replacement policies from the current shell.

### Trust, privacy and scope

Rate-limit event creation/invitations and add basic report-to-admin plus organizer/admin cancellation controls. Do not expose attendee rosters across audiences. Restrict contact/location instructions for invited-only events and avoid storing sensitive health information. Minor/guardian participation and club safeguarding policy must be settled before onboarding a youth group; V1 does not implement guardian accounts or parental consent. Retention, account deletion and audit access need a written policy before real member data is collected. No legal compliance claim is made here.

Calendar capacity is a planning limit, not a pool reservation or permission to dive unsupervised. Include level/access constraints and organizer instructions where relevant; eligibility verification remains with the organizer/club. Payments, official entries, guest places, check-in, medical certificates and coaching assignments are deferred.

### External calendar integration

V1: download a single event as ICS, with stable UID, event timezone, sequence/version and cancellation semantics. A downloaded file does not update itself; explain this in UI. Later: revocable private subscription feeds, rotation of token URLs, data minimization and refresh-delay messaging. Bidirectional Google/Apple calendar sync is a distinct project.

## Release and rollback

Use additive migration, explicitly applied before dependent backend deployment. Rollback app and disable worker/feature, preserving new records for investigation; no destructive down migration during an incident. Flag the API writes and UI together, and make disabled-feature behavior explicit for outstanding jobs/links. Use ci/ship.sh server --dry-run then the repository deployment workflow. No Mac agent or media pipeline changes expected. Release note components: frontend/backend; worker setup is an additional operational acceptance gate because the current release catalog only tracks service image SHAs, not cron health. Do not announce reliable reminders until that gate is verified.

Track pilot success with minimal aggregate counts: event creation, response completion, duplicate/inconsistent responses, notification lag/failures and navigation usability feedback. Avoid collecting private event titles/descriptions in analytics.

## Confirmed decisions and scope defaults

1. Confirmed: club managers and coaches they authorize publish club events. Initial appointment of the manager is app-admin managed.
2. Confirmed: pilot adult accounts; guardian support comes later.
3. Confirmed: five icons only on mobile; retain accessible names and test on actual iPhone.
4. Invitations to nonusers: defer; existing accounts only.
5. Paid/official bookings and pool reservations: external links, clearly separate from RSVP.
6. Confirmed: time/venue changes retain acceptance and capacity; notify participants of the change without requiring reconfirmation.

Next implementation action: step 1, a dev-only React prototype inside the real shell, followed by the permission/state-transition contract and additive schema. No production feature should be activated merely because the navigation prototype looks ready.

## Confirmed source and access decisions — latest clarification

- Source inventory: the hyperlinks embedded in the supplied competition workbook, not a live original spreadsheet. The user does not want the original table as an ongoing dependency. Investigate federation/organizer/resource links directly; preserve original cells as provenance and proposed mappings. Do not crawl private WhatsApp invitations or treat old live-results slots as stable meet IDs.
- Signup: selecting KCPM immediately grants active club membership. Legacy affiliations are admin-assigned. No automatic elevation to coach/manager. Club affiliation does not imply assigned-group access.
- Training visibility: members can see only their assigned group calendar; coaches see both. Enforce in SQL/API/detail routes, resource links, notifications, exports, search and caches. A club-wide event is a separate audience. Group-only events must not be exposed merely by following the calendar or choosing the club.
- Until group assignment: show club-wide events/resources and a clear “Your training group has not been assigned” state; do not default into either group. Coaches/managers assign groups with effective dates. This unassigned-member behavior is an implementation default, not an additional user decision.
- V1 responses express interest without a place limit. Remove capacity, full-event badges, reservation semantics and waiting lists from production V1 designs. Existing exploratory HTML showing waiting lists is historical and superseded.
- Import exact KCPM schedule dates from the supplied PDFs; automatic refresh of competition resources does not provide an upstream source for private club schedule changes. Those remain manager-edited or replaced by reviewed PDF imports unless a club source is later configured.
