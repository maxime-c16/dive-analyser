# Technique History implementation

The runtime now includes private technique history on Scores. The approved
[proposal](TECHNIQUE_HISTORY_PROPOSAL.md) remains the product contract. This
implementation has only been exercised locally; no production schema, checkout,
service or data was changed.

## Delivered behavior

Scores obtains its context inventory with a complete ownership-filtered SQL
aggregation, independently of the existing attempt-list cap. Select one diver,
exact code, apparatus, height, position and sync context, then one technique
track. General is the initial track; additional tracks are private to that diver.

A change records intended/usual technique, independently of caption modifiers
and explicitly recorded attempt use. Changes can start at an immutable attempt
key, a retrospective date in a saved account timezone, or an approximate range.
Position/sync constraints and notes are optional. Supported family scopes are
1/2/3/4 and 51/52/53/54. Armstand uses exact catalog codes. Copies into selected
code/family, apparatus and height scopes are independent episodes with a source
reference. Previews disclose target scopes, affected context counts, preserved
explicit use and upcoming boundaries. Inserting a boundary preserves the next
existing change. Ambiguous equally specific position/sync overlaps and duplicate
boundaries are rejected.

Explicit attempt state wins over a context-specific mixed/unknown session flag,
then exact-code episode/gap, family episode/gap, then unrecorded context. Gaps
block fallback; an explicit end permits family fallback after preview. Approximate
boundary ranges remain unknown context. Assignments carry their original diver,
code, apparatus, height, position and sync fence. Caption resync cannot replace
these tables. Boundary edits preserve assignments; deleted episode provenance
remains visible on explicitly tagged attempts.

Attempt and episode lists are paginated and keyboard-operable. Attempt selection
includes thumbnails, date/session filters, individual checks, a page selection
and the range between checked attempts. Bulk actions record technique, mixed or
unknown. A session can be marked without logging each attempt. Identity reuse
keeps A/B/A as three chronological episodes; renaming an identity changes its
label and retains revision history.

Technique chart mode leaves the ordinary all-history chart available when off.
It displays one selected track, splits session points by episode/recorded-state
subset, and computes rolling curves in SQL within resolved contiguous segments.
Mixed/unknown gaps have no rolling summaries. Continuation pages retain their
preceding segment context. Score colors are preserved. Selection highlights the
resolved episode; boundaries are marked, approximate ranges hatched, and
coincident boundaries grouped into cycling count controls. The episode list
provides a separate large target for every episode. Recorded comparisons use the
summary table rather than a curve through interleaved variants.

Periods and Recorded use have distinct SQL membership. Both require the same
exact comparison context and modifier set. The modifier inventory exposes each
set's eligible/scored counts on both sides, including empty sides. Coverage is
shown for both sides before ratings. Recorded use includes explicit assignments
from the union of the two selected resolved periods, preserves conflicts on their
recorded identity, reports out-of-intended-period use and exclusions, and handles
same-identity recurrence by episode. It does not include intervening gaps or later
recurrences. Attempt and equal-session weighting use continuous-percentile
median/IQR, with no spread for a singleton and no zero for a missing rating.
Ratings use the existing app mapping, including its 45/55 phase weighting;
no official judging, DD weighting, winner or causal improvement is inferred.
Other-track changes appear as textual selection controls.

## Concurrency and audit

Every annotation writer locks the diver ownership row, revalidates ownership,
then locks the selected track and checks its shared revision. Family and exact
scope writers use that same revision. Reads share-lock the revision while
materializing their result. A stale preview receives 409. Copies and selections
are atomic within their declared batch. UI requests have generation/cleanup
fences and no private history cache.

Revisions record author, operation, time and before/after state. Undo applies to
the latest create, boundary edit/end, delete, copy or rename; it refuses an
intervening revision. Bulk attempt/session state and order corrections retain
audit records but are not undo actions. An order correction previews affected
attempts, requires every diver-track revision, increments those revisions and
preserves existing anchor boundary keys. Moving an anchored boundary remains an
explicit episode edit. The ordinary ORM/SQL update paths cannot rewrite keys.

## Request budgets

| Path | Selection / materialization | SQL / response contract |
| --- | --- | --- |
| Contexts, tracks, episodes, attempts, modifiers, chart, revision metadata | At most 50 items plus one sentinel; stable context/history cursors | Read target <=12 statements including normal auth; <=512 materialized rows; <=256 KiB detail response |
| Preview | Immediate neighbors, one aggregate row; no attempt list | <=16 statements, complete SQL affected counts |
| Bulk assignment | <=100 IDs; <=100 narrow dive rows and existing assignments | <=256 statements including bounded ORM writes; atomic |
| Copy | <=16 target scopes; immediate neighbors and one aggregate per target | <=256 statements including bounded ORM writes; atomic |
| Order correction | One attempt, <=16 tracks | Refuses larger fan-out before mutation; requires all track revisions |
| Comparison | Two episodes, two summary sides, bounded other-track indicators | Full SQL counts/percentiles; never computed from detail pages |

Labels are limited to 120 characters, track names to 80, notes to 2,000.
Dive mutations load only required identity/order columns, not unbounded captions
or notes. Complete eligible-history and session-bin scans occur inside PostgreSQL;
constant query count does not mean constant database work. Chart windows may
scan preceding segment bins. Python detail retention target is 2 MiB.

Measured PostgreSQL detail proof: 75 episodes with maximum-length notes produced
50 + 25 item pages, five SQL statements across the two direct service calls
(excluding authentication), a 123,279-byte first response, and <0.5 MiB peak
traced Python memory. Comparison statistics remain complete beyond the first
50 attempts; tests use 121 eligible ratings. These are isolated representative
checks, not production latency/load benchmarks.

## Migration and backout

Apply `backend/migrations/add_technique_history.sql` manually **before** deploying
both backend and frontend. `ship.sh` does not apply SQL. The migration is additive
and transactional, creates the private history/preference tables and indexes,
backfills `dives.history_occurred_at` once from the existing occurrence date,
and installs an INSERT/UPDATE trigger. ORM creation also captures the key; the
trigger covers raw SQL and older ingest clients. Display-date edits leave the
key unchanged. Deleted anchors retain their boundary timestamp/ID.

Before rollout, take the normal database backup and schedule the backfill/index
work according to production volume. Verify zero NULL history keys and the new
tables/trigger, then deploy the backend and frontend together through the normal
repository workflow. No Mac worker upgrade, nginx change or automatic migration
is required. The immutable `technique-history` release note names both services.

For application backout, restore the previous backend/frontend images and retain
all additive tables, history keys, trigger and revision records. Older insert
writers remain compatible with the trigger. Do not drop history or restore old
dates over the immutable keys as part of rollback. Any later schema removal
requires stopped dependent writers and an independently verified export/backup;
there is deliberately no destructive down migration.

## Verification

- Full isolated backend run: **1,908 passed, 129 skipped, 28 performance tests
  deselected**. Skips are environment-specific PostgreSQL/live tests; the new
  production-dialect tests are run separately against a disposable database.
- Frontend gate: **984 tests across 120 files**, TypeScript and production bundle passed. Latest
  focused checks include mobile segmented SVG rendering, keyboard selection,
  preview-before-save, immutable anchors, stale-diver responses, CodeAnalysis
  behavior and locale parity.
- **19 dedicated PostgreSQL checks** apply the migration twice and exercise immutable
  SQL/ORM key producers, full-scope statistics, phase weighting, session weighting,
  recorded conflicts, context fences/ownership, shared locks/stale revisions,
  insertion/splitting, copy independence, boundary undo, order correction,
  deleted provenance, complete context inventory, A/B/A session partitioning,
  chart continuation and response/query/memory budgets.

Reproduction uses `TECHNIQUE_TEST_DATABASE_URL` pointing to a disposable
`calendar_test_*` database and `pytest backend/tests/test_technique_history_postgres.py`.
The test refuses other database names. The local frontend Node version requires
`NODE_OPTIONS=--no-experimental-webstorage ci/gate.sh frontend`; without that flag,
Node's experimental global storage shadows jsdom storage in unrelated suites.
The cached Python environment runs the backend suite directly; its missing pip
launcher prevented the first gate wrapper attempt, not pytest execution.

## Operational limits

No deployment, production migration, browser E2E or production load measurement
has been performed. Boundary/identity undo is one latest action. Larger copy or
assignment selections require explicit bounded batches/pages; order correction
refuses more than 16 tracks rather than partially changing history. Other-track
comparison indicators return the first 50 plus an explicit more flag; the full
track/episode inventories remain paginated. Live media playback retains its
existing authorization and transport workflow.

## Local commits

- `acd958e4`: approved proposal and original pure-rule foundation.
- `1f248784`: original foundation status.
- `03baef9d`: first runtime schema/API/SQL milestone.
- `eec9b8d4`: integrated Scores UI, complete context inventory, segmented SQL chart, exact-context comparisons, mutations/provenance, release note and dedicated PostgreSQL/frontend verification.

## Mobile journey redesign

The initial implementation exposed editing and administration inline. The Scores
experience now opens on a segmented chart and readable, newest-first technique
timeline. One selected period reveals edit, copy and tagging actions. Compare
explicitly selects two named periods and presents coverage before side-by-side
medians; attribution, spread, exclusions and weighting are in comparison details.
Only the applicable resolved episode is labeled current. A new exact-code change
retains an existing exact-code episode's position/sync constraints so it does not
silently create a less-specific default beneath the episode the user is viewing.

Record change opens a native modal (bottom sheet on phones) with a label and date,
then a review before saving. Attempt anchors, uncertain dates, family scope and
notes remain in additional options. Track creation, all-history chart switching,
undo, period deletion/ending/renaming, bulk/session attribution and history-order
correction remain available through management or a selected episode. Existing
notes are preserved when editing. Singleton context and dead pagination controls
are omitted, dates are localized, and long labels wrap within the viewport.

Browser verification on the LAN sandbox at 390 CSS pixels exercised period
comparison, the record/review/save flow and undo cleanup, with zero horizontal
page/dialog overflow and no render errors. Native dialogs keep focus within the
modal, support Escape and restore the initiating control. No production data
was involved. Interaction tests cover the quiet default view, immutable-anchor
preview-before-save, explicit comparison selection, cancel and diver-switch
isolation. The production frontend build passes.

Validation for this redesign: the full frontend suite passed 988 tests across
121 files. A further focused check covers preservation of notes and scope during
editing, alongside the journey and locale tests. TypeScript and the production
bundle pass. Browser checks at 320 and 390 CSS pixels found no horizontal
overflow; Tab remains in the dialog, Escape closes it and focus returns to the
record-change button. The synthetic save was reverted through the UI undo action.

## Finding past changes in the Library player

The code page now calls this feature **Technique changes**. Its main action,
**Find my technique changes**, opens the existing Library `ClipViewer` in a
focused workflow. The same mobile drag-follow pager, video controls, previous/
next keys and desktop filmstrip remain in use. Social/evaluation panels give
way to boundary recording. A missing-media attempt still supports the shared
swipe gesture surface, but does not pretend to contain playable video.

Users browse chronologically, seek by date and mark the first clip of each new
technique. Each marker captures the immutable attempt key and a short label.
The draft holds at most 16 markers and can be edited or removed before saving.
Reviewing a marker can reopen its clip with surrounding attempts, including when
that clip has left the navigation window. The existing quick date-based change
form remains available as a secondary action.

Only 100 navigation records are retained. Forward and backward pages each fetch
at most 51 narrow records. An anchor-centered request fetches at most 26 records
on either side, returns at most 50 and exposes both continuation cursors. All
three cursor paths resolve the anchor through the owner-authorized exact
context; foreign anchors yield no results. No full-history statistics are
calculated from this navigation window. Failed prefetches stop until an explicit
retry; close/context changes abort requests and discard late results.

Review validates markers before writes. Save applies them chronologically as
individual atomic, revision-checked changes; this is not a multi-boundary atomic
transaction. If a later save fails, already-saved markers are identified and the
remaining draft is retained. Retry skips successful markers. An explicit refresh
allows rechecking against a newer history revision. Closing an unsaved draft asks
before discarding it; no boundary is written while browsing or naming markers.

Validation: 995 frontend tests passed across 122 files, including reuse of the
Library swipe pager, multi-marker review/save, partial-failure retry, bounded
navigation, failed-prefetch stopping and stale-response cleanup. Twenty isolated
PostgreSQL tests pass, including anchor lookup, reverse/forward continuity and
foreign-context rejection. TypeScript and the production build pass. The LAN
browser check exercised mobile swipe navigation and draft review without saving
the temporary markers. Backend and frontend updates are required; no additional
migration beyond add_technique_history.sql is introduced.

### 2026-11-10 — clip journey UI corrections

The retrospective journey now prevents player navigation during naming/saving, reuses existing or newly drafted technique identities, and lets users move a draft boundary while browsing clips. Each clip shows its current and proposed technique and its position within the session. Failed reads remain errors, with sign-in/retry recovery; they never become fabricated empty comparisons. Review omits provisional per-marker counts because the draft is saved as revisioned sequential boundaries, with partial progress retained.

Secondary forms protect unsaved edits, use local dates, confirm undo and offer named sharing choices. Same-day boundaries retain their distinct times. Session ordinals are computed across the complete selected-code context before pagination; technique names use a bounded ID cursor. No database migration changes in this correction. Validation and dispositions are recorded in docs/reviews/REVIEW_FINDINGS.md.

### 2026-11-10 — effective boundaries and media walkthrough

Date search is an anchor seek, not a lower-bound filter. Around navigation retains both older and newer attempts. Existing exact-code anchored periods can open directly in the shared player to adjust their start; the episode and technique identities and saved notes/context are preserved.

The setup preview now accepts at most16 ordered boundaries in one revision/context, with no writes. Each effective interval stops at the next existing or proposed boundary; complete SQL counts and preserved following changes are returned for review. Each save still revalidates against its revision and reports partial progress. Response details remain bounded by16 markers and the clip window remains100. This preview intentionally performs bounded validation/count operations per proposed marker; it does not load the entire attempt/episode history into application memory. Existing mixed/gap/assignment rules and caption-sync storage are unchanged.

The analytical player contains the complete frame by default on mobile. Its main entry precedes the chart and timeline. Period labels describe usual technique; comparisons retain descriptive period statistics and make conflicting-only attribution less prominent. No migration required for this correction. Browser verification included real local media, date seek/back navigation and a draft adjustment of a saved September boundary, discarded before saving.

### Final correction — atomic setup saves and review recovery (2026-11-10)

This section supersedes the earlier dated notes describing sequential partial setup saves. The setup now sends one bounded setup-save request for up to16 markers. The server checks the shared track revision/lock and joint preview, applies the existing writer within one transaction, reuses draft identities across A→B→A and commits once. Any failure rolls back the complete action. The final journal entry groups the action; undo reverses all its boundaries while keeping audit records. A lost network response is described as unconfirmed, not proof that no write occurred.

New periods default to exact viewed position and individual/synchronized condition; broader application remains an explicit advanced choice. Existing adjustments preserve their saved scope. The player detects an existing boundary before naming and opens it for adjustment. Review has an independently scrolling list with a stationary footer; comparison selectors stack on narrow screens, use same-day times, preserve empty-side names and distinguish a single rating. Counts are pluralized independently in English/French. No migration is required by this final correction.

Council stopped at Maxime's request after three UI review rounds. Final reviewed head402b8c43 received7.2/10 from each reviewer; subsequent fixes were validated with automated checks and a real-media browser smoke, without another council or an invented revised score. Physical iPhone/Safari gestures and VoiceOver remain unverified.

### Timeline motion and touch selection (2026-11-10)

Selecting a period now leaves the chart's time scale fixed to the loaded data. Previously the selected start replaced the domain start and clamped all earlier points onto the left edge. A stable selected-period band moves between dates, point emphasis fades and the timeline details expand/collapse together. The selected name and dates appear directly above the graph, with an All periods reset. Reduced motion disables these transitions.

The technique chart selects on completed taps, not pointer-down or vertical scrolling. Taps use the nearest plotted point; the isolated-point cursor is hidden because this view selects technique periods. General score charts retain horizontal scrubbing. Tests verify stable coordinates across selection changes and that vertical movement produces no selection. A real-media mobile browser smoke confirmed stable point coordinates, the named period and configured range transition.

The LAN sandbox now uses an isolated snapshot of the requesting account's own real history and original password verifier, with the available videos for the tested code. No production credentials are reset, no production sessions copied and no demo technique periods are applied to real attempts. Private exports, media and runtime settings remain outside the repository. All test edits stay in the local snapshot; it has no production database connection or mail delivery.
