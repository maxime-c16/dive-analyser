#!/usr/bin/env python3
"""DIVE_ANALYZER_FLIGHT_PERCEPTION_SUCCESSOR_V1 — blind HUMAN flight annotation (session 2).

Two authorities collected in one blind session (split: FLIGHT_PERCEPTION_SUCCESSOR_SPLIT_V1):

- FLIGHT_GT_HUMAN_V2_HOLDOUT — the sealed FRESH holdout (13 dives, 10 sessions never
  used by science). Per dive: human takeoff + water contact, then 9 boxes at
  fractions k/8 (k=0..8) of that window; 6 repeat items. Never read by training
  or model-selection code.
- FLIGHT_TRAIN_HUMAN_V1 — new flight training labels (16 dives, 6 other sessions).
  Same events, then 11 boxes at k/10 (k=0..10).

Protocol identical to FLIGHT_GT_HUMAN_V1 (INDEP flow): no detector box, candidate,
track or draft is ever shown; every stored box is drawn by the human; one dive at a
time; holdout dives first. The annotator is not told which set a dive belongs to.
Event scrubbing uses proxy frames; box frames use the HQ edited rendition resampled
to proxy geometry when fps_media_v1 verified an identity spatial map, else the
proxy frame. Boxes are stored in PROXY pixels (202x360) on the proxy PTS timeline.

Commands: serve [--port] | validate | freeze
"""
from __future__ import annotations

import argparse
import datetime
import functools
import hashlib
import json
import sys
import threading
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / 'subject_resolution'))
import fps_media_v1 as fm  # noqa: E402
from fsr_flight_gt_annotation_v1 import _UI as _UI_V1  # noqa: E402  (frozen FGT1 UI, reused)

SETS = {
    'HOLDOUT': {'label': 'FLIGHT_GT_HUMAN_V2_HOLDOUT', 'prefix': 'FGT2H', 'n_frac': 8, 'ks': range(0, 9)},
    'TRAIN_NEW': {'label': 'FLIGHT_TRAIN_HUMAN_V1', 'prefix': 'FTR1', 'n_frac': 10, 'ks': range(0, 11)},
}
WORK = Path(__import__('os').environ.get('FPS_ANNOT_WORK', fm.RUNS / 'flight_gt_annotation_v2'))
DRAFT_PATH = WORK / 'annotations_draft.json'
FREEZE_ROOT = fm.DOC / 'localization_annotations_v1'
N_REPEATS = 6
CTX = 3
UP = 3
PW, PH = 202, 360
LOCK = threading.Lock()


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


@functools.lru_cache(maxsize=None)
def dive_order():
    """Holdout dives first, then new-train dives; each in split-doc order."""
    r = fm.split()['roles']
    return ([('HOLDOUT', str(x['dive_id'])) for x in r['FRESH_FLIGHT_HOLDOUT']['dives']] +
            [('TRAIN_NEW', str(x['dive_id'])) for x in r['TRAIN_NEW_HUMAN_FLIGHT_LABELS']['dives']])


def set_of(d):
    return dict((b, a) for a, b in dive_order())[str(d)]


def nearest_idx(pts, t):
    return min(range(len(pts)), key=lambda i: abs(pts[i] - t))


def ev_id(d, ev):
    return f"{SETS[set_of(d)]['prefix']}_EV_{d}_{ev}"


def frac_items(d, pts, t0, t1):
    s = SETS[set_of(d)]
    out, seen = [], set()
    for k in s['ks']:
        fi = nearest_idx(pts, t0 + k / s['n_frac'] * (t1 - t0))
        if fi in seen:
            continue
        seen.add(fi)
        out.append({'id': f"{s['prefix']}_{d}_f{fi:05d}", 'dive_id': d, 'set': set_of(d), 'frame_index': fi,
                    'pts_s': pts[fi], 'flight_fraction': f"{k}/{s['n_frac']}",
                    'window_source': 'HUMAN_EVENT_MARKED_IN_THIS_TOOL', 'kind': 'box'})
    return out


def dive_window(draft, d):
    a, b = draft['events'].get(ev_id(d, 'takeoff')), draft['events'].get(ev_id(d, 'water_contact'))
    if a and b and b['pts_s'] > a['pts_s']:
        return a, b
    return None


def build_queue(draft=None):
    """steps = for each dive: takeoff, water_contact, boxes (once both events set); then repeats."""
    draft = draft or {'items': {}, 'events': {}}
    steps, events, hold_items = [], [], []
    excluded = draft.get('excluded_dives', {})
    for sname, d in dive_order():
        if d in excluded:
            continue
        pts = fm.proxy_pts(d)
        for ev in ('takeoff', 'water_contact'):
            e = {'id': ev_id(d, ev), 'dive_id': d, 'set': sname, 'event': ev, 'n_frames': len(pts), 'kind': 'event'}
            events.append(e)
            steps.append(e)
        w = dive_window(draft, d)
        if w:
            its = frac_items(d, pts, w[0]['pts_s'], w[1]['pts_s'])
            steps += its
            if sname == 'HOLDOUT':
                hold_items.append(its)
    # deterministic repeats: the mid-flight (k=4/8) holdout item of every 2nd holdout dive (dive order)
    reps = []
    for its in hold_items[::2][:N_REPEATS]:
        mid = [i for i in its if i['flight_fraction'] == '4/8'] or its[len(its) // 2:len(its) // 2 + 1]
        reps.append(dict(mid[0], id=mid[0]['id'] + '_R', repeat_of=mid[0]['id']))
    steps += reps
    items = [s for s in steps if s['kind'] == 'box']
    return {'events': events, 'items': items, 'steps': steps,
            'created_rule': 'HOLDOUT k/8 (k=0..8), TRAIN_NEW k/10 (k=0..10) of the HUMAN flight window; nearest proxy frame by PTS'}


# ------------------------------------------------------------ frames ----------

def scrub_path(d, fi):
    return WORK / 'scrub' / d / f'f{fi:05d}.jpg'


def box_path(d, fi):
    return WORK / 'box' / d / f'f{fi:05d}.jpg'


def _man():
    p = WORK / 'frames_manifest.json'
    return json.loads(p.read_text()) if p.exists() else {'box': {}, 'scrub': {}}


def _save_man(m):
    (WORK / 'frames_manifest.json').write_text(json.dumps(m, indent=1, sort_keys=True))


def extract_scrub(d):
    import cv2
    pts = fm.proxy_pts(d)
    if all(scrub_path(d, i).exists() for i in range(len(pts))):
        return
    p, sha = fm.verified_proxy(d)
    (WORK / 'scrub' / d).mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(p))
    i = 0
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        cv2.imwrite(str(scrub_path(d, i)), cv2.resize(fr, (PW * 2, PH * 2), interpolation=cv2.INTER_CUBIC),
                    [cv2.IMWRITE_JPEG_QUALITY, 85])
        i += 1
    cap.release()
    assert i == len(pts), (d, i, len(pts))
    m = _man()
    m['scrub'][d] = {'representation': 'proxy_360p_decoded_upscaled_x2', 'proxy_sha256': sha, 'n': i}
    _save_man(m)


def extract_box(d, fis):
    """Box frames (+-CTX context): HQ resampled to proxy geometry if the map is verified, else proxy."""
    import cv2
    import numpy as np
    pts = fm.proxy_pts(d)
    want = sorted({f + o for f in fis for o in range(-CTX, CTX + 1) if 0 <= f + o < len(pts)})
    want = [i for i in want if not box_path(d, i).exists()]
    if not want:
        return
    (WORK / 'box' / d).mkdir(parents=True, exist_ok=True)
    m = _man()
    p, psha = fm.verified_proxy(d)
    rec = m['box'].setdefault(d, {})
    if fm.hq_ok(d):
        e = fm.hq_entry(d)
        mp = e['map']
        if (mp['x_off'], mp['x_span'], mp['y_off'], mp['y_span']) == (0.0, 1.0, 0.0, 1.0):
            hp = []
            cap = cv2.VideoCapture(e['path'])
            while cap.grab():
                hp.append(cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0)
            cap.release()
            ha = np.array(hp)
            targets = {}
            for i in want:
                j = int(np.argmin(np.abs(ha - (pts[i] - mp['dt']))))
                if abs(ha[j] - (pts[i] - mp['dt'])) <= 0.5 / 24:
                    targets.setdefault(j, []).append(i)
            cap = cv2.VideoCapture(e['path'])
            j = 0
            while targets and j <= max(targets):
                ok, fr = cap.read()
                if not ok:
                    break
                for i in targets.get(j, []):
                    cv2.imwrite(str(box_path(d, i)), cv2.resize(fr, (PW * UP, PH * UP), interpolation=cv2.INTER_AREA),
                                [cv2.IMWRITE_JPEG_QUALITY, 92])
                    rec[str(i)] = {'representation': 'hq_display_resampled_to_proxy_geometry',
                                   'hq_sha256': e['sha256'], 'hq_frame': j, 'proxy_sha256': psha}
                j += 1
            cap.release()
    need = {i for i in want if not box_path(d, i).exists()}
    if need:
        cap = cv2.VideoCapture(str(p))
        i = 0
        while i <= max(need):
            ok, fr = cap.read()
            if not ok:
                break
            if i in need:
                cv2.imwrite(str(box_path(d, i)), cv2.resize(fr, (PW * 2, PH * 2), interpolation=cv2.INTER_CUBIC),
                            [cv2.IMWRITE_JPEG_QUALITY, 90])
                rec[str(i)] = {'representation': 'proxy_360p_native_decoded_frame_upscaled', 'proxy_sha256': psha}
            i += 1
        cap.release()
    _save_man(m)


def ensure_dive_frames(draft, d):
    w = dive_window(draft, d)
    if w:
        extract_box(d, [it['frame_index'] for it in frac_items(d, fm.proxy_pts(d), w[0]['pts_s'], w[1]['pts_s'])])


# ------------------------------------------------------------ draft -----------

def load_draft():
    if DRAFT_PATH.exists():
        return json.loads(DRAFT_PATH.read_text())
    return {'items': {}, 'events': {}}


def save_draft(draft):
    tmp = DRAFT_PATH.with_suffix('.tmp')
    tmp.write_text(json.dumps(draft, indent=1, sort_keys=True))
    tmp.replace(DRAFT_PATH)


_UI = (_UI_V1
       .replace('<title>Flight GT (human)</title>', '<title>Flight GT session 2 (human)</title>')
       .replace("function src(d,f){return `/frames/${d}/f${String(f).padStart(5,'0')}.jpg`;}",
                "function src(d,f){return `/box/${d}/f${String(f).padStart(5,'0')}.jpg`;}"
                "function ssrc(d,f){return `/scrub/${d}/f${String(f).padStart(5,'0')}.jpg`;}")
       .replace('function evshow(){setimg(src(list[pos].dive_id,evframe));',
                'function evshow(){setimg(ssrc(list[pos].dive_id,evframe));')
       .replace('<div class="row"><button id="back">',
                '<button class="r" id="excl">DIVE UNLABELABLE (x) &mdash; cannot see the diver reliably</button>\n <div class="row"><button id="back">')
       .replace("(async()=>{fit();await refresh();pos=firstOpen();show();})();",
                "async function excl(){const it=list[pos];if(!it||it.repeat_of)return;"
                "if(!confirm('Remove the WHOLE dive '+it.dive_id+' from the session (diver not reliably visible)?'))return;"
                "const r=await api('/api/exclude',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({dive_id:it.dive_id})});"
                "if(!r.ok){toast(r.error||'error','rgba(183,28,28,.95)');return;}"
                "toast('✔ dive '+it.dive_id+' removed (unlabelable)','rgba(183,28,28,.95)');await refresh();pos=firstOpen();show();}"
                "$('excl').onclick=e=>{e.currentTarget.blur();excl();};"
                "window.addEventListener('keydown',e=>{if(e.key=='x'&&!e.repeat){e.preventDefault();excl();}});"
                "(async()=>{fit();await refresh();pos=firstOpen();show();})();")
       .replace("' (boxes for event-less dives appear after their 2 events are set)'",
                "' (a dive\\'s boxes appear once its takeoff and water contact are set)'"))
assert _UI.count('ssrc(') == 2 and '/frames/' not in _UI, 'UI patch drifted'


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype='application/json'):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj).encode())

    def do_GET(self):
        if self.path in ('/', '/index.html'):
            return self._send(200, _UI.encode(), 'text/html')
        if self.path == '/api/state':
            with LOCK:
                draft = load_draft()
            q = build_queue(draft)
            steps = []
            for s in q['steps']:
                pub = {k: v for k, v in s.items() if k != 'set'}  # annotator is not told the set
                if s['kind'] == 'event':
                    a = draft['events'].get(s['id'])
                    sugg = None
                    if s['event'] == 'water_contact':
                        t = draft['events'].get(s['id'].replace('water_contact', 'takeoff'))
                        sugg = min(t['frame_index'] + 1, s['n_frames'] - 1) if t else None
                    steps.append({**pub, 'resolved': bool(a), 'frame_index': a['frame_index'] if a else None,
                                  'suggest_from': sugg})
                else:
                    a = draft['items'].get(s['id'])
                    steps.append({**pub, 'resolved': bool(a), 'bbox': a.get('bbox') if a else None,
                                  'visibility': a.get('visibility') if a else None})
            pending = any(not s['resolved'] for s in steps if s['kind'] == 'event')
            return self._json({'steps': steps, 'pending_indep': pending})
        for kind in ('scrub', 'box'):
            if self.path.startswith(f'/{kind}/'):
                fp = (WORK / self.path.lstrip('/')).resolve()
                if not str(fp).startswith(str((WORK / kind).resolve())) or not fp.exists():
                    return self._send(404, b'not found', 'text/plain')
                return self._send(200, fp.read_bytes(), 'image/jpeg')
        self._send(404, b'not found', 'text/plain')

    def do_POST(self):
        n = int(self.headers.get('Content-Length', 0))
        req = json.loads(self.rfile.read(n))
        with LOCK:
            draft = load_draft()
            if self.path == '/api/event':
                q = build_queue(draft)
                ev = {e['id']: e for e in q['events']}.get(req.get('id'))
                fi = req.get('frame_index')
                if not ev or not isinstance(fi, int) or not 0 <= fi < ev['n_frames']:
                    return self._json({'ok': False, 'error': 'bad event'}, 400)
                pts = fm.proxy_pts(ev['dive_id'])
                other_id = ev['id'].replace('takeoff', 'water_contact') if ev['event'] == 'takeoff' \
                    else ev['id'].replace('water_contact', 'takeoff')
                other = draft['events'].get(other_id)
                if other and not req.get('confirm'):
                    t0, t1 = (pts[fi], pts[other['frame_index']]) if ev['event'] == 'takeoff' \
                        else (pts[other['frame_index']], pts[fi])
                    if t1 <= t0:
                        return self._json({'ok': False, 'error': 'water contact must be after takeoff'}, 400)
                    if not 0.3 <= t1 - t0 <= 2.5:
                        return self._json({'ok': True, 'warn': f'Flight duration takeoff->water = {t1 - t0:.2f}s looks unusual (typical 0.6-1.8s).'})
                prev = draft['events'].get(ev['id'])
                if prev and prev['frame_index'] != fi:
                    old = [k for k, v in draft['items'].items() if v['dive_id'] == ev['dive_id']]
                    for k in old:
                        draft.setdefault('superseded', {})[k + '@' + now()] = {**draft['items'].pop(k),
                                                                                'reason': 'event_frame_changed'}
                    draft.setdefault('superseded_events', {})[ev['id'] + '@' + now()] = prev
                draft['events'][ev['id']] = {'dive_id': ev['dive_id'], 'event': ev['event'], 'frame_index': fi,
                                             'pts_s': pts[fi], 'authority': 'HUMAN_REVIEWED', 'annotator': 'maxime',
                                             'created_at': now()}
                save_draft(draft)
                ensure_dive_frames(draft, ev['dive_id'])
                return self._json({'ok': True})
            if self.path == '/api/exclude':
                d = str(req.get('dive_id'))
                if d not in dict((b, a) for a, b in dive_order()):
                    return self._json({'ok': False, 'error': 'bad dive'}, 400)
                draft.setdefault('excluded_dives', {})[d] = {
                    'reason': 'HUMAN_UNLABELABLE: annotator cannot reliably see the diver (e.g. phone recording of a replay screen)',
                    'set': set_of(d), 'annotator': 'maxime', 'at': now()}
                for k in [k for k, v in draft['items'].items() if v['dive_id'] == d]:
                    draft.setdefault('superseded', {})[k + '@' + now()] = {**draft['items'].pop(k), 'reason': 'dive_excluded'}
                for k in [k for k, v in draft['events'].items() if v['dive_id'] == d]:
                    draft.setdefault('superseded_events', {})[k + '@' + now()] = draft['events'].pop(k)
                save_draft(draft)
                return self._json({'ok': True})
            if self.path == '/api/annotate':
                q = build_queue(draft)
                it = {i['id']: i for i in q['items']}.get(req.get('id'))
                vis, bbox = req.get('visibility'), req.get('bbox')
                if not it or vis not in ('visible', 'partial', 'not_visible', 'ambiguous'):
                    return self._json({'ok': False, 'error': 'bad item/visibility'}, 400)
                if vis in ('visible', 'partial'):
                    if not (isinstance(bbox, list) and len(bbox) == 4 and bbox[2] > bbox[0] and bbox[3] > bbox[1]):
                        return self._json({'ok': False, 'error': 'bad bbox'}, 400)
                    bbox = [max(0.0, float(bbox[0])), max(0.0, float(bbox[1])),
                            min(float(PW), float(bbox[2])), min(float(PH), float(bbox[3]))]
                else:
                    bbox = None
                if not box_path(it['dive_id'], it['frame_index']).exists():
                    return self._json({'ok': False, 'error': 'frame image missing'}, 400)
                fmeta = _man()['box'].get(it['dive_id'], {}).get(str(it['frame_index']), {})
                draft['items'][it['id']] = {
                    **{k: it[k] for k in ('dive_id', 'set', 'frame_index', 'pts_s', 'flight_fraction', 'window_source')},
                    'repeat_of': it.get('repeat_of'), 'bbox': bbox, 'visibility': vis,
                    'authority': 'HUMAN_REVIEWED', 'annotator': 'maxime', 'method': 'human_drawn_blind',
                    'source_identity': 'intended Dive Analyzer subject (diver performing the dive)',
                    'representation': fmeta.get('representation'), 'display_hq_sha256': fmeta.get('hq_sha256'),
                    'media_sha256': fmeta.get('proxy_sha256'),
                    'image_sha256': fm.sha256_file(box_path(it['dive_id'], it['frame_index'])),
                    'width': PW, 'height': PH, 'coordinate_frame': 'proxy_pixels_202x360', 'created_at': now()}
                save_draft(draft)
                return self._json({'ok': True})
        self._send(404, b'not found', 'text/plain')


def prepare():
    WORK.mkdir(parents=True, exist_ok=True)
    if not DRAFT_PATH.exists():
        save_draft({'items': {}, 'events': {}})
    draft = load_draft()
    for _, d in dive_order():
        fm.assert_allowed(d)
        extract_scrub(d)
        ensure_dive_frames(draft, d)


def cmd_serve(args):
    prepare()
    srv = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    print(f'flight GT session 2 UI: http://127.0.0.1:{args.port}', flush=True)
    srv.serve_forever()


def cmd_validate(args, quiet=False):
    draft = load_draft()
    q = build_queue(draft)
    miss_ev = [e['id'] for e in q['events'] if e['id'] not in draft['events']]
    miss = [i['id'] for i in q['items'] if i['id'] not in draft['items']]
    rep = []
    for i in q['items']:
        if i.get('repeat_of') and i['id'] in draft['items'] and i['repeat_of'] in draft['items']:
            a, b = draft['items'][i['id']], draft['items'][i['repeat_of']]
            if a['bbox'] and b['bbox']:
                ca = ((a['bbox'][0] + a['bbox'][2]) / 2 / PW, (a['bbox'][1] + a['bbox'][3]) / 2 / PH)
                cb = ((b['bbox'][0] + b['bbox'][2]) / 2 / PW, (b['bbox'][1] + b['bbox'][3]) / 2 / PH)
                rep.append(round(((ca[0] - cb[0]) ** 2 + (ca[1] - cb[1]) ** 2) ** .5, 4))
            else:
                rep.append(None if a['visibility'] == b['visibility'] else 'VISIBILITY_DISAGREE')
    # counts only (no box geometry is printed: the holdout stays sealed from the model designer)
    per_set = {s: dict(Counter(v['visibility'] for v in draft['items'].values() if v['set'] == s)) for s in SETS}
    durations = {d: round(w[1]['pts_s'] - w[0]['pts_s'], 3) for _, d in dive_order()
                 if (w := dive_window(draft, d)) and set_of(d) == 'TRAIN_NEW'}
    rpt = {'missing_events': len(miss_ev), 'missing_items': len(miss), 'visibility_per_set': per_set,
           'repeat_center_dist_norm': rep, 'train_flight_durations_s': durations,
           'complete': not miss_ev and not miss}
    if not quiet:
        print(json.dumps(rpt, indent=1))
    return rpt


def cmd_freeze(args):
    rpt = cmd_validate(args, quiet=True)
    assert rpt['complete'], 'incomplete'
    draft = load_draft()
    q = build_queue(draft)
    live = {i['id'] for i in q['items']}
    out = {}
    for sname, s in SETS.items():
        fdir = FREEZE_ROOT / s['label']
        fdir.mkdir(parents=True, exist_ok=True)
        hashes = {}
        for k, v in sorted(draft['items'].items()):
            if k in live and v['set'] == sname:
                p = fdir / f'{k}.json'
                p.write_text(json.dumps({'id': k, **v}, indent=1, sort_keys=True) + '\n')
                hashes[p.name] = fm.sha256_file(p)
        evs = {k: v for k, v in draft['events'].items() if set_of(v['dive_id']) == sname}
        excl = {d: v for d, v in draft.get('excluded_dives', {}).items() if v['set'] == sname}
        ev = fdir / f"{s['prefix']}_EVENTS.json"
        ev.write_text(json.dumps(evs, indent=1, sort_keys=True) + '\n')
        hashes[ev.name] = fm.sha256_file(ev)
        digest = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
        (fdir / 'MANIFEST.json').write_text(json.dumps(
            {'label': s['label'], 'frozen_at': now(), 'digest': digest, 'files': hashes,
             'split_authority': 'FLIGHT_PERCEPTION_SUCCESSOR_SPLIT_V1',
             'dives': [d for sn, d in dive_order() if sn == sname and d not in excl],
             'excluded_dives_human_unlabelable': excl,
             'visibility': rpt['visibility_per_set'][sname],
             'repeat_center_dist_norm': rpt['repeat_center_dist_norm'] if sname == 'HOLDOUT' else None,
             'queue_rule': q['created_rule'],
             'superseded_count': sum(1 for v in draft.get('superseded', {}).values() if v.get('set') == sname),
             'blind': 'no detector/candidate/draft shown; every box human-drawn; annotator not told the set',
             'sealed': sname == 'HOLDOUT'}, indent=1, sort_keys=True) + '\n')
        out[s['label']] = digest
        print('frozen', s['label'], digest)
    return out


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['serve', 'validate', 'freeze', 'prepare'])
    ap.add_argument('--port', type=int, default=8766)
    a = ap.parse_args()
    {'serve': cmd_serve, 'validate': cmd_validate, 'freeze': cmd_freeze, 'prepare': lambda _a: prepare()}[a.cmd](a)
