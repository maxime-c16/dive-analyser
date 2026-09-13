# DIVE_ANALYZER_SUBJECT_RESOLUTION_V1

**Packet:** DIVE_ANALYZER_SUBJECT_RESOLUTION_V1 (Dive Analyzer only; Core Detection / DiveSensei out of scope)
**Date:** 2026-09-13
**Branch:** `subject-resolution-v1` (base `c4c9cfc1…`, repair commit `3dafd8b`)
**Gate:** `SUPERVISOR_REVIEW_AFTER_SUBJECT_RESOLUTION_V1`
**Companion:** `docs/audits/DIVER_ID_19_PHANTOM_REPAIR_V1.md` (Phase 1, GREEN)

---

## 1. Scope and discipline

This packet closed two things:

1. **Phase 1 — the diver_id=19 "RIP" phantom** (live DB repair, supervisor-authorized):
   root cause proven, parser fixed + deployed, 6 rows repaired in one explicit
   transaction, zero collateral change. Full detail in the repair audit; not
   repeated here.
2. **Phases 2–12 — subject resolution science** on the frozen V1 cohort
   {1040, 2169, 2341, 2353, 2541}, reusing 100% of frozen caches
   (D5 floor candidates, 579,709-key OSNet embedding cache, GT chains) with
   **zero** new detections/embeddings/training/labels/B2 writes.

GT chains were used **for evaluation only**. Nothing in the inference path saw GT.

## 2. What was measured

### PersonTrack construction (Phase 4/6) — NOT the main lock

Union-find agglomerative merge over all plausible floor-candidate tracklets
(endpoint IoU ≥ 0.3 OR cos ≥ 0.80, gap ≤ 0.5 s):

- Subject **tracklet** coverage: 1.0 on all 5 dives — every GT subject frame is
  contained in *some* tracklet.
- Subject **merged-track** coverage: 1.0 / 1.0 / 0.894 / 0.995 / 1.0.
- Tracklets are heavily fragmented (subject spans 15–161 tracklets per dive;
  longest single run 5.69 s on 2169, only 0.55 s on 2341).
- Naive merging is **degenerate**: the biggest merged group per dive is a mega
  distractor cluster (same collapse as V4 bounded-degree linkage).

### Junk taxonomy (Phase 5) — safe by construction for movers

Area < 0.02 or micro-span/conf → `NON_PERSON_LIKELY`; static stable person-sized
→ `PERSON_NON_DIVER_POSSIBLE`; moving excursion ≥ 0.20 → `VALID_PERSON_TRACK`.
Counts stay honest (e.g. 2541: 497 junk / 117 valid movers / 409 unknown) and
movers — including the next-diver trap on 2341 — survive the filter. Junk
elimination is not the bottleneck: the problem is choosing among hundreds of
surviving person tracks.

### R0 — GT-free within-clip reference acquisition (Phase 7) — THE REAL LOCK

A stable reference (flow-compensated, cy_std ≤ 0.03, span ≥ 2 s) followed by
OSNet-cos subject retrieval reaches, with the **oracle** reference:

| dive | oracle ref | GT@1 | longest wrong run |
|---|---|---|---|
| 1040 | tid914 | 0.689 | 0.97 s |
| 2169 | tid245 | 0.873 | 0.45 s |
| 2341 | tid120 | 0.707 | 0.43 s |
| 2353 | tid1471 | 0.788 | 0.65 s |
| 2541 | tid439 | 0.859 | 1.13 s |

So with a good reference, subject-conditioned matching **works** — including
repairs that both D5 top-1 and the audit's H1a GT-prep reference failed
(2341 0.022 → 0.707, 2541 0.005/0.149 → 0.859).

But **no GT-free acquisition rule tested separated the correct reference from
wrong stable tracks on 4 of 5 dives**: longest-span, area×span, max-confidence,
person-size window, leftmost, later-displacement topology, joint ensembles,
single-frame max-conf — all ~0 on 1040/2341/2353/2541. Correct references have
median area 0.038–0.05 yet rank 16–79 by area/span/score: no tested property
separates them. Only 2169 admits a GT-free rule (max-conf stable: 0.885).
**Verdict: `REFERENCE_R0_WITHIN_CLIP = PARTIAL / ACQUISITION_FAILED`.**

### R1 — cross-clip gallery (Phase 7) — REJECTED

- Same-athlete cross-clip reference cos: 0.64–0.81 (1040↔2353: 0.808).
- FANNY reference vs Maxime dive embeddings: 0.591–0.794.
- Cross-athlete cos overlaps same-athlete cos and distractor cos (0.6–0.8):
  raw OSNet cos is not identity-separative across clips.
- **Verdict: `REFERENCE_R1_GALLERY = REJECTED`** — confirms audit H1b; no new
  factor changes separability.

### Ambiguity behaviour (Phase 8/12)

Top-1/top-2 cos margins are tight but nonzero (p50 0.008–0.05) → abstention
thresholds are feasible-in-principle **once a real reference exists**; expect a
need for learned margin calibration. Twin-track trap demonstrated on 1040
(best cos 0.977 is a non-subject static twin; the 0.967 track is 88% subject).

## 3. Honest decision (per supervisor directive)

- **PersonTrack construction is probably no longer the main lock** — subject
  coverage is near-complete wherever tracklets exist.
- **GT-free reference acquisition has become the real lock.** Every bounded
  mechanism tested this cycle failed on 4/5 dives; R1 is dead on raw cos.
- The protocol was **not** changed to chase this inside the packet (explicit
  supervisor directive). It is reported as the open problem, honestly:
  current evidence shows *existence* of good references (oracle ceiling
  0.69–0.87) but no *acquisition* principle.

**Architecture confirmed:** `OPTION_D_HYBRID` (PersonTracks → junk elimination →
subject-conditioned resolution) remains the preferred architecture.
**Next learning problem:** `TRAIN_SUBJECT_CONDITIONED_MATCHER` (unchanged), plus
a new bounded line: **reference-acquisition signal study** — candidate signals
not tested here: temporal position priors relative to dive phases,
board-occupancy topology (who is on the board when), or a learned
stable-reference scorer. Constraints: LOSO-by-dive, no random frame splits,
bounded proposals only.

## 4. Constraints ledger

| Constraint | Value |
|---|---|
| D5 reruns | 0 |
| New embeddings | 0 |
| Training runs | 0 |
| Human labels | 0 |
| B2 writes | 0 |
| Holdout touched | no |
| Paris frames extracted | 0 |
| Frozen-cache recompute | 0 |
| Tests | 33/33 pass |

## 5. Artifacts

- `docs/audits/DIVER_ID_19_PHANTOM_REPAIR_V1.md` — Phase 1 repair (GREEN)
- `experiments/subject_resolution/phantom_repair_v1.sql` — the exact transaction
- `docs/science/DIVE_ANALYZER_SUBJECT_RESOLUTION_V1.json` — machine-readable results
- `mac-agent/src/metadata.py` + `mac-agent/tests/test_metadata.py` — parser fix + 5 regression tests

**Gate: `SUPERVISOR_REVIEW_AFTER_SUBJECT_RESOLUTION_V1`.**
