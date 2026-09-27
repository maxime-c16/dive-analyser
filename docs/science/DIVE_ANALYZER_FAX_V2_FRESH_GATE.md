# Selected-flight full-action association: FAX V2 fresh gate

**Verdict: FAIL.** The FAT3-informed conservative V2 candidate eliminated the two recorded FAT3 wrong prep overlaps, but did not improve FAT3 coverage (29/70 visible prep anchors). On new FAX2 HUMAN authority it was identical to V1: 7/54 correct prep anchors, 26 wrong-person prep overlaps. It cannot drive a full-action box overlay. Event Logic was not evaluated or changed because trajectory identity failed.

## Authority and selection

`FULL_ACTION_GT_HUMAN_FAX2_FRESH` is a sealed, blind, session-disjoint DEVELOPMENT authority: 205/s28, 1751/s112, 1621/s100, 1363/s84. Reserve 1440/s88 was not needed. Queue selection used DB metadata followed by raw contact sheets, never model outcome. Prior-science, FAT3, FAT2, FGT3H, INTERNAL_EVAL, FINAL_HOLDOUT, Paris, 524, and 2555 sessions were excluded. Eight metadata-shortlisted source objects were SHA-verified read-only against `media_blobs`; the raw screen retained four with visible prep and crowd interaction. All four dives were HUMAN-labeled with no exclusion. The authority manifest hashes 147 files (146 individual HUMAN records and `FAX2_EVENTS.json`), digest `6a4914c93176cb683e383462ca9a0b41d388f0c603d7d26f860997d47425fd16`; apex repeat disagreement was 0, 0.0333, 0, and 0.0167 s. The queue and V2 development code were committed at `7bfbaaf` before HUMAN geometry was inspected. The annotator saw only raw frames.

Emulated user selection is the first Q-ordered FSR candidate with at least two HUMAN flight-anchor hits, flight coverage >=0.75, and overlap purity >=0.75 at 0.06 normalized center distance. This conditions evaluation on a correct selected flight and keeps other DiveTracks intact. Three of four dives qualify. 1751 has no qualifying selected flight, so it is an independent upstream flight-surfacing failure, not an association score.

## Fresh readout (V1 and V2 identical)

| Dive | Selected flight | Correct prep / visible | Wrong prep overlaps | Flight correct / visible | Back stop | Longest observation gap | Adjacent center jumps >0.06 |
|---|---:|---:|---:|---:|---|---:|---:|
| 205 | yes | 0/35 | **26** | 8/9 | GAP_TOO_LONG | 0.267 s | 29 |
| 1363 | yes | 0/12 | 0 | 9/9 | GAP_TOO_LONG | 0.067 s | 0 |
| 1621 | yes | 7/7 | 0 | 9/9 | CLIP_START | 0.267 s | 2 |
| 1751 | no | not scored (19 visible prep anchors) | — | no qualifying flight | — | — | — |

Selected dives: pooled prep correct coverage 7/54 = **0.130**, wrong-person overlap **26**, flight-anchor correct 26/27, post-entry correct 1/2 visible anchors. Overall correct full-action sampled-anchor coverage is 34/83 = **0.410** (prep + flight + post); 26 prep and one flight anchor are wrong. All track ends have labeled reasons, but a labeled eventual GAP does not excuse earlier identity contamination. HUMAN marked two 1363 items ambiguous; they are excluded from scoring, and the track has no boxes at its visible early prep anchors. V2's explicit uncertain-core-prefix and scale-stop guards fired on FAT3 2519 and 16 respectively, but on no selected FAX2 track. Thus fresh FAX2 is a direct falsification of these guards as a general solution.

## Failure attribution

In 205, the selected flight begins with an S3 box spanning two people on the board. The backward chain attaches to the right-hand person at x≈0.38 while HUMAN boxes for the dive-producing diver are at x≈0.15–0.19. At frame 1050, raw-frame review shows two separate people: model box red encloses the right-hand person and HUMAN green encloses the diver. At frame 1102, the red selected-flight box encloses both people. The wrong continuation persists over 26 sampled prep frames rather than ending at the eventual GAP. The frozen S3 floor has candidates within 0.06 of the HUMAN prep center on 20/35 visible 205 anchors, so association and merged/group box representation both contribute; local residual and the V2 scale/low-support checks cannot choose the person inside a group box. This is not global identity recognition. It is a local one-to-many split at the selected flight boundary.

At 1363 the backward track stops honestly soon after flight, and S3-floor candidate presence is only 2/12 visible prep anchors. At 1621 the same-person track reaches clip start with 7/7 correct prep anchors. At 1751 prep candidate presence is 17/19 visible anchors, but no flight meets the selection rule. These distinct modes must not be pooled into an association-only explanation.

## Decision

V2 remains a DEVELOPMENT candidate and is not frozen for product use. FAX V1 and all other frozen baselines remain untouched. Full-action box overlays are unsafe in crowded clips; only short trustworthy flight segments or explicit uncertainty can be shown. Pose/geometry cannot resume. V3-C0 and V4-B0 remain frozen; the prep-rise-lock hypothesis is deferred because the trajectory gate did not pass.

The next association hypothesis must represent the selected flight's mixed-person edge as competing person-specific paths and abstain where the detector provides only a merged group box. It also needs a distinct perception treatment for 1363 and a flight-surfacing treatment for 1751. FAX2 is consumed DEVELOPMENT evidence; any revised association must use another newly selected session-disjoint blind HUMAN authority before a generalization claim.

Host-only reproducibility artifacts: `runs/fax_v2_media/PROXY_REGISTRY_FAX_V2.json`, `runs/fax_v2_annotation/QUEUE_MANIFEST.json`, `runs/full_action_fax_v2/caches/CAND_S3_FAX2_360.json` (SHA256 `db10411ef680e56663a248126647104379e25721061bac139188576a5a3edd45`), `runs/fax_v2/fax_v2_fresh_results.json`, and raw diagnostic frames `runs/fax_v2/diag205_*.png`. Frozen S3 weights SHA256 `3dc07f69cbe3824490f73c14a59ed328ff35fc2da48da2fd4e324acf9bcc4e9a`.
