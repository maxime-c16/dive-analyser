"""Build DIVE_ANALYZER_FLIGHT_SEARCH_RECOVERY_V1.json from the sealed evaluation outputs."""
import glob
import json
from collections import Counter

import fsr_common_v1 as C

FE = C.RUNS / 'final_eval'
KS = (1, 3, 5, 10, 20)


def rec(e):
    return bool(e and e.get('recovered', e.get('qualifies')))


def main():
    mine = json.loads((FE / 'mine.json').read_text())
    v3 = {}
    for p in glob.glob(str(FE / 'v3_*_*.json')):
        _, d, rep = p.rsplit('/', 1)[1][:-5].split('_')
        v3[(d, rep)] = json.loads(open(p).read())
    out = {'packet': 'DIVE_ANALYZER_FLIGHT_SEARCH_RECOVERY_V1',
           'authority': {'label': 'FLIGHT_GT_HUMAN_V1', 'digest': C.EVAL_DIGEST,
                         'protocol_doc': 'docs/science/FLIGHT_SEARCH_RECOVERY_V1_PROTOCOL.md',
                         'protocol_sha256': '5c3fb3444e99b3aa4f08237f8aa607e50278150bf619d353218d8a77fd6e515c'},
           'funnel': {}, 'per_dive': {}}
    for tag in ('all', 'strict'):
        F = {}
        for rep in ('360', 'hq', '360+hq'):
            dives = [d for d in C.COHORT if f'{tag}:{rep}' in mine[d]]
            rows = [mine[d][f'{tag}:{rep}'] for d in dives]
            f = {'dives': len(dives),
                 'S0_raw_presence_ge_0.75': sum(r['S0_raw_presence'] >= C.RECOVERY for r in rows)}
            if rep != '360+hq':
                f['S1_lattice_presence_ge_0.75'] = sum(r['S1_lattice_presence'] >= C.RECOVERY for r in rows)
                f['S2_graph_oracle'] = sum(rec(r['S2_graph_oracle']) for r in rows)
                f['S3_pool'] = sum(r['S3_pool_recovered'] for r in rows)
            f['S3b_any_candidate'] = sum(r['S3b_any_candidate_recovered'] for r in rows)
            for k in KS:
                f[f'S4_top{k}'] = sum(r[f'top{k}'] for r in rows)
            F[f'FSR_V1:{rep}'] = f
            # event-dive-only view for 360 (comparable with hq)
            if rep == '360':
                ev = [mine[d][f'{tag}:360'] for d in C.EVENT_DIVES]
                F['FSR_V1:360@event9'] = {'dives': 9, 'S3_pool': sum(r['S3_pool_recovered'] for r in ev),
                                          'S2_graph_oracle': sum(rec(r['S2_graph_oracle']) for r in ev),
                                          **{f'S4_top{k}': sum(r[f'top{k}'] for r in ev) for k in KS}}
        for rep in ('360', 'hq'):
            rows = [v3[(d, rep)][tag] for d in C.COHORT if (d, rep) in v3]
            F[f'FROZEN_V3:{rep}'] = {
                'dives': len(rows),
                'S0_raw_presence_ge_0.75': sum(r['S0_raw_presence'] >= C.RECOVERY for r in rows),
                'S1_lattice_presence_ge_0.75': sum(r['S1_lattice_presence'] >= C.RECOVERY for r in rows),
                'S2_graph_oracle': sum(rec(r['S2_graph_oracle']) for r in rows),
                'S3_pool': sum(r['S3_pool_recovered'] for r in rows),
                'F0_topK': sum(r['F0_topK_recovered'] for r in rows),
                'F1_final_top5': sum(r['F1_final_first_recovered_rank'] is not None for r in rows)}
        out['funnel'][tag] = F
    for d in C.COHORT:
        row = {'window_source': mine[d]['window_source'], 'flight_anchors': mine[d]['flight_anchors_all'],
               'unobserved_items': mine[d]['unobserved_items']}
        for rep in ('360', 'hq', '360+hq'):
            k = f'all:{rep}'
            if k in mine[d]:
                r = mine[d][k]
                row[f'FSR_V1:{rep}'] = {
                    'raw': round(r['S0_raw_presence'], 3),
                    'lattice': round(r['S1_lattice_presence'], 3) if 'S1_lattice_presence' in r else None,
                    'graph': rec(r.get('S2_graph_oracle')), 'pool': r.get('S3_pool_recovered'),
                    'first_rank': r['first_recovered_rank'],
                    'best_candidate_cov': round((r['best_candidate'] or {}).get('coverage', 0), 3),
                    'best_candidate_pur': (r['best_candidate'] or {}).get('purity')}
        for rep in ('360', 'hq'):
            if (d, rep) in v3:
                r = v3[(d, rep)]['all']
                row[f'FROZEN_V3:{rep}'] = {'raw': round(r['S0_raw_presence'], 3), 'lattice': round(r['S1_lattice_presence'], 3),
                                           'graph': rec(r['S2_graph_oracle']), 'pool': r['S3_pool_recovered'],
                                           'F1_rank': r['F1_final_first_recovered_rank']}
        out['per_dive'][d] = row
    # GT authority audit
    man = json.loads((C.EVAL_DIR / 'MANIFEST.json').read_text())
    items = [json.loads(open(p).read()) for p in glob.glob(str(C.EVAL_DIR / 'FGT1_*_f*.json'))]
    out['gt_authority'] = {
        'FLIGHT_GT_HUMAN_V1': {'items': len(items), 'visibility': dict(Counter(i['visibility'] for i in items)),
                               'repeatability_center_dist_norm': man['validation']['repeat_center_dist_norm'],
                               'indep_flight_durations_s': man['validation']['indep_flight_durations_s'],
                               'blind': man['blind'], 'digest': man['digest'],
                               'superseded_items': man['superseded_count'],
                               'discarded_pre_fix_events': sorted(man['discarded_pre_fix'])},
        'pre_existing': {
            'LANDMARK_HUMAN': 'takeoff/apex/entry boxes, HUMAN_REVIEWED but D4/D5 training (DEV_TRAIN) or validation (2341/2353) labels',
            'D5_MINED_HUMAN': 'hurdle HUMAN_GT seeds = D5 mining frames (+-15 frames around events), D5 training labels',
            'LEVEL_A_HUMAN': 'STANDING L1A, 1-3 anchors per flight, not detector training',
            'CHAIN_DERIVED': 'hurdle target_chains_v1: evaluator-seeded, interpolated, snapped to D5 candidates; not human',
            'VISUAL_EVALUATOR': '1040/2541 hurdle seeds eyeballed by an agent; not human'},
        'queue_items_on_D5_mined_frames': ['FGT1_2353_f00368', 'FGT1_311_f00432']}
    # loss-stage classification (frozen v1; ranking also with post-sealed ranker v2)
    r2 = json.loads((FE / 'ranker_v2_posthoc.json').read_text())
    cls = {}
    for rep in ('360', 'hq', '360+hq'):
        cc = {}
        for d in C.COHORT:
            k = f'all:{rep}'
            if k not in mine[d]:
                continue
            r = mine[d][k]
            base = mine[d].get(f'all:{rep}' if rep != '360+hq' else 'all:360')
            graph = rec(base.get('S2_graph_oracle')) if rep != '360+hq' else (
                rec(mine[d]['all:360'].get('S2_graph_oracle')) or rec(mine[d].get('all:hq', {}).get('S2_graph_oracle')))
            v2 = r2[f'rank_v2|{rep}|SEALED_BURNED'].get(d)
            if r['S0_raw_presence'] < C.RECOVERY:
                c = 'PROPOSAL_OBSERVATION_FAILURE'
            elif not graph:
                c = 'REPRESENTATION_GRAPH_FAILURE'
            elif not r['S3b_any_candidate_recovered']:
                c = 'SEARCH_CONSTRUCTION_FAILURE'
            elif not r['top5']:
                c = 'RANKING_FAILURE' + ('_FIXED_BY_RANKER_V2' if v2 and v2 <= 5 else '')
            else:
                c = 'SURFACED_TOP5'
            cc[d] = c
        cls[rep] = {'per_dive': cc, 'counts': dict(Counter(cc.values()))}
    out['loss_stage_classification'] = cls
    out['post_sealed_adaptive'] = {
        'note': 'Evaluated on FLIGHT_GT_HUMAN_V1 AFTER the frozen v1 result; adaptive, not promoted; needs fresh held-out confirmation.',
        'ranker_v2_trim_and_rescore': {k: {'top1': sum(1 for v in d.values() if v and v <= 1),
                                           'top5': sum(1 for v in d.values() if v and v <= 5),
                                           'any': sum(1 for v in d.values() if v), 'n': len(d), 'ranks': d}
                                       for k, d in r2.items()},
        'search_variants': json.loads((FE / 'posthoc_variants.json').read_text()),
        'osnet_appearance_auc_subject_vs_other_person': 0.586,
        'synthetic_top1_recovered_of_10': {'rank_v1': 6, 'rank_v2': 8}}
    (C.DOC / 'DIVE_ANALYZER_FLIGHT_SEARCH_RECOVERY_V1.json').write_text(json.dumps(out, indent=1, sort_keys=True) + '\n')
    print(json.dumps(out['funnel'], indent=1))


if __name__ == '__main__':
    main()
