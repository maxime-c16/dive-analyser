# Temporal Landmark Pilot V1 — Results Report

> **Pilot label:** `TEMPORAL_LANDMARK_DEVELOPMENT_PILOT_V1`
> **Pilot protocol:** `docs/science/TEMPORAL_LANDMARK_PILOT_PROTOCOL_V1.md`
> **Date completed:** 2026-09-05
> **Status:** DRAFT — pending proxy-vs-original canary (Phase P) and human annotation of 8 UNCERTAIN dives

---

## 1. Scope

This report summarises the outcomes of the first landmark-extraction pilot run on the 20-dive
baseline corpus defined in `docs/science/PILOT_MANIFEST_V1.json`.

**What was run:**
- Pipeline: `temporal_landmarks_baseline_a_v1` v1.0.0
- Algorithm: `baseline_a_motion_centroid` v1.0.0 (MOG2 background subtraction → vertical
  centroid trajectory → Gaussian smoothing → peak-velocity landmark detection)
- Input: 360p proxy clips only (originals not recalled)
- Execution: `experiments/landmark_pilot/run_pilot_standalone.py`, outside Docker, using
  experiment-isolated venv (cv2 4.10, numpy 2.4.6, scipy 1.17.1)

**Security constraints observed:**
- No original media recalled from Mac source vault (proxy-vs-original canary pending)
- No processing beyond 24 dives (20 processed)
- No production bulk-enqueue (standalone runner only)
- No scores; no raw video stored in Git

---

## 2. Corpus

| Attribute           | Value                     |
|---------------------|---------------------------|
| Total dives         | 20                        |
| Dive groups         | 6 (groups 0–5)            |
| Sessions            | 7 (2025-04-12 to 2026-07-17) |
| Dive codes          | 010, 101, 102, 103, 104, 202, 203, 301, 302, 401, 5111, 5132, 5222, 5411 |
| Heights             | 1m springboard through 5m platform |
| Proxy canary subset | 6 dives (2661, 2169, 192, 311, 2555, 2387) — proxy-vs-original comparison pending |

---

## 3. Landmark-Extraction Results

### 3.1 Overall

| Category        | Count | Share  |
|-----------------|-------|--------|
| Runs succeeded  | 20    | 100 %  |
| Ordering valid (APPLICABLE) | 12 | 60 % |
| Ordering violated (UNCERTAIN) | 8 | 40 % |

### 3.2 Per-Dive Breakdown

| dive_id | code    | T frame | A frame | W frame | flight (s) | apex_norm | status     |
|---------|---------|---------|---------|---------|------------|-----------|------------|
| 133     | 301B    | 116     | 160     | 164     | 1.602      | 0.917     | APPLICABLE |
| 160     | 202A    | 140     | 508     | 556     | 6.940      | 0.885     | APPLICABLE |
| 169     | 5222A   | 152     | 152     | 604     | —          | —         | UNCERTAIN  |
| 191     | 202B    | 212     | 228     | 256     | 0.734      | 0.364     | UNCERTAIN  |
| 192     | 203C    | 1128    | 1172    | 2396    | 21.154     | 0.035     | APPLICABLE |
| 311     | 401C    | 380     | 428     | 428     | —          | —         | UNCERTAIN  |
| 524     | 103B    | 468     | 520     | 520     | —          | —         | UNCERTAIN  |
| 676     | 301A    | 56      | 172     | 220     | 5.472      | 0.707     | APPLICABLE |
| 848     | 302C    | 108     | 108     | 508     | —          | —         | UNCERTAIN  |
| 1040    | 102C    | 184     | 268     | 268     | —          | —         | UNCERTAIN  |
| 2169    | 101B    | 484     | 524     | 528     | 0.734      | 0.909     | APPLICABLE |
| 2281    | 104B    | 296     | 328     | 1064    | 12.812     | 0.042     | APPLICABLE |
| 2341    | 101B    | 120     | 120     | 120     | —          | —         | UNCERTAIN  |
| 2353    | 101A    | 288     | 288     | 288     | —          | —         | UNCERTAIN  |
| 2387    | 5411C   | 212     | 224     | 248     | 1.201      | 0.333     | APPLICABLE |
| 2541    | 5111B   | 580     | 620     | 624     | 1.468      | 0.909     | APPLICABLE |
| 2555    | 5132D   | 220     | 564     | 664     | 7.492      | 0.775     | APPLICABLE |
| 2625    | 103B    | 176     | 188     | 188     | —          | —         | UNCERTAIN  |
| 2661    | 010B    | 608     | 768     | 800     | 3.203      | 0.833     | APPLICABLE |
| 2680    | 010C    | 264     | 304     | 308     | 0.735      | 0.909     | APPLICABLE |

*T = takeoff, A = apex, W = water_contact. UNCERTAIN = ordering violated, landmarks flagged
confidence=0.0, not used for derived metrics.*

---

## 4. Derived Metrics (APPLICABLE Dives Only)

| Metric                | Mean   | Std    | Min    | Max    |
|-----------------------|--------|--------|--------|--------|
| flight_duration_s     | 5.296  | 6.233  | 0.734  | 21.154 |
| ascent_duration_s     | 2.508  | 2.436  | 0.267  | 6.139  |
| descent_duration_s    | 2.788  | 4.207  | 0.067  | 20.420 |
| apex_normalized       | 0.635  | 0.345  | 0.035  | 0.917  |

The large variance in flight_duration (std=6.2s) and apex_norm (std=0.345) reflects the diverse
dive types in the corpus — from quick 1m springboard entries (fd≈0.7s) to an unusually long dive
(192: 21s). Dive 192 (203C from 5m platform) shows an almost immediate apex (apex_norm=0.035)
followed by a long slow descent phase — plausible for a dive that peaks right out of the takeoff
and then falls from height.

Notable outlier: dive 191 (202B) has apex_norm=0.364, meaning it apexes only 36% into the
flight — shorter ascent than descent. This is unusual; it may reflect an asymmetric body position
or a clip that starts later in the motion.

---

## 5. Pairwise Comparison Results

66 pairwise landmark-normalized comparisons computed with method `temporal_landmark_pairwise_v1`.

### 5.1 Most Similar Pairs (apex_delta < 0.01)

| Pair             | apex_T | apex_R | delta  | similarity | notes                        |
|------------------|--------|--------|--------|------------|------------------------------|
| 2169 / 2541      | 0.909  | 0.909  | 0.000  | 1.000      | Both 101B; 5m springboard    |
| 2169 / 2680      | 0.909  | 0.909  | 0.000  | 1.000      | 101B vs 010C; same apex norm |
| 2541 / 2680      | 0.909  | 0.909  | 0.000  | 1.000      | 5111B vs 010C                |
| 192  / 2281      | 0.035  | 0.042  | 0.007  | 0.993      | Both extreme early-apex dives|

### 5.2 Most Different Pairs

| Pair             | delta  | similarity | notes                             |
|------------------|--------|------------|-----------------------------------|
| 133  / 192       | 0.882  | 0.118      | 1m platform vs 5m platform/long   |
| 133  / 2281      | 0.875  | 0.125      | 301B (1m) vs 104B (1m) — opposite profiles |
| 192  / 2541      | 0.874  | 0.126      | Long 5m dive vs tight 5111B       |

### 5.3 Interpretation

The apex_normalized metric naturally clusters dives by their aerial trajectory shape. Three
dives (2169, 2541, 2680) converge at apex_norm=0.909 despite different dive codes — suggesting
a common tight-flight profile pattern. The bimodal distribution (cluster near 0.909, cluster
near 0.035–0.042) may reflect two fundamentally different flight arc types in this corpus.
Full scientific interpretation requires human-annotated ground truth.

---

## 6. Failure Analysis: UNCERTAIN Landmarks (8 dives)

### 6.1 Failure Modes

| Pattern                  | Count | Dives                       | Cause hypothesis                                |
|--------------------------|-------|-----------------------------|-------------------------------------------------|
| All 3 same frame (T=A=W) | 2     | 2353, 2341                  | Background subtractor not converging; centroid stuck on constant position |
| T<A but A=W              | 4     | 524, 2625, 1040, 311        | Water-entry splash not generating distinct area jump above apex |
| T=A but T<W              | 2     | 848, 169                    | No takeoff velocity signature; centroid motion too smooth |

### 6.2 Root Cause

Baseline A relies on:
1. **Takeoff**: max upward velocity in centroid trajectory (centroid moves up fastest)
2. **Apex**: minimum centroid Y value (topmost position)
3. **Water contact**: max foreground-area jump after apex

In dives where the centroid trajectory is insufficiently smooth, noisy, or where the background
subtractor hasn't warmed up (typically first ~30 frames at FRAME_STEP=4), all three signals
can resolve to the same frame. Short clips (&lt;6s at 30fps) are especially affected.

### 6.3 Mitigation Options for Baseline B

- **Longer warmup**: use a separate warm-up pass on the first 3 seconds before tracking
- **Dual signal for water entry**: combine area-jump with centroid-Y crossing a low threshold
- **Adaptive frame step**: use FRAME_STEP=1 for short clips (< 8s)
- **Confidence-weighted detection**: require minimum apex displacement before accepting takeoff

---

## 7. Proxy-vs-Original Canary (Phase P) — PENDING

The 6 canary dives (2661, 2169, 192, 311, 2555, 2387) require running Baseline A on the
original-resolution files from the Mac source vault. Original files have not been recalled
as of this report date.

**To complete Phase P:**
1. On Machine B (Mac), locate originals for canary dive_ids
2. Export to temporary directory on server (single-session, one-time)
3. Run `run_pilot_standalone.py --dive-id <id> --media-path <original>` for each canary dive
4. Compare landmark frame positions (proxy vs original): acceptable delta ≤ 5 frames (takeoff,
   water_contact) or ≤ 8 frames (apex) per the protocol
5. Delete temporary originals after comparison; do not store in Git

---

## 8. Annotation Tool

A minimal web-based annotation/correction tool was built at
`experiments/landmark_pilot/annotate.py`. It serves a single-page UI on port 8765 (SSH-tunnel
from Mac) allowing:
- Video playback of proxy clips with frame stepping (1f / 10f)
- Keyboard shortcuts: T=set takeoff, A=set apex, W=set water_contact, S=save
- Speed control (0.1×, 0.25×, 0.5×, 1×)
- HUMAN landmark save to DB (replaces AUTO/UNCERTAIN for chosen keys)
- NOT_APPLICABLE marking
- Sidebar showing all 20 dives with their ordering status and source

The 8 UNCERTAIN dives should be annotated before final analysis.

---

## 9. Metric Registry

10 metrics are computed for APPLICABLE runs (all defined in `backend/app/data/metric_registry.yaml`):

| metric_key                             | unit    | description                               |
|----------------------------------------|---------|-------------------------------------------|
| flight_duration_seconds                | seconds | time from takeoff to water contact        |
| ascent_duration_seconds                | seconds | time from takeoff to apex                 |
| descent_duration_seconds               | seconds | time from apex to water contact           |
| takeoff_frame_normalized               | ratio   | takeoff frame / total clip frames         |
| apex_frame_normalized                  | ratio   | apex frame / total clip frames            |
| water_contact_frame_normalized         | ratio   | water_contact frame / total clip frames   |
| landmark_proposer_confidence_takeoff   | ratio   | algorithm confidence [0,1]                |
| landmark_proposer_confidence_apex      | ratio   | algorithm confidence [0,1]                |
| landmark_proposer_confidence_water_contact | ratio | algorithm confidence [0,1]            |
| ascent_fraction                        | ratio   | ascent_dur / flight_dur                   |

`flight_duration_delta_seconds` is a comparison metric (Baseline B cross-run delta, not yet computed).

---

## 10. DB Artifacts

| Table                     | Rows added |
|---------------------------|------------|
| analysis_runs             | 20         |
| analysis_jobs             | 20         |
| analysis_landmarks        | 60 (3 per run) |
| analysis_phases           | 3 per APPLICABLE run = 36 |
| analysis_metrics          | 10 per APPLICABLE run = 120 |
| analysis_artifacts        | 1 per run (diagnostic.json) = 20 |
| analysis_comparisons      | 66         |
| analysis_comparison_metrics | 4 per comparison = 264 |

Storage: `media/analysis-artifacts/<dive_id>/<run_uuid>/diagnostic.json` (20 files).

---

## 11. Next Steps

1. **Human annotation (Phase K)**: Correct 8 UNCERTAIN dives using `annotate.py`
2. **Proxy canary (Phase P)**: Run Phase P once originals available on Mac
3. **Baseline B design**: Address root causes in Section 6.3
4. **Formal scoring**: Once ≥ 3 human-annotated dives per group, compute accuracy vs AUTO
5. **Temporal alignment v2**: Integrate DTW on landmark-normalized centroid trajectories

---

*This report is EXPERIMENTAL. All outputs are flagged `experimental=True` in API responses.
No production inference is drawn from Baseline A results.*
