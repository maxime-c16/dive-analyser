# SUBJECT_GT_LEVEL_B_ANNOTATION_PLAN_V1

Packet: `DIVE_ANALYZER_INDEPENDENT_SUBJECT_GT_EXPANSION_V1`
Date: 2026-09-13
Status: FROZEN PLAN (queue built, frames extracted, UI verified)

## Purpose

The 6 new independent dives need a **Level-B subject-identity authority**:
enough HUMAN_REVIEWED identity evidence across each dive to determine which
frozen-D5 candidate PersonTracks/tracklets correspond to the intended product
subject throughout the scientifically relevant interval (here: the full clip,
because no event-GT authority exists for the new dives).

Level-B must support: reference identity, track identity, identity-switch
evaluation, subject vs other-real-person negatives.

## Minimum-density derivation (Phase 9, minimize human work)

Evidence used (no self-labeling, no algorithm ranking):

1. **Cohort track-fragmentation evidence** (Subject Resolution Cohort
   Expansion V1): deterministic geometry-only continuation from sparse
   anchors FAILED defensibility on STANDING (676: 49 conflicting frames of
   148 at 0.8 s spacing; walker survival median 0.73 s, p25 0.17 s). A 0.5 s
   anchor grid was adopted for Level-A for exactly this reason.
2. **V3 evidence**: the remaining decoys are SUPPORTED real-person movers and
   subject-adjacent association fragments (purity up to 0.67) — identity
   ambiguity concentrates at moments when two people are close. The frozen
   Level-A close-person extra rule (two distinct supported candidates within
   0.10 mean-bh center distance, IoU < 0.50 → +0.25 s anchor) is the right
   ambiguity sensor and is REUSED unchanged (no new constants).

### Plan

- Base grid: 0.5 s over the FULL clip (`frame = round(t*fps)`).
- Close-person extras: +0.25 s anchor at any base frame with a close pair
  (frozen constants: conf ≥ 0.05, dist < 0.10 mean-bh, IoU < 0.50).
- Propagated drafts (Phase 10): for an unresolved item, if the nearest
  earlier human box of the same dive is ≤ 1.0 s away, the best-IoU supported
  frozen-D5 candidate (gate IoU ≥ 0.40, conf ≥ 0.05) is offered as a DRAFT.
  A draft is authority ONLY after explicit human ACCEPT / CORRECT.
  `AUTO-PROPAGATED != HUMAN_REVIEWED`. No silent interpolation anywhere.

## Queue (SUBJECT_GT_LEVEL_B_QUEUE_INDEPENDENT_V1)

Byte-reproducible (stamp = sha256 of the frozen D5 cache). All constants are
reused frozen Level-A constants. Blindness: no A0/A1 ranking, no V3 support
score, no OSNet identity score, no selector result shown or stored.

| dive | diver | session date | clip end | base | extras | total |
|---|---|---|---|---|---|---|
| 1304 | FANNY | 2025-10-28 | 6.60 s | 14 | 0 | 14 |
| 2223 | LOUIS | 2026-04-07 | 9.82 s | 20 | 2 | 22 |
| 2204 | FANNY | 2026-04-07 | 8.58 s | 18 | 0 | 18 |
| 2526 | MAT | 2026-05-30 | 15.92 s | 32 | 19 | 51 |
| 2583 | MAXIME | 2026-07-08 | 9.58 s | 20 | 16 | 36 |
| 2839 | MAXIME | 2026-09-06 | 17.50 s | 36 | 3 | 39 |
| **total** | | | | 140 | 40 | **180** |

The extras concentrate on the two richest multi-person scenes (2526, 2583) —
exactly where identity ambiguity lives.

## Workflow

```text
python3 experiments/subject_resolution/phase_subject_gt_level_b_annotation_v1.py serve
→ http://127.0.0.1:8766
frame → identify intended subject → draw / ACCEPT draft / correct → save → next
SAVE (s) | ACCEPT DRAFT (a) | NOT_VISIBLE (n) | BACK/NEXT (arrows)
```

UI shows: dive id, diver, frame, t, progress. It does NOT show any
algorithm ranking/support/identity score.

## Schema

Per anchor (one JSON file per anchor under
`docs/science/localization_annotations_v1/SUBJECT_GT_LEVEL_B_INDEPENDENT_V1/`):

```text
id L1B_<dive>_f<frame>
dive_id, diver, family, frame_index, pts_s, rel_clip_time_s, reason
bbox [x1,y1,x2,y2] px on 202x360 proxy_360p frame  | null
visibility visible | not_visible
method human_drawn_or_corrected |
        human_accepted_propagation_draft | human_not_visible
authority HUMAN_REVIEWED
annotator maxime
source_identity intended Dive Analyzer subject
media_sha256 (proxy), image_sha256 (extracted frame), representation
provenance {origin, queue, packet, d5_cache_sha256}
```

Track identity is derived OFFLINE by deterministic IoU matching against
these human boxes; the annotator never self-labels tracklets.

## Effort estimate

180 review units at 0.5 s spacing (Level-A: 63 units across 4 dives);
estimated 45-75 minutes.
