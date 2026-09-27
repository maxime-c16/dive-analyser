"""Sealed-HUMAN FAX6 evaluation of the frozen instance bridge.

Run only after FAX6 HUMAN freeze and GT-free S3 cache completion. The
bridge receives selected S3 core and read-only source video; labels are
used afterward for scoring only. Full mask trajectories stay host-only.
"""
import hashlib
import json
from pathlib import Path

import fax_v6_fresh_eval as E
import fax_instance_bridge_v1_dev as I

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'runs/fax_v6/instance_results.json'
WEIGHTS = ROOT / 'yolov8n-seg.pt'
RAW = ROOT / 'runs/fax_v6_raw'
SOURCE_SHA = {
    '649': 'd773598d9fade0af2ce5f72506525d7eb0de1c079ae24accdfb5340a8bc3b77a',
    '745': '54e0ac743f4c32e687e16a2c87ec70d823335fcb1abe7438a949a5c49ccdd577',
    '772': '0ec6a49eeb8d656d1d357c2ff2ff8ae48033af3c274f3a2c9063ae16f41b0730',
    '850': '823e716613848b1e057725aad7aa51a2373ce252580dd45ede59c548e23b1c62',
}


def main():
    labels, events, man = E.authority()
    cache = json.loads(E.CACHE.read_text())
    assert cache['gt_payload'] == 'NONE'
    assert cache['model_sha256'] == '3dc07f69cbe3824490f73c14a59ed328ff35fc2da48da2fd4e324acf9bcc4e9a'
    out = {'authority': man['authority'], 'digest': man['digest'],
           'queue_denominator': 4, 'excluded_dives': man.get('excluded_dives', {}),
           'prototype_sha256': hashlib.sha256(Path(I.__file__).read_bytes()).hexdigest(),
           'instance_model_sha256': I.MODEL_SHA256, 'dives': {}}
    assert out['prototype_sha256'] == '46db2213e4e21f206d58746a57ea26adeaeea353bb0e68a4e5369cbf4731944f'
    for d in events:
        parts = labels[d]
        flight = {f: a for phase, rows in parts.items() if phase.endswith('/8')
                  for f, a in rows.items()}
        c = E.select(E.select_flight({'360': cache}, d), flight)
        row = {'selected': c is not None}
        if c is None:
            out['dives'][d] = row
            continue
        core = {f: b for f, b in c['obs'].items()
                if c['parts']['t0'] - 1e-9 <= c['pts'][f] <= c['parts']['t1'] + 1e-9}
        source = RAW / f'{d}.mov'
        assert hashlib.sha256(source.read_bytes()).hexdigest() == SOURCE_SHA[d]
        result = I.build(core, c['Fl'], c['pts'], source, WEIGHTS,
                         device='mps', overlay_size=tuple(json.loads(
                             (ROOT / 'runs/fax_v6_media/PROXY_REGISTRY_FAX_V6.json').read_text()
                         )[d]['size']))
        obs = {int(f): tuple(v['box']) + (v['conf'],)
               for f, v in result.get('trajectory', {}).items()}
        row.update({'selected_candidate': {'pool_rank': c['pool_rank'],
                                          'Q': c['Q'], 'ft0': c['parts']['t0'],
                                          'ft1': c['parts']['t1']},
                    'state': result['state'], 'mixed_edge': result.get('mixed_edge'),
                    'trusted_subcore': result.get('trusted_subcore'),
                    'unresolved_interval_s': result.get('unresolved_interval_s'),
                    'first_asserted_frame': result.get('first_asserted_frame'),
                    'last_asserted_frame': result.get('last_asserted_frame'),
                    'n_asserted': len(obs),
                    'prep': E.score_phase(obs, parts.get('PREP', {})),
                    'flight': E.score_phase(obs, flight),
                    'post': E.score_phase(obs, parts.get('POST', {})),
                    'stability': E.stability(obs, c['pts']),
                    'alternatives': result.get('alternatives', [])})
        mask_file = OUT.parent / f'instance_{d}_masks.json'
        mask_file.parent.mkdir(parents=True, exist_ok=True)
        mask_file.write_text(json.dumps(result) + '\n')
        row['mask_file_sha256'] = hashlib.sha256(mask_file.read_bytes()).hexdigest()
        out['dives'][d] = row
        print(d, row['state'], row['n_asserted'], row['flight'], flush=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, sort_keys=True) + '\n')
    print('results_sha256', hashlib.sha256(OUT.read_bytes()).hexdigest())


if __name__ == '__main__':
    main()
