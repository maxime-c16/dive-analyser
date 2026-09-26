#!/usr/bin/env python3
"""DIVE_ANALYZER_FLIGHT_PERCEPTION_SUCCESSOR_V1 — summaries + the protocol's selection score.

Usage:
  python3 fps_summarize_v1.py select <authority> <key> [<key> ...]   # validation selection table
  python3 fps_summarize_v1.py table  <authority> <key> [<key> ...]   # per-representation summary
"""
from __future__ import annotations

import json
import statistics as st
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fps_media_v1 as fm  # noqa: E402

VALID = ['1304', '2204', '2223', '2526', '2583', '2839']


def load(key, authority):
    return json.loads((fm.RUNS / 'downstream' / f'{key}_{authority}.json').read_text())


def summary(res, dives, min_anchors=2):
    ev = [d for d in dives if d in res['dives'] and res['dives'][d]['n_flight_anchors'] >= min_anchors]
    out = {'evaluable_dives': len(ev)}
    for rep in ('360', 'hq', '360+hq'):
        rows = [res['dives'][d][rep] for d in ev if rep in res['dives'][d]]
        s = {'n': len(rows)}
        for k in (1, 3, 5, 10, 20):
            s[f'top{k}'] = sum(bool(r.get(f'top{k}')) for r in rows)
        if rep != '360+hq':
            s['S0_raw_ge_0.75'] = sum((r['S0_raw_presence'] or 0) >= 0.75 for r in rows)
            s['S2_graph'] = sum(bool((r['S2_graph_oracle'] or {}).get('recovered')) for r in rows)
            s['S3_pool'] = sum(bool(r['S3_pool_recovered']) for r in rows)
            P = [p for r in rows for p in r['proposal']]
            if P:
                s['anchors'] = len(P)
                s['presence'] = round(sum(p['present'] for p in P) / len(P), 3)
                for t in ('0.05', '0.10', '0.25'):
                    s[f'presence_conf{t}'] = round(sum(p[f'present_conf{t}'] for p in P) / len(P), 3)
                s['subject_is_top1'] = round(sum(p['rank'] == 0 for p in P) / len(P), 3)
                s['median_subject_conf'] = round(st.median(p['subject_conf'] for p in P), 4)
                s['median_margin'] = round(st.median(p['margin_vs_other'] for p in P), 4)
                s['median_best_iou'] = round(st.median(p['best_iou'] for p in P), 3)
                ious = [p['iou_of_subject_cand'] for p in P if p['iou_of_subject_cand'] is not None]
                s['median_iou_subject_cand'] = round(st.median(ious), 3) if ious else None
            C = [r['continuity_INTERP'] for r in rows if r['continuity_INTERP']]
            if C:
                for t in ('conf0.001', 'conf0.05'):
                    s[f'INTERP_{t}_present'] = round(st.mean(c[t]['present_frac'] for c in C), 3)
                    s[f'INTERP_{t}_runs'] = round(st.mean(c[t]['n_runs'] for c in C), 2)
                    s[f'INTERP_{t}_longest'] = round(st.mean(c[t]['longest_run_frac'] for c in C), 3)
        out[rep] = s
    return out


def select_score(sm):
    return (sm['360']['top5'] + sm['360+hq']['top5'],
            sm['360']['S3_pool'] + sm['hq']['S3_pool'],
            sm['360']['S2_graph'] + sm['hq']['S2_graph'],
            round((sm['360']['presence_conf0.10'] + sm['hq']['presence_conf0.10']) / 2, 3))


def main():
    cmd, auth, keys = sys.argv[1], sys.argv[2], sys.argv[3:]
    for k in keys:
        res = load(k, auth)
        dives = VALID if auth == 'FGT1' else sorted(res['dives'], key=int)
        sm = summary(res, dives)
        if cmd == 'select':
            print(k, 'score', select_score(sm))
        print(k, json.dumps(sm, indent=None))


if __name__ == '__main__':
    main()
