# Dive Analyzer selected-flight association — detailed supervisor output

Date: 2026-09-27. Product path under test: `S3/FSR flight candidates → user selects the correct flight → same-person full-action track → landmarks → overlay → pose`. This cycle tested the association step. Gate token: `SUPERVISOR_REVIEW_AFTER_SELECTED_FLIGHT_CONDITIONED_ASSOCIATION`.

## Executive conclusion

**Fresh trajectory gate: FAIL.** FAX V2 was a conservative, versioned development successor to frozen FAX V1. It removed the four scored FAT3 wrong prep overlaps (two on 16, two on 2519) by stopping earlier, while retaining the 29 clean prep hits. That was useful consumed-development evidence, but on four new blind HUMAN dives V2 and V1 produced identical tracks. Among the three dives with a qualifying selected flight, prep recovery was 7/54 correct anchors, 26 wrong-person overlaps, and 21 absent anchors. The worst case (205) silently followed another person for 26 sampled prep frames. Full-action overlays and pose remain blocked; V3-C0/V4-B0 were left frozen.

The decisive new observation is that the selected flight can have a **mixed-person box at its edge**. On 205, the FSR-selected path has a large S3 box containing the target diver and the adjacent person at frame 1102 (t=18.367 s). The backward chain exits that box onto the adjacent person. A track algorithm that treats each S3 box as one physical body cannot infer which person inside the mixed box produced the later flight by residual/IoU alone. This is local continuity and box representation, not a call for global ReID.

## Repository and scientific firewall

- Canonical repo: `mcauchy@192.168.1.57:~/dive-analyser`, branch `uiux-overhaul-pro-app`. The prior FAT3 handoff was `931f973`; the queue and V2 candidate were committed locally as `7bfbaaf` and merged canonically as `0dd74a0` before HUMAN geometry was inspected. The sealed authority and gate report were committed as `1662397` and merged canonically as `695af0e5016bd451d399d63cad3d5f52f8d37def`.
- Frozen inputs untouched: S3 weights SHA256 `3dc07f69cbe3824490f73c14a59ed328ff35fc2da48da2fd4e324acf9bcc4e9a`; S3 inference floor `conf=.001`, NMS `.45`, `imgsz=640`, cap 200; FSR search/rank; FAX V1; V3-C0; V4-B0. No `diver_id` entered inference. Each selected flight was evaluated independently; other candidate DiveTracks remain in the FSR pool.
- Production media and B2 were read only. Eight edited B2 sources were fetched with GetObject and byte-checked against `media_blobs.sha256`. Study-local 360p proxies, PTS registry, S3 cache, draft labels, and diagnostic frames remain host-only. The HUMAN annotation UI exposed raw frames only and was closed after authority freeze.
- Protected INTERNAL_EVAL, FINAL_HOLDOUT, Paris, 524, and 2555 were not DEVELOPMENT evidence. FAT3 was used only for V2 design, not for this fresh gate.

## Fresh authority construction

DB metadata filter: edited rendition, non-lineup/non-sync, 1m/3m, duration at least 10 s; previous-science and protected sessions excluded. The eight metadata-shortlisted dive IDs had no `dive_id` science JSON authority references. Raw contact sheets, with no detector or track output, were screened for visible preparation and competing people. Main queue: 205/s28, 1751/s112, 1621/s100, 1363/s84. Reserve 1440/s88 was not activated. Raw-screen rejects were 1998 (foreground subject then long empty scene), 2115 and 2231 (tiny distant figures).

The user completed every queued item, including four blind prep-box repeats and four apex repeats, with no exclusions. HUMAN instructions distinguish visible target, partial target behind an occluder, not visible, and identity ambiguous; the target is the person performing the marked dive. In 1363 two labels were identity ambiguous and excluded from visible-anchor scoring. Apex repeat disagreements were 0.000/0.0333/0.000/0.0167 s for 205/1751/1621/1363. Sealed authority `FULL_ACTION_GT_HUMAN_FAX2_FRESH`: 146 individual HUMAN records + `FAX2_EVENTS.json`, all hashed in `MANIFEST.json`, digest `6a4914c93176cb683e383462ca9a0b41d388f0c603d7d26f860997d47425fd16`.

The emulated user click followed the predeclared rule: first Q-ordered FSR candidate with at least two correct HUMAN flight-anchor hits, flight coverage at least 0.75, and overlap purity at least 0.75 at normalized center radius 0.06. This uses HUMAN only to emulate the correct click for evaluation; HUMAN is never input to extension inference. Three of four dives qualified. On 1751 (HUMAN takeoff/contact 9.167/10.400 s), top FSR candidates centered near 10.2–11.23 s had 0 correct flight-anchor hits; this is an upstream flight-surfacing failure. It has 17/19 S3-floor prep candidates near visible HUMAN centers, but cannot be used to grade selected-flight extension.

## Algorithm tested

Frozen FAX V1 greedily extends both ways from the selected flight core across the full S3 floor, taking the lowest motion residual among overlap/size/speed-gated boxes; near-residual ties stop as ambiguous. FAT3 showed two ways to be confidently wrong: scale/crowd drift on 16 and static-junk ride on 2519. FAX V2 development added two conservative checks without changing FAX V1: (1) trim a low-confidence early flight-core prefix if it spatially jumps away from a sustained later flight body; (2) retroactively stop a backward chain before a sustained low-confidence box-area explosion. These were motivated and tested on consumed FAT3. On FAT3, 16 changed from two wrong prep overlaps to zero with `LOW_SUPPORT_SCALE_HANDOFF`; 2519 changed from two wrong prep overlaps to zero with a two-frame uncertain core prefix and `AMBIGUOUS_HANDOFF`. Clean FAT3 prep hits 1491/251/2742 stayed 12/11/6. Total correct prep coverage did not rise (29/70).

These checks specifically target low-support anomalies. They do not model a high-support adjacent person or the split of a group box into two bodies. FAX2 was a direct generalization test of that limitation.

## Fresh measured results

V1 and V2 are numerically identical on all three selected FAX2 dives. No selected FAX2 trajectory triggered either V2 safeguard.

| Dive | Selected Q / rank | HUMAN takeoff/apex/contact (s) | Flight correct / visible | Prep correct / visible | Wrong prep | Absent visible prep | Backward stop | Max internal gap | Adjacent center jumps >0.06 |
|---|---|---|---:|---:|---:|---:|---|---:|---:|
| 205 | 0.936 / 5 | 18.600/18.983/19.583 | 8/9 | 0/35 | **26** | 9 | GAP at 4.167 s | 0.267 s | 29 |
| 1363 | 0.593 / 1 | 7.083/7.583/8.483 | 9/9 | 0/12 | 0 | 12 | GAP at 6.833 s | 0.067 s | 0 |
| 1621 | 0.766 / 2 | 3.183/3.650/4.617 | 9/9 | 7/7 | 0 | 0 | CLIP_START | 0.267 s | 2 |
| 1751 | no qualifying flight | 9.167/9.667/10.400 | not scored | not scored (19 visible prep) | — | — | — | — | — |

Selected pooled prep: 7/54 = 0.130 correct coverage, 26 wrong-person overlaps, 21 honest missing anchors. Flight: 26/27 correct, with one wrong flight anchor (205 f1123). Post-entry: 1/2 correct visible anchors (one 1363 anchor absent). Full-action sampled-anchor correct coverage: 34/83 = 0.410. All track ends have reasons, but the 205 GAP appears after a long wrong-person path. `max_gap_s` describes gaps *inside emitted observations*; it does not include missing preparation before the first emitted box and is therefore not a full abstention-duration measure. Adjacent-step stability further flags 205 (29 center jumps above 0.06, maximum center step 0.089 normalized; maximum absolute log-area step 0.787). Even if the box path looked visually continuous, its physical identity is wrong.

## Attribution and limits

**205: confident wrong-person continuation.** HUMAN prep centers are around x=0.15–0.19; the emitted backward boxes over f270–f1050 follow x≈0.37–0.38. A raw-frame diagnostic at f1050 clearly shows the green HUMAN target on the left and the red emitted box on the adjacent right-hand person. At f1102 (the first selected core frame) the red S3 box spans both people. Candidate inspection finds only one large floor box at f1102 (cx=.227, cy=.447, bw=.455, bh=.470, conf=.235); at f1050 the high-confidence floor box is centered on the wrong person (cx=.384, cy=.485, conf=.492). The same-person prep candidate is available by center radius at 20/35 sampled 205 anchors, so this is a mixture of missing person-specific boxes near the merge and association loss where alternatives exist. The center-radius flight score can accept a large mixed box whose center lies near the diver: 205's 8/9 flight score does not certify that all selected core boxes isolate one person.

**1363: mostly floor-recall bound and honest stop.** S3 has a candidate within 0.06 of only 2/12 visible prep anchors. The track stops at 6.833 s, just before selected flight starts at 7.150 s, with no wrong prep boxes. There is no evidence that a stronger association algorithm alone can recover the early prep from this floor.

**1621: clean continuation control.** All 7 visible prep anchors and all 9 flight anchors match; backward reaches clip start. This confirms the pipeline remains functional where the observation and identity problem is simple.

**1751: flight-surfacing failure outside the conditional association gate.** Top FSR candidates have 0/9 correct flight-anchor hits even though 17/19 visible prep anchors have nearby S3 floor candidates. Do not treat this as evidence against or for V2 extension.

Limitations: four new dives, three selected; 205 dominates wrong-link count. HUMAN center-radius scoring is a useful screen but cannot validate whether a large box contains only the target. Only selected-anchor sampled points were scored, not framewise identity truth across every frame. The raw-frame 205 adjudication establishes a true person switch at sampled frames; it does not quantify the exact first switching frame. FAX2 is consumed DEVELOPMENT evidence for the next method and cannot serve as its fresh validation.

## My proposed fix and decision sequence

1. **Represent flight-edge uncertainty explicitly.** A selected FSR flight is a user choice of a physical diver, but its first detector boxes may be group boxes. Store the selected flight and its immutable candidate provenance; also derive a *trusted person-specific subcore* from the later unambiguous flight, while marking mixed/oversized edge boxes `UNCERTAIN` rather than treating their centers as identity anchors. Do not replace or delete other DiveTracks. A detector box spanning two people must never assert a single-person overlay.
2. **Generate competing backward person paths, including NULL.** From the trusted flight body, keep several spatially distinct candidate paths through the group/split interval. Score a short temporal window jointly, rather than accepting the first small residual. Required evidence should include bidirectional motion consistency, box shape/scale, board/lane position, and whether the candidate path reconnects to the selected flight body. Emit a box only where one path has defensible support; otherwise emit an uncertainty interval and bounded alternatives. This is local conditioned tracking, not global identity recognition.
3. **Test appearance before adding it.** Crops around the selected diver and competing people at f1050–f1123 provide a direct experiment. Compare simple color/texture embeddings and temporal consistency through occlusion on consumed 205/16/2519 plus clean controls. Account for pose, lighting, and merged crops. Require a measured separation advantage over geometry and a calibrated abstention rule. Do not assume OSNet helps; prior OSNet flight-search AUC was poor and this is a different local task.
4. **Address candidate granularity at hard frames.** For mixed boxes, test targeted higher-resolution crop inference or person-instance segmentation around the board only if it yields two independent person boxes at the merge/split frame. If it does not, the correct output is abstention across that interval. Frozen S3 and FSR remain baselines; any perception successor must be separately versioned. Do not infer a person's location by interpolating through an unresolved multi-person overlap.
5. **Evaluate three outcomes separately.** The next gate must report correct continuation, honest abstention, and wrong-person continuation at sampled anchors and at explicitly reviewed transitions, with wrong-person continuation dominant. Add box-instance purity review for group boxes, first-wrong-link time, abstained interval duration, longest missing interval, flight preservation, and visual trajectory stability. Pre-register on consumed FAT3/FAX2 development, then select another session-disjoint blind HUMAN authority without screening by model outcome.

Priority is to remove 205-class silent switches. A conservative path that abstains during a merged-person crossing is preferable to 205's 26 wrong prep boxes even if coverage remains low. Once that safety gate passes fresh validation, improve prep coverage in available-candidate scenes; separately diagnose 1363 floor recall and 1751 flight surfacing. Only then test V4-B0 prep-rise lock on independently trustworthy full-action tracks. No Event Logic change is justified from this cycle.

## Exact artifact identities at this handoff

- Canonical HEAD before this detailed note: `695af0e5016bd451d399d63cad3d5f52f8d37def`.
- Sealed HUMAN authority: `docs/science/localization_annotations_v1/FULL_ACTION_GT_HUMAN_FAX2_FRESH/MANIFEST.json`, digest `6a4914c93176cb683e383462ca9a0b41d388f0c603d7d26f860997d47425fd16`, manifest SHA256 `9f3ad21586d2192ed37ca3b59f9e8acd85dcdb238c041abb8faa1dcf2c1dbbf4`.
- V2 code `experiments/full_action/fax_extension_v2_dev.py`, SHA256 `7011664b005acdbe44adf9cc286aaf825197fab5fa7b380e8e88455f3c8b3b6c`; fresh evaluator `experiments/full_action/fax_v2_fresh_eval.py`, SHA256 `c669953bbdf5605657e175704a619d3533f0dcd169545393afa3f20e11a711ed`.
- S3 FAX2 cache (host only): `runs/full_action_fax_v2/caches/CAND_S3_FAX2_360.json`, SHA256 `db10411ef680e56663a248126647104379e25721061bac139188576a5a3edd45`; evaluation JSON: `runs/fax_v2/fax_v2_fresh_results.json` (host only). Prior concise gate report: `docs/science/DIVE_ANALYZER_FAX_V2_FRESH_GATE.md`, SHA256 `42c5595fc2ef62e2de6a501b5f14aefeeccaf5962351ca8942992a40464fb0d7`.

**Remaining blocker:** establishing person-specific continuity across selected-flight mixed boxes without silent handoff, while admitting uncertainty when person separation is unobservable.

`SUPERVISOR_REVIEW_AFTER_SELECTED_FLIGHT_CONDITIONED_ASSOCIATION`
