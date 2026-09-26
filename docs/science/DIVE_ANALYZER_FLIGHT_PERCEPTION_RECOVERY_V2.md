# Dive Analyzer flight perception recovery V2

**Decision:** `S3_S2init_DS2_OOD` passes the frozen manual multi-track selection gate on a newly annotated, session-disjoint development holdout. Promote it for further science and a bounded candidate-selection product path, while keeping D5 and S2 immutable. This is not a production-wide accuracy claim: 14 dives give limited precision, and one of two replay/screen dives still fails.

## Authority and method

The split was frozen at commit `4d111da57514cce7dae5ec7e8751b96751b0076c` before V2 detector/fusion design. `FLIGHT_GT_HUMAN_V3_HOLDOUT` contains 14 dives from 13 sessions disjoint from training and design data, with 126 main flight positions, six blind repeats, and no human-excluded dives. Its direct HUMAN manifest digest is `83326b04cdd745d3e003abb13c78262f00b207ffe7419677c5e2735b65ff2048`. Four main positions were marked ambiguous and omitted from box-based measures; one of six repeats disagreed on visibility. This limitation is retained, not silently relabeled. Twelve dives had strictly aligned HQ source footage; dives 31 and 1003 were evaluated at proxy resolution only. Source B2 revisions, proxy SHA-256 identities, dimensions, and alignment checks are in `FLIGHT_PERCEPTION_RECOVERY_MEDIA_V2.json`.

`FLIGHT_GT_HUMAN_V2_HOLDOUT` was consumed by the prior cycle. The V2 protocol explicitly changed its role to development diagnostic and targeted training evidence before S3 was trained. S3 was a single 20-epoch fine tune of a **copy** of S2 on DS1 plus 45 HUMAN-box images from four consumed V2 OOD failures. It passed a prespecified admission check on the separate, older FGT1 validation and was frozen as the sole primary V3 strategy at commit `3317d9f2e4f8f2f1d2dfc61eefadea72af339065`, before V3 GT was loaded. The protocol SHA is `d15c21382125688ea0d7cc0bcd8c4d4b4531c9e387b632d983a52612e92bfbb8`. The frozen FSR search, pool, ranker, recovery criterion and top-K list were unchanged.

## Fresh held-out result

Primary top-K uses the combined 360p plus strictly verified HQ candidate list when HQ exists, otherwise 360p. Every dive remains in the denominator. The manual-selection gate is top-5 at least 60% and top-10 at least 70%: with 14 dives that requires at least 9 and 10 successes respectively.

| Immutable comparator / candidate | Primary top-1 | Primary top-5 | Primary top-10 | 360p raw presence | HQ raw presence (12 dives) | 360p median best IoU | HQ median best IoU |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| D5 | 1/14 | 3/14 | 4/14 | 0.861 | 0.972 | 0.593 | 0.600 |
| S2_COCOinit_DS1 | 10/14 | 11/14 | 11/14 | 0.852 | 0.907 | 0.670 | 0.707 |
| S3_S2init_DS2_OOD | **11/14** | **12/14** | **12/14** | 0.844 | 0.944 | 0.660 | 0.707 |

At 360p, the median subject confidence / margin over the strongest other detection was D5 `0.060/-0.185`, S2 `0.607/+0.360`, S3 `0.700/+0.599`. At HQ it was D5 `0.121/-0.148`, S2 `0.759/+0.740`, S3 `0.764/+0.708`. Thus S3 retains strong subject separation while its **raw presence remains slightly below S2 and D5**; it did not literally recover all of D5's low-confidence tail.

At 360p and confidence 0.05, interpolated flight-window presence / mean number of runs were D5 `0.459/4.36`, S2 `0.661/3.93`, S3 `0.718/2.86`. At HQ they were `0.611/4.83`, `0.793/3.67`, `0.832/2.42`. S3's higher-confidence observations are more continuous despite similar unthresholded raw presence.

The primary either-resolution funnel (14 dives) is:

| Stage | D5 | S2 | S3 |
| --- | ---: | ---: | ---: |
| Raw presence >= 75% of visible anchors | 14 | 12 | 13 |
| Graph oracle recoverable | 14 | 12 | 13 |
| Search pool recoverable | 6 | 11 | 13 |
| Extracted candidate recoverable | 5 | 11 | 12 |
| Surfaced top-5 | 3 | 11 | 12 |
| Surfaced top-10 | 4 | 11 | 12 |

The graph oracle is an evaluation diagnostic, not an input to FSR. D5's high raw coverage does not become a bounded candidate list: its weak subject confidence strands most subjects at pool construction. S3 improves the actual surfaced list by one dive over S2. The gain is modest, but it clears both frozen gates without search tuning.

## Resolution and OOD

| Stratum | D5 top-5 | S2 top-5 | S3 top-5 |
| --- | ---: | ---: | ---: |
| 360p only, all 14 | 3/14 | 10/14 | 8/14 |
| HQ only, 12 aligned dives | 4/12 | 10/12 | 11/12 |
| Primary 360p+HQ, 12 aligned dives | 3/12 | 10/12 | 11/12 |
| Primary proxy-only, 2 dives | 0/2 | 1/2 | 1/2 |
| Replay/screen, 2 dives | 0/2 | 0/2 | 1/2 |
| Native camera, 12 dives | 3/12 | 11/12 | 11/12 |
| 1 m, 8 dives | 0/8 | 7/8 | 8/8 |
| 3 m or higher, 6 dives | 3/6 | 4/6 | 4/6 |
| Median HUMAN box height < 0.10 of frame, 1 dive | 1/1 | 1/1 | 1/1 |

The small-subject stratum has only one dive and cannot establish far-camera generalization. HQ materially contributes to S3: 8/14 at 360p alone versus 12/14 primary. Replay dive 992 is the sole S3-only top-5 recovery relative to S2. Replay dive 1003 has five visible HUMAN anchors and no verified HQ: S3 observes all five and the graph/search pool can represent it, but the extracted candidate misses the required flight coverage. Dive 377 is a different failure: S3 sees 3/9 anchors at 360p and 6/9 at HQ; neither graph nor pool reaches the recovery threshold. D5 supplies more faint proposals there (6/9 and 8/9), yet no surfaced subject trajectory. These are the actual remaining OOD barriers, including the unverified HQ alignment for 1003.

## Complementarity and disposition

The consumed V2 diagnostic proved proposal complementarity: S2's 360p raw presence 0.667 rose to 0.963 with a per-frame D5 union, but top-5 fell from 5/9 to 4/9. A prespecified clip-representation confidence route retained 0.852 raw presence and raised top-5 to 6/9. Neither fusion was selected on fresh V3. On V3, D5 adds faint observations, including on failed dive 377, but its trajectories do not surface. S3 instead improves confidence and continuity; it is the accepted primary. There is **no fresh held-out evidence that a D5 union would improve final top-K**, and V3 must not be reused to choose one.

The research gate supports a several-candidate manual selection path, with a system default when confident and another valid DiveTrack selectable by the user. This is technical viability for a bounded candidate list, not proof of product-wide robustness or unique-person identification. Promote S3 for further science and preserve D5/S2 as immutable comparators. The next independent science question is replay/proxy-only and difficult distant flight coverage, with fresh authority for any further detector/fusion selection. FSR remains the measuring instrument; the pool-to-extraction loss on 1003 is reported rather than tuned away in this cycle.

## Reproducible artifacts

The complete per-dive proposal and funnel records and aggregate table are committed under `flight_perception_recovery_v2_eval/`. `FLIGHT_PERCEPTION_RECOVERY_ARTIFACTS_V2.json` pins each detector cache and checkpoint outside Git. The S3 checkpoint is `last.pt`, SHA-256 `3dc07f69cbe3824490f73c14a59ed328ff35fc2da48da2fd4e324acf9bcc4e9a`; DS2 digest is `1c6f107d968ec45c9b08c8ad984aa00437e46f8d135861c0197ab035a27d42e6`. D5 and S2 checkpoint hashes remain `82b420c4583f8271b1eb3429b14dadf0a1e27477249de7b6a0b9d42a788dcf25` and `d3ba0b035e7a8eb20bb5af66db62984bfb4682075b0c1267677d293e0e9d9c7f`.
