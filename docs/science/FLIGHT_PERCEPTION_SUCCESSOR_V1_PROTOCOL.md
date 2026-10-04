# FLIGHT_PERCEPTION_SUCCESSOR_V1 — protocol (frozen before the sealed holdout is loaded)

Packet: `DIVE_ANALYZER_FLIGHT_PERCEPTION_SUCCESSOR_V1`. Split authority:
`FLIGHT_PERCEPTION_SUCCESSOR_SPLIT_V1.json` (committed `525ee82`, before any new label or
model). `fps_downstream_v1.load_holdout()` refuses to load `FLIGHT_GT_HUMAN_V2_HOLDOUT`
unless this exact file is committed at HEAD.

## 1. Question

Does a flight-focused successor of frozen D5 materially increase usable airborne-subject
proposals and downstream candidate-trajectory recall, with the trajectory algorithm unchanged?

## 2. Roles

| role | content | use |
|---|---|---|
| TRAIN / DESIGN | historical D4/D5 labels minus 524/2555; FLIGHT_GT_HUMAN_V1 boxes on the 9 event dives; FLIGHT_TRAIN_HUMAN_V1 (new) | training only |
| MODEL-SELECTION VALIDATION | FLIGHT_GT_HUMAN_V1 on the 6 Level-B dives 1304/2204/2223/2526/2583/2839 (never in D-series training) | every model/recipe decision |
| FRESH FLIGHT HOLDOUT | FLIGHT_GT_HUMAN_V2_HOLDOUT, 10 sessions never used by science | loaded once, after this commit, for frozen D5 vs the frozen successor |

## 3. Frozen measurement

- Detector recipe for every cache: conf floor 0.001, NMS 0.45, imgsz 640, cap 200, MPS,
  sequential decode; representations `360` (production proxy) and `hq` (verified edited
  rendition mapped to the proxy frame/timeline; dives failing the frozen NCC gate are 360-only).
  No representation-specific threshold anywhere.
- Downstream = frozen FLIGHT_SEARCH_RECOVERY_V1 search/rank/surfacing, byte-unchanged
  (adapter `fps_downstream_v1` only swaps the candidate source; parity with the sealed FSR
  funnel verified: 0 differences on 15 dives at 360p).
- Recovery rule (frozen V3/FSR): hits ≥ 2, coverage ≥ 0.75, purity ≥ 0.75, radius 0.06.
  Flight anchors: visible|partial items with PTS in [takeoff − 0.05, water_contact + 0.05].
- Proposal metrics per anchor: presence (0.06 radius), subject confidence, confidence rank,
  margin vs best non-subject candidate (> 2·radius away), best IoU vs HUMAN box, presence at
  conf ≥ 0.05 / 0.10 / 0.25. Continuity: S2 graph reachability (primary) and the INTERP
  diagnostic (dense presence near the linear interpolation of HUMAN anchors — diagnostic only).

## 4. Model-selection rule (validation only)

Candidates are compared on the 6 validation dives. Score, lexicographic:
1. surfaced top-5 dives, summed over representations {360, 360+hq};
2. S3 pool recovered dives (360 + hq);
3. S2 graph-reachable dives (360 + hq);
4. mean anchor presence at conf ≥ 0.10 (360 + hq).
The chosen successor is frozen (checkpoint SHA recorded below) before the holdout is loaded.

## 5. Holdout decision rules (pre-registered)

Primary representation: `360+hq` surfaced list (HQ where the map is verified, 360 otherwise);
`360` alone reported alongside. Evaluable holdout dive = ≥ 2 flight anchors.

- **Material improvement (successor promoted for further science):** successor − D5 ≥ +2
  evaluable holdout dives in surfaced top-5 AND mean anchor presence at conf ≥ 0.10 not lower.
- **Manual multi-track selection viable:** successor top-5 ≥ 60 % and top-10 ≥ 70 % of evaluable
  holdout dives.
- Otherwise: report the stage where subject recall is lost (S0/S2/S3/S4) per dive.

## 6. Frozen successor identity

Selected by the §4 rule on validation only (score = top-5 sum, pool, graph, presence@0.10):

| candidate | score |
|---|---|
| frozen D5 | (2, 2, 10, 0.471) |
| S0_pilot_DS0 (D5 init, existing labels) | (5, 6, 8, 0.566) |
| S1_D5init_DS1 (D5 init, + FLIGHT_TRAIN_HUMAN_V1) | (5, 4, 6, 0.528) |
| **S2_COCOinit_DS1** (COCO yolov8n init, + FLIGHT_TRAIN_HUMAN_V1) | **(7, 7, 8, 0.632)** |

Frozen successor: `DIVER_DETECTOR_FPS_S2_COCOINIT_DS1` (experimental) = variant `S2_COCOinit_DS1`,
yolov8n, init COCO `yolov8n.pt` (sha `f59b3d833e2ff32e194b5bb8e08d211dc7c5bdf144b90d2c8412c47ccfc83b36`), dataset `DS1_HIST_FGT1_FTR1`
(digest `c1daa81384bc2ac1fb4641cf0041d83428bc6d61a61ff3592c2681181a5f49db`), 60 epochs, imgsz 640, batch 16, MPS, amp False, `last.pt`,
checkpoint sha256 `d3ba0b035e7a8eb20bb5af66db62984bfb4682075b0c1267677d293e0e9d9c7f`. Reference: frozen D5 `82b420c4583f8271b1eb3429b14dadf0a1e27477249de7b6a0b9d42a788dcf25`.
