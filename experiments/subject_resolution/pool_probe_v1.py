"""Evaluation-only pool probe for an implementation module: best subject
pool path / pool core (with Q rank) and top-K, frozen authority."""
import importlib, json, math, sys
import audit_flight_path_recall_v1 as au
import run_flight_anchored_traj_v3 as r3
import run_multi_track_action_v1 as v1run

def probe(impl_name, dive):
    impl = importlib.import_module(impl_name)
    group = next(g for g, ids in v1run.GROUPS.items() if dive in ids)
    doc = json.loads(v1run.CACHES[group].read_text())['dives'][dive]
    clean = impl.inference_view(doc['frames']); pts = [f['pts_s'] for f in clean]
    _, off = impl.compute_flow(clean, pts)
    kept, _ = impl.build_frame_lattice(clean, off); ka = impl._frame_arrays(kept)
    pool = impl._extend_starts(kept, ka, pts, list(range(0, len(pts), impl.START_STRIDE)))
    cores = []
    for q in pool:
        b = impl.extract_flight_core(q, kept, pts)
        if b: cores.append((b[0], q, b[1], b[2]))
    cores.sort(key=lambda c: (-round(c[0], 9), tuple(c[1].obs)))
    diverse = []
    for ci, (qv, qp, i, j) in enumerate(cores):
        if all(impl._agree(qp.obs, kept, d[1].obs, kept) < impl.DUP_AGREE for d in diverse):
            diverse.append((qv, qp, i, j, ci))
        if len(diverse) >= impl.FINAL_TOP_K * 4: break
    # ---- GT ----
    w = r3.flight_window(dive, pts); an = v1run.subject_anchors(dive, pts)
    fl = {fi: v for fi, v in an.items() if w['takeoff_s'] - .05 <= pts[fi] <= w['water_contact_s'] + .05}
    flight = {'anchors': fl, 't0': w['takeoff_s'], 't1': w['water_contact_s']}
    pe = lambda obs: au.path_eval(obs, kept, pts, an, flight)
    bp = max((pe(q.obs) for q in pool), key=au._key)
    ce = [(ci, pe(qp.obs[i:j + 1])) for ci, (qv, qp, i, j) in enumerate(cores)]
    bc = max(ce, key=lambda x: au._key(x[1]))
    drank = {d[4]: r for r, d in enumerate(diverse, 1)}
    qual = [(ci + 1, drank.get(ci), round(e['coverage'], 2)) for ci, e in ce if e['qualifies']]
    return {'pool': len(pool), 'cores': len(cores), 'diverse': len(diverse),
            'pool_best': (round(bp['coverage'], 2), bp['purity'] and round(bp['purity'], 2), bp['qualifies']),
            'core_best': (round(bc[1]['coverage'], 2), bc[1]['qualifies'], 'Qrank', bc[0] + 1, 'div', drank.get(bc[0])),
            'qualifying_cores(Qrank,divrank,cov)': qual[:12]}

if __name__ == '__main__':
    for d in sys.argv[2:]:
        print(sys.argv[1], d, probe(sys.argv[1], d), flush=True)
