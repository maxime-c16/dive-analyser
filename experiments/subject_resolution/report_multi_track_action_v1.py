"""Render the durable packet report after successful packet validation."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / 'docs/science'
PATH = DOC / 'DIVE_ANALYZER_MULTI_TRACK_DIVE_ACTION_V1.json'


def render():
    r = json.loads(PATH.read_text())
    rows = r['per_dive']
    r['test_results'] = {'packet_owned': '14 passed, zero failures',
                         'command': 'python3 -m pytest -q experiments/subject_resolution/test_multi_track_action_v1.py'}
    r['integration'] = {'science_branch':'dive-analyzer-multi-track-dive-action-v1',
        'canonical_branch':'uiux-overhaul-pro-app',
        'exact_final_head_receipt':'See MULTI_TRACK_DIVE_ACTION_V1_INTEGRATION_RECEIPT.json in the dedicated worktree; intentionally untracked to avoid a self-referential commit SHA.'}
    r['totals'] = {'raw_person_tracks':sum(v['PersonTracks'] for v in rows.values()),
                   'merged_hypotheses':sum(v['merged_hypotheses'] for v in rows.values()),
                   'D0_dive_like':sum(v['D0']['DIVE_LIKE'] for v in rows.values()),
                   'D1_dive_like':sum(v['D1']['DIVE_LIKE'] for v in rows.values())}
    PATH.write_text(json.dumps(r, indent=1, sort_keys=True) + '\n')
    table = ['| Dive | Raw / supported | Merged | D0 dives | D1 dives / non / ambiguous | Subject retained / rank | Other positives* |',
             '|---|---:|---:|---:|---:|---|---:|']
    fragments = ['| Dive | Raw subject-touching fragments | Merged touching / qualifying | Best raw / merged anchor coverage | Best selected trajectory coverage / gap s | Observed off-subject anchors |',
                 '|---|---:|---:|---:|---:|---:|']
    for d,v in rows.items():
        q = v['D1']; b = v['best_subject_hypothesis']
        table.append(f"| {d} | {v['PersonTracks']} / {v['supported_person_tracks']} | {v['merged_hypotheses']} | {v['D0']['DIVE_LIKE']} | {q['DIVE_LIKE']} / {q['NON_DIVE']} / {q['AMBIGUOUS']} | {'yes' if q['subject_retained'] else 'no'} / {q['subject_rank']} | {q['unmatched_positive_hypotheses']} |")
        quality = 'unavailable' if b is None else f"{b['trajectory_coverage']:.3f} / {b['longest_observation_gap_s']:.4f}"
        contamination = 'unavailable' if b is None else str(b['evaluation']['observed_non_subject_anchor_count'])
        fragments.append(f"| {d} | {v['raw_subject_fragments']} | {v['merged_action_fragments_touching_subject']} / {v['merged_subject_correspondence_count']} | {v['best_raw_subject_anchor_coverage']:.3f} / {v['best_merged_subject_anchor_coverage']:.3f} | {quality} | {contamination} |")
    md = f'''# LOCAL_AGENT_REPORT — DIVE_ANALYZER_MULTI_TRACK_DIVE_ACTION_V1

## STATUS

`MULTI_TRACK_DIVE_ACTION_V1_NOT_READY`. The architecture preserves multiple hypotheses and supports independent Event Logic replay, but this formulation does not produce reliable action-spanning subject trajectories. This is a result about the tested formulation, not proof that identity-free tracking is impossible.

## STARTING_STATE / FRESH_GIT_AUTHORITY

Canonical `diveanalyzer-server:/home/mcauchy/dive-analyser`, branch `uiux-overhaul-pro-app`, starting HEAD `1d49bbead2c230b44ab42c76958c24eac5fe1a35`. Fresh dedicated worktree `/Users/maximecauchy/.perso/diveanalyzer-multi-track-v1`, branch `dive-analyzer-multi-track-dive-action-v1`. Original task cwd is a non-Git reference slice. Protocol committed before inference at `95d1de59261526d423fadd3f979607fd7e3d7156`.

Canonical existing deletions of subject-resolution audit MD/JSON, DB export, audit script/test and untracked detector/annotation work were explicitly excluded from this packet. Four existing server worktrees and the local L0 worktree were preserved. No DiveSensei Core Detection work.

The JSON authority manifest records exact SHA-256 identities for D5 caches/model declaration, frozen R5/V2/V3 and V3-C0/dependency, HUMAN chain GT, 63 Level-A anchors, 180 Level-B anchors, and nine DEVELOPMENT event authorities. GT digests were recomputed. Event proxy SHA matches its authority input SHA in all nine cases. Recorded PTS drives new association/events/evaluation; original R5 nominal-fps association remains frozen and disclosed.

## PERSONTRACK_INPUTS / MULTI_TRACK_PRESERVATION

All 15 accepted clips, including 1304/2223/2526, evaluated. {r['totals']['raw_person_tracks']:,} raw PersonTracks and {r['totals']['merged_hypotheses']:,} merged alternatives retained. Every raw track survives independently of score and merge success. These are hypotheses, including phantom detections and duplicate alternatives, not counts of physical people. Full frame-level artifacts (~278 MB) stay host-only in `runs/multi_track_action_v1/`; the durable JSON stores compact positive/subject-track evidence and exact artifact hashes. Reproduce with `run_multi_track_action_v1.py preflight`, `infer`, `evaluate`, then packet tests and this report renderer. Inference takes no product subject, GT, family, or event times.

## DIVETRACK_DEFINITION

A PersonTrack is a temporal person hypothesis. A DiveTrack is a PersonTrack or bounded fragment chain exhibiting procedural dive evidence. No automatic `diver_id` assignment, no PRIMARY_DIVER, and no identity ranking. All original alternatives remain inspectable.

## D0_PROCEDURAL_RESULTS

{r['totals']['D0_dive_like']} positive hypotheses; anchor-correspondence recall {r['D0_recall']}/15. Frozen V3-C0 receives each full track extent with missing observations explicit, recorded PTS, original cy and detector confidence, and uniform empty-code UNKNOWN context. It therefore uses the existing non-HURDLE takeoff fallback for every track. No clip-family routing. Complete ordered events plus frozen minimum extent, bounded gaps, and observed descent >=0.08 form eligibility. This is not a physical proof of entry: frozen last-confident-detection fallback and camera motion remain confounds. Non-dive labels describe track fragments, not a person's behavior across the clip.

## D1_QUALITY_RESULTS

`EXECUTED`. Frozen V3 Q0 support gates resolved D0 labels; unsupported hypotheses become AMBIGUOUS. {r['totals']['D1_dive_like']} positives, reducing 117 to 62 without improving recall. No thresholds fitted, no sweeps, no third formulation. A documented compliance correction moved quality out of the D0 static-negative rule into D1; positive decisions and D1 outputs were unchanged.

## PRIMARY_METRIC

`KNOWN_DIVE_TRACK_RECALL = 1 / 15` under preregistered HUMAN-anchor correspondence (at least two matching visible anchors, >=0.75 overlap purity). No clip silently excluded for fragmentation. The only pass is 2387 at generic rank 3, covering 3/13 visible anchors. **Strong subject coverage >=75% recall is 0/15.** The primary is an anchor-based proxy for action recall, not verified recovery of the intended action. Large event errors below prevent treating even that pass as downstream-ready.

## PER_DIVE_RESULTS

{chr(10).join(table)}

*Other positives are unmatched hypotheses, not validated other divers or false dives. For EVERY clip, legitimate other-diver count and false-DiveTrack count are UNVERIFIED / null because existing authority does not exhaustively label every person's action. Unmatched counts provide an upper bound for unmatched false hypotheses, not precision or total false-action bounds; even a subject-corresponding hypothesis may have a false action arc. Hypothesis duplication also inflates counts. No extra labels invented.

## MULTI_DIVER_RESULTS

- 2341: 1,394 raw / 389 supported, zero D1 positives; 119 subject-touching fragments and 31 merged alternatives touching the subject. All anchors have a nearby raw observation in union, yet the best qualifying raw fragment covers only 3.7%. Clear association bottleneck.
- 2353: 1,668 raw / 493 supported, three positive hypotheses, none subject-corresponding; 58 raw and 19 merged subject-touching fragments. Intended dive not retained.
- 2526: 1,319 raw / 584 supported, zero positives; 31 raw and ten merged subject-touching fragments. 94.4% union anchor coverage but best qualifying fragment only 11.1%.
- 2583: 1,107 raw / 269 supported, 12 positives, none subject-corresponding; 51 overlapping positive pairs demonstrate nonexclusive representation, not 12 real divers. Best qualifying subject fragment is a NON_DIVE preparation fragment with 40% anchor coverage.
- 2204 and 2839 are additional crowded hypothesis cases: ten positives each, none subject-corresponding. 1304 and 2223 lack any >=2-hit, >=0.75-purity qualifying hypothesis. Existing labels cannot certify next-diver/bystander action identities; all movers are preserved for inspection.

## SYNCHRO_REPRESENTATION

`SYNCHRO_REPRESENTABLE`. The real frozen Event Logic runs on a synthetic pair of simultaneous arcs and returns two independent DIVE_LIKE trajectories. Actual clips also retain overlapping hypotheses. No synchro-specific model/evaluation and no exclusivity assumption.

## FRAGMENT_ASSOCIATION / SUBJECT_TRAJECTORY_QUALITY

Identity-free mutual-best endpoint prediction adds chains using PTS gaps <=0.30 s, frozen R5 spatial/size/velocity gates and V3 residual radius 0.06. Inputs use geometry and timing only. Overlapping fragments never merge, all originals retained. This conservative method can join synthetic arcs, but **does not improve best qualifying subject-anchor coverage on any real clip**. Likely constraints include temporally interleaved/overlapping alternatives and unreliable endpoints; neither is solved by short temporal-gap stitching.

{chr(10).join(fragments)}

Subject-touching includes any hit; qualifying means >=2 hits and >=0.75 overlap purity. Trajectory coverage is within the selected hypothesis extent, not full-dive coverage; high values for tiny fragments must not be mistaken for recovery. Observation gap includes frame spacing. Anchor mismatch is observable contamination, not a certified identity-switch count; sparse intervals and unlabelled people remain unverified. Exact per-track evidence and selected-track anchor purity are in the JSON.

## PER_TRACK_EVENT_LOGIC / SUBJECT_EVENT_ACCURACY

Every final D1 positive was independently replayed in tests: takeoff/apex/contact all found, complete 62/62 by construction. This measures procedural output availability, not event accuracy or identity. Per-track event dictionaries remain in host artifacts and compact durable JSON. Partial/empty sequences are retained on other candidates.

For known-subject DiveTracks, only 2387 is scoreable: takeoff signed error -2.648107 s, apex -2.163940 s, water contact -0.928704 s (absolute 2.648107 / 2.163940 / 0.928704 s). The evaluator chooses the best retained subject hypothesis by anchor coverage/purity only, an explicit evaluation oracle with no inference role. Eight other event-authority clips have no retained subject DiveTrack. Six expansion clips have no event YAML authority. 311 apex is NOT_APPLICABLE and remains unscored. All other DiveTracks lack corresponding event GT and remain unscored. No Event Logic modification.

## ANALYSIS_TRACK_CONTRACT / FUTURE USER SELECTION

See `ANALYSIS_TRACK_CONTRACT_V1.md`: stable scoped ID, interval, raw references/provenance, box trajectory, representative frame, statuses, events and analysis availability. Independent `analysis_subject_track` selection preserves `Dive.diver_id` authority. Future default may derive from identity, generic ranking, or prior choice; user override and independent users' choices are required. Interface is viable; manual choice alone does not repair present fragmentation. No UI or DB migration.

## OVERLAY_READINESS

`TRACK_STABILITY_INSUFFICIENT_FOR_OVERLAY`. Observed box drawing is technically available for diagnostics; stable whole-action identity needed for reliable masks/silhouettes/pose is not yet established. No segmentation introduced.

## PRODUCT_STATE_SEMANTICS

NO_DIVE_TRACK_FOUND, ONE_DIVE_TRACK_FOUND, MULTIPLE_DIVE_TRACKS_FOUND all supported from hypothesis counts; AMBIGUOUS_TRACKS is an additional nonexclusive flag. Do not present these as counts of verified physical dives until deduplication/discrimination is validated.

## IDENTITY_LINE / REFERENCE_ACQUISITION

`FROZEN_DEFERRED`: B0 oracle cosine 4/12, B1 + V3 2/12, L0 learned matcher 1/12 and three MATCHER_NOT_EVALUABLE cases remain historical accepted results; L0 not rerun or reinterpreted. Identity is not an analysis gateway. `REFERENCE_ACQUISITION_DEFERRED`. ARMSTAND deferred.

## V1_STATUS / NEXT_RESEARCH_DECISION / CURRENT_TRUE_BOTTLENECK

`MULTI_TRACK_DIVE_ACTION_V1_NOT_READY`.

`IMPROVE_TRACK_ASSOCIATION_NEXT`.

Action-spanning association is the next blocker. The data model and independent replay are viable, but no candidate simultaneously has strong subject coverage and procedural eligibility. Frozen Event Logic also emits misleading early sequences; after association improves, action discrimination and event accuracy still need evidence. This result does not justify returning to identity training or changing D5/Event Logic.

## RESOURCE_RESULTS

D5 inference 0; new embeddings 0; training 0; new labels 0; B2 reads 0; B2 writes 0; media decodes 0. Final sequential inference runtime {r['resources']['runtime_s']:.2f} s; peak process RSS {r['resources']['peak_ram_bytes']:,} bytes ({r['resources']['peak_ram_bytes']/1e9:.3f} GB), well below 20 GB. A first 82.37 s pass preceded the documented D0-negative compliance correction; full outputs regenerated. These timings exclude preflight, documentation and tests. `caffeinate -i -s` used; no media loaded into memory.

## TEST_RESULTS

14 packet-owned tests pass, zero failures: cohort identity/protected allowlist; frozen D5/V3/Event Logic/GT SHA identity; no identity/GT/training/media operations in inference; metadata poisoning boundary; all raw alternatives preserved; overlap representation; deterministic association and PTS gap behavior; no overlap merging; two simultaneous positive arcs through real frozen replay; invalid PTS rejection; D0/D1 quality separation; known-subject evaluation; all final positive event replays and immutable parameter dictionary; full real-clip determinism; resource/zero-operation assertions. Tests combine contracts and artifact checks. No inference outputs changed by evaluation.

## SCIENTIFIC_AUTHORITIES_MUTATED / MEDIA_BACKBONE_MUTATED

`NO` / `NO`. Existing scientific source files and GT/cache bytes rechecked. 524=AUTHORITY_CONFLICT_EXCLUDED; 2555=SCREEN_RECORDING_STRESS_CASE (unused); Paris=EXTERNAL_ONLY (not accessed); INTERNAL_EVAL=NOT_ACCESSED; FINAL_HOLDOUT=NOT_ACCESSED. No B2/MediaRevision writes or durable media tier.

## DURABLE_ARTIFACTS / GIT_STATE

This MD and companion JSON; `ANALYSIS_TRACK_CONTRACT_V1.md`; preregistered protocol and ongoing progress log; inference, evaluation/report code and tests under `experiments/subject_resolution/`; union-style PROJECT_STATE update. Raw caches excluded from Git.

Science branch and canonical integration preserve concurrent work. Exact science commit, final canonical 40-character HEAD and mirror verification are recorded in the final response and local `MULTI_TRACK_DIVE_ACTION_V1_INTEGRATION_RECEIPT.json`; the receipt is deliberately outside its own commit to avoid an impossible self-referential SHA. Current integration progress is in `MULTI_TRACK_DIVE_ACTION_V1_PROGRESS.md`.

## STOP_DOING_LIST_UPDATE / SCIENTIFIC_RECOMMENDATION

Stop collapsing clips to one diver, using top-1 identity as a downstream gateway, equating Event Logic completeness with a real dive, interpreting hypothesis counts as distinct people, and treating high within-fragment coverage as full action recovery. Do not train identity/L1/OSNet, change D5 floor, reopen A0/A1, add V4 quality, tune by dive/family, alter Event Logic, expand ARMSTAND/reference acquisition, or touch protected media. Preserve all alternatives while improving generic association across interleaved fragments. Downstream production work should wait for adequate trajectory and event evidence; architecture work can use the contract now.

## NEXT_SUPERVISOR_DECISIONS

1. Authorize a bounded identity-free association experiment addressing temporally overlapping/interleaved fragments.
2. Decide whether to obtain HUMAN other-action labels to measure true/false multi-diver precision; current packet invents none.
3. Decide the minimum action-spanning coverage evidence required before per-track analytics resumes.

## RECOMMENDED_NEXT_SUPERVISOR_GATE

SUPERVISOR_REVIEW_AFTER_MULTI_TRACK_DIVE_ACTION_V1
'''
    (DOC / 'DIVE_ANALYZER_MULTI_TRACK_DIVE_ACTION_V1.md').write_text(md)


if __name__ == '__main__':
    render()
