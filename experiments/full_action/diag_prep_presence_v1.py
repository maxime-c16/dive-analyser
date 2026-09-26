"""Diagnosis D1: prep presence decomposition for FAT1 five dives.

For each dive/rep and each HUMAN FAT1 PREP anchor (visible/partial):
  - raw floor presence: any of the <=200 floor candidates within RADIUS
  - non-static presence: same restricted to FSR lattice (non-static) nodes
  - static-only presence: raw hit but lattice miss
  - pool-path observation: selected pool path node within RADIUS
Also reports per-dive S3 floor candidate counts and conf profiles in prep span.
GT-free inference structures only; HUMAN boxes used post-hoc for diagnosis.
"""
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'experiments' / 'subject_resolution'))
sys.path.insert(0, str(ROOT / 'experiments' / 'flight_perception'))
import fsr_search_v1 as S

WORK = ROOT / 'runs' / 'selected_divetrack_v1'
CACHE = {r: WORK / 'caches' / f'CAND_S3_S2init_DS2_OOD_{r}.json' for r in ('360', 'hq')}
FAT1 = ROOT / 'docs' / 'science' / 'localization_annotations_v1' / 'FULL_ACTION_GT_HUMAN_V1_DEVELOPMENT'
RADIUS = 0.06
DIVES = ('23', '980', '1555', '2257', '2288')


def load_caches():
    return {r: json.loads(p.read_text()) for r, p in CACHE.items()}


def frames_of(payload, d, rep):
    return [{'fi': f['fi'], 'pts_s': f['pts_s'], 'c': f['c']} for f in payload[rep]['dives'][d]['frames']]


def fat1_prep(d):
    out = {}
    for p in sorted(FAT1.glob(f'FAT1_{d}_f*.json')):
        if p.name.endswith('_R.json'):
            continue
        a = json.loads(p.read_text())
        if a.get('flight_fraction') != 'PREP':
            continue
        if a.get('visibility') not in ('visible', 'partial') or not a.get('bbox'):
            continue
        x1, y1, x2, y2 = a['bbox']
        out[a['frame_index']] = ((x1 + x2) / 2 / a['width'], (y1 + y2) / 2 / a['height'])
    return out


def main():
    payload = load_caches()
    for d in DIVES:
        prep = fat1_prep(d)
        print(f'=== dive {d}: {len(prep)} visible/partial PREP anchors ===')
        for rep in ('360', 'hq'):
            fr = frames_of(payload, d, rep)
            assert payload[rep]['model_sha256'] == '3dc07f69cbe3824490f73c14a59ed328ff35fc2da48da2fd4e324acf9bcc4e9a'
            L = S.lattice(fr)
            n_raw = sum(len(f['c']) for f in fr)
            n_lat = sum(len(a) for a in L)
            print(f'  rep={rep}: frames={len(fr)} raw_cands={n_raw} lattice_cands={n_lat} '
                  f'static_frac={1 - n_lat / max(n_raw, 1):.3f}')
            for fi in sorted(prep):
                if fi >= len(fr):
                    print(f'    f{fi}: OUT_OF_RANGE')
                    continue
                hx, hy = prep[fi]
                raw = [c for c in fr[fi]['c']
                       if math.hypot(c['cx'] - hx, c['cy'] - hy) <= RADIUS]
                lat = [tuple(map(float, v)) for v in L[fi]
                       if math.hypot(v[0] - hx, v[1] - hy) <= RADIUS]
                conf = max([c['conf'] for c in raw], default=0.0)
                tag = 'HIT' if raw else 'MISS'
                lat_tag = 'lattice' if lat else ('STATIC-ONLY' if raw else 'absent')
                print(f'    f{fi}: {tag} raw_n={len(raw)} maxconf={conf:.3f} [{lat_tag}]')


if __name__ == '__main__':
    main()
