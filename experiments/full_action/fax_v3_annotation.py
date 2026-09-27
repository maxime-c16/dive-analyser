"""FAX3 fresh full-action HUMAN annotation queue (4 session-disjoint DEVELOPMENT dives + 1 reserve).

Dives: 1515/s94, 2086/s128, 2160/s131, 2674/s156.
Reserve 1810/s111 enters ONLY on annotator-exclusion (its steps
appear automatically once a queued dive is excluded; no code change).
All are UNUSED in every training/consumed/DEV role; none has prior flight
boxes or event times. Everything in this task is new HUMAN authority:
takeoff, water contact, apex (+independent apex repeat), flight boxes at k/8
of the marked window, preparation boxes every 0.5 s, post-entry boxes, one
blind PREP repeat per dive.

Blindness: the UI shows verified raw study-local proxy frames only.
No S3 boxes, FSR candidates, FAX tracks, scores, or overlays are shown or
reachable. S3 caches + FSR selection viability are sealed until the freeze.

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

WORKROOT = Path('/Users/maximecauchy/.perso/diveanalyzer-selected-flight-cycle')
PROXIES = WORKROOT / 'runs' / 'fax_v3_media' / 'proxies'
REGISTRY = WORKROOT / 'runs' / 'fax_v3_media' / 'PROXY_REGISTRY_FAX_V3.json'

DIVES = ('1515', '2086', '2160', '2674')
RESERVE = ('1810',)
ALL = DIVES + RESERVE
SET = 'FAX3'
WORK = WORKROOT / 'runs' / 'fax_v3_annotation'
DRAFT_PATH = WORK / 'annotations_draft.json'
FREEZE_DIRNAME = 'FULL_ACTION_GT_HUMAN_FAX3_FRESH'

SESSIONS = {'1515': 94, '2086': 128, '2160': 131, '2674': 156, '1810': 111}
CODES = {'1515': '103B', '2086': '103B', '2160': '104B', '2674': '103B', '1810': '103B'}

PROXY_SHA = {d: x['proxy_sha256'] for d, x in json.loads(REGISTRY.read_text()).items()}


class Media:
    _reg = None

    @staticmethod
    def _registry():
        if Media._reg is None:
            Media._reg = json.loads(REGISTRY.read_text())
        return Media._reg

    @staticmethod
    def assert_allowed(d):
        assert str(d) in ALL, d

    @staticmethod
    def proxy_pts(d):
        Media.assert_allowed(d)
        return list(Media._registry()[str(d)]['pts'])

    @staticmethod
    def proxy_size(d):
        Media.assert_allowed(d)
        return tuple(Media._registry()[str(d)]['size'])

    @staticmethod
    def sha256_file(p):
        return hashlib.sha256(Path(p).read_bytes()).hexdigest()

    @staticmethod
    def verified_proxy(d):
        Media.assert_allowed(d)
        p = PROXIES / f'{d}.mp4'
        sha = Media.sha256_file(p)
        assert sha == PROXY_SHA[str(d)], (d, 'proxy SHA mismatch')
        return p, sha

    @staticmethod
    def hq_ok(d):
        return False

    @staticmethod
    def hq_entry(d):
        raise AssertionError('FAX3 is proxy-only; no HQ arm')


def nearest(pts, t):
    return min(range(len(pts)), key=lambda i: abs(pts[i] - t))


def fixed_prep_post(d, t0, t1, window_source):
    """FAT1/FAT2-identical rule: PREP every 0.5 s from clip start to >= 0.1 s
    before takeoff; POST +0.1/+0.3/+0.5 s after contact; nearest recorded PTS."""
    pts = Media.proxy_pts(d)
    w, h = Media.proxy_size(d)
    out, seen = [], set()
    for k in range(int((t0 - .10) / .5) + 1):
        fi = nearest(pts, k * .5)
        if fi in seen:
            continue
        seen.add(fi)
        out.append({'id': f'FAX3_{d}_f{fi:05d}', 'dive_id': d, 'set': SET,
                    'frame_index': fi, 'pts_s': pts[fi], 'flight_fraction': 'PREP',
                    'window_source': window_source, 'kind': 'box', 'width': w, 'height': h})
    for dt in (.10, .30, .50):
        if t1 + dt > pts[-1]:
            continue
        fi = nearest(pts, t1 + dt)
        if fi in seen:
            continue
        seen.add(fi)
        out.append({'id': f'FAX3_{d}_f{fi:05d}', 'dive_id': d, 'set': SET,
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
        out.append({'id': f'FAX3_{d}_fl_f{fi:05d}', 'dive_id': d, 'set': SET,
                    'frame_index': fi, 'pts_s': pts[fi], 'flight_fraction': f'{k}/8',
                    'window_source': window_source, 'kind': 'box', 'width': w, 'height': h})
    return out


def apex_events(d, n_frames):
    w, h = Media.proxy_size(d)
    return [{'id': f'FAX3_{d}_apex', 'dive_id': d, 'set': SET, 'event': 'apex',
             'n_frames': n_frames, 'kind': 'event', 'width': w, 'height': h},
            {'id': f'FAX3_{d}_apex_R', 'dive_id': d, 'set': SET, 'event': 'apex',
             'n_frames': n_frames, 'kind': 'event', 'width': w, 'height': h,
             'repeat_of': f'FAX3_{d}_apex'}]


def effective_dives(draft=None):
    """Queued dives + reserve 1810 IFF a queued dive is annotator-excluded
    (pre-registered reserve rule; no mid-annotation code change)."""
    draft = draft or {'items': {}, 'events': {}}
    excluded = set(draft.get('excluded_dives', {}))
    if excluded & set(DIVES):
        return DIVES + RESERVE
    return DIVES


def build_queue(draft=None):
    """Per dive: takeoff -> water_contact -> apex -> apex_R event steps;
    once takeoff+water_contact are marked, window-derived boxes appear
    (flight k/8, prep/post rule). Reserve 1810 joins only via the protocol
    reserve rule (a queued dive excluded). Uniform fresh authority."""
    draft = draft or {'items': {}, 'events': {}}
    excluded = set(draft.get('excluded_dives', {}))
    steps, events, items = [], [], []
    for d in effective_dives(draft):
        if d in excluded:
            continue
        pts = Media.proxy_pts(d)
        w, h = Media.proxy_size(d)
        for ev in ('takeoff', 'water_contact'):
            e = {'id': f'FAX3_{d}_{ev}', 'dive_id': d, 'set': SET, 'event': ev,
                 'n_frames': len(pts), 'kind': 'event', 'width': w, 'height': h}
            steps.append(e)
        a, b = draft['events'].get(f'FAX3_{d}_takeoff'), draft['events'].get(f'FAX3_{d}_water_contact')
        if a and b and b['pts_s'] > a['pts_s']:
            ws = 'HUMAN_EVENT_MARKED_IN_THIS_TOOL'
            steps += flight_eighths(d, a['pts_s'], b['pts_s'], ws)
            steps += fixed_prep_post(d, a['pts_s'], b['pts_s'], ws)
        steps += apex_events(d, len(pts))
    for s in steps:
        (events if s['kind'] == 'event' else items).append(s)
    # deterministic blind box repeat per dive: middle PREP item (resolves with events)
    for d in effective_dives(draft):
        if d in excluded:
            continue
        preps = [i for i in items if i['dive_id'] == d and i['flight_fraction'] == 'PREP']
        if preps:
            mid = preps[len(preps) // 2]
            r = dict(mid, id=mid['id'] + '_R', repeat_of=mid['id'])
            items.append(r)
            steps.append(r)
    return {'events': events, 'items': items, 'steps': steps,
            'created_rule': 'Per dive: takeoff, water contact (scrub), apex + independent apex repeat '
                            '(scrub, constrained to the marked window); then flight k/8 boxes, PREP every 0.5s '
                            'clip-start to >=0.1s pre-takeoff, POST +0.1/+0.3/+0.5; one blind PREP repeat '
                            'per dive (middle PREP). Nearest recorded proxy PTS throughout.'}


def ensure_dive_frames(draft, d):
    q = build_queue(draft)
    U.extract_box(d, [it['frame_index'] for it in q['items'] if it['dive_id'] == d])


def apex_window(d, draft):
    """(lo_pts, hi_pts) constraining an apex pick (fresh marked window)."""
    a, b = draft['events'].get(f'FAX3_{d}_takeoff'), draft['events'].get(f'FAX3_{d}_water_contact')
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
                        f'FAX3_{ev["dive_id"]}_apex', f'FAX3_{ev["dive_id"]}_apex_R'):
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
    U.dive_order = lambda: [(SET, d) for d in ALL]
    # NOTE: step visibility for the reserve is gated by effective_dives()
    # (joins only on queued-dive exclusion); dive_order covers all 7 so the
    # base exclusion endpoint and scrub extraction work uniformly.
    U.ensure_dive_frames = ensure_dive_frames
    U._UI = U._UI.replace('Flight GT session 3 (human)', 'FAX3 full-action GT (human, blind)')
    assert 'FAX3 full-action GT' in U._UI
    # Viewport fix (2026-09-27, pre-annotation, draft empty): the inherited
    # fit() constrains canvas scale by viewport height only. Dive 16's proxy
    # is 648x360 landscape (all prior annotation dives were 202x360
    # portrait), so its canvas (~1570px wide) pushes the control panel
    # off-screen. Constrain by width too; S stays uniform so box mapping
    # (canvas/S -> native proxy pixels, server-clamped per dive) is exact.
    _old_fit = 'S=Math.max(1,(window.innerHeight-20)/H);'
    _new_fit = ('S=Math.max(0.5,Math.min((window.innerHeight-20)/H,'
                '(window.innerWidth-420)/W));')
    assert U._UI.count(_old_fit) == 1, 'viewer fit() patch drifted'
    U._UI = U._UI.replace(_old_fit, _new_fit)


def queue_manifest():
    reg = Media._registry()
    q = build_queue({'items': {}, 'events': {}})
    return {'authority': 'FULL_ACTION_GT_HUMAN_FAX3_FRESH (queue; labels pending)',
            'dives': list(DIVES), 'reserve': list(RESERVE),
            'sessions': {d: SESSIONS[d] for d in ALL},
            'codes': {d: CODES[d] for d in ALL},
            'created_rule': q['created_rule'],
            'n_event_steps': len(q['events']),
            'media_sha256': {d: Media.verified_proxy(d)[1] for d in ALL},
            'pts_source': {d: 'study-local proxy sequential cv2 decode (PROXY_REGISTRY_FAX_V3)' for d in ALL},
            'proxy_size': {d: list(reg[d]['size']) for d in ALL},
            'blind': 'Raw study-local proxy frames only. No S3 boxes, FSR candidates, '
                     'FAX tracks, scores, or overlays shown or reachable. '
                     'S3 caches + FSR selection are sealed until the freeze.'}


def cmd_serve(args):
    from http.server import ThreadingHTTPServer
    patch_tool()
    WORK.mkdir(parents=True, exist_ok=True)
    if not DRAFT_PATH.exists():
        U.save_draft({'items': {}, 'events': {}})
    draft = U.load_draft()
    for d in ALL:
        Media.verified_proxy(d)
        U.extract_scrub(d)
    (WORK / 'QUEUE_MANIFEST.json').write_text(json.dumps(queue_manifest(), indent=1, sort_keys=True) + '\n')
    srv = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    print(f'FAX3 annotation UI: http://127.0.0.1:{args.port}', flush=True)
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
           for d in effective_dives(draft) if d not in draft.get('excluded_dives', {})}
    apex = {}
    for d in effective_dives(draft):
        if d in draft.get('excluded_dives', {}):
            continue
        a, b = draft['events'].get(f'FAX3_{d}_apex'), draft['events'].get(f'FAX3_{d}_apex_R')
        if a and b:
            apex[d] = round(abs(a['pts_s'] - b['pts_s']), 4)
    print(json.dumps({'missing_events': miss_ev, 'missing_items': miss, 'visibility_per_dive': per,
                      'apex_repeat_agreement_s': apex,
                      'excluded_dives': sorted(draft.get('excluded_dives', {})),
                      'complete': not miss_ev and not miss}, indent=1))


def cmd_freeze(args):
    patch_tool()
    draft = U.load_draft()
    excluded = sorted(draft.get('excluded_dives', {}))
    if excluded and not args.allow_excluded:
        raise SystemExit('excluded dive(s) need a protocol decision: re-run with --allow-excluded '
                         '(the exclusion set is then recorded in the MANIFEST; the reserve rule '
                         'in FAX3_PROTOCOL_V1 decides whether 1810 enters)')
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
    events = {}
    for d in effective_dives(draft):
        if d in excluded:
            continue
        t0 = draft['events'][f'FAX3_{d}_takeoff']['pts_s']
        t1 = draft['events'][f'FAX3_{d}_water_contact']['pts_s']
        ta = draft['events'][f'FAX3_{d}_apex']['pts_s']
        assert t0 <= ta <= t1, (d, 'apex outside flight window')
        events[d] = {'takeoff': t0, 'water_contact': t1,
                     'takeoff_contact_source': 'FAX3_FRESH_HUMAN',
                     'apex': ta, 'apex_source': 'FAX3_FRESH_HUMAN'}
    pe = dst / 'FAX3_EVENTS.json'
    pe.write_text(json.dumps(events, indent=1, sort_keys=True) + '\n')
    files[pe.name] = hashlib.sha256(pe.read_bytes()).hexdigest()
    man = {'authority': 'FULL_ACTION_GT_HUMAN_FAX3_FRESH', 'sealed': True,
           'excluded_dives': {d: draft['excluded_dives'][d] for d in excluded},
           'n_items': len(files) - 1, 'digest': hashlib.sha256(
               json.dumps(files, sort_keys=True).encode()).hexdigest(), 'files': files}
    (dst / 'MANIFEST.json').write_text(json.dumps(man, indent=1, sort_keys=True) + '\n')
    print(json.dumps({k: v for k, v in man.items() if k != 'files'}, indent=1))


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['serve', 'validate', 'freeze'])
    ap.add_argument('--port', type=int, default=8766)
    ap.add_argument('--allow-excluded', action='store_true')
    a = ap.parse_args()
    {'serve': cmd_serve, 'validate': cmd_validate, 'freeze': cmd_freeze}[a.cmd](a)
