# Selected DiveTrack V1 protocol

## Question and immutable inputs

Given the correct surfaced S3 + frozen FSR flight candidate, determine whether
an identity-stable full-action trajectory and frozen Event Logic V3-C0 landmarks
can be recovered. HUMAN identity and event GT are used only in an evaluation
process after the candidate list is generated. The inference path has no
`diver_id` or subject GT. Multiple candidate tracks remain available.

S3 checkpoint SHA-256: `3dc07f69cbe3824490f73c14a59ed328ff35fc2da48da2fd4e324acf9bcc4e9a`.
Frozen FSR: `fsr_search_v1.py`, `fsr_rank_v1.py`, `fsr_pipeline_v1.py`.
Frozen Event Logic: `proposer_event_logic_v3_c0.py`. No changes to any of these
files are part of this protocol.

## Authority roles

The 14-dive FGT3H authority is **consumed diagnostic**. Twelve dives have a
recoverable surfaced S3 flight. Dives 377 and 1003 are separate perception
failures. FGT3H may guide development and diagnosis, but a change selected on
it is never described as fresh validation.

The new full-action evaluation authority is five previously HUMAN-labelled
FGT2H dives from five distinct sessions: 23 (s9), 980 (s60), 1555 (s98),
2257 (s131), 2288 (s140). None supplied the OOD boxes used to train S3
(66, 538, 540, 2498; see `fpsr2_build_ds2.py`).

Existing FGT2H flight boxes and event times identify the candidate for
evaluation, and do not enter inference. New full-action HUMAN boxes are drawn
blind to all detector/track output on verified raw proxy frames at every 0.5 s
from clip start until at least 0.1 s before HUMAN takeoff, and at +0.1/+0.3/+0.5
s after HUMAN water contact. Two repeated frames measure annotation agreement.
`visible`, `partial`, `not_visible`, and `ambiguous` are retained; ambiguous
frames are excluded from spatial accuracy and counted separately. Annotate
the diver who performs the intended flight, even if another diver appears.

## Evaluation

Run the exact frozen FSR top-5 selection on S3 360p plus strictly aligned HQ
candidate caches (all five HQ mappings passed the prior alignment registry).
Use HUMAN FGT2H
flight boxes to select the first qualifying candidate as a proxy for the user
click. An unsurfaced target is a perception failure and stays in the total
funnel denominator; it does not enter conditional selected-track statistics.
After selection, recover using only proposal geometry/confidence, recorded
PTS, and the selected flight. Preserve flight-core observations; do not let
long preparation outrank or replace them. Do not delete or invalidate another
candidate.

Measure per phase: visible-anchor coverage and precision/purity within the
frozen 0.06 normalized-center radius; observed temporal coverage; longest
missing interval; off-subject runs and switches; takeoff/entry span; box
continuity and clipping. Replay frozen V3-C0 without retuning; report each
event error and missing event, with apex only where HUMAN apex GT exists.
Report perception, trajectory, and Event Logic failures separately. The
five-session result is DEVELOPMENT evidence, with uncertainty and no claim of
production-wide reliability.

Protected exclusions: FINAL_HOLDOUT, INTERNAL_EVAL, Paris, 524, 2555 outside
stress authority, B2/Media Backbone mutation, detector training, identity,
pose, and segmentation. Large media, detector caches, paths, and overlays stay
outside Git. Frozen artifacts remain byte-identical.
