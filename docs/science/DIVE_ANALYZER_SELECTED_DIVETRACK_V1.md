# Dive Analyzer selected DiveTrack V1

**Science decision: `SELECTED_FLIGHT_DOES_NOT_YET_YIELD_RELIABLE_FULL_DIVE_ANALYSIS`.**
Correct flight selection removes the main perception identity choice, but the
current frozen FSR output is a short flight-centered window, and its complete
underlying path is not a safe full-action replacement. On two visually clean,
longer paths, frozen Event Logic V3-C0 makes large early-event errors. The next
work must treat trajectory extension and Event Logic as separate blockers.

## Evaluation authority

The S3 manual-selection gate remains its prior **11/14 top-1, 12/14 top-5,
12/14 top-10** on FGT3H. That 14-dive authority is consumed; it was used here
only for diagnosis. Dives 377 and 1003 remain distinct perception failures and
are absent from conditional downstream denominators.

New full-action HUMAN GT was collected blind to tracks on five FGT2H dives
from five distinct sessions: 23/s9, 980/s60, 1555/s98, 2257/s131, 2288/s140.
Their existing flight boxes and takeoff/contact times were already consumed
by earlier perception research, but none of these five was in S3's OOD training
set. The **new** preparation/post-entry labels were not used to choose a
trajectory method. Forty of 54 annotation items are visible/partial, 14 are
not visible; two blind repeats differ by 0.0088/0.0053 normalized center.
The authority is five sessions of DEVELOPMENT evidence, not a new detector
holdout or production-wide generalization claim.

## Selected flight to trajectory

S3 proposals were generated with the frozen floor recipe (confidence 0.001,
NMS 0.45, image size 640, cap 200) on verified 360p proxies and strictly
aligned HQ renditions. Frozen FSR independently generated and ranked up to
five DiveTracks; the first flight matching HUMAN flight boxes was selected
**after inference**, as a proxy for a user's click. All five were rank 1 in
this set. Other candidates remained in the list (2–5 per clip), unchanged.
No `diver_id`, subject GT, or identity feature entered path reconstruction.

Two existing representations were replayed unchanged: the actually surfaced
FSR candidate, bounded to flight segment minus 1 s/plus 0.5 s, and the entire
underlying FSR pool path from which it was cut. The surfaced candidate's flight
observations were not replaced. No new heuristic was promoted after seeing
the five-dive GT: a tuned extension would require another fresh authority.

## Recovery and continuity

HUMAN box hits use the frozen 0.06 normalized-center radius. Preparation
purity is hits divided by *overlapping visible* anchors; a missing box counts
against coverage, not purity. “Full span” runs from the first visible prep
anchor to HUMAN water contact; frame coverage counts detector observations
in that interval and includes any unobserved prefix.

| Dive | Selected flight hits | Surfaced prep hits | Full-path prep hits / visible | Full-path prep purity | Full-path span frame coverage | Longest missing interval |
|---|---:|---:|---:|---:|---:|---:|
| 23 | 9/9 | 1/10 | 5/10 | 5/7 | 75.1% | 1.585 s |
| 980 | 8/9 | 0/3 | 0/3 | no overlap | 46.7% | 1.235 s |
| 1555 | 9/9 | 1/6 | 6/6 | 6/6 | 99.2% | 0.033 s |
| 2257 | 9/9 | 2/7 | 6/7 | 6/6 | 91.9% | 0.350 s |
| 2288 | 9/9 | 3/7 | 3/7 | 3/3 | 60.5% | 0.617 s |

All five surfaced and full-pool tracks hit the one visible post-contact anchor
per dive; two later post-entry probes were often HUMAN-marked not visible.
Hence this is evidence of immediate entry recovery, not sustained underwater
tracking. All five selected flights meet the historical >=75% flight recovery
rule, but only 1555 and 2257 recover substantial *preparation* with strong
anchor support and visual continuity. Dive 980 has no pre-takeoff observation;
2288 lacks four of seven visible prep anchors. Dive 23 has two center-radius
mismatches on overlapping preparation anchors. Its contact sheet looks like
one continuous diver; the misses may be poor box localization rather than a
confirmed identity switch. Across all five, max adjacent observed gap on the
full path is 0.02/0.17/0.05/0.08/0.18 s respectively (23/980/1555/2257/2288);
the larger missing intervals in the table arise chiefly from absent prefixes.

The consumed FGT3H diagnostic gives a separate contamination warning: visual
box sheets for 1731 and 2474 show the long FSR pool path attaching to earlier
pool or other-diver activity before the selected flight. Thus its apparently
larger temporal extent cannot be equated with selected-subject continuity.
The root assumption error is that a global best-through FSR **flight-search
path** is also a certified full-action PersonTrack. The surfaced 1 s/0.5 s
limits were never a full-action recovery method. There is no justification for
silently substituting the full pool path in the product.

## Frozen Event Logic V3-C0

No Event Logic code, parameters, family routing, or event context was changed.
Errors below are absolute seconds against existing HUMAN takeoff/water-contact.
`—` means no complete event sequence was emitted. HUMAN apex GT was not
collected in FGT2H, so apex predictions are retained in the host JSON but
**apex error is unscored**.

| Dive | Surfaced takeoff / contact | Full-path takeoff / contact | Attribution |
|---|---:|---:|---|
| 23 | — / — | 3.320 / 1.535 | prep localization/association uncertain; early Event Logic sequence |
| 980 | — / — | — / — | no preparation, insufficient path |
| 1555 | 0.217 / 0.600 | 2.183 / 2.750 | Event Logic selects early prep on visually continuous full path |
| 2257 | 0.234 / 0.250 | 2.135 / 0.467 | Event Logic selects early prep on visually continuous full path |
| 2288 | 0.234 / 0.033 | 1.018 / 1.368 | missing prep plus early Event Logic sequence |

The 1555 and 2257 contact sheets show the same diver throughout the extended
path, and their prep/flight HUMAN purity is 100% on overlapping anchors. V3-C0
nonetheless moves takeoff more than 2 s early on both. This is a real
**Event Logic blocker on recoverable tracks**, not evidence to retune it here.
Conversely, 980 and 2288 cannot support a claim that Event Logic alone is the
primary cause, because their full-action trajectories are incomplete. None of
the five full-pool outputs supports reliable takeoff/contact analysis, even
before requiring a scored apex.

## Box overlays and next science

Bounded host-only diagnostic box sheets were rendered for selected full paths
on 23/1555/2257/2288 and consumed cases 1731/2040/2242/2474/31. Boxes are
technically sufficient for a user to identify the **flight candidate**. They
also expose the unsafe longer association in some clips. Selected full-action
box overlays and per-track pose/biomechanics are **not generally ready**;
pose remains paused. `Dive.diver_id` stays distinct from a user's selected
analysis track, and selection leaves all other DiveTracks intact.

Next, build an explicitly flight-anchored, phase-aware extension that reports
uncertainty and can stop before an identity handoff; validate it on a new
session-disjoint DEVELOPMENT authority. After its track quality clears a
predeclared gate, address V3-C0's early-preparation event logic with separate
fresh event authority, including HUMAN apex labels. Do not tune Event Logic
to compensate for missing or contaminated trajectories.

## Exact identities and reproducibility

Starting canonical HEAD: `01d6c3cfec18269213fd02687dc186838249c7dd`.
S3 checkpoint: `3dc07f69cbe3824490f73c14a59ed328ff35fc2da48da2fd4e324acf9bcc4e9a`.
D5: `82b420c4583f8271b1eb3429b14dadf0a1e27477249de7b6a0b9d42a788dcf25`.
S2: `d3ba0b035e7a8eb20bb5af66db62984bfb4682075b0c1267677d293e0e9d9c7f`.
S3 360 cache: `5b0c3e2f37f717fc5062d3d728f019d570e63552e14846d43c9673ac3baf87a0`.
S3 HQ cache: `443b9a1947b43dbaa40f470884a207e03d5e564666bebd46d146097077d40f98`.
Frozen FSR search/ranker/pipeline source SHA-256:
`7fe664c9cd55fada0856c7b59cfa7f15f13114505011f753a262b368bb027091`,
`c8403a0562d9d4dd24b2c67ce7adce0586aa7feb9304aa595fe5ca6b1a69201f`,
`6ef686ddd1ed3adf4c09248fa7e4d7831bd49df8b71d75008c59ce182f06b48d`.
Frozen V3-C0 source: `9c5077191699416e0148f868bd0d2fc6f19fd5a823102eeb1bdd5e0f129a8438`.
Pre-existing FGT2H digest: `f971294256212070fdae5202db16ca40922a33f84ee732ed00c738e44969392f`.
New full-action GT digest:
`91f729961f7acc21608b642043efc465f27e8887d80436b557ed452709983dc1`.

Reproduction: `python3 experiments/flight_perception/selected_track_fresh_eval_v1.py`
with the recorded local S3 caches and verified source media. Host-only exact
results: `runs/selected_divetrack_v1/fresh_full_action.json`; no large media,
caches, or overlay images are in Git. No protected evaluation set, Paris, 524,
or 2555 data was accessed. No B2/Media Backbone mutation, detector training,
identity, segmentation, or pose work was performed.
