"""Consumed FAX6 diagnostic. This is not a fresh validation gate."""
import hashlib
import json
from pathlib import Path

import fax_v6_fresh_eval as E
import fax_v2_fresh_eval as E2
import prep_to_subcore_v1_dev as P

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'runs/prep_to_subcore_dev/results.json'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    labels, _, man = E.authority()
    labels2, _, man2 = E2.authority()
    reg = json.loads((ROOT / 'runs/fax_v6_media/PROXY_REGISTRY_FAX_V6.json').read_text())
    reg2 = json.loads((ROOT / 'runs/fax_v2_media/PROXY_REGISTRY_FAX_V2.json').read_text())
    out = {'status': 'CONSUMED_DEVELOPMENT_ONLY', 'authority': man['authority'],
           'authority_digest': man['digest'], 'additional_authority': man2['authority'],
           'additional_authority_digest': man2['digest'],
           'method_sha256': sha(P.__file__), 'dives': {}}
    for d in ('205', '745', '850'):
        interval = ROOT / f'runs/prep_to_subcore_dev/interval_{d}.json'
        prep = ROOT / f'runs/prep_to_subcore_dev/v1_{d}.json'
        flight = (ROOT / 'runs/fax_v5/instance_205_dev.json' if d == '205' else
                  ROOT / f'runs/fax_v6/instance_{d}_masks.json')
        x, v, b = (json.loads(path.read_text()) for path in (interval, prep, flight))
        f = b['trusted_subcore'][0]
        pts = reg2[d]['pts'] if d == '205' else reg[d]['pts']
        phases = labels2[d] if d == '205' else labels[d]
        score = E2.score_phase if d == '205' else E.score_phase
        decision = P.connect(x['frames'], pts, f,
                             b['trajectory'][str(f)]['box'], v['trajectory'])
        mask_obs = {int(k): tuple(z['box']) + (z['conf'],)
                    for k, z in b['trajectory'].items()}
        prep_obs = ({int(k): tuple(z['box']) + (z['conf'],)
                     for k, z in v['trajectory'].items()
                     if int(k) < decision['prep_anchor_frame']}
                    if decision['state'] == 'CONNECTED_WITH_NULL_INTERVAL' else {})
        flight_labels = {f: a for phase, rows in phases.items()
                         if phase.endswith('/8') for f, a in rows.items()}
        row = {'decision': decision, 'prep': score(prep_obs, phases['PREP']),
               'flight': score(mask_obs, flight_labels),
               'post': score(mask_obs, phases.get('POST', {})),
               'interval_sha256': sha(interval), 'prep_path_sha256': sha(prep),
               'trusted_subcore_artifact_sha256': sha(flight)}
        out['dives'][d] = row
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, sort_keys=True) + '\n')
    print(sha(OUT))
    for d, row in out['dives'].items():
        print(d, row['decision']['state'], row['decision'].get('reason'),
              row['prep'], row['flight'], row['post'])


if __name__ == '__main__':
    main()
