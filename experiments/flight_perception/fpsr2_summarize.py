#!/usr/bin/env python3
"""Aggregate sealed V3 funnel and OOD strata after final evaluation only."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from fps_summarize_v1 import summary
import fpsr2_media as fm

RUN = fm.RUNS / 'downstream'


def report(keys):
    split = fm.split()
    metadata = {str(x['dive_id']): x for x in split['dives']}
    out = {'label': 'FLIGHT_PERCEPTION_RECOVERY_V2_FRESH_EVAL', 'split': split['label'],
           'groups': {}, 'models': {}}
    for key in keys:
        res = json.loads((RUN / f'{key}_FGT3H.json').read_text())
        dives = sorted(res['dives'], key=int)
        groups = {
            'all': dives,
            'replay_screen': [d for d in dives if d in ('992', '1003')],
            'native_camera': [d for d in dives if d not in ('992', '1003')],
            'one_meter': [d for d in dives if metadata[d]['height'] == '1m'],
            'three_meter_or_higher': [d for d in dives if metadata[d]['height'] != '1m'],
            'hq_verified': [d for d in dives if fm.hq_ok(d)],
            'hq_unavailable': [d for d in dives if not fm.hq_ok(d)],
            'nonstandard_proxy_width': [d for d in dives if fm.proxy_size(d)[0] != 202],
            'small_human_box_h_lt_0.10': [d for d in dives
                                           if res['dives'][d]['median_human_box_height_norm'] < .10],
        }
        primary = {}
        for name, ds in groups.items():
            ranks = [(res['dives'][d]['360+hq'] if '360+hq' in res['dives'][d]
                      else res['dives'][d]['360'])['first_recovered_rank'] for d in ds]
            primary[name] = {'n': len(ds), **{f'top{k}': sum(r is not None and r <= k for r in ranks)
                                               for k in (1, 5, 10)}}
        out['models'][key] = {'authority_digest': res['authority_digest'],
                              'excluded_lt2_visible_flight_anchors': res['excluded_lt2_visible_flight_anchors'],
                              'groups': {name: summary(res, ds) for name, ds in groups.items()},
                              'primary': primary}
        out['groups'] = groups
    dest = fm.RUNS / 'FRESH_SUMMARY_V2.json'
    dest.write_text(json.dumps(out, indent=2, sort_keys=True))
    print(dest)
    for key in keys:
        a = out['models'][key]['primary']['all']
        raw = out['models'][key]['groups']['all']['360'].get('presence')
        print(key, 'n', a['n'], 'top1/5/10', a['top1'], a['top5'], a['top10'], 'raw360', raw)


if __name__ == '__main__':
    report(sys.argv[1:])
