"""Deterministic on-disk cache of search pools (search is GT-free and pure).

Key = (search module version + protocol constants hash, dive, rep). Lets ranking
experiments reuse pools without recomputing the DP.
"""
import hashlib
import json
import pickle

import fsr_common_v1 as C

DIR = C.RUNS / 'pool_cache'


def key(mod, d, rep):
    h = hashlib.sha256(json.dumps(mod.PROTOCOL_CONSTANTS, sort_keys=True, default=str).encode()).hexdigest()[:12]
    return DIR / f'{mod.SEARCH_VERSION}_{h}_{d}_{rep}.pkl'


def pool(mod, d, rep):
    p = key(mod, d, rep)
    if p.exists():
        return pickle.loads(p.read_bytes())
    fr = C.frames(d, rep)
    res = mod.search(fr)
    DIR.mkdir(parents=True, exist_ok=True)
    p.write_bytes(pickle.dumps(res))
    return res
