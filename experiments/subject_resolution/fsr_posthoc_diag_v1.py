"""POST-HOC (after sealed evaluation) diagnosis of construction loss. Not used for design
of the frozen v1 pipeline. For every sealed flight anchor: subject node conf rank, and
whether that node's own best-through path recovers; if not, where it deviates and the
confidence of the object it deviates onto."""
import json, math, sys
import numpy as np
import fsr_common_v1 as C, fsr_search_v1 as S, fsr_final_eval_v1 as FE
from fsr_node_oracle_v1 import node_paths

auth = C.load_eval_authority(FE.PROTOCOL_SHA)
rows = {}
for rep in ('360', 'hq'):
    for d in C.COHORT:
        if rep == 'hq' and d not in C.HQ_DIVES:
            continue
        fr = C.frames(d, rep); pts = [f['pts_s'] for f in fr]
        A = FE.flight_anchors(auth, d, pts)
        L, T, through, allT = node_paths(S, fr)
        out = []
        for fp, a in sorted(A.items()):
            if not len(L[fp]):
                out.append({'fp': fp, 'status': 'NO_NODES'}); continue
            dd = np.hypot(L[fp][:, 0] - a[0], L[fp][:, 1] - a[1])
            js = np.nonzero(dd <= C.RADIUS)[0]
            if not len(js):
                out.append({'fp': fp, 'status': 'NOT_IN_LATTICE'}); continue
            j = int(max(js, key=lambda k: T[fp][k]))
            conf = float(L[fp][j][4]); rank = int((L[fp][:, 4] > conf).sum())
            path = through(fp, j)
            obs = S.path_obs(path, L)
            sc = C.score_track(obs, A)
            dev = []
            for g, b in sorted(A.items()):
                if g in obs and math.hypot(obs[g][0] - b[0], obs[g][1] - b[1]) > C.RADIUS:
                    dev.append(round(obs[g][4], 3))
            subj_conf = [round(float(L[g][int(np.argmin(np.hypot(L[g][:, 0] - b[0], L[g][:, 1] - b[1])))][4]), 3)
                         for g, b in A.items() if len(L[g])]
            out.append({'fp': fp, 'status': 'REC' if sc['recovered'] else 'NO', 'cov': round(sc['coverage'], 2),
                        'pur': sc['purity'], 'node_conf': round(conf, 3), 'conf_rank': rank,
                        'deviated_onto_conf': dev, 'subject_conf_at_anchors': subj_conf})
        rows[f'{d}:{rep}'] = out
        st = [o['status'] for o in out]
        print(d, rep, 'nodes REC', st.count('REC'), '/', len(st), 'NOT_IN_LATTICE', st.count('NOT_IN_LATTICE'),
              '| subj conf med', np.median([o['node_conf'] for o in out if 'node_conf' in o]) if any('node_conf' in o for o in out) else None,
              '| deviated-onto conf med', np.median([c for o in out for c in o.get('deviated_onto_conf', [])]) if any(o.get('deviated_onto_conf') for o in out) else None, flush=True)
(C.RUNS / 'final_eval' / 'posthoc_node_diag.json').write_text(json.dumps(rows, indent=1))
