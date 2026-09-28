# Dive Analyzer mixed-interval reattachment — detailed supervisor output

Date: 2026-09-28. Product path under test:
`S3/FSR flight candidates → user selects the physical diver → mixed detector interval → NULL/competing paths → person-specific reattachment → full-action overlay`.
Gate token: `SUPERVISOR_REVIEW_AFTER_MIXED_INTERVAL_REATTACHMENT`.

## Executive conclusion

**Local reattachment demonstrated; general promotion rejected.** A frozen
development candidate represents the selected flight's first mixed box as
uncertain, derives a later trusted subcore from individual person masks,
and emits NULL until a supported local mask path is available. On a new
blind, session-disjoint HUMAN gate it reattached to the selected physical
diver in both qualifying mixed-flight cases: **2/2 correct reattachments,
2/2 explicit pre-reattachment NULL intervals, 0/2 observed wrong-person
continuations**. The respective unresolved intervals lasted 0.400 s and
0.100 s. All eight asserted mixed-flight HUMAN anchors showed the correct
person on raw-frame review. These are two case outcomes, not population
rates or proof that the branch selector cannot switch silently elsewhere.

The method restores useful flight coverage relative to uncertainty-aware
FAX V3/V4: 8/18 visible mixed-flight anchors are person-specific, versus
0/18. It does not reconnect earlier preparation on either mixed clip:
0/19 visible prep anchors asserted. The ungated V1/V2 baseline had no
observed physical-person switch on this fresh authority, so a material
reduction in silent switches is **not demonstrated** here. General
full-action box overlays remain unsafe. FAX instance V1 is retained as
development evidence, not promoted into inference; Event Logic and pose
remain frozen.

## Repository, method firewall, and authority order

- Canonical Git: `diveanalyzer-server:~/dive-analyser`, branch
  `uiux-overhaul-pro-app`. The raw-only FAX6 queue and frozen instance
  prototype were committed at `122ea6818999c2a284975fb9aee4e146832efb5c`.
  HUMAN labels were sealed at
  `9965c9783e429ac82b6b6c9c6e6c2a15e5820067` before any FAX6
  S3/FSR/FAX outcomes were inspected. The concise gate and PROJECT_STATE
  were integrated at `fcf15c1c06fb13b3739f4f165d314a2a11f5a1c9`.
- Frozen inputs preserved: S3, FSR, FAX V1/V2/V3, D5/S2, V3-C0/V4-B0,
  global identity/ReID, Media Backbone, and pose/biomechanics. S3 weights
  remained SHA256
  `3dc07f69cbe3824490f73c14a59ed328ff35fc2da48da2fd4e324acf9bcc4e9a`;
  S3 floor inference used confidence .001, NMS .45, `imgsz=640`, cap 200.
  The separate segmentation model did not replace S3 or alter FSR ranking.
  No `diver_id` or HUMAN geometry entered reattachment inference.
- B2 source retrieval was read only and byte-checked against source SHA256.
  Verified source clips, 360p proxies, PTS registry, GT-free detector cache,
  diagnostic frames, and mask/result JSON remain host-only. Protected
  authorities and B2 objects were untouched; canonical's pre-existing
  unrelated dirty files were preserved.
- FAX3B/164, FAX2/205, and FAX5/590 were consumed development clips for
  signal measurement and candidate design. Their reattachment observations
  are not counted as fresh validation. FAX4 had no mixed selected edge;
  FAX5's mixed edge defeated V4. FAX6 is the first fresh gate for the
  frozen instance-mask candidate.

## Fresh blind HUMAN authority

Eight metadata candidates from unused sessions were screened at raw-source
times 2/4/6/8 s for nearby people or multiple board users, before model
inspection. The four selected dives were 649/s45, 745/s48, 772/s49, and
850/s52. Raw-screened nonselected dives were 703/s46, 711/s47, 795/s50,
and 823/s51. The queue had no reserve and no outcome-dependent replacement.
All four selected sessions remain in the funnel denominator. The HUMAN UI
showed only raw study-local frames, with takeoff/contact/apex and independent
apex repeat, nine flight boxes, fixed 0.5 s preparation boxes, immediate
post-entry boxes, and one blind preparation repeat per dive.

Maxime completed all labels with no exclusions. Apex-repeat disagreements
were 0.0167/0.0167/0.0167/0.0000 s. Sealed authority
`FULL_ACTION_GT_HUMAN_FAX6_FRESH` has 109 individual event/box files plus
manifest; digest
`a719d25f1e32a22aaededa178925916a6b718284f484a4b24c6d8b411e9a7a45`;
manifest SHA256
`e77bfab011f115fb137b1db0de333e60e1cd58bccbf05219a1f3280aa4f5f92a`.
Queue manifest SHA256
`5813d48740f91039f04ef6ebd438361f8df3431e616eeefd4fe8e888ebeab3d5`;
host-only proxy registry SHA256
`095816a83c519dccabac1f3d1cf054f379f90448b07f1dce4a032c70b0c96983`.
The predeclared emulated user click used HUMAN only to identify the correct
FSR candidate for evaluation: at least two target flight-anchor center
hits, at least .75 visible-anchor coverage, and at least .75 purity within
normalized radius .06. HUMAN was not input to S3, FSR, or bridge inference.

Three of four dives qualified for selected-flight-conditioned association.
649's best target-matching surfaced path hit only 5/9 HUMAN flight anchors,
below the fixed selection threshold. It remains in the funnel denominator
and is attributed to upstream flight surfacing, not reattachment.

## Representation and frozen candidate

The FSR-selected S3 boxes are immutable provenance. A mixed first-flight
box is not an identity anchor. Separate high-resolution person segmentation
provides individual masks in the selected source core. Candidate masks are
ranked by source-box overlap times instance confidence; a later run of
three consecutive masks must meet fixed source-support and competitor-margin
thresholds to become a trusted person-specific subcore. A bounded local
search links masks backward and forward by short-time geometry, size, box
overlap, and source support. Unsupported or competing links stop. Three
sustained person-specific observations are required after the mixed edge
before any assertion. The output contains a compressed individual mask,
indexing box, trusted-subcore status, unresolved interval, and stop reasons.
This is a local selected-flight bridge, with no cross-clip appearance bank
or global ReID.

The method's important unproven step is ranking seed paths by supported
length and score. A continuously tracked wrong person could outrank the
target. The near-length conflict check is a useful abstention gate, not a
proof of identity. The prototype only searches within selected-flight
source frames; it does not establish which earlier preparation branch
reconnects to the trusted subcore. `NO_MIXED_EDGE` is a delegation signal:
the clean-control comparison uses frozen V3 on 772; the prototype itself
does not emit a clean-track trajectory and is not wired into product overlay.

## Fresh measured results

| Dive | Selected flight | V3 mixed edge | Candidate outcome | Correct asserted HUMAN flight masks / visible | Prep asserted | Post correct | First wrong-person time |
|---|---|---|---|---:|---:|---:|---|
| 649/s45 | No: best target path 5/9 | — | Upstream surfacing exclusion from conditional gate | — | — | — | Not applicable |
| 745/s48 | Yes, Q .772/rank 4 | f256, 4.267 s | Reattached at f280, 4.667 s; 0.400 s NULL | 3/3 asserted, 3/9 visible covered | 0/8 | 1/1 | None observed |
| 772/s49 | Yes, Q .819/rank 2 | No | Clean V3 delegation | 8/8 asserted, 8/9 visible covered | 11/12 | 1/1 | None observed |
| 850/s52 | Yes, Q .784/rank 1 | f345, 5.756 s | Reattached at f351, 5.856 s; 0.100 s NULL | 5/5 asserted, 5/9 visible covered | 0/11 | 1/1 | None observed |

745's trusted subcore is f284–286, its asserted path f280–318 (39
consecutive frames); unsupported f279/f319 bound it. 850's trusted subcore
is f356–358, its asserted path f351–399 (49 consecutive frames), stopping
before unsupported f400. Both mixed-edge source boxes remain NULL. Raw
overlays at all HUMAN flight anchors and dense four-frame path contact
sheets show the selected airborne diver in the asserted masks, separate
from board bystanders. At 850 f371 the mask is on the selected diver
although its indexing-box center lies outside the .06 HUMAN center radius.
It is a center miss, not a wrong-person continuation. No first wrong-link
time was observed. Internal asserted paths have no frame gap or adjacent
center jump above .06; maximum steps were .028 (745) and .051 (850).

On the two mixed selected flights, the candidate's physical-person outcomes
are **2/2 correct reattachment, 2/2 honest NULL before reconnection, 0/2
observed wrong-person continuation**. It covers 8/18 visible mixed-flight
anchors with correct masks and both immediate post anchors. V3/V4 cover
0/18 of those mixed-flight anchors and 0/2 post. With clean 772 handled by
V3, conditional sampled flight preservation is 16/27, post 3/3, and
prep 11/31. Full-action sampled physical-person coverage is approximately
30/61 anchors (11 prep + 16 flight + 3 post), with the other 31 abstained;
this is a composed evaluation result, not a product-integrated output.
Both mixed clips have 0/19 prep assertions. Their longest unresolved prep
interval is effectively the visible preparation span; only the explicit
edge-to-first-reassertion gap is timed at 0.400/0.100 s.

For comparison, frozen V1/V2 have prep center hits 28/31, flight center
hits 25/27, post 3/3. Visual review of 745 f180 prep and f238 flight
shows partial/downshifted target boxes, not another person. No
physical-person switch was observed for V1/V2 on the FAX6 sampled
authority. V3/V4 avoid a hypothetical switch but lose 19 correct/usable
mixed prep anchors and all mixed flight coverage. Therefore FAX6 provides
evidence that masks recover person-specific flight after the mixture; it
does not show a fresh silent-switch reduction versus V1/V2 or safe general
full-action coverage. The FAX2/205 wrong-person baseline remains consumed
development evidence, not a FAX6 validation result.

## Failure attribution and scientific limits

- **True local association/representation failure:** V3/V4 suppress the
  two mixed selected flights completely. The mask bridge resolves later
  person-specific flight but cannot certify a preparation-to-subcore link.
  On clean 772, the missing frame-0 prep assertion has an S3 target
  candidate and is a separate association edge.
- **Perception bound:** 850 f270 has no S3 candidate near the visible
  HUMAN target. Legacy 164/1363 preparation absences are separate S3
  candidate-recall problems; no bridge can assert an observed box there.
- **Flight-surfacing bound:** 649 here, and legacy 1751/373, lack a
  qualifying correctly surfaced selected flight. They do not score
  selected-flight extension.
- **Identity safety limit:** FAX6 has only two mixed selected opportunities,
  and neither ungated baseline switched physical people. HUMAN anchors and
  dense contact sheets support the observed 0 wrong links but do not prove
  zero switches at every source frame or generalize to a 205-like crossing.
  The longest-path heuristic can still choose a wrong continuous branch.
- **Metric limit:** normalized box-center hits are diagnostic, not identity
  truth. Mixed group boxes and partial target masks require raw-person
  adjudication. The 745 and 850 apparent center misses illustrate this.

## Supervisor decision and next gate

Accept the **scientific finding** that an individual-mask representation can
recover a selected physical diver after an explicitly unresolved mixed
flight edge. Keep the algorithm development-only. Do not promote FAX V3,
the mask bridge, general full-action box overlays, Event Logic, or pose.
The remaining calibrated blocker is two-sided continuity from an earlier
trusted preparation branch to the later person-specific subcore, with
multiple local hypotheses and NULL where merge/split evidence is
indistinguishable. A successor must prove that its path choice reduces
silent wrong-person continuations on fresh, session-disjoint close-person
authority while preserving enough preparation and flight coverage. It
must be frozen before the next blind HUMAN gate. Appearance, higher
resolution, or separation should be retained only if measured against
competing people; the 205 color probe failed across 164 pose/lighting
changes. No global identity/ReID or `diver_id` is needed.

## Exact artifact identities

| Artifact | Identity |
|---|---|
| Canonical HEAD before this detailed note | `fcf15c1c06fb13b3739f4f165d314a2a11f5a1c9` |
| Blind queue | `docs/science/FAX6_QUEUE_MANIFEST.json`, SHA256 `5813d48740f91039f04ef6ebd438361f8df3431e616eeefd4fe8e888ebeab3d5` |
| Sealed HUMAN manifest | `docs/science/localization_annotations_v1/FULL_ACTION_GT_HUMAN_FAX6_FRESH/MANIFEST.json`, SHA256 `e77bfab011f115fb137b1db0de333e60e1cd58bccbf05219a1f3280aa4f5f92a`, digest `a719d25f1e32a22aaededa178925916a6b718284f484a4b24c6d8b411e9a7a45` |
| GT-free S3 cache, host only | `runs/full_action_fax_v6/caches/CAND_S3_FAX6_360.json`, SHA256 `767921b22d45459cd4b8cae6e97e1d8a9c61c8949e6867826ccfc5e8d88a6766` |
| S3 weights | SHA256 `3dc07f69cbe3824490f73c14a59ed328ff35fc2da48da2fd4e324acf9bcc4e9a` |
| Instance model | `yolov8n-seg.pt`, SHA256 `a7cd8f929e1903d78a12a48efecab430209f18dc46cb96c3599a5980c63c423c` |
| Frozen bridge source | `experiments/full_action/fax_instance_bridge_v1_dev.py`, SHA256 `46db2213e4e21f206d58746a57ea26adeaeea353bb0e68a4e5369cbf4731944f` |
| Cache builder | `experiments/full_action/fax_v6_s3_cache.py`, SHA256 `058b67420ed74f586815e25887f5d29fb250f1c7986ba9499359c09aeffb9e5b` |
| Control evaluator | `experiments/full_action/fax_v6_fresh_eval.py`, SHA256 `cf09b78ebb52d8d29844a517a09ae7d1bd9eda6463622beb182073e51d5b5f8f` |
| Instance evaluator | `experiments/full_action/fax_v6_instance_eval.py`, SHA256 `2ddc8f9bb9e4302e9eec79b4fd60c84988fa7b43fe17205929ace0ea85fd54bc` |
| Host-only control result | `runs/fax_v6/fax_v6_fresh_results.json`, SHA256 `8c2304517d3ee07f967ba38009c2ca85d89e8e19d168fce2da447fc4daad66e7` |
| Host-only instance summary | `runs/fax_v6/instance_results.json`, SHA256 `e8299adbbf0d4faf9e1fea1d93352a01813e51ed20a085eba6941634160318cc` |
| Host-only asserted mask trajectories | 745 SHA256 `84d6e116f4dd5286523fd71df5d83afa9395ca413ea24c62647b1aa5131f110e`; 850 SHA256 `d61a183d1e3157549fd020e40521d08c5cc817ed55e2b8784a799a170ef84f11` |
| Concise FAX6 gate | `docs/science/DIVE_ANALYZER_FAX_V6_INSTANCE_FRESH_GATE.md`, SHA256 `936300c8bf428529086ba5a530cdfbc6bd074345e8b810f5cb958e000fe2b69e` |

**Remaining blocker:** calibrated preparation-to-trusted-subcore association
through mixed intervals, with explicit competing paths/NULL and fresh proof
against silent wrong-person continuation.

`SUPERVISOR_REVIEW_AFTER_MIXED_INTERVAL_REATTACHMENT`
