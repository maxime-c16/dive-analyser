"""Reproducible consumed-development comparison; never a fresh V3 gate."""
import hashlib
import json
from pathlib import Path

import fax_extension_v1 as V1
import fax_extension_v2_dev as V2
import fax_extension_v3_dev as V3
import fax_v2_fresh_eval as F

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'runs/fax_v3/fax_v3_consumed_results.json'


def longest_missing(labels, obs):
    missing = sorted((a['pts_s'], f) for f, a in labels.items()
                     if a.get('visibility') in ('visible', 'partial') and a.get('bbox')
                     and f not in obs)
    if not missing:
        return 0.0
    runs, run = [], [missing[0]]
    for x in missing[1:]:
        if x[0] - run[-1][0] <= .6:
            run.append(x)
        else:
            runs.append(run)
            run = [x]
    runs.append(run)
    return max(r[-1][0] - r[0][0] for r in runs)


def main():
    labels, events, authority = F.authority()
    cache = json.loads(F.CACHE.read_text())
    assert cache['gt_payload'] == 'NONE'
    out = {'role': 'CONSUMED_DEVELOPMENT_ONLY', 'authority': authority['authority'],
           'authority_digest': authority['digest'],
           'v3_code_sha256': hashlib.sha256(Path(V3.__file__).read_bytes()).hexdigest(),
           'dives': {}}
    for d in events:
        parts = labels[d]
        flight = {f: a for phase, rows in parts.items() if phase.endswith('/8') for f, a in rows.items()}
        candidate = F.select(F.select_flight({'360': cache}, d), flight)
        if candidate is None:
            out['dives'][d] = {'selected': False, 'failure_class': 'UPSTREAM_FLIGHT_SURFACING'}
            continue
        row = {'selected': True, 'models': {}}
        for name, engine in [('v1', V1), ('v2', V2), ('v3', V3)]:
            t = engine.build_track(d, candidate['rep'], candidate['parts']['t0'],
                                   candidate['parts']['t1'], candidate['path'],
                                   candidate['Latt'], candidate['Fl'], candidate['pts'])
            obs = {int(f): tuple(v['box'] + [v['conf']])
                   for f, v in t['trajectory'].items() if v['box'] is not None}
            pre = F.score_phase(obs, parts.get('PREP', {}))
            fl = F.score_phase(obs, flight)
            po = F.score_phase(obs, parts.get('POST', {}))
            row['models'][name] = {
                'prep': pre, 'flight': fl, 'post': po,
                'prep_honest_abstention': pre['visible'] - pre['overlap'],
                'first_wrong_prep_time': (candidate['pts'][min(pre['wrong'])]
                                          if pre['wrong'] else None),
                'longest_missing_prep_s': longest_missing(parts.get('PREP', {}), obs),
                'stability': F.stability(obs, candidate['pts']),
                'mixed_intervals': t.get('uncertainty', []),
                'selected_flight_source_frames': t['anchor']['n_core'],
                'asserted_boxes': len(obs),
            }
        out['dives'][d] = row
    for name in ('v1', 'v2', 'v3'):
        rows = [r['models'][name] for r in out['dives'].values() if r['selected']]
        out[name + '_pooled'] = {
            'prep_correct': sum(r['prep']['hits'] for r in rows),
            'prep_visible': sum(r['prep']['visible'] for r in rows),
            'prep_wrong': sum(len(r['prep']['wrong']) for r in rows),
            'prep_honest_abstention': sum(r['prep_honest_abstention'] for r in rows),
            'flight_correct': sum(r['flight']['hits'] for r in rows),
            'flight_visible': sum(r['flight']['visible'] for r in rows),
            'mixed_selected_flights': sum(bool(r['mixed_intervals']) for r in rows),
        }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, sort_keys=True) + '\n')
    print(json.dumps({k: v for k, v in out.items() if k.endswith('_pooled')}, indent=1))


if __name__ == '__main__':
    main()
