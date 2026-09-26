"""FAT2 fresh full-action HUMAN annotation queue (3 session-disjoint DEVELOPMENT dives).

Dives: 1190/s75 (201A 1m), 1279/s80 (203C 1m), 2838/s202 (103B 1m).
All are UNUSED in every training/consumed/DEV role; none has prior flight
boxes or event times (the V2 holdout covered 9 other dives). Everything in
this task is new HUMAN authority: takeoff, water contact, apex (+independent
apex repeat), flight boxes at k/8 of the marked window, preparation boxes
every 0.5 s, post-entry boxes, one blind box repeat.
Backup: 1194/s75 swap-only for 1190 (same session; never added alongside).

Blindness: the UI shows verified raw proxy frames (HQ-resampled only for
1190 box frames under its VERIFIED identity map). No S3 boxes, FSR
candidates, FAX tracks, scores, or overlays are shown or reachable.
S3 caches + FSR selection viability are sealed until the freeze.

Reuse: frame extraction + HTTP server + base UI come from
fpsr2_flight_gt_annotation (imported, NOT modified) via module-global
patching. Apex event handling is wrapped (range-checked) in this module.

Commands: serve [--port] | validate | freeze
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'experiments' / 'flight_perception'))
import fpsr2_flight_gt_annotation as U  # noqa: E402 (infra reuse; file untouched)

MAC = Path('/Users/maximecauchy/.perso')
SUCCESSOR = MAC / 'diveanalyzer-flight-perception-successor'
PROXIES = SUCCESSOR / 'media/fps_v1/proxies'
PTS_INDEX = SUCCESSOR / 'runs/flight_perception_successor_v1/PROXY_PTS_INDEX_V1.json'
HQ_REGISTRY = SUCCESSOR / 'runs/flight_perception_successor_v1/HQ_REGISTRY_V1.json'
SPLIT = ROOT / 'docs' / 'science' / 'FLIGHT_PERCEPTION_SUCCESSOR_SPLIT_V1.json'
FGT2H_EVENTS = ROOT / 'docs' / 'science' / 'localization_annotations_v1' / 'FLIGHT_GT_HUMAN_V2_HOLDOUT' / 'FGT2H_EVENTS.json'

DIVES = ('1190', '1279', '2838')
SET = 'FRESH'
WORK = ROOT / 'runs' / 'fat2_annotation'
DRAFT_PATH = WORK / 'annotations_draft.json'
FREEZE_DIRNAME = 'FULL_ACTION_GT_HUMAN_V2_FRESH'

CACHE360 = ROOT / 'runs' / 'full_action_fax_v1' / 'caches' / 'CAND_S3_FAT2_360.json'


class Media:
    _pts = None

    @staticmethod
    def _index():
        return json.loads(PTS_INDEX.read_text())

    @staticmethod
    def proxy_pts(d):
        assert d in DIVES
        if d == '1279':
            # No upstream PTS index for this reserve dive: decode-recorded
            # timeline from the S3 cache build (same decode method, proxy
            # timeline; self-consistent for selection/scoring/annotation).
            c = json.loads(CACHE360.read_text())
            assert d in c['dives'], 'build the 1279 S3 cache first (records decode PTS)'
            return [f['pts_s'] for f in c['dives'][d]['frames']]
        return list(Media._index()[d]['pts'])

    @staticmethod
    def proxy_size(d):
        assert d in DIVES
        return (202, 360)

    @staticmethod
    def sha256_file(p):
        return hashlib.sha256(Path(p).read_bytes()).hexdigest()

    @staticmethod
    def verified_proxy(d):
        assert d in DIVES
        p = PROXIES / f'{d}.mp4'
        sha = Media.sha256_file(p)
        if d in ('1190', '2838'):
            expected = next(x['proxy_360p_sha256'] for x in
                            json.loads(SPLIT.read_text())['roles']['FRESH_FLIGHT_HOLDOUT']['dives']
                            if str(x['dive_id']) == d)
            assert sha == expected, (d, 'proxy SHA mismatch')
        else:
            assert sha == '084d29b09aee095441a0c70c512ca9f5178d9a76942a570f5669eb449b102fbf', (d, sha)
        return p, sha

    @staticmethod
    def hq_ok(d):
        return d == '1190'

    @staticmethod
    def hq_entry(d):
        assert d == '1190'
        e = json.loads(HQ_REGISTRY.read_text())['1190']
        assert e['status'] == 'VERIFIED' and e['map'] == {
            'dt': 0.0, 'x_off': 0.0, 'x_span': 1.0, 'y_off': 0.0, 'y_span': 1.0}
        p = Path(e['path'])
        assert Media.sha256_file(p) == e['sha256']
        return {'path': str(p), 'sha256': e['sha256'], 'map': e['map']}


def fgt2h_window(d):
    ev = json.loads(FGT2H_EVENTS.read_text())
    return ev[f'FGT2H_EV_{d}_takeoff']['pts_s'], ev[f'FGT2H_EV_{d}_water_contact']['pts_s']


def nearest(pts, t):
    return min(range(len(pts)), key=lambda i: abs(pts[i] - t))


def fixed_prep_post(d, t0, t1, window_source):
    """FAT1-identical rule: PREP every 0.5 s from clip start to >= 0.1 s
    before takeoff; POST +0.1/+0.3/+0.5 s after contact; nearest recorded PTS."""
    pts = Media.proxy_pts(d)
    w, h = Media.proxy_size(d)
    out, seen = [], set()
    for k in range(int((t0 - .10) / .5) + 1):
        fi = nearest(pts, k * .5)
        if fi in seen:
            continue
        seen.add(fi)
        out.append({'id': f'FAT2_{d}_f{fi:05d}', 'dive_id': d, 'set': SET,
                    'frame_index': fi, 'pts_s': pts[fi], 'flight_fraction': 'PREP',
                    'window_source': window_source, 'kind': 'box', 'width': w, 'height': h})
    for dt in (.10, .30, .50):
        if t1 + dt > pts[-1]:
            continue
        fi = nearest(pts, t1 + dt)
        if fi in seen:
            continue
        seen.add(fi)
        out.append({'id': f'FAT2_{d}_f{fi:05d}', 'dive_id': d, 'set': SET,
                    'frame_index': fi, 'pts_s': pts[fi], 'flight_fraction': 'POST',
                    'window_source': window_source, 'kind': 'box', 'width': w, 'height': h})
    return out


def flight_eighths(d, t0, t1, window_source):
    pts = Media.proxy_pts(d)
    w, h = Media.proxy_size(d)
    out, seen = [], set()
    for k in range(9):
        fi = nearest(pts, t0 + k / 8 * (t1 - t0))
        if fi in seen:
            continue
        seen.add(fi)
        out.append({'id': f'FAT2_{d}_fl_f{fi:05d}', 'dive_id': d, 'set': SET,
                    'frame_index': fi, 'pts_s': pts[fi], 'flight_fraction': f'{k}/8',
                    'window_source': window_source, 'kind': 'box', 'width': w, 'height': h})
    return out


def apex_events(d, n_frames):
    w, h = Media.proxy_size(d)
    return [{'id': f'FAT2_{d}_apex', 'dive_id': d, 'set': SET, 'event': 'apex',
             'n_frames': n_frames, 'kind': 'event', 'width': w, 'height': h},
            {'id': f'FAT2_{d}_apex_R', 'dive_id': d, 'set': SET, 'event': 'apex',
             'n_frames': n_frames, 'kind': 'event', 'width': w, 'height': h,
             'repeat_of': f'FAT2_{d}_apex'}]


def build_queue(draft=None):
    """Per dive: takeoff -> water_contact -> apex -> apex_R event steps;
    once takeoff+water_contact are marked, window-derived boxes appear
    (flight k/8, prep/post rule). Uniform fresh authority for all dives."""
    draft = draft or {'items': {}, 'events': {}}
    excluded = set(draft.get('excluded_dives', {}))
    steps, events, items = [], [], []
    for d in DIVES:
        if d in excluded:
            continue
        pts = Media.proxy_pts(d)
        w, h = Media.proxy_size(d)
        for ev in ('takeoff', 'water_contact'):
            e = {'id': f'FAT2_{d}_{ev}', 'dive_id': d, 'set': SET, 'event': ev,
                 'n_frames': len(pts), 'kind': 'event', 'width': w, 'height': h}
            steps.append(e)
        a, b = draft['events'].get(f'FAT2_{d}_takeoff'), draft['events'].get(f'FAT2_{d}_water_contact')
        if a and b and b['pts_s'] > a['pts_s']:
            ws = 'HUMAN_EVENT_MARKED_IN_THIS_TOOL'
            steps += flight_eighths(d, a['pts_s'], b['pts_s'], ws)
            steps += fixed_prep_post(d, a['pts_s'], b['pts_s'], ws)
        steps += apex_events(d, len(pts))
    for s in steps:
        (events if s['kind'] == 'event' else items).append(s)
    # deterministic blind box repeat: middle PREP item of 1279 (resolves with events)
    preps = [i for i in items if i['dive_id'] == '1279' and i['flight_fraction'] == 'PREP']
    if preps:
        mid = preps[len(preps) // 2]
        r = dict(mid, id=mid['id'] + '_R', repeat_of=mid['id'])
        items.append(r)
        steps.append(r)
    return {'events': events, 'items': items, 'steps': steps,
            'created_rule': 'Per dive: takeoff, water contact (scrub), apex + independent apex repeat '
                            '(scrub, constrained to the marked window); then flight k/8 boxes, PREP every 0.5s '
                            'clip-start to >=0.1s pre-takeoff, POST +0.1/+0.3/+0.5; one blind box repeat '
                            '(1279 mid-prep). Nearest recorded proxy PTS throughout.'}


def ensure_dive_frames(draft, d):
    q = build_queue(draft)
    U.extract_box(d, [it['frame_index'] for it in q['items'] if it['dive_id'] == d])


def apex_window(d, draft):
    """(lo_pts, hi_pts) constraining an apex pick (fresh marked window)."""
    a, b = draft['events'].get(f'FAT2_{d}_takeoff'), draft['events'].get(f'FAT2_{d}_water_contact')
    if a and b:
        return a['pts_s'], b['pts_s']
    return None


class Handler(U.Handler):
    def log_request_line(self):
        try:
            with open(WORK / 'requests.log', 'a') as f:
                f.write(f'{U.now()} {self.command} {self.path}\n')
        except Exception:
            pass

    def do_GET(self):
        self.log_request_line()
        return super().do_GET()

    def do_POST(self):
        if self.path == '/api/event':
            import io
            n = int(self.headers.get('Content-Length', 0))
            raw = self.rfile.read(n)
            try:
                req = json.loads(raw)
            except Exception:
                return self._json({'ok': False, 'error': 'bad json'}, 400)
            with U.LOCK:
                draft = U.load_draft()
                q = build_queue(draft)
                ev = {e['id']: e for e in q['events']}.get(req.get('id'))
                fi = req.get('frame_index')
                if ev is not None and ev.get('event') == 'apex' and ev['id'] in (
                        f'FAT2_{ev["dive_id"]}_apex', f'FAT2_{ev["dive_id"]}_apex_R'):
                    pts = Media.proxy_pts(ev['dive_id'])
                    if not isinstance(fi, int) or not 0 <= fi < ev['n_frames']:
                        return self._json({'ok': False, 'error': 'bad apex frame'}, 400)
                    win = apex_window(ev['dive_id'], draft)
                    if win is None:
                        return self._json(
                            {'ok': False,
                             'error': 'mark takeoff and water contact for this dive first'}, 400)
                    if not (win[0] - 1e-9 <= pts[fi] <= win[1] + 1e-9):
                        return self._json(
                            {'ok': False,
                             'error': f'apex must lie between takeoff ({win[0]:.2f}s) and water contact ({win[1]:.2f}s)'},
                            400)
                    prev = draft['events'].get(ev['id'])
                    if prev and prev['frame_index'] != fi:
                        draft.setdefault('superseded_events', {})[ev['id'] + '@' + U.now()] = prev
                    draft['events'][ev['id']] = {
                        'dive_id': ev['dive_id'], 'event': 'apex', 'frame_index': fi,
                        'pts_s': pts[fi], 'authority': 'HUMAN_REVIEWED', 'annotator': 'maxime',
                        'repeat_of': ev.get('repeat_of'), 'created_at': U.now()}
                    U.save_draft(draft)
                    return self._json({'ok': True})
            # Not an apex mark: replay the body for the base handler (it reads
            # the stream itself). Never let the base see a consumed stream.
            self.rfile = io.BytesIO(raw)
            return super().do_POST()
        return super().do_POST()


def patch_tool():
    U.fm = Media
    U.WORK = WORK
    U.DRAFT_PATH = DRAFT_PATH
    U.build_queue = build_queue
    U.dive_order = lambda: [(SET, d) for d in DIVES]
    U.ensure_dive_frames = ensure_dive_frames
    U._UI = U._UI.replace('Flight GT session 3 (human)', 'FAT2 full-action GT (human, blind)')
    U._UI = U._UI.replace(
        "' (a dive\\'s boxes appear once its takeoff and water contact are set)'",
        "' (1279 boxes appear once its takeoff and water contact are set; apex picks lie inside the flight window)'")
    assert 'FAT2 full-action GT' in U._UI


def queue_manifest():
    pts = {d: Media.proxy_pts(d) for d in DIVES}
    q = build_queue({'items': {}, 'events': {}})
    return {'authority': 'FULL_ACTION_GT_HUMAN_V2_FRESH (queue; labels pending)',
            'dives': list(DIVES), 'sessions': {'1190': 75, '1279': 80, '2838': 202},
            'codes': {'1190': '201A', '1279': '203C', '2838': '103B'},
            'backup': '1194/s75 swap-only for 1190 (same session; never added alongside)',
            'reps': {'1190': ['360', 'hq-verified'], '1279': ['360'], '2838': ['360']},
            'created_rule': q['created_rule'],
            'n_event_steps': len(q['events']),
            'media_sha256': {d: Media.verified_proxy(d)[1] for d in DIVES},
            'pts_source': {'1190': 'successor PROXY_PTS_INDEX_V1', '2838': 'successor PROXY_PTS_INDEX_V1',
                           '1279': 'decode-recorded (no upstream index; same cv2 method as cache build)'},
            'blind': 'Raw proxy frames only (HQ-resampled box frames for 1190 under its VERIFIED identity map). '
                     'No S3 boxes, FSR candidates, FAX tracks, scores, or overlays shown or reachable. '
                     'S3 caches + FSR selection are sealed until the freeze.'}


def cmd_serve(args):
    from http.server import ThreadingHTTPServer
    patch_tool()
    WORK.mkdir(parents=True, exist_ok=True)
    if not DRAFT_PATH.exists():
        U.save_draft({'items': {}, 'events': {}})
    draft = U.load_draft()
    for d in DIVES:
        Media.verified_proxy(d)
        U.extract_scrub(d)
    (WORK / 'QUEUE_MANIFEST.json').write_text(json.dumps(queue_manifest(), indent=1, sort_keys=True) + '\n')
    srv = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    print(f'FAT2 annotation UI: http://127.0.0.1:{args.port}', flush=True)
    srv.serve_forever()


def cmd_validate(args):
    patch_tool()
    draft = U.load_draft()
    q = build_queue(draft)
    miss_ev = [e['id'] for e in q['events'] if e['id'] not in draft['events']]
    miss = [i['id'] for i in q['items'] if i['id'] not in draft['items']]
    # counts only: box geometry stays sealed from the designer
    import collections
    per = {d: dict(collections.Counter(v['visibility'] for v in draft['items'].values() if v['dive_id'] == d))
           for d in DIVES}
    apex = {}
    for d in DIVES:
        a, b = draft['events'].get(f'FAT2_{d}_apex'), draft['events'].get(f'FAT2_{d}_apex_R')
        if a and b:
            apex[d] = round(abs(a['pts_s'] - b['pts_s']), 4)
    print(json.dumps({'missing_events': miss_ev, 'missing_items': miss, 'visibility_per_dive': per,
                      'apex_repeat_agreement_s': apex,
                      'excluded_dives': sorted(draft.get('excluded_dives', {})),
                      'complete': not miss_ev and not miss and not draft.get('excluded_dives')}, indent=1))


def cmd_freeze(args):
    patch_tool()
    draft = U.load_draft()
    assert not draft.get('excluded_dives'), 'excluded dive(s) need a queue revision before freezing'
    q = build_queue(draft)
    assert not [e['id'] for e in q['events'] if e['id'] not in draft['events']], 'events incomplete'
    assert not [i['id'] for i in q['items'] if i['id'] not in draft['items']], 'items incomplete'
    dst = ROOT / 'docs' / 'science' / 'localization_annotations_v1' / FREEZE_DIRNAME
    assert not dst.exists(), 'authority already frozen; never overwrite'
    dst.mkdir(parents=True)
    files = {}
    for key in sorted(set(draft['items']) | set(draft['events'])):
        a = draft['items'].get(key) or draft['events'].get(key)
        p = dst / (key + '.json')
        p.write_text(json.dumps(a, indent=1, sort_keys=True) + '\n')
        files[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
    fgt2h = None
    events = {}
    for d in DIVES:
        t0 = draft['events'][f'FAT2_{d}_takeoff']['pts_s']
        t1 = draft['events'][f'FAT2_{d}_water_contact']['pts_s']
        ta = draft['events'][f'FAT2_{d}_apex']['pts_s']
        assert t0 <= ta <= t1, (d, 'apex outside flight window')
        events[d] = {'takeoff': t0, 'water_contact': t1,
                     'takeoff_contact_source': 'FAT2_FRESH_HUMAN',
                     'apex': ta, 'apex_source': 'FAT2_FRESH_HUMAN'}
    pe = dst / 'FAT2_EVENTS.json'
    pe.write_text(json.dumps(events, indent=1, sort_keys=True) + '\n')
    files[pe.name] = hashlib.sha256(pe.read_bytes()).hexdigest()
    man = {'authority': 'FULL_ACTION_GT_HUMAN_V2_FRESH', 'sealed': True,
           'n_items': len(files) - 1, 'digest': hashlib.sha256(
               json.dumps(files, sort_keys=True).encode()).hexdigest(), 'files': files}
    (dst / 'MANIFEST.json').write_text(json.dumps(man, indent=1, sort_keys=True) + '\n')
    print(json.dumps({k: v for k, v in man.items() if k != 'files'}, indent=1))


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['serve', 'validate', 'freeze'])
    ap.add_argument('--port', type=int, default=8765)
    a = ap.parse_args()
    {'serve': cmd_serve, 'validate': cmd_validate, 'freeze': cmd_freeze}[a.cmd](a)
