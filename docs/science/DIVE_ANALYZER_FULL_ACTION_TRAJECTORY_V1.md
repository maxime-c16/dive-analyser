# Dive Analyzer full-action trajectory V1 (DEV)

**Science decision: `FLIGHT_ANCHORED_EXTENSION_V1_DEV_VALIDATED`.**
A user-selected flight can be extended into the same diver's full dive on
tracks where detector evidence supports continuity, and the extension says
STOP with a labeled reason where it does not. The frozen FSR full pool path
is retired as a full-action representation (it silently wanders and silently
attaches). Frozen Event Logic V3-C0 fails systematically on the now
trustworthy tracks (first-motion firing, ~2 s early); a flight-anchored
takeoff prototype removes the failure without any threshold tuning. Neither
claim is a generalization claim: FAT1/FGT3H are DEV (design) evidence.
Fresh session-disjoint validation (FAT2) is queued and pre-registered.

## Diagnosis (why the FSR full path cannot serve)

- The surfaced FSR window (flight ±1 s/0.5 s) is intentionally
  flight-centered: prep coverage 0-3/10 on FAT1. Never a full-action track.
- The full pool path maximizes flight-motion evidence; preparation links
  earn ~0 (low-conf, slow/static motion), so its prep span is unconstrained:
  correct by luck on 1555/2257/23, attached to far-platform/other-diver
  activity on 2474/1731 (prefix median conf 0.00-0.02), empty on 980.
- The FSR search lattice removes static candidates, so quiet standing
  preparation has no nodes by construction (2288 f30-f120 STATIC-ONLY at
  HUMAN prep anchors; raw detector boxes exist).
- Raw detector absence also blocks some prep (23 f90/f120, 980 f30).
- The pool path carries no uncertainty signal: a confident pure prep chain
  (2257) and a conf-0.01 wander (2474) are indistinguishable in the output.

## FAX V1 (frozen; `experiments/full_action/FAX_V1_PROTOCOL.md`)

Flight-anchored bidirectional extension over the FULL floor lattice
(including static). The selected flight core is immutable. Greedy linking
with frozen-adjacent gates (residual 0.6, size ln 2.2, EWMA 0.35, speed 2.5,
bridge 0.30 s) plus two DEV additions: same-frame double merging
(center ≤ 0.06 or IoU ≥ 0.30 — the S3 floor's NMS-0.45 leaves 0.37-0.45
IoU doubles on one object) and same-object overlap (IoU > 0 with the
current box — a handoff across a gap must stop, not link). Uniqueness by
residual margin 0.25 (dominant MAP continuation links; near-ties stop with
AMBIGUOUS_HANDOFF). No confidence threshold anywhere (a handstand-prep
chain links through conf-0.002 boxes on dive 31; a conf floor would destroy
it). Forward scope cap 0.5 s past core end (POST_ENTRY_CAP). Missing frames
are absent, never synthetic. V1 stops rather than bridging uncertainty;
alternatives are reported bounded, never linked. Sensitivity grid
(margin × merge 3×3) leaves all scored coverage/purity invariant.

## DEV results (FAT1 prep + FGT3H flight-only; design evidence only)

| Dive | Prep (hits/visible, purity) | Flight | Backward stop | Forward stop |
|---|---|---|---|---|
| 1555 | 6/6, 1.0 | 9/9 | CLIP_START | AMBIGUOUS (submerged junk tie — correct) |
| 2257 | 7/7, 1.0 | 9/9 | GAP (1.27 s, nothing linkable) | GAP (submerged) |
| 2288 | 7/7, 1.0 | 9/9 | CLIP_START (static prep linked) | GAP |
| 23 | 1/10, 1.0 | 9/9 | AMBIGUOUS (margin 0.22, 0.35 s pre-core; honest) | GAP at clip end |
| 980 | 0/3 | 8/9 | GAP (no prep evidence; honest flight-only) | GAP |
| 31 | — | 7/9 | CLIP_START (handstand prep chain) | GAP |
| 872 | — | 9/9 | CLIP_START (7 s platform chain) | POST_ENTRY_CAP (≤0.5 s poolside tail — known limit) |
| 966 | — | 8/9 | CLIP_START (3 m platform chain) | GAP |
| 1731/2474 | — | 9/9, 8/9 | GAP (far-platform wander refused) | GAP |
| 992/2242 | — | 6/9, 7/9 | GAP (weak/OOD tracks, honest small tracks) | GAP |

Pooled FAT1 prep: 21/33 anchors at purity 1.0 (zero wrong-person links).
Overlays show the user can follow the same diver through the action on
1555/2257/2288/31/872/966-class tracks. 23 is a near-margin honest stop;
980/992/2242 are honest short tracks (perception limits, not extension bugs).

## Event Logic (frozen V3-C0 replayed unchanged, '' context)

On the FAX tracks V3-C0 takeoff errors are −2.0 to −3.1 s on
1555/2257/31/872/966/1637/2040 and missing on partial tracks; only
2288/2474/1417 pass (≤ 0.25 s). Mechanism (confirmed): takeoff = FIRST
sustained rise after the FIRST stillness, so any visible prep motion (arm
raise, hurdle jump, first step) fires seconds before true departure; the
flight anchor is unused, and the dive-code context branch does not rescue
springboard/standing cases (true-code replay fixes only 2257/HURDLE).
This is an Event Logic blocker on recoverable tracks, not trajectory noise.

V4-A0 DEV prototype (flight-anchored takeoff: last pre-flight low point +
first sustained rise after it; frozen PARAMS_E1 thresholds; apex/wc reuse
V3-C0 bounded detectors; NOT frozen, no validation claim): takeoff error
−0.17 to −0.48 s on 14/17 FAX tracks, honest abstention on 980/992/2242.
Same trajectories, same thresholds — the failure was event semantics.
The uniform ~0.25 s early bias is a calibration question for the successor
cycle (rise-onset vs HUMAN last-contact definition), not tuned here.

## Gate and next steps

Predeclared FAT2 gate (frozen protocol): (i) flight ≥ 0.75 coverage/purity
every track; (ii) pooled prep purity 1.0 on overlapping visible anchors;
(iii) pooled prep coverage ≥ 0.5 (honest stops count as missing);
(iv) every track end labeled. FAT2 = {1190/s75, 1279/s80, 2838/s202} with
new HUMAN takeoff/contact/apex + prep/flight/post boxes; queue committed
before annotation; selection viability pre-screened GT-free (all viable).
If the gate clears: freeze the flight-anchored Event Logic successor with
its own protocol + fresh event authority (apex included), then run the
bounded box-overlay pilot. Pose/biomechanics stay paused until landmarks
validate; current evidence supports reopening them after the successor gate.

## Identities

FAX code SHA-256 `55282fb968cc960919242ee43ef9ebd3db7c13becbd663aab35b3b150306a2ad`
(`experiments/full_action/fax_extension_v1.py` at the integration commit;
protocol text frozen pre-FAT2-eval).
S3 `3dc07f69…`; FSR search/ranker/pipeline SHAs per the selected-DiveTrack
report; V3-C0 source `9c507719…`. DEV record (host-only):
`runs/full_action_fax_v1/fax_v1_dev_results.json`. FAT1 digest
`91f72996…`; FGT3H digest `83326b04…`. No protected set, Paris, 524, 2555,
B2/media mutation, detector training, identity, or pose work.
