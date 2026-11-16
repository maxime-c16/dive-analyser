# Independent technique adjustments

This supersedes the exclusive-period default in the earlier technique-history proposal. A diver describes individual adjustments, such as less pike and earlier twist. They may overlap. Adding one never ends another unless the diver explicitly selects a replacement.

## Journey

The code page lists ongoing and ended adjustments. “Add an adjustment” opens the existing session/month browser and the uncropped Library player. The naming form defaults to “Adds to the others”; “Replaces…” names one saved adjustment or an earlier draft marker. Two different adjustments can start at the same dive. Joint review shows each adjustment's own interval; open-ended changes explicitly continue. Saving the whole batch is atomic.

An ongoing adjustment has an explicit stop action with a date and preview. Removing a saved end date is a separate, confirmed action for an adjustment that never actually stopped. The original dates are never reinterpreted from labels. Existing ends remain recorded until the owner changes them. Draft removal can be undone before leaving the workflow. A saved adjustment can be removed only after review; this soft-deletes the record and retains its audit/attempt annotations.

Selecting an adjustment opens its score chart inline. Ratings describe that interval; overlapping adjustments do not establish independent effects. The main Scores section remains intact. No comparison pools different tracks into a headline result.

## Storage and contracts

No schema migration is required. Each independent adjustment uses an isolated existing `TechniqueTrack`; the UI hides this storage detail. Old tracks and intervals remain supported by the legacy APIs. A date-only old start can be located in the player and reviewed before adjustment. Editing or removing an old end detaches that episode from a shared old track when necessary; explicit episode assignments and intersecting session states are preserved in the isolated track. Other episodes' dates are unchanged.

New owner-only routes are `/api/v1/technique-adjustments/{diver}/list`, `/preview`, `/save`, `/end`, `/remove`, and `/copy`. The diver row serializes all writers before validating the aggregate history revision. Existing writers use the same diver lock. The aggregate revision is the sum of track revisions plus track count; retained tracks make it monotonic. Each adjustment mutation is audited. These journal operations cannot be replayed through the legacy undo API.

A replacement ends only the explicitly named adjustment. No neighboring-boundary inference is used. The server rejects invalid/foreign targets, duplicate marker keys, stale revisions, crossed start/end boundaries, double replacements and identical already-recorded starts. A failed save rolls back every boundary and replacement. An unconfirmed network response still requires refresh; it is never described as proof that no save occurred.

Sharing is an explicit independent copy with chosen code/family, apparatus and height; it does not close target adjustments. A family copied “elsewhere” excludes its original exact-code context, so it does not duplicate the source there. That exclusion is represented by the internal `adjustment-copy-` track prefix and source episode reference; legacy family fallback is unaffected. Exact armstand defaults remain unchanged. Copy retries are rejected when the source is already copied to that target.

Caption modifiers DB/HU/SD remain separate. Assignment provenance and scoring are unchanged; an intended adjustment is not a confirmed execution tag. Legacy assignment endpoints remain available for confirmed/mixed/unknown attribution; the simple history journey does not require per-dive tagging.

## Resource bounds

Inventory uses a joined SQL page of50 plus one sentinel, with stable occurrence/ID ordering. UI pagination replaces the current page, so retained inventory is bounded. Full revision/count calculations happen in SQL. Batches retain at most16 changes; validation/count/writer work is bounded by that batch. Clone operations preserve records with INSERT…SELECT, never an unbounded Python scan. Session and clip browsing keep their existing24/50/100 limits. Account/diver/context keys isolate private drafts and state. Stale asynchronous results are ignored.

## Validation and test access

41 backend checks (PostgreSQL plus attribution rules),36 focused frontend checks, TypeScript and production build passed. Checks cover two overlapping starts, explicit replacement of only one adjustment, atomic rollback after a second writer failure, conservative old ends, explicit end removal preserving records, pagination, cross-diver refusal, soft deletion and independent family copies without source duplication.

A headless browser on the real isolated history prepared two adjustments at the same dive, verified that both remain open, replaced just one with a third adjustment, and confirmed three correct preview intervals at320px without horizontal overflow or JS errors. No actual history save was performed. Evidence is private outside git in `~/.local/share/dive-technique-preview/independent`.

The existing test relay remains `http://192.168.1.57:6191/dives/analysis/5122D`. It forwards privately through deb-serv to the Mac's isolated test instance, so the Mac must remain running. Production has not been deployed or changed. No further council was launched, as requested.

### Mobile editing recovery (2026-11-16)

Successful mutations reload the list without retaining the mutation's busy
state. Read-request generations and context epochs are separate: a reload
invalidates old reads, while a diver/context switch also invalidates mutation
callbacks. Preview failures leave retry, cancel and close available.

Regression coverage exercises two consecutive end removals with refreshed
revisions, cancellation/close after the first write, failed preview recovery,
and a pending preview across a context switch. The five related frontend test
files pass (39 tests); TypeScript and the production build pass. Headless
browser checks use intercepted mutation responses, with no user-data writes,
and verify chart gutters and reachable dialog actions at 320 and 390 px.

The new release note validates against the schema. The full catalog check is
blocked by a pre-existing branch/base difference: `adaptive-clip-streaming.json`
is present on `origin/master` but absent on this branch. No published note was
changed by this fix. Browser interaction checks passed in headless Chromium;
a separate WebKit run timed out before opening the code page, so these results
do not constitute physical iPhone/Safari validation.

### Edge-case pass (2026-11-16)

Confirmed and fixed:

- Renaming or moving an earlier draft no longer breaks a later marker's
  `replace_draft_key`; deleting a referenced draft asks the user to change or
  remove its replacement first.
- Identical labels on the same anchor (ignoring case and outer whitespace)
  are rejected within a draft, both in the UI and by preview/save validation.
  Different simultaneous adjustments are still allowed.
- Renaming an approximate draft preserves its uncertainty interval.
- Invalid end dates, revision conflicts, and unavailable requests have distinct
  recovery messages. The dialog can refresh a conflicting revision in place;
  submitting is disabled during refresh. Mutation requests time out after
  30 seconds rather than holding the UI indefinitely.
- Pending mutations are invalidated on viewer changes as well as context changes.

Verification includes 43 backend checks against a disposable PostgreSQL database,
46 frontend checks including locale parity, TypeScript and a production build.
Coverage includes atomic rollback, exact context/owner isolation, family-copy
exclusion, paged inventory, overlapping changes, replacement, sequential stop and
resume, local-time conversion, invalid dates, stale revisions, and draft editing.
The branch-wide release catalog check retains the known baseline discrepancy
noted above; the newly added note passes its schema validator.

In a private background preview tab, real clips decoded (`readyState=4`),
navigation resumed after naming, and a local marker reached the server-backed
review (five eligible dives). The review had no horizontal overflow at 320px.
No history write was submitted. These browser checks do not validate physical
Safari gestures, VoiceOver or uncertain network commit delivery.

The temporary browser draft was closed and reopened successfully, then removed;
no adjustment draft remained in the private profile when its tab was closed.
At 320px the review footer's buttons ended at y=582 within a 640px viewport.
