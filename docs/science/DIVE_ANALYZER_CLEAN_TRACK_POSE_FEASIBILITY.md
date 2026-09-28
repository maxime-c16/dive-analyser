# Dive Analyzer clean-track pose feasibility

**Cycle date:** 2026-09-28
**Canonical branch:** `uiux-overhaul-pro-app`
**Canonical base:** `ca5bab9`
**Gate:** `CLEAN_TRACK_POSE_FEASIBILITY` (feasibility only, not production biomechanics).

## Preserved prior result (not reopened)

The true-merge continuity result and PROJECT_STATE at `ca5bab9` are durably
integrated and preserved. Development-only method
`experiments/full_action/prep_to_subcore_v1_dev.py`
(SHA256 `b71b3f3b4aa61d10fcef30809ecf87e750f30e0e3ac0c147b5a4a95d1319e404`)
remains development-only. The finding that the current authorized corpus
contains no raw-verified true merge/split suitable for validation stands;
no new merge/split search was opened in this task. S3, FSR, FAX histories,
identity/ReID, Media Backbone, B2, Event Logic, and protected authorities
(Paris, INTERNAL_EVAL, FINAL_HOLDOUT, 524, 2555) were not mutated or used
as DEVELOPMENT evidence. No general full-action overlay promotion is
claimed. Detailed prior handoff:
`docs/science/DIVE_ANALYZER_PREP_TO_SUBCORE_CONTINUITY_DETAILED_SUPERVISOR_OUTPUT.md`.

## Data / track authority (DEVELOPMENT only)

HUMAN-validated clean same-person DiveTracks from sealed blind fresh
authorities (read-only):

- `FULL_ACTION_GT_HUMAN_FAX7_FRESH`, digest
  `b71b950e3af60d5f736642053ace5cfdd13f65b00328431e6d50f6a316bfc436`
  (182 records plus events, six session-disjoint DEVELOPMENT dives).
- `FULL_ACTION_GT_HUMAN_FAX8_FRESH`, digest
  `a31d5bcfd93afa1704191e336dc72a5124255a97f19ad6da8eafea038b974188`
  (174 records plus events, six different session-disjoint DEVELOPMENT dives).

Primary clean same-person set (all HUMAN flight 9/9 V1 center hits, no
confirmed physical wrong-person link, session-disjoint, not protected):

| Dive | Session | Code / height | HUMAN prep/flight/post (V1) | Role |
|---|---|---|---|---|
| 47 | s15 | 201C 1m | 19/19, 9/9, 1/1 | fully clean control |
| 952 | s58 | 201C 1m | 13/13, 9/9, 1/1 | fully clean replicate |
| 1257 | s79 | 301C 1m | 11/11, 9/9, 1/1 | fully clean, small-distant |
| 2120 | s129 | 101C 1m | 4/6, 9/9, 1/1 | flight-clean, code diversity |

Supplemental (flight-clean, for rotation/scale failure modes):
1849/s107 403B 3m (V1 prep 0/4, flight 9/9 — large-person 3m tuck);
2134/s130 103B 1m (V1 flight 9/9 — single-person rotation artifact that
caused the FAX8 false mixed-edge flag; used here only to test pose under
rotation, not as clean control).

HUMAN takeoff/apex/water_contact events segment phases; HUMAN
`flight_fraction` (PREP, 0/8–8/8 flight eighths, POST) provides
phase-specific reliability. Consumed science clips are used for
feasibility development only; no population-wide claim is made.
Input identity/track is assumed solved for these samples; pose was never
used to repair tracking. Ambiguous intervals were marked lost/unusable
(distance gate 0.15 normalized), not forced.

Media: `fresh_prep_authority/raw/*.mov` (HQ, e.g. 720×1280 portrait to
1080×1920 portrait) vs `fresh_prep_authority/proxies/*.mp4` (360p,
202×360 portrait). HQ/raw alignment by PTS (frame counts differ, e.g.
952 raw 672 vs proxy 665, 2120 raw 795 vs proxy 771); HUMAN boxes are
`proxy_pixels_native_360p`, scaled to raw by display-size ratio.

## Pose approach chosen

Bounded comparison, COCO-pretrained, no diving fine-tune (correct for
feasibility):

- A: `yolov8n-pose.pt` (SHA256 `c6fa93dd…`, 6.5 MB) — primary.
- B: `yolov8m-pose.pt` (SHA256 `dbe539ea…`, 50.8 MB) — capacity check.
- Mask spot check: `yolov8n-seg.pt` (SHA256 `a7cd8f92…`, already frozen
  segmentation weights) on 8 flight frames.

Full-frame inference (imgsz 640, conf 0.25, IoU 0.45), then association
to the trusted HUMAN identity by normalized center distance (match
threshold 0.06, same radius as FAX scoring; dense-track gate 0.15).
Track-conditioned visual coherence checked via overlays (green HUMAN box
plus blue pose skeleton, proxy and HQ side-by-side). No Event Logic
tuning. No HUMAN pose annotation was requested; qualitative raw-frame
review suffices for this feasibility decision (minimal future ask defined
below if needed).

## Quantitative findings (117 HUMAN-sampled frames)

Detection recall = fraction of HUMAN-sampled frames with a pose box
within 0.06 normalized center distance.

| Dive | Phase | proxy n-pose | proxy m-pose | HQ-raw n-pose |
|---|---|---|---|---|
| 47 | PREP 19 | 19/19 1.00 | 19/19 1.00 | 19/19 1.00 |
| 47 | FLIGHT 9 | 3/9 0.33 | 1/9 0.11 | 6/9 0.67 |
| 952 | PREP 13 | 11/13 0.85 | 12/13 0.92 | 13/13 1.00 |
| 952 | FLIGHT 9 | 2/9 0.22 | 1/9 0.11 | 7/9 0.78 |
| 1257 | PREP 11 | 0/11 0.00 | 0/11 0.00 | 7/11 0.64 |
| 1257 | FLIGHT 9 | 0/9 0.00 | 0/9 0.00 | 1/9 0.11 |
| 2120 | PREP 6 | 5/6 0.83 | 0/6 0.00 | 6/6 1.00 |
| 2120 | FLIGHT 9 | 1/9 0.11 | 0/9 0.00 | 6/9 0.67 |
| 1849 | PREP 4 | 4/4 1.00 | 3/4 0.75 | 4/4 1.00 |
| 1849 | FLIGHT 9 | 8/9 0.89 | 9/9 1.00 | 9/9 1.00 |
| 2134 | PREP 4 | 2/4 0.50 | 3/4 0.75 | 3/4 0.75 |
| 2134 | FLIGHT 9 | 0/9 0.00 | 0/9 0.00 | 0/9 0.00 |
| all POST (entry/splash) | 6 | 0/6 0.00 (except 1849 0/1 proxy, 1/1 m/raw) | — | 1/6 |

Larger model (m) is not systematically better: 2120 PREP m 0/6 vs n 5/6;
47 FLIGHT m 1/9 vs n 3/9. Capacity is not the blocker.

Keypoint completeness among matched detections (conf>0.3):

- Shoulders/elbows/wrists/hips/knees/ankles: 0.95–1.00 in PREP and
  FLIGHT, proxy and HQ. When detection succeeds, limb keypoints exist.
- Head/face: nose 0.48–0.91, eyes 0.08–0.86 (strong L/R asymmetry, e.g.
  proxy PREP lefteye 0.78 vs righteye 0.34, rightear 0.22), ears
  0.00–0.97. Side-view diving occludes one side; head/face are
  unreliable and must not feed geometry.

Small-person threshold (proxy normalized): 1257 boxes area 0.017–0.032,
bw 0.13–0.18 vs 47/952 area 0.04–0.09, bw 0.20–0.40. Below ~0.03 area /
~0.18 width on 360p, proxy pose fails completely (0/11 prep, 0/9
flight); HQ recovers prep to 7/11 but flight stays 1/9.

Dense flight stability (takeoff−0.3 s to water+0.4 s, n-pose, nearest to
HUMAN-initialized identity, lost if >0.15):

| Dive | Proxy tracked | Raw tracked | Torso CV | Jitter median (torso-norm) | Shoulder/hip CV | L/R flips |
|---|---|---|---|---|---|---|
| 47 | 14/59 24% | 23/60 38% | proxy 0.093, raw 0.199 | proxy 0.326, raw 0.384 | raw sh 0.75, hip 0.68 | 9/22 41% |
| 952 | 17/105 16% | — | proxy 0.098 | proxy 0.144 | — | — |
| 1257 | 0/63 0% | 7/62 11% | raw 0.090 | raw 0.321 | sh 0.52, hip 0.51 | 2/6 |
| 2120 | 33/113 29% | 74/113 65% | proxy 0.227, raw 0.327 | proxy 0.132, raw 0.217, max 7.5 | sh 0.57, hip 0.63 | 31/73 42% |
| 1849 | 28/110 25% | 95/111 86% | proxy 0.091, raw 0.116 | proxy 0.159, raw 0.168 | sh 0.54, hip 0.52 | 16/94 17% |

Even with perfect identity initialization, proxy pose loses lock 70–100%
of flight frames; HQ improves continuity (1849 25→86%, 2120 29→65%)
but jitter stays 13–38% of torso per frame and torso scale varies
9–33%. Shoulder/hip widths vary 50–75%. L/R shoulder-order flips
17–42% of consecutive flight frames. This is not stable enough for
velocity/angle derivatives.

Masks: `yolov8n-seg` yields 0 masks on 47 f295/f300 and 2120 f288/f297
(exactly where pose fails) and 1 mask where pose succeeds. Silhouette
fails concurrently; it does not rescue pose.

## Visual findings (raw-frame review, no numeric pose GT)

Host-only overlays (72 PNGs, proxy+HQ pairs with green HUMAN box and
blue skeleton) confirm numerics:

- Coherent: 47 takeoff upright (f285, d=0.02), 1849 tuck hold
  (f383, d=0.00 both res, full skeleton), 1257 standing prep on HQ
  (f0 proxy miss d=inf vs raw hit d=0.01, full skeleton) — clean-track
  box plus pose are visually coherent here.
- Incoherent: 47 early-flight horizontal rotation (f300 proxy miss
  d=0.36; HQ match d=0.01 but skeleton anatomically collapsed with
  limb misassignment); 2120 pike (f297, HQ d=0.29 miss despite large
  clear person); 47 late-flight vertical entry (f324 both miss d=0.70,
  splash/motion blur); 1257 flight tiny diver (f172, single proxy
  detection is a spectator 0.45 away); 2134 takeoff inversion
  (f230 both miss, diver upside-down — COCO upright bias).
  The 2134 compact-rotation case that caused the FAX8 false mixed-edge
  flag also defeats pose on both resolutions.

## Phase-specific reliability

- Standing / hurdle / preparation: reliable (proxy 0.83–1.00 except
  tiny-1257 0.00; HQ 0.64–1.00). HQ required for small-distant prep.
- Takeoff upright: reliable when upright and large.
- Takeoff inversion / handstand: unreliable even HQ (2134).
- Airborne rotation (horizontal/fast): unreliable on proxy; HQ improves
  recall (47/952/2120 flight 0.67–0.78) but skeletons show limb swaps
  and collapse — not geometry-ready.
- Compact tuck hold, slow, large (1849-like 403B): reliable (0.89–1.00
  both res, coherent skeleton) — the only flight sub-interval plausibly
  usable with hardening.
- Compact pike/fold (2120_f297, 2134): unreliable even HQ (0.00).
- Extension vertical: unreliable (47_f324 miss).
- Water entry / splash / POST: unreliable (0/6 proxy, 1/6 HQ) — do not
  run pose here.
- Small-distant flight (1257): unusable (proxy 0.00, HQ 0.11, dense
  0–11%).

Joints: shoulders, hips, elbows, wrists, knees, ankles are the only
candidates for geometry (95–100% present when matched), but L/R identity
flips 17–42% in flight and widths CV 50–75%, so they are not yet
geometry-ready without L/R disambiguation and temporal hardening. Head,
eyes, ears are excluded (10–86%, asymmetric occlusion).

## HQ / proxy findings

HQ materially improves detection recall and continuity (1257 prep
0→64%, 47 flight 33→67%, 952 flight 22→78%, 2120 flight 11→67%, dense
1849 25→86%, 2120 29→65%). Small-person prep is resolution-limited and
HQ rescues it. However HQ does not fix geometry stability: torso CV,
jitter, and L/R flips remain catastrophic during rotation/inversion
even on HQ (47 raw CV 0.199, jitter 0.384, flips 41%; 2120 raw CV
0.327, max jump 7.5 torsos, flips 42%). HQ is necessary but not
sufficient. Proxy-only pose is not viable for flight; any future pose
layer must be HQ-gated for small persons and phase-gated for flight.

## Geometry readiness

No stable full-action body geometry can be derived now. Torso length CV
0.09–0.33, shoulder/hip width CV 0.50–0.75, jitter median 0.13–0.38
torsos/frame, max jumps 1.1–7.5 torsos, L/R flips 17–42% — normalization
by body scale is not stable enough for later biomechanics. The sole
exception is slow-tuck-hold sub-intervals on large persons (1849: torso
CV 0.116, jitter 0.168, 86% HQ continuity) which could support geometry
after hardening (temporal smoothing, L/R disambiguation, phase gating).
Do not derive body-length / torso / hip / shoulder angles or velocities
yet.

## Failure modes that would corrupt later biomechanics

1. L/R swaps (17–42% flip rate in flight) — corrupts all lateralized
   angles and angular velocities.
2. Limb misassignment during fast rotation (HQ skeleton collapsed
   despite detection match, e.g. 47_f300_raw).
3. Inversion blindness (upside-down missed even HQ, e.g. 2134_f230) —
   COCO upright bias; systematic across diving.
4. Compact pike collapse (2120_f297, 2134 flight 0/9 both res).
5. Small-person miss and spectator hijack on proxy (1257 flight single
   detection 0.3–0.5 away is the wrong person).
6. Entry/splash disappearance (POST 0–17%).
7. Head/face occlusion asymmetry — must exclude head from geometry.
8. Torso foreshortening (CV up to 0.33) invalidates scale normalization.
9. Temporal jitter (0.13–0.38 torsos/frame) corrupts derivatives.
10. Mask/seg fails concurrently with pose — no silhouette rescue.

Any biomechanics built on current raw pose would ingest swaps, jumps,
and scale noise as false joint velocities and bend angles.

## Recommendation for the next science step

Pose hardening plus landmark integration before any geometry or
biomechanics. Specifically: (a) phase-gated, HQ-gated pose — run only
on PREP/standing and demonstrably slow-tuck sub-intervals, HQ-only when
proxy box area <~0.03; mark rotation/inversion/pike/entry intervals
unusable rather than forcing pose; (b) fix L/R identity with
track-conditioned side priors and temporal consistency before geometry;
(c) address rotation/inversion with diving-specific pose training or a
rotation-robust model (out-of-box COCO pose is the core blocker), not a
larger COCO model (m shows no systematic gain); (d) integrate with
frozen HUMAN landmarks / event outputs to gate phases, evaluating pose
quality independently as done here; do not tune Event Logic. More
diving pose data (fine-tune) is needed before the geometry layer. If
HUMAN pose annotation becomes necessary, keep it minimal and targeted:
the only uncertainty it would resolve now is L/R swap rate versus true
anatomical ambiguity — e.g. ≤20 flight frames across 47/2120 with
explicit L/R labels — after hardening, not before. No new full-action
overlay promotion, no dive score, no coaching advice, no automatic
identity.

## Artifact identities

| Artifact | Identity |
|---|---|
| Canonical branch/base | `uiux-overhaul-pro-app` / `ca5bab9` (commit containing this file identifies final HEAD) |
| FAX7 HUMAN authority | `docs/science/localization_annotations_v1/FULL_ACTION_GT_HUMAN_FAX7_FRESH/MANIFEST.json`, digest `b71b950e3af60d5f736642053ace5cfdd13f65b00328431e6d50f6a316bfc436` |
| FAX8 HUMAN authority | `docs/science/localization_annotations_v1/FULL_ACTION_GT_HUMAN_FAX8_FRESH/MANIFEST.json`, digest `a31d5bcfd93afa1704191e336dc72a5124255a97f19ad6da8eafea038b974188` |
| Pose weights | `yolov8n-pose.pt` SHA256 `c6fa93dd1ee4a2c18c900a45c1d864a1c6f7aba75d84f91648a30b7fb641d212`; `yolov8m-pose.pt` SHA256 `dbe539ea268db2534390942cfdf206e521f376f19e5415967a57f6a2ddfa3c90`; `yolov8n-seg.pt` SHA256 `a7cd8f929e1903d78a12a48efecab430209f18dc46cb96c3599a5980c63c423c` |
| Feasibility code (host-only dev) | `run_pose_feas.py` SHA256 `36216a56166ea5bbde33c2e64321a32e9492f790c59f74d11c9e1beee38c5fe7`; `run_dense_overlay.py` SHA256 `6514f46549d60f88ba38b9c377ceb9c1b0c95bd5f26cd0cdc9ba04a3243b2289`; `run_raw_dense.py` SHA256 `2156ac59eba7898b11e753572f1556abad0148926061950eec0f4c0b20236197` |
| Sampled pose result | host-only `/tmp/pose_feas/results/sampled_pose.json`, 117 samples, SHA256 `f9695e86bce498ec…` (full); canonical summary embedded above |
| Overlays | host-only `/tmp/pose_feas/overlays/` (72 PNGs, proxy+HQ pairs); representative cases described above |

SUPERVISOR_REVIEW_AFTER_CLEAN_TRACK_POSE_FEASIBILITY
