# FAX V3 uncertainty-aware development and fresh gate

2026-09-27. FAX V1/V2, S3, FSR, Event Logic V3-C0/V4-B0 and all protected
authorities are frozen. V3 is a separate development candidate. It receives
one user-selected FSR flight and the unchanged S3 floor; HUMAN labels and
`diver_id` never enter inference.

## Representation

The selected flight retains its immutable FSR provenance. `trajectory` contains
only asserted person-specific boxes. `uncertainty` records unresolved mixed
flight intervals, a bounded list of possible component explanations and NULL,
source frame counts, and the first/last selected times. A downstream overlay
must render this state visibly as uncertain and must not draw the mixed box as
though it isolated the diver. V3 currently detects a broad flight-edge box
containing a sustained, laterally separated compact floor component within
0.65 s before the edge. It abstains on the whole selected track in that case:
the component could be the target or the neighbor, and neither geometry nor
confidence certifies which. Otherwise it delegates to conservative V2.

The V3 thresholds are development choices based on consumed FAX2 and FAT3
only. No appearance or segmentation result has been accepted. In particular,
V3 does not claim to recover a target-specific subcore from 205's group boxes.

## Fresh authority, sealed before track evaluation

Metadata screen: edited media blobs, non-lineup and non-sync, 1m/3m, duration
at least 10 s. Prior FAX2/FAT3/FAT2 and protected sessions excluded. Two
metadata shortlists were fetched read-only from B2 and source SHA256 checked
against `media_blobs`. Raw contact sheets alone were used for viability;
detector or track output was never used for queue selection. First shortlist
mostly showed empty preparation or tiny distant figures. The selected queue
has 1515/s94, 2086/s128, 2160/s131, 2674/s156. 1810/s111 is reserve only
if a main dive is HUMAN-unlabelable. These clips include long visible prep,
competing people on 1515/2086, and simpler controls on 2160/2674. Exact proxy
SHA256 and PTS are in host-only `runs/fax_v3_media/PROXY_REGISTRY_FAX_V3.json`.

The annotation UI shows raw study-local proxy frames only. The HUMAN annotator
marks takeoff/contact/apex (with blind apex repeat), nine flight boxes at
eighth-step fractions including endpoints, prep every 0.5 s, post-entry probes and a blind prep
repeat. Visibility includes visible, partial, not visible and identity
ambiguous. The authority is not valid until the completed labels are frozen
with a file-hashed manifest. The selected-flight rule remains the FAX2 rule:
first Q-ordered FSR candidate with at least two correct flight anchors,
coverage at least 0.75 and purity at least 0.75 within radius 0.06. HUMAN is
used only to emulate the correct click in evaluation.

## Required readout

Report CORRECT_CONTINUATION, HONEST_ABSTENTION and WRONG_PERSON_CONTINUATION
separately for visible prep, flight, post and full-action anchors. Review any
mixed-core box visually for instance purity. Report first wrong-link time,
longest missing/uncertain interval, selected-flight preservation, adjacent-box
stability and whether the physical diver remains represented across the
transition. Compare V1/V2/V3 on identical selected candidates. A zero-wrong
result on a tiny or all-abstaining conditional set does not clear the gate.
Full-action overlay promotion requires useful correct coverage, no silent
switches in the fresh crowd cases and visible uncertainty rendering. Event
Logic replay is diagnostic only after trustworthy trajectories; pose remains
paused until the trajectory gate passes.
