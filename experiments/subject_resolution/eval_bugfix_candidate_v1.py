"""Evaluate a V3 bug-fix candidate against frozen V3 with the frozen V3
evaluator functions (flight_correspondence / correspondence / flight_window).
Candidate inference is GT-free; evaluation follows per dive after inference.
Outputs runs/<impl>/<dive>.json and a comparison table."""
from __future__ import annotations

import importlib
import json
import sys
from multiprocessing import Pool

import audit_flight_path_recall_v1 as au
import run_flight_anchored_traj_v3 as r3
import run_multi_track_action_v1 as v1run

IMPL = sys.argv[1] if len(sys.argv) > 1 else 'flight_anchored_traj_v3_1_bf'
OUT = au.ROOT / 'runs' / IMPL


def score(output, dive):
    pts = output['frame_pts']
    window = r3.flight_window(dive, pts)
    res = {}
    for aname, anchors in (('FROZEN_V3_AUTHORITY', v1run.subject_anchors(dive, pts)),
                           ('STRICT_HUMAN_SEEDS', au.strict_human_anchors(dive, pts))):
        if not anchors:
            res[aname] = {'status': 'NO_AUTHORITY', 'flight_recovered': None, 'best_flight_cov': None,
                          'best_flight_rank': None, 'best_subject_full_cov': None, 'full_recovered': None,
                          'tracks': []}
            continue
        rows = []
        for t in output['tracks']:
            ae = v1run.correspondence(t, anchors)
            row = {'path_rank': t['path_rank'], 'full_cov': ae['matched_anchor_coverage'],
                   'full_subject': ae['is_subject'], 'full_purity': ae['purity'],
                   'sequence': t['procedural_sequence'], 'status': t['status']}
            if window['status'] == 'SCORED':
                fe = r3.flight_correspondence(t, anchors, window, pts)
                row.update({'flight_cov': fe['matched_anchor_coverage'], 'flight_purity': fe['purity'],
                            'flight_anchors': fe['flight_anchors'],
                            'flight_qualifies': bool(fe['is_subject'] and fe['matched_anchor_coverage'] >= au.COVER)})
            rows.append(row)
        fsub = [r for r in rows if r.get('flight_qualifies')]
        subj = [r for r in rows if r['full_subject']]
        res[aname] = {
            'flight_recovered': bool(fsub) if window['status'] == 'SCORED' else None,
            'best_flight_cov': max((r['flight_cov'] for r in rows if r.get('flight_purity') is not None
                                    and r['flight_purity'] >= .75), default=0.0) if window['status'] == 'SCORED' else None,
            'best_flight_rank': min((r['path_rank'] for r in fsub), default=None),
            'best_subject_full_cov': max((r['full_cov'] for r in subj), default=0.0),
            'full_recovered': any(r['full_cov'] >= au.COVER for r in subj),
            'tracks': rows}
    return res


def run_dive(dive):
    impl = importlib.import_module(IMPL)
    cached = OUT / f'{dive}.json'
    if cached.exists():
        out = json.loads(cached.read_text())
    else:
        group = next(g for g, ids in v1run.GROUPS.items() if dive in ids)
        raw = json.loads(v1run.CACHES[group].read_text())
        doc = raw['dives'][dive]
        out = impl.infer(impl.inference_view(doc['frames']), float(doc['fps']))
        out['clip_id'] = dive
        out['frame_pts'] = [f['pts_s'] for f in doc['frames']]
        out['input_proxy_sha256'] = doc.get('proxy_sha256')
        del raw
        cached.write_text(json.dumps(out, sort_keys=True) + '\n')
    ref = json.loads((au.ROOT.parent / 'diveanalyzer-flight-v3/runs/flight_anchored_traj_v3' / f'{dive}.json').read_text())
    return dive, score(out, dive), score(ref, dive)


if __name__ == '__main__':
    OUT.mkdir(parents=True, exist_ok=True)
    dives = sys.argv[2:] or v1run.COHORT
    results = {}
    with Pool(6) as p:
        for dive, cand, base in p.imap_unordered(run_dive, dives):
            results[dive] = {'candidate': cand, 'v3': base}
            c, b = cand['FROZEN_V3_AUTHORITY'], base['FROZEN_V3_AUTHORITY']
            print(dive, 'flight', b['best_flight_cov'], '->', c['best_flight_cov'],
                  'rec', b['flight_recovered'], '->', c['flight_recovered'], 'rank', c['best_flight_rank'],
                  '| full', round(b['best_subject_full_cov'], 3), '->', round(c['best_subject_full_cov'], 3),
                  '| strict', base['STRICT_HUMAN_SEEDS']['best_flight_cov'], '->',
                  cand['STRICT_HUMAN_SEEDS']['best_flight_cov'], flush=True)
    (OUT / '_comparison.json').write_text(json.dumps(results, indent=1, sort_keys=True) + '\n')
