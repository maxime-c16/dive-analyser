#!/usr/bin/env python3
"""DIVE_ANALYZER_INDEPENDENT_SUBJECT_GT_EXPANSION_V1 — Phase 7.

Frozen OSNet candidate-embedding cache for the 6 NEW independent
subject-resolution dives. PARITY artifact, same accepted representation as
HURDLE_OSNET_EMBED_CACHE_V1 / osnet_emb_cohort_v1.npz:

- frozen OSNet x1.0 Market-1501 weights (models/reid/osnet_x1_0_market1501.pth,
  sha256 2809d322...), OSNetWrap from the frozen appearance benchmark module;
- crop recipe: box crop with pad 1.3, resize 256x128 (h,w), ImageNet norm;
- L2-normalized 512-d float32 vectors, keyed "dive|fi|k" for EVERY
  candidate of every frame (cohort-cache parity: n_keys == total candidates);
- one clip at a time, sequential decode, no seeks, device=mps;
- NO model comparison, NO ReID experiment, NO HQ experiment, NO tuning.

Artifact: runs/subject_resolution/osnet_emb_indep_v1.npz (+ .meta.json)
(host cache, outside Git).

Usage:
  caffeinate -i -s .venv-reid/bin/python3 experiments/subject_resolution/ \
      phase_indep_gt_osnet_cache_v1.py [dive_id ...]
"""

import datetime
import json
import resource
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import torch

BASE = Path(__file__).parents[2]
sys.path.insert(0, str(BASE / "experiments" / "landmark_pilot"))

from phase_hurdle_e_appearance_benchmark_v1 import (  # noqa: E402
    crop_tensor,
    sha256_file,
    to_input,
    OSNetWrap,
)

OSNET_PATH = BASE / "models/reid/osnet_x1_0_market1501.pth"
CROP_PAD = 1.3
EMB_SIZE = (256, 128)
D5_CACHE = BASE / "runs/subject_resolution/R5_FULLCLIP_CANDIDATES_INDEP_V1.json"
OUT_NPZ = BASE / "runs/subject_resolution/osnet_emb_indep_v1.npz"
OUT_META = BASE / "runs/subject_resolution/osnet_emb_indep_v1.meta.json"
BATCH = 64
EXPECTED_PROXY_SHA256 = {
    "2839": "4c0b93468ad8bedc710c03c17c2914cf9d30c6587fcff96e3a34f129dcbefef9",
    "2583": "496ba22de35d93e37071d56f89309ebb944aa9974566b2b0b60d2a99041f36cf",
    "2526": "82276c05f79a84a1160791825d533de9f55299d99c9188725d0a743d4d279e05",
    "2223": "c1a38b51ed212abd1af443004b8eb8ebd5824f9195af773de3d4a2ebc43d3919",
    "2204": "de7f769aa5e029b07efbf8faca73aca92c519580d6b11c8d96d4875356c115bd",
    "1304": "293b0acb0755a4aa47f4e743c8ebacfd299bd62a0e3f712a6b98822794c9b491",
}


def peak_rss_gb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1 << 30)


def main():
    data = {}
    if OUT_META.exists() and OUT_NPZ.exists():
        meta = json.loads(OUT_META.read_text())
        z = np.load(OUT_NPZ)
        for kk, v in zip(z["keys"], z["vecs"]):
            dive, fi, k = str(kk).split("|")
            data[(dive, int(fi), int(k))] = v
        print(f"[load] {len(data)} existing embeddings")
    else:
        meta = None

    d5 = json.loads(D5_CACHE.read_text())
    assert d5["model_sha256"] == sha256_file(
        BASE / "models/frozen/DIVER_DETECTOR_D5_A_V8N_best.pt"), "D5 drift"

    weights_sha = sha256_file(OSNET_PATH)
    if meta and meta["weights_sha256"] != weights_sha:
        raise SystemExit("OSNet weights drift")
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model = OSNetWrap(OSNET_PATH).to(device)
    model.eval()

    ids = sys.argv[1:] or list(EXPECTED_PROXY_SHA256)
    for did in ids:
        done_keys = {k for k in data if k[0] == did}
        if done_keys:
            print(f"[skip] {did} already embedded ({len(done_keys)} keys)")
            continue
        doc = d5["dives"][did]
        if doc["proxy_sha256"] != EXPECTED_PROXY_SHA256[did]:
            raise SystemExit(f"proxy sha drift for {did}")
        proxy = BASE / doc["proxy_path"]
        cap = cv2.VideoCapture(str(proxy))
        t0 = time.time()
        keys, vecs = [], []
        fi_seq = 0
        n_crops = 0
        for fdoc in doc["frames"]:
            ok, frame = cap.read()
            if not ok or frame is None:
                raise RuntimeError(f"{did}: decode failed at fi {fi_seq}")
            fi = fdoc["fi"]
            if fi != fi_seq + 1:
                raise SystemExit(f"{did}: frame order drift {fi} vs {fi_seq}")
            fi_seq = fi
            crops, fkeys = [], []
            for k, box in enumerate(fdoc["c"]):
                crops.append(crop_tensor(
                    frame, (box["cx"], box["cy"], box["bw"], box["bh"]),
                    pad=CROP_PAD))
                fkeys.append((did, fi, k))
            n_crops += len(crops)
            with torch.no_grad():
                for i in range(0, len(crops), BATCH):
                    x = to_input(crops[i:i + BATCH], EMB_SIZE).to(device)
                    f = model(x)
                    f = torch.nn.functional.normalize(f, dim=1)
                    keys.extend(fkeys[i:i + BATCH])
                    vecs.extend(f[j].cpu().numpy()
                                for j in range(len(f)))
        cap.release()
        for k, v in zip(keys, vecs):
            data[k] = v
        runtime = time.time() - t0
        meta = {
            "weights_sha256": weights_sha,
            "crop_pad": CROP_PAD,
            "emb_size": list(EMB_SIZE),
            "n_keys": len(data),
            "packet": "DIVE_ANALYZER_INDEPENDENT_SUBJECT_GT_EXPANSION_V1",
            "recipe": "identical to HURDLE_OSNET_EMBED_CACHE_V1 "
                      "(OSNet x1.0 market1501, pad 1.3, 256x128, L2)",
            "updated": datetime.datetime.now(
                datetime.timezone.utc).isoformat(),
        }
        all_keys = sorted(data.keys())
        arr = np.stack([data[k] for k in all_keys])
        np.savez_compressed(
            OUT_NPZ,
            keys=np.array(["%s|%d|%d" % k for k in all_keys]),
            vecs=arr)
        OUT_META.write_text(json.dumps(meta, indent=1) + "\n")
        print(f"[done] {did}: {n_crops} crops, {runtime:.1f}s, "
              f"n_keys {len(data)}, peak_rss {peak_rss_gb():.2f} GB")

    print(json.dumps(meta, indent=1))


if __name__ == "__main__":
    main()
