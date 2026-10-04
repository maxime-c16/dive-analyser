# DIVE_ANALYZER_SUBJECT_GT_LEVEL_A_ANNOTATION_V1

Packet: `DIVE_ANALYZER_SUBJECT_GT_LEVEL_A_ANNOTATION_V1`
Gate: `SUPERVISOR_REVIEW_AFTER_SUBJECT_GT_LEVEL_A_ANNOTATION_V1`
Date: 2026-09-13
Branch: `subject-gt-level-a-annotation-v1` (base = canonical `uiux-overhaul-pro-app` @ `bf78182`)

## Phase 0 — Fresh preflight

- Packet-stated HEAD `f00dffd74ad0b1cc3d029c4bfa76bd80e8b3744e` verified as an
  ancestor of current server canonical `origin/uiux-overhaul-pro-app`; canonical
  advanced to `bf78182` (concurrent UI-U1/U2 integration recorded on top of the
  Cohort Expansion merge `f00dffd`). Science content of `f00dffd` verified intact
  (report, plan, caches all present and SHA-verified). Branch cut from `bf78182`.
- Dedicated worktree `~/.perso/diveanalyzer-subject-gt-l1a`
  (branch `subject-gt-level-a-annotation-v1`). Concurrent threads untouched:
  UI (`diveanalyzer-perception` dirty main worktree), core-detection,
  media-backbone P8/P9/P10, identity-v2, sci-v2, cohort-exp, subject-resolution.
- Frozen authority re-verified by SHA: D5 `82b420c4…`, OSNet `2809d322…`,
  frozen D5 cohort cache `b2f01e41…`, STANDING proxies (4/4 match cache).
- V2 module byte-identity pinned: `subject_reference_acquisition_v2.py`
  sha256 `01a17dd77131076d323b4adbc0790ac1d284f36fe39ebfb98a0ef64ad7a1d73e`.

## Phase 1 — Deterministic annotation queue

`docs/science/SUBJECT_GT_LEVEL_A_QUEUE_STANDING_V1.json` — regenerated from the
frozen `SUBJECT_GT_MINIMUM_ANNOTATION_PLAN_V1`; **byte-identical on re-run**.

- Eval window `[0, water_contact + 0.5 s]` from the frozen DEVELOPMENT_DESIGN
  water-contact authority (133 f88, 311 f444, 676 f145, 2387 f164).
- Base grid 0.5 s ⇒ 7/31/11/12 = 61 anchors (exactly the approved plan).
- Close-person rule (deterministic, from the frozen D5 cache): two distinct
  candidates (conf ≥ 0.05, IoU < 0.5) with center distance < 0.10 mean-bh at a
  base frame ⇒ one extra anchor at ±0.25 s. Fired on 133 (t=0.0) and 2387 (t=0.0).
- **Reuse outcome: 0 reused / 63 new.** Two exact-frame candidates existed
  (676 f30 D4 batch, 676 f150 D5 batch) but D4/D5 mining boxes carry generic
  *diver-box* semantics, not *subject-identity* semantics; reusing them would
  silently upgrade their meaning. Both were labeled fresh; historical artifacts
  untouched. (Upper-bound plan was ~61; final 63 = 61 base + 2 measured extras.)

## Phase 2/3/4/5 — Human annotation session

Blind local web UI (127.0.0.1 only): open frame → drag bbox → SAVE SUBJECT BOX
/ NOT_VISIBLE; BACK/NEXT; progress persisted per action. No A0/A1/D5/OSNet
rankings, no reference-acquisition output, no selector hints displayed. D5
boxes were NOT used as a drawing aid (manual placement only).

`HUMAN_SUBJECT_GT_ANNOTATION_REQUIRED` was raised and fulfilled in-thread:
**63/63 annotated by Maxime in one session** (58 visible boxes, 5 NOT_VISIBLE),
no review corrections requested.

## Phase 6/7 — Schema + mechanical validation

Existing `localization_annotations_v1` semantics, extended with
`source_identity` ("intended Dive Analyzer subject") and `provenance`.
Validation **PASS** on all checks: bbox inside 202×360 bounds, positive
width/height, source/frame identity, no duplicate conflicts, explicit
NOT_VISIBLE, all 63 queue items resolved, existing human anchors preserved
(semantic-field comparison vs the V1 freeze — see test note: 12 files were
re-saved by packet `daae424` changing ONLY `reviewed_at`; pre-existing, out of
scope). Model agreement was NOT used as a quality criterion.

## Phase 8 — Consistency review

- Jump scan: max consecutive-anchor shift 1.06 bh / 0.5 s (walking pace);
  no swap-like jumps (> 2 bh).
- Static-run scan: no identical-box runs ≥ 5 (no non-person structure boxed).
- Examined and accepted: 311 f435 generous box (0.77 clip width) during fast
  descent — overlaps the conf-0.35 D5 person cluster; human authority stands.
- Nothing returned to the annotator.

## Phase 9 — Level-A authority frozen

`docs/science/localization_annotations_v1/SUBJECT_GT_LEVEL_A_STANDING_V1/`
(63 anchor files + `MANIFEST.json`):

- artifact SHA256 `d805aac2b46e52f002de2842b56bb9a1b0ced808f0862a4c559f5ffe9099a75e`
- dives 133/311/676/2387, annotator `maxime`, authority `HUMAN_REVIEWED`
- 8/31/11/13 annotations per dive; 5 NOT_VISIBLE (post-entry submersion /
  mid-flight non-identifiability)
- provenance: queue SHA, proxy SHAs, per-frame image SHAs recorded

## Phase 10 — No full-trajectory GT

No interpolation performed; nothing densified. Level-B remains unauthorized.

## Phase 11 — Frozen V2 replay (zero changes)

A0/A1 replayed on STANDING from the frozen GT-free cache with the frozen
module (SHA-pinned) and constants asserted against the V2 freeze artifact:
**A0 changed: NO · A1 changed: NO · D5 rerun: NO · OSNet rerun: NO**
(OSNet never loaded; downstream matching not in scope). All 8 top-1 selections
(A0+A1 × 4 dives) match the frozen cohort replay exactly (tid + score).

## Phase 12 — Level-A reference correctness (STANDING)

Subject candidate ≡ consistent (center distance ≤ 0.06, project
`reference_purity` precedent) with **every** visible human anchor its tracklet
covers. Reference verdict = top-1 purity over visible anchors inside its span.

| Dive | A0 verdict | A0 purity | A1 verdict | A1 purity | best subj rank A0/A1 (strict) | (p ≥ 0.5) |
|---|---|---|---|---|---|---|
| 133 | SUBJECT_WRONG | 0.00 (0/2) | SUBJECT_WRONG | 0.00 (0/7) | 77 / 17 | 15 / 9 |
| 311 | SUBJECT_WRONG | 0.00 (0/2) | SUBJECT_WRONG | 0.00 (0/7) | 30 / 22 | 30 / 21 |
| 676 | SUBJECT_WRONG | 0.00 (0/2) | SUBJECT_WRONG | 0.00 (0/4) | 22 / 152 | 9 / 4 |
| 2387 | REFERENCE_GT_UNOBSERVED | — | SUBJECT_WRONG | 0.18 (2/11) | — / 92 | 24 / 4 |

**Headline: 0/8 top-1 reference selections subject-correct (0/7 measured;
1 unobserved).** The V2 failure is CONFIRMED on STANDING with true human GT.
2387-A0's selected span (7.12–9.49 s) lies entirely after the eval window —
honestly classified `REFERENCE_GT_UNOBSERVED`, no verdict manufactured.

Correction vs the cohort packet: its "best anchor-consistent rank 3–89" used
2–4 sparse event anchors with single-anchor consistency; the 0.5 s grid +
all-covered-anchors rule yields stricter ranks (17–152 strict). Earlier
optimism quantified and corrected.

## Phase 13 — HURDLE vs STANDING (reported separately)

- **Does V2 fail in both families? YES** (HURDLE 0/5+0/5 recorded; STANDING
  0/4+0/4 measured here).
- **Subject rank distribution similar? NO** — HURDLE best A1 ranks 2–14;
  STANDING strict 17–152 (p05 4–30). STANDING is worse.
- **Dominant negatives similar? NO** — this is the key new finding:
  - HURDLE (recorded V2/R4): stable **static** tracklets outrank the subject.
  - STANDING (measured here): top-1 decoys are **low-confidence phantom
    person-mover tracklets** — mean D5 conf 0.002–0.056, dive-like excursion
    0.21–0.48 cy, terminal toward water, and NO conf ≥ 0.3 person detection
    near them (133/311: 0.5–0.8 normalized from the subject; 2387-A1 tracks
    near the subject early at 0.04–0.07 then drifts, purity 2/11).
- **Static/non-person decoys equally dominant? NO** — family-dependent.
- **Person distractors more important in one family? YES — STANDING**: the
  trap there is motion-plausibility (phantom movers), not static stability.

No pooled-only conclusion drawn; pooling would now be actively misleading
because the dominant failure modes differ by family.

## Phase 14 — Candidate-learning dataset audit (no training)

Statistical unit = dive/session, NOT the candidate box.

| | HURDLE (V2 artifacts) | STANDING (measured here) |
|---|---|---|
| dives | 5 | 4 |
| acquisition candidates | 451/516/545/771/605 (2 888) | 176/424/237/658 (1 495) |
| subject-reference positives | ≥ 1 per dive (per-frame chains) | 2/1/3/6 = **12** (strict union) |
| person-mover negatives | present (multi-person scenes) | 483 |
| static/non-person negatives | dominant decoy class | 396 |
| unobserved / no-anchor-coverage | ~0 (per-frame GT) | **626** |

Cohort totals: 9 dives, 2 families, 1–2 athletes (subject diver_id=1 on 7/9;
diver_id=7 on 2341/676), single venue. STANDING negatives are heavily
correlated within dive (phantom families, static repeats) — candidate counts
must not be read as independent examples.

## Phase 15/16/17 — Learning gate

**`LEARNING_EXPERIMENT_STILL_TOO_SMALL`** — ~17 subject-reference positives
total across 9 dives by 1–2 athletes at one venue, negatives dominated by
within-dive correlated phantom/static families; LOSO folds would rest on ~15
training positives with heavy dependence. Adding ARMSTAND would not change
this verdict.

Learning design: `NOT_AUTHORIZED_YET`. Split recommendation recorded for the
future: LOSO by dive minimum, session-aware grouping preferred, no
generalization-to-unseen-athletes claims from a Maxime-dominated corpus.

## Phase 18 — ARMSTAND decision

**`ARMSTAND_EXPANSION_NOT_NEEDED_YET`** — the binding constraint is
positive-count/label independence, not family count; ARMSTAND proxies/caches
stay deferred.

## Firewalls / resources

524 EXCLUDED, 2555 separated, Paris/INTERNAL_EVAL/FINAL_HOLDOUT NOT_ACCESSED.
0 B2 reads/writes, 0 new D5 inference, 0 new embeddings, 0 training, no media
mutation. 63 frames extracted (outside Git); UI server stopped; frames retained
under `runs/subject_gt_level_a_v1/frames/` for `image_sha256` re-verification
(re-extraction is not byte-deterministic — documented).

## Tests

15 new tests (`test_subject_gt_level_a_annotation_v1.py`): queue determinism,
plan conformance, firewall, schema, bbox validity, human authority, provenance,
frozen A0/A1 identity (module SHA + constants), frozen cache/model SHAs,
existing-anchor preservation. Subject-resolution suite **54/54 green**. The 3
pre-existing cosmetic `test_candidate_reranker.py` failures reproduce
byte-identically — pre-existing historical debt, untouched per firewall.

## Next supervisor decisions

1. Authorize a bounded V3 revision exploring phantom suppression (a-priori
   candidate-quality rule, e.g. minimum track support/confidence), or keep
   A0/A1 frozen and wait for learning.
2. Confirm the semantics call: D4/D5 mining boxes excluded from Level-A reuse
   (documented; historical artifacts untouched).
3. Whether to invest in more sessions/athletes (label independence) vs more
   anchors — learning is blocked on independence, not family count.
4. Approve `SUBJECT_GT_LEVEL_A_STANDING_V1` as the STANDING
   reference-correctness standard for future packets.

## Recommended next gate

`SUPERVISOR_REVIEW_AFTER_SUBJECT_GT_LEVEL_A_ANNOTATION_V1`
