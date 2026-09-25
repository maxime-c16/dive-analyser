"""Aggregate FLIGHT_PATH_CANDIDATE_RECALL_AUDIT_V1 per-dive runs into the
retention funnel, per-dive root cause and the durable JSON report.

Root-cause rule (fixed before aggregate inspection; first failing stage):
  S6 qualifies           -> RECOVERED if the same-track full-action coverage
                            >= 0.75 else FULL_ACTION_EXTENSION_LIMITED
  S0 < 0.75              -> FLIGHT_OBSERVATION_LIMITED
  S2 not qualifying      -> GRAPH_REPRESENTATION_LIMITED
  S3 not qualifying      -> SEARCH_PRUNING_LIMITED
  S4 not qualifying      -> TOPK_RANKING_LIMITED
  else                   -> FULL_ACTION_EXTENSION_LIMITED (F1 degraded a
                            qualifying core)
"qualifies" = frozen V3 recovery rule: hits >= 2, purity >= 0.75,
flight-anchor coverage >= 0.75.
"""
from __future__ import annotations

import json
from pathlib import Path

import audit_flight_path_recall_v1 as au

RUNS = au.OUT
TRACE = au.OUT / 'beam_trace'
STAGES = [('raw_union', 'S0'), ('graph_oracle', 'S2'), ('generated_pool', 'S3'),
          ('final_F0_topK', 'S4'), ('extended_pool', 'S5'), ('final_F1_topK', 'S6')]


def load_runs():
    return {p.stem: json.loads(p.read_text()) for p in sorted(RUNS.glob('*.json')) if not p.stem.startswith('_')}


def stage_q(a):
    """Per-stage qualification for one authority block."""
    g = lambda k: bool(a[k] and a[k]['qualifies'])
    return {'S0': a['S0_raw_union'] >= au.COVER,
            'S1': a['S1_capped_lattice_union'] >= au.COVER,
            'S2': bool(a['S2_graph_oracle']['eval'] and a['S2_graph_oracle']['eval']['qualifies']),
            'S3a': g('S3a_beam_final_best'), 'S3': g('S3_pool_path_best'),
            'S3c': g('S3c_pool_core_best'), 'S4': g('S4_f0_topk_core_best'),
            'S5': g('S6_f1_final_best'),  # V3 extends only the top-K: S5 == S6
            'S5cf': g('S5cf_f1_all_cores_best'), 'S6': g('S6_f1_final_best')}


def classify(a):
    q = stage_q(a)
    if q['S6']:
        b = a['S6_f1_final_best']
        return ('RECOVERED' if b['full_action_coverage'] >= au.COVER else 'FULL_ACTION_EXTENSION_LIMITED'), q
    if not q['S0']:
        return 'FLIGHT_OBSERVATION_LIMITED', q
    if not q['S2']:
        return 'GRAPH_REPRESENTATION_LIMITED', q
    if not q['S3']:
        return 'SEARCH_PRUNING_LIMITED', q
    if not q['S4']:
        return 'TOPK_RANKING_LIMITED', q
    return 'FULL_ACTION_EXTENSION_LIMITED', q


def funnel(runs, authority):
    rows = {}
    n = 0
    for d in au.EVENT_COHORT:
        a = runs[d]['authorities'][authority]
        if a['status'] != 'SCORED':
            continue
        n += 1
        for k, v in stage_q(a).items():
            rows[k] = rows.get(k, 0) + int(v)
    return {'evaluable': n, **{k: rows.get(k, 0) for k in
                               ('S0', 'S1', 'S2', 'S3a', 'S3', 'S3c', 'S4', 'S5', 'S5cf', 'S6')}}


def _m(x, k='coverage'):
    if x is None:
        return None
    x = x.get('eval', x) if 'eval' in x else x
    return None if x is None else x.get(k)


def per_dive_rows(runs, authority):
    out = {}
    for d in au.EVENT_COHORT:
        r = runs[d]
        a = r['authorities'][authority]
        if a['status'] != 'SCORED':
            out[d] = {'status': a['status']}
            continue
        cls, q = classify(a)
        s2 = a['S2_graph_oracle']['eval']
        out[d] = {
            'flight_anchors': a['flight_anchor_count'],
            'raw_union': a['S0_raw_union'], 'capped_lattice_union': a['S1_capped_lattice_union'],
            'graph_oracle': {k: s2[k] for k in ('coverage', 'purity', 'off_subject', 'longest_gap_s', 'qualifies')},
            'beam_final_best': {k: _m(a['S3a_beam_final_best'], k) for k in ('coverage', 'purity', 'qualifies')},
            'F0_pool_best': {k: _m(a['S3_pool_path_best'], k) for k in ('coverage', 'purity', 'off_subject', 'longest_gap_s', 'qualifies')},
            'F0_pool_core_best': {**{k: _m(a['S3c_pool_core_best'], k) for k in ('coverage', 'purity', 'qualifies', 'core_rank_by_Q', 'diverse_rank', 'suppressed_by_diverse_rank', 'Q')}},
            'F0_final_best': {k: _m(a['S4_f0_topk_core_best'], k) for k in ('coverage', 'purity', 'qualifies', 'diverse_rank')},
            'F1_pool_best_counterfactual_all_cores': {k: _m(a['S5cf_f1_all_cores_best'], k) for k in ('coverage', 'purity', 'qualifies', 'core_rank_by_Q', 'diverse_rank')},
            'F1_final_best': {k: _m(a['S6_f1_final_best'], k) for k in ('coverage', 'purity', 'off_subject', 'longest_gap_s', 'qualifies', 'path_rank', 'full_action_coverage')},
            'link_feasibility': a['link_feasibility'],
            'stage_qualifies': q,
            'primary_loss_stage': cls,
        }
    return out


def build():
    runs = load_runs()
    assert set(runs) == set(au.v1run.COHORT), sorted(runs)
    v3 = json.loads(au.V3_REPORT.read_text())
    ident = {d: r['v3_output_identical_to_frozen_artifact'] for d, r in runs.items()}
    s6_frozen = {d: runs[d]['authorities']['FROZEN_V3_AUTHORITY']['S6_f1_final_best']
                 for d in au.EVENT_COHORT}
    recall = sum(bool(s6_frozen[d] and s6_frozen[d]['qualifies']) for d in au.EVENT_COHORT)
    repro_match = {d: abs((s6_frozen[d]['coverage'] if s6_frozen[d] else 0.0)
                          - v3['per_dive'][d]['best_flight_coverage']) < 1e-12 for d in au.EVENT_COHORT}
    traces = {p.stem: json.loads(p.read_text()) for p in sorted(TRACE.glob('*.json'))} if TRACE.exists() else {}
    report = {
        'packet': au.AUDIT, 'gate': au.GATE,
        'V3_REPRODUCTION': {
            'all_15_outputs_identical': all(ident.values()), 'per_dive_identical': ident,
            'flight_recall': {'recovered_clips': recall, 'evaluable_clips': len(au.EVENT_COHORT)},
            'best_flight_coverage_matches_v3_report': repro_match,
            'lattice_pool_rank_sha256': {d: [r['lattice_sha256'], r['pool_sha256'], r['core_rank_sha256']]
                                          for d, r in runs.items()},
            'search_pool_sizes': {d: {'starts_eligible': r['starts_eligible'], 'starts_survived': r['starts_survived'],
                                      'beam_final_paths': r['beam_final_paths'], 'pool_paths': r['pool_paths'],
                                      'cores': r['cores'], 'diverse_cores': r['diverse_cores'],
                                      'suppressed_as_duplicate': r['suppressed_cores']} for d, r in runs.items()},
        },
        'RETENTION_FUNNEL': {a: funnel(runs, a) for a in ('FROZEN_V3_AUTHORITY', 'STRICT_HUMAN_SEEDS')},
        'PER_DIVE': {a: per_dive_rows(runs, a) for a in ('FROZEN_V3_AUTHORITY', 'STRICT_HUMAN_SEEDS')},
        'BEAM_TRACE': traces,
        'resources': {'D5_inference': 0, 'new_embeddings': 0, 'training': 0, 'new_labels': 0,
                      'B2_reads': 0, 'B2_writes': 0, 'media_decodes': 0,
                      'runtime_s_per_dive': {d: r['runtime_s'] for d, r in runs.items()}},
        'protected_data': {'524': 'AUTHORITY_CONFLICT_EXCLUDED', '2555': 'SCREEN_RECORDING_STRESS_CASE',
                           'Paris': 'EXTERNAL_ONLY', 'INTERNAL_EVAL': 'NOT_ACCESSED',
                           'FINAL_HOLDOUT': 'NOT_ACCESSED'},
    }
    return report


if __name__ == '__main__':
    rep = build()
    print(json.dumps(rep['RETENTION_FUNNEL'], indent=1))
    for a, rows in rep['PER_DIVE'].items():
        print('==', a)
        for d, r in rows.items():
            if 'primary_loss_stage' not in r:
                print(d, r['status'])
                continue
            print(d, 'n', r['flight_anchors'], 'S0 %.2f' % r['raw_union'], 'S1 %.2f' % r['capped_lattice_union'],
                  'S2', round(r['graph_oracle']['coverage'], 2), r['graph_oracle']['purity'],
                  'S3a', r['beam_final_best']['coverage'], 'S3', r['F0_pool_best']['coverage'],
                  'S3c', r['F0_pool_core_best']['coverage'], 'S4', r['F0_final_best']['coverage'],
                  'S5cf', r['F1_pool_best_counterfactual_all_cores']['coverage'],
                  'S6', r['F1_final_best']['coverage'], r['F1_final_best']['path_rank'], '->', r['primary_loss_stage'])
    Path('/tmp').exists()
    out = au.ROOT / 'runs/flight_path_recall_audit_v1/_report_draft.json'
    out.write_text(json.dumps(rep, indent=1, sort_keys=True, default=float) + '\n')
