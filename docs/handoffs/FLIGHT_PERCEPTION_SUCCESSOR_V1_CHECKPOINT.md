# CHECKPOINT — DIVE_ANALYZER_FLIGHT_PERCEPTION_SUCCESSOR_V1 (2026-09-26 ~17:15 CEST)

Resume point if the working session is lost. Not a final report.

## Location / git
- Worktree: `~/.perso/diveanalyzer-flight-perception-successor`, branch
  `dive-analyzer-flight-perception-successor-v1` (tracks `origin/uiux-overhaul-pro-app`, base
  canonical `f1066229e772080bbfd51aaf2ca34b700ab00174`). Canonical = server `diveanalyzer-server:dive-analyser`.
- Commits so far: `525ee82` split authority; `3dfc0be` frozen human authorities + tooling.
- UNCOMMITTED: `experiments/flight_perception/fps_summarize_v1.py`, trainer variants S1/S2 in
  `fps_train_v1.py`, `docs/science/FLIGHT_PERCEPTION_SUCCESSOR_V1_PROTOCOL.md` (draft; §6 to fill;
  must be committed BEFORE loading the holdout), this checkpoint.
- Host artifacts (git-ignored): `runs/flight_perception_successor_v1/` (caches, datasets, models,
  downstream JSONs, MODEL_REGISTRY_V1.json, HQ_REGISTRY_V1.json, PROXY_PTS_INDEX_V1.json),
  `media/fps_v1/` (proxies, hq_b2 originals, proxies_hist).

## Authorities
- Split: `docs/science/FLIGHT_PERCEPTION_SUCCESSOR_SPLIT_V1.json` (session-grouped; no FINAL_HOLDOUT
  exists anywhere; eligible = sessions never used by science; 2584 excluded (session 158 = 2583)).
- `FLIGHT_GT_HUMAN_V2_HOLDOUT` digest `f971294256212070fdae5202db16ca40922a33f84ee732ed00c738e44969392f`
  — SEALED, 9 dives (23, 66, 538, 540, 980, 1555, 2257, 2288, 2498; 4 excluded by Maxime as
  unlabelable: 551, 1190, 1194, 2838). Never read yet. Loader `fps_downstream_v1.load_holdout(sha)`
  requires the protocol committed at HEAD.
- `FLIGHT_TRAIN_HUMAN_V1` digest `05574219f79ee3adcc85ab4542246c199173176a6b1ac8569f94b836b85f1611`
  (16 dives, 176 boxes, k/10 of human flight window).
- Validation = FLIGHT_GT_HUMAN_V1 (740bf71d) on 1304/2204/2223/2526/2583/2839.
- Repeatability 0.004–0.028 norm; 203/262 boxes drawn on HQ frames.

## Media
- HQ: PROD B2 edited renditions via server read-only playback key inside backend container
  (Maxime authorised B2; Photos LaunchAgent export hung in blocked open(), plist removed).
  35 SHA-verified; frozen NCC gate VERIFIED 29; HQ_UNAVAILABLE 538/540/551/66 (aspect/letterbox),
  2636/2838 (content mismatch). Event dives use frozen ANALYSIS_SOURCE_HQ_V1.

## Parity (done)
- New cache script == frozen D5 360 caches byte-identical (1304, 2169, 133); HQ == frozen
  HQ_D5_CANDIDATES_V1 on 8/9 (133: 1/178 frames differ).
- Downstream adapter (frozen FSR search/rank/surface) reproduces sealed FSR 360 funnel: 0 diffs / 15 dives.

## Models (MODEL_REGISTRY_V1.json; all EXPERIMENTAL; frozen D5 82b420c4 untouched)
- S0_pilot_DS0 (D5 init, DS0 = HIST(-524/2555) + FGT1 event boxes) sha 3f8b10bc…
- S1_D5init_DS1 (D5 init, DS1 = DS0 + FTR1) sha a4b188fb…
- S2_COCOinit_DS1 (COCO yolov8n init, DS1) — training at checkpoint time (chain script
  `runs/flight_perception_successor_v1/chain_s1s2.sh` also caches + evaluates it on validation).
- Recipe: yolov8n, imgsz 640, 60 epochs fixed, batch 16, MPS, amp False, last.pt, BASE_AUG.

## Validation selection score (top5 360+360hq, pool, graph, presence@0.10)
- D5 (2, 2, 10, 0.471); S0 (5, 6, 8, 0.566); S1 (5, 4, 6, 0.528); S2 pending.
- Mechanism seen: successor raises subject confidence and margin vs nearby people (2204 conf
  0.07→0.45, rank 0); cost: fewer low-conf boxes / misses on rare poses (2839 twisting).

## Remaining steps
1. `python3 fps_summarize_v1.py select FGT1 D5 S0_pilot_DS0 S1_D5init_DS1 S2_COCOinit_DS1` → pick
   by protocol §4 lexicographic rule; fill protocol §6 (variant, dataset digest, ckpt sha); commit.
2. Caches for chosen successor on holdout dives (360 + hq; D5 holdout caches already exist):
   `fps_detector_cache_v1.py <key> 360|hq 23 66 538 540 980 1555 2257 2288 2498`.
3. `fps_downstream_v1.evaluate(key, 'FGT2H', protocol_sha)` for D5 and successor; summarize with
   `fps_summarize_v1.py table FGT2H ...`; apply protocol §5 rules.
4. Report `docs/science/DIVE_ANALYZER_FLIGHT_PERCEPTION_SUCCESSOR_V1.md` + JSON, tests, PROJECT_STATE,
   merge into canonical (server), push mac-mirror, memory note. Gate
   `SUPERVISOR_REVIEW_AFTER_FLIGHT_PERCEPTION_SUCCESSOR`.
