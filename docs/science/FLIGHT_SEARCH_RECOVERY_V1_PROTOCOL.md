# FLIGHT_SEARCH_RECOVERY_V1 — protocol (frozen before sealed evaluation)

Packet: `DIVE_ANALYZER_FLIGHT_SEARCH_RECOVERY_V1`. This document freezes the flight
search, ranking and surfacing pipeline, and the evaluation plan, **before** the sealed
evaluation authority `FLIGHT_GT_HUMAN_V1` (digest `740bf71d…`, committed `fddfe4c`) is
loaded by any search-evaluation code. `fsr_common_v1.load_eval_authority()` refuses to
load it unless this exact file is committed at HEAD.

## 1. Design-time authority (DEV only)

All design decisions used only: DEVELOPMENT landmark boxes (HUMAN, but D4/D5 training
labels), D5-mined HUMAN seeds (D5 training), STANDING Level-A anchors (HUMAN), and the
hurdle chains (CHAIN_DERIVED, diagnostic only) on the 9 event dives. FLIGHT_GT_HUMAN_V1
was annotated blind (no detector output shown) and was never read during design.

## 2. Frozen pipeline

- Input: frozen D5 floor candidate caches, unchanged recipe (conf 0.001, NMS 0.45,
  imgsz 640, cap 200). Representations: `360` (frozen 202x360 proxy caches, 15 dives),
  `hq` (HQ_D5_CANDIDATES_V1: same weights/recipe on the recovered high-res rendition,
  mapped to proxy frame/timeline; 9 event dives), `360+hq` (score-merged surfaced sets).
- Search `fsr_search_v1` MODE=EVIDENCE: static-persistence node mask; forward/backward
  track-before-detect DP F[n] = ev(n) + max(0, max_i F[i] - cost(i,n)),
  ev = clip(ln(conf/C_BG)); residual gate relative to (capped) box size; gap cost per
  missing second; per-node best-through path read-out with novelty dedup.
- Ranking `fsr_rank_v1`: ballistic flight segments (closed-form quadratic y / linear x
  fits on every segment of every pool path; downward-curvature envelope; drop into
  entry, fit residual, missingness, mean detection evidence); up to SEGS_PER_PATH
  time-disjoint segments per path.
- Surfacing `fsr_pipeline_v1`: each segment -> candidate DiveTrack = path observations in
  [t0 - PRE_S, t1 + POST_S]; merged across representations by segment score; duplicate
  suppression; at most MAX_SURFACED.

## 3. Frozen constants

```json
{
 "PIPELINE": {
  "DUP_AGREE": 0.7,
  "DUP_OVERLAP": 0.5,
  "MAX_SURFACED": 50,
  "PIPELINE_VERSION": "FLIGHT_SEARCH_RECOVERY_V1_PIPELINE",
  "POST_S": 0.5,
  "PRE_S": 1.0,
  "XREP_AGREE": 0.8
 },
 "RANK": {
  "C_BG": 0.003,
  "E_MAX": 6.0,
  "E_MIN": 0.2,
  "MIN_SEG_OBS": 6,
  "Q_SEG_MIN": 0.05,
  "SEGS_PER_PATH": 3,
  "SEG_MAX_S": 2.5,
  "SEG_MIN_S": 0.35,
  "SEG_OVERLAP": 0.3,
  "SEG_STRIDE": 2,
  "W_EV": 0.1,
  "W_FIT": 0.1,
  "W_MISS": 0.1
 },
 "SEARCH": {
  "C_BG": 0.003,
  "EV_MAX": 4.0,
  "EV_MIN": -1.0,
  "E_REL_MAX": 0.6,
  "GAP_COST_S": 30.0,
  "KAPPA": 0.3,
  "LAMBDA": 55.0,
  "MODE": "EVIDENCE",
  "NOVEL_MIN_S": 0.25,
  "NULL_MAX_S": 0.3,
  "N_MAX": 200,
  "POOL_MAX": 60,
  "P_D": 0.8,
  "RADIUS": 0.06,
  "REF_DT": 0.03333333333333333,
  "SCALE_CAP": 0.2,
  "SEARCH_VERSION": "FLIGHT_SEARCH_RECOVERY_V1_GLOBAL_DP",
  "SIG_REL": 0.15,
  "SIZE_TOL": 0.7984573603642703,
  "STATIC_OFFS_S": [
   0.1,
   0.2
  ],
  "STATIC_R": 0.008,
  "TAU_SLOW_S": 0.2,
  "TOP_K": [
   1,
   3,
   5,
   10
  ],
  "T_MIN": 3.0,
  "VEL_ALPHA": 0.35,
  "V_MOVE0": 0.12,
  "V_MOVE1": 0.35,
  "V_SMOOTH_MAX": 2.5,
  "W_RESID": 1.0,
  "W_SIZE": 0.5
 }
}
```

## 4. Evaluation plan (sealed authority)

- Flight anchors: FLIGHT_GT_HUMAN_V1 items with visibility visible|partial whose frame PTS
  lies in [takeoff - 0.05, water_contact + 0.05] (event dives: DEVELOPMENT event YAML;
  indep dives: FGT1 human event marks). Repeat items excluded.
- Recovery rule (frozen V3 rule, unchanged): hits >= 2, coverage >= 0.75 of ALL flight
  anchors, purity >= 0.75, match radius 0.06 (normalized box centre).
- Funnel per dive and representation: S0 raw floor presence; S1 search lattice presence
  (non-static nodes); S2 graph reachability (GT-guided oracle over the same gated
  transition graph, evaluation-only); S3 pool (any whole pool path); S3b any extracted
  candidate; S4 surfaced top-K, K in (1, 3, 5, 10, 20). Primary product metric: top-5.
- Baselines on the same authority: frozen V3 (byte-unchanged) at 360p and on HQ caches:
  raw, lattice, V3 graph oracle (audit implementation), pool, F0 top-K, F1 final top-5.
- Secondary: DEV-authority numbers reported alongside; strict subset excluding the two
  queue items that coincide with D5-mined frames.
- No constant in section 3 may change after this commit for the reported results.

## 5. Design-time results (DEV authority, 9 event dives; for the record)

- global evidence DP whole-path pool: 360 5/9 (top-1 4/9), hq 5/9 (top-1 4/9), union 7/9.
- surfaced flight-segment candidates (frozen config): 360+hq top-1 2, top-5 4, top-10 5,
  top-20 6 of 9.
- Rejected on DEV: motion-reward DP (clutter surfing), motion-gated evidence (crowd hop
  fabrication), step-LLR DP (duration bias), greedy multi-track G-MT (fragments, 1/9),
  windowed DP (4/9), evidence caps EV_MAX 0.5-2.0 (2-4/9), merged 360+hq lattice (4/9),
  POOL_MAX 200 (no gain).
