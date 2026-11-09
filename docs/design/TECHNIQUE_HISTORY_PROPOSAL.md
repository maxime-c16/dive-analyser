# Technique history on dive Scores

Status: council-reviewed product proposal, with the final explicit comparison guard applied; not implemented.

## Purpose

A diver can mark when they tried or adopted a technique and inspect ratings during that history. Existing attempt modifiers (DB, HU, SD) remain separate and can coexist with a technique. The feature describes performance and recorded technique use; it does not establish that a technique caused an improvement.

## Record a change

From a code's Scores page, choose **Record technique change**, enter a short label, and select the starting attempt. A date or approximate date range is available for retrospective records. Optional notes and a track selector live under additional options. The track defaults to General; user-created tracks can describe hurdle, twisting, entry, or other changes without prescribing coaching terminology.

The initial scope is the current diver, dive code, apparatus and height. Show that scope beside the save action. Offer **Apply to family** and **Also apply to…** as explicit options, not automatic propagation. Changes can be recorded after training; recording every attempt is optional.

A saved change begins an episode of the diver's intended/usual technique. It does not certify execution. Before the first known episode, history stays unrecorded. No invented "old technique" baseline.

## Scope and sharing

Family selectors include 1XX, 2XX, 3XX, 4XX, 51XX, 52XX, 53XX and 54XX as practical user scopes, without claiming that these are independent biomechanical categories. Twisting direction, takeoff, and apparatus remain relevant. Hurdle changes can be deliberately shared across 1/51 or 3/53; the application never infers transfer from numbering.

For armstand, default to the exact code. An expanded selector separates rotation and twisting using the validated code catalog. Do not introduce a single automatic all-armstand scope. If the catalog cannot represent a subgroup reliably, list exact codes instead.

Family expansion targets the selected apparatus/height. Additional heights or apparatus require explicit selection. Position and sync remain visible comparison context rather than automatically creating duplicate episode histories. Users can narrow a change to a position or sync context if needed.

Sharing means **copy this change once** into selected scopes, which may be exact-code or family scopes. Each copy remains a scope-level episode, not a materialized assignment to every matching dive. It creates independent episodes with a common source reference; future edits and future changes do not propagate. A preview names affected scopes, upcoming existing boundaries, and inferred attempt counts. Exact-code episodes take precedence over broader family episodes; a new family episode cannot override an existing code exception. **Resume family technique** explicitly ends a code exception. **Record unknown gap** creates a scoped blocking interval: it cannot fall back to the family default. A family-scoped gap blocks family inference but does not erase a more-specific code episode.

For the same scope, context constraints and track, inserting a new boundary splits the containing episode at that boundary, preserving any later existing boundary. Saving requires a preview of that split. Identical boundary keys, ambiguous equally specific overlaps, and edits that cross an existing boundary are rejected; the user must explicitly edit the neighboring boundary first. There is no implicit last-write-wins resolution. Copies follow these same rules atomically within their batch. Deletion previews include newly exposed family context; an explicit gap is available when fallback is unwanted.

## Intent, recorded use, and mixed practice

Keep two separate facts:

- **Episode context:** the technique intended/usual at that time, resolved from scope and boundary. This is inferred context.
- **Recorded attempt use:** an explicit assignment to a technique, or an explicit mixed/unknown state. This always wins over inferred context and survives boundary edits.

Bulk selection supports consecutive attempt ranges, selected attempts, and a session. A diver can mark a whole mixed session without tagging each dive, then label known subsets later. A mixed session does not mean every attempt was itself a blend: it means the session's technique attribution is unresolved. Explicit per-attempt labels take precedence over that session flag.

Every attempt state, session flag and gap is scoped to the diver, selected track and applicable dive context. A mixed hurdle flag cannot suppress a known entry technique. Technique identities also belong to one track. The attempt selector is a paginated chronological list with date/session filters and thumbnails; recording a change never requires hitting a chart dot. Alternating practice can be left mixed or bulk-tagged via this list; an automatic alternating-pattern tool is deferred.

An episode's label describes an intention/cue, not an objectively verified movement. "Recorded" means recorded by the user, not coach-verified. Returning A → B → A creates three episodes; reuse of a technique name never merges their chronology or statistics. Tracks are independent for recording; the UI never claims their performance effects are independent.

## Boundaries and editing

An attempt anchor uses an immutable history order key: the original recorded occurrence timestamp plus immutable attempt ID as a tie-breaker. Existing attempts receive this key once when the feature is introduced; new attempts receive it at creation. Display datetime edits never silently reorder attribution or move an anchor. Explicit history-order correction is a separate revisioned operation with an affected-attempt preview; until corrected, the UI shows any disagreement between displayed dates and history order. Deleting an anchor attempt preserves its boundary key and marks the source attempt unavailable. Late imports use their original occurrence key, and any resulting inferred context changes are disclosed; explicit assignments survive. Unanchored exact dates use the saved profile timezone by default, changeable under additional options, and display date precision. Approximate ranges remain visibly approximate; attempts within the uncertain boundary range have unknown episode context and are excluded from default episode comparisons with counts shown. Changes later in the same session are supported by attempt anchors.

Episodes use half-open intervals: start included, next start excluded, with an optional explicit end for a break. No carry-forward through a recorded gap. A new episode closes only the previous episode for the same scope and track. Ordering ties and overlap validation are enforced by the server, not browser timestamps.

An explicit end leaves unrecorded context at that scope; it does not itself block a less-specific family default. Recording a break with unknown technique uses the blocking gap action above. Ending a blocking gap can resume the currently applicable family context only through a previewed action, not through silent deletion.

Store technique identity separately from episode identity. Renaming updates the display label while retaining audit history; it does not alter assignments. Moving boundaries or changing scope previews affected inferred assignments and comparison counts. Explicit attempt assignments remain unchanged. Boundary edits support undo. Record author, creation time, effective boundary and precision, copies, edits and deletions. Deletion removes an episode from normal views without silently reassigning its explicitly tagged attempts; those retain technique identity and provenance, with deleted episode context identifiable in history. Scope permission checks apply to every target of bulk edits and copies.

## Scores UI

Display one selected technique track at a time. Preserve existing score colors. A compact chronological list below the chart provides large selectable targets for every episode, including short experiments; selecting one highlights its time region and attempts. Thin boundary markers appear for the selected track with details on selection; avoid multiple stacked strips and full legends on the plot. Approximate boundaries use a range treatment rather than a precise line.

In the selected-track view, rolling median, usual band and peak/trough detection reset at every resolved episode boundary and gap; they never use neighboring episodes to calculate the selected episode's summaries. Apply the existing minimum-data rules independently per segment and omit summaries where insufficient. The ordinary all-history view retains its original cross-period summaries with technique overlays off. Recorded-technique comparisons use the summary table and selected attempt highlights, not a rolling curve connecting interleaved variants. Session points are partitioned into episode/technique subsets when needed rather than recoloring a whole-session median. Co-located boundary markers collapse into a count control; every episode remains individually accessible in the paginated list. Approximate ranges are hatched with labeled endpoints and are also described in list text.

The list and controls expose the same information to keyboard and screen-reader users. Color is supplemental; labels distinguish recorded use, inferred context, mixed and unrecorded. Session mode can show multiple techniques within one session; it must not assign a single technique based on the whole session median. Compare works below the plot and does not require finding a tiny marker.

## Comparison contract

Two distinct comparison modes avoid conflating chronology with actual technique:

1. **Periods:** ratings during two episodes, grouped by episode time/context. Display how many attempts have recorded, inferred, conflicting or unknown technique attribution. Include a mixed session in chronological period statistics as a mixed session, not proof of variant use. Explicit conflicting assignments count in period ratings and are disclosed; they are never counted as matching recorded technique use.
2. **Recorded techniques:** compare only explicitly assigned attempts. The window is the union of the two selected episodes' resolved half-open intervals, after the same scope/context filters; intervening gaps or other episodes are not included. Within that window, partition explicit assignments by the two selected technique identities, regardless of which intended episode contains each assignment. Disclose counts recorded outside their intended episode. Exclude other technique identities, unknown, mixed and inferred assignments, and uncertain boundary ranges, showing their counts. A session may contribute separate subsets to both variants. Later recurrence episodes are outside this window unless explicitly selected. If both selected episodes use the same technique identity (A → B → A), disable variant partitioning and offer a recorded-A-by-episode comparison instead; do not merge them.

Default to Periods, matching the user's timeline question. The result is labeled "Ratings during these periods", never "Technique improvement". Before any numerical result, require a coverage header for each side: eligible/scored counts plus recorded-matching, recorded-conflicting, inferred-only, and mixed/unknown counts. Attribution groups are disjoint; scored coverage is a separate measure. The recorded-only option remains adjacent and shows coverage before selection.

Matching/conflicting describes recorded use relative to the intended episode in Periods mode. Recorded mode instead labels the selected technique identity groups directly and separately discloses out-of-intended-episode counts. For example, if the selected A and B periods contain six recorded A attempts and four recorded B attempts, including two A attempts during intended B, recorded mode includes those two on the A side and identifies their context. It never silently treats them as B use.

Comparison requires one identical diver, track, exact code, position, apparatus, height and sync context on both sides. Selectors reject cross-track or incompatible-context episode pairs and show eligibility counts without computing ratings. Family-level and exact-code episodes may be compared only after resolving both to that same exact context; different codes or heights are never pooled. Overlapping changes on other tracks appear as textual indicators with links, not as a second plotted track.

Use the same diver, exact code, position, apparatus, height and sync context for the initial comparison. Modifier sets must match. If multiple sets exist, show a selector listing each exact set (including no modifiers) with eligible/scored counts per side; require an explicit selection before calculating ratings. Sets with zero attempts or zero ratings on one side stay visible with those counts. If there is only one set it is selected visibly. Show excluded counts. Family sharing never pools different codes or heights into a headline score. If comparable subsets do not exist, show "No comparable rated attempts" and the side-by-side counts, without a pooled rating or delta. Multi-stratum tables are deferred.

Show scored attempts / all eligible attempts, session counts, median, and spread for each side. Default to attempt weighting. Spread is the interquartile range using continuous percentile interpolation; show it only with at least two rated observations and show the actual count. A singleton shows its rating without a spread band or stability claim. Expose equal-session weighting; each session contributes its technique/episode-specific subset median, and median/IQR are calculated over those session medians. Preserve existing app rating provenance: a mapped app rating is not relabeled as an official judging mark. Do not combine these ratings with DD-weighted competition points. Missing ratings are not zeros. No success percentage in the initial release, avoiding the existing ambiguity between successful attempts and successful session medians.

No automated winner, causal claim, significance badge or arbitrary universal sample threshold. Descriptive values remain accessible with their actual counts and existing sample labels; do not invent a minimum n that certifies reliability. Show overlapping changes on other tracks near the comparison. Expose known rater differences if the data exists; do not imply that unrecorded fatigue, injury, confidence, entry quality or rater changes were controlled. Use concise contextual labels rather than permanent disclaimer paragraphs.

## Storage and engineering boundaries

Use separate, ownership-scoped technique, episode, assignment and revision storage. Never place techniques in caption-derived dive_modifiers: current video sync replaces those records. Generic date-only training_periods do not provide the required ownership, scope, provenance or mid-session ordering. Caption resync must not mutate technique history. A dive ownership or identity change must revalidate access and attribution rather than carrying private annotations into another diver's history.

Resolve assignments deterministically: explicit attempt state > explicit session mixed/unknown > exact-code episode or blocking gap > matching family episode or blocking gap > unrecorded. More-specific context constraints take precedence within a scope; ambiguous equally specific overlaps are rejected. All family/code writers for the same diver and track validate a shared history revision under the same writer lock; a stale preview is rejected and refreshed, including inherited-context changes. Copy and bulk actions are atomic over a bounded selection; larger operations use explicit batches with progress, not partial silent success.

Aggregate complete comparison statistics in SQL; paginate episode and attempt detail. Set explicit per-request selection, query, row, memory and response-size budgets before implementation. Avoid per-attempt episode lookups and never treat a capped attempt list as complete statistics. Cache keys include viewer, diver, track, scope, comparison filters and annotation revision. Invalidate comparisons and chart requests after edits and ignore stale in-flight responses.

## MVP and verification

Ship change recording, exact-code defaults, opt-in family/copy scope, independent tracks displayed one at a time, unknown/mixed states, bulk attempt assignment, episode list/selected markers, and descriptive comparisons. Defer ongoing linked scopes, automatic technique transfer, pooled recurring-technique statistics, multi-track overlays, coaching taxonomy, phase-specific causal attribution and automated recommendations.

Before implementation, specify database/API budgets and validate the workflow with concrete examples: one family change with a code exception; A/B alternating in one session; a change anchored mid-session; A → B → A; approximate historical start; deleted/backdated boundary with explicit assignments; family copy into a scope with an upcoming change; armstand twisting versus non-twisting; unequal modifier sets; sparse/missing ratings; simultaneous tracks; caption resync; ownership changes; concurrent edits and stale client responses. Test mobile and accessible selection of short episodes.

## Council record

Round 1 reviewed the conversational proposal: Sol 6.1 medium (Codex second) 6/10; Muse Spark 1.3 Contributor xhigh 4/10.

Round 2 reviewed the written revision: Sol 7.5/10; Muse 7/10, both acceptable to implement with named conditions. Applied amendments define family fallback versus blocking gaps, deterministic overlap handling, recorded-comparison membership including repeat identities, track-scoped flags and shared writer revisions, stable attempt anchors, segmented chart summaries, mandatory coverage, modifier-set selection and empty states. Round 3 checked these amendments. Optional family sharing and independent recording tracks remain intentional requirements.

Round 3 final check: Sol 8.8/10, yes with no remaining product blockers; Muse 8.5/10, yes conditional on an explicit cross-context/track comparison guard. That guard is now stated in the comparison contract, along with text-only other-track indicators and coverage terminology. These final clarifications were applied after the round-3 reviews and have not received a further review pass. All round-2 blockers were confirmed resolved by both reviewers. No implementation validation is claimed.

| Category | Sol round 1 | Muse round 1 | Sol round 2 | Muse round 2 | Sol round 3 | Muse round 3 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Diving/domain fidelity | 7 | 3 | 8 | 7 | 9 | 9 |
| Family/scope model | 6 | 4 | 7 | 7 | 9 | 8.5 |
| Technique lifecycle/mixed practice | 6 | 3 | 8 | 8 | 9 | 8.5 |
| Modifier compatibility | 8 | 7 | 9 | 7 | 9 | 9 |
| Comparison/statistical honesty | 6 | 4 | 8 | 6 | 9 | 8.5 |
| Mobile chart/readability | 5 | 4 | 8 | 6 | 8 | 8 |
| Logging UX/burden | 5 | 3 | 8 | 7 | 8 | 8 |
| History/provenance/edit safety | 5 | 4 | 7 | 8 | 9 | 8.5 |
| Implementation/data integrity/scalability | 6 | 5 | 7 | 6 | 9 | 8 |
| MVP focus/value | 6 | 4 | 7 | 7 | 8 | 9 |
| Overall | 6 | 4 | 7.5 | 7 | 8.8 | 8.5 |
