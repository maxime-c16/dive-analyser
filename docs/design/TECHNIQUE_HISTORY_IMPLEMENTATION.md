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
