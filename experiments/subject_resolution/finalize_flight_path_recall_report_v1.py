"""Write docs/science/DIVE_ANALYZER_FLIGHT_PATH_CANDIDATE_RECALL_AUDIT_V1.json:
builder aggregates + audit findings + decisions + bug-fix candidate results."""
import json
import subprocess

import audit_flight_path_recall_v1 as au
import build_flight_path_recall_report_v1 as br

ROOT = au.ROOT


def candidate_summary(impl):
    p = ROOT / 'runs' / impl / '_comparison.json'
    if not p.exists():
        return {'status': 'NOT_RUN'}
    c = json.loads(p.read_text())
    rows = {}
    for d, v in sorted(c.items()):
        a, b = v['candidate']['FROZEN_V3_AUTHORITY'], v['v3']['FROZEN_V3_AUTHORITY']
        rows[d] = {'v3_flight_recovered': b['flight_recovered'], 'cand_flight_recovered': a['flight_recovered'],
                   'v3_best_subject_full_cov': b['best_subject_full_cov'],
                   'cand_best_subject_full_cov': a['best_subject_full_cov']}
    ev = [d for d in au.EVENT_COHORT if d in rows]
    return {'flight_recall_v3': sum(bool(rows[d]['v3_flight_recovered']) for d in ev),
            'flight_recall_candidate': sum(bool(rows[d]['cand_flight_recovered']) for d in ev),
            'regressions': [d for d, r in rows.items()
                            if (r['cand_best_subject_full_cov'] or 0) < (r['v3_best_subject_full_cov'] or 0) - 1e-9
                            or (r['v3_flight_recovered'] and not r['cand_flight_recovered'])],
            'per_dive': rows}


FINDINGS = [
    {'id': 'BUG_ROGUE', 'severity': 'CRITICAL', 'stage': 'GRAPH (S2) + upstream r5 tracklets',
     'claim': 'Velocity caps calibrated for span-averaged velocity (DEP_VEL_MAX=1.4, "divers never sprint") and a '
              'per-second jitter allowance (JITTER_C=0.012) are applied to INSTANTANEOUS single-frame velocity. '
              'At 60 fps normal detector box jitter on a rotating airborne diver exceeds the cap.',
     'evidence': 'Mean flight speed ~0.5-1.0 norm/s but per-frame GT speed oscillates 0-5 norm/s; camera flow ~0 '
                 '(not a compensation artifact). V3 gate blocks subject adjacent pairs 2341 21/55, 1040 5/30, '
                 '2541 5/23, 2387 2/27 (takeoff link). r5._gate_ok rejects subject flight links 1040 41%, 2169 55%, '
                 '2341 42%, 2353 32%, 2541 24% (clip-wide 6-25%).'},
    {'id': 'BUG_QUEUDVER', 'severity': 'CRITICAL', 'stage': 'SEARCH (S2->S3)',
     'claim': 'Pool is harvested only from paths alive at the LAST frame of the clip; flight hypotheses found '
              'mid-beam are pruned or die before harvest.',
     'evidence': '2169: subject in-beam post-prune on 86% (frozen) / 100% (strict) of flight anchor frames, 3 starts '
                 'carry it through the whole window, yet final beam/pool best = 0.184. 2341 strict: 100% in-beam, '
                 'pool 0.0.'},
    {'id': 'BUG_PEEVES', 'severity': 'HIGH', 'stage': 'SEARCH (beam retention)',
     'claim': 'Dynamic (mover) slots rank by cost - W_DYN*age*min(maxspeed,0.8)/0.8 with maxspeed the max-ever EWMA '
              'speed: one spike latches a permanent bonus that grows with age; sparse hijack/jitter paths evict the '
              'real subject.',
     'evidence': '676 start 120 frame 131: 9 on-subject hypotheses pre-prune, 0 post; dynamic occupants have 5-7 obs '
                 'over 11 frames with maxspeed ~0.8 vs subject 0.54; ~3.5 key-unit gap from the age x maxspeed term. '
                 'Mean mover-latch fraction in flight windows 0.42-0.82.'},
    {'id': 'BUG_SEEDING_NEVER_ON_SUBJECT', 'severity': 'HIGH', 'stage': 'SEARCH (seeding)',
     'claim': 'Starts seed only top-12 confidence + 6 movers at 30-frame strata; the airborne diver is rarely seeded '
              'and never re-acquired.',
     'evidence': 'Beam trace: 71/94 start-windows (frozen authority) never place a hypothesis on the subject during flight; '
                 'whole-beam snapshot harvest on 1040 still only 0.07-0.14.'},
    {'id': 'BUG_LOCKHART', 'severity': 'HIGH', 'stage': 'EVALUATION AUTHORITY',
     'claim': 'Hurdle subject "GT" is evaluator-seeded and candidate-snapped: 1040 and 2541 have ZERO HUMAN_GT '
              'anchors (VISUAL_EVALUATOR only); other hurdle chains are 2-5 human seeds linearly interpolated and '
              'snapped to D5 candidates; unresolved frames AMBIGUOUS_GT are excluded from denominators; one '
              'not_visible HUMAN seed (2169 t=6.2833) is used as a position seed.',
     'evidence': 'Median anchor-to-floor distance 0.0000 on all hurdle dives (union=1.0 by construction). 2169: 28/80 '
                 'flight frames AMBIGUOUS (all 28 of the clip); mid-flight snaps at match_dist 0.055-0.079 > '
                 'RADIUS 0.06 on 2341/2541. Human flight seeds: 1040 0, 2169 5, 2341 2, 2353 4, 2541 0.'},
    {'id': 'BUG_NEVILLE', 'severity': 'MEDIUM', 'stage': 'F1 extension',
     'claim': 'extend_core backward prediction double-negates (vx=-vel0 with dt_sign<0) so it extrapolates forward '
              'in time; forward seed velocity mixes raw with compensated coordinates; velocity never updated.',
     'evidence': 'Source inspection; corrected in candidate BF-B (no retained gain, see candidates).'},
    {'id': 'BUG_DUDLEY', 'severity': 'MEDIUM', 'stage': 'F0 core objective Q',
     'claim': 'Excursion term (running max-min) is monotone in window length while penalties are means, so cores '
              'saturate at CORE_MAX_S=3.0 s and pack ~1.2 s flights with 1.8 s of surrounding content.',
     'evidence': '2169 top-5 cores all 2.94-2.98 s; 2541 r1 2.97 s; 311 r1 2.97 s.'},
    {'id': 'BUG_HAGRID', 'severity': 'STRATEGIC', 'stage': 'PERCEPTION INPUT',
     'claim': 'Entire pipeline runs on 202x360 portrait proxies; airborne diver 27x41 to 60x32 px. 1920x1080 '
              'originals were recovered and timeline-aligned for 12 development dives '
              '(ICLOUD_HIGHRES_ANALYSIS_SOURCE_RECOVERY_V1) but never fed to detection/trajectory.',
     'evidence': 'HUMAN_GT flight boxes (2169/2341/2353) and L1A boxes; HIGHRES manifest RECOVERED_ALIGNED 11 + '
                 'DETERMINISTIC_MAPPING 1.'},
    {'id': 'BUG_NICK_QUASI_SANS_TETE', 'severity': 'LOW', 'stage': 'OBSERVATION CONTROL (311)',
     'claim': "311's single flight anchor is a 156x148 px box clipped at the right frame edge; neighbours (-1,+2) have "
              'floor matches; under the frozen hits>=2 rule 311 is unrecoverable by construction (1 flight anchor).',
     'evidence': 'L1A_311_f00435 bbox [46,15,202,163] on 202x360; f00420 not_visible.'},
]

DECISIONS = {
    'MANUAL_SELECTION_READINESS': 'MANUAL_TRACK_SELECTION_NOT_YET_VIABLE',
    'OTHER_ACTION_GT': 'OTHER_ACTION_GT_STILL_PREMATURE',
    'PRIMARY_BLOCKER': 'SEARCH_IS_PRIMARY_BLOCKER',
    'NEXT_RESEARCH_DECISION': 'IMPROVE_SEARCH_RECALL_NEXT',
    'IDENTITY_LINE': 'FROZEN_DEFERRED', 'REFERENCE_ACQUISITION': 'DEFERRED',
    'EVENT_LOGIC': 'FROZEN', 'POSE_ANALYTICS': 'PAUSED',
    'SCIENTIFIC_AUTHORITIES_MUTATED': 'NO', 'MEDIA_BACKBONE_MUTATED': 'NO',
}

ROOT_CAUSE = {  # primary (+ secondary) per event dive, frozen authority primary
    '1040': ['SEARCH_PRUNING_LIMITED', 'AUTHORITY: VISUAL_EVALUATOR_ONLY'],
    '2169': ['SEARCH_PRUNING_LIMITED', 'FULL_ACTION_EXTENSION_LIMITED (F1 contaminates: purity 1.0->0.34)'],
    '2341': ['GRAPH_REPRESENTATION_LIMITED', 'SEARCH_PRUNING_LIMITED (strict-human oracle 1.0, pool 0.0)'],
    '2353': ['SEARCH_PRUNING_LIMITED', None],
    '2541': ['GRAPH_REPRESENTATION_LIMITED', 'AUTHORITY: VISUAL_EVALUATOR_ONLY'],
    '133': ['FLIGHT_OBSERVATION_LIMITED', 'THIN_AUTHORITY (2 anchors)'],
    '311': ['FLIGHT_OBSERVATION_LIMITED', 'THIN_AUTHORITY (1 edge-clipped anchor; unrecoverable under hits>=2)'],
    '676': ['FULL_ACTION_EXTENSION_LIMITED', 'THIN (2 anchors; flight reached only by F1 of a pre-flight core)'],
    '2387': ['GRAPH_REPRESENTATION_LIMITED', 'takeoff link velocity/size-blocked'],
}

GIT = {
    'true_canonical_branch': 'uiux-overhaul-pro-app (server mcauchy@192.168.1.57:~/dive-analyser)',
    'starting_canonical_head': 'd3ab6c43acf4971ab914547f0dd373f097771b0a',
    'v2_integration': '509f4a9 merged into canonical by d3ab6c4 (already integrated before this packet)',
    'v3_integration': 'd252f7b -> 3e889f2 feature-only on dive-analyzer-flight-anchored-trajectory-v3; merged '
                      'non-destructively into canonical as f043f6382defdda5acecfe8db66da7305c175d98 (--no-ff, clean)',
    'stale_mirror_explanation': 'mac-mirror (divesensei@192.168.1.19 ...dive-analyser-2026-09-05.git) was at 8964f7d '
                                'and never received d3ab6c4; V3 used a local clone whose uiux-overhaul-pro-app tracked '
                                'the stale state, hence "d3ab6c4 missing".',
    'concurrent_work_preserved': 'yes (server working tree carried 5 pre-existing uncommitted deletions of '
                                 'subject_resolution_audit_v1 files + untracked files; untouched)',
    'v3_runner_hash_note': 'frozen V3 inference artifacts record runner sha cef17b32...; committed runner at 3e889f2 is '
                           'c191c148... (post-inference evaluation-only edits disclosed in the V3 report); inference '
                           'outputs reproduce byte-identical.',
}


if __name__ == '__main__':
    rep = br.build()
    rep['GIT_AUTHORITY_RECONCILIATION'] = GIT
    rep['V3_REPRODUCTION']['official_runner_reinference_identical'] = all(
        json.loads((ROOT / 'runs/flight_anchored_traj_v3' / f'{d}.json').read_text())
        == json.loads((ROOT.parent / 'diveanalyzer-flight-v3/runs/flight_anchored_traj_v3' / f'{d}.json').read_text())
        for d in au.v1run.COHORT)
    rep['STAGE_DEFINITIONS'] = au.__doc__
    rep['FINDINGS'] = FINDINGS
    rep['PER_DIVE_ROOT_CAUSE'] = ROOT_CAUSE
    rep['DECISIONS'] = DECISIONS
    rep['BUGFIX_CANDIDATES_EVALUATION_ONLY'] = {
        'note': 'Not promoted, not merged into the frozen pipeline. A=motion-gate units, B=F1 sign/coords, '
                'C=snapshot harvest, D=sustained-motion dynamic slots.',
        'A+B+C+D': candidate_summary('flight_anchored_traj_v3_1_bfcd'),
        'pool_probe_notes': 'Pool-level subject coverage does not improve under A+B / A+B+D / A+B+C+D on 1040/2169/2341 '
                            '(2169 0.184 -> 0.12-0.14); whole-beam snapshot harvest on 1040 0.07-0.14; frozen V3 + whole-beam snapshot harvest on 2169 0.184 -> 0.31 (purity 0.94, Q-rank 1 / diverse rank 1: ranking is not the blocker once subject flight reaches the pool), with fix A 0.12. Local fixes '
                            'are necessary but insufficient: V3 cost economics rank real (jittery, shape-changing, '
                            'NULL-bridged) flight below static/hijack paths at seeding, retention and triage.'}
    rep['DECISIONS']['HEAD_AT_AUDIT_START'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    out = ROOT / 'docs/science/DIVE_ANALYZER_FLIGHT_PATH_CANDIDATE_RECALL_AUDIT_V1.json'
    out.write_text(json.dumps(rep, indent=1, sort_keys=True, default=float) + '\n')
    print('wrote', out, rep['RETENTION_FUNNEL'])
