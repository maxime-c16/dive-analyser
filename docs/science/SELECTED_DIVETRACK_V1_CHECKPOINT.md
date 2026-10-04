# Selected DiveTrack V1 checkpoint — 2026-09-26

This is an in-progress checkpoint, not the final science claim. Working branch
`agent/selected-divetrack-analysis-v1` was cut from canonical
`01d6c3cfec18269213fd02687dc186838249c7dd`. The server canonical working
tree had unrelated deletions/untracked files and has not been touched.

## Immutable inputs and authority

- S3 checkpoint SHA-256 `3dc07f69cbe3824490f73c14a59ed328ff35fc2da48da2fd4e324acf9bcc4e9a`.
- Frozen FSR search/ranker/pipeline and frozen Event Logic V3-C0 are imported
  unchanged. D5/S2 remain unchanged.
- FGT3H 14-dive holdout is **consumed diagnostic** only. Twelve selected flights
  passed its frozen recovery criterion; 377/1003 are separate perception cases.
- Fresh full-action HUMAN authority: five FGT2H dives from distinct sessions,
  23/s9, 980/s60, 1555/s98, 2257/s131, 2288/s140. They were not used in S3's
  OOD training set (66/538/540/2498). FGT2H flight/event labels are pre-existing;
  54 new prep/post box labels were drawn blind to model output by Maxime.
  Authority at `docs/science/localization_annotations_v1/FULL_ACTION_GT_HUMAN_V1_DEVELOPMENT/`,
  manifest digest `91f729961f7acc21608b642043efc465f27e8887d80436b557ed452709983dc1`.
  Visibility: 30 visible, 10 partial, 14 not visible. Two repeated box-center
  differences: 0.0088, 0.0053 normalized. An initial six-dive queue was corrected
  before label use when 2498's S3 training exposure was noticed; the final queue
  includes no 2498 item, and the five-session protocol was committed before
  fresh trajectory scoring.

## Reproducible experiment

Host-only S3 360p and strictly aligned HQ caches are at
`runs/selected_divetrack_v1/caches/`. Exact cache/model hashes are embedded in
`runs/selected_divetrack_v1/fresh_full_action.json` (host only). The frozen FSR
top-5 selection is computed before FGT2H flight GT identifies the intended
candidate. The candidate is then held fixed. `selected_track_fresh_eval_v1.py`
compares the actual FSR surfaced window (flight segment with 1 s pre/0.5 s
post limits) with its complete underlying pool path; neither changes frozen
FSR or Event Logic. All five intended flights are surfaced at rank 1 (a
conditional result on these five DEVELOPMENT dives, not fresh S3 perception
generalization).

## Current observed results

| Dive | Surfaced prep HUMAN hits | Full pool prep HUMAN hits | Full pool prep purity | Surfaced takeoff / contact absolute error | Full pool takeoff / contact absolute error |
|---|---:|---:|---:|---:|---:|
| 23 | 1/10 | 5/10 | 5/7 | missing / missing | 3.320 / 1.535 s |
| 980 | 0/3 | 0/3 | no overlap | missing / missing | missing / missing |
| 1555 | 1/6 | 6/6 | 6/6 | 0.217 / 0.600 s | 2.183 / 2.750 s |
| 2257 | 2/7 | 6/7 | 6/6 | 0.234 / 0.250 s | 2.135 / 0.467 s |
| 2288 | 3/7 | 3/7 | 3/3 | 0.234 / 0.033 s | 1.018 / 1.368 s |

Flight HUMAN hits on the surfaced track: 23 9/9, 980 8/9, 1555 9/9,
2257 9/9, 2288 9/9. All five have one visible post-contact anchor hit.
The frozen full-pool path gives extensive, apparently pure preparation for
1555 and 2257, but Event Logic picks early movement and produces >2 s
takeoff error. That isolates an Event Logic failure on at least these
anchor-supported paths, subject to final visual inspection between sparse
anchors. Dive 23 has two preparation center mismatches at the frozen 0.06
radius, but its contact sheet suggests the same diver; call this localization
error or identity uncertainty, not a confirmed switch.
980 has no prep observation. Dive 2288 has missing prep despite an extended
pool path. The surfaced window cannot be called a full-action track.

FGT3H consumed diagnostic independently showed why exposing the raw full
pool path is unsafe: on 1731 and 2474, contact sheets show the path attaching
to other activity before the intended flight. Across 12 selected flights, a
longer pool path often made frozen Event Logic errors much larger. Contact
sheets and the exact diagnostic JSON are host-only under
`runs/selected_divetrack_v1/`.

## Remaining work

1. Validate all frozen source/cache hashes and the new authority, then inspect
   full-pool overlays for 1555/2257 and contamination cases.
2. Record the final phase coverage, longest gaps, contamination runs, box
   stability, and frozen Event Logic table. HUMAN apex event GT was not in
   FGT2H and has not been collected; report apex estimates as unscored unless
   a separate HUMAN apex annotation is obtained.
3. Decide whether an anchor-preserving extension repair is defensible from
   consumed diagnostic evidence. Do not use the new five-dive labels to tune a
   rule and then call the same result fresh validation.
4. Produce the durable report, update PROJECT_STATE, and integrate accepted
   work to canonical without disturbing its unrelated working-tree changes.

Protected sets FINAL_HOLDOUT, INTERNAL_EVAL, Paris, 524, 2555 stress-only,
B2/Media Backbone mutation, detector training, identity, segmentation, and
pose were not used.
