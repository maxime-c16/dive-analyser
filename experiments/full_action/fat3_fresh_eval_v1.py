"""FAT3 gate record (runs ONCE per freeze; frozen FAX + frozen V4-B0).

Strict predeclared procedure FIRST: emulate the user click via fresh flight
boxes (first Q-ordered candidate passing the frozen recovery rule). If no
candidate qualifies, the dive is recorded unsurfaced (perception failure in
the funnel denominator) with NO conditional track statistics.
Diagnostics on the top-Q candidate (clearly labeled non-gate) follow for
reporting only and cannot change the gate verdict above.

Landmark layer (gate-passing tracks only): frozen V3-C0 baseline replay +
frozen V4-B0 successor; signed/absolute errors for takeoff/apex/contact;
abstention separated from wrong prediction. No thresholds touched.
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
import proposer_event_logic_v4_b0 as V4
from fax_eval_v1 import select_flight, score_phase

FAT3 = ROOT / 'docs' / 'science' / 'localization_annotations_v1' / 'FULL_ACTION_GT_HUMAN_V3_FRESH'
CACHE = json.loads((ROOT / 'runs' / 'full_action_fat3' / 'caches' /
                    'CAND_S3_FAT3_360.json').read_text())
RADIUS = 0.06
OUT = ROOT / 'runs' / 'full_action_fat3' / 'fat3_gate_results.json'


def load_authority():
    man = json.loads((FAT3 / 'MANIFEST.json').read_text())
    assert man['sealed'] and man['authority'] == 'FULL_ACTION_GT_HUMAN_V3_FRESH'
    assert hashlib.sha256(json.dumps(man['files'], sort_keys=True).encode()).hexdigest() == man['digest']
    for name, h in man['files'].items():
        assert hashlib.sha256((FAT3 / name).read_bytes()).hexdigest() == h, name
    boxes, flight = {}, {}
    for name in man['files']:
        if name in ('MANIFEST.json', 'FAT3_EVENTS.json'):
            continue
        a = json.loads((FAT3 / name).read_text())
        d = a['dive_id']
        ff = a.get('flight_fraction') or ''
        if ff.endswith('/8'):
            flight.setdefault(d, {})[a['frame_index']] = a
        elif ff in ('PREP', 'POST'):
            boxes.setdefault(d, {})[a['frame_index']] = a
    events = json.loads((FAT3 / 'FAT3_EVENTS.json').read_text())
    return boxes, flight, events, man['digest'], sorted(man.get('excluded_dives', {}))


def ctr(a):
    b = a['bbox']
    return ((b[0] + b[2]) / 2 / a['width'], (b[1] + b[3]) / 2 / a['height'])


def main():
    assert FAX.RESID_MARGIN == 0.25 and FAX.IOU_MERGE == 0.30 and FAX.FWD_MAX_S == 0.5
    assert FAX.VERSION == 'FAX_V1'
    assert V4.VERSION == 'EVENT_LOGIC_V4_B0' and V4.TAKEOFF_BIAS_S == 0.23
    assert CACHE['model_sha256'] == '3dc07f69cbe3824490f73c14a59ed328ff35fc2da48da2fd4e324acf9bcc4e9a'
    assert CACHE['gt_payload'] == 'NONE'
    assert hashlib.sha256((HERE / 'fax_extension_v1.py').read_bytes()).hexdigest() == \
        '55282fb968cc960919242ee43ef9ebd3db7c13becbd663aab35b3b150306a2ad'
    boxes, flight, events, digest, excluded = load_authority()
    dives = sorted(events)
    out = {'authority': 'FULL_ACTION_GT_HUMAN_V3_FRESH', 'digest': digest,
           'fax_code': hashlib.sha256((HERE / 'fax_extension_v1.py').read_bytes()).hexdigest(),
           'v4b0_code': hashlib.sha256(
               (HERE.parent / 'landmark_pilot' / 'proposer_event_logic_v4_b0.py').read_bytes()).hexdigest(),
           'excluded': excluded, 'dives': {}}
    for d in dives:
        anchors = {f: ctr(a) for f, a in flight[d].items()
                   if a.get('visibility') in ('visible', 'partial') and a.get('bbox')}
        cands = [c for c in select_flight(CACHE, d) if c['rep'] == '360']
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
    selected = [d for d, r in out['dives'].items() if r['verdict'] == 'SELECTED']
    preps = [(d, out['dives'][d]['gate_track']['preparation']) for d in selected]
    pooled_hits = sum(p['hits'] for _, p in preps)
    pooled_vis = sum(p['visible'] for _, p in preps)
    pooled_wrong = sum(len(p['wrong']) for _, p in preps)
    flights_ok = all(out['dives'][d]['gate_track']['flight']['coverage'] >= 0.75 and
                     out['dives'][d]['gate_track']['flight']['purity'] >= 0.75 for d in selected)
    ends_labeled = all(out['dives'][d]['gate_track']['backward_stop']['reason'] and
                       out['dives'][d]['gate_track']['forward_stop']['reason'] for d in selected)
    gate_pass = (len(selected) >= 4 and flights_ok and pooled_wrong == 0 and
                 (pooled_hits / pooled_vis >= 0.5 if pooled_vis else False) and ends_labeled)
    out['gate'] = {'n_selected': len(selected), 'flights_ok': flights_ok,
                   'pooled_prep': [pooled_hits, pooled_vis], 'pooled_wrong': pooled_wrong,
                   'ends_labeled': ends_labeled}
    out['gate_pass'] = bool(gate_pass)
    if len(selected) < 4 and not any(out['dives'][d]['gate_track']['preparation']['wrong'] for d in selected):
        out['gate']['note'] = 'conditional set too small; gate VOID (FAT2 precedent)'
    OUT.write_text(json.dumps(out, indent=1, sort_keys=True))
    print('GATE', 'PASS' if gate_pass else 'NOT-PASS', 'n_selected=', len(selected), '. Wrote', OUT)


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
    pre = {f: a for f, a in boxes.get(d, {}).items() if a.get('flight_fraction') == 'PREP'}
    post = {f: a for f, a in boxes.get(d, {}).items() if a.get('flight_fraction') == 'POST'}
    fl = {f: a for f, a in flight.get(d, {}).items()}
    lo, hi = min(obs), max(obs)
    ys = [obs[f][1] if f in obs else None for f in range(lo, hi + 1)]
    cs = [obs[f][4] if f in obs else 0.0 for f in range(lo, hi + 1)]
    pts = sel['pts'][lo:hi + 1]
    e3 = EL.propose_events_v3c0(ys, pts, cs, '')
    e4 = V4.propose_events_v4b0(ys, pts, cs, sel['parts']['t0'])
    t0, t1, ta = (events[d][k] for k in ('takeoff', 'water_contact', 'apex'))
    row = out['dives'][d]
    key = 'gate_track' if gate_evidence else 'non_gate_track'
    row[key] = {
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
        'v4b0': {k: e4.get(k + '_t') for k in ('takeoff', 'apex', 'water_contact')},
        'v4b0_clamped': e4.get('clamped_to_anchor'),
        'v4b0_abstained': e4.get('takeoff_t') is None}
    for tag in ('v3c0', 'v4b0'):
        for evk, h in (('takeoff', t0), ('water_contact', t1), ('apex', ta)):
            v = row[key][tag][evk]
            row[key][tag][evk + '_err'] = round(v - h, 3) if v is not None else None
    r = row[key]
    print(d, 'GATE' if gate_evidence else 'NON-GATE', 'rep=', r['rep'],
          'flight=', (r['flight']['hits'], r['flight']['visible']),
          'prep=', (r['preparation']['hits'], r['preparation']['visible']),
          'back=', r['backward_stop']['reason'], 'fwd=', r['forward_stop']['reason'],
          'v3to=', r['v3c0']['takeoff_err'], 'v3apex=', r['v3c0']['apex_err'],
          'v3wc=', r['v3c0']['water_contact_err'],
          'v4to=', r['v4b0']['takeoff_err'], 'v4apex=', r['v4b0']['apex_err'],
          'v4wc=', r['v4b0']['water_contact_err'], flush=True)


if __name__ == "__main__":
    main()
