# SUBJECT_GT_MINIMUM_ANNOTATION_PLAN_V1 — PLAN ONLY (no labels collected)

Packet: `DIVE_ANALYZER_SUBJECT_RESOLUTION_COHORT_EXPANSION_V1`
Status: plan for supervisor approval. **No annotation is performed in this packet.**

## Why annotation is required

Existing human authority for STANDING/ARMSTAND is sparse event-frame boxes
(2–9 per dive). A deterministic geometry-only continuation from these anchors was
tested this packet and is NOT defensible as GT: multi-anchor chains disagree
(676: 49 conflicting frames / 148 covered at 0.8 s spacing; 133/2387/311: zero
consistent overlap), and forward-walk survival is median 0.73 s (p25 0.17 s).
Model outputs (D5 top-1, OSNet similarity, PersonTrack, old selectors) are
forbidden as GT authority (no self-labeling invariant).

## Level A — reference correctness (recommended first)

Question answered: *was the selected stable/reference interval actually the
intended subject?*

- **Which dives**: STANDING 133, 311, 676, 2387 (cohort members with fresh
  frozen D5 + OSNet caches). ARMSTAND 2661/2680 deferred until proxies are
  materialized (separate bounded packet).
- **Which frames/windows**: human-verified identity anchors inside the eval
  window `[0, water_contact + 0.5 s]` at **0.5 s spacing** (the measured
  walker-survival p25 is 0.17 s, median 0.73 s; 0.5 s spacing keeps every
  plausible reference interval covered by ≥1 anchor while bounding cost).
  Where two people are within ~0.1 normalized distance, add an extra anchor.
- **What the user must identify**: for each sampled frame, click/box the
  intended subject (the diver performing the dive), or mark `NOT_VISIBLE`.
  Format identical to existing `DEVELOPMENT_DESIGN` / D4/D5 batch annotations
  (`{frame_id, dive_id, frame_index, bbox [x1,y1,x2,y2] px, visibility,
  state: HUMAN_REVIEWED, annotator, annotated_at}`) so derivation tooling is
  uniform.
- **Estimated annotation units**: 133 → 7, 311 → 31, 676 → 11, 2387 → 12
  (61 boxes total at 0.5 s; ~122 if 0.25 s chosen for the two long clips).
- **Why necessary**: without an anchor inside a candidate reference span,
  reference subject-correctness is unmeasurable; with it, Level-A metrics
  (reference subject-correct, rank of best subject reference, top-k subject
  availability) become evaluable on STANDING immediately, giving a genuine
  2-family learned experiment (9 dives) for the reference-acquisition scorer.

## Level B — downstream framewise matching (deferred)

Question answered: *how much of the full subject trajectory was correctly
recovered?* Requires per-frame chain authority comparable to HURDLE
`target_chains_v1` (human anchors at 60 fps audit + validated chain
construction). Estimated cost: hundreds of boxes per clip. NOT planned now;
do not attempt before Level-A science has justified the investment.

## Explicitly forbidden

- Human event timestamps + D5 nearest-person ⇒ "subject GT" (self-labeling).
- Geometry-only walker chains as GT (measured unreliable this packet).
- Any use of 2555 / 524 / Paris / INTERNAL_EVAL / holdout in this work.
