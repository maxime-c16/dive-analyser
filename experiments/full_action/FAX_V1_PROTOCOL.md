# Flight-Anchored Extension V1 (FAX V1) — protocol (FROZEN 2026-09-26)

Status: FROZEN. Constants below are fixed. Any change requires a new
versioned protocol. Frozen FSR search/ranker/pipeline and frozen Event
Logic V3-C0 were not modified. Code: `experiments/full_action/fax_extension_v1.py`
at the freeze commit (SHA recorded in the integration report).

## Question

Given a user-selected flight DiveTrack (flight segment + core observations),
recover the same diver backward (preparation, true departure) and forward
(entry, immediate post-entry) without switching identity, and say STOP with
a reason where continuity is not defensible.

## Immutable inputs (GT-free inference)

- Selected flight: `flight_segment` time bounds `[ft0, ft1]` (proxy PTS) from
  the frozen FSR ranker, and the underlying pool-path node set restricted to
  that window = the immutable CORE. The selected flight remains the semantic
  anchor; extension may widen the span but never replaces core observations.
- Extension lattice: the FULL S3 floor candidate set (`conf >= 0.001`,
  `NMS 0.45`, cap 200) on the SELECTED representation's proxy timeline,
  INCLUDING static candidates. This deliberately differs from the FSR
  search lattice, which removes static nodes: a standing diver has no FSR
  node, so FSR paths cannot represent quiet preparation by construction
  (observed: 2288 prep anchors f30-f120 are STATIC-ONLY in the FSR lattice).
- Recorded proxy PTS. No `diver_id`, no subject GT, no appearance features,
  no detector retraining. Other DiveTrack candidates are untouched.

## Algorithm (deterministic, greedy, bidirectional from the anchor)

Core = pool-path nodes with ft0 <= pts <= ft1 (immutable, status CORE).
Edge velocities = time-forward EWMA from core nodes. Then per direction
(-1 backward from core start, +1 forward from core end):

- Scan the NEAREST frame within G_BRIDGE_S holding >= 1 gate-passing
  hypothesis. Hypotheses = same-frame candidates merged when center
  distance <= RADIUS or pair IoU >= IOU_MERGE (the S3 floor's NMS-0.45
  leaves sub-0.45-IoU double detections of one object; DEV trace: every
  multi-hypothesis step shows pair IoU 0.37-0.45 when a double is present).
- Gate (all must pass): candidate overlaps current box (IoU > 0:
  asserts the SAME image object; a handoff across a spatial gap has
  IoU = 0 and must stop); prediction residual <= E_REL_MAX box sizes
  (constant-velocity EWMA); |log area ratio| <= SIZE_TOL; EWMA speed <=
  V_SMOOTH_MAX.
- 0 hypotheses in window -> STOP: CLIP_START/CLIP_END if the bridge window
  reaches the clip boundary, else GAP_TOO_LONG.
- >= 2 merged hypotheses with (resid_2nd - resid_best) < RESID_MARGIN ->
  STOP: AMBIGUOUS_HANDOFF (record n competitors, margin, frame, top-3).
  A dominant MAP continuation far ahead of floor junk is LINKED.
- 1 hypothesis -> LINK (status LINKED); jumped frames marked BRIDGED
  (absent, never synthetic boxes); update EWMA; continue.
- Forward only: stop at core_end + FWD_MAX_S with POST_ENTRY_CAP
  (scope stop, explicitly labeled; not an evidence claim).

No confidence threshold anywhere: geometry decides. DEV evidence: a
handstand-prep chain (dive 31) and a 7 s platform chain (dive 872) link
through conf-0.002 boxes that are geometrically continuous from the
anchor; a conf floor would destroy them. Conversely low conf never
promotes a link (uniqueness + gates required).

V1 abstains rather than bridging uncertainty: there are no interior
UNCERTAIN intervals — an uncertain handoff ends the asserted track, with
near-miss alternatives reported bounded (top-3, NOT linked).

## Frozen constants

| Constant | Value | Source |
|---|---|---|
| RADIUS (merge + agreement) | 0.06 norm-center | frozen FSR agreement scale |
| E_REL_MAX | 0.6 box sizes | frozen FSR residual gate |
| SIZE_TOL | ln(2.2) | frozen r5 size gate |
| VEL_ALPHA | 0.35 | frozen r5 EWMA |
| V_SMOOTH_MAX | 2.5 norm/s | frozen FSR physical cap |
| G_BRIDGE_S | 0.30 s | frozen V3-C0 interp_max_gap_s |
| SCALE_CAP | 0.20 | frozen FSR scale cap |
| RESID_MARGIN | 0.25 | DEV grid: separates observed dominant links (margin >= 0.29) from near-tie stops (margin <= 0.24); FAT1/FGT3H scores invariant over {0.15, 0.25, 0.35} |
| IOU_MERGE | 0.30 | DEV: merges NMS-0.45 doubles (observed pair IoU 0.37-0.45); scores invariant over {0.20, 0.30, 0.40} |
| FWD_MAX_S | 0.5 s past core end | DEV: core end overshoots contact by <= 0.35 s; covers +0.5 s HUMAN probes with margin; bounds splash->poolside morph tails (dive 872) |

## Output: AnalysisTrack FA-V1 (per selected flight)

`{version, dive, rep, anchor:{ft0,ft1,core_frames,n_core},
backward:{n_linked, bridged, stop}, forward:{...},
trajectory:{f:{box,conf,status}}}` with status in {CORE, LINKED};
missing frames absent; `stop.reason` in {CLIP_START, CLIP_END,
GAP_TOO_LONG, AMBIGUOUS_HANDOFF, POST_ENTRY_CAP} with stop frame/time and
bounded alternatives.

## DEV evidence at freeze (17 dives; FAT1 prep + FGT3H flight-only)

FAT1 (new prep boxes, now DEV for this design): 1555 6/6 pure,
2257 7/7 pure, 2288 7/7 pure, 23 1/10 pure (near-margin AMBIGUOUS stop
0.35 s before core; honest), 980 0/3 (no prep evidence; honest
flight-only). Flight 9/9 except 980 8/9 (frozen-core node, unchanged).
FGT3H (consumed flight anchors): flight preserved at/above prior surfaced
scores on 11/12 (992 6/9 vs 8/9: conservative GAP refusal at core edge);
contamination refused on 1731/2474 (GAP/AMBIGUOUS stops instead of the
prior pool path's far-platform wander); full prep chains recovered on
31 (handstand), 872 (7 s platform), 966 (3 m platform) with visual
continuity. Sensitivity grid (margin x merge 3x3) leaves all scored
coverage/purity invariant: the operating point sits on a stable plateau.

## Fresh validation gate (predeclared; needs new blind authority)

FAT2 (dives/sessions disjoint from all training, consumed, and DEV sets)
with new HUMAN prep/entry boxes + takeoff/contact/apex events:
(i) flight coverage >= 0.75 and purity >= 0.75 on every selected track;
(ii) pooled prep purity 1.0 on overlapping visible anchors (zero silently
linked wrong-person prep);
(iii) pooled prep coverage >= 0.5 over visible anchors (honest stops count
as missing, not errors);
(iv) 100 % of track ends carry a labeled stop reason.
Gate evaluation runs the frozen code unchanged. FAT1/FGT3H must not be
re-scored as validation.
