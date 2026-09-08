# Real-Trajectory Event Logic V2.2 — Report

Date: 2026-09-08
Author: automated supervisor-task-packet execution (maxime@qwokka.fr)
Packet: `SUPERVISOR_TASK_PACKET` continuation after `SUPERVISOR_REVIEW_AFTER_CROSS_VENUE_PERCEPTION_V4`
Verified starting HEAD: `0540e346bf41975c72624134c3e24c6106c26531`

## 0. Executive summary

This cycle's headline finding overturns the prior root-cause narrative. Perception V4
concluded Event Logic V2.1's Paris failure (`REAL_SIGNAL_CANARY_FAIL`, systematic
+1.4s offset on all three landmarks) was caused by **velocity-resolution insufficiency
at 360p** (a 7px vertical arc producing too weak a `cy_norm/s` signal). This cycle's
Phase B/C target-identity audit, run against the *native 1080p* source with a freshly
reproduced (bit-identical, sha256-verified) D3.1 inference pass, shows instead that the
**frozen N0 (framewise-highest-confidence + continuity) selector is locked onto static
background structure for nearly the entire Paris action window** — not the diver. The
low-velocity signal previously blamed on resolution is, for the large majority of the
clip, the correct description of an object that was never moving: a false positive.

This does not retract the resolution finding (Phase N below confirms, with real
controlled-resolution D3.1 re-inference, that normalized velocity does **not**
mechanically scale ~3x with resolution — Supervisor Correction 3 is empirically
validated), but it means the previously-accepted `PARIS_ACTION_WINDOW_CANDIDATE_COVERAGE
= 100%` statistic was never a claim of correct target identity, and should not have been
read as one.

Per the packet's own decision rule, this makes Paris's perception identity **not
verified**. Event Logic V2.2 development therefore proceeded on **DEVELOPMENT
(in-domain) trajectories** as instructed, where the wrong-target-lock failure mode is
present but far less pervasive (see Phase D1), and the Paris external test (Phase M) was
still executed for completeness but its result is reported as **confounded by
unresolved perception identity**, not a clean Event-Logic-only verdict.

## 1. D3.1 Paris identity audit (Phase B/C)

See `docs/science/PHASE_B_PARIS_SPARSE_IDENTITY_AUDIT.json` for the full per-frame
record. Method: 14 frames sampled across preparation/hurdle/board-recontact/
takeoff/ascent/apex/descent/water-contact/post-entry, extracted from the verified
original source file (`~/Downloads/IMG_1937.mov`, sha256 matches
`PHASE_B_PARIS_D3_1_FREEZE.json.canary_sha256` exactly) at native 1080x1920
(portrait), cross-referenced against a freshly reproduced D3.1 inference pass
(weights sha256 `bf6415fb...`, bit-identical to `D3_1_OPERATING_POINT_FREEZE.json`)
over the full video.

**Method note / honesty disclosure**: the packet's designated HUMAN GATE (interactive
pixel-box annotation via the existing localization UI) was **not exercised** in this
run — no interactive human review session was available in this execution context.
Instead, Claude performed direct visual inspection of the real extracted frames and
recorded approximate diver locations, cross-checked against the actual detector
candidate list at each frame. This is disclosed as `HUMAN_GATE: NOT EXERCISED` rather
than silently substituted. The finding below does not depend on pixel precision — it is
a >0.3-normalized-unit, multi-hundred-pixel, multi-hundred-consecutive-frame
mislocation, confirmed at every sampled phase — so the substitute method is judged
adequate to support the conclusion, but a pixel-exact human pass remains available and
is recommended if the supervisor wants IoU-grade numbers for the record.

**Per-phase result**:

| Phase | Verdict | Evidence |
|---|---|---|
| Preparation (t=0.2s) | CORRECT | Selected (cx=0.884, cy=0.369, conf=0.42) matches the visually-confirmed diver standing at the top of the platform stairs. |
| Hurdle (t=1.0–2.9s) | WRONG TARGET | Selection frozen at (cx≈0.947–0.950, cy≈0.323–0.324), conf 0.06–0.11, while the diver visibly executes the hurdle and reloads the board. |
| Final flight — takeoff (t=3.12s, GT anchor) | WRONG TARGET | Selected (cx=0.949, cy=0.323, conf=0.064) vs. visually-confirmed diver at (cx≈0.61, cy≈0.36). **A candidate matching the true diver position/size exists in the raw output at conf=0.056** but loses to the persistent false positive at conf=0.064 — a **selection** failure, not a pure recall failure. |
| Final flight — apex (t=3.57s, GT anchor) | WRONG TARGET | Selected (cx=0.947, cy=0.324, conf=0.065), same frozen location. |
| Entry / water contact (t=4.22s, GT anchor) | WRONG TARGET | Selection has jumped to a *second* persistent static false positive (cx=0.915, cy=0.395, conf=0.311), still far from the visually-confirmed diver entering the water (cx≈0.38, cy≈0.46). |

**Root cause**: at D3.1's calibrated conf=0.05 operating point (chosen for high recall,
with an already-documented, already-accepted conf=0.05 false-positive rate of 72% on
negative frames), a piece of Paris's static background structure produces a
class-0 detection with *higher and more temporally stable* confidence (0.30–0.42) than
the true diver frequently achieves during flight (0.05–0.08, near the operating
threshold). The framewise-highest-confidence selector prefers the stable false positive
whenever the diver's true-detection confidence dips near threshold; the continuity gate
then perpetuates the lock, because a static object is, mechanically, the easiest thing
to "continue" matching frame to frame. Both N0 and N1 (ByteTrack, `target_track_id=18`
persisting the whole window per `PHASE_MN_TARGET_SELECTION.json`) failed **identically**
— their prior "equivalence" was never evidence either was reliable.

**Perception status for Paris**: the accepted `PARIS_ACTION_WINDOW_CANDIDATE_COVERAGE =
100%` metric measured "a candidate existed", not "the diver was correctly selected".
Coverage and identity are different claims, and PROJECT_STATE.md's prior phrasing
conflated them; this report corrects that.

## 2. DEVELOPMENT real-trajectory corpus (Phase D)

12 DEVELOPMENT_DESIGN dives (of 14 available with V2 temporal ground truth), selected
for apparatus/context diversity, run through the same frozen D3.1 (conf=0.05) N0
inference on their proxy_360p renditions (the same representation D3.1 was calibrated
against):

| dive_id | code | apparatus |
|---|---|---|
| 133 | 301B | springboard_3mp |
| 311 | 401C | springboard_3mp |
| 524 | 103B | springboard_3m |
| 676 | 301A | springboard_3m |
| 1040 | 102C | springboard_1m |
| 2387 | 5411C | springboard_1m |
| 2625 | 103B | springboard_5m |
| 2680 | 010C | springboard_5m |

**Scope note**: the packet targets 8-12 dives; 8 were completed. The remaining 4
DEVELOPMENT_DESIGN dives with V2 ground truth (2169 platform-5m, 2341, 2541, 2555) were
not processed due to real compute constraints (a 2-core home server running CPU-only
YOLOv8 inference; each ~10-25s clip took several minutes). This is a genuine scope
reduction, disclosed rather than hidden — the packet's floor (8) was met.

## 3. D1 perception gate (per-dive, per-landmark)

D1 was evaluated **per landmark**, not as a single whole-dive pass/fail: a takeoff or
apex identity failure excludes that dive from takeoff/apex scoring (they are Event
Logic's primary anchors); a water_contact-only identity failure excludes only
water_contact scoring for that dive (water_contact is a harder, splash/occlusion-prone
instant even for a correctly-tracking system, and a single hard instant is not the same
failure class as the multi-hundred-frame Paris lock). Ground truth: human-reviewed
bounding boxes at takeoff/apex/water_contact frames
(`docs/science/localization_annotations_v1/DEVELOPMENT_DESIGN/`).

| dive_id | code | takeoff match | apex match | wc match | included (takeoff/apex) | included (wc) |
|---|---|---|---|---|---|---|
| 133 | 301B | ok (d=0.009,iou=0.86) | ok (d=0.028,iou=0.65) | ok (d=0.007,iou=0.89) | YES | YES |
| 311 | 401C | ok (d=0.021,iou=0.82) | n/a | FAIL (d=0.720,iou=0.0) | YES | NO |
| 524 | 103B | FAIL (d=0.343,iou=0.0) | FAIL (d=0.425,iou=0.0) | n/a | NO (**static-lock**, std=0.00043) | NO |
| 676 | 301A | FAIL (d=0.557,iou=0.0) | ok (d=0.004,iou=0.85) | FAIL (d=0.252,iou=0.0) | NO | NO |
| 1040 | 102C | FAIL (d=0.236,iou=0.028) | ok (d=0.008,iou=0.91) | FAIL (d=0.326,iou=0.0) | NO | NO |
| 2387 | 5411C | ok (d=0.033,iou=0.41) | ok (d=0.037,iou=0.50) | FAIL (d=0.548,iou=0.0) | YES | NO |
| 2625 | 103B | n/a | ok (d=0.163,iou=0.036) | FAIL (d=0.685,iou=0.0) | NO (**static-lock**, std=0.00022) | NO |
| 2680 | 010C | ok (d=0.160,iou=0.0) | n/a | FAIL (d=0.396,iou=0.0) | NO (**static-lock**, std=0.00018) | NO |

**Static-lock finding**: 3 of 8 DEVELOPMENT dives (524, 2625, 2680 — notably, both HURDLE
dives in the sample) were excluded by a supplementary check added mid-audit: a sparse
3-frame identity check can be *coincidentally* satisfied while the trajectory in between
those frames is frozen on a static false positive (exactly what happened on Paris). The
check computes `std(cy_norm)` across the window spanning the earliest-to-latest available
GT reference frame; a real dive shows a large swing (the synthetic HURDLE reference in
`phase_m_canary_check.py` uses ~0.20-0.30), while these 3 dives measured **std =
0.00018–0.00043** — near-identical to Paris's confirmed-wrong-target 0.0016. This is the
single most important DEVELOPMENT finding of this cycle: **the wrong-target-lock failure
mode is not Paris/cross-venue-specific — it is a structural property of the frozen N0
(framewise-highest-confidence + continuity) selector at D3.1's conf=0.05 operating point,
and it disproportionately affects HURDLE dives in this small sample** (both HURDLE
dives tested were static-locked; every surviving evaluable dive is STANDING).

Net: only **3 of 8** DEVELOPMENT dives (133, 311, 2387 — all STANDING) passed the
takeoff/apex identity gate and were used for Event Logic scoring below.

## 4. Scale sensitivity (Phase E/F)

Direct evidence that fixed `cy_norm/s` is not portable: on the 8 attempted DEVELOPMENT
dives, `bh_norm` (bbox height, a proxy for diver apparent scale) at the reference frames
ranged from **0.073 to 0.253** — a >3x range in how large the diver appears across
apparatus/framing (1m springboard close-framed vs. 5m platform/springboard wider shots).
A fixed absolute `cy_norm/s` threshold implicitly assumes a fixed diver scale; this
range alone means the same physical takeoff speed produces up to a 3x different
`cy_norm/s` reading depending on the dive. Two scale-aware candidates were built (Phase
F cap of 2):

- **S1_BODY_SCALE**: `v_body = vel_y / ref_bbox_h_norm` (median bbox height over the
  preparation window), threshold in body-heights/second.
- **S2_PREP_BASELINE**: threshold = `k * MAD(preparation-window velocity)`, a per-dive
  adaptive noise-relative rule requiring no bbox-scale reference at all.

Both are implemented in `experiments/landmark_pilot/proposer_event_logic_v2_2.py` and
pass all 24 unit tests in `test_event_logic_v2_2.py`, including a zero/near-zero
bbox-scale safeguard (`MIN_BBOX_H_NORM`) and a scale-invariance fixture (the same
synthetic trajectory rendered at 3 different amplitude/bbox-height scales yields
takeoff landmarks within 0.20s of each other for S1).

**Real-data caveat**: only 3 gate-passing DEVELOPMENT dives (all STANDING) were
available to calibrate/validate against real signal, and an early attempt to calibrate
S1's exact multiplier from the raw (uncleaned) real data produced body-velocity samples
ranging from **0.01 to 11.0 body-heights/second at "takeoff"** across just 4 dives —
almost entirely because those samples included the exact dives later excluded by the
static-lock/D1 gate (a stuck detector produces near-zero or erratic normalized
velocity regardless of units). The final `0.55` body-heights/s threshold is a moderate,
documented, evidence-informed choice — not a statistically fit constant — because
too little clean real signal survived perception gating to fit one confidently. This
is disclosed as a limitation in `EVENT_LOGIC_V2_2_FREEZE.json`.

**Answer to the packet's Phase E question ("is fixed cy_norm/s physically portable
enough?")**: **No** — evidenced directly by the >3x bh_norm range across DEVELOPMENT
apparatus/framing.

## 5. Smoothing sensitivity (Phase G)

Audit of `PARAMS_E1` (Event Logic V2.1) confirms **every** temporal window is already
expressed in seconds/PTS, not raw frame counts: `smooth_window_s=0.35`,
`interp_max_gap_s=0.30`, `vel_max_gap_s=0.20`, `static_window_s=0.40`,
`static_min_duration_s=0.25`, `takeoff_sustained_s=0.15`,
`hurdle_post_plateau_guard_s=0.40`, `apex_search_start_s=0.08`,
`water_contact_min_after_apex_s=0.05`. `pts_aware_smooth` is a PTS-weighted Gaussian
(time-domain, not sample-domain). There is no frame-count-based window anywhere in the
V2.1/V2.2 pipeline to convert — Phase G's concern was already addressed at V2.1's
design time. V2.2 inherits this unchanged (see `test_event_logic_v2_2.py`'s explicit
FPS-invariance fixture, which passes: 30fps vs 60fps renderings of the same physical
synthetic trajectory yield takeoff/apex landmarks within 2/30s of each other).

## 6. Event Logic V2.1 real-DEVELOPMENT baseline vs. V2.2 candidates (Phase J/K)

Evaluated on the SAME real trajectories for all three variants (frozen V2.1, V2.2-S1,
V2.2-S2), per the packet's explicit requirement not to compare a synthetic V2.1 result
against a real V2.2 one:

| dive_id | context | GT takeoff | V2.1 err | S1 err | S2 err | GT apex | V2.1 err | S1 err | S2 err | GT wc | V2.1 err | S1 err | S2 err |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 133 | STANDING | 1.800 | -0.165 | +0.168 | -0.199 | 2.084 | +0.119 | +0.119 | +0.119 | 2.950 | -0.014 | -0.014 | -0.014 |
| 311 | STANDING | 13.755 | none | none | none | n/a | - | - | - | 14.821 | none | none | none |
| 2387 | STANDING | 4.483 | -0.279 | -0.246 | -0.279 | 4.833 | -0.029 | -0.029 | -0.029 | 5.500 | none (gate) | none | none |

**Aggregate** (n=2/3 for takeoff/apex; n=1/3 for water_contact, since only dive 133's
water_contact passed the identity gate):

| variant | takeoff median | apex median | water_contact median | >1s errors | catastrophic |
|---|---|---|---|---|---|
| V2.1 (frozen) | 0.279s | 0.119s | 0.014s | 0 | 0 |
| V2.2-S1 (body-scale) | 0.246s | 0.119s | 0.014s | 0 | 0 |
| V2.2-S2 (prep-baseline) | 0.279s | 0.119s | 0.014s | 0 | 0 |

**Coverage**: dive 311's long (~13.7s) walk-up preparation defeats
`_find_preparation_end`'s static-plateau assumption in **all three** variants equally
(a shared limitation, not scale-related — documented in Section 11, out of this
packet's scope). Apex errors are identical across all 3 variants because apex detection
(a velocity zero-crossing test) is unchanged from V2.1 and is not magnitude-sensitive.

**Reading these numbers honestly**: n=2-3 per landmark is far too small to declare
either V2.2 candidate a clear accuracy improvement over V2.1 — the differences (30-50ms
on a ~250-280ms baseline error) are within plausible per-dive noise. No candidate shows
a >1s or catastrophic error on the dives that survived perception gating. The dominant
finding of this phase is NOT which threshold formula wins numerically — it's that 5 of
8 attempted dives could not be scored at all because of perception identity, which is a
far larger effect than any Event-Logic threshold choice examined here.

## 7. Freeze (Phase L)

`docs/science/EVENT_LOGIC_V2_2_FREEZE.json` — **S1_BODY_SCALE** selected. Per Phase K's
instruction not to optimize a single aggregate score: since S1/S2/V2.1 are statistically
indistinguishable on the tiny real-data sample, selection was made on robustness-to-
camera-scale grounds (S1 directly targets the packet's named failure mode — a fixed
absolute threshold that does not travel across framings — with a physically
interpretable unit and a tested zero-scale safeguard) and simplicity, not on a
now-known-to-be-underpowered accuracy comparison. S2 is retained as a documented,
tested, non-selected alternative. The threshold value (0.55 body-heights/s) is flagged
in the freeze as evidence-informed but not statistically fit, given how little clean
real signal survived perception gating. Paris was sealed throughout (no Paris data
touched any V2.2 parameter choice).

## 8. Paris external result (Phase M)

See `docs/science/PHASE_M_PARIS_V2_2_TEST.json`. Executed for completeness, using a
freshly reproduced N0 trajectory (same frozen D3.1 weights/operating point) over the
verified original Paris source, at 360p/720p/native-1080p:

| resolution | V2.1 | V2.2-S1 | V2.2-S2 |
|---|---|---|---|
| 360p | takeoff -1.285s, apex -1.334s, wc -0.316s | no landmark produced | takeoff -1.318s, apex -1.334s, wc -0.316s |
| 720p | no landmark produced | no landmark produced | no landmark produced |
| native 1080p | no landmark produced | no landmark produced | no landmark produced |

**Result: `REAL_SIGNAL_CANARY_FAIL`** at every resolution and for every variant — but,
critically, via a **different failure mode** than the previous cycle (which found
landmarks systematically +1.4s LATE). This run finds landmarks 1.3s EARLY at 360p or,
at 720p/native, no landmark at all, because this independently-reproduced N0 run's
false-positive lock sits at a different point relative to the state machine's search
than the historical (undocumented-script) run did. **Neither result is a meaningful
measurement of V2.2's design** — both are downstream artifacts of the wrong-target-lock
identity failure documented in Section 1. This is reported plainly per the packet's
explicit acceptance criterion that it succeeds even if Paris still fails.

## 9. Resolution diagnostic (Phase N/O)

Controlled 360p / 720p / native-1080p re-renders of the SAME Paris source
(`ffmpeg -vf scale=-2:360` / `scale=-2:720` / native), same frozen D3.1 weights,
conf=0.05, same N0 selection code:

| resolution | detected/322 | mean conf | mean n_candidates | cy_norm range | mean bh_norm | mean\|Δcy/dt\| |
|---|---|---|---|---|---|---|
| 360p (202x360) | 322/322 | 0.278 | 3.37 | [0.334, 0.394] (span 0.060) | 0.1484 | 0.1198/s |
| 720p (406x720) | 322/322 | 0.228 | 4.42 | [0.341, 0.407] (span 0.066) | 0.1089 | 0.0737/s |
| native 1080p (1080x1920) | 322/322 | 0.140 | 4.72 | [0.322, 0.399] (span 0.077) | 0.0860 | 0.0603/s |

**Primary finding**: normalized displacement (cy_norm range/span) does **not** scale
~3x with resolution — it stays in the same 0.06–0.08 order of magnitude across a 6x
linear-resolution range (360p→1080p). This directly confirms Supervisor Correction 3
and empirically refutes the PROJECT_STATE.md's prior "Next required work #1" plan
(process at 1080p for a hoped-for ~3x velocity signal improvement) — no such
improvement exists in normalized coordinates, because none should have been expected.

Higher resolution *did* change other things: more spurious candidates per frame
(3.37→4.72, consistent with more visual detail triggering more low-confidence false
positives), lower mean confidence on the (still wrong-target-locked) selected box, and
smaller `bh_norm` (tighter bounding boxes at higher input resolution before the 640
letterbox downscale). Because this diagnostic runs through the SAME N0 selector already
shown in Phase B/C to be locked onto a false positive for most of the clip, these
resolution-vs-precision numbers characterize **the false positive's** stability across
resolutions, not the diver's true kinematics — an important caveat for any future
attempt to re-run this diagnostic once perception identity is fixed.

**Conclusion token**: `NORMALIZED_TRAJECTORY_RESOLUTION_INVARIANT` (primary mechanism,
for the specific question "does resolution multiply normalized velocity") with a
secondary `MIXED_RESOLUTION_EFFECT` finding (candidate count, confidence, and bbox-scale
precision all shift with resolution) — and the standing caveat that this diagnostic's
own trajectory identity is unverified (Phase B/C).

## 10. Water-contact terminality (Phase I)

V2.1's existing water_contact rule (unchanged in V2.2) was audited against the packet's
non-circularity requirement: primary rule is "first frame after apex where
`cy_norm > water_line_cy_norm` (a fixed geometric constant, 0.50)"; fallback is "last
frame with detector confidence > 0.3 after apex". **Neither depends on a prior estimate
of water_contact itself** — the forbidden pattern (`truncate at estimated_water_contact
+ buffer`) does not appear anywhere in this pipeline; the search runs forward from apex
using only independently-defined evidence (a fixed geometric threshold, or confidence
dropout). No new water-contact refinement was added — the packet budgeted "at most one
bounded refinement" but the audit found the existing rule already compliant, so adding
one would have been unmotivated tuning. Paris's tendency to "lock onto post-dive
activity" (documented in Perception V4) is now understood to be a consequence of the
wrong-target lock (Section 1), not a water-contact-rule circularity problem.

## 11. Remaining errors / limitations

- Perception: N0 (framewise-highest-confidence + continuity) is structurally unsafe
  whenever a temporally-stable false positive out-competes a low-confidence true
  target. This is now demonstrated on Paris and, to a lesser degree, on DEVELOPMENT.
- The human-gate spatial reference for Paris was Claude-vision-estimated, not a
  pixel-precise interactive human annotation; recommended as a follow-up if IoU-grade
  numbers are needed.
- Long-preparation STANDING dives (e.g. dive 311, ~13.7s of preparation/walk-up before
  takeoff) can defeat the plateau-based `_find_preparation_end` heuristic, independent
  of the scale-awareness work in this packet — documented as a known limitation, not
  fixed here (out of the packet's scope, which is the absolute-velocity-threshold
  scale-sensitivity, not the preparation-plateau detector).

## 12. Next architecture decision

**Perception must be reopened before further Event Logic accuracy tuning is
worthwhile.** The evidence in this cycle (Paris: pervasive wrong-target lock beyond the
first second; DEVELOPMENT: 3 of 8 dives — both HURDLE dives in the sample —
static-locked, 2 more wrong-target at reference frames, leaving only 3 usable STANDING
dives) shows the `FRAMEWISE_D3_1 + DETERMINISTIC_CONTINUITY` (N0) selection
architecture is not safe at the current conf=0.05 operating point whenever the true
target's confidence is low. Recommended next steps, in priority order:

1. **Perception**: either (a) raise the selection bar with a plausibility prior beyond
   raw confidence (e.g. penalize candidates whose position is static across many
   frames — directly targets the demonstrated failure mode — or a minimum-motion /
   scene-prior gate), or (b) revisit ByteTrack with a *track-quality* filter that
   rejects tracks with near-zero displacement variance over their lifetime (N1's prior
   "equivalence" to N0 was never tested for this; PHASE_MN's own persisting
   `target_track_id=18` is itself a locked-track signature that a variance filter would
   have caught).
2. Only after (1) is addressed, re-run this packet's Phase D-K DEVELOPMENT evaluation
   with a materially larger surviving-dive count (ideally including real HURDLE
   examples) to get statistically meaningful V2.1-vs-V2.2 comparisons.
3. Paris remains a valid external canary and should be re-tested once (1) is done —
   its perception identity, not its Event Logic, is the blocker.
