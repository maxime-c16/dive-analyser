# Dive Analyzer — Flight Search Recovery V1

Packet: `DIVE_ANALYZER_FLIGHT_SEARCH_RECOVERY_V1` · Gate: `SUPERVISOR_REVIEW_AFTER_FLIGHT_SEARCH_RECOVERY`
Metrics: `DIVE_ANALYZER_FLIGHT_SEARCH_RECOVERY_V1.json` · Protocol (frozen before sealed eval):
`FLIGHT_SEARCH_RECOVERY_V1_PROTOCOL.md` (sha256 `5c3fb344…`, commit `3317d70`) · New human
authority: `localization_annotations_v1/FLIGHT_GT_HUMAN_V1/` (digest `740bf71d…`, commit `fddfe4c`).

## 1. Conclusions

1. **Search can be made materially better, but flight construction under clutter remains the
   blocker.** A redesigned search (global track-before-detect DP over non-static D5 floor
   candidates + ballistic flight-segment ranking) surfaces the HUMAN-verified subject flight
   in its top-5 on **3/15** dives at 360p (frozen V3: **2/15**, and frozen V3's search pool
   recovers **0/15**). With 360p+HQ merged, 4/9 event dives are surfaced (top-10); a
   post-sealed GT-free-validated ranker fix puts every surfaced case at rank 1 (4/9), i.e.
   **ranking is no longer where it dies**.
2. **The dominant loss is search construction (8/15 at 360p):** the subject flight is observed
   (raw ≥ 75 % on 11/15) and reachable in the gated graph (11/15), but no constructed
   hypothesis follows it. Mechanism (sealed post-hoc diagnosis): mid-flight the airborne
   subject has **lower D5 confidence than nearby real people** (e.g. 2353: subject median
   0.017 vs hijacker 0.13), so evidence-driven search is captured by them; confidence-agnostic
   variants are captured by dense clutter instead. Appearance does not separate them
   (frozen OSNet cosine AUC 0.59), so identity/ReID is not the missing piece.
3. **The design-time authority was biased toward the detector.** Every pre-existing human
   box near the flight (DEVELOPMENT landmark boxes, D5-mined hurdle seeds) is a D4/D5
   training/validation label; at those frames the subject is found at confidence-rank 0.
   DEV results over-stated recovery (top-5 5/9 vs sealed 2–3/9) and systematically favoured
   confidence-reliant designs. Mid-flight human authority did not exist before this packet.
4. **1080p helps observation, not construction.** HQ raises raw presence where 360p
   localization is off (133: 0.71 → 1.0) and is complementary to 360p (different dives
   succeed; union > either), but HQ alone surfaces 0/9 at top-5 with the frozen ranker (2/9
   with ranker v2) and frozen V3 on HQ surfaces 0/9. The HQ floor saturates the frozen
   200-candidate cap on most frames.
5. **Manual multi-track selection is not yet viable** (≤ 4/9 event dives, 3/15 overall at K=5).

## 2. Retention funnel (sealed authority FLIGHT_GT_HUMAN_V1, rule: hits ≥ 2, coverage ≥ 0.75, purity ≥ 0.75, radius 0.06)

| stage | V3 360p (15) | FSR 360p (15) | V3 HQ (9) | FSR HQ (9) | FSR 360p+HQ (9) |
|---|---|---|---|---|---|
| S0 raw floor presence ≥ 0.75 | 11 | 11 | 8 | 8 | 8 |
| S1 search lattice presence | 10 | 11 | 8 | 8 | — |
| S2 graph reachable (GT-guided oracle) | 9 | 11 | 6 | 8 | — |
| S3 search pool | **0** | **3** | **0** | **2** | — |
| S3b any extracted candidate | — | 3 | — | 2 | 4 |
| S4 surfaced top-1 / top-5 / top-10 | F1 top-5: 2 | 2 / 3 / 3 | F1 top-5: 0 | 0 / 0 / 2 | 1 / 2 / 4 |
| post-sealed ranker v2 top-1 (adaptive) | — | 3 | — | 2 | 4 |

Strict subset (dropping the 2 queue items that coincide with D5-mined frames): identical
conclusions (JSON `funnel.strict`). Loss stage per dive, FSR 360p: SURFACED 1040, 2541, 676;
OBSERVATION 133, 311, 1304, 2204; CONSTRUCTION 2169, 2223, 2341, 2353, 2387, 2526, 2583, 2839.

## 3. Human GT authority

- **New:** `FLIGHT_GT_HUMAN_V1` — 123 blind human boxes (no detector output, no drafts) at
  fractions k/8 of the HUMAN flight window: 7 interior frames on 9 event dives, 9 frames on
  the 6 Level-B dives whose takeoff/water-contact Maxime marked in the tool (final takeoff
  after the last bounce). 115 visible, 1 partial, 5 not visible, 2 ambiguous; repeat items
  0.010–0.039 normalized centre distance (≪ 0.06 radius). Frames shown as HQ resampled to
  proxy geometry where the map is identity and verified; stored in proxy pixels. 1304's first
  event marks (4.3 s window through bounces) were archived and re-marked (1.43 s).
- **Audit of pre-existing authority:** landmark boxes = D5 training labels (in-sample);
  hurdle `HUMAN_GT` seeds = D5 mining frames; 1040/2541 seeds are `VISUAL_EVALUATOR`
  (agent-eyeballed); hurdle chains are evaluator-seeded, interpolated and D5-snapped (raw
  union = 1.0 by construction). 2169 apex landmark is "no diver visible".
- Only 2 of the 123 new items coincide with D5-mined frames (reported as the strict subset).

## 4. What changed and why

| change | why | status |
|---|---|---|
| `fsr_search_v1` global evidence DP (per-node best-through paths) | removes V3's three search leaks by construction (no seeding strata, no beam eviction, no harvest timing); motion gate expressed as position residual relative to capped box size | frozen, evaluated sealed |
| static-persistence node mask | removes ~45 % of candidates, keeps 99–100 % of subject anchors | frozen |
| `fsr_rank_v1` ballistic segments + detection evidence | V3's Q excursion term grows monotonically with segment length; flight = downward-curved arc with drop | frozen |
| `fsr_pipeline_v1` segment candidates, 360p/HQ merge | surfaced unit must be a flight, not a clip-long path | frozen |
| `fsr_rank_v2` trim-and-rescore | GT-free synthetic test: v1 extends segments into junk continuations (6/10 → 8/10) | post-sealed, not promoted |
| `fsr_hq_cache_v1` HQ D5 caches | 1080p question with frozen weights/recipe; maps verified by blurred NCC | host cache |
| 311 HQ trim 12.125 → 12.145 s | every motion sample preferred the previous HQ frame; sub-frame NCC scan peak | caveat on manifest |
| annotation tool | blind human flight authority | frozen GT |

## 5. Verified defects (independent of the previous audit)

- **V3/r5 motion-gate unit error — confirmed:** 29–46 % of the subject's own consecutive flight
  steps violate V3's per-second caps applied to single-frame velocity (single-frame p90
  1.6–3.2 norm/s vs 0.5–0.8 over a 0.2 s baseline).
- **r5 size gate** (`log 2.2`) rejects ~10 % of subject steps (rotating diver area change p90 0.94).
- **V3 pool never recovers** (0/15 sealed; its only recoveries come from F1 extension).
- **Global-optimality duration bias** (new): any globally optimal path through a subject node
  prefers continuing onto a longer-lived, brighter person after entry (and mid-flight).
- **Ranking extends into junk continuations** (new, fixed in rank v2).
- **DEV authority is detector-in-sample** (new; affects V3 "observation complete" statements).
- **311 HQ trim offset** off by ~0.6 frame (20 ms): negligible for event labels, relevant for
  frame-exact HQ box transfer.

## 6. Experiments that failed (all DEV-designed unless noted; numbers in JSON/protocol)

motion-reward DP (clutter surfing, fabricated 13-unit paths); motion-gated evidence (crowd
hop fabrication, 3/9); step-LLR DP (duration bias, 3/9); greedy multi-track (pure fragments,
1/9); windowed DP (4/9); evidence caps EV_MAX 0.5–2.0 (DEV 2–4/9; sealed 2–4/15 pool);
merged 360p+HQ lattice (4/9); POOL_MAX 200 (no gain); post-sealed confidence-agnostic
ballistic micro-tracklet chaining, DP (pool 3/15) and greedy (360p+HQ 4/9) — same ceiling;
OSNet appearance continuity rejected on discriminability (AUC 0.59).

## 7. Remaining blocker and recommendation

The blocker is **flight-phase observation quality feeding construction**: airborne detections
are low-confidence and box-offset relative to nearby people, so no search tested (5 families)
constructs the flight on more than ~4/9 event dives. Search/ranking levers inside the frozen
detector are largely exhausted. Recommended next packet (needs supervisor authority):
**flight-phase detector data** — a bounded D5 successor trained with the recovered HQ sources
and the new mid-flight human boxes as *training* data only after a fresh held-out flight
authority exists (the 6 unused proxies 2498/2584/2838/540/551/66 have unverified split
authority and were not touched). Keep FLIGHT_GT_HUMAN_V1 as design authority from now on
(it is burned for v2 selection).

## 8. Boundaries, resources, tests

- DEVELOPMENT only; Paris, INTERNAL_EVAL (160/169/191/192/2281/848), FINAL_HOLDOUT, 524,
  2555 untouched. No D5 training/weight change (HQ inference with frozen weights only). No
  B2/media-backbone mutation. Event Logic untouched. Frozen V3 and caches SHA-verified.
- Heavy runs on the M2: HQ D5 inference 9 dives ≈ 2.5 min sequential; V3 sealed funnel 24 jobs
  (4-way parallel). Host artifacts under `runs/flight_search_recovery_v1/` (git-ignored):
  `HQ_D5_CANDIDATES_V1.json`, `HQ_ALIGNMENT_VERIFY_V1.json`, `v3_on_hq/`, `final_eval/`,
  `pool_cache/`, `flight_gt_annotation/`.
- Tests: `test_flight_search_recovery_v1.py` 19 passed (GT-free inference path, protocol freeze,
  sealed-authority guard, protected firewall, static mask, synthetic recovery + determinism,
  ballistic score, ranker v2 fix, HQ maps, HQ timeline/recipe, frozen V3/caches, queue rule,
  blind UI). Legacy: `test_flight_anchored_traj_v3.py`, `test_audit_flight_path_recall_v1.py`.
