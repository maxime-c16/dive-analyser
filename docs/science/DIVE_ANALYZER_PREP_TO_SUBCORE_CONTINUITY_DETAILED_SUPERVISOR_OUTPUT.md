# Dive Analyzer preparation-to-trusted-subcore continuity — detailed supervisor output

**Cycle date:** 2026-09-28
**Canonical branch:** `uiux-overhaul-pro-app`
**Canonical base before this cycle:** `fcf15c1c06fb13b3739f4f165d314a2a11f5a1c9`
**Canonical HEAD before adding this handoff:** `46fe0f9acaeb452718726f610267335b9345aa3b`; the commit containing this file is reported with its delivered path.
**Gate:** `PREPARATION_TO_TRUSTED_SUBCORE_CONTINUITY` remains **OPEN / NOT SOLVED**. No general full-action overlay pilot, Event Logic validation, or pose/geometry resumption is authorized by these results.

## Supervisor decision

The requested product contract is: after a user selects the diver in flight, a full-action overlay must follow that physical diver or visibly admit uncertainty. This cycle built a local two-endpoint, person-mask path test that can preserve `NULL` through a merge/split. It connected one *consumed development* example (850), abstained on two others (205, 745), and made no observed wrong-person assertion on those three clips. That is a useful representation experiment, not fresh proof of physical identity continuity.

Two new blind HUMAN authorities, FAX7 and FAX8, were frozen and evaluated. They provide clean-flight controls, preparation candidate and coverage measurements, an upstream surfacing breakdown, and a mixed-edge false-positive diagnosis. **Neither contains a true mixed-person selected-flight edge with a trusted later person-specific subcore.** The fresh qualifying denominator for `CORRECT_SAME_PERSON_CONNECTION`, `HONEST_UNRESOLVED`, and `WRONG_PERSON_CONNECTION` is zero. A material reduction in wrong-person connection cannot be estimated. The full-action overlay gate stays closed.

There is a deeper prerequisite error in the development connector: its caller supplies the geometric V1 backward extension as the supposed *trusted preparation branch*. V1 is neither an independent person-specific observation nor proof of the selected diver's earlier identity. Even a unique mask path to that supplied branch certifies consistency of observations only. The next cycle must independently establish the preparation person and retain competing branches before testing the link.

## Scope, preserved authorities, and chronology

This is local selected-flight-conditioned continuity. No global identity or ReID is inferred; no `diver_id` enters inference. S3, FSR, FAX V1/V2/V3, instance-bridge V1 history, D5/S2, V3-C0/V4-B0, Media Backbone, pose, Event Logic, B2, and protected authorities were not mutated. B2 access for new raw clips was read-only. Host-only model caches and raw screens are outside Git; their hashes below identify them.

1. Consumed FAX2 205 and FAX6 745/850 were used for development of `prep_to_subcore_v1_dev.py`; they were never counted as fresh validation. Development method SHA256 `b71b3f3b4aa61d10fcef30809ecf87e750f30e0e3ac0c147b5a4a95d1319e404`; corrected evaluator SHA256 `39681421917a2ff7f0a5f38dbc489f1344915aa14ffd03c87ad007ffa480c734`; result SHA256 `2b4291a370c517c0c0e61f4f02895c4b80d067303fb29fc4cc269292c277bcfc`.
2. FAX7 raw clips were selected from a 24-session metadata shortlist using original 2/4/6/8-second frames, without model outcomes. Queue and evaluator code were committed before annotation. Maxime completed blind events and boxes; 182 HUMAN records plus events were sealed at canonical `2b74eb49113f3a2e9cf6844e6d4c9aa443d3e65e`, before S3 caching.
3. FAX7 found no selected mixed flight edge. The readout and a new FAX8 raw-only queue were integrated at `9e850c1c6f4bc14c38153b467add1e9389225d79`.
4. FAX8 selected six different sessions from unused raw-screened clips, without FAX8 inference. Maxime completed all six blind annotations, no exclusions; the authority was sealed at `bc4a5522dfd5bb3cb5d4596a96dcb1c4a61cf398`. A copied queue-ID constant in the cache script prevented its first run; it was corrected and committed at `ceaac5adb137e602da893de7346249fa85ceb3b1` **before any FAX8 inference**. The science method, clips, and labels were unchanged.
5. FAX8 model caches and frozen evaluations ran after sealing. Post-seal raw review determined that its sole machine-flagged mixed edge was one diver rotating. The FAX7 884 center miss was also visually rechecked and corrected from an initially mistaken wrong-person interpretation. Both corrections are explicit below and in canonical readouts.
6. After FAX8, one metadata-selected representative from each of 12 further unused sessions was SHA-verified and screened at one-second raw intervals. The screen did not establish a true target-person convergence/split, so no further HUMAN queue was frozen and no outcome-based replacement occurred. Host-only shortlist SHA256 `e29755fa5d6e170e09ebecf1d4e58844bf7357e57a4b3d4d57d033bfcda4d9c5`; it is **not** an annotation authority.

## Chosen representation and its limit

The development method starts from a selected-flight person-specific mask subcore after a broad mixed edge. It retains all plausible instance-mask links backward across a bounded interval, using temporal spacing, center motion, scale change, and mask overlap. It compares the path reaching the supplied preparation branch with paths reaching competing earlier instances. A weak, absent, or near-tied path returns `UNRESOLVED`; a supported link returns `CONNECTED_WITH_NULL_INTERVAL`. The proposed display shows preparation before the interval and the trusted selected-flight subcore after it, while **every frame of the ambiguous interval remains `NULL`**. It never interpolates a person box merely to make the path continuous.

That logic is a development candidate. The caller currently provides `fax_extension_v1`'s backward trajectory as `prep_track`. V1 extends a selected flight through geometric box overlap and motion and can stop, drift, or emit a partial box. It cannot independently certify which earlier preparation person is the selected diver. The connector therefore does not yet satisfy the objective's premise of a *trusted person-specific prep branch*. The development connection on 850 should be read as conditional on that premise, not as final physical identity proof.

## Consumed development probe (not a fresh gate)

| Dive | Decision | Declared NULL / coverage | Physical-person observation |
|---|---|---|---|
| FAX2 205 | `UNRESOLVED`: supplied prep branch not reached | Prep 0/35; flight 6/9 center hits; post 0/1 | Prevents assertion of the V1 preparation branch that had 26 wrong-person overlaps; subcore endpoint still needs independent trust review. |
| FAX6 745 | `UNRESOLVED`: competing prep ancestor | Prep 0/8; flight 3/9; post 1/1 | Preserves the competitor instead of forcing the prep link. |
| FAX6 850 | `CONNECTED_WITH_NULL_INTERVAL` | 0.984 s tested NULL; prep 9/11, flight 5/9 person-mask correct, post 1/1 | No observed wrong-person assertion; conditional on the supplied V1 prep branch. |

On the two consumed mixed FAX6 clips, strict display accounting retains 9/19 visible preparation, 8/18 physical-person flight, and 2/2 immediate-post anchors: 19/39 full-action samples. The 850 displayed gap is 0.918 s because the prep branch ends before f297 and the mask suffix starts at f351. No wrong-person assertion was observed, and no first wrong-link time exists in this probe. These are not fresh safety rates.

## Fresh FAX7 authority and results

**Queue:** 47/s15, 884/s53, 952/s58, 1327/s82, 1798/s109, 2120/s129.
**HUMAN:** `FULL_ACTION_GT_HUMAN_FAX7_FRESH`, 182 records plus events, no exclusions; digest `b71b950e3af60d5f736642053ace5cfdd13f65b00328431e6d50f6a316bfc436`; manifest SHA256 `0f0efb0be80103670f48227e7e3967ded6b19ad1c04d75d928fcae307527324c`.
**Selection:** five flights surfaced; 1798 failed upstream FSR surfacing. No selected flight had a machine mixed edge, and no true merge/split connection opportunity was present.

| Surfaced dive | Prep center hits / visible | Flight | Immediate post | Longest missing prep span |
|---|---:|---:|---:|---:|
| 47 | 19/19 | 9/9 | 1/1 | 0 s |
| 884 | 1/16 | 9/9 | 1/1 | 6.5065 s |
| 952 | 13/13 | 9/9 | 1/1 | 0 s |
| 1327 | 0/6 | 9/9 | 1/1 | 2.5025 s |
| 2120 | 4/6 | 9/9 | 1/1 | 0.5005 s |

Pooled V1/V2/V3/V4 results on surfaced clips were identical: 37/60 prep center hits, 22 prep abstentions, one center miss, 45/45 flight hits, and 5/5 post hits: **87/110 full-action sampled center coverage**. Post-seal S3 candidate audit found a target-near floor center on 51/60 prep samples, showing both candidate availability and association/abstention limits. On 1327 only 2/6 prep samples had a target-near candidate; on 884 13/16 did, while the asserted track had only 1/16 center hits, mostly due to abstention.

**Critical correction:** the evaluator labels 884 f210 / 7.007 s `prep_wrong=1` because its asserted center is just outside the normalized 0.06 scoring radius. The actual asserted box covers the HUMAN-labeled *left* diver's lower body and excludes the neighboring *right* diver. The box is shifted/partial on the same person; it is **not** a physical wrong-person connection. My earlier visual claim of a switch was wrong because it was made before reconstructing the asserted box. No physically wrong link was confirmed in FAX7. Maximum adjacent asserted V1 center step was 0.0751 normalized units (47, three steps >0.06); there was also one such step on 2120. Those are overlay-stability measurements, not identity judgments.

The prep-to-subcore evaluator returned `NO_MIXED_EDGE` / `NO_TRUSTED_SELECTED_SUBCORE` for all five selected flights. A clean case is not counted as a failed physical connection; the qualifying outcome denominator is zero.

## Fresh FAX8 authority and results

**Queue:** 907/s54, 1257/s79, 1463/s90, 1849/s107, 2134/s130, 2398/s153.
**HUMAN:** `FULL_ACTION_GT_HUMAN_FAX8_FRESH`, 174 individual records plus events, no exclusions; digest `a31d5bcfd93afa1704191e336dc72a5124255a97f19ad6da8eafea038b974188`; manifest SHA256 `5dee66183401131680eaae38c2ddab5dd8586c2ec47672ab5c5c115e87f41450`.
**Selection:** 907, 1257, 1849, and 2134 surfaced; 1463 and 2398 failed upstream FSR surfacing.

| Surfaced dive | V1 prep / visible | V1 flight | V1 post | V3/V4 flight | Main attribution |
|---|---:|---:|---:|---:|---|
| 907 | 5/13 | 8/9 | 0/0 | 8/9 | Preparation gaps; one absent sampled flight frame. |
| 1257 | 11/11 | 9/9 | 1/1 | 9/9 | Clean control. |
| 1849 | 0/4 | 9/9 | 1/1 | 9/9 | Preparation unavailable; S3 target-near candidate 1/4. |
| 2134 | 1/4 | 9/9 | 1/1 | 0/9 | False mixed-edge flag suppresses a same-person flight. |

V1 pooled selected-track coverage: prep 17/32, flight 35/36, post 3/3, **55/71 full-action sampled centers**. V3/V4: prep 16/32, flight 26/36, post 2/3, **44/71**. A post-seal candidate audit found target-near S3 prep boxes on 21/32 selected samples. In the two unsurfaced clips, target-near prep candidates were 0/16 (1463) and 6/11 (2398); they do not enter selected-track coverage. V1 maximum adjacent center step was 0.0697 (2134, three steps >0.06). Its longest missing prep spans were 3.000 s on 907 and 1.502 s on 1849.

V3 machine logic flags 2134 at f254 / 4.237567 s because an earlier compact body box is laterally offset within a broad flight-edge box. Post-seal raw-frame review around f228–f308 shows **one rotating diver**; no second physical person converges or splits there. The compact detection is a body/pose artifact. V4's motion bridge reports weak/competing support, and the frozen instance bridge returns `UNRESOLVED` with no trusted subcore. This is an honest abstention to a **false mixed-edge premise**, not a qualifying prep-to-subcore trial. It suppresses the 0.901 s selected-flight span despite V1's 9/9 center hits on that same diver. No physically wrong link was confirmed at sampled FAX8 anchors.

## Required outcome and failure attribution

| Required measure | Fresh result | Interpretation |
|---|---|---|
| `CORRECT_SAME_PERSON_CONNECTION` | 0 qualifying trials | Cannot estimate. Consumed 850 is development-only and conditional on V1 prep branch. |
| `HONEST_UNRESOLVED` through a true mixed-person interval | 0 qualifying trials | 2134 abstains to a false flag; do not count it as a true merge/split abstention. |
| `WRONG_PERSON_CONNECTION` through a true interval | 0 qualifying trials | No fresh rate or demonstrated reduction; no physical wrong link confirmed at sampled anchors. |
| Preparation coverage | FAX7 37/60; FAX8 V1 17/32, V3/V4 16/32 | Candidate recall and association/abstention both constrain coverage. |
| Flight preservation | FAX7 45/45; FAX8 V1 35/36, V3/V4 26/36 | FAX8 false mixed-edge flag costs nine sampled flight anchors. |
| Unresolved interval duration | True fresh interval unmeasured | Consumed 850 tests 0.984 s NULL; 2134 false flag suppresses 0.901 s selected flight. |
| First wrong-link time | None physically observed fresh | This is not a safety-rate estimate. |
| Full-action sampled coverage | FAX7 87/110; FAX8 V1 55/71, V3/V4 44/71 | Center-hit coverage is not person-identity certification. |
| Overlay stability | FAX7 max adjacent step 0.0751; FAX8 V1 max 0.0697 | Jumps and long prep gaps require visible NULL handling. |

Separate upstream and perception attribution: FSR did not surface FAX7 1798 or FAX8 1463/2398. S3 target-near preparation candidates were missing on 9/60 selected FAX7 and 11/32 selected FAX8 visible prep samples, by the center-radius audit. A center-near box may still be mixed or partial; those counts are candidate-availability upper bounds. V3's 2134 mixed-edge false positive is a distinct classification failure. None of these is added to an association score. Event Logic and pose were not run.

## Next technical gate

1. Obtain a raw-verified close-person DEVELOPMENT clip where two physical people actually converge or overlap, separate, and one produces a selectable flight. Verify the physical interaction from the original video before HUMAN annotation; select by raw scene, not model outcome. If available footage lacks such an event, acquire new footage rather than fabricating a denominator.
2. Establish a *person-specific preparation branch independently* of V1's backward selected-flight extension. Measure preparation candidate recall first. Maintain multiple nearby people and `NULL`; require evidence that distinguishes the intended prep person from an alternative branch.
3. Condition on a separately trusted selected-flight subcore after the interval. Test two-sided path agreement and competing ancestors; leave the interval `NULL` until the identity link is supported. Distinguish a real two-person merge from a single person's rotating or folded pose before suppressing the selected flight.
4. Freeze method and raw-selected sessions before new blind HUMAN labeling. Score physical correct connection, honest unresolved, and wrong-person connection separately; wrong-person dominates. Report preparation/flight/full-action coverage, NULL duration, first wrong-link time, overlay stability, and separate FSR/perception failures. Do not promote merely because a geometric path exists.

**Supervisor answer to the seven definition-of-done questions:** (1) One consumed conditional connection exists, but fresh physical-person connection is unproven. (2) Yes, the development representation can keep an ambiguous window `NULL`; fresh true-case performance is unmeasured. (3) No material fresh wrong-person reduction has been demonstrated. (4) Clean-flight coverage remains useful, but mixed-edge false positives and preparation gaps lose coverage. (5) General full-action overlays are not ready for a bounded pilot. (6) Event Logic validation cannot resume. (7) Pose/geometry cannot resume after it yet.

## Exact artifact identities

| Artifact | Identity |
|---|---|
| Canonical branch/HEAD before adding this handoff | `uiux-overhaul-pro-app` / `46fe0f9acaeb452718726f610267335b9345aa3b`; the commit containing this file identifies the final HEAD. |
| Prep connector code | `experiments/full_action/prep_to_subcore_v1_dev.py`, SHA256 `b71b3f3b4aa61d10fcef30809ecf87e750f30e0e3ac0c147b5a4a95d1319e404` |
| Consumed development result | `runs/prep_to_subcore_dev/` host-only; result SHA256 `2b4291a370c517c0c0e61f4f02895c4b80d067303fb29fc4cc269292c277bcfc` |
| FAX7 HUMAN | `docs/science/localization_annotations_v1/FULL_ACTION_GT_HUMAN_FAX7_FRESH/MANIFEST.json`, SHA256 `0f0efb0be80103670f48227e7e3967ded6b19ad1c04d75d928fcae307527324c`, digest `b71b950e3af60d5f736642053ace5cfdd13f65b00328431e6d50f6a316bfc436` |
| FAX7 S3 cache | Host-only `fresh_prep_authority/model_caches/CAND_S3_FAX7_360.json`, SHA256 `c80b02668b4e93fecc9d862c973ff883cb78d163cbae125c86d8aacc438afe1c` |
| FAX7 frozen control / connector results | Host-only SHA256 `86d77f1aaffc8d4cc71a7840e89d64a6ffb949fe44f9a9531af34fa47a7a7a75` / `74a6aa5cacc73eb0bb1cfdeaa56de81ca2e40439d333fefb2547c54febf78f45` |
| FAX8 raw-only selection / registry | Host-only SHA256 `c06af274aa266760aa96449e1fb1a245ca762b0777204366f1c4f697b087adb3` / `67ae277be517b3bd73d3cfd81834f086214b349dd5a1a4810b7bbfea3e77321b` |
| FAX8 canonical queue | `docs/science/FAX8_QUEUE_MANIFEST.json`, SHA256 `70324bcb4e9dbab8e2abf7d720c40edcfebf5cfe3fc1ac6c7a5bfe518669b194` |
| FAX8 HUMAN | `docs/science/localization_annotations_v1/FULL_ACTION_GT_HUMAN_FAX8_FRESH/MANIFEST.json`, SHA256 `5dee66183401131680eaae38c2ddab5dd8586c2ec47672ab5c5c115e87f41450`, digest `a31d5bcfd93afa1704191e336dc72a5124255a97f19ad6da8eafea038b974188` |
| FAX8 S3 cache | Host-only `fresh_prep_authority/model_caches/CAND_S3_FAX8_360.json`, SHA256 `a92f4dfde70ecf6763284bc05ad2c5e5121560a64f8d32c42c442a96955be8ca` |
| FAX8 frozen control / connector results | Host-only `fresh_prep_authority/fax_v8_fresh_results.json` SHA256 `31f6efa61f542c3a64017d831babe607b7ae0b69444075abd704c684afc5ee17`; `fresh_prep_authority/prep_to_subcore_fax8_results.json` SHA256 `0e8de0ad6a65aa2fb3bce7f399374f719d1988508c149290de875a552f494d1e` |
| Further raw-only search | Host-only `fresh_prep_authority/FAX9_RAW_SCREEN_SHORTLIST.json`, SHA256 `e29755fa5d6e170e09ebecf1d4e58844bf7357e57a4b3d4d57d033bfcda4d9c5`; no FAX9 authority |

SUPERVISOR_REVIEW_AFTER_PREP_TO_SUBCORE_CONTINUITY
