# PROJECT_STATE.md — Dive Analyser / DiveSensei

> Clean-track pose feasibility (2026-09-28): pose is phase-gated viable only.
> DEVELOPMENT HUMAN-validated same-person DiveTracks (FAX7 digest b71b950e,
> FAX8 digest a31d5bcf; primary 47/s15, 952/s58, 1257/s79, 2120/s129 plus
> supplemental 1849/s107, 2134/s130) tested with bounded yolov8n-pose vs
> yolov8m-pose, HQ raw vs proxy 360p, plus seg spot check. PREP/standing
> reliable (proxy 0.83-1.00 except tiny-1257 0.00; HQ 0.64-1.00); flight
> proxy 0.00-0.33 (except 1849 0.89) vs HQ 0.11-0.78 (except 1849 1.00,
> 2134 0.00); POST ~0. When matched, limbs 95-100% but head 10-86% and
> L/R flips 17-42% in flight, torso CV 0.09-0.33, jitter 0.13-0.38
> torsos/frame, shoulder/hip CV 0.50-0.75. HQ materially improves recall
> and continuity (e.g. dense 1849 25-86pct, 2120 29-65pct) but does not fix
> rotation/inversion/pike geometry. Masks fail concurrently with pose.
> No stable full-action body geometry can be derived; normalization by
> body scale is not yet stable. Next: pose hardening + landmark
> integration before geometry (phase/HQ gating, L/R disambiguation,
> rotation-robust model/diving fine-tune); no overlay promotion, no Event
> Logic tuning. True-merge continuity result at ca5bab9 preserved
> (dev-only prep_to_subcore_v1_dev, no raw-verified true merge/split in
> authorized corpus). Report:
> docs/science/DIVE_ANALYZER_CLEAN_TRACK_POSE_FEASIBILITY.md.
> Gate: SUPERVISOR_REVIEW_AFTER_CLEAN_TRACK_POSE_FEASIBILITY.

> Detailed supervisor handoff for the completed FAX7/FAX8
> prep-to-subcore cycle: `docs/science/DIVE_ANALYZER_PREP_TO_SUBCORE_CONTINUITY_DETAILED_SUPERVISOR_OUTPUT.md`.
> The connection remains unproven on fresh true merge/split data; general
> full-action pilot, Event Logic, and pose stay gated.

> FAX8 fresh authority (2026-09-28): six HUMAN-complete session-disjoint
> dives, digest `a31d5bcf…`; four selected flights, two upstream FSR
> surfacing failures. The sole machine-flagged mixed edge, 2134, is a
> one-person rotation artifact on raw visual review; the instance bridge
> abstains and no trusted selected subcore is available. Thus the fresh
> true merge/split prep-to-subcore denominator is zero again. V1 selected
> coverage is 17/32 prep, 35/36 flight, 3/3 immediate post (55/71 sampled
> full-action); V3/V4 are 16/32, 26/36, 2/3 (44/71). Target-near S3 prep
> candidates appear on 21/32 selected samples. No sampled physical
> wrong-person link is confirmed, but a reduction cannot be estimated.
> General overlay pilot, Event Logic, and pose remain gated. Readout:
> `docs/science/DIVE_ANALYZER_FAX8_PREP_CONTINUITY_FRESH_READOUT.md`.
> A later raw-only screen of 12 additional unused sessions did not establish
> a true target-person convergence/split, so no further HUMAN queue was
> frozen. Core architecture risk: `prep_to_subcore_v1_dev` takes V1's
> geometric backward extension as its prep branch; that is not independent
> physical-person trust. The next gate needs a separately trusted prep
> branch and a raw-verified two-person interaction before annotation.

> FAX7 fresh blind authority sealed (2026-09-28): six session-disjoint dives,
> 182 HUMAN records plus events, digest `b71b950e…`; five selected flights,
> one separate FSR surfacing failure. No selected flight had a qualifying
> mixed edge, so fresh prep-to-subcore connection outcomes have denominator
> zero. Clean controls gave 37/60 correct prep centers, 22 prep abstentions,
> one center miss at 884 f210 / 7.007 s, 45/45 selected flight,
> and 5/5 immediate post. A post-seal S3 candidate audit found a target-near
> prep box on 51/60 samples, including 13/16 on 884 versus only 1/16
> center-localized: association and perception must be measured
> separately. The 884 asserted box covers the HUMAN-labeled left diver's
> lower body; it is a same-person partial-box error, not a physical switch.
> Report: `docs/science/DIVE_ANALYZER_FAX7_PREP_CONTINUITY_FRESH_READOUT.md`.
> General overlay pilot, Event Logic, and pose remain gated.
>
> FAX8 raw-only DEVELOPMENT queue prepared (2026-09-28): 907/s54, 1257/s79,
> 1463/s90, 1849/s107, 2134/s130, 2398/s153, all selected from unused
> original raw contact sheets with distinct sessions before FAX8 inference.
> The sealed result above supersedes this queue-only status. Queue and gate:
> `docs/science/FAX8_QUEUE_MANIFEST.json`,
> `experiments/full_action/FAX_V8_PROTOCOL.md`. No FAX8 result is claimed.

> FAX7 prep-to-subcore fresh blind queue prepared (2026-09-28): six new
> session-disjoint raw-screened DEVELOPMENT dives 47/s15, 884/s53,
> 952/s58, 1327/s82, 1798/s109, 2120/s129. Selection used 2/4/6/8 s
> source frames only, from 24 metadata-shortlisted sessions; no model
> outcomes were inspected. Source SHA, proxy SHA, and blind HUMAN rules:
> `experiments/full_action/FAX_V7_PROTOCOL.md` and
> `docs/science/FAX7_QUEUE_MANIFEST.json`. The later sealed result above
> supersedes this queue-only status.

> Prep-to-trusted-subcore continuity V1 development probe (2026-09-28):
> two-endpoint person-instance path competition on consumed FAX2 205 and FAX6
> 745/850 yields 850 connected with a 0.984 s explicit NULL interval,
> 745 honestly unresolved due to competing prep ancestor, and 205 honestly
> unresolved rather than asserting V1's 26 wrong-person prep overlaps.
> Consumed mixed FAX6 sampled coverage under strict interval NULL is 9/19 prep, 8/18 physically correct
> flight masks, 2/2 immediate post; wrong-person assertions observed 0.
> This consumed probe is not a safety or pilot gate. General full-action
> overlay, Event Logic validation, and pose/geometry remain paused. No
> frozen method or protected authority was changed. Report:
> `docs/science/DIVE_ANALYZER_PREP_TO_SUBCORE_CONTINUITY_DEV_V1.md`.

> FAX6 fresh mixed-interval gate (2026-09-27): blind HUMAN authority sealed
> at `9965c978`, digest `a719d25f…`, four new sessions, two qualifying
> mixed selected flights (745, 850), one clean selected flight (772), one
> upstream unsurfaced (649). Frozen individual-mask bridge recovers both
> mixed selected physical divers after explicit 0.400/0.100 s NULL; 8/8
> asserted HUMAN flight masks correct, zero observed wrong-person links.
> This restores 8/18 mixed-flight anchors versus V3/V4 zero, but mixed
> prep remains 0/19 and V1/V2 had zero observed physical switches here.
> No demonstrated silent-switch reduction, no general full-action overlay
> promotion. Instance bridge remains development-only. Event Logic/pose
> stay frozen. Report:
> `docs/science/DIVE_ANALYZER_FAX_V6_INSTANCE_FRESH_GATE.md`.
> Detailed supervisor handoff:
> `docs/science/DIVE_ANALYZER_FAX_V6_DETAILED_SUPERVISOR_OUTPUT.md`.

> FAX6 blind HUMAN gate prepared before detector inspection (2026-09-27): four new
> session-disjoint raw-screened dives 649/s45, 745/s48, 772/s49, 850/s52.
> It tests a frozen development instance-mask bridge after mixed edges;
> consumed 164/205/590 showed local person-specific reattachment but did not
> establish safety. Source SHA and queue rules:
> `experiments/full_action/FAX_V6_PROTOCOL.md`; blind queue manifest
> `docs/science/FAX6_QUEUE_MANIFEST.json` SHA `5813d487…`; prototype
> `experiments/full_action/fax_instance_bridge_v1_dev.py` SHA `46db2213…`.
> No promotion or general overlay readiness is claimed. FAX5 failure and
> separate perception/surfacing blockers remain authoritative below.

> FAX5 fresh mixed-person gate FAIL (2026-09-27): blind authority digest
> `c178fd72…`, three labelable dives + 627 HUMAN-unlabelable. Only 590 has
> a qualifying selected flight; 321/474 are upstream unsurfaced. 590 has a
> mixed selected edge. V4 abstains honestly but never reattaches (0/9
> asserted flight anchors, 0/14 prep); its width-based suffix first appears
> post-entry and fails motion competition (7 target-candidate vs 12 competing
> moving features). V1/V2 preserve 9/9 flight and 10/14 correct prep; three
> other prep center misses are visually partial/downshifted boxes on the
> same diver, not physical-person switches. Fresh wrong-person continuation
> observed: zero. No demonstrated safety gain, major coverage loss.
> Full-action box overlays remain unsafe; Event Logic/pose remain frozen.
> Report: `docs/science/DIVE_ANALYZER_FAX_V5_FRESH_GATE.md`.

> FAX4 fresh HUMAN gate sealed (2026-09-27, digest `f6bd2af9…`): four queued,
> one HUMAN-unlabelable (410), two qualifying selected flights (2473, 2533),
> one upstream unsurfaced (1667). Neither selected path has a mixed edge.
> V1/V2/V3/V4 are identical: 10/20 correct prep, 10 honest prep NULL,
> zero sampled wrong-person links, 16/18 flight, 2/3 post. This is a clean
> control, not reattachment validation. 2473 is an association abstention
> with S3 target candidates at all 7 missing prep anchors; 2533's 3 missing
> prep anchors lack S3 target candidates. General overlay stays unsafe;
> Event Logic and pose stay frozen. Report:
> `docs/science/DIVE_ANALYZER_FAX_V4_FRESH_GATE.md`.
>
> The FAX5 queue (590/s42, 321/s32, 474/s37, 627/s44) was prepared from
> six source-screened clips before detector inspection. Queue identities:
> `docs/science/FAX5_QUEUE_MANIFEST.json` and
> `experiments/full_action/FAX_V5_PROTOCOL.md`.

> FAX4 queue provenance (2026-09-27): the raw-only,
> session-disjoint HUMAN queue 2473/s140, 2533/s148, 410/s35, 1667/s102
> was frozen before S3/FSR outcomes at `70b008f`. No mixed-interval
> reattachment rate, overlay promotion, or Event Logic/pose resume claim
> follows from this authority. Queue identities and protocol:
> `docs/science/FAX4_QUEUE_MANIFEST.json`,
> `experiments/full_action/FAX_V4_PROTOCOL.md`. FAX3B remains consumed
> development evidence. Its 164 flight path has only a 0.05 s consecutive
> narrow run at the first apparent post-mix split; width alone does not
> certify physical-person reattachment. A provisional sparse-motion bridge
> links 23 moving mixed-edge features into that run versus zero stationary
> and at most three competing-box features, yielding local reattachment
> after 0.4 s of explicit NULL but only four asserted frames. It does not
> restore sampled flight coverage or establish overlay safety. See
> `docs/science/DIVE_ANALYZER_FAX_V4_DEV_READOUT.md`.

> Latest science: **2026-09-27 FAX V3 uncertainty-aware fresh gate FAIL;
> overlay gate CLOSED.** Blind FAX3 (four new sessions, authority digest
> `9a9e712c…`) produced identical V1/V2/V3 prep: 25/51 correct, 26 honest
> abstentions, zero sampled wrong-person links, but no mixed selected-flight
> edge. Targeted blind FAX3B (four further sessions, digest `0cf6e1d…`) found
> one true mixed edge on 164; V3 abstained safely but suppressed its later
> correct flight subcore. Three selected flights: V1/V2 23/31 correct prep,
> 24/27 flight; V3 23/31 prep, 16/27 flight; zero sampled wrong-person prep
> overlaps for all. 373 was unsurfaced. Consumed 205 still shows V3 changing
> 26 wrong prep overlaps to abstention, but that is development evidence only.
> V3 is not promoted. Next blocker: calibrated person-specific reattachment
> after a mixed interval; 164/1363 prep perception and 373/1751 upstream
> flight surfacing are separate. Event Logic V3-C0/V4-B0 remains frozen and
> pose paused. Reports: `docs/science/DIVE_ANALYZER_FAX_V3_FIRST_FRESH_READOUT.md`,
> `docs/science/DIVE_ANALYZER_FAX_V3B_FRESH_GATE.md`.
> Gate: `SUPERVISOR_REVIEW_AFTER_UNCERTAINTY_AWARE_FULL_ACTION_TRACKING`.

> Latest science: **2026-09-27 FAX V2 fresh gate FAIL.** Blind session-disjoint
> `FULL_ACTION_GT_HUMAN_FAX2_FRESH` (205/1751/1621/1363; digest `6a4914c9`)
> found V2 identical to V1 on selected tracks: 7/54 correct prep anchors,
> 26 wrong-person overlaps, 3/4 flights selectable. In 205 a selected-flight
> S3 box spans two people and the backward chain follows the wrong one.
> Full-action overlays and pose remain unsafe; Event Logic V3-C0/V4-B0 frozen.
> Report: `docs/science/DIVE_ANALYZER_FAX_V2_FRESH_GATE.md`.
> Detailed supervisor output and repair hypotheses:
> `docs/science/DIVE_ANALYZER_FAX_V2_DETAILED_SUPERVISOR_OUTPUT.md`.
> Gate: `SUPERVISOR_REVIEW_AFTER_SELECTED_FLIGHT_CONDITIONED_ASSOCIATION`.

> Durable project handoff. Last verified: **2026-09-27** (science thread: FAT3 full-action + event-logic validation - fresh session-disjoint DEVELOPMENT authority FULL_ACTION_GT_HUMAN_V3_FRESH (6 dives, digest dfd493f0); frozen FAX V1 validated 29/29 prep @ 1.0 where identity is unambiguous, association (not perception) is the blocker in multi-person prep; frozen V3-C0 still fails on validated tracks; V4-B0 successor materially improves with a documented prep-rise-lock failure; overlay conditional, pose stays paused; gate SUPERVISOR_REVIEW_AFTER_FULL_ACTION_AND_EVENT_LOGIC_VALIDATION.)
> Previous handoff: **2026-09-26** (science thread:
> Dive Analyzer flight perception recovery V2 — fresh blind HUMAN V3 development
> holdout (14 dives/13 disjoint sessions, digest `83326b04`), selected S3
> (`3dc07f69`) before V3 GT read; frozen FSR primary top-5/top-10 **12/14**
> versus S2 **11/14** and D5 **3/14 / 4/14**. Frozen manual multi-track
> gate passed. S3 360p raw presence 0.844 vs S2 0.852 and D5 0.861, but
> stronger confidence continuity drives pool and surfaced trajectories;
> replay 1/2, HQ 11/12. D5 faint tail is real but naive union did not
> improve surfaced trajectories in consumed V2 development. Remaining:
> dive 377 observation/graph loss; replay 1003 search-pool to candidate
> extraction with proxy-only unverified HQ. S3 PROMOTED FOR FURTHER SCIENCE;
> product-wide robustness not established. Gate
> `SUPERVISOR_REVIEW_AFTER_FLIGHT_PERCEPTION_RECOVERY_V2`.)
> Previous: **2026-09-26** (science thread:
> Dive Analyzer flight perception successor V1 — fresh session-grouped split from the canonical
> DB (`FLIGHT_PERCEPTION_SUCCESSOR_SPLIT_V1`, 525ee82); new blind human authorities
> `FLIGHT_GT_HUMAN_V2_HOLDOUT` (sealed, 9 dives/8 sessions, f9712942) and `FLIGHT_TRAIN_HUMAN_V1`
> (16 dives, 176 boxes, 05574219); experimental successor `S2_COCOinit_DS1` (yolov8n COCO init,
> d3ba0b03) selected on validation only; fresh holdout surfaced top-5 **5/9 vs frozen D5 1/9**
> (HQ dives 5/6 vs 0/6), frozen FSR search unchanged; mechanism = subject confidence separation
> (HQ top-1 box 28 %→91 %, margin −0.16→+0.76); new failure = low-confidence tail lost on
> out-of-domain footage (screen recordings, distant subject); manual multi-track narrowly NOT viable
> (56 % < 60 %); successor PROMOTED for further science (experimental), D5 frozen untouched;
> HQ read from PROD B2 read-only; gate `SUPERVISOR_REVIEW_AFTER_FLIGHT_PERCEPTION_SUCCESSOR`).
> Previous: **2026-09-26** (science thread:
> Dive Analyzer flight search recovery V1 — new blind mid-flight HUMAN authority
> `FLIGHT_GT_HUMAN_V1` (123 boxes, 15 dives, digest `740bf71d`); redesigned search
> (global track-before-detect DP + ballistic flight-segment ranking, protocol frozen
> `3317d70` before sealed eval): surfaced top-5 3/15 at 360p vs frozen V3 2/15 (V3 pool
> 0/15); 360p+HQ 4/9 event dives (top-10; all rank 1 with post-sealed ranker v2);
> dominant loss = SEARCH CONSTRUCTION 8/15 (airborne subject has lower D5 confidence than
> nearby people; OSNet AUC 0.59); DEV landmark authority found detector-in-sample; 1080p
> helps observation, complementary, not sufficient; manual multi-track NOT viable;
> gate `SUPERVISOR_REVIEW_AFTER_FLIGHT_SEARCH_RECOVERY`).
> Previous: **2026-09-25** (science thread:
> Dive Analyzer flight-path candidate recall audit V1 — frozen V3 reproduced
> 15/15 byte-identical; retention funnel (9 event dives): raw 7 → graph oracle 4
> → generated pool 0 → F0 top-K 0 → F1 1 (676 thin); strict-human seeds 5→4→0→1;
> subject flight is representable but never generated → `SEARCH_IS_PRIMARY_BLOCKER`,
> `IMPROVE_SEARCH_RECALL_NEXT`, `MANUAL_TRACK_SELECTION_NOT_YET_VIABLE`,
> `OTHER_ACTION_GT_STILL_PREMATURE`; defects found: motion-gate unit error in V3
> and upstream r5 (subject flight links rejected 24–55 %), end-of-clip-only pool
> harvest, spike-latched mover slots, seeding never on airborne diver (71/94),
> hurdle subject authority evaluator-seeded/candidate-snapped (1040/2541 zero
> HUMAN_GT), F1 backward sign, core-length saturation, 202×360 proxies despite
> recovered aligned 1080p for 12 dives; bug-fix candidates evaluated, NOT promoted;
> git authority reconciled: V3 merged into canonical `f043f63`, mirror was stale).
> Previous: **2026-09-21** (science thread:
> Dive Analyzer flight-anchored trajectory V3 — frame-level flight-lattice
> decoding with NULL state and dual-population beam: flight recall 1/9
> (676 thin), action recall 1/15 (2169 prep-dominated, refused as recovery);
> observation complete, chaining works, subject selection among competing
> flights is the next blocker → `FLIGHT_ANCHORED_TRAJECTORY_V3_PARTIAL`,
> `IMPROVE_DIVE_ACTION_VALIDATION_NEXT`; frozen authorities untouched).
> Previous: **2026-09-20** (science thread:
> Dive Analyzer subject-conditioned identity pilot L0 — first bounded learned
> identity-matching experiment with oracle within-clip reference: LODO top-1
> B0 4/12, B1 2/12, L0 1/12 → `IDENTITY_MATCHER_L0_FAILS`,
> `SCALE_IDENTITY_MATCHER_DATA_NEXT`; GT-free reference acquisition stays open).
> Previous: **2026-09-20** (science thread:
> Dive Analyzer independent subject-GT expansion V1 — 6 new dives, Level-B
> frozen, V3 replay generalizes, identity-learning pilot justified, design-only).
> Previous: **2026-09-13** (infrastructure thread:
> HTTPS migration, session auth, B2 thumbnail fallback, DB connection leak fix).
> Previous: **2026-09-11** (media-backbone P11:
> FINAL CLOSURE — MEDIA_BACKBONE_V1 CLOSED_AND_RETURNED_TO_PARENT_SUPERVISOR).
> Latest backbone: `docs/handoffs/MEDIA_BACKBONE_V1_CLOSURE_HANDOFF.md` (final
> parent-supervisor handoff; byte+count accounting RECONCILED).
> Previous backbone: `docs/audits/MEDIA_BACKBONE_P10_OVERNIGHT_FULL_DIVE_ANALYZER_MIGRATION_V1.md`
> Latest science: `docs/science/DIVE_ANALYZER_FLIGHT_PERCEPTION_RECOVERY_V2.md`
> (fresh V3 HUMAN authority, frozen S3/D5/S2 comparison and downstream FSR gate)
> Previous science: `docs/science/DIVE_ANALYZER_FLIGHT_PERCEPTION_SUCCESSOR_V1.md`
> (fresh holdout, flight-focused detector successor vs frozen D5 through the frozen search)
> Previous science: `docs/science/DIVE_ANALYZER_FLIGHT_SEARCH_RECOVERY_V1.md`
> (sealed funnel V3 vs redesigned search, 360p vs HQ, human flight authority audit)
> Previous science: `docs/science/DIVE_ANALYZER_FLIGHT_PATH_CANDIDATE_RECALL_AUDIT_V1.md`
> (audit/localization; S0–S6 stage funnel with evaluation-only graph oracle and
> beam subject trace; search S2→S3 loses every representable case)
> Previous science: `docs/science/DIVE_ANALYZER_FLIGHT_ANCHORED_TRAJECTORY_V3.md`
> (frame-level F0 flight lattice + F1 bidirectional extension, protocol-frozen;
> 1/9 flight recall, 1/15 action recall prep-dominated; observation ruled out,
> chaining solved, selection is the blocker → `PARTIAL`,
> `IMPROVE_DIVE_ACTION_VALIDATION_NEXT`, `OTHER_ACTION_GT_NOW_HIGH_VALUE`)
> Previous science: `docs/science/DIVE_ANALYZER_SUBJECT_CONDITIONED_IDENTITY_PILOT_L0.md`
> (15 dives / 13 sessions / 4 athletes; `ORACLE_WITHIN_CLIP_REFERENCE_V1`
> even/odd split, 11-D L2 logistic C=1.0; Layer-A LODO top-1 B0 4/12, B1 2/12,
> L0 1/12, LOSO identical; rank smoothing without top-1 gain on 29 MATCH
> positives → `IDENTITY_MATCHER_L0_FAILS`, `SCALE_IDENTITY_MATCHER_DATA_NEXT`;
> oracle is non-production, GT-free acquisition remains the product bottleneck)
> Previous science: `docs/science/DIVE_ANALYZER_INDEPENDENT_SUBJECT_GT_EXPANSION_V1.md`
> (6 new independent dives 1304/2204/2223/2526/2583/2839; 180 HUMAN_REVIEWED
> Level-B anchors frozen as `SUBJECT_GT_LEVEL_B_INDEPENDENT_V1`
> SHA `dc958909…`; frozen V3 replay 0/12 top-1, phantom top-1 1→0, all wrong
> tops supported movers → `SUPPORTED_REAL_MOVER_IDENTITY_GENERALIZES`;
> `IDENTITY_LEARNING_PILOT_JUSTIFIED`, L0 design-only, no training)
> Previous science: `docs/science/PERCEPTION_STATUS_REBASE_V1.md` (strategic status rebase)
> Previous science: `docs/science/ICLOUD_HIGHRES_ANALYSIS_SOURCE_RECOVERY_V1_REPORT.md`
> Previous science: `docs/science/EVENT_LOGIC_V3_REAL_DATA_REPAIR_REPORT.md`
> Previous science: `docs/science/PROCEDURAL_TRAJECTORY_READINESS_AND_EVENT_LOGIC_V3_REPORT.md`
> Previous supervisor gate (flight perception recovery V2): **`SUPERVISOR_REVIEW_AFTER_FLIGHT_PERCEPTION_RECOVERY_V2`**
> (previous: `SUPERVISOR_REVIEW_AFTER_FLIGHT_PERCEPTION_SUCCESSOR`,
> `SUPERVISOR_REVIEW_AFTER_FLIGHT_SEARCH_RECOVERY`, `SUPERVISOR_REVIEW_AFTER_FLIGHT_PATH_CANDIDATE_RECALL_AUDIT_V1`,
> earlier: `SUPERVISOR_REVIEW_AFTER_FLIGHT_ANCHORED_TRAJECTORY_V3`,
> earlier: `SUPERVISOR_REVIEW_AFTER_SUBJECT_CONDITIONED_IDENTITY_PILOT_L0`,
> earlier: `SUPERVISOR_REVIEW_AFTER_INDEPENDENT_SUBJECT_GT_EXPANSION_V1`,
> earlier: `SUPERVISOR_REVIEW_AFTER_SUBJECT_CANDIDATE_QUALITY_V3`,
> earlier: `SUPERVISOR_REVIEW_AFTER_SUBJECT_GT_LEVEL_A_ANNOTATION_V1`,
> earlier: `SUPERVISOR_REVIEW_AFTER_SUBJECT_RESOLUTION_COHORT_EXPANSION_V1`,
> earlier: `SUPERVISOR_REVIEW_AFTER_SUBJECT_REFERENCE_ACQUISITION_V2`,
> `SUPERVISOR_REVIEW_AFTER_SUBJECT_RESOLUTION_V1`,
> `SUPERVISOR_REVIEW_AFTER_SUBJECT_RESOLUTION_AUDIT_V1`,
> `SUPERVISOR_REVIEW_AFTER_PERCEPTION_STATUS_REBASE_V1`;
> earlier: `SUPERVISOR_REVIEW_AFTER_CORE_DETECTION_V1_P1`, pending)
> Media-backbone gate: **`MEDIA_BACKBONE_V1: CLOSED_AND_RETURNED_TO_PARENT_SUPERVISOR`**
> (media-backbone subproject ended; further media work returns to the main supervisor)

## Project purpose

Personal diving-analysis platform for a single athlete (Maxime) and training partners.
Divers manually pre-trim clips in macOS Photos and caption them with a compact grammar
(dive code, performance, height, modifiers). The system ingests those clips + captions,
stores structured metadata, computes statistics/insights, and serves a web UI.
Long-term goal: a second, deeper analysis layer (phase timing, takeoff/entry
characteristics, athlete-vs-self comparison). **Partially underway — Perception V1 frozen.**

## Canonical repository

- **`mcauchy@192.168.1.57:~/dive-analyser`** (Debian 12, host `deb-serv`) — the ONLY
  canonical Git repository. Branch `uiux-overhaul-pro-app`. HEAD: `e3c6cc4` → updated this cycle.
  No remotes.
- Mac bare mirror: `~/.perso/diveanalyzer-perception.git` (cloned from server).
- Mac working copy: `~/.perso/diveanalyzer-perception`. Remote `origin` → server. Remote `mac-mirror` → bare mirror.
- Local Mac working copy `~/.perso/diveanalyzer` is **NOT a git repo** — only a partial
  reference slice; never treat it as canonical.
- SSH access (passwordless from Maxime's MacBook Air only): key `~/.ssh/qwokka`
  installed in both hosts' `authorized_keys`; aliases in `~/.ssh/config`:
  `ssh diveanalyzer-server` (= `mcauchy@192.168.1.57`),
  `ssh diveanalyzer-mac` (= `divesensei@192.168.1.19`).

## Current deployment topology

Two machines on a LAN:

| Machine | Host | Role |
|---|---|---|
| Machine A | Debian 12 server `deb-serv` @ `192.168.1.57` (user `mcauchy`) | App host: Postgres 16, FastAPI backend, React frontend (nginx), reverse proxy (6090/6443), adminer. Canonical repo at `~/dive-analyser`. |
| Machine B | Intel MacBook, macOS 15.1.1, `mac-server.home` @ `192.168.1.19` (user `divesensei`) | Ingestion + media edge: watches the Photos library, parses captions, syncs metadata, exports/transcodes/uploads posters & proxies, manages a source vault for originals. |

## Science layer status (2026-09-09)

### High-Resolution Analysis Source Recovery — FROZEN_WITH_PER_ASSET_TEMPORAL_AUTHORITY

The Photos/iCloud recovery blocker was repaired through normal macOS Photos Full Access
for the actual PhotoKit client. Full-byte edited high-resolution renditions were recovered
for all 14 authorized TRAIN + DEVELOPMENT_EVAL media IDs, with media stored outside Git at
`/Users/Shared/services/data/media-node/highres_analysis_source_v1/`.

Temporal authority is per asset, now fully deterministic: 11 assets are
`PTS_EQUIVALENT` and 3 are `RECOVERED_DETERMINISTIC_MAPPING` (311 trim
`t_hq = t_proxy − 12.125s`; 524 PTS-equivalent with hflip+1.25-crop spatial
transform; 676 verified top-band crop map). **Zero quarantines remain** — the
311/524 quarantines were lifted by the quarantine forensics (evidence:
`docs/science/HIGHRES_QUARANTINE_FORENSICS_V1.json`), and 676's spatial map
was verified (the earlier map was direction-inverted).

Resolution decision (frozen):
`PRODUCTION_ANALYSIS_REPRESENTATION_REMAINS_PROXY_360P`
(`docs/science/HQ_REPRESENTATION_DECISION_V1.json`). HQ = archival master +
label forensics + future-retrain source, never fed to the frozen D5 detector;
720p canaries are derived tooling artifacts. Detector status remains
`NO_RETRAIN_AUTHORIZED`.

Primary artifacts:
- `docs/science/PHOTOS_TCC_CLIENT_V1.json`
- `docs/science/HIGHRES_ANALYSIS_SOURCE_MANIFEST_V1.json`
- `docs/science/ANALYSIS_SOURCE_HQ_V1_FREEZE.json`
- `docs/science/HIGHRES_QUALITY_AUDIT_D5_CANARY_V1.json`
- `docs/science/ICLOUD_HIGHRES_ANALYSIS_SOURCE_RECOVERY_V1_REPORT.md`
- `docs/science/HIGHRES_QUARANTINE_FORENSICS_V1.json`
- `docs/science/HQ_REPRESENTATION_DECISION_V1.json`
- `docs/science/HQ_REPRESENTATION_720P_AND_QUARANTINE_FORENSICS_V1_REPORT.md`
- `docs/science/HQ_PROXY_TEMPORAL_SPATIAL_INTEROP_V1.md`

### Frozen references
- Canary dive: 2819 (5122D G/G, springboard 1m, hurdle)
- Source: `IMG_1937.mov` SHA=`d122262be8e7a8721ab2f6a71721bb3544403da78324138d026360ef9820eaae`
- GT PTS: takeoff=3.120s, apex=3.570s, water_contact=4.220s
- Event Logic V2.1 frozen: `EVENT_LOGIC_V2_1_FREEZE.json`, 29/29 unit tests pass

### Perception V1 — FROZEN

**Architecture: `D5_FRAMEWISE_SUFFICIENT`**

| Component | SHA (first 16) | Status |
|---|---|---|
| D5-A detector (YOLOv8n) | `82b420c4583f8271...` | FROZEN |
| R1 reranker (ResNet50+LogReg) | N/A | NOT USED |
| Temporal continuity | N/A | NOT IMPLEMENTED |

**DEVELOPMENT metrics:**
- floor_recall: 97.1% (33/34 canonical frames)
- op_recall: 88.2%
- top-1 recall (D5-alone): 33.3%
- top-1 recall (D5+R1): 27.8%
- Δ top-1 (R1 contribution): -5.5%
- Architecture selection: R1 does not add material value (threshold: 5pp)

### Paris Canary (external evaluation — firewall intact)

**Flight trajectory gate: `TRAJECTORY_INPUT_PASS`** ✓

| Criterion | Result | IoU |
|---|---|---|
| C1: takeoff identity | ✓ PASS | 0.379 |
| C2: apex identity | ✓ PASS | 0.417 |
| C3: water_contact identity | ✓ PASS | 0.324 |
| C4: ≥80% flight coverage | ✓ PASS | 100.0% |
| C5: max gap | ✓ PASS | 0.0s |
| C6: wrong-target run | ✓ PASS | 0.0s |

**Procedural trajectory gate: `PARIS_PROCEDURAL_INPUT_PASS`** ✓  
C1_prep=100%, C2_pretakeoff=100%, Flight=100%. Full video (322/344 frames @ 1080p).

**Event Logic on Paris (V2.1 and V2.2) — FULL TRAJECTORY:**

| Version | Complete | to_err | ap_err | wc_err | Note |
|---|---|---|---|---|---|
| V2.1 | ✓ | 1.685s | 1.952s | 0.183s | HURDLE prep_end fails (FM2) |
| V2.2 | ✓ | 1.335s | 1.552s | 0.183s | HURDLE prep_end fails (FM2) |

Previous "BOTH_FAIL" EL result was incorrect — it ran on 3-point anchor trajectory, not full video.
Current failure: HURDLE prep_end detection (FM2 — first motion at 0.683s, actual takeoff 3.12s).

Artifact: `PARIS_PROC_EL_EVALUATION_V1.json`

### DEVELOPMENT Multi-Dive Evaluation

| Metric | Value |
|---|---|
| Dives evaluated | 10 |
| PERCEPTION_VALID (D5_FRAMEWISE) | 6 (60.0%) |
| PERCEPTION_INVALID | 4 |
| Valid dives | [133, 311, 676, 1040, 2169, 2387] |
| Invalid dives | [524, 2341, 2555, 2625] |

**PROCEDURAL gate (new):** All 6 VALID dives pass `PROCEDURAL_TRAJECTORY_INPUT`.  
Floor coverage = 100% for all. Op_conf coverage: 133=58.4%, 311=62.0%, 676=81.5%, 1040/2169=100%, 2387=89.2%.

**DEVELOPMENT EL evaluation (full continuous trajectories):**

| Dive | V2.1 complete | to_err | wc_err | Root cause |
|---|---|---|---|---|
| 133  | ✓ | 0.165s | 0.148s | OK |
| 311  | ✓ | 0.059s | **3.530s** | FM1: UNBOUNDED APEX FALLBACK |
| 676  | ✗ | — | — | FM3: 360p noise + interpolate_gaps crash |
| 1040 | ✓ | 1.995s | 2.511s | FM2: PREMATURE HURDLE PREP_END |
| 2169 | ✓ | 1.280s | 0.364s | FM2: late takeoff detection |
| 2387 | ✓ | 2.148s | 0.039s | FM2: PREMATURE PREP_END (brief off-board rest) |

**EL gate: `EVENT_LOGIC_FAILURE_CONFIRMED`** — 5/6 complete, documented failures.

### Event Logic V3 — DEVELOPMENT COMPLETE, NOT PROMOTED

**V3_DEVELOPMENT_COMPLETE_INSUFFICIENT**: V3-B best (3/6) < V2.1 (5/6). Not promoted.

**V3-A**: REJECTED (2/6) — STANDING "last qualifying plateau" picks post-wc pool-deck detections.  
**V3-B**: MARGINAL (3/6) — water_line_cy_norm boundary unreliable (diver disappears at wc).

**Confirmed future improvements:**
- A1 (bounded apex fallback): correct, validated by unit tests. Patch to V2.1 in next cycle.
- A2 (bounded wc search): correct. Patch to V2.1 in next cycle.

**Key finding (HURDLE prep_end):** HURDLE preparation structure is non-deterministic across divers (user-confirmed). No single rule generalizes. Requires future scene-level temporal segmentation.

V3 freeze: `EVENT_LOGIC_V3_FREEZE.json`

### Dive 311 diagnosis (CORRECTED)

| Field | Value |
|---|---|
| Classification | **EVENT_LOGIC_CAUSED_FAILURE** (corrected from PERCEPTION_GAP_CAUSED_FAILURE) |
| Procedural coverage | PASS (C2=89.7%, flight=100%) |
| V2.1 takeoff | 13.814s (error: **0.059s** — excellent) |
| V2.1 wc | 18.352s (error: **3.530s** — catastrophic) |
| Root cause | FM1: unbounded apex fallback picks pool-deck cy~0.11 as apex at 18.35s |
| Fix | A1 bounded apex (V3 confirmed): [takeoff, takeoff+1.5s] → wc_err ~0.15s |

### PTS Authority

**`PTS_AUTHORITATIVE_SEEK`** — always `cap.set(CAP_PROP_POS_FRAMES, fi)` before `cap.read()` for anchor frames.

Historical Paris failure documented: fi=235 sequential drift → fi=238 seek canonical (3-frame, 53ms at 56.5fps). Test suite: `test_pts_authority_v1.py` — 15/15 pass.

### Detector closure
`D5_A_FROZEN` — no new detector training authorized. Floor coverage 100% across all dives. No `RAW_DETECTOR_MISS` failures. No D6 warranted.

### Resolution diagnostic
`BLOCKED_TCC_PHOTOS_AUTHORIZATION` — iCloud catalog metadata is visible on the
Photos host, but full-byte edited high-resolution export is not proven. The
SSH-launched `osxphotos --download-missing --use-photokit` canary requested
Photos "Allow Access to All Photos" and failed authorization. Batch recovery was
not started; `ANALYSIS_SOURCE_HQ_V1` remains not frozen.

High-res recovery artifacts:
- `docs/science/ICLOUD_HIGHRES_ANALYSIS_SOURCE_RECOVERY_V1_REPORT.md`
- `docs/science/ANALYSIS_SOURCE_HQ_V1_FREEZE.json` (`NOT_FROZEN_CANARY_GATE_CLOSED`)
- `docs/science/HIGHRES_RECOVERY_BATCH_V1.json`

### Bug fix
`interpolate_gaps_time` in `proposer_event_logic_v2_1.py`: NoneType crash when left gap boundary is None. Fixed (None-guard). PARAMS_E1 unchanged.



`SUPERVISOR_REVIEW_AFTER_HURDLE_IDENTITY_REPAIR_V1`

## HURDLE target identity repair — COMPLETE (2026-09-09, identity-repair thread)

Packet `HURDLE_TARGET_IDENTITY_REPAIR` executed on top of `a551319` (Event Logic
HEAD) with the HQ-representation thread's `4b192dc` fetched read-only as the
canonical base. Read-only wrt the HQ thread's artifacts; no media/manifest
authority modified.

**Phase A — per-frame GT identity classification (new evidence):**
- Built `HURDLE_TARGET_ANCHORS_V1.json` (HUMAN_GT boxes at 20 annotated frames
  across 2169/2341/2353/2555 + operator-verified visual anchors; identity traps
  documented) and `HURDLE_TARGET_CHAINS_V1.json` (per-frame GT chains, GT-direct
  at annotated frames, AMBIGUOUS where identity is not establishable, WATER
  post-wc). Chains validated against every human box: IoU 0.30–1.00.
- `HURDLE_TARGET_IDENTITY_CLASSIFICATION_V1.json`: on ALL 5 classified HURDLE
  dives the target is present in the raw floor proposals **100% of evaluable
  frames**, while the D5 op-point top-1 is the target only **0.5–51.8%** (1040
  10.6%, 2169 96.3%, 2341 2.2%, 2353 0.5%, 2541 14.9%, 2555 51.8%); longest
  continuous wrong runs 33–363 frames. The failure is SELECTION, not detection.

**Phase B — R4 appearance-aware global path: FAIL.**
- `R4_APPEARANCE_AWARE_GLOBAL_PATH` implemented per packet spec (frozen ResNet50
  ImageNet features, NULL state, E3 sequence prior with bounded scan, E4 static
  prep protection, 192-config hyperparameter grid + dive-event track picking).
- Verdict: appearance features are non-discriminative at 360p (cross-cos ≈
  self-cos, 0.60–1.00) and D5 conf is anti-informative (the distractors are
  static background boxes with TOP conf — 2341: (0.64,0.11) conf 0.403 all
  video). Best R4 mean top-1 = 0.213 < D5 baseline 0.249. No configuration
  repairs any dive; 2169 is preserved (0.91–0.96).
- `HURDLE_R4_APPEARANCE_REPAIR_RESULT_V1.json` (verdict + diagnostics).

**FM2 reclassification + V3-D0 replay:**
- `HURDLE_FM2_RECLASSIFICATION_V1.json`: FM2 root cause corrected from "target
  instability/oscillation" to SYSTEMATIC per-frame selection failure (static
  distractors outrank the diver); detector-ceiling hypotheses refuted
  (avail_floor=1.000 on all classified dives incl. 1040).
- V3-D0 replayed on the frozen cache: 1040/2169 magnitudes reproduce the freeze
  exactly (sign convention differs); 5 HURDLE dives had no prior V3-D0 numbers.
  The frozen 1040 trajectory (cy=0.221) is literally the structure distractor —
  FM2 operates on the wrong object on 4/6 classified dives.

**524:** no usable GT anchors; the HQ hflip mapping self-validation FAILED
(exhaustive scale/flip/time search caps at NCC 0.32–0.46 vs spec ~0.74) — HQ 524
boxes NOT used; representation authority untouched.

### Tests / commits
- Worktree: `~/.perso/diveanalyzer-hurdle-identity-repair` (detached at `a551319`
  → `682b634` Phase A → `438b7e0` Phase B). Server integration lands on
  `4b192dc` via cherry-pick, then the report commit.
- Report: `docs/science/HURDLE_TARGET_IDENTITY_REPAIR_AND_FM2_CAUSAL_V1_REPORT.md`

## Event Logic V3-C — COMPLETE (2026-09-09)

**Decision: `V3_REAL_DATA_PROMOTION_JUSTIFIED`** — V3-C0 frozen.

### V3-C0 (A1+A2): FROZEN

Patches V2.1 with two bounded-search fixes only. All PARAMS_E1 values unchanged.

| Param | Value | Derivation |
|---|---|---|
| `apex_max_window_s` | 1.5s | 4.3× max dev takeoff→apex (0.35s, dive 2387) |
| `wc_max_window_s` | 2.5s | 2.6× max dev apex→wc (0.97s, dive 676) |

**DEVELOPMENT results:**

| Dive | V2.1 wc_err | V3-C0 wc_err | Note |
|---|---|---|---|
| 133  | 0.148s | 0.148s | unchanged |
| 311  | 3.530s | **0.027s** ✓ | FM1 FIXED |
| 676  | 0.752s | 1.016s | FM3 unresolved, minor regression |
| 1040 | 2.511s | 2.511s | FM2 unresolved |
| 2169 | 0.364s | 0.364s | FM2 unresolved |
| 2387 | 0.039s | 0.161s | minor regression |

| Metric | V2.1 | V3-C0 |
|---|---|---|
| Complete | 6/6 | 6/6 |
| med_to_err | 1.637s | 1.637s |
| med_wc_err | 0.558s | **0.262s** (+53%) |

**Paris V3-C0:** to_err=1.685s (FM2 unresolved), wc_err=0.133s (vs 0.183s V2.1).

### V3-C1 (A1+A2+HURDLE recontact): NOT PROMOTED

Scans all sustained-neg-vel starts; rejects any with positive vel in 0.25s window
(= board recontact after hurdle jump). Returns first candidate after last recontact.

Paris: to_err=0.183s, ap_err=0.033s (excellent). Development HURDLE catastrophic
regression (1040 to_err=6.214s, 2169 to_err=2.848s) due to 360p noise corrupting
the takeoff signal. DEVELOPMENT must justify before Paris can confirm.

### Open failures

- FM2 (HURDLE prep_end, dives 1040/2169): requires scene-level segmentation or higher-res proxies.
- FM3 (360p noise, dive 676): perception limitation.
- Paris HURDLE takeoff FM2: out of scope for V3-C0.

### Tests and artifacts

- `experiments/landmark_pilot/proposer_event_logic_v3_c0.py` — V3-C0 source
- `experiments/landmark_pilot/proposer_event_logic_v3_c1.py` — V3-C1 source (not promoted)
- `experiments/landmark_pilot/test_event_logic_v3_c.py` — 14 tests, 14/14 pass
- `docs/science/PARIS_MEDIA_IDENTITY_V1.json` — 322 vs 344 reconciliation
- `docs/science/EL_REAL_BASELINE_V1.json` — V2.1/V2.2 on full trajectories
- `docs/science/EL_V3C_DEVELOPMENT_EVAL_V1.json` — 4-variant DEVELOPMENT comparison
- `docs/science/EL_V3C_PARIS_EVAL_V1.json` — Paris external evaluation
- `docs/science/EVENT_LOGIC_V3_REAL_DATA_REPAIR_REPORT.md` — full report

**Regression:** 65/65 pass (V2.1 36 + PTS 15 + V3-C 14).

## Event Logic V3-D — FROZEN (2026-09-09)

**Decision: V3_D_DEVELOPMENT_IMPROVES_PARIS_FAILS / SCENE_CONTEXT_NEXT_JUSTIFIED**

### V3-D0: FROZEN (EVENT_LOGIC_V3_D0_FREEZE)

Board-rise validity gate for HURDLE apex detection + STANDING-like fallback.
Inherits V3-C0 (A1+A2) completely. Two new parameter keys only.

**Change summary:**
- D0: At each neg->non-neg velocity crossing after guard, check cy_apex < y_prep - min_rise.
  Physical invariant: at a real hurdle apex the diver must be above the board.
  If violated: crossing is a detector artifact -> continue scanning.
- Fallback: if no valid apex found, search for sustained negative velocity from guard_end.

**Parameters:** min_hurdle_rise_cy=0.01, fallback_sustained_s=0.15. All V3-C0/PARAMS_E1 values unchanged.

**DEVELOPMENT results:**

| Dive | Context | V3-C0 to_err | V3-D0 to_err | Delta |
|---|---|---|---|---|
| 133  | STANDING | 0.165s | 0.165s | UNCHANGED |
| 311  | STANDING | 0.059s | 0.059s | UNCHANGED (FM1 closed) |
| 676  | STANDING | 3.086s | 3.086s | UNCHANGED |
| 1040 | HURDLE   | 1.995s | 1.995s | UNCHANGED |
| 2169 | HURDLE   | 1.280s | **0.412s** | **-67.8%** (STANDING_FALLBACK) |
| 2387 | STANDING | 2.148s | 2.148s | UNCHANGED |

med_to: 1.637s -> 1.204s (-26.5%). med_wc: 0.262s -> 0.224s (improved).

**Freeze gate: PASS.** Hurdle improves, no STANDING catastrophe, FM1 closed, WC not regressed.

**Paris external test (read-only, post-freeze):**
- V3-D0 Paris to_err=1.685s -- identical to V3-C0
- Paris false hurdle at 1.117s: cy_apex=0.380 < y_prep=0.464, rise=+0.083 -> passes board-rise check
- Different failure mode from 2169 (approach-walk creates valid-looking brief rise above board)

**Scene context decision: SCENE_CONTEXT_NEXT_JUSTIFIED**
Paris approach-walk kinematics pass board-rise gate. Kinematic signals alone cannot distinguish
prep-walk rises from real hurdle at 360p.

**Observability findings (from V3-D analysis):**
- Both HURDLE dives: smooth_neg_ratio=0.0 at GT takeoff -> Gaussian smoothing destroys signal
- 2169 root cause: D5 switches from cy=0.262 to cy=0.711 at t=6.406s; artifact overwhelms rising motion
- 1040 root cause: D5 oscillates between cy=0.22 and cy=0.60; no filter/primitive recovers signal
- HQ (iCloud thread): 2169 HQ to_err=0.439s (improved); 1040 HQ sm_neg=0.714 (signal visible at HQ)

**V3-D1 evaluated:** identical results to V3-D0 (fallback_sustained_s=0.25s). Not promoted.

### Tests and artifacts

- experiments/landmark_pilot/proposer_event_logic_v3_d0.py -- V3-D0 source (frozen)
- experiments/landmark_pilot/test_event_logic_v3_d0.py -- 13 tests, 13/13 PASS
- docs/science/EVENT_LOGIC_V3_D0_FREEZE.json -- freeze artifact
- docs/science/EL_V3D_REVISED_DEVELOPMENT_EVAL_V1.json -- per-dive results
- docs/science/HURDLE_OBSERVABILITY_V3D_ANALYSIS_V1.json -- observability analysis
- docs/science/HURDLE_FINAL_TAKEOFF_OBSERVABILITY_AND_V3_D_REPORT.md -- full report

**Regression:** 27/27 pass (V3-C0 14 + V3-D0 13).

## V3-D0 status correction (2026-09-09, V3-E thread)

V3-D0 is `V3_D0_EXPERIMENTAL_FROZEN_DEVELOPMENT_BASELINE` — a frozen **development**
baseline, NOT production-promoted. Paris external failure (to_err 1.685s) stands.
FM1 CLOSED; FM2 OPEN/PARTIALLY_ADDRESSED; FM3 (360p target instability, 1040) open.
The V3-D0 test suite's Paris numeric assertion (`Paris to_err <= 2.0s`) was retired
as a selection criterion and replaced by Paris scientific-firewall integrity tests
(Paris absent from DEVELOPMENT inputs/params; freeze precedes Paris evaluation;
Paris artifact report-only). Suite now 16/16.

## HURDLE approach-end context and V3-E — COMPLETE (2026-09-09)

**Decision: `MORE_HURDLE_GT_REQUIRED` / `V3_D0_REMAINS_EXPERIMENTAL_BASELINE`.**
Full report: `docs/science/HURDLE_APPROACH_END_CONTEXT_AND_V3_E_REPORT.md`.

### Parallel-thread integration
Canonical HEAD `30267b1` verified on server + Mac; both reported thread HEADs
(`30267b1` Event Logic, `9881813` HQ/media) are ancestors (linear history, no
merge needed). HQ thread stable artifacts preserved; quarantined HQ (311, 524)
untouched. Audit: `docs/science/PARALLEL_THREAD_INTEGRATION_AUDIT.json`.

### HURDLE DEVELOPMENT corpus: 2 -> 7 dives (all with human V2 GT)
1040, 2169, 524 (HQ quarantined — 360p only), 2341, 2353 (drill), 2541, 2555.
2625 excluded (no takeoff GT); 2661/2680 excluded (armstand); INTERNAL_EVAL
(2281) untouched. No human-labeling gate needed; no step-count inference.

### Key findings
- **Robust board reference:** 1040's `y_prep` (0.531) is a corrupted mixture of
  two D5 levels; robust B1r cluster-median recovers the true level (0.2208) and
  fails loud (2541 non-diver plateau). Chosen: B1r.
- **2D audit:** no dive is APPROACH_END_OBSERVABLE_FROM_2D; the approach-progress
  coordinate s(t) is not reliably extractable at 360p. Vertical-only failure
  generalizes to 2D.
- **HQ (read-only, 1040/2169 only):** controlled comparison gives 1040 =
  HQ_IMPROVES_SNR_ONLY, 2169 = HQ_NO_MATERIAL_GAIN. Target instability persists
  at HQ; HQ does not repair detection.
- **V3-E0 (V3-D0 + B1r):** 2169 unchanged; **1040 regressed** (1.995s -> 5.746s):
  with a correct board level, the unbounded gate scan accepts a post-water-contact
  flicker crossing at 9.343s. STANDING byte-identical (4/4). FM1 intact.
- **V3-E1:** NOT_JUSTIFIED_BY_DEVELOPMENT_EVIDENCE (no validated end-of-board cue).
- **Freeze gate: FAILED** -> no V3-E freeze; `MORE_HURDLE_GT_REQUIRED`.
- **Paris (report-only, post-decision):** full-clip authority unchanged
  (to_err 1.685s); frozen 182-frame window trajectory: V3-D0 = V3-E0 = to_err
  1.3919s (window excludes the 1.117s pre-window feature). No tuning afterward.
- **Scene-context decision: `MORE_HURDLE_GT_REQUIRED`** — scene segmentation is
  NOT yet justified (target trajectory itself is incorrect; HQ no material gain).

### Tests
V3-E 13/13, V3-D0 16/16 (incl. Paris firewall 1-4), V3-C 14/14, highres 16/16,
PTS 15/15. Zero failures.

### Artifacts
- `experiments/landmark_pilot/proposer_event_logic_v3_e0.py` (candidate, not frozen)
- `experiments/landmark_pilot/test_event_logic_v3_e.py`
- `docs/science/DEV_HURDLE_TRAJ_CACHE_V2.json`, `STANDING_TRAJ_CACHE_V2.json`
- `docs/science/V3D0_HURDLE_CORPUS_BASELINE_V1.json`, `BOARD_REFERENCE_AUDIT_V1.json`
- `docs/science/TWOD_APPROACH_AUDIT_V1.json`, `HQ_HURDLE_DIAGNOSTIC_V1.json`
- `docs/science/V3E_DEVELOPMENT_COMPARISON_V1.json`, `V3E_FREEZE_GATE_FAILED_V1.json`
- `docs/science/PARIS_EXTERNAL_V3E_EVAL_V1.json`
- `docs/science/HURDLE_APPROACH_END_CONTEXT_AND_V3_E_REPORT.md`


## HQ representation audit + quarantine forensics — COMPLETE (2026-09-09)

**Decision: `PRODUCTION_ANALYSIS_REPRESENTATION_REMAINS_PROXY_360P`; manifest
`RECOVERED_ALL_DETERMINISTIC` (zero quarantines).**
Full report: `docs/science/HQ_REPRESENTATION_720P_AND_QUARANTINE_FORENSICS_V1_REPORT.md`.

### Quarantine forensics (Phases B/C/D)
- **311 lifted:** HQ = deterministic trim, `t_hq = t_proxy − 12.125s` (10/10
  stride-1 samples NCC 0.977–0.995, scale 1.0, no spatial transform). Both
  annotated events (takeoff 13.747s, water_contact 14.815s proxy) inside the
  HQ-covered window [12.125, 19.2433].
- **524 lifted:** PTS-equivalent (offset 0) with spatial transform
  hflip + zoom 1.25 (16/16 frames, scores 0.701–0.778; identity scan failed ->
  hflip required). HQ-arm box math for 524 unexercised (no audit run).
- **676 map verified:** HQ display 1080x1136 == proxy top band (rows
  [0, ~213/360]) upscaled x5.347, full horizontal FOV, no hflip; blur-equalized
  NCC 0.998 at loc (0,1); GT boxes for takeoff/apex/water_contact mapped into
  HQ land on the diver (`runs/hq_rep_v1/sheets/676_gt_overlay_HQ.png`). Prior
  map `{y_off 0.002, y_span 0.5917}` was direction-inverted and is superseded.
- Phase A unchanged: `ORIGINAL_MASTER_NOT_INDEPENDENTLY_PROVEN` (library fully
  iCloud-optimized; "original" exports byte-identical to edited renditions).

### Representation audit (frozen D5, 360p vs 720p vs HQ)
- 1040: 720p top-1 target switching (anchored cy SNR 0.22 vs 2.81 at 360p).
- 2169: anchored missingness 0.24–0.27 in takeoff window at 720p/HQ (0.0 at
  360p); anchored peak departure velocity ~2x at 720p.
- 676: top-1 switches away from the diver at takeoff/apex in 720p/HQ arms
  (diver present in candidates at IoU 0.63–0.72 but outranked) — genuine
  resolution-dependent ranking effect, not a mapping failure.
- 133 (control): stable across arms. Higher resolution gives 3–4x diver pixel
  height and better 2169 water-contact IoU, but only matters after a retrain.
- Tooling fixes: 676 map direction corrected and `event_identity` proxy-arm
  identity bug fixed in `hq_representation_audit_v1.py`; authoritative numbers
  from `hq_audit_recompute_v2.py` (V2 recomputed JSON + trajectory sheets).

### Decision + policy (frozen)
- Detector inference: proxy_360p only (frozen D5). HQ = archival master,
  label transfer allowed for all 14 dives through explicit deterministic
  transforms. 720p canaries = derived tooling artifacts (not durable; 1040
  720p drops 7/339 frames, VFR).
- Retrain at ≥480p: NOT authorized; requires a new detector freeze + fresh audit.
- `ANALYSIS_SOURCE_HQ_V1_FREEZE.json` amended (`resolution_decision`,
  `batch_summary`: 11 aligned + 3 deterministic mapping + 0 quarantined;
  amendment log).

### Tests
`experiments/landmark_pilot/test_hq_quarantine_forensics_v1.py` — 10/10
(manifest invariants, recovery_history preservation, 676 map direction math,
311 window coverage, forensics↔manifest↔decision↔freeze consistency,
audit-script map parity). Existing suites untouched.

### Artifacts
- `docs/science/HIGHRES_QUARANTINE_FORENSICS_V1.json`
- `docs/science/HQ_REPRESENTATION_DECISION_V1.json`
- `docs/science/HQ_PROXY_TEMPORAL_SPATIAL_INTEROP_V1.md`
- `docs/science/HQ_REPRESENTATION_720P_AND_QUARANTINE_FORENSICS_V1_REPORT.md`
- `runs/hq_rep_v1/`: `HQ_REPRESENTATION_AUDIT_V2_RECOMPUTED.json`,
  `scale_match_676_v2_blur.json`, `offset_verify_311_stride1.json`,
  `720p_canaries/`, `sheets/` (untracked; videos not committed)

## Media backbone P0/P1 — COMPLETE (2026-09-09, media-backbone thread)

**Status: `INTAKE_GATE_1_READY`** — implementation branch `media-backbone-p0-p1-v1`
(worktree `~/.perso/diveanalyzer-media-backbone`, base HEAD `4b192dc0`).
Task packet `MEDIA_BACKBONE_P0_P1_V1`. No cloud resources created. Production
upload/serving untouched; science authorities untouched.

### What exists now (all additive, feature-flagged OFF)

- **Agent-side backbone** `mac-agent/src/ingest/`:
  `content_addr` (sha256 + `blobs/sha256/<2>/<sha>` keys),
  `objectstore/` (`FakeObjectStore` test backend with fault injection,
  `BackblazeB2Store` S3-compatible adapter — lazy boto3, private-bucket,
  DEV/PROD bucket cross-wiring rejected, no bucket creation, guarded delete),
  `state_store` (JSON atomic-persist resumable state),
  `coordinator` (`ObjectStoreIngestCoordinator`, states
  DISCOVERED→…→CACHE_CLEANED + QUARANTINED, verified-ingest roundtrip rule:
  full GET SHA == local SHA, min_free_disk_bytes guard, stale-temp
  reconciliation, idempotent re-drive),
  `caption` (`CurrentStableCaptionProvider` authority — R1: returns the EXACT
  provider string, no app-level strip; `PhotosDbCaptionProviderShadow`
  SHADOW provider — R2: truthful name, direct Photos-DB SQLite is NOT
  PhotoKit, `PHOTOKIT_CAPTION_SHADOW_STATUS =
  NOT_IMPLEMENTED_CURRENT_RUNTIME`; redacted provider-identity parity
  harness).
  Config: `object_store:` block in mac-agent config, `enabled: false` default;
  disabled mode never constructs object-store components (tested).
- **Server-side additive schema** `backend/app/models/media_backbone.py`
  (`media_blobs`, `media_revisions`, `caption_revisions`,
  `ingest_object_state`) + idempotent commit service
  `backend/app/services/media_backbone.py::commit_verified_ingest`
  (refuses unverified commit; caption SHA must equal sha256 of the exact
  persisted caption_raw UTF-8 bytes) + additive migration
  `backend/migrations/add_media_backbone_tables.sql` (IF NOT EXISTS only,
  reversible by dropping the 4 new tables; static guard test).
- **Caption doctrine implemented (post-R1)**: `caption_raw` = EXACT provider
  output BEFORE any application-level whitespace normalization; the legacy
  `.strip()` lives ONLY in the legacy payload path
  (`legacy_caption_transform`) and is byte-unchanged; append-only revisions;
  shadow comparison fields; parser never mutates raw.
- **State-machine crash tests A–G all green** (before materialization /
  before hash / before upload / mid-upload / before verify / before commit /
  before cleanup) + no-duplicate replay + corrupt-state-file recovery.

### Test results (2026-09-09, Python 3.12, post-repair R1)

- `mac-agent`: `test_ingest_backbone.py` **68/68 pass**; full mac-agent suite
  with the repo-required deps installed (incl. pytest-asyncio): **127/127 pass
  on branch, 59/59 on base HEAD** — zero new failures.
- `backend`: `test_media_backbone.py` **23/23 pass**; full backend suite in an
  identical venv: base `9 failed / 279 passed / 11 skipped / 273 errors` vs
  branch `9 failed / 302 passed / 11 skipped / 273 errors` with **byte-identical
  failure/error signatures (282 lines)** — all pre-existing (sqlite vs
  postgres-UUID analysis models + 8 e2e async-plugin + 1 DD-metric test).
  `NEW_FAILURES_INTRODUCED_BY_BRANCH = 0` (branch adds +23 passing tests).

### B2 research (see `docs/architecture/MEDIA_BACKBONE_SECURITY_V1.md`)

Region choice is ACCOUNT-LEVEL at creation, immutable, one region per account;
EU Central = Amsterdam (`s3.eu-central-003.backblazeb2.com`); EU residency does
NOT remove US (CLOUD Act) jurisdiction over the provider — legal/policy
decision explicitly left to the human. PRIMARY-SOURCE pricing (Pay-As-You-Go):
$6.95/TB-month, first 10 GB free, free egress up to 3× average monthly
storage, $0.01/GB above; S3 API requires an Application Key (master key
unusable). Resource plan presents Option A (one account, two buckets) vs
Option B (separate accounts) neutrally; the human decides. P1 private-bucket
claims are CONFIGURATION REQUIREMENTS only — anonymous-access denial must be
verified against the real DEV bucket at P2.

### STATE AUTHORITY (post-R3)

Single coherent model: the mac-agent per-clip JSON execution journal is the
ONLY pre-commit/restart orchestration authority; the server DB
(blob/revision/caption-revision rows) is the ONLY durable committed-result
authority; `ingest_object_state` is a server-side durable commit ledger
written once per verified commit, never read by agent orchestration.
Reconciliation matrix (4 cases, one deterministic outcome each) tested in
`TestStateAuthority` + `TestStateAuthorityArchitecture`.

### Next gate

~~`INTAKE_GATE_1`~~ **PASSED 2026-09-09** — EU-Central account, DEV bucket
`diveanalyzer-dev-media` (private) + bucket-scoped key provisioned by the
maintainer; P2 canary executed **GREEN** (see next section). Remaining human
action: rotate the exposed first application key (P2 audit §17.1). Next phase:
P3 (5–10 clip queue, still canary-only) — DO NOT START without a new packet.

### Media backbone P2 — CANARY GREEN (2026-09-09)

**`P2_CANARY_GREEN`.** Full report: `docs/audits/MEDIA_BACKBONE_P2_CANARY_V1.md`.
One real clip (uuid `42D80813-0D2F-4F75-92BB-F0648E7AA77E`, `IMG_1641.mov`,
album `DiveAnalyser Ready` — en-GB spelling accepted as boundary alias) went
through the complete verified-ingest flow into the private EU-Central DEV
bucket `diveanalyzer-dev-media` (endpoint `s3.eu-central-003.backblazeb2.com`):

- exact caption byte-proof: `caption_raw` 48 chars / 49 UTF-8 bytes,
  SHA `18d6377f…`; shadow (PhotosDbCaptionProviderShadow, repaired to introspect
  the macOS 13+ caption join) exact-equal; caption-only mutation produced
  CaptionRevision id 2 (SHA `2c11f584…`) with SAME blob + same MediaRevision
  and ZERO media upload; append-only history holds (2 rows).
- media: Photos edited rendition (hasadjustments=true), HEVC 1920×1080
  9.288s, 19,019,783 B; SHA `2af63b4b…`; object key
  `blobs/sha256/2a/2af63b4b…9.mov`; full-GET roundtrip SHA equality (A==B PASS).
- controlled crash at `REMOTE_VERIFIED:before_effect` (injected failpoint) then
  receipt-confirmed restart converged `DB_COMMITTED → CACHE_CLEANED` (one
  logical result); server commit service idempotent (replay → same ids).
- real-provider privacy: anonymous bucket LIST → 403, anonymous object GET → 401;
  presigned GET (300s TTL) → 200; byte-range GETs → 206 (incl. mid-file + tail).
- DB authority: media_blobs/media_revisions/caption_revisions/
  ingest_object_state = 1/1/2/1 rows; legacy tables byte-untouched
  (0 dives/catalog rows for the canary; LaunchAgent ran throughout, pid stable).
- rollback: production agent config has NO object_store block (flag off by
  construction); canary runner refuses configs without the section.
- cost: ~19 MB storage + ~57 MB transfer → $0 (B2 free tier).
- production mutations: NONE. PROD resources: NONE. Secrets in Git: NONE.
- SECURITY: first applicationKey exposed in a chat screenshot during install —
  rotate (delete + recreate + re-inject) before P3.
- runtime corrections: production runtime IS the "DiveSensei Python Runtime.app"
  bundle (P0-era note was wrong); P2 ran one-shot CLI from the same
  host/user/interpreter context with proven Photos TCC (probe 12277 videos).

### Media backbone P3 — READY QUEUE COMPLETE (2026-09-09)

**Status: P3_COMPLETE** (DEV/canary only). Full report:
`docs/audits/MEDIA_BACKBONE_P3_READY_QUEUE_V1.md`. Branch
`media-backbone-p3-ready-queue-v1`.

- Key rotation done BEFORE any P3 media op: old `diveanalyzer-dev-canary` key
  revoked (maintainer-attested in console), new bucket-scoped DEV key
  installed (0600, single file); preflight + negative scope probes green
  (no all-buckets/admin/prod capability; UI Read/Write preset includes
  deleteFiles — flagged for P4 key tightening).
- Bounded queue: explicit 9-UUID allowlist (album = 82 assets; membership is
  NOT authorization; >10 refused live + unit-tested). 9/9 ingested, 100%
  full-GET SHA equality, shadow caption parity 9/9 exact-equal.
- Controlled tests (live): retryable PUT failure → recovery; quarantine
  (fail-closed) → isolation + release/resume; low-disk guard → refusal
  before materialization + resume; SIGKILL mid-run → journal restart
  convergence; unchanged rerun ×2 → 0 ops / 0 duplicates.
- Mutations: caption-only (new CaptionRevision id 11, same blob/revision,
  0 media upload); media trim (new fingerprint v2, bytes 19,019,783 →
  10,139,200, 9.288 s → 5.158 s, new blob `b712e2ea…` + MediaRevision id 10;
  old blob retained on B2).
- Repairs (auto-repair scope): GUI-launchd one-shot materialization for
  iCloud-only assets (PhotoKit needs Aqua session; maintainer granted venv
  python Photos access via System Settings; transient launchd job per
  export, booted out after use — not a daemon); edited-rendition-preferred
  selection; edit fingerprint v2 (adjustment render plist SHA);
  interactive-prompt refusal; stale-receipt cleanup on journal reset.
- DB authority: media_blobs/media_revisions/caption_revisions/
  ingest_object_state = 10/10/11/10; legacy tables untouched
  (`LEGACY_PRODUCTION_PATH_MUTATIONS NONE`, `BACKBONE_CANARY_DB_MUTATIONS YES`
  — corrected terminology per packet §3, P2 audit §20 updated).
- Privacy/presign/range recheck: anonymous LIST 403 / object GET 401;
  presign 200; Range 206 (representative new object).
- Bounds: min free disk 20.28 GB; peak temp cache 275 MB; sequential
  single-asset policy held. DEV storage ~0.2 GB → cost $0 (free tier).
- Ready-album UX finding (not frozen): album is a poor exclusive boundary at
  82 members; implicit readiness (caption-present + not-yet-ingested) with
  album-as-override is the evidence-backed direction for P4.
- Rollback unchanged: production config has NO object_store block (flag off
  by construction); nothing to revert.
- STOP before P4 (production dual-write canary).

### Media backbone P4 — PRODUCTION DUAL-WRITE CANARY GREEN (2026-09-09)

**Status: `P4_PRODUCTION_DUAL_WRITE_GREEN`.** Full report:
`docs/audits/MEDIA_BACKBONE_P4_PRODUCTION_DUAL_WRITE_CANARY_V1.md`. Branch
`media-backbone-p4-prod-dual-write-v1` (ff-merged into canonical).

- PROD bucket `diveanalyzer-prod-media` (EU-Central 003), private
  (anonymous LIST 403 / GET 401 re-verified post-commit). One NEW
  production clip (uuid `5F884C3D…`, `IMG_2069.MOV`, not previously in DEV
  backbone) dual-wrote once: legacy media job materialized the edited
  rendition ONCE, dual-write staged a copy (0.023 s) and ingested the same
  bytes to B2 PROD (40,865,620 B, `blobs/sha256/a8/a8579aa4….mov`),
  full-GET SHA equality, authenticated backend commit (env=prod rows).
- Production-safe commit transport replaces the operator tunnel:
  `POST /api/v1/media/backbone/commit` (X-API-Key, fail-closed validation,
  canonical `{payload, extra}` document, idempotent via
  `commit_verified_ingest`). P3 tunnel = DEV/CANARY DIAGNOSTIC ONLY.
- Flags `object_store.enabled` + `dual_write.enabled` (default OFF) with
  hard single-UUID allowlist guard; single backpressure slot.
- Controlled injections GREEN: first-B2-PUT retryable failure → legacy
  unaffected → recovery, one blob; backend-commit lost-response → remote
  retained, retry converged, 0 duplicates (put skipped, 0 new bytes).
- Unchanged rerun: 0 rows / 0 bytes. Caption-only mutation (new
  CaptionRevision id 13, same blob/revision, 0 B2 upload) + idempotent
  rerun. Rollback: flags OFF → legacy-only verified (0 object-store
  activity, playback intact), canary blob retained.
- Mutations: `LEGACY_PRODUCTION_BEHAVIOR_MUTATION NONE`;
  `BACKBONE_PRODUCTION_CANARY_DB_MUTATION YES`;
  `PRODUCTION_OBJECT_STORE_MUTATION YES (one canary lineage)`;
  `PRODUCTION_PLAYBACK_MUTATION NONE`; science untouched.
- Repairs: production daemon connectivity probe lacked the internal CA
  (loops never started since boot — pre-existing; logs prove pre-P4) —
  fixed; backend endpoint accepted the canonical nested document shape;
  ObjectStoreConfig.storage_backend; P3 metrics run-unique snapshots.
- SECURITY DEBT (temporary, maintainer-accepted): PROD key preset includes
  `deleteFiles` (Backblaze UI limitation; key is bucket-scoped; no delete
  in any ingest path). `P5_OR_BROADER_PROD_BLOCKER = YES` until a
  deleteFiles-free key exists or the supervisor re-approves. PROD key
  rotated by maintainer before closure (chat-exposed key revoked,
  attested). **DEBT CLOSED 2026-09-09 by P4.1 (see next section).**
- Object Lock console check still owed (key cannot read lock config).
- Tests: agent 164/164; backend backbone 32/32; full backend suite has
  only the pre-existing failure. Cost: ~0.2 GB storage + transfer → $0.

### Media backbone P4.1 — least-privilege PROD key hardening COMPLETE (2026-09-09)

**Status: `PROD_KEY_HARDENING_GREEN`.** Packet
`MEDIA_BACKBONE_P4_1_PROD_KEY_HARDENING_V1` on top of canonical HEAD
`ce3be0381…` (security hardening only; no code changes; no P5, no
broader cohort). Evidence:
`docs/audits/MEDIA_BACKBONE_P4_1_PROD_KEY_HARDENING_V1_EVIDENCE.json`;
P4 audit §35.

- New PROD key `diveanalyzer-prod-ingest-v2` (id `…0006`) created via
  Backblaze Native API v4 with exact capabilities
  `[listFiles, readFiles, writeFiles]`, bucket-restricted to
  `diveanalyzer-prod-media` (`7e720bcb6587827caf0b0a17`), `options=["s3"]`.
- Scope proven twice (create response + fresh authorize WITH the new
  key); negative probes: hard delete / bucket ops / key ops → 401,
  other-bucket S3 → 403; S3 DeleteObject = soft hide on B2 (upload
  version retained) — canary untouched throughout.
- S3 compat GREEN: PUT single + 12 MB multipart, HEAD, GET SHA equality,
  presigned GET 300 s → 200, list ok. No DELETE performed.
- Runtime cutover atomic: `object_store_prod.env` (0600, divesensei)
  now holds the least-privilege key; production runtime preflight GREEN
  (adapter init, canary HEAD, full-GET SHA equality 3.81 s); dual-write
  flags OFF; legacy daemon healthy; no production media mutation.
- Old key `diveanalyzer-prod-agent` (…0004) revoked
  (maintainer-attested). Privileged admin credential used in memory only
  (local `read -s` helper), never stored anywhere.
- `TEMPORARY_DELETEFILES_SECURITY_DEBT = NO`;
  `P5_OR_BROADER_PROD_KEY_BLOCKER = NO` — credential blocker cleared
  ONLY; P5/broader rollout still requires a new packet.
- Flagged (pre-existing, out of scope): `diveanalyzer-dev-agent` (…0001)
  is an ACCOUNT-WIDE key with admin capabilities.

### Media backbone P4.2 — bounded production dual-write cohort COMPLETE (2026-09-09)

**Status: `P4_2_COMPLETE` (`PRODUCTION_COHORT_GREEN`).** Packet
`MEDIA_BACKBONE_P4_2_PRODUCTION_COHORT_V1` on top of canonical HEAD
`bba47b77…`. Durable audit:
`docs/audits/MEDIA_BACKBONE_P4_2_PRODUCTION_COHORT_V1.md`.

- 8-clip bounded production cohort (bounds [5, 10], target = 8; explicit
  allowlist, all `DiveAnalyser Ready` members, none PROD lineages, none
  science-referenced, none selected from scientific data). Legacy primary;
  B2 PROD additive; playback legacy-only; flags started OFF and returned
  OFF at close (rollback proven: 0 object-store activity, playback 200,
  all 10 PROD objects retained).
- Legacy: 22/22 renditions eventually READY via the normal product request
  endpoint (two 600 s iCloud export timeouts on the cold cache recovered
  through product-driven retry — legacy never waited on B2).
- B2: 8/8 PUT + full-GET SHA equality + authenticated env=prod commits +
  receipts; 167,393,364 B total; **4 new PROD lineages**
  (606653E2, C3A7A952, 0EC8DDBE, C27D4087) + 4 clips that are P3 DEV
  lineages whose prod commits content-deduped idempotently onto existing
  rows (0 duplicate rows; first production exercise of cross-environment
  content-addressed dedupe). prod DB: ledger 1→5, prod blobs 1→5,
  prod caption revisions 2→6; dev counts unchanged (10).
- Unchanged rerun of the complete allowlist: 8/8 `already_terminal`,
  0 rows / 0 bytes / 0 duplicate legacy clips. Caption parity exact_equal
  8/8; no natural mutations (caption-only mechanism stays P4 §32-proven;
  unchanged-caption guard re-proven as a no-op).
- **Real production bug found and fixed:** with the P4.1 least-privilege
  key, B2 S3 returns 403 (not 404) for HEAD on a MISSING object — the
  adapter mapped only the 404 family to "absent", stalling drives at
  REMOTE_UPLOAD_STARTED (retryable; legacy unaffected). Repair:
  fail-closed 403 disambiguation via prefix-LIST probe (absent → None,
  present/list-failure → raise); 3 adapter tests; stalled journals
  re-driven to convergence reusing staged legacy bytes (0 new
  materializations).
- Guard hardened: prod allowlist now requires 5–10 explicit UUIDs
  (REFUSE TO ARM outside; implicit readiness structurally impossible);
  backpressure keeps ONE active dual-write and records a tiny bounded
  pending marker with NO staged byte accumulation (skipped triggers
  recoverable via the bounded one-shot run mode); static no-delete/hide
  firewall tests over the whole ingestion path (delete/hide operations
  performed: 0); state machine has no destructive state.
- Privacy recheck: anonymous LIST 403 / GET 401 (canary + cohort objects).
- Security findings: P4.1's two synthetic objects are no longer in the
  bucket (pre-dates P4.2's first LIST; likely external console cleanup —
  P4.2 deleted nothing; flagged for reconciliation);
  `diveanalyzer-dev-agent` account-wide admin key still flagged
  (pre-existing). Object Lock console check still owed.
- Metrics: per-asset median 8.97 s / max 12.82 s background B2 leg
  (31–34 MB); legacy critical-path overhead 0.01–0.03 s staging copy;
  min free disk ≈ 17.9 GB. Ready album UX: no friction observed.
- Tests: mac-agent 171/171 (production venv); backend backbone 35 pass +
  1 pre-existing env-only failure (static host-path test; backend code
  untouched). `LEGACY_PRODUCTION_BEHAVIOR_MUTATION NONE`;
  `PRODUCTION_PLAYBACK_MUTATION NONE`; science untouched.

### Media backbone P4.3 — overnight storage-authority hardening COMPLETE (2026-09-10)

**Status: `P4_3_COMPLETE` / `P5_STORAGE_AUTHORITY_READY`.** Full report:
`docs/audits/MEDIA_BACKBONE_P4_3_STORAGE_AUTHORITY_HARDENING_V1.md`.
Packet `MEDIA_BACKBONE_P4_3_OVERNIGHT_STORAGE_AUTHORITY_HARDENING_V1`
(fully unattended; no human interaction; flags stayed OFF; 0 new media;
0 B2 writes/deletes). Branch `media-backbone-p4-3-storage-authority-v1`,
ff-merged into canonical (`268bfe5` → `572516f` + docs commit).

- **Diagnosis (§2 gate):** the pre-P4.3 schema could NOT represent the same
  SHA in DEV and PROD simultaneously — `media_blobs` conflated content
  identity with physical location, and the P4.2 dev-overlap cohort's four
  verified PROD replicas (901A95AF, F2A9B8CC, BB513C7F, EB4ACB9E) were not
  durably represented (deduped onto DEV rows; ledger dedupe on
  `(video_uuid, object_key)` swallowed the PROD commit events).
- **Repair (additive):** `media_blob_locations` = authoritative per-replica
  storage records (unique on replica identity and per-blob replica;
  environment + verified state); blob location columns documented
  transitional/non-authoritative; ledger uniqueness env-scoped
  (`(video_uuid, environment, object_key)`; index swap, no data rewrite);
  commit service separates content dedupe from location dedupe and rejects
  environment/bucket mismatches + conflicting-SHA location keys at two
  layers; migration `add_media_blob_locations.sql` idempotent on real
  Postgres (empty / cross-env / re-run tested).
- **Live reconciliation:** backup of the 5 backbone tables first
  (`~/backups/backbone_p4_3_before_reconciliation_20260910_001112.sql`);
  backfill 10 DEV + 5 PROD locations (0 dups); the 4 missing PROD replicas
  reconstructed by **idempotent replay of the durable P4.2 receipts**
  through `commit_verified_ingest` (fail-closed pre-checks; B2 HEAD
  byte-verified read-only). Final: 15 blobs / 19 locations (10 dev + 9
  prod, all verified) / 15 revisions / 17 captions / 19 ledger rows —
  zero duplicate logical rows; each shared SHA = 1 DEV + 1 PROD location.
- **P5 precondition proven:** `resolve_verified_location` /
  `resolve_media_revision_location` give one deterministic verified
  location per (revision, environment); `verified=false` locations are
  never playback-eligible. No P5 surface implemented.
- **Daemon singleton:** the P4.2 duplicate (`28973`, SSH-probe orphan —
  the runtime app binary is a daemon launcher, so probing it via SSH
  started a full production daemon; it never started loops) terminated
  cleanly; `daemon_lock.py` pid/lock file with stale-owner verification
  wired into full-daemon mode only; two live-deploy bugs found and fixed
  same-night (ps lstart= header suppression; locale-dependent output —
  now LC_ALL=C forced); §20 contract proven live (second instance refuses
  with `DAEMON_SINGLETON_REFUSE`, zero loop starts). Exactly one
  production agent instance.
- **Connectivity probes:** curl exit/stderr surfaced at WARNING,
  `NetworkMonitor` CA propagation repair, PID in every log line — no TLS
  authority change; the orphan's 000-loop cause is formally
  `INSUFFICIENT_EVIDENCE` (was DEBUG-invisible; future recurrences
  diagnosable in minutes).
- **Materializer timeout:** bounded configurable
  `materialization_timeout_seconds` (default 600 = current production
  behavior; [30,3600]; wired end-to-end; live value unchanged).
- **P4.1 synthetic objects:** `EXTERNAL_OR_MANUAL_REMOVAL_MOST_LIKELY`
  (project-code deletion excluded by evidence; provider lifecycle not
  fully excludable; not recreated/deleted; not a P5 blocker).
- **DEV admin key (…0001):** audit only — zero runtime references;
  production does not depend on it; recommendation: revoke in a
  maintainer-attended step. No rotation performed.
- Tests: backend backbone 52 pass; mac-agent 192/192 (production venv);
  full backend suite signature-identical to baseline (1 pre-existing
  failure + 273 pre-existing errors, byte-identical on pre-P4.3 code);
  migration/secret/media scans clean.
- Verdict recommendation: `P5_STORAGE_AUTHORITY_READY` — P5 still requires
  a new explicit supervisor packet.

### Key documents

- `docs/architecture/MEDIA_BACKBONE_CURRENT_STATE_V1.md` (P0 audit)
- `docs/architecture/MEDIA_BACKBONE_TARGET_V1.md` (interfaces/seams)
- `docs/architecture/MEDIA_INGEST_STATE_MACHINE_V1.md` (states, crash contract)
- `docs/architecture/MEDIA_BACKBONE_SECURITY_V1.md` (security + B2 EU research)
- `docs/architecture/MEDIA_BACKBONE_MIGRATION_PLAN_V1.md` (P0–P8 phases; DB-driven historical migration, NOT a Photos-library crawl)

## HURDLE identity selection V2 — GATE FAILED, confound closed (2026-09-10, identity-v2 thread)

Packet `HURDLE_TARGET_IDENTITY_V2` executed on Apple M2 (worktree
`~/.perso/diveanalyzer-identity-v2`, branch `hurdle-identity-v2`, base
`d4c0c8a`). Report:
`docs/science/HURDLE_IDENTITY_SELECTION_V2_REPORT.md`.

**A1 — the R4 confound is quantified and confirmed.** The true target was
OUTSIDE R4's top-12 candidate graph on 50.2% of primary evaluable frames
(2353 85.9%, 1040 65.8%, 2541 64.9%); recall@48 ≥ 0.88, @96 ≥ 0.985, @200
= 1.000 on every classified dive (`HURDLE_R5_STATE_SPACE_AUDIT_V1.json`).
R4 was therefore NOT valid evidence that appearance-aware association is
intrinsically insufficient.

**Full-clip GT-free inference (Phase B).** The frozen D5 recipe re-ran over
FULL production clips for all six primary dives; selector paths consume
only `R5_FULLCLIP_CANDIDATES_V1.json` (interval [0, video_end]); GT times
appear only under `gt_eval_only` metadata. Regression-tested.

**R5-A (candidate-complete sparse tracklets) — repairs one dive.** 2353
0.365 vs D5 top-1 0.005 (longest wrong 363 → 23); 2169 regresses
catastrophically (movers with dive-scale excursions exist in that clip);
no stable multi-dive configuration. **R5-B (frozen OSNet Market-1501
association) — repairs none.** Selection gate **FAILED**; no
`HURDLE_TARGET_IDENTITY_V2_FREEZE`; no repaired trajectories; V3-D0
replayed UNCHANGED on the frozen cache and reproduces the recorded
magnitudes exactly (adds per-dive baselines for 2341/2353/2541/2555).

**Appearance is vindicated as a direction (Phase E).** Frozen OSNet
(Market-1501) is discriminative on the tiny 360p divers: separation
margin 0.203 / ROC-AUC 0.902 aggregate vs ResNet50-ImageNet 0.126 / 0.837
(AUC 0.82–0.98 on all five ordinary dives, NN-retrieval ≈ 1.0). The R4
"appearance is insufficient" verdict is REFUTED at the representation
level. Measured pose-transition structure: prep–prep cos 0.89–0.97,
prep–flight 0.67–0.79 vs distractor ~0.65 — appearance verifies static
identity but cannot bridge prep→flight alone.

**HQ appearance-only (Phase F): `MIXED_HQ_APPEARANCE_GAIN`** (aggregate
margin 0.199/AUC 0.932 vs proxy 0.231/0.923; per-dive mixed; 2341
improves). All six HQ renditions sha-verified against the manifest.

**FM2: `FM2_STILL_IDENTITY_LIMITED`.** Detector remains closed
(`D5_DETECTOR_REMAINS_CLOSED`; recall@200 = 1.000 re-confirmed). **524:
`524_MAPPING_AUTHORITY_CONFLICT_CONFIRMED`** (read-only re-audit: at the
HQ thread's own claimed parameters NCC 0.24–0.32, exhaustive search caps
0.64 at unstable parameters) — 524 stays excluded. **2555** stays
`SCREEN_RECORDING_STRESS_CASE` (all instruments degrade; not promoted).

Tests: `experiments/landmark_pilot/test_hurdle_identity_v2.py` — 21/21
pass (zero failures). Host caches/weights stay outside Git with sha256
provenance committed.

### Next gate

`SUPERVISOR_REVIEW_AFTER_HURDLE_IDENTITY_SELECTION_V2`

## Media backbone P5 — auth + B2 playback canary (2026-09-10, P5 thread)

Packet `MEDIA_BACKBONE_P5_ACCELERATED_AUTH_PLAYBACK_V1` executed on top of
the P4.3 closure base (`59e9097`) and the concurrent hurdle-identity-v2
science commit (`636b0dc`, untouched). Reported P5-PRE head `8a332d3` was
NOT in canonical history (invalid object) — proceeded from fresh canonical
state without overwriting anything.

- **USER auth layer V1 (flag-gated)**: additive schema (`app_users` /
  `user_credentials` / `user_sessions` / `user_diver_access` /
  `login_attempts` / `media_playback_grants`), Argon2id passwords
  (argon2-cffi 23.1.0 pinned), opaque server-side sessions (cookie carries
  raw token, DB stores SHA-256 only), hardened cookie
  (HttpOnly/Secure/SameSite=Strict/Path=/), login/logout/me endpoints with
  uniform failures + DB-backed rate limit (5 fails / id / 15 min → 429),
  one-shot operator bootstrap CLI (getpass-only password).
- **Ownership**: `MEDIA_DIVER_LINK_ALREADY_DETERMINISTIC`
  (MediaRevision.video_uuid → dives.video_uuid UNIQUE → diver_id); central
  policy `can_user_access_media` (authenticated + exactly one trusted
  diver owner + explicit OWNER binding); IDOR-proven with synthetic users.
- **Playback grant**: `GET /api/v1/media/revisions/{id}/play` — 302 to a
  120 s presigned B2 URL (clamp [1,300]); `no-store`/`no-referrer`;
  presigned URLs never logged/stored (asserted); expired grant rejected by
  the provider live (401 after 130 s) and a fresh grant works.
- **Live proof**: one real owner (maxime, diver 1, OWNER), cohort 9/9
  verified-PROD revisions authorized (target 8), Range/seek GREEN in
  Chromium (real Chrome channel) + WebKit via Playwright; negative tests
  (unauthenticated 401, wrong-owner 404 no-Location, unknown 404,
  flags-off fail-closed); provider-failure → explicit 503, no legacy
  fallback. CORS NOT required (B2 untouched). Legacy playback healthy.
- **Future-ingest Content-Type repair** (mac-agent, no historical
  rewrite): evidence-based video MIME from ffprobe container/codec;
  dual-write flags OFF; 0 B2 writes/deletes; 0 new media ingested.
- **Flags returned OFF at closure** (rollback contract): production
  default playback remains legacy; re-activation = `.env` flip
  (`USER_AUTH_ENABLED=true`, `B2_PLAYBACK_CANARY_ENABLED=true`) + backend
  restart; schema and the provisioned owner account persist.
- Tests: backend P5 suite 21 pass (+ backbone suites 32 pass), full
  backend suite delta = 0 new failures; mac-agent on the production Mac
  182/182 (incl. 11 new Content-Type tests + 2 test-harness signature
  repairs for the additive content_type argument).
- Outstanding: Object Lock attestation pending; `diveanalyzer-dev-agent`
  admin-key cleanup debt; presign uses the P4.1 key (recorded end-state
  debt: dedicated presign-only playback key, provider-console action).

### Next gate

`SUPERVISOR_REVIEW_AFTER_MEDIA_BACKBONE_P5_AUTH_PLAYBACK_V1`

## Media backbone P6 handoff (2026-09-10)

Packet `MEDIA_BACKBONE_P6_ACCELERATED_DEFAULT_PLAYBACK_V1` on top of the
accepted P5 state (`a2f7885`). Full evidence:
`docs/audits/MEDIA_BACKBONE_P6_ACCELERATED_DEFAULT_PLAYBACK_V1.md`.

- **Dedicated playback key**: `diveanalyzer-prod-playback-v1` (…000a,
  caps exactly `readFiles`, PROD bucket only) — the backend lost the
  write-capable ingest credential entirely (credential domains separated
  and live-verified). Playback key proofs: read GREEN (206/200), write/
  delete/hide/bucket/cross-bucket DENIED. `diveanalyzer-dev-agent`
  account-wide admin key REVOKED. Object Lock attested DISABLED.
  Maintainer UI cleanup pending: revoke `…0009` (duplicate) +
  `p6-op-ephemeral` `…0008`.
- **Login rate-limit repair**: two-tier (per-IP 10/15 min + per-identifier
  20/15 min, success clears) — no more indefinite lockout via wrong-
  password bursts; brute-force still bounded.
- **Session cleanup** bounded (expired/revoked, 24 h retention) after
  login; cookie/session model unchanged and revalidated.
- **CSRF**: SameSite=Strict primary + minimal Origin validation on
  auth POSTs; cookie policy unchanged.
- **Legacy IDOR closure** (auth-enabled state): `/videos/{uuid}`,
  `/videos/check/{uuid}`, `/media/cache/{id}/play`,
  `/media/events/viewed` now require session + central OWNER
  authorization. Flags off = exact legacy behavior (emergency rollback,
  proven).
- **Authenticated legacy fallback**: B2 default (verified-PROD replica +
  grant-time provider HEAD proof) → else server-side legacy stream with
  Range; browser never receives an unauthenticated legacy URL; ambiguous
  → fail-closed; auth failures never fall back.
- **Live proofs**: default B2 grant chain (302 → 200/206), expired-
  presign refresh (401 → fresh 302 → 206), B2-failure injection →
  authenticated legacy fallback (200/206) with wrong-owner DENY during
  outage, wrong-owner DENY on play/legacy routes, Chrome + WebKit GREEN
  (metadata/play/seek, 0 page errors).
- **Cohort**: 9/9 verified-PROD owner revisions via B2 (each provider
  fetch ranged 206); DEV-only → authorized legacy fallback or fail-closed
  404.
- **Production default (owner only)**: `USER_AUTH_ENABLED=true`,
  `B2_PLAYBACK_CANARY_ENABLED=true` (final, live-verified). No public
  registration; no additional athletes; legacy fallback remains behind
  authorization. Both rollback paths (flag-level + emergency) proven.
- **Observability**: in-process playback metrics + authenticated
  `/api/v1/media/playback/metrics`; grant ledger extended with
  LEGACY_FALLBACK outcomes; no tokens/URLs/cookies in metrics or logs.
- **Ops counters**: B2_MEDIA_WRITES=0; delete/hide=0; media ingested=0;
  science untouched.
- Tests: P6 suite 30 pass + P5 suite 21 pass; full backend suite delta
  0 new failures (2 pre-existing failures / 273 pre-existing errors).
- Frontend note: the deployed SPA is the baked image
  `dive-analyser-frontend:latest` built via
  `docker build -f frontend/Dockerfile.deploy -t dive-analyser-frontend:latest frontend`
  — `docker-compose build frontend` builds a dev image and does NOT
  produce the deployed one.

### Next gate

`SUPERVISOR_REVIEW_AFTER_MEDIA_BACKBONE_P6_AUTH_PLAYBACK_V1`

## Media backbone P7 — continuous ingest + historical migration (2026-09-10, GREEN)

- **Continuous dual-write ARMED (production-normal)**: new captioned
  production clips flow legacy-first → automatic additive B2 PROD dual-write
  via the EXISTING media-job event stream (trigger reason
  `new_captioned_ingestion` — jobs created only for newly inserted dives).
  NO allowlist dependency in normal production; the 5-10 UUID cohort
  allowlist remains canary/debug-only. Historical/renovation jobs are
  structurally refused (unit-proven per reason).
- **Historical backlog isolation**: the continuous path performs no
  discovery of any kind; history is reached only by the migration engine.
- **Historical migration COMPLETE**: DB-driven inventory (agent-key endpoint,
  storage facts only) → 15 OWNER revisions: 9 already verified PROD (class A),
  6 DEV-only (class B) migrated DEV→PROD with separate bucket-scoped
  credentials, roundtrip SHA-verified (137,309,564 bytes each way); 0
  C/D/E/F, 0 retries, 0 quarantines, 0 residuals. Second pass: 0 uploads,
  0 GETs, 0 commits, 0 duplicate rows.
- **Playback convergence**: migrated revisions automatically became
  B2-backed (302 → provider 206) with zero frontend changes; wrong-owner
  404 / unauth 401 re-proven on migrated + legacy routes.
- **Rollback proofs (live)**: `B2_PLAYBACK_CANARY_ENABLED=false` → play
  route 404 + authenticated legacy playback GREEN (video 307/cache 200) +
  unauth 401; `dual_write.enabled=false` → legacy loops healthy, zero
  object-store arming. Both re-armed after proof.
- **Engine authority**: `docs/architecture/HISTORICAL_MEDIA_MIGRATION_V1.md`;
  audit: `docs/audits/MEDIA_BACKBONE_P7_ACCELERATED_CONTINUOUS_INGEST_MIGRATION_V1.md`.
- **Final state**: `USER_AUTH_ENABLED=true`, `B2_PLAYBACK_CANARY_ENABLED=true`,
  `object_store.enabled=true`, `dual_write.enabled=true`,
  `continuous_new_ingest=true`, `migration.enabled=true` (one-shot engine,
  never a daemon). PROD bucket: 16 objects / 345,568,956 bytes. Delete/hide:
  0. Science: untouched.
- **Next phase**: user onboarding / external access / legacy decommission
  preparation (P8 requires its own supervisor packet + evidence).

### Next gate

`SUPERVISOR_REVIEW_AFTER_MEDIA_BACKBONE_P8`

## Media backbone P8 — accelerated productionization (2026-09-10, GREEN)

Packet `MEDIA_BACKBONE_P8_ACCELERATED_PRODUCTIONIZATION_V1` on top of
canonical `b8e5de9`. Branch `media-backbone-p8-productionization-v1`.
Full audit: `docs/audits/MEDIA_BACKBONE_P8_ACCELERATED_PRODUCTIONIZATION_V1.md`.

- **Multi-user operator administration**: server-local CLI
  `backend/scripts/manage_user.py` (create/disable/enable/reset-password/
  bind/unbind/revoke-sessions/list — no secrets, getpass+Argon2id,
  disable & reset revoke ALL sessions). NOT the mac-agent X-API-Key
  authority; no web admin role; no public registration.
- **Security audit trail**: additive `security_audit_log` table +
  service; events for user lifecycle, session revocation, ownership
  changes, login_rate_limited. Applied to real Postgres (idempotent,
  reversible).
- **Auth metrics**: privacy-safe counters + authenticated
  `/api/v1/auth/metrics`.
- **Live production proofs** (synthetic identities, cleaned up; audit
  retained): IDOR matrix across legacy routes + B2 play (A→A allow,
  cross-user deny 404, anon 401, B→maxime 404); §44 disable live (live
  session loses access instantly, login denied); §45 password reset
  live (old session dead, old pw fails, new pw works); rate-limit
  10→429 with audit row.
- **Production defect fixed**: nginx forwarded `Host $host`
  (port-stripped), breaking backend Origin reconstruction → same-origin
  browser login 403 unless the origin was in CORS_ALLOW_ORIGINS. Fix:
  `Host $http_host` (deployed, reload-verified). No wildcard origins;
  cookie policy unchanged.
- **Playback cohort (P8-E)**: 62+ authenticated requests observed —
  100% authorized, 100% B2-selected, 0 denials / 0 unexpected fallback /
  0 provider failures / 0 presign leaks; provider ranged GET 206.
- **Continuous ingest**: armed and healthy throughout; no natural new
  clip occurred → `CONTINUOUS_NATURAL_INGEST = NOT_OBSERVED_YET` (no
  fake data; legacy decommission stays NOT_READY). Soak: single daemon,
  ledger 25/25 DB_COMMITTED, no staging accumulation.
- **Reconciliation**: 15/15 eligible OWNER revisions verified PROD
  (100%); B2 fresh inventory 16 objects / 345.6 MB, all
  content-addressed, 0 orphans. B2 delete/hide: 0.
- **External access**: LAN_ONLY (WAN probes dead, no port-forward).
  Prepared path documented (`EXTERNAL_ACCESS_V1`); verdict
  `EXTERNAL_ACCESS_PROVIDER_GATE`; ONE consolidated provider action
  defined (Cloudflare Zero-Trust route + CORS entry). Nothing opened.
- **Legacy readiness**: full dependency audit
  (`LEGACY_DECOMMISSION_PLAN_V1`); cache = still primary UI substrate;
  `/videos` = 14 GB unreferenced fallback (largest future reclaim);
  vault 13 GB = ingest source (keep). Verdict
  `LEGACY_DECOMMISSION_NOT_READY`; no deletion; no dry-run yet.
- Tests: P8 suite 10/10; P5+P6 51/51 (fixture gained the audit table);
  media_backbone 91 pass + 1 pre-existing env-only (needs /mac-agent in
  container); commit_api failures pre-existing on base HEAD in this
  container (reproduced on reverted code). mac-agent untouched.
- Flags final: `USER_AUTH_ENABLED=true`, `B2_PLAYBACK_CANARY_ENABLED=true`,
  `object_store.enabled=true`, `dual_write.enabled=true`,
  `continuous_new_ingest=true`. Science untouched. No secrets in Git.

### Next gate

`SUPERVISOR_REVIEW_AFTER_MEDIA_BACKBONE_P8`

## Media backbone P9 — production readiness + external access prep (2026-09-10, GREEN with natural-ingest PENDING)

Packet `MEDIA_BACKBONE_P9_PRODUCTION_READINESS_AND_EXTERNAL_ACCESS_V1` on
top of canonical `9da2310`. Branch
`media-backbone-p9-production-readiness-v1`. Full audit:
`docs/audits/MEDIA_BACKBONE_P9_PRODUCTION_READINESS_AND_EXTERNAL_ACCESS_V1.md`.

- **Verdicts**: `P9_PRODUCTION_READINESS_GREEN`;
  `CONTINUOUS_NATURAL_INGEST_PENDING` (no natural clip in the P8+P9
  windows; durable passive capture now deployed so the next natural clip
  closes the gate without an operator);
  `EXTERNAL_ACCESS_PROVIDER_GATE` (machine-side 100% prepared + externally
  live-tested through a temporary quick tunnel, then torn down);
  `LEGACY_DECOMMISSION_DRY_RUN_READY` with
  **LEGACY_PHYSICAL_DELETION_READY = NO**.
- **Backup/restore (P9-C)**: frozen policy
  (`docs/architecture/BACKUP_AND_RETENTION_V1.md` +
  `ops/retention_policy_v1.json`); daily 03:15 encrypted pg_dump cron live
  (AES-256-CBC+PBKDF2, readability gate, 14 daily + 8 weekly retention);
  off-host encrypted copy on the ingest Mac via a
  `restrict,from=<server>` restricted SSH key; isolated-container restore
  test PASS (14-table row reconciliation + ownership chain 15/15 +
  verified PROD locations 15/15; 73 s total).
- **Account/session cleanup (P9-D)**: the two historical synthetic
  negative accounts removed from production (audit trail retained; 0
  orphan sessions; production = exactly 1 legitimate real user).
- **External access (P9-E)**: cloudflared audit (navidrome quick tunnel =
  separate app, untouched); decision = separate named tunnel + loopback
  vhost :6091 (adminer refused); external proofs through a temporary
  quick tunnel: login/cookie flags, foreign-origin 403, unauth 401,
  wrong-owner 404, owner 302→206 with Range/seek, expired-presign
  refresh, privacy-safe errors; ONE consolidated HUMAN_PROVIDER_ACTION
  (EXTERNAL_ACCESS_V1 §7: domain zone in Cloudflare + named tunnel
  `diveanalyzer` + hostname `dive.<domain>` → HTTP localhost:6091).
- **Soak (P9-F)**: 192 ALLOWED / 16 denied-intentional / 0 provider
  failures / 0 unexpected (≥100 target exceeded); ledger 25/25
  DB_COMMITTED; staging clean; single daemon; §40 rollback revalidated
  live (B2-off → authenticated legacy fallback with Range 206).
- **Metrics durability (§41)**: durable aggregation from append-only
  tables (login_attempts / media_playback_grants / security_audit_log) on
  both metrics endpoints — restart no longer loses operational data.
- **Reconciliation (§28/§29)**: 15/15 verified-PROD (100%, 0 drift);
  B2 16 objects / 345.6 MB, 0 unexplained orphans (1 documented P4
  preflight evidence object), 0 missing.
- **Legacy dry-run (P9-G)**: `backend/scripts/legacy_dry_run.py`
  (DRY-RUN ONLY, no delete primitives, static-tested); cache 1718 files /
  890 MB (29 B2-derivable candidates); /videos 176 files / 14.28 GB ALL
  icloudpd iCloud-original cache artifacts with 0 DB references
  (rebuildable from iCloud; NOT authorized); vault 13 GB ACTIVE_REQUIRED
  with bounded-cache conditions documented; science excluded everywhere.
- **Repairs found live**: restricted-key sshd option syntax (`pty=no` →
  `restrict`); rsync `--no-times --no-perms` under the restricted key;
  backup sha-manifest filename mismatch; standalone `docker-compose`
  (no `docker compose` plugin on this host).
- Counters: B2 delete/hide 0; legacy media deleted 0; Photos ops 0;
  science untouched; no secrets in Git.
- Tests: mac-agent 248/248; backend P9 suite 10 pass (+1 env-layout skip);
  P5/P6/P8/backbone 101 pass (1 pre-existing env-only failure).

### Next gate

`SUPERVISOR_REVIEW_AFTER_MEDIA_BACKBONE_P9`

## Media backbone P10 — FULL-CORPUS historical migration (2026-09-11 overnight, FULL_RECOVERABLE_CORPUS_GREEN)

Packet `MEDIA_BACKBONE_P10_OVERNIGHT_FULL_DIVE_ANALYZER_MIGRATION_V1`,
UNATTENDED OVERNIGHT execution, on top of canonical `2fa9187` (P9).
Full audit: `docs/audits/MEDIA_BACKBONE_P10_OVERNIGHT_FULL_DIVE_ANALYZER_MIGRATION_V1.md`.
Canonical HEAD after P10: `8a50d89e2cbbdffb4d96785f534ac024dde09cf0`.

- **Corpus re-definition (the P9 gap closed)**: inventory boundary = the
  DOMAIN graph (dives.video_uuid), NOT media_revisions. Fresh counts:
  dives 2805 / distinct video_uuid 2805 (UNIQUE ⇒ 0 duplicate refs,
  0 cross-diver conflicts) / 23 divers with video / 15 revision rows = 14
  distinct identities. **2799/2805 identities resolve via
  dives.video_filename** (corpus-wide caption corroboration 2799/2799);
  6 rows are synthetic TEST fixtures with no recoverable media.
- **Result**: 2799/2799 real recoverable assets = **verified PROD bytes +
  truthful MediaRevision + resolved caption (100% of the real corpus;
  99.79% of all distinct identities)**. 60.5 GB new bytes, every upload
  full-GET roundtrip-verified; 0 B2 retries; 0 remote-SHA failures;
  0 media-only commits (0 MEDIA_VERIFIED_METADATA_PENDING); peak RAM
  719 MiB (streamed); min free disk 10.92 GiB (guard never breached).
- **Source identity/seams (additive + tested)**: domain-inventory endpoint
  (caption-free), media-only commit mode (ledger
  MEDIA_VERIFIED_METADATA_PENDING — built + tested, not needed),
  vault provenance firewall (identity mapping + export-freshness proof;
  201 of 440 vault entries accepted, rest fell through to Photos by
  design), explicit `--library` materializer fix (launchd "last opened
  library" XPC hang — root-caused via process sampling), deterministic
  G-class caption-equality identity tie-break (dive raw_caption ==
  exactly one asset description; the one ambiguous item resolved + migrated).
- **Idempotence**: second full pass = 0 uploads / 0 GETs / 0 commits /
  0 duplicate rows; canary-repair re-drive re-verified PROD via HEAD
  (dedupe 216 MB avoided).
- **Authorization**: all-diver STORAGE migration (23 divers) with
  **UserDiverAccess rows created = 0; AppUsers created = 0**; wrong-owner
  playback 404 + unauth 401 on migrated non-owner items while owner 302→206
  (storage existence != authorization).
- **B2**: 2,801 objects / 61.42 GB; 0 malformed; 0 missing verified keys;
  1 documented P4 evidence object = only orphan; **delete/hide = 0**.
  Cost ≈ $0.36/month.
- **Residuals (explicit)**: 6 synthetic test-fixture rows (permanent,
  no media exists) — decision requested for a future cleanup packet.
- **Unchanged**: CONTINUOUS_NATURAL_INGEST = PENDING (passive capture
  armed, 0 triggers); EXTERNAL_ACCESS_PROVIDER_GATE;
  LEGACY_PHYSICAL_DELETION_READY = NO (second independent replica still
  required before any physical deletion); legacy/cache/Photos deletions 0;
  science untouched.
- Durable artifacts: `/Users/Shared/services/data/media-node/p10/`
  (full-corpus-inventory.json, migration-plan.json, migration-final-summary.json,
  migration-residuals.json, migration-journals/ 2799, migration-checkpoints/).

### Next gate

`SUPERVISOR_REVIEW_AFTER_MEDIA_BACKBONE_P10` — next candidates:
P11 fixture-row cleanup decision, second independent replica decision,
external hostname action, natural-ingest evidence closure.

## Media backbone P11 — FINAL CLOSURE (2026-09-11, MEDIA_BACKBONE_V1_CLOSED_READY_FOR_PARENT_SUPERVISOR)

Packet `MEDIA_BACKBONE_P11_FINAL_CLOSURE_AND_PARENT_HANDOFF_V1`.
Final handoff: `docs/handoffs/MEDIA_BACKBONE_V1_CLOSURE_HANDOFF.md`
(self-contained; a fresh main-project supervisor thread needs no other history).

- **Fresh verification of the accepted P10 state: exact.** dives 2805 /
  distinct video_uuid 2805 / 23 divers / blobs 2800 / revisions 2800 /
  captions 2802 / PROD verified locations 2800 / DEV 10 / 1 real user.
  B2 fresh LIST: **2,801 objects / 61,416,354,980 bytes; 0 malformed keys;
  0 missing verified DB keys; 1 documented P4 evidence object (408 B) =
  the only non-media object; 0 unexplained orphans.**
- **COUNT_ACCOUNTING = RECONCILED**: 2799 real identities = 2798 × 1 blob +
  1 identity (`42D80813…`, dive 2838) with 2 retained append-only revisions
  (same Photos asset re-trimmed 2026-09-09; distinct edit fingerprints and
  durations; both blobs verified PROD) — EXPECTED_APPEND_ONLY_HISTORY.
  2800 blobs = 2785 P10-created + 15 pre-P10 (9 dual-write-canary + 6 P7
  DEV→PROD). 2800 PROD locations + 1 evidence object = 2801 B2 objects
  (byte-exact).
- **BYTE_ACCOUNTING = RECONCILED**: the reported P10 upload metric
  60,497,725,121 was a surviving-run-counter aggregation; the exact
  573,060,903-byte gap = crashed-canary PUTs 216,084,468 (journal-proven
  dedupe re-verify) + restart-counter losses 183,131,868 + 173,696,767 +
  final-run sliver 147,800. Every byte is physically present, journal-verified
  and byte-accounted: 345,568,956 + 61,070,786,024 = 61,416,354,980.
  Durable ledger: `…/p10/p11-b2-object-ledger.json` (2801 entries classified,
  totals exact, 0 unexplained).
- **Six synthetic fixture rows: RETAIN + DOCUMENT
  (SYNTHETIC_NON_MEDIA_FIXTURE)** — production rows exist, 0 caption
  revisions, 0 ledger rows, 0 backbone media, no recoverable Photos/source
  media, no real athlete media behind them; excluded transparently from
  media-backbone coverage denominators, not hidden from DB-health audits;
  no purge, no new schema field.
- **Authorization regression live**: owner migrated item 302→presigned B2;
  non-owner migrated item (diver 19) 404; unauthenticated 401 — storage
  existence != authorization.
- **Runtime**: all flags live (USER_AUTH_ENABLED, B2 playback,
  object_store.enabled, dual_write.enabled, continuous_new_ingest,
  migration.enabled); single production agent daemon (pid verified); no
  migration process running (P10 one-shot finished; staging tmp empty);
  backend cleanly recreated at P10 final deployment (RestartCount 0, healthy).
- **CONTINUOUS_NATURAL_INGEST = PENDING** (passive capture armed; no
  natural ingest observed yet — independent future observation).
- **Unchanged gates**: EXTERNAL_ACCESS_PROVIDER_GATE (owned Cloudflare
  domain/zone + hostname — human action outside this workstream);
  LEGACY_PHYSICAL_DELETION_READY = NO (dry-run ready only; second
  independent media replica RECOMMENDED before any physical deletion);
  legacy/Photos/B2 deletions = 0; B2 delete/hide ops P10+P11 = 0;
  UserDiverAccess created = 0; science mutations = NONE; secrets in Git = NO.
- Storage reconciliation live: 2507/2507 OWNER revisions
  exactly-one-verified-PROD, 0 drift (293 non-owner revisions verified via
  blob-location + B2 reconciliation).
- Tests: backend P10/commit suites 20/20; P9 suite 9 pass / 1 skipped /
  1 env-only path failure (pre-existing, unchanged).


## Perception status rebase (2026-09-11, PERCEPTION_STATUS_REBASE_V1)

Strategic evidence-synthesis rebase; observational only — zero new detector/ReID/
video-model inference, zero new labels, no protected holdout access, no Paris tuning,
no new freezes. Full report: `docs/science/PERCEPTION_STATUS_REBASE_V1.md`;
artifacts: `PERCEPTION_STATUS_SCORECARD_V1.json`, `PERCEPTION_PRIORITY_MATRIX_V1.json`.

- **Git authority:** canonical `uiux-overhaul-pro-app`; science V4 commits
  `f116558`/`ccf40b5` are on branch `hurdle-prototype-v3` and NOT reachable from
  canonical — used read-only as accepted science history (integration discrepancy
  reported, not merged).
- **Scorecard (15 recorded rows, development corpus):** 2 PASS (133, 311 STANDING),
  3 PARTIAL, 7 FAIL, 3 NOT_EVALUATED. STANDING is the only family with any
  end-to-end scientific validity (2/4 dives; 676 FM3 and 2387 takeoff still fail).
  HURDLE: proposals usable (100% floor availability), identity BLOCKING
  (top-1 0.5-51.8% except 2169), Event Logic FM2 downstream-blocked
  (`FM2_STILL_IDENTITY_LIMITED`), 524 authority conflict excluded.
- **Product prevalence:** `PRODUCT_PREVALENCE_UNKNOWN` (caption grammar has no
  approach field); documented lower bound: hurdle-mandatory codes = 156/2803 (5.6%).
  The product is unevaluated on most dives, not blocked on one subset.
- **Core Detection V1:** `NOT_STARTED` — no raw-session spotting / clip-extraction
  code exists anywhere in the repository.
- **Media backbone readiness (read-only from committed P10 state):** 2799/2799 real
  assets verified PROD (61.42 GB); only `photos_edited_rendition` tier exists —
  360p/720p are NOT durably addressable in B2 yet; the 14-dive HQ analysis source
  remains the research HQ authority.

### Decisions

```text
HURDLE_IDENTITY_HEURISTIC_RESEARCH = PAUSED
PRIMARY_NEXT_MILESTONE             = PRIORITY_CORE_DETECTION_V1
SECONDARY_PARALLEL_LINE            = TARGET_IDENTITY_V1_LEARNED (background, evaluation-only, no freeze)
HURDLE_DECISION                    = HURDLE_DEPENDS_ON_FUTURE_TARGET_IDENTITY
TRAINING_DECISION                  = LEARNED_TARGET_IDENTITY_JUSTIFIED_BUT_NOT_NEXT_PRIORITY
LABELING_DECISION                  = NEW_LABELS_LIKELY_REQUIRED (Core Detection: minimal raw-session event windows; NOT collected in this packet)
```

### Proposed roadmap

M1 CORE_DETECTION_V1 (raw-session spotting + rough clip + recall) ->
M2 TARGET_IDENTITY_V1_LEARNED -> M3 supported-family temporal pipeline + takeoff
refinement -> M4 pose/mask/biomechanics at HQ renditions.
Aligns with detect -> extract -> align -> measure -> compare -> interpret.

### Tests

`experiments/landmark_pilot/test_perception_status_rebase_v1.py` — 13/13 pass.
Aggregation script: `experiments/landmark_pilot/phase_perception_status_rebase_v1.py`
(stdlib-only, deterministic). Science authorities mutated: NO. Media backbone
mutated: NO.

### Next gate

`SUPERVISOR_REVIEW_AFTER_PERCEPTION_STATUS_REBASE_V1`

## HURDLE GT-free prototype selection V3 — GATE FAILED, seed-preference gap closed (2026-09-10, prototype-v3 thread)

Packet `HURDLE_TARGET_IDENTITY_V3` executed on Apple M2 (worktree
`~/.perso/diveanalyzer-prototype-v3`, branch `hurdle-prototype-v3`, cut at
canonical HEAD `636b0dc`; media-backbone `59e9097` verified ancestor).
Report: `docs/science/HURDLE_GT_FREE_PROTOTYPE_SELECTION_V3_REPORT.md`.

**Cache discipline held: 0 D5 frames rerun; one bounded OSNet extraction
(25,524 crops, persisted + sha-provenanced); everything else from frozen
caches.** Candidate-complete graph, R5-A/R5-B machinery, OSNet weights
reused unchanged.

**Diagnosis (the cycle's durable contribution).** (1) The correct target
prototype EXISTS in bounded GT-free candidate pools on 4/5 ordinary dives
(43-48 pure target fragments per dive; appearance-guided rollouts reach
best-in-pool 0.47-0.77 where D5 top-1 is 0.02-0.15). (2) No aggregate
GT-free scorer can pick it: excursion magnitude prefers junk movers;
appearance coherence REWARDS static structures and PENALIZES true divers
(pose gap); coverage/NULL terms are satisfied by surviving junk. (3)
Confidence does not separate the target (conf p50 0.002-0.003 = floor
junk on 1040/2353). (4) The V2 oracle gap is a seed-PREFERENCE gap, not
an association or appearance gap.

P0 (appearance-consensus clusters) collapses into one mega-cluster per
dive at the frozen 0.70 mover floor — rejected. P1 (multi-hypothesis)
demonstrated the 1040 engineering-variant repair (0.609-0.658, longest
wrong 122 -> 37) recorded as a diagnostic, not a result. P2 (dual-phase
consensus) never binds. Two frozen scorer variants both gameable.

**Freeze gate FAILED** (0/4 materially improved, 2169 not preserved by
V6's own selection) -> no `HURDLE_TARGET_IDENTITY_V3_FREEZE`, no repaired
trajectories (Phases K/L skipped per packet order), historical V3-D0
replay re-verified byte-exact. **FM2_STILL_IDENTITY_LIMITED.**
**PROTOTYPE_SELECTION_STILL_PRIMARY_BLOCKER** (residual failure is
selection preference + chain existence, NOT appearance separability -> no
trained ReID head justified this cycle). 2555 stress case kept (V6
0.0089; undecodable tail frames handled). 524 conflict re-verified
read-only. Phase S: `EVENT_LOGIC_V3_D0_FREEZE_ERRATUM_V1` — the V3-D0
freeze JSON recorded interp/vel_max_gap_s 0.5/0.5 vs executable 0.30/0.20
(executable = scientific authority; Event Logic files byte-untouched);
the historical freeze artifact is immutable — the interim in-place
metadata correction was REVERTED to the original committed bytes
(sha256 `9702f7ee…`) and the drift + replay proof live in
`docs/science/EVENT_LOGIC_V3_D0_FREEZE_ERRATUM_V1.json`.

Tests: `experiments/landmark_pilot/test_hurdle_prototype_v3.py` — 34/34
(zero failures; includes historical-freeze immutability + erratum
consistency + freeze-gate verdict recording in `V6_FINAL_V3.json`).

### Next gate

`SUPERVISOR_REVIEW_AFTER_HURDLE_PROTOTYPE_SELECTION_V3`

## HURDLE identity component & target selection V4 — percolation eliminated, 2341 hypothesis repaired, ranking still the blocker (2026-09-11, prototype-v3 thread)

Packet `HURDLE_IDENTITY_COMPONENT_AND_TARGET_SELECTION_V4` (worktree
`~/.perso/diveanalyzer-prototype-v3`, branch `hurdle-prototype-v3`, cut
at the V3 closure commit `f116558`; media-backbone untouched).

**V3 closure first (§0):** recovered all uncommitted V3 work, closed the
suite at 34/34 (gate-verdict recording repaired in `V6_FINAL_V3.json`),
committed the complete negative result as its own commit `f116558`,
pushed to canonical server + Mac bare mirror,
`HURDLE_PROTOTYPE_V3_NEGATIVE_RESULT_CLOSED`. Historical freeze
immutability restored: `EVENT_LOGIC_V3_D0_FREEZE.json` reverted to its
original committed bytes (sha `9702f7ee…`) and the metadata drift +
executable authority (0.30/0.20) + replay proof recorded in
`EVENT_LOGIC_V3_D0_FREEZE_ERRATUM_V1.json`. No executable behavior
changed.

**Cache discipline:** 0 D5 frames rerun; one bounded completion pass of
the OSNet host cache to FULL candidate-ocean coverage (348,622 → 579,709
keys; 1.0 coverage on all corpus dives; no double-embedding;
manifest `HURDLE_OSNET_EMBED_CACHE_V1` V1.1 committed, npz NOT in Git).

**Positive results.** (1) A0 mutual-kNN REJECTED (k∈{1,2,3} all collapse
— reciprocal ranking does not bound percolation on the frozen ocean).
(2) A1 bounded-degree identity graph (deg 3 + bridge margin 0.06)
ELIMINATES percolation: 136–278 components/dive, largest fraction
0.04–0.09 (was 1.0). (3) 2341 hypothesis-generation repaired with ONE
bounded mechanism (component-seeded appearance-NN rollouts): the pool
now contains a target trajectory at 0.337 pf (was 0.0/0.077); rollouts
generate excellent chains on 1040/2169/2353/2541 (0.82–0.88).

**Still the blocker (V3 diagnosis re-confirmed at component level):**
component purity is 0.10–0.42 (< 0.75 required) ->
`COMPONENT_IDENTITY_STILL_COLLAPSED`; the new frozen component scorer
AND the frozen Kinetics r2plus1d_18 action-semantic score (E3:
target 0.71–0.96 vs bystander 0.01–0.24 — decisive vs bystanders/
structures, NOT vs airborne-looking fast movers; ocean max ≈ 1.0) both
remain gameable. No automatic 2169-preservation mechanism found
(stable-wrong D5 paths are smoother+more confident than the correct
one). **Freeze gate FAILED (0/4)** -> no V4 freeze, no repaired
trajectories, no repaired-trajectory replay (historical V3-D0 replay
re-verified byte-exact). **FM2_STILL_IDENTITY_LIMITED.**
**IDENTITY_COMPONENT_CONSTRUCTION_STILL_PRIMARY_BLOCKER** (proposal
completeness ✓, hypothesis generation ✓, component purity ✗).

Tests: `experiments/landmark_pilot/test_hurdle_identity_v4.py` — 31/31
(zero failures).

### Next gate

`SUPERVISOR_REVIEW_AFTER_HURDLE_IDENTITY_V4`

## Core Detection V1 P0/P1 — PARTIAL (2026-09-11, core-detection thread)

Branch `core-detection-v1` (merge `d968ad1` canonicalized V3/V4 hurdle
history: `V3_V4_HISTORY_CANONICALIZED`). Protocol + results:
`docs/science/CORE_DETECTION_V1_P0_P1.md`, `CORE_DETECTION_V1_RESULTS.json`,
`CORE_DETECTION_V1_PROTOCOL.json`, corpus `CORE_DETECTION_V1_CORPUS.json`;
code `experiments/core_detection/` (16/16 tests).

**Corpus:** single authorized raw session `IMG_0543-7294485222.MOV`
(3892.35 s, local sha256 f7833812…, server hash timed out — size+ffprobe
identity). 13 further long sessions are iCloud-only (icloudpd container
absent on server) → corpus readiness PARTIAL; recall not currently possible
without redeploy (`candidate_sessions_pending_recall`).

**GT recovery (verifier v2):** v1 raw-NCC alignment is undiscriminating in
the static pool scene (median NCC ≈ 0.99; false peaks verified in empty
segments). v2 = temporal-derivative signature votes + offset clustering +
path-score ranking + ambiguity margin + raw block-NCC floor. 10/19 clips
RECOVERED (5 captioned DIRECT), 9 WEAK (ambiguous similar-dive clusters),
→ 10 unique primary-GT dives after overlap merge (two clips share one dive).

**Event metrics (pre-registered thresholds, no tuning):** V0 visual-only
recall 0.50 (31 FP); final visual+audio recall **0.90 = target** (9/10;
audio recovered 4 weak-splash misses) at precision 0.085 (97 FP ≈ 90/h,
mostly low-score audio blips + camera-handling at session edges) and
full-dive containment 0.0 (event_time anchors at splash peak vs clip-extent
GT; pre-registered [t−8 s, t+6 s] window). Audio fusion needed an
implementation fix (one-sided onset → positive-support robust stats,
rectified z, per-bin max, no pre-smoothing); pre-registered fusion rule
preserved. Bands frozen from frame inspection: water [0.50,0.66], board
[0.28,0.48]. Representation: `360P_SUFFICIENT_FOR_SPOTTING_WITH_CAVEATS`.

**Verdict: `CORE_DETECTION_P1_PARTIAL`** — recall target reached on one
session, but precision/containment fail the "rough clip containing the
complete dive" half; single-session corpus limits generalization. No B2 /
media-backbone / HURDLE-research mutation; no holdout/Paris access; no new
human labels; no media in Git.

### Next gate

`SUPERVISOR_REVIEW_AFTER_CORE_DETECTION_V1_P1` — decisions requested:
(a) iterate precision (audio gating / FP suppression) on top of the
audio-fused recall signal; (b) revisit rough-window anchor (event start vs
splash peak) for containment; (c) recall iCloud-only sessions to widen the
corpus before further threshold work.

## Infrastructure / App layer — COMPLETE (2026-09-12–13)

Incremental production hardening on top of the accepted P11 state.
No science authorities mutated. No B2 media writes. No backbone schema changes.

### DB connection leak fix — RESOLVED

**Root cause:** SQLAlchemy 2.0 `Session.close()` does NOT always rollback an
open transaction before returning the connection to the pool, leaving connections
in an `idle in transaction` state. With pool_size=10 + max_overflow=5, all 15
slots could be blocked, causing `POST /api/v1/dives?limit=5000` to return 499
(client timeout) and `UPDATE media_jobs` to deadlock.

**Fix (`backend/app/database.py`):** explicit `db.rollback()` in the `get_db`
finally block before `db.close()`, wrapped in a bare except to avoid masking the
original exception. Zero `idle in transaction` connections observed after fix.
Dives endpoint response time: from timeout (>30 s) to <1 s.

**In-process backbone ID cache (`backend/app/api/v1/media.py`):** the per-request
backbone JOIN (`MediaRevision JOIN MediaBlobLocation`) that maps `video_uuid →
revision_id` was running on every status poll from the Dives page. Added a module-level
`_backbone_id_cache: dict` + `threading.Lock()`. The JOIN now runs at most once per
UUID per worker restart. Cache miss result (None or revision_id) is stored so
missing-revision UUIDs are also cached and never re-queried.

### Session auth — login page and auth guard — COMPLETE

**Context:** ALL user sessions had expired (last active Sep 10–11, TTL 7 days);
no login page existed in the main app — login UI existed only inside the `P5Canary`
internal page.

**New files:**
- `frontend/src/contexts/AuthContext.tsx` — `AuthProvider` + `useAuth()` hook;
  calls `GET /api/v1/auth/me` on mount; exposes `{ user, checking, refresh }`.
- `frontend/src/pages/Login.tsx` — standalone email/password form; posts to
  `POST /api/v1/auth/login`; calls `refresh()` on success; redirects to
  `location.state.from` (the URL the AuthGuard bounced from).

**Modified:**
- `frontend/src/App.tsx` — wrapped entire tree with `<AuthProvider>` (outside
  `<SyncStatusProvider>` and `<BrowserRouter>`).
- `frontend/src/router.tsx` — added `AuthGuard` component (redirects
  unauthenticated users to `/login` with `state.from`; shows a loading spinner
  while checking); restructured `Router()` so `/login` is outside the guard and
  all other routes are inside it.
- `frontend/src/components/DiveVideoPlayer.tsx` — added auth-awareness; when
  `!authChecking && !user`, renders a "Sign in to play" overlay with a link to
  `/login` instead of the video player.

**Deployment:** rebuilt frontend Docker image with
`docker build -f frontend/Dockerfile.deploy -t dive-analyser-frontend:latest frontend`
+ `docker-compose up -d --force-recreate --no-deps frontend`.

### HTTPS migration — COMPLETE (2026-09-12)

The app was accessible over both HTTP (`:6090`) and HTTPS (`:6443`) with cookies
marked `Secure`, so HTTP sessions were silently broken. The nginx config had an
HTTP→HTTPS redirect block but it was commented out.

**`nginx/conf.d/default.conf` changes:**
- Split the single dual-protocol server block into two:
  - HTTP server (port 80): `return 301 https://$host:6443$request_uri;`
    (redirects `http://...:6090/…` → `https://...:6443/…`)
  - HTTPS server (port 443): all application proxy blocks unchanged
- Added security headers to the HTTPS server block (applied to all API and
  frontend responses):
  - `Strict-Transport-Security: max-age=31536000; includeSubDomains`
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: SAMEORIGIN`
  - `Referrer-Policy: strict-origin-when-cross-origin`
- Added `ssl_prefer_server_ciphers on` and `ssl_session_cache/timeout`.

**`.env` CORS update:** removed HTTP origins
(`http://192.168.1.57:6090`, `http://deb-serv:6090`, `http://localhost:6090`).
`CORS_ALLOW_ORIGINS` now: `https://192.168.1.57:6443,https://deb-serv:6443`.
(The `_origin_allowed` function in `auth.py` also dynamically adds both schemes
for the request's own Host, so this is belt-and-suspenders.)

**Already correct (no changes needed):**
- WebSocket: `wss://` auto-detected from `window.location.protocol === 'https:'`
  in `SyncStatusContext.tsx`.
- Cookies: already `Secure + HttpOnly + SameSite=Strict` (`AUTH_COOKIE_SECURE=true`).
- All frontend API calls: relative paths (`/api/...`), no hardcoded hosts.

**Verification:** `http://...:6090/` → 301 → `https://...:6443/` ✓;
HTTPS health 200 ✓; API 200 ✓; security headers present on all API responses ✓.

### Thumbnail fallback for B2-only dives — COMPLETE (2026-09-12)

**Gap:** 805/2805 dives have local poster cache entries (`media_cache_entries`
with `rendition='poster'`). The remaining ~2000 B2-only dives (all post-migration
originals, especially recent: Aug 2026 = 7/113 with posters) showed only the
dive-code placeholder. Backend has no ffmpeg/OpenCV (Alpine container); server-side
frame extraction is off the table.

**Fix (`frontend/src/pages/Dives.tsx`):**
- `MediaPreview` type extended: `{ posterUrl, videoThumbUrl, ready }`.
- `getPreview()` populates `videoThumbUrl` from `status.playback_url` when
  `status.poster_url` is null. The cached value is the proxy URL
  (`/api/v1/media/revisions/{id}/play`), NOT the raw B2 presigned URL — so the
  cache never goes stale (the proxy regenerates a fresh presign on each browser
  request).
- `DiveThumbnail` render: three-way fallback:
  1. `posterUrl` → `<img>` (unchanged, existing path)
  2. `videoThumbUrl` → `<video preload="metadata" muted playsInline>` with
     `onLoadedMetadata` nudging `currentTime = 0.001` to force first-frame
     display on WebKit/Chrome instead of a black placeholder.
  3. Neither → dive-code gradient placeholder (unchanged)
- The IntersectionObserver lazy-loading (`rootMargin: '200px'`) and the
  `previewRequests` in-flight deduplication map are unchanged — at most one
  status fetch per UUID, only for dives near the viewport.

**Rebuilt and redeployed** via `docker build -f Dockerfile.deploy` +
`docker-compose up -d --force-recreate --no-deps frontend`.

### "Keep me signed in" — COMPLETE (2026-09-13)

**Problem:** session TTL = 7 days (604800 s); repeated sign-ins required as
sessions expired. No "remember me" option existed.

**Backend changes:**
- `backend/app/config.py`: added `auth_session_remember_ttl_seconds: int`
  (default `AUTH_SESSION_REMEMBER_TTL_SECONDS=2592000` = 30 days).
- `backend/app/api/v1/auth.py`:
  - `LoginRequest` gains `remember_me: bool = False`.
  - `_set_session_cookie()` gains a `ttl_seconds: int | None = None` override
    parameter.
  - Login handler selects `session_ttl`:
    `remember_me=True → auth_session_remember_ttl_seconds (30 d)`,
    `remember_me=False → auth_session_ttl_seconds (7 d)`;
    passes the same TTL to both `create_session()` and `_set_session_cookie()`.

**Frontend change (`frontend/src/pages/Login.tsx`):**
- Added `rememberMe` state (default `true` — personal device).
- Added "Keep me signed in for 30 days" checkbox above the submit button.
- Posts `remember_me: boolean` in the JSON body to `POST /api/v1/auth/login`.

**Rebuilt and redeployed** frontend + backend.

### Verified live state (2026-09-13)

```
Container       Image                         Status
backend         dive-analyser-backend         Up, healthy
frontend        dive-analyser-frontend:latest Up
nginx           nginx:alpine                  Up (6090→HTTP redirect, 6443→HTTPS app)
postgres        postgres:16-alpine            Up, healthy
adminer         adminer:latest                Up

http://...:6090/    → 301 https://...:6443/
https://...:6443/   → 200 (React SPA)
/api/v1/auth/me     → 401 unauthenticated (correct)
/api/v1/dives       → 200 <1 s (was timeout)
Security headers:   HSTS / nosniff / SAMEORIGIN / Referrer-Policy present
```

### Flags unchanged
`USER_AUTH_ENABLED=true`, `B2_PLAYBACK_CANARY_ENABLED=true`,
`object_store.enabled=true`, `dual_write.enabled=true`,
`continuous_new_ingest=true`. Science: untouched. B2 delete/hide: 0.

### Next gate

No science gate. Infrastructure is in a stable, fully operational state.
Next supervisor action depends on the science roadmap:
`SUPERVISOR_REVIEW_AFTER_PERCEPTION_STATUS_REBASE_V1` (pending) /
`SUPERVISOR_REVIEW_AFTER_CORE_DETECTION_V1_P1` (pending).

## UI Simplification Program (UI-U0R — 2026-09-13)

**Status: UI_U0R GREEN (audit/rebase gate; no redesign performed).**
Durable audit: `docs/audits/UI-U0R-authoritative-source-live-contract-rebase-v1.md`
(+ `docs/audits/evidence-ui-u0r-screenshots/`, 39 desktop/mobile live captures).

- **Authoritative frontend source PROVEN:** the live app (https://192.168.1.57:6443,
  image `dive-analyser-frontend:latest` built 2026-09-12T13:03:55Z via
  `frontend/Dockerfile.deploy`) is built from THIS working tree `frontend/`
  (still uncommitted — documented build drift). Proof: deployed bundle
  sourcemap sources 44/44 byte-identical to working tree; fresh `npm run
  build` reproduces deployed bundle `index-BD0otN-g.js` byte-exactly.
- Canonical HEAD at audit start `c4c9cfc` → mechanical repair commit `165eadf`
  (vitest IntersectionObserver stub + AppleDouble cleanup; tsc/vitest/build green).
- Current routes: `/` Dashboard, `/journey`, `/analytics`, `/dives` (Library:
  "Browse attempts"), `/dives/analysis/:code`, `/media/{representatives,recall,
  p5-canary}` ("Player" nav item = P5 canary harness), `/admin`, `/sessions`,
  `/competitions` (alias rendering Journey), `/login`, no 404 fallback.
- Playback: `GET /api/v1/media/{uuid}/status` → playback_url = B2 backbone
  proxy `/api/v1/media/revisions/{id}/play` (auth-checked, 302→presigned GET
  TTL 120s, legacy-cache fallback) or legacy `/api/v1/media/cache/{id}/play`;
  native `<video>` player; prep lifecycle via `/api/v1/media/{uuid}/request`
  + 3s polling. B2/media semantics untouched by this audit.
- Library state: search/scope/filters/view in URL params (persist across
  nav/reload); selected clip + pagination + scroll NOT URL-backed (lost on
  back/reload — the main U1 fix). Prev/Next = client-side over the current
  filtered result set (backend order `dive_datetime DESC, id DESC`) — works
  live, no backend redesign needed.
- Known defects for U1/U2: no 404 route; reader not deep-linkable; `/dives`
  load error has no retry; two competing visual systems (app-* tokens vs
  legacy gray/cyan on Dashboard/Journey/Analytics/Sessions + DiveVideoPlayer
  overlays); e2e suite 34/34 broken by auth (needs auth fixture, pre-existing);
  P5Canary mislabeled "Player" and stuck on "Checking session…".
- Next gate: **authorize UI-U1/U2 — MINIMAL_IA_AND_LIBRARY_CORE_V1** (Dives.tsx
  is the Library base; supervisor decision needed on `/` = Library).
**Gate: `SUPERVISOR_REVIEW_AFTER_SUBJECT_RESOLUTION_AUDIT_V1`.**
NOTE for concurrent threads: PROJECT_STATE sections must be UNIONED when the
infrastructure thread commits (established convention, cf. `d968ad1`/`98a3528`).

## Subject Resolution V1 — DIVE_ANALYZER_SUBJECT_RESOLUTION_V1 (2026-09-13)

Packet executed on worktree branch `subject-resolution-v1` (base `c4c9cfc1…`,
repair commit `3dafd8b`, science commit this section). Companion to the V1
audit above. Two closures:

### Phase 1: DIVER_ID_19 phantom — REPAIRED (PHANTOM_DIVER_REPAIR_GREEN)

Supervisor-authorized live repair, full detail in
`docs/audits/DIVER_ID_19_PHANTOM_REPAIR_V1.md`, exact transaction in
`experiments/subject_resolution/phantom_repair_v1.sql`:
- Root cause proven: `_is_person_name()` accepted the annotation token `RIP`
  (rip entry); `resolve_diver()` auto-created `divers.id=19`.
- Parser fixed (`RIP` → reserved annotation token; all-caps names deliberately
  still accepted — production convention), 5 regression tests, **fix deployed
  and live on the production mac-agent** (service restarted, verified RIP→None,
  TOM→TOM).
- 6 rows (217, 1919, 1957, 2169, 2388, 2713) moved `diver_id 19→1` in ONE
  explicit transaction with snapshot-proven zero collateral change; pre/post
  evidence in the audit doc. `dives WHERE diver_id=19` → 0.
- `divers.id=19` documented as orphan (NOT deleted); follow-up hardening noted:
  `resolve_diver()` does not filter `active` — backend deny-list or active
  filtering is a separate decision.
- Backup guard-rail finding: daily pg-backup cron was failing since 2026-09-11
  (script lost exec bit during P4.3 work); fixed (`chmod +x`) and a fresh
  verified backup taken before mutation (`20260913T111414Z.dump.enc`, sha256
  manifest, off-host push OK).

### Phases 2–12: subject resolution science — measured, lock relocated

Report: `docs/science/DIVE_ANALYZER_SUBJECT_RESOLUTION_V1.{md,json}`.
Cohort {1040, 2169, 2341, 2353, 2541}, 100% frozen-cache reuse (0 D5 reruns,
0 embeddings, 0 training, 0 labels, 0 B2 writes; GT chains eval-only):
- **PersonTrack construction is probably no longer the main lock**: subject
  tracklet coverage 1.0 on all 5 dives; merged-track coverage
  1.0/1.0/0.894/0.995/1.0; but naive union-find merge collapses subject+distractors
  into one mega-cluster (V4 failure mode again). Junk taxonomy (Phase 5) is
  safe-by-construction for movers; junk elimination is not the bottleneck.
- **GT-free reference acquisition is the real lock**: with an oracle stable
  reference, subject-conditioned OSNet retrieval reaches GT@1
  0.689/0.873/0.707/0.788/0.859 (repairs H1a misses 2341/2541), but NO tested
  GT-free acquisition rule (longest-span, area×span, max-conf, person-size
  window, leftmost, later-displacement topology, joint ensembles, single-frame)
  separated the correct reference on 4/5 dives — only 2169 admits one (0.885).
  Verdict `REFERENCE_R0_WITHIN_CLIP = PARTIAL/ACQUISITION_FAILED`.
- **R1 cross-clip gallery REJECTED** (confirmed H1b): same-athlete cross-clip
  cos 0.64–0.81 overlaps cross-athlete 0.59–0.79 and distractor 0.6–0.8.
- Ambiguity margins p50 0.008–0.05: abstention feasible-in-principle with a
  real reference; margin calibration will need learning.
- Decisions: `OPTION_D_HYBRID` architecture CONFIRMED;
  `NEXT_LEARNING_PROBLEM = TRAIN_SUBJECT_CONDITIONED_MATCHER` + NEW bounded
  line: reference-acquisition signal study (dive-phase temporal priors,
  board-occupancy topology, or learned stable-reference scorer; LOSO-by-dive,
  no random frame splits). Protocol NOT changed mid-packet per supervisor
  directive; the open problem is reported honestly.

Tests: 33/33 (20 metadata incl. 5 phantom-repair regressions + 13 audit).
Server temp cleanup `/tmp/subject_resolution_v1/*` pending → done this cycle.

**Gate: `SUPERVISOR_REVIEW_AFTER_SUBJECT_RESOLUTION_V1`.**
NOTE for concurrent threads: PROJECT_STATE sections must be UNIONED when the
infrastructure thread commits (established convention, cf. `d968ad1`/`98a3528`).

## Subject Reference Acquisition V2 — DIVE_ANALYZER_SUBJECT_REFERENCE_ACQUISITION_V2 (2026-09-13)

Packet executed on worktree branch `subject-reference-acquisition-v2`
(base = integrated canonical `uiux-overhaul-pro-app` @ d4c3f29 = V1
reconciliation `a0e09d2` + DIVER_ID_19_HARDENING_V2 `d4c3f29`).

### Phase 0 — canonical reconciliation + hardening

- V1 (`3dafd8b` + `1a656c7`) merged into canonical `uiux-overhaul-pro-app`
  (merge `a0e09d2`, clean temporary integration worktree; concurrent dirty
  main worktree + staged science deletions preserved untouched; UI-U0R
  sections unioned).
- `PHANTOM_DIVER_HARDENING_GREEN`: diver 19 retired generically — live DB
  `active=false` (snapshot-proven, zero collateral), `resolve_diver()`
  requires `active` and refuses to resurrect retired names (no RIP-specific
  branch; production container redeployed and verified live: RIP -> None,
  TOM/PAUL/FANNY/SARA/MAT -> active rows). Tests 9/9 divers + full-suite
  failure set identical to pristine. `docs/audits/DIVER_ID_19_HARDENING_V2.md`.

### Science verdict (5-dive HURDLE multi-person cohort; frozen caches only)

- `EDITED_CLIP_TEMPORAL_STRUCTURE_STRONG` (action inside clip body in 5/5,
  τ_water 0.29–0.57; pre/post padding 0.24–0.54τ / 0.43–0.71τ; subject
  visible+stable pre-takeoff 5/5) — but NOT discriminative: other persons do
  not occupy reliably different temporal regions.
- `BOARD_TOPOLOGY_WEAK` (coarse water region usable as weak prior; specific
  apparatus region NOT separable from generic static clusters).
- `A0_CLIP_RELATIVE_ACTION_OWNERSHIP` and `A1_APPARATUS_TO_WATER` (the two
  allowed no-training formulations, fixed a priori constants, flow-compensated,
  GT-free stripped store): `REFERENCE_SUBJECT_CORRECT 0/5 dives` for both.
  Best subject reference ranks 2–14 (A1, 4/5 dives) — real but insufficient
  ranking signal. Bounded stable-anchor→departure continuation diagnostic
  also failed.
- Downstream frozen matcher replay with V2 references: GT@1 ≈ 0 (acquisition
  failure is not hidden by the matcher). Oracle stable-ref ceiling unchanged
  (0.689/0.873/0.707/0.788/0.859).
- `ABSTENTION_NOT_INFORMATIVE` (margin thresholds remove nothing catastrophic;
  top-1 errors are confident wrong picks).
- Multi-person cohort remains 5 HURDLE dives only (STANDING dives lack
  per-frame subject GT + multi-person frozen D5 caches; new D5 inference was
  prohibited this packet). Cross-family generalization UNTESTABLE this cycle.

### Decision

```text
LEARNING_DECISION = NO_TRAINING_YET
DATA_SUFFICIENCY  = DATA_TOO_SMALL_FOR_LEARNING
CURRENT TRUE BLOCKER = GT-free subject reference acquisition (unchanged from V1)
```

Recommended next: widen the multi-person cohort (bounded D5-inference packet
for STANDING/ARMSTAND) THEN `TRAIN_REFERENCE_ACQUISITION_SCORER_NEXT`
(LOSO-by-dive, labels from frozen GT chains). Do NOT train a subject-
conditioned matcher yet.

Resources: 0 D5 inference, 0 embeddings, 0 training, 0 labels, 0 B2 reads/
writes, no holdout/Paris/524/2555 science use (2555 not even loaded).
Tests: 11/11 V2 + 20/20 metadata + 13/13 audit; zero failures.

**Gate: `SUPERVISOR_REVIEW_AFTER_SUBJECT_REFERENCE_ACQUISITION_V2`.**
NOTE for concurrent threads: PROJECT_STATE sections must be UNIONED when the
infrastructure thread commits (established convention, cf. `d968ad1`/`98a3528`).

### UI-U1/U2 — MINIMAL_IA_AND_LIBRARY_CORE_V1 (2026-09-13)

**Status: UI_U1U2 GREEN (first CLIP_FIRST product gate).**
Durable audit: `docs/audits/UI-U1U2-minimal-ia-library-core-v1.md`
(+ `docs/audits/evidence-ui-u1u2-screenshots/`, 14 desktop/mobile/state captures).

- **Concurrent ownership resolved:** the infra thread's completed, deployed
  session-auth/HTTPS/B2-thumbnail work was durably committed as a
  path-limited attribution commit `0133386c` (content md5-verified unchanged;
  science-thread staged deletions/untracked experiments untouched). The UI
  task worktree `ui-u1u2-library-core-v1` is based on it — the worktree now
  contains the true authoritative frontend for the first time.
- **Library is the product home:** `/` → redirect to `/dives` (query
  preserved); `/dashboard` renders the Dashboard secondarily; nav is now
  PRIMARY=Library, SECONDARY=Overview/Journey/Analytics/Representatives/
  Sessions, OPERATIONS=collapsed disclosure (Media recall, System);
  P5Canary and Competitions hidden from nav (routes preserved); real 404
  page with "Back to Library".
- **Selected clip is URL-addressable:** `/dives?...&clip=<attempt-id>`
  (stable DB id, not media UUID). Reader is derived from the URL: open=PUSH,
  Prev/Next=REPLACE, close=REPLACE, browser Back closes the reader before
  leaving the Library. Reload reopens the clip; invalid/stale clip ids fail
  safely. Filter changes keep REPLACE semantics and never reset because of
  the clip param.
- **Context restoration proven live:** pagination depth survives the review
  loop; scroll restored exactly (desktop 4000→4000, mobile 2500→2500);
  reader focus moves into the dialog on mount (required so the browser does
  not scroll the still-focused card back into view on close).
- **Library reliability:** distinct empty state with Clear filters;
  retryable error with working Retry.
- **E2E auth foundation:** global-setup login fixture via the real
  `/api/v1/auth/login` (runtime env credentials only, storageState
  gitignored); legacy 34/34-failing suite repaired → **83 passed / 1
  skipped / 0 failed** across desktop+mobile projects; new
  `e2e/tests/library.spec.ts` covers packet Tests A–F. Unit/component tests
  61/61 (was 44). typecheck + production build green; lint still
  NOT_CONFIGURED (pre-existing).
- Gate integration: task branch merged at `75fca59` (canonical
  `uiux-overhaul-pro-app`); canonical has since advanced with concurrent
  science merges (`f00dffd7`) preserving this gate's frontend content.
  Deployed live bundle `index-Dt1jwy4N.js` verified byte-identical to Git.
- Next gate: **UI-U3 — CLIP_VIEWER_CORE_V1** (reader redesign; the reader
  implementation itself was intentionally not redesigned here).

### UI-U3 — CLIP_VIEWER_CORE_V1 (2026-09-13)

**Status: UI_U3_GREEN (clip review is now a real review instrument).**
Durable audit: `docs/audits/UI-U3-clip-viewer-core-v1.md`
(+ `docs/audits/evidence-ui-u3-screenshots/`, 11 desktop/mobile/state captures).

- **Viewer architecture:** the U0R-era side-sheet reader is replaced by a
  full-viewport review surface (`components/clip-viewer/`:
  ClipViewer, ClipViewerNavigation, ClipMetadataSummary, ClipDetails) —
  video-first hierarchy per the U3 packet; Library stays mounted underneath
  and the selected clip stays URL-authoritative (`clip=<attempt-id>`).
  Shared attempt presentation extracted to `utils/attemptPresentation.ts`;
  thumbnail preview cache extracted to `utils/mediaPreview.ts` (also used for
  bounded adjacent-clip prefetch). `DiveVideoPlayer` gained an optional
  `playbackRate` prop and its overlays moved from legacy gray/cyan to the
  `--app-*` token system (media lifecycle semantics unchanged).
- **Frozen U1/U2 contract preserved:** open=PUSH, Prev/Next=REPLACE,
  close/Escape=REPLACE, browser Back closes the viewer first, reload
  reopens, pagination depth + exact scroll restoration intact; N/TOTAL
  reflects the current filtered result set with boundary disabling and no
  wrap-around. Clean clip-to-clip transitions via player remount
  (`key=attempt.id`) — no stale metadata.
- **Review controls:** playback-rate control (0.25×–2×, default 1×,
  labelled select) persisted for the mounted Library session; bounded
  keyboard model (Escape close; Shift+←/→ Previous/Next guarded against
  typing targets; Space play/pause only off interactive controls; plain
  arrows left to native seek). Focus returns to the originating Library
  card on close (`data-attempt-id`).
- **Progressive disclosure:** Details collapsed by default (secondary
  metadata incl. raw caption); Analysis stays a secondary link that
  round-trips via browser Back to the selected clip. No new metrics, no
  implementation identifiers exposed; no new mutation capabilities.
- **Defect found+fixed during validation:** Details panel was permanently
  visible because Tailwind's `grid` class overrode the `hidden` attribute
  (utility display beats UA display); fixed with an explicit grid/hidden
  class swap.
- **Tests:** vitest **85/85** (was 61); typecheck + production build green;
  new `e2e/tests/clipViewer.spec.ts` (15 passed / 1 mobile-keyboard skip)
  covering viewer-open, playback/rate/seek, rapid review (history flat),
  keyboard contract, Back-context, reload deep link, Analysis round-trip,
  390px mobile (no horizontal overflow), failed-media state via route
  interception only; full authenticated suite 97–98 passed / 0 persistent
  failures (two documented load-sensitive legacy tests pass on isolated
  re-run, unchanged from U1/U2). E2E ran against a local production preview
  (`vite preview` :4173, HTTPS, `/api` proxied to the live backend — preview
  proxy/HTTPS support added to `vite.config.ts`); credentials runtime-env
  only (stored U1/U2 session had been revoked server-side; a fresh real
  `/api/v1/auth/login` was performed).
- Performance (preview build, live backend): clip open→playable ~1.2s;
  Next→playable 1.1–1.8s over consecutive ready clips.
- Canonical integration: server-side merge `c0a5ae8` (task branch
  `ui-u3-clip-viewer-core-v1` @ `0f08b52`) over the concurrently advanced
  `4f01003` (science Subject Candidate Quality V3; no frontend overlap);
  frontend content byte-identical to the task branch; post-merge tsc /
  vitest 85/85 / build green. Deployed frontend bundle **`index-CYly4foH.js`**
  (image `dc534c142c3b`), deployed sourcemap sources byte-identical to Git
  (10/10 key files); live production E2E **98 passed / 2 skipped / 0
  failed**; live captures added to the evidence dir (16 total).
- Next gate: **UI-U4/U5 — RELIABILITY_MOBILE_ACCESSIBILITY_V1** (player
  status-poll terminalization, indefinite spinner, shared retry, focus-trap/
  WCAG hardening, reduced-motion, 200% zoom, broader mobile reliability).
NOTE for concurrent threads: PROJECT_STATE sections must be UNIONED when
integrating (established convention).

### UI-U4/U5 — RELIABILITY_MOBILE_ACCESSIBILITY_V1 (2026-09-13)

**Status: UI_U4U5 GREEN (the review loop is now operationally trustworthy).**
Durable audit: `docs/audits/UI-U4U5-reliability-mobile-accessibility-v1.md`
(+ `docs/audits/evidence-ui-u4u5-screenshots/`, 12 state captures).

- **Media transport-failure policy (frontend-only; backend lifecycle
  untouched):** `DiveVideoPlayer` rewritten around an explicit phase
  machine (checking/ready/preparing/prepare-failed/not-cached/
  transport-failed). Initial status lookup: 3 bounded automatic retries,
  then an actionable `role=alert` "Retry status check" — no endless
  spinner; a failed status GET never POSTs a prepare request. Active
  preparation polling: transient failures preserve the last known
  authoritative state presented honestly as "transcoding — connection
  interrupted" (STALE_OR_CACHED); at 5 consecutive failures the automatic
  loop stops and "Check status again" appears; recovery clears stale
  framing. Long legitimate preparations become "Still preparing this
  clip" + "Check status now" after 90s (never marked failed, no invented
  progress). Decode failure ("Video could not be loaded") is now an
  accessible alert with an in-place "Try again" reload — no new media
  jobs. Prepare/Retry-prepare remain explicit and duplicate-guarded.
- **Viewer modal contract:** background (sidebar, mobile nav, mounted
  Library) made `inert` while the viewer is open via the new
  `utils/a11y.tsx` primitives (`inertExcept`, `trapTabKey`,
  `VisuallyHidden`); Tab/Shift+Tab cycle inside the dialog; close returns
  focus to the originating card with a search-input fallback when the
  card no longer exists. Frozen U3 keyboard/URL/history contracts
  preserved verbatim (unit + E2E re-proven).
- **Core accessibility:** skip-to-main-content link (first focusable,
  visible on focus, desktop+mobile); `main#main-content` landmark exactly
  once; Library loading/empty use `role=status`, errors `role=alert`;
  player states use status/alert semantics with announcement dedup (no
  poll spam); reduced motion enforced + E2E-asserted (spinner static,
  state text informative); non-color state signals (icon+text) on core
  surfaces; touch targets unchanged ≥44px.
- **Mobile/reflow:** 390×844 loop green; NEW 320px narrow reflow green
  (scrollWidth ≤320, all critical controls reachable); landscape 844×390
  green; 200% zoom validated via 640×400 equivalent reflow.
- **E2E identity isolation:** the single production user IS the operator
  identity (PERSONAL_OPERATOR_IDENTITY); the existing storageState
  (session 147, remember_me, exp 2026-10-13) was reused for ALL U4/U5
  validation — ZERO logins performed, zero session revocations; no auth
  semantics changed. Upstream recommendation: provision a dedicated E2E
  user before session 147 expires.
- **Automated a11y:** `@axe-core/playwright@4.13.0` (pinned, dev-only,
  lockfile committed): 0 critical / 0 serious on Library, Viewer-ready,
  Viewer-error, mobile-390 Viewer. Manual keyboard/zoom/reflow pass done;
  screen reader NOT_MANUALLY_SCREEN_READER_TESTED.
- **Tests:** vitest **110/110** (was 85; +25); new
  `e2e/tests/reliabilityAccessibility.spec.ts` 22 passed/2 skipped
  (transport-failure D/E/F/F2, library-retry G, focus containment C,
  keyboard loop B, reduced motion H, 320 J, landscape K, axe L/L2); full
  authenticated suite 120 passed/4 skipped/0 failed on preview AND 124
  passed/4 skipped/0 failed against production post-deploy; typecheck +
  build green; lint still NOT_CONFIGURED (pre-existing).
- **Deployment:** frontend-only rebuild from canonical tree; live bundle
  **`index-CbYUMwwV.js`**, deployed sourcemaps byte-identical to Git
  (11/11 key files); live captures added (4).
- Next gate: **UI-U6 — OBSOLETE_ROUTE_AND_VISUAL_SYSTEM_CLEANUP_V1** (COMPLETE, see below).
NOTE for concurrent threads: PROJECT_STATE sections must be UNIONED when
integrating (established convention).

### UI-U6 — OBSOLETE_ROUTE_AND_VISUAL_SYSTEM_CLEANUP_V1 (2026-09-19)

**Status: UI_U6 GREEN (subtractive cleanup; core review loop untouched).**
Durable audit: `docs/audits/UI-U6-obsolete-route-visual-system-cleanup-v1.md`
(+ `docs/audits/evidence-ui-u6-screenshots/`, 28 before/after captures at 1440px + 390px).

- **Route cleanup:** `/competitions` no longer renders Journey inline — it is
  now a query-preserving compatibility redirect (`/competitions?scope=all`
  → `/journey?scope=all`, unit + live-production E2E proven). No normal-nav
  entry, no duplicate component ownership. `/media/p5-canary` audited
  **OPERATIONALLY_USED** (sole consumer of the gated B2 canary endpoint
  `GET /api/v1/media/playback/canary/revisions`; standing diagnostic harness in the P5/P6 media-backbone
  audits) — kept reachable and hidden, documented as the
  operational/debug route.
- **Navigation/breadcrumbs:** routeLabels dropped the obsolete alias + the
  fake media parent; new exported breadcrumbTrail() maps paths to
  user-visible IA (deep analysis →s Library plus code-analysis crumb;
  media routes →s single crumb, no dead hierarchy). Fake in-component
  breadcrumb removed from RecentProgress. Hierarchy unchanged
  (Library-first).
- **Visual consolidation:** Dashboard/Journey/JourneyNarrative/Analytics/
  Sessions/SessionDetail/RecentProgress/AvoidedDives/SyncStatus/
  MentalBlockIndicator/SyncNotifications/SyncErrorHandler/MilestoneNotifier/
  SessionDirectionIndicator/Admin migrated from the legacy gray/cyan page
  themes to app tokens (neutral/info →s tokens, decorative
  cyan/blue/purple/teal →s accent, gradients →s solid, dead
  CTA/confetti/duplicate-chart/fake-breadcrumb removed). Success/warning/
  error treatments and true data-series colors kept as justified semantics.
  No secondary-page features added; charts, player, media semantics
  untouched.
- **Dead removal (proven):** DiveStory.tsx, EmotionalStateCapture.tsx,
  styles/sync.css, App.css, the gray/cyan index.css shim, the unused
  diving Tailwind palette, dead animate-in classes. Net **+547/-1233
  lines** across 26 files.
- **Tests:** tsc green; vitest **113/113** (was 110; +redirect, +query,
  +breadcrumb table); build green; preview E2E **120 passed/4 skipped/0
  failed** and production E2E **120 passed/4 skipped/0 failed**
  (desktop 62 + mobile 58; axe L/L2 0 critical/0 serious both runs); lint
  still NOT_CONFIGURED (pre-existing).
- **Deployment:** frontend-only rebuild from canonical tree; live bundle
  **`index-CHTyUqYq.js`** + `index-B_p-ckMH.css` (JS -1,559 B, CSS -28%; no new runtime
  deps), deployed sources byte-identical to Git (10/10 key JS files via
  sourcemap + md5 vs canonical-tree build). Backend/auth/DB/B2 untouched.
  Stored localhost-scoped session 147 reused for all runs — zero logins,
  zero revocations; dedicated E2E identity debt remains.
- Next gate: **UI-U7 — ANALYSIS_PROGRESSIVE_DISCLOSURE_V1**.
NOTE for concurrent threads: PROJECT_STATE sections must be UNIONED when
integrating (established convention).

### UI-U7 — ANALYSIS_PROGRESSIVE_DISCLOSURE_V1 (2026-09-19)

**Status: UI_U7 GREEN. Analysis is a secondary inspection surface attached to
clip review (calm first screen, authoritative data only, exact return).**
Durable audit: `docs/audits/UI-U7-analysis-progressive-disclosure-v1.md`
(+ `docs/audits/evidence-ui-u7-screenshots/`, 8 captures: viewer, first
screen 1440/390/320, progression open, comparison, unavailable, retry).

- **Route/context contract:** Viewer entry
  `/dives/analysis/:code?attempt=<id>` + `state.returnTo` (presentation-only
  context, never computation). Back-to-clip restores the exact Viewer
  (returnTo, else `/dives?clip=<id>`); direct code-only URLs fall back to
  `/dives?q=<CODE>`; invalid `attempt=` stays unresolved and can never claim
  a clip; code switches strip `attempt`; drawer no longer auto-opens.
- **Grain model:** all aggregates DIVE_CODE_AGGREGATE under active filters
  (deterministic layer B); personal-values = ATTEMPT values in code scope
  (heuristic v1, caveats kept); representatives = media-authority ATTEMPT
  selections. No per-attempt science exists (stub/perception firewall
  untouched); no UNKNOWN_AUTHORITY output user-facing; scope labeled
  everywhere ("all attempts" vs "this attempt").
- **First screen:** Back control, scope header, selected-attempt context,
  4-figure key summary (Attempts/Median/Consistency/Trend), What-changed
  insights. Collapsed `AnalysisSection` units (unmounted until opened):
  Filters, Progression, Comparison & history, Phases, Attempts, plus
  Representatives / Personal priority. Sticky bar + observability footer
  removed from user UI. Transport (loading/error+read-only Retry) separated
  from capability states (available/partial/unavailable).
- **Viewer round-trip:** Viewer→Analysis→Back proven same attempt +
  Library context (unit + live E2E, incl. browser Back).
- **Tests:** tsc green; vitest **126/126** (was 113); build green;
  preview E2E **142 passed/4 skipped/0 failed** (desktop+mobile, 22 new
  analysis specs); production live **52 passed/0 failed**; axe 0
  critical/0 serious on tested U7 surfaces (one nested-interactive repair in
  the chart svg role). Lint still NOT_CONFIGURED (pre-existing).
- **Production bundle:** **`index-BQ0tlWdF.js`** + `index-A_H9YTui.css`
  (JS +0.18%, CSS −1%, no new deps), frontend-only rebuild from the
  committed canonical tree, deployed sources byte-identical to Git.
  Stored session 147 reused — zero logins; dedicated E2E identity debt
  remains (expires 2026-10-13).
- Next gate: **UI-U8 — FINAL_USABILITY_PERFORMANCE_REGRESSION_CLOSURE_V1**
  (no redesign: usability closure, dead-UI sweep, E2E identity, manual SR
  pass if available, PRODUCT_SUCCESS_TEST).
NOTE for concurrent threads: PROJECT_STATE sections must be UNIONED when
integrating (established convention).

### UI-U8 — FINAL_USABILITY_PERFORMANCE_REGRESSION_CLOSURE_V1 (2026-09-19)

**Status: UI_U8 GREEN — CLOSED (2026-09-20 addendum: operator
provisioned `e2e-regression@local` and full production E2E is green under
it; pre-resolution BLOCKED history preserved in the audit).**
Durable audit: `docs/audits/UI-U8-final-usability-performance-regression-closure-v1.md`
(+ `docs/audits/evidence-ui-u8-final/`, 10 captures).
Start-here architecture doc (new): `docs/ui/UI_SIMPLIFICATION_V1_FINAL.md`
(final IA, route map, Library/Viewer/Analysis contracts,
reliability/mobile/a11y contracts, visual authority, ownership,
deployment freeze, test strategy).

- **Authority:** base = accepted U7 HEAD `6218149`; no drift, no
  concurrent product regression. Task `cef0c16` → code-merge `1dd8045`
  (deployment source); docs-merge `03aa751`; final canonical HEAD
  `f571d830952f9279c7c3427910ab0ef433f727f6` (this line recorded
  post-merge; all merges after `1dd8045` are docs-only, frontend tree
  identical to the deployment source).
  Deployed from committed canonical source only (frontend-only rebuild);
  live bundle **`index-zrC4-UyN.js`**
  (md5 `138abc98420a2779f1c650231da43b35`) + `index-A_H9YTui.css`
  (md5 `2815236eb28049fc8187361467e84d3e`),
  md5-identical to the canonical-tree build, sourcemaps byte-identical
  to Git (8/8 key files). Prior U7 bundle `index-BQ0tlWdF.js` was
  verified consistent at preflight.
- **Contracts:** all U1–U7 contracts re-proven (tsc clean, vitest
  **126/126**, desktop E2E 71+19 rerun green, mobile **69/4skip/0fail**,
  axe 0 critical/0 serious). Clip URL/history (`clip=<attempt-id>`,
  PUSH open / REPLACE nav / exact Back), viewer, keyboard, reliability
  phases, Analysis grain (`?attempt=` presentation-only), mobile
  390/320/landscape, 200% reflow — all preserved.
- **Bounded repairs (3):** SessionDetail modal gained the canonical
  focus contract (inertExcept+trapTabKey, focus return; media semantics
  untouched — proven by probe); Journey dead emotional-state teaser
  removed (11 lines; capability deleted in U6); axe `landmark-unique`
  moderate repaired (redundant inner region role dropped; verified
  absent). AttemptDrawer classified JUSTIFIED_SECONDARY_PLAYER (kept).
- **Product success:** NEW_USER / RAPID_REVIEW / MOBILE /
  ERROR_RECOVERY / KEYBOARD_ONLY / ANALYSIS_ROUND_TRIP — all PASS
  (heuristic + automated evidence; no real user study). Rapid review:
  14 moves, 0 wrong-target, history +0 across REPLACE nav, Next≈510ms
  (no regression vs U3/U4 baseline). Scroll 3568→3568 exact.
- **E2E identity (CLOSED 2026-09-20):** dedicated `e2e-regression@local`
  (user_id=13, OWNER diver 1, no admin role) provisioned by the operator
  via `manage_user.py create-user`. Isolation proven: `user_id=1` keeps
  `live_sessions=1` before/after every run (zero Maxime logins, zero
  revocations).   Full preview suite 146 effective green + full production suite (142
  passed / 4 skipped / 0 failed) under the dedicated identity; no shared
  personal session remains in any E2E path. Credentials in run-time env
  only, never in Git. Also fixed one test-data drift (`analysis.spec.ts`
  103B-first assumption → generic code pattern; test-only, bundle
  unaffected). Full detail in audit §17.
- **Deployment freeze:** compose frontend has no build section — the
  frozen procedure (explicit Dockerfile.deploy build + frontend-only
  recreate + bundle/sourcemap verification) is now durable in the
  start-here doc. Mirror `mac-mirror` synced; server→mirror SSH
  mechanically repaired with the already-authorized agent key
  (IdentitiesOnly; no new access). Stale `:4173` preview stopped;
  dormant UI worktrees removed after no-unmerged-commits proof.
- **Program status: UI_SIMPLIFICATION_PROGRAM CLOSED_GREEN.**
  All success paths PASS; remaining intentional debt is non-core
  (unconfigured lint, no manual SR pass). Final canonical HEAD recorded
  below; E2E no longer depends on the personal session.
- **U8R normalization (2026-09-20):** full preview E2E from fresh
  canonical HEAD **142 passed / 4 skipped / 0 failed** under the
  dedicated identity (all six former drift failures green in-run; axe
  0 critical / 0 serious); production bundle unchanged and
  source-identical (no prod rerun required); operator session valid
  before/after. No product code changed. Detail: audit §18.
NOTE for concurrent threads: PROJECT_STATE sections must be UNIONED when
integrating (established convention).

## Subject Resolution Cohort Expansion V1 — DIVE_ANALYZER_SUBJECT_RESOLUTION_COHORT_EXPANSION_V1 (2026-09-13)

Packet executed on worktree branch `subject-resolution-cohort-expansion-v1`
(base = canonical `uiux-overhaul-pro-app` @ `7289037`, the accepted V2 integration;
local stale `uiux-overhaul-pro-app` pointer at `c4c9cfc` noted, server is authority).

### Purpose
Break the single-family HURDLE evaluation ceiling: build a frozen, multi-family
DEVELOPMENT cohort for Subject Resolution experiments (cache materialization +
GT audit only; no training, no tuning, no new labels).

### Cohort result (primary DEVELOPMENT cohort: 9 dives, 2 families)
- HURDLE (5): 1040, 2169, 2341, 2353, 2541 — unchanged, FULL_SUBJECT_GT
  (target_chains_v1), full-candidate + OSNet caches from V1.
- STANDING (4, NEW): 133, 311, 676, 2387 — frozen multi-person D5 full-candidate
  caches materialized this packet (`runs/subject_resolution/
  R5_FULLCLIP_CANDIDATES_COHORT_V1.json`, GT-free schema identical to
  R5_FULLCLIP_CANDIDATES_V1) + OSNet appearance cache
  (`osnet_emb_cohort_v1.npz`, 144,729 crops, frozen recipe) → full parity with
  HURDLE cache authority.
- ARMSTAND (2661/2680): NOT materialized (proxies absent from the media set);
  8/6 human bbox anchors exist. NOT_READY.
- Excluded: 524 (AUTHORITY_CONFLICT), 2555 (SCREEN_RECORDING_STRESS, not
  loaded), 2625 (no takeoff GT), INTERNAL_EVAL dives, Paris, holdout.

### Frozen D5 verification (cache materialization only)
Same frozen D5-A (sha 82b420c4…), conf 0.001 / NMS 0.45 / imgsz 640 / cap 200 /
MPS / sequential PTS read. Proxy SHAs verified against frozen
STANDING_TRAJ_CACHE_V2 before inference. Determinism: bounded 133 re-run
reproduced 0/178 differing frames. Cross-check: per-frame best candidate
matches STANDING_TRAJ_CACHE_V2 within 0.02 on ALL comparable frames
(0 mismatches in 104/358/181/667) — frozen D5 behaves well on STANDING.
Peak RAM 0.6 GB, strictly sequential, caffeinate.

### Subject-GT audit (no self-labeling)
- STANDING human authority = sparse event-frame bbox anchors only
  (133:3, 311:4, 676:9, 2387:3 — HUMAN_REVIEWED, DEVELOPMENT_DESIGN + D4/D5
  mining batches). ARMSTAND: 2661:8, 2680:6.
- Deterministic geometry-only continuation from anchors tested and FAILED
  defensibility: multi-anchor chains disagree (676: 49 conflicting frames of
  148 covered at 0.8s spacing; 133/2387/311: zero consistent overlap);
  walker survival median 0.73s (p25 0.17s). Forbidden pattern (human takeoff
  time + D5 nearest person) explicitly rejected. No synthetic GT.
- Verdicts: STANDING/ARMSTAND = SUBJECT_GT_INSUFFICIENT;
  HURDLE = SUBJECT_GT_ALREADY_SUFFICIENT.

### V2 cross-family replay (bounded, frozen A0/A1 unchanged)
A0/A1 top-1 is NOT the subject on ALL 4 STANDING dives (anchor-verified);
best anchor-consistent ranks 3–89; top-20 anchor-subject availability
133 yes/yes, 311 no/no, 676 yes/yes, 2387 yes/no.
**V2 failure REPRODUCES OUTSIDE HURDLE** — GT-free reference acquisition is
generically hard, not HURDLE-unique. No new rules derived, nothing tuned.

### Level A/B distinction + minimum GT plan
Level A (reference correctness) becomes evaluable on STANDING with sparse
identity anchors at ~0.5s spacing over [0, wc+0.5s] (derived from measured
walker survival, not assumed): 133→7, 311→31, 676→11, 2387→12 units.
Level B (framewise trajectory) requires per-frame chain authority — NOT
derivable from existing annotations. Plan (no labels collected):
`docs/science/SUBJECT_GT_MINIMUM_ANNOTATION_PLAN_V1.md`.

### Decisions
```text
LEARNING_GATE   = COHORT_EXPANSION_REQUIRES_MINIMAL_HUMAN_GT
SCIENCE_DECISION = COLLECT_MINIMAL_SUBJECT_GT_NEXT
```
Training remains NOT executed. HURDLE-only training stays forbidden; the
Level-A anchor plan is the cheapest unlock to a genuine ≥2-family learned
experiment (9 dives).

### Tests / pre-existing failures
New `test_cohort_expansion_v1.py` 15/15 (cohort determinism, family
classification, protected-data firewall, Paris/524/2555 exclusions, frozen
D5 config identity, cache provenance, no GT self-labeling, no B2 mutation);
subject_resolution suite 39/39. PRE-EXISTING (not this packet, present on
server canonical): 3 cosmetic failures in test_candidate_reranker.py —
(1) manifest string "IoU>=0.3" vs test literal "0.30" (f-string renders
0.30→0.3; unsatisfiable by construction), (2)+(3) test expects
D5_ANNOTATION_BATCH_MANIFEST.json under docs/science/reranker_v1/ but the
committed batch manifest lives at
docs/science/localization_annotations_v1/D5_ANNOTATION_BATCH/manifest.json
(per the reranker report's own artifact index). No science impact; left
untouched (out of packet scope).

### Resources / firewalls
0 B2 reads/writes, 0 training, 0 new human labels, 0 protected-data access,
0 Paris access. No scientific authority mutated; no media-backbone mutation.
Caches remain outside Git (host science caches).

Report: `docs/science/DIVE_ANALYZER_SUBJECT_RESOLUTION_COHORT_EXPANSION_V1.md`
(+ `.json`).

**Gate: `SUPERVISOR_REVIEW_AFTER_SUBJECT_RESOLUTION_COHORT_EXPANSION_V1`.**
NOTE for concurrent threads: PROJECT_STATE sections must be UNIONED when the
infrastructure thread commits (established convention, cf. `d968ad1`/`98a3528`).

## Subject GT Level-A Annotation V1 — DIVE_ANALYZER_SUBJECT_GT_LEVEL_A_ANNOTATION_V1 (2026-09-13)

Packet executed on worktree branch `subject-gt-level-a-annotation-v1`
(base = canonical `uiux-overhaul-pro-app` @ `bf78182`; packet-stated HEAD
`f00dffd` verified as ancestor — canonical had advanced via the concurrent
UI-U1/U2 integration, science content intact).

### Purpose
Close the STANDING subject-GT measurement gap with the minimum scientifically
valid human Level-A identity GT, then measure true GT-free reference-acquisition
correctness on STANDING (A0/A1 frozen, zero changes).

### Level-A GT (new scientific authority)
- Deterministic queue (`SUBJECT_GT_LEVEL_A_QUEUE_STANDING_V1.json`,
  byte-identical regeneration) from the frozen minimum-GT plan: eval window
  `[0, wc+0.5 s]`, 0.5 s grid (7/31/11/12 = 61) + 2 measured close-person
  extras = **63 anchors**; blind local web UI; **63/63 annotated by Maxime**
  (58 boxes / 5 NOT_VISIBLE) in one session.
- Reuse: 0 reused — 2 exact-frame D4/D5 mining-box candidates rejected because
  mining boxes carry generic diver semantics, not subject identity (labeled
  fresh; historical artifacts untouched).
- Frozen: `docs/science/localization_annotations_v1/SUBJECT_GT_LEVEL_A_STANDING_V1/`
  (63 anchors + MANIFEST, artifact SHA `d805aac2…a75e`, HUMAN_REVIEWED,
  annotator maxime). Validation PASS; consistency review clean (max shift
  1.06 bh/0.5 s; no static-structure boxes; nothing returned). No
  interpolation; Level-B remains unauthorized.

### Frozen V2 replay + true Level-A reference correctness (STANDING)
A0/A1 replayed unchanged (module SHA-pinned, constants asserted vs V2 freeze;
all 8 top-1 selections match the frozen cohort replay exactly; D5/OSNet never
re-run). Subject candidate ≡ consistent (center ≤ 0.06) with EVERY visible
human anchor its tracklet covers:

| Dive | A0 | A1 | best subj rank A0/A1 strict (p≥0.5) |
|---|---|---|---|
| 133 | WRONG 0.00 | WRONG 0.00 | 77/17 (15/9) |
| 311 | WRONG 0.00 | WRONG 0.00 | 30/22 (30/21) |
| 676 | WRONG 0.00 | WRONG 0.00 | 22/152 (9/4) |
| 2387 | GT_UNOBSERVED | WRONG 0.18 | —/92 (24/4) |

**0/8 top-1 subject-correct (0/7 measured).** V2 failure CONFIRMED on STANDING
with true human GT. Cohort-packet rank optimism (3–89, sparse single-anchor
rule) quantified and corrected (17–152 strict).

### HURDLE vs STANDING (family-specific failure modes — key finding)
Both families fail top-1, but for DIFFERENT dominant reasons: HURDLE decoys
are stable STATIC tracklets (recorded V2/R4); STANDING decoys are
LOW-CONFIDENCE PHANTOM person-mover tracklets (mean D5 conf 0.002–0.056,
dive-like kinematics, no conf≥0.3 person nearby). Static decoys are NOT
equally dominant across families; pooling would mislead.

### Candidate-learning dataset + gate
9 dives / 2 families / 1–2 athletes / single venue; ~17 subject-reference
positives total (STANDING strict union = 12; HURDLE ≥1/dive); 626/1495
STANDING candidates unobservable by anchors; negatives correlated within dive.
**`LEARNING_EXPERIMENT_STILL_TOO_SMALL`**; design `NOT_AUTHORIZED_YET`;
**`ARMSTAND_EXPANSION_NOT_NEEDED_YET`** (constraint is independence, not
family count).

### Resources / firewalls
0 B2 reads/writes, 0 new D5 inference, 0 embeddings, 0 training, no media
mutation; 524/2555/Paris/INTERNAL_EVAL/holdout untouched. 63 frames extracted
(outside Git, kept for image_sha256 re-verification). Tests: 15 new +
subject-resolution suite 54/54 green; 3 pre-existing cosmetic reranker
failures reproduced identically, untouched. Full report:
`docs/science/DIVE_ANALYZER_SUBJECT_GT_LEVEL_A_ANNOTATION_V1.md` (+ `.json`).

**Gate: `SUPERVISOR_REVIEW_AFTER_SUBJECT_GT_LEVEL_A_ANNOTATION_V1`.**
NOTE for concurrent threads: PROJECT_STATE sections must be UNIONED when the
infrastructure thread commits (established convention, cf. `d968ad1`/`98a3528`).

## Subject Candidate Quality V3 — DIVE_ANALYZER_SUBJECT_CANDIDATE_QUALITY_V3 (2026-09-13)

Packet executed on worktree branch `subject-candidate-quality-v3`
(fresh from canonical `uiux-overhaul-pro-app` @ `0dabd2b`). Final bounded
no-training hypothesis: suppress/down-rank unsupported low-quality person
hypotheses via TRACK-LEVEL evidence while preserving the floor-conf=0.001
proposal recall that keeps the true subject available. D5 floor NOT raised.

### Phase 0/1 — authorities + baseline reproduction (PASSED)
Level-A authority SHA recomputed `d805aac2…a75e` (63 anchors); frozen D5
model `82b420c4…`; HURDLE caches `3bed1aaf…`/`48ab9bd3…`; STANDING caches
`b2f01e41…`/`4d836002…`; V2 module byte-identical (`01a17dd7…`). Baseline
replayed EXACTLY: HURDLE A0/A1 top-1 tid+score match the frozen V2 freeze
artifact on all 10 cells; STANDING full ranked lists + candidate features
byte-identical to the durable Level-A replay (0/7 measurable top-1 correct).

### Phase 2/3 — diagnostic + track-support signal: `TRACK_SUPPORT_SIGNAL_PARTIAL`
Per-candidate quality measures from the frozen caches only (GT for labeling
only). STANDING: every subject candidate has >=2 supported frames (0%
zero-support; support = conf>=0.05 detection within normalized center
distance 0.06, both constants reused frozen semantics) while 76.7% of
non-subject movers and 92.2% of statics have zero support; the 133/311
top-1 phantom decoys have ZERO support. HURDLE: 26.8% of subject candidates
have zero support (true subject sometimes exists only below 0.05), and the
2169/2353/2541 top-1 decoys are SUPPORTED movers.

### Phase 4/5/6/7/8 — Q0 executed, Q1 rejected early, retention gate PASSED
Q0 (pre-registered, no new numeric cutoff): support_count tier — supported
candidates outrank unsupported; frozen A0/A1 order within tier; frozen
abstention semantics on the top tier; graceful fallback; NOTHING deleted.
Retention gate passed on all 9 dives at cutoff family {1,2,3,5}. Q1
(within-track OSNet appearance coherence) REJECTED_EARLY with data:
non-subject movers are equally/more coherent (median 0.866–0.918 vs subject
0.824–0.870) — no generic benefit.

### Phase 9–12 — V3 results: `CANDIDATE_QUALITY_V3_PARTIAL`
Top-1 subject-correct: HURDLE 0/10, STANDING 0/8 — UNCHANGED from frozen V2.
Phantom suppression real: phantom top-1 wins 9 -> 0; 1578/1581 phantom
candidates down-ranked; no deletion. Best-subject-rank improves materially
on 12/18 cells (311-A0 30->2, 133-A0 77->14, 2387-A0 435->100, 676-A1
152->32, 2341-A1 178->83) but regresses on 3 HURDLE cells (1040-A1 2->15,
2353-A0 9->18, 2353-A1 2->16). DECISIVE FINDING: after phantom suppression
the dominant wrong references are SUPPORTED movers — real other-person
tracks and subject-adjacent association fragments (purity up to 0.67). The
remaining failure is IDENTITY/ASSOCIATION, not candidate quality.

### Phase 13–19 — decisions
No V4 rule cycle proposed
(`HANDCRAFTED_SUBJECT_REFERENCE_HEURISTICS_CONTINUE_ONLY_IF_NEW_EVIDENCE`).
Learning: `EXPAND_INDEPENDENT_GT_BEFORE_LEARNING` (9 dives/~17 positives;
target now points at identity-aware reference selection, not sharpened
enough for a pilot). Next GT: 4–6 NEW independent dives/sessions/athletes
(Level-B chains), NOT more anchors on the same 4 STANDING clips.
`ARMSTAND_STILL_DEFERRED` (limitation is independence + identity, not
family diversity). Abstention: diagnostic only — wrong top-1s remain
confidently wrong (margins up to 2.24); no production threshold. Matcher
replay `NOT_JUSTIFIED` (no correct references). Event Logic untouched
(`EVENT_LOGIC_REPLAY_DEFERRED`).

### Resources / firewalls / tests
0 new D5 inference, 0 embeddings, 0 training, 0 labels, 0 B2 reads/writes;
524/2555/Paris/INTERNAL_EVAL/holdout untouched; GT structurally excluded
from the inference path (test-enforced); Level-A GT unmutated. Tests: 19
new + subject-resolution suite 73 passed/1 pre-existing skip. Code:
`experiments/subject_resolution/phase_subject_candidate_quality_v3.py`
(+ tests). Full report:
`docs/science/DIVE_ANALYZER_SUBJECT_CANDIDATE_QUALITY_V3.md` (+ `.json`).

**Gate: `SUPERVISOR_REVIEW_AFTER_SUBJECT_CANDIDATE_QUALITY_V3`.**

## 2026-09-20 — Multi-track dive-action V1 (latest Dive Analyzer science gate)

Starting canonical authority: `1d49bbead2c230b44ab42c76958c24eac5fe1a35`.
Accepted L0 history remains frozen: B0 4/12, B1 2/12, L0 1/12,
`IDENTITY_MATCHER_L0_FAILS`; three additional clips fragmented. No rerun.
The new product decision supersedes identity-as-gateway: `Dive.diver_id`
remains product authority, but `analysis_subject_track` is independently
selectable and multiple simultaneous/sequential DiveTracks must coexist.

**`MULTI_TRACK_DIVE_ACTION_V1_NOT_READY`**; next research:
**`IMPROVE_TRACK_ASSOCIATION_NEXT`**. Multi-track architecture and frozen
per-track replay work, but action-spanning trajectory quality does not.
All 15 clips retained: 34,320 raw PersonTracks + 6,490 merged hypotheses.
D0 117 and D1 62 dive-like hypotheses. Primary anchor-correspondence
`KNOWN_DIVE_TRACK_RECALL = 1 / 15` (2387, rank 3); stronger >=75% subject
anchor coverage recall 0/15. The one primary pass covers only 3/13 anchors
and has event absolute errors 2.648/2.164/0.929 s, so it does not validate
recovery of the actual intended dive. Bounded identity-free merging improves
no clip's best qualifying subject coverage. Other-diver legitimacy and false
DiveTrack counts remain unknown without exhaustive HUMAN action labels;
non-subject positives are not automatically false dives.

`SYNCHRO_REPRESENTABLE` verified using two simultaneous synthetic arcs through
the real frozen Event Logic. `TRACK_STABILITY_INSUFFICIENT_FOR_OVERLAY` for
whole-action attachments; observed diagnostic boxes are available. Future
user selection contract defined, no UI/DB migration. Manual selection cannot
alone repair fragmented or contaminated trajectories.

Apple M2, sequential cache-only inference, <0.7 GB process RSS; no D5 inference,
embeddings, training, labels, media decoding, or B2 reads/writes. Frozen D5,
R5/V2/V3, Event Logic V3-C0 and HUMAN authorities hash-verified, unchanged.
14 packet tests pass. No protected dataset access. Identity line frozen,
`REFERENCE_ACQUISITION_DEFERRED`, ARMSTAND deferred, Media Backbone closed.

Reports: `docs/science/DIVE_ANALYZER_MULTI_TRACK_DIVE_ACTION_V1.md` / `.json`;
contract: `docs/science/ANALYSIS_TRACK_CONTRACT_V1.md`; recovery log:
`docs/science/MULTI_TRACK_DIVE_ACTION_V1_PROGRESS.md`. Host-only trajectories
are gitignored. Existing UI/infra/science history and worktree changes preserved.

**Gate: `SUPERVISOR_REVIEW_AFTER_MULTI_TRACK_DIVE_ACTION_V1`.**
## 2026-09-20 — Action-spanning track association V2 (Dive Analyzer science gate)

Starting canonical authority: `8964f7d1258d5160c0f42e6db80521a12a148747`.
V1 baseline reproduced exactly first (V1 suite 14 passed, recall 1/15,
strong 0/15, 34,320 raw / 6,490 merged); V1 report/implementation
byte-identical to canonical. Dedicated branch
`dive-analyzer-action-span-assoc-v2`; concurrent work preserved.

**`ACTION_SPANNING_ASSOCIATION_V2_PARTIAL`**; next research:
**`IMPROVE_ASSOCIATION_REPRESENTATION_NEXT`**. Association reformulated as
trajectory decoding over an overlap-aware fragment lattice (gap + overlap +
interleave edges; interleave links strictly alternating fragments that V1
could not represent) with beam search (`BEAM_WIDTH = 512`) and diverse
top-5 path preservation (no connected-component collapse, no identity, no
GT, frozen gates only). A0 continuity on all 15 clips; A1 (frozen OSNet
local compatibility) on the 10 clips with embedding caches (hurdle has no
cache: A0 fallback).

`ACTION_SPANNING_SUBJECT_TRAJECTORY_RECALL = 0/15` (>=75% retained
criterion; V1 had 1 weak/15). Decoded-pool subject coverage materially
exceeds V1 merged best on 10+ clips (2169: 0.795 vs 0.194; 2541: 0.584 vs
0.027; 1040: 0.547 vs 0.031); lattice transition recall 0.83-1.00 on 9
clips — representable pairwise, unchainable by beam into top-5.
Subject chains are Pareto-dominated on every identity-free signal; A1
measured null (subject-subject vs other handoff appearance delta <=0.03:
geometry-redundant). Flight anchors observed at ~100% union where HUMAN
windows exist but shattered into single-anchor micro-fragments (2169: 49
anchors / 54 fragments) — the true bottleneck is flight-phase chaining.
The >=75% all-anchor criterion is prep-dominated (2169 prep = 79%) and
must become flight-phase-aware before gating analytics.

`SYNCHRO_REPRESENTABLE` (5 diverse overlapping paths/clip);
`TRACK_STABILITY_STILL_INSUFFICIENT_FOR_OVERLAY`; analytics 15/15
`TRAJECTORY_NOT_READY`; other-action GT `STILL_PREMATURE`;
`IDENTITY_LINE = FROZEN_DEFERRED`. Frozen Event Logic V3-C0 replayed
unchanged. Cache-only: D5/training/embeddings/labels/B2/media all zero;
runtime 691 s, peak RAM 1.7 GB. V2 suite 16 passed + V1 suite 14 passed.
No protected data, no B2/media mutation.

Reports: `docs/science/DIVE_ANALYZER_ACTION_SPANNING_TRACK_ASSOCIATION_V2.md`
/ `.json`; contract addendum in `ANALYSIS_TRACK_CONTRACT_V1.md` (V2 path
fields). Run outputs gitignored.

**Gate: `SUPERVISOR_REVIEW_AFTER_ACTION_SPANNING_TRACK_ASSOCIATION_V2`.**

## Git authority reconciliation — 2026-09-25 (FLIGHT_PATH_CANDIDATE_RECALL_AUDIT_V1)

- True canonical: `uiux-overhaul-pro-app` on the server (`mcauchy@192.168.1.57:~/dive-analyser`).
  Starting HEAD `d3ab6c43acf4971ab914547f0dd373f097771b0a` (V2 `509f4a9` already merged).
- V3 `d252f7b` (protocol) → `3e889f2` (science) were feature-only; merged `--no-ff` (clean) →
  `f043f6382defdda5acecfe8db66da7305c175d98`. No science commit rewritten.
- The "d3ab6c4 missing" report came from a stale mirror (`mac-mirror` …`dive-analyser-2026-09-05.git`
  at `8964f7d`) and a local clone tracking it; fresh server evidence wins. Mirror resynced at
  audit completion.
- Frozen V3 artifacts record runner SHA `cef17b32…` vs committed `c191c148…` (disclosed
  post-inference evaluation-only edits); inference outputs reproduce byte-identical.
- Concurrent server working-tree state (5 uncommitted deletions of subject_resolution_audit_v1
  files + untracked files) left untouched.

## Flight-path candidate recall audit V1 — 2026-09-25

Retention funnel (frozen V3 authority, 9 event dives): raw union 7/9, graph oracle 4/9
(1040/2169/2353/676), generated pool 0/9, F0 top-K 0/9, F1 1/9 (676, 2-anchor, F1-carried).
Strict HUMAN seeds: 5/7 → 4/7 → 0/7 → 0/7 → 1/7. Root causes: SEARCH 1040/2169/2353;
GRAPH 2341/2541/2387; OBSERVATION 133/311 (thin); FULL_ACTION_EXTENSION 676.
Decisions: `SEARCH_IS_PRIMARY_BLOCKER`, `IMPROVE_SEARCH_RECALL_NEXT`,
`MANUAL_TRACK_SELECTION_NOT_YET_VIABLE`, `OTHER_ACTION_GT_STILL_PREMATURE`.
Key defects (see report §9): motion-gate unit error (V3 + r5), end-of-clip-only harvest,
spike-latched mover slots, seeding misses the airborne diver, hurdle GT authority weaker than
reported (1040/2541 evaluator-only), F1 backward sign, core-length saturation, proxy-only
perception despite recovered aligned 1080p. Bug-fix candidates (A–D) evaluated outside the
frozen pipeline and NOT promoted (no retained gain, regressions on 676/2169).
Gate: `SUPERVISOR_REVIEW_AFTER_FLIGHT_PATH_CANDIDATE_RECALL_AUDIT_V1`.

## Flight search recovery V1 — 2026-09-26

Report `docs/science/DIVE_ANALYZER_FLIGHT_SEARCH_RECOVERY_V1.md` / `.json`; protocol
`FLIGHT_SEARCH_RECOVERY_V1_PROTOCOL.md` (frozen `3317d70` before sealed evaluation).

- **Human authority:** `localization_annotations_v1/FLIGHT_GT_HUMAN_V1` (commit `fddfe4c`,
  digest `740bf71d`): 123 blind boxes at k/8 of the HUMAN flight window on 15 DEVELOPMENT
  dives + human takeoff/water-contact for 1304/2204/2223/2526/2583/2839. Pre-existing
  landmark boxes and hurdle HUMAN seeds are D4/D5 training labels (detector-in-sample).
  FLIGHT_GT_HUMAN_V1 is now *burned* for further design selection (post-sealed work on it is
  adaptive); a fresh held-out flight authority is needed before promoting any v2.
- **Sealed funnel** (raw ≥75 % → graph → pool → top-5): frozen V3 360p 11 → 9 → 0 → 2/15;
  FSR v1 360p 11 → 11 → 3 → 3/15; FSR HQ 8 → 8 → 2 → 0/9 (top-10 2/9); FSR 360p+HQ top-5
  2/9, top-10 4/9. Post-sealed ranker v2 (trim-and-rescore, GT-free synthetic validation):
  360p+HQ top-1 4/9 = candidate ceiling.
- **Blocker:** search construction (8/15): subject reachable but captured by brighter nearby
  people (evidence search) or clutter (confidence-agnostic search); appearance useless (AUC
  0.59). Five search families tried; same ceiling. Next: flight-phase detector data (needs
  authority; D5 unchanged here).
- **HQ:** `runs/flight_search_recovery_v1/HQ_D5_CANDIDATES_V1.json` (host; frozen D5 recipe on
  recovered renditions, proxy frame/timeline); 311 trim refined to 12.145 s.
- Code: `experiments/subject_resolution/fsr_*.py`; tests `test_flight_search_recovery_v1.py`
  19 passed. Frozen V3/r5/D5/Event Logic unchanged; no protected data; no B2 mutation.
- Gate: `SUPERVISOR_REVIEW_AFTER_FLIGHT_SEARCH_RECOVERY`.

## Selected DiveTrack V1 — 2026-09-26

Starting canonical `01d6c3cfec18269213fd02687dc186838249c7dd` (S3
Flight Perception Recovery V2 already integrated). Full report:
`docs/science/DIVE_ANALYZER_SELECTED_DIVETRACK_V1.md`; protocol:
`docs/science/SELECTED_DIVETRACK_V1_PROTOCOL.md`; HUMAN authority:
`docs/science/localization_annotations_v1/FULL_ACTION_GT_HUMAN_V1_DEVELOPMENT/`
(digest `91f729961f7acc21608b642043efc465f27e8887d80436b557ed452709983dc1`).

**Decision: `SELECTED_FLIGHT_DOES_NOT_YET_YIELD_RELIABLE_FULL_DIVE_ANALYSIS`.**
The five-session fresh full-action DEVELOPMENT evaluation (dives
23/980/1555/2257/2288) had 5/5 intended flights at rank 1 among frozen
S3+FSR candidates. The original surfaced tracks hit 44/45 flight HUMAN
anchors but only 7/33 visible preparation anchors; they are bounded to the
flight segment minus 1 s/plus 0.5 s, so not full-action trajectories. Their
underlying global FSR pool paths recover 20/33 preparation anchors: 1555
6/6, 2257 6/7, 23 5/10 (two localization/identity-uncertain mismatches),
2288 3/7, 980 0/3. Visual overlays show clean full paths on 1555/2257 and
unsafe preflight associations in consumed FGT3 diagnostic cases. The FSR
global flight-search path is not a certified selected-subject PersonTrack.

Frozen Event Logic V3-C0, replayed unchanged on the visually continuous
1555/2257 full paths (100% HUMAN prep/flight purity at overlapping anchors),
places takeoff 2.183/2.135 s early and contact 2.750/0.467 s away from HUMAN
events. EL is an independent blocker once a good track exists; 980/2288 are
primarily trajectory incomplete. HUMAN apex error remains unscored (no apex
GT in this authority). No new extension heuristic or Event Logic tuning was
promoted. Box overlays are viable for flight-candidate identification, not
general full-action analysis. Per-track pose stays paused; multiple DiveTracks
and independent user selections remain intact.

Next science: explicitly flight-anchored, phase-aware extension with handoff
uncertainty and new session-disjoint DEVELOPMENT evaluation; then isolate and
repair V3-C0 early-prep logic on validated tracks with HUMAN apex authority.
Frozen S3/D5/S2/FSR/V3-C0 byte-identical; no protected set, Paris, 524, 2555,
B2/Media Backbone mutation, training, identity, segmentation, or pose.

**Gate: `SUPERVISOR_REVIEW_AFTER_SELECTED_DIVETRACK_ANALYSIS`.**


## Full-action trajectory V1 (FAX) — 2026-09-26

Starting canonical 4cab183e1b99b2b1e629c6e8d854ead296712430.
Decision: FLIGHT_ANCHORED_EXTENSION_V1_DEV_VALIDATED (design evidence only;
no generalization claim). The frozen FSR full pool path is retired as a
full-action representation: its prep span is unconstrained flight-evidence
by-catch (correct on 1555/2257, far-platform wander on 2474/1731, empty on
980), and its search lattice deletes static candidates so quiet standing
prep has no nodes by construction (2288 f30-f120 STATIC-ONLY vs HUMAN boxes).

FAX V1 (frozen protocol experiments/full_action/FAX_V1_PROTOCOL.md, code
SHA-256 55282fb968cc960919242ee43ef9ebd3db7c13becbd663aab35b3b150306a2ad):
flight-anchored bidirectional extension over the full floor lattice incl.
static; immutable flight core; frozen-adjacent gates + NMS-double merging
(IoU 0.30 or higher) + same-object overlap (IoU above 0); residual-margin 0.25
uniqueness (AMBIGUOUS_HANDOFF stops); no confidence threshold (handstand
prep links through conf-0.002 on dive 31); forward scope cap 0.5 s
(POST_ENTRY_CAP); missing frames absent, never synthetic; stops carry
labeled reasons, alternatives bounded and unlinked. Margin-by-merge 3x3
sensitivity leaves all scored coverage/purity invariant.

DEV results (FAT1 prep now design evidence: 1555 6/6, 2257 7/7, 2288 7/7
pure; 23 1/10 honest near-margin stop; 980 0/3 honest flight-only; pooled
21/33 at purity 1.0. FGT3H consumed flight preserved 11/12; contamination
refused on 1731/2474; full prep chains on 31/872/966 with visual continuity).
Frozen V3-C0 replayed unchanged fails on the trustworthy tracks (takeoff
-2.0 to -3.1 s: first-motion-after-first-stillness fires on prep motion;
flight anchor unused; dive-code context rescues only 2257/HURDLE).
V4-A0 DEV probe (flight-anchored takeoff, frozen thresholds, NOT frozen):
takeoff -0.17 to -0.48 s on 14/17, honest abstention on 980/992/2242.
Same trajectories, so the failure is event semantics. The uniform 0.25 s
early bias is a successor-cycle calibration question.

Predeclared FAT2 gate plus committed blind queue (FAT2_ANNOTATION_QUEUE_V1.md,
queue code fat2_annotation_v1.py): dives 1190/s75, 1279/s80, 2838/s202
(all unused in every training/consumed/DEV role; sessions disjoint from all
prior sets), new HUMAN takeoff/contact/apex (plus apex repeat) and
flight/prep/post boxes; GT-free selection viability pre-screened (all viable;
37 rejected at raw-clip check: empty deck). S3 caches plus selection sealed
until the freeze. Next after gate: versioned flight-anchored Event Logic
successor with fresh event authority, then bounded overlay pilot.
Pose/biomechanics stay paused; reopen after the landmark gate.

Gate: SUPERVISOR_REVIEW_AFTER_FULL_ACTION_TRAJECTORY_AND_EVENT_LOGIC.

## FAT2 gate V1 — 2026-09-27 (verdict: VOID)

Fresh authority `FULL_ACTION_GT_HUMAN_V2_FRESH` (digest
74aaf4ad29e00180f5893a0c43bba10bc1dac3a323f758539395a9f2ea914592,
48 items + FAT2_EVENTS): dives 1190/s75 and 1279/s80 fully labeled
(takeoff, water contact, apex + independent apex repeat at 0.033 s
agreement on both; flight/prep/post boxes + blind repeat); 2838
annotator-excluded as unlabelable (mostly empty 18.6 s proxy), recorded in
MANIFEST, stays in the funnel denominator. Queue revision:
`FAT2_QUEUE_REVISION_V1.md`. S3 caches + selection were sealed until the
freeze and are now open.

Gate (frozen FAX, predeclared rule): 1190 top-Q 6/9, 1279 top-Q 4/9 — both
below the 0.75 recovery bar, so the conditional selected-track set is empty
and criteria (ii)-(iv) cannot be evaluated. **Verdict: FAT2_GATE_VOID**
(not a FAX failure finding). Full record: `DIVE_ANALYZER_FAT2_GATE_V1.md`;
gate script `fat2_fresh_eval_v1.py`; host-only numbers
`runs/full_action_fax_v1/fat2_gate_results.json`.

Diagnostics (frozen code, non-gate): 1190 is the correct flight missed on
localization noise (two 0.06-boundary misses + one detector gap; overlay
shows the right diver); 1279 is a partial flight (segment starts 0.30 s
after takeoff; short-prep regime with 2 distinct prep frames). S3 prep
recall is ~0 at every fresh prep anchor (1190: 13 partial; 1279: 2 visible)
— a perception-coverage bound on small/partial prep figures (S3 training
stays frozen), not an extension bug. Where S3 sees nothing, FAX links
nothing (1190: 30-obs flight-only; 1279: 25-obs short track; zero
hallucinated prep across 15 anchors): the uncertainty design holds on fresh
data. Frozen V3-C0 abstains on both short tracks; V4-A0 DEV probe gives
1190 to -0.167 / apex 0.000 / wc -0.533 and 1279 to +0.167 / apex +0.067 /
wc -0.267 — first scored HUMAN apex errors, corroborating the DEV envelope.

Conclusion: FAT2 as drawn cannot validate FAX prep recovery (regime
mismatch + n=2 + one exclusion). DEV (21/33 prep at purity 1.0) stands as
design evidence, still unvalidated. Next: one more targeted fresh round in
the FAT1 regime (long visible prep, near subjects, new sessions) combined
with EL-successor validation (apex proven collectible); then the bounded
overlay pilot. Pose/biomechanics stay paused.

Gate: SUPERVISOR_REVIEW_AFTER_FULL_ACTION_TRAJECTORY_AND_EVENT_LOGIC.


## FAT3 gate V1 — 2026-09-27 (verdict: FAIL with validated generalization)

Fresh authority `FULL_ACTION_GT_HUMAN_V3_FRESH` (digest
`dfd493f0fe482cfd73149b38de474d54ba9fdbff6d30c044aacf4cfebcb0c48b`,
182 items + FAT3_EVENTS, zero exclusions, apex-repeat agreement
0.000–0.033 s): 6 session-disjoint DEVELOPMENT dives in the
visible-prep regime (16/s7, 251/s31, 1491/s92, 1716/s104, 2519/s139,
2742/s166; reserve 735/s47 unused), all 1m springboard, committed
pre-annotation (`69ad2f2`) with GT-free metadata + raw-clip screen and a
dive-context sweep (no prior dive reference to any of the 10 shortlisted
IDs). S3 caches + FSR selection built GT-free and sealed; viability 7/7.
Event Logic successor V4-B0 (flight-anchored takeoff + DEV-median bias
+0.23 s, frozen V3-C0 apex/wc downstream) designed and frozen on DEV
only (`39bba63`), 10/10 unit tests, before annotation.

Gate (frozen FAX V1, predeclared rule): 6/6 flights surfaced, but pooled
prep purity violated (4 wrong-person overlaps: 16×2, 2519×2) and pooled
prep coverage 29/70 = 0.414 < 0.5; flight (i) fails on 2519 (0.667).
**Verdict: FAT3_GATE_FAIL.** Full record:
`DIVE_ANALYZER_FAT3_GATE_V1.md` (`48dd1e8`).

Attribution (visual + coordinate forensics):
- VALIDATED full recovery where identity is unambiguous: 1491 (12/12),
  251 (11/11, same-athlete annotator-adjudicated), 2742 (6/6) — 29/29 at
  purity 1.0. FAX V1 generalizes fresh. 1716 honest short track (empty
  scene → walk-in, 0 visible prep, GAP/GAP).
- Association failures (extension, NOT perception): 16 (crowd drift onto
  background people within 1 s of core in a 2-simultaneous-diver scene,
  then honest AMBIGUOUS stop); 2519 (static water-junk ride via an
  IoU-0.10 handoff while the diver steps to the board; partial flight).
  S3 sees the HUMAN-boxed diver at 56/65 visible prep anchors
  (2519 @ conf 0.77) — no FAT2-class perception bound in this regime.
  FAX V1's identity-free geometric gates admit confident wrong-person
  links → real algorithmic limitation; FAX successor justified (next
  cycle; FAT3 burned as validation; FAX V1 unchanged).
- V3-C0 still fails on validated tracks (1491 −3.033, 2742 −2.352).
- V4-B0 materially improves (takeoff median 0.508 vs 2.142 on
  {1491,2742,251,1716}; exact fresh apexes 0.000 on clean takeoffs; wc
  mixed: −0.583 on 1491 threshold semantics) with a new documented
  prep-rise-lock failure (251 satellite bounce −0.883, 2742 board mount
  −1.168): "first rise after last low" must prefer proximity to ft0.
  2519 honest abstention (both logics).
- Overlay: viable on sparse single-diver tracks only; confident
  wrong-person risk in crowds → bounded pilot on sparse scenes +
  FAX-successor cycle. Pose/geometry stay PAUSED (identity blocker).
- Blocker (exactly one): trajectory extension = identity-aware
  association in multi-person prep scenes.
- Method: targeted annotator adjudication (251 same-athlete) is now the
  identity firewall; viewer viewport fix pre-annotation (`34fb42b`); no
  ghost-exclusion incident.

Frozen: FAX V1 `55282fb9…`, S3 `3dc07f69…`, V3-C0, V4-B0 `21ad37bb…`
(tests `fe40ca39…`), eval `81dd9d03…`, authority digest `dfd493f0…`.
Concurrent worktree state untouched throughout.

Gate: `SUPERVISOR_REVIEW_AFTER_FULL_ACTION_AND_EVENT_LOGIC_VALIDATION`.
