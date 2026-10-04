"""FAT2 gate record (runs ONCE per freeze; frozen FAX code).

Strict predeclared procedure FIRST: emulate the user click via fresh flight
boxes (first Q-ordered candidate passing the frozen recovery rule). If no
candidate qualifies, the dive is recorded unsurfaced (perception failure in
the funnel denominator) with NO conditional track statistics.
Diagnostics on the top-Q candidate (clearly labeled non-gate) follow for
reporting only and cannot change the gate.
"""
import hashlib
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'experiments' / 'subject_resolution'))
sys.path.insert(0, str(ROOT / 'experiments' / 'flight_perception'))
sys.path.insert(0, str(ROOT / 'experiments' / 'landmark_pilot'))
import fax_extension_v1 as FAX
import proposer_event_logic_v3_c0 as EL
import proposer_event_logic_v4_a0_dev as V4
from fax_eval_v1 import select_flight, score_phase

FAT2 = ROOT / 'docs' / 'science' / 'localization_annotations_v1' / 'FULL_ACTION_GT_HUMAN_V2_FRESH'
CACHE = {r: json.loads((ROOT / 'runs' / 'full_action_fax_v1' / 'caches' /
                        f'CAND_S3_FAT2_{r}.json').read_text()) for r in ('360', 'hq')}
RADIUS = 0.06
DIVES = ('1190', '1279')  # 2838 annotator-excluded (in MANIFEST)
REPS = {'1190': ('360', 'hq'), '1279': ('360',)}
OUT = ROOT / 'runs' / 'full_action_fax_v1' / 'fat2_gate_results.json'


def load_authority():
    man = json.loads((FAT2 / 'MANIFEST.json').read_text())
    assert man['sealed'] and man['authority'] == 'FULL_ACTION_GT_HUMAN_V2_FRESH'
    assert hashlib.sha256(json.dumps(man['files'], sort_keys=True).encode()).hexdigest() == man['digest']
    for name, h in man['files'].items():
        assert hashlib.sha256((FAT2 / name).read_bytes()).hexdigest() == h, name
    boxes, flight, apex_ev = {}, {}, {}
    for name in man['files']:
        if name in ('MANIFEST.json', 'FAT2_EVENTS.json'):
            continue
        a = json.loads((FAT2 / name).read_text())
        d = a['dive_id']
        ff = a.get('flight_fraction') or ''
        if ff.endswith('/8'):
            flight.setdefault(d, {})[a['frame_index']] = a
        elif ff in ('PREP', 'POST'):
            boxes.setdefault(d, {})[a['frame_index']] = a
        else:
            apex_ev[name] = a
    events = json.loads((FAT2 / 'FAT2_EVENTS.json').read_text())
    return boxes, flight, events, man['digest']


def ctr(a):
    b = a['bbox']
    return ((b[0] + b[2]) / 2 / a['width'], (b[1] + b[3]) / 2 / a['height'])


def main():
    assert FAX.RESID_MARGIN == 0.25 and FAX.IOU_MERGE == 0.30 and FAX.FWD_MAX_S == 0.5
    assert CACHE['360']['model_sha256'] == '3dc07f69cbe3824490f73c14a59ed328ff35fc2da48da2fd4e324acf9bcc4e9a'
    boxes, flight, events, digest = load_authority()
    out = {'authority': 'FULL_ACTION_GT_HUMAN_V2_FRESH', 'digest': digest,
           'fax_code': hashlib.sha256((HERE / 'fax_extension_v1.py').read_bytes()).hexdigest(),
           'excluded': ['2838'], 'dives': {}}
    for d in DIVES:
        anchors = {f: ctr(a) for f, a in flight[d].items()
                   if a.get('visibility') in ('visible', 'partial') and a.get('bbox')}
        cands = []
        for rep in REPS[d]:
            for c in select_flight(CACHE, d):
                if c['rep'] == rep:
                    cands.append(c)
        cands.sort(key=lambda z: (-z['Q'], z['pool_rank'], z['rep']))

        def qualifies(c):
            h = sum(1 for f, a in anchors.items() if f in c['obs'] and
                    math.hypot(c['obs'][f][0] - a[0], c['obs'][f][1] - a[1]) <= RADIUS)
            o = sum(1 for f in anchors if f in c['obs'])
            return (h >= 2 and h / len(anchors) >= 0.75 and
                    (h / o if o else 0) >= 0.75, h, o)

        scored = [(c,) + qualifies(c) for c in cands]
        sel = next((c for c, ok, h, o in scored if ok), None)
        top = cands[0]
        row = {'n_candidates': len(cands),
               'topQ': {'rep': top['rep'], 'Q': round(top['Q'], 3),
                        'ft': [top['parts']['t0'], top['parts']['t1']],
                        'hits': qualifies(top)[1], 'overlap': qualifies(top)[2],
                        'anchors': len(anchors)},
               'selected': None if sel is None else
               {'rep': sel['rep'], 'pool_rank': sel['pool_rank'], 'Q': round(sel['Q'], 3)}}
        if sel is None:
            row['verdict'] = 'UNSURFACED_PERCEPTION_FAILURE'
            out['dives'][d] = row
            print(d, 'UNSURFACED: top', row['topQ'], flush=True)
            diag_top_candidate(out, d, top, boxes, flight, events)
            continue
        row['verdict'] = 'SELECTED'
        score_selected(out, d, sel, boxes, flight, events)
    out['gate'] = {'i_flight': False, 'note': 'conditional set empty; gate VOID'}
    out['gate_pass'] = False
    OUT.write_text(json.dumps(out, indent=1, sort_keys=True))
    print('GATE VOID (see verdicts). Wrote', OUT)
def score_selected(out, d, sel, boxes, flight, events):
    tr = FAX.build_track(d, sel['rep'], sel['parts']['t0'], sel['parts']['t1'],
                         sel['path'], sel['Latt'], sel['Fl'], sel['pts'])
    obs = {int(f): tuple(v['box'] + [v['conf']]) for f, v in tr['trajectory'].items()}
    score_track(out, d, sel, tr, obs, boxes, flight, events, gate_evidence=True)


def diag_top_candidate(out, d, top, boxes, flight, events):
    # NON-GATE diagnostic (reporting only): FAX track + EL replays on the
    # top-Q candidate. Cannot change the gate verdict above.
    tr = FAX.build_track(d, top['rep'], top['parts']['t0'], top['parts']['t1'],
                         top['path'], top['Latt'], top['Fl'], top['pts'])
    obs = {int(f): tuple(v['box'] + [v['conf']]) for f, v in tr['trajectory'].items()}
    score_track(out, d, top, tr, obs, boxes, flight, events, gate_evidence=False)


def score_track(out, d, sel, tr, obs, boxes, flight, events, gate_evidence):
    pre = {f: a for f, a in boxes[d].items() if a.get('flight_fraction') == 'PREP'}
    post = {f: a for f, a in boxes[d].items() if a.get('flight_fraction') == 'POST'}
    fl = {f: a for f, a in flight[d].items()}
    lo, hi = min(obs), max(obs)
    ys = [obs[f][1] if f in obs else None for f in range(lo, hi + 1)]
    cs = [obs[f][4] if f in obs else 0.0 for f in range(lo, hi + 1)]
    pts = sel['pts'][lo:hi + 1]
    e3 = EL.propose_events_v3c0(ys, pts, cs, '')
    e4 = V4.propose_events_v4a0(ys, pts, cs, sel['parts']['t0'])
    t0, t1, ta = (events[d][k] for k in ('takeoff', 'water_contact', 'apex'))
    row = out['dives'][d]
    row['non_gate_track'] = {
        'rep': sel['rep'], 'Q': round(sel['Q'], 3), 'gate_evidence': gate_evidence,
        'flight': score_phase(obs, fl),
        'preparation': score_phase(obs, pre),
        'post_entry': score_phase(obs, post),
        'n_obs': len(obs), 'first_s': sel['pts'][lo], 'last_s': sel['pts'][hi],
        'max_gap_s': max((sel['pts'][b] - sel['pts'][a]
                          for a, b in zip(sorted(obs), sorted(obs)[1:])), default=None),
        'backward_stop': tr['backward']['stop'], 'forward_stop': tr['forward']['stop'],
        'human_events': {'takeoff': t0, 'water_contact': t1, 'apex': ta},
        'v3c0': {k: e3.get(k + '_t') for k in ('takeoff', 'apex', 'water_contact')},
        'v4dev': {k: e4.get(k + '_t') for k in ('takeoff', 'apex', 'water_contact')}}
    for tag in ('v3c0', 'v4dev'):
        for evk, h in (('takeoff', t0), ('water_contact', t1), ('apex', ta)):
            v = row['non_gate_track'][tag][evk]
            row['non_gate_track'][tag][evk + '_err'] = round(v - h, 3) if v is not None else None
    r = row['non_gate_track']
    print(d, 'NON-GATE rep=', r['rep'], 'flight=', (r['flight']['hits'], r['flight']['visible']),
          'prep=', (r['preparation']['hits'], r['preparation']['visible']),
          'back=', r['backward_stop']['reason'], 'fwd=', r['forward_stop']['reason'],
          'v3to=', r['v3c0']['takeoff_err'], 'v3apex=', r['v3c0']['apex_err'],
          'v3wc=', r['v3c0']['water_contact_err'],
          'v4to=', r['v4dev']['takeoff_err'], 'v4apex=', r['v4dev']['apex_err'],
          'v4wc=', r['v4dev']['water_contact_err'], flush=True)


if __name__ == "__main__":
    main()
