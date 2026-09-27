# FAT3 gate V1 — verdict: FAIL (with validated generalization on unambiguous tracks)

**Gate verdict: `FAT3_GATE_FAIL`.** All 6 dives surfaced a qualifying
flight (no unsurfaced cases), but pooled prep purity is violated (4
wrong-person overlaps on 2 tracks) and pooled prep coverage is 29/70 =
0.414 < 0.5. The flight criterion (i) fails on 2519 (0.667 < 0.75).
This is a FAIL, not a VOID — and the attribution below is the scientific
yield: FAX V1 generalizes perfectly where identity is unambiguous, and
fails by association (not perception) in multi-person prep scenes.

Full record (host-only): `runs/full_action_fat3/fat3_gate_results.json`.
Eval code SHA `81dd9d03…` (self-contained; latent FAT2-path bugs fixed:
self-contained selection/scoring, SELECTED-row assignment, rep-dict cache).
FAX code SHA `55282fb9…` (frozen, unchanged). V4-B0 SHA `21ad37bb…`.

## Strict gate record (frozen rule, fresh HUMAN boxes, radius 0.06)

| Dive | Flight (hits/vis, pur) | Prep (hits/vis, pur) | Back stop | Verdict |
|---|---|---|---|---|
| 16 | 8/9, 1.0 | 0/30, — (2 wrong) | AMBIGUOUS_HANDOFF | SELECTED |
| 251 | 8/9, 0.89 | 11/11, 1.0 | CLIP_START | SELECTED |
| 1491 | 9/9, 1.0 | 12/12, 1.0 | CLIP_START | SELECTED |
| 1716 | 7/9, 1.0 | 0/0 (none visible) | GAP_TOO_LONG | SELECTED |
| 2519 | 6/9, 0.75 | 0/11 (2 wrong) | GAP_TOO_LONG | SELECTED |
| 2742 | 9/9, 1.0 | 6/6, 1.0 | GAP_TOO_LONG | SELECTED |

Pooled prep: 29/70 coverage, 4 wrong overlaps. Ends 12/12 labeled.
Sealed viability (pre-annotation, same rule as FAT2): 7/7 viable.

## Attribution (per dive; visual + coordinate forensics, not speculation)

- **1491 — VALIDATED full recovery.** 12/12 prep + 9/9 flight, same athlete
  on one board throughout (HUMAN+FAX coincide tightly), CLIP_START.
  Frozen FAX generalizes on fresh data. ✓
- **251 — VALIDATED full recovery (after adjudication).** 11/11 prep +
  8/9 flight. The prep person at the satellite board is the SAME athlete
  (annotator-adjudicated; deck-wait → board-sprint → rushed hurdle →
  center-board dive). Initial two-body reading recorded and retracted;
  targeted annotator adjudication is now the identity firewall.
- **2742 — VALIDATED full track.** 6/6 prep + 9/9 flight, one athlete
  mounting/standing/hurdling on one board, no second dive in clip.
- **1716 — honest short track.** Clip opens on an empty scene; the diver
  walks in (~3.3 s); all prep anchors correctly HUMAN-not-visible; GAP/GAP
  stops; flight 7/9. Abstention-by-structure, not a failure.
- **16 — association failure (crowd drift).** HUMAN right on all 30 prep
  anchors (1m blue diver). Backward chain leaves the correct flight core
  and is on the wrong object within ~1 s (f466 dist 0.16, f481 dist 0.09:
  wrong object, not radius noise), then stops AMBIGUOUS_HANDOFF at f465
  (margin 0.015; diver candidate present in floor at conf 0.007 but gated
  out). Scene has TWO SIMULTANEOUS divers (1m + 3m) + walkers-by. The stop
  is desirable; the 2 wrong links before it are the violation.
- **2519 — association failure (static-junk ride).** HUMAN right (diver
  waiting at pool edge, S3 conf med 0.77 at 10/11 prep anchors). Backward
  chain steps off the diver onto a frozen water-junk box via an IoU-0.10
  handoff (f334) and rides it 0.35 s (IoU≈1.0, conf 0.001–0.01) while the
  diver steps to the board. Partial flight (starts 0.27 s post-takeoff,
  6/9). Both Event Logics honestly abstain.

## Q1: does frozen FAX V1 generalize on fresh visible-prep dives? YES —
where identity is unambiguous: 29/29 prep anchors at purity 1.0 across
1491/251/2742 (fresh sessions, fresh athletes' scenes), zero wrong links,
CLIP_START/GAP labeled ends. The DEV design claim (21/33 @ 1.0) is now
fresh-validated in its regime.

## Q2: perception or extension? EXTENSION.

S3 floor contains the HUMAN-boxed diver at 56/65 visible prep anchors
(16: 19/30, 2519: 10/11 @ conf 0.77, 2742: 6/6, 1491: 11/12, 1716: 0/0
honest). Zero evidence of a FAT2-class perception bound in this regime.
Both failures are wrong-identity links through geometrically-plausible
chains: crowd drift across overlapping people (16), confident static-junk
ride (2519). FAX V1's identity-free geometric gates (IoU>0 + residual
margin 0.25) admit confident wrong-person links: a static distractor
outranks the moving diver on residual at handoffs, and near-tie
AMBIGUOUS fires only when competitors tie — not when junk wins
outright. **This demonstrates a real algorithmic limitation and justifies
a FAX successor cycle** (identity-aware association; not built here —
FAT3 is burned as validation).

## Event Logic baseline (frozen V3-C0, same validated tracks)

V3-C0 still fails: 1491 takeoff −3.033 / apex −3.167 / wc −3.750;
2742 −2.352/−2.369/−2.986; 251 −1.933/−2.000/−2.417 (first-motion firing
on long prep, as on DEV). 1716 −0.100/0.000/−0.067 (short prep: passes).
2519 + 16-prep-contaminated: abstains / −0.667 (reported, not gated).

## Event Logic successor (frozen V4-B0, DEV-calibrated, never tuned on FAT3)

On identity-clean tracks {1491, 2742, 251, 1716}:

| Dive | V4-B0 to/apex/wc err |
|---|---|
| 1491 | 0.000 / 0.000 / −0.583 |
| 2742 | −1.168 / −1.268 / −1.885 |
| 251 | −0.883 / −1.183 / −1.583 |
| 1716 | +0.133 / 0.000 / −0.067 |
| 16 (flight-validated, prep-contaminated; reported separately) | +0.133 / −0.033 / −0.167 |
| 2519 | honest abstention (both logics) |

Takeoff median |err|: V4-B0 0.508 (n=4) vs V3-C0 2.142 on the same
tracks (with 16: 0.133 vs 2.033). Apex on clean takeoffs is EXACT
(1491/1716: 0.000 — first validated fresh apex errors; adequate once
takeoff is correct, no over-engineering). WC is mixed: fine on 1716/16
(−0.067/−0.167), early on 1491 (−0.583, water-line threshold semantics
vs first-touch definition — known V3-C0 inheritance, not tuned here).

**New successor failure mode (both legit tracks): prep-rise lock.**
On 2742 V4 locks onto the board-mount rise (~2.8 s) and on 251 onto the
satellite-board bounce (~4.3 s): "first sustained rise after the last
local low" does not prefer proximity to the flight anchor, and smoothing
can erase the true hurdle dip's locality. DEV had no mounting/bouncing
prep rises, so this was invisible at freeze. Successor-cycle direction:
prefer the sustained rise CLOSEST to ft0 (flight-continuation
constraint); no change made here (FAT3 is validation).

Predeclared bar (median |takeoff| ≤ 0.5, apex/contact not regressed vs
V3-C0): narrowly missed on the strict n=4 set (0.508), met with n=5
(0.133); apex/contact strongly improved either way (apex med 0.067 vs
2.369; wc med 0.583 vs 2.986). Material improvement: YES (4–16× on
takeoff). Reliable landmarks: YES on unambiguous single-rise prep
(1491/1716-class); NO on mounting/bouncing prep (251/2742-class) —
the next successor cycle's design input.

## Overlay readiness: CONDITIONAL, not general

Stable full-action box overlay is viable on sparse single-diver tracks
(1491/2742-class: pure, labeled ends). In multi-person prep scenes
FAX V1 can display the WRONG PERSON confidently (16/2519-class) — a
product overlay must not ship without identity-risk flagging. Recommend:
bounded overlay pilot on sparse scenes + FAX-successor cycle for crowds.

## Pose/geometry: stay PAUSED

Trajectory + landmarks validate only where identity is unambiguous; the
remaining blocker is identity-aware association. Attaching pose to a
possibly-wrong person would be worse than no pose. Reopen after the FAX
successor gate.

## Remaining blocker (exactly one): trajectory extension —
identity-aware association in multi-person prep scenes. NOT perception
during prep (S3 sees the diver: 56/65 anchors) and NOT event semantics
(V4-B0 works on clean tracks: 3/4 within ±0.15 s, exact apexes).

## Methodological notes

- Targeted annotator adjudication (251: same-athlete verdict) resolved a
  genuine two-body ambiguity the designer could not resolve from pixels
  alone. Future queues: pre-register an identity-adjudication step for
  multi-person prep scenes; never unilaterally overturn HUMAN identity.
- The 251 episode also retroactively qualifies DEV purity claims
  (21/33 @ 1.0): same-identity risk there is unverified, not refuted.
- No ghost-exclusion incident (no /api/exclude traffic outside Maxime's
  session; exclusion set empty).
- Annotation viewer viewport fix (648×360 landscape dive 16 pushed the
  panel off-screen): committed pre-annotation (`34fb42b`), draft verified
  empty, geometry unaffected.

## Identities

Queue/protocol `69ad2f2`; V4-B0 freeze `39bba63`; viewer fix `34fb42b`;
authority `a2eade0` (`FULL_ACTION_GT_HUMAN_V3_FRESH`, 182 items +
FAT3_EVENTS, digest `dfd493f0…`, zero exclusions). FAX `55282fb9…`;
S3 `3dc07f69…`; V4-B0 `21ad37bb…`; eval `81dd9d03…`. Host-only: S3 FAT3
caches, `fat3_gate_results.json`, overlays, DEV repro (`dev_tracks.json`,
exact match to frozen DEV record), y(t) + adjudication strips.
