"""Blinded full-action HUMAN box queue for five separate DEVELOPMENT sessions.

Only verified raw proxy frames and pre-existing HUMAN event times are displayed.
No detector boxes, FSR paths, selected candidate, or track metric enters this UI.
The queue is fixed before any new full-action labels are collected.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fpsr2_flight_gt_annotation as U

ROOT = HERE.parents[1]
SOURCE = ROOT.parent / 'diveanalyzer-flight-perception-successor'
PROXIES = SOURCE / 'media/fps_v1/proxies'
PTS = SOURCE / 'runs/flight_perception_successor_v1/PROXY_PTS_INDEX_V1.json'
SPLIT = ROOT / 'docs/science/FLIGHT_PERCEPTION_SUCCESSOR_SPLIT_V1.json'
EVENTS = ROOT / 'docs/science/localization_annotations_v1/FLIGHT_GT_HUMAN_V2_HOLDOUT/FGT2H_EVENTS.json'
WORK = ROOT / 'runs/selected_divetrack_v1/annotation'
DIVES = ('23', '980', '1555', '2257', '2288')
FORBIDDEN = {'524', '2555', '2819', '160', '169', '191', '192', '848', '2281'}


class Media:
    @staticmethod
    def sha256_file(p):
        return hashlib.sha256(Path(p).read_bytes()).hexdigest()

    @staticmethod
    def assert_allowed(d):
        assert d in DIVES and d not in FORBIDDEN

    @staticmethod
    def proxy_pts(d):
        return json.loads(PTS.read_text())[d]['pts']

    @staticmethod
    def proxy_size(d):
        return json.loads(PTS.read_text())[d]['size']

    @staticmethod
    def verified_proxy(d):
        Media.assert_allowed(d)
        p = PROXIES / f'{d}.mp4'
        sha = Media.sha256_file(p)
        expected = next(x['proxy_360p_sha256'] for x in
                        json.loads(SPLIT.read_text())['roles']['FRESH_FLIGHT_HOLDOUT']['dives']
                        if str(x['dive_id']) == d)
        assert sha == expected, (d, 'proxy SHA mismatch')
        return p, sha

    @staticmethod
    def hq_ok(d):
        return False


def fixed_items():
    ev = json.loads(EVENTS.read_text())
    out = []
    for d in DIVES:
        pts = Media.proxy_pts(d)
        w, h = Media.proxy_size(d)
        t0 = ev[f'FGT2H_EV_{d}_takeoff']['pts_s']
        t1 = ev[f'FGT2H_EV_{d}_water_contact']['pts_s']
        targets = [(k * .5, 'PREP') for k in range(int((t0 - .10) / .5) + 1)]
        targets += [(t1 + dt, 'POST') for dt in (.10, .30, .50) if t1 + dt <= pts[-1]]
        seen = set()
        for target, phase in targets:
            fi = min(range(len(pts)), key=lambda i: abs(pts[i] - target))
            if fi in seen:
                continue
            seen.add(fi)
            out.append({'id': f'FAT1_{d}_f{fi:05d}', 'dive_id': d, 'set': 'DEVELOPMENT',
                        'frame_index': fi, 'pts_s': pts[fi], 'flight_fraction': phase,
                        'window_source': 'PREEXISTING_FGT2H_HUMAN_EVENTS', 'kind': 'box',
                        'width': w, 'height': h})
    return out


def queue(draft=None):
    items = fixed_items()
    # Same-image repeatability checks at two predetermined preparation frames.
    for d in ('23', '2257'):
        candidates = [x for x in items if x['dive_id'] == d and x['flight_fraction'] == 'PREP']
        item = candidates[len(candidates) // 2]
        items.append(dict(item, id=item['id'] + '_R', repeat_of=item['id']))
    return {'events': [], 'items': items, 'steps': items,
            'created_rule': 'PREP every 0.5s from clip start to >=0.1s before HUMAN takeoff; POST +0.1/+0.3/+0.5s after HUMAN contact; nearest recorded proxy PTS; two blind repeats'}


def prepare():
    U.WORK.mkdir(parents=True, exist_ok=True)
    if not U.DRAFT_PATH.exists():
        U.save_draft({'items': {}, 'events': {}})
    for d in DIVES:
        Media.verified_proxy(d)
        U.extract_box(d, [x['frame_index'] for x in fixed_items() if x['dive_id'] == d])
    (U.WORK / 'QUEUE_MANIFEST.json').write_text(json.dumps({
        'authority': 'FULL_ACTION_GT_HUMAN_V1_DEVELOPMENT',
        'dives': list(DIVES), 'items': queue()['items'], 'event_source_sha256': Media.sha256_file(EVENTS),
        'split_source_sha256': Media.sha256_file(SPLIT),
        'proxy_sha256': {d: Media.verified_proxy(d)[1] for d in DIVES},
        'blind': 'No detector/path/selected candidate shown'}, indent=2, sort_keys=True) + '\n')


def freeze():
    draft = U.load_draft()
    expected = {x['id'] for x in queue()['items']}
    assert expected == set(draft['items']), 'annotation queue incomplete or contains excluded dive'
    assert not draft['events'], 'event times must come only from frozen FGT2H authority'
    dst = ROOT / 'docs/science/localization_annotations_v1/FULL_ACTION_GT_HUMAN_V1_DEVELOPMENT'
    assert not dst.exists(), 'authority already frozen; never overwrite'
    dst.mkdir(parents=True)
    files = {}
    for key in sorted(expected):
        a = draft['items'][key]
        assert a['authority'] == 'HUMAN_REVIEWED' and a['annotator'] == 'maxime'
        assert a['dive_id'] in DIVES and a['visibility'] in ('visible', 'partial', 'not_visible', 'ambiguous')
        p = dst / f'{key}.json'
        p.write_text(json.dumps({'id': key, **a}, indent=2, sort_keys=True) + '\n')
        files[p.name] = Media.sha256_file(p)
    digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    (dst / 'MANIFEST.json').write_text(json.dumps({
        'label': 'FULL_ACTION_GT_HUMAN_V1_DEVELOPMENT', 'digest': digest,
        'files': files, 'dives': list(DIVES), 'n_items': len(files),
        'queue_manifest_sha256': Media.sha256_file(WORK / 'QUEUE_MANIFEST.json'),
        'preexisting_flight_gt': 'FLIGHT_GT_HUMAN_V2_HOLDOUT',
        'event_source_sha256': Media.sha256_file(EVENTS),
        'blind': 'Raw proxy frames only; no detector candidate or track shown',
        'sealed': True}, indent=2, sort_keys=True) + '\n')
    print('frozen', dst, digest)


def setup():
    U.fm = Media
    U.WORK = WORK
    U.DRAFT_PATH = WORK / 'annotations_draft.json'
    U.dive_order = lambda: [('DEVELOPMENT', d) for d in DIVES]
    U.SETS = {'DEVELOPMENT': {'label': 'FULL_ACTION_GT_HUMAN_V1_DEVELOPMENT', 'prefix': 'FAT1'}}
    U.build_queue = queue
    U._UI = U._UI.replace('Flight GT session 3 (human)', 'Full-action GT (human)')


def main():
    setup()
    p = argparse.ArgumentParser()
    p.add_argument('cmd', choices=['prepare', 'serve', 'validate', 'freeze'])
    p.add_argument('--port', type=int, default=8767)
    a = p.parse_args()
    if a.cmd == 'prepare':
        prepare()
        print('prepared', len(queue()['items']), 'items', WORK)
    elif a.cmd == 'serve':
        prepare()
        from http.server import ThreadingHTTPServer
        srv = ThreadingHTTPServer(('127.0.0.1', a.port), U.Handler)
        print(f'full-action annotation UI: http://127.0.0.1:{a.port}', flush=True)
        srv.serve_forever()
    elif a.cmd == 'validate':
        U.cmd_validate(a)
    else:
        freeze()


if __name__ == '__main__':
    main()
