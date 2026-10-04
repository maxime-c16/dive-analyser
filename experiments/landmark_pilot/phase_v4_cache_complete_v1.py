#!/usr/bin/env python3
"""V4 — ONE-TIME bounded completion of the OSNet embedding cache.

Packet HURDLE_IDENTITY_COMPONENT_AND_TARGET_SELECTION_V4. The V3 cache
covered every plausible tracklet crop (25,524-crop extraction + hypothesis
path crops). Phase B's bounded hypothesis repair needs embeddings for
candidates outside that set (2341's short target fragments were never
embedded). This script completes the cache to FULL candidate-ocean
coverage for the corpus — a single sequential decode per dive, MPS-batched,
appended to the provenanced cache (no crop embedded twice).

After completion the manifest (docs/science/HURDLE_OSNET_EMBED_CACHE_V1.json)
MUST be regenerated (new sha256 / n_keys / coverage).

Usage:
  caffeinate -i -s ~/.perso/diveanalyzer-identity-v2/.venv-reid/bin/python \
      experiments/landmark_pilot/phase_v4_cache_complete_v1.py [dive ...]
"""

import json
import sys
import time
from pathlib import Path

import numpy as np

BASE = Path(__file__).parents[2]
sys.path.insert(0, str(BASE / "experiments/landmark_pilot"))

import v6_prototype_v1 as V  # noqa: E402
from v6_prototype_v1 import ALL_DIVES, EMB_SIZE  # noqa: E402

DEVICE = "mps" if __import__("torch").backends.mps.is_available() else "cpu"
BATCH = 32


def main():
    import torch
    import cv2
    from phase_hurdle_e_appearance_benchmark_v1 import (
        OSNetWrap, crop_tensor, to_input,
    )
    fc, _ = V.load_corpus()
    cache = V.EmbeddingCache()
    ok, sha16 = cache.verify()
    assert ok, "cache provenance failed BEFORE completion"
    model = OSNetWrap(V.OSNET_PATH).m.to(DEVICE).eval()
    args = [a for a in sys.argv[1:] if a in ALL_DIVES] or ALL_DIVES
    for did in args:
        t0 = time.time()
        dive_doc = fc["dives"][did]
        frames = dive_doc["frames"]
        missing_fis = [fi for fi, f in enumerate(frames)
                       if any((did, fi, k) not in cache.data
                              for k in range(len(f["c"])))]
        n_missing = sum(1 for fi in missing_fis
                        for k in range(len(frames[fi]["c"]))
                        if (did, fi, k) not in cache.data)
        print(f"== {did}: {n_missing} missing crops "
              f"({len(missing_fis)} frames)", flush=True)
        cap = cv2.VideoCapture(str(BASE / dive_doc["proxy_path"]))
        pos = -1
        done = 0
        for fi in missing_fis:
            if fi != pos + 1:
                cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
                ok_r, fr = cap.read()
                pos = fi
            else:
                ok_r, fr = cap.read()
                pos += 1
            if not ok_r or fr is None:
                print(f"  decode failed at fi {fi} (screen-recording tail?)",
                      flush=True)
                continue
            ks, crops = [], []
            for k, box in enumerate(frames[fi]["c"]):
                if (did, fi, k) in cache.data:
                    continue
                crops.append(crop_tensor(
                    fr, (box["cx"], box["cy"], box["bw"], box["bh"]),
                    pad=V.CROP_PAD))
                ks.append(k)
            for i in range(0, len(crops), BATCH):
                with torch.no_grad():
                    x = to_input(crops[i:i + BATCH], EMB_SIZE).to(DEVICE)
                    f = model(x)
                    f = torch.nn.functional.normalize(f, dim=1)
                    for j, k in enumerate(ks[i:i + BATCH]):
                        cache.data[(did, fi, k)] = f[j].cpu().numpy()
            done += len(ks)
            if done % 20000 < BATCH:
                el = time.time() - t0
                print(f"  {done}/{n_missing} ({el:.0f}s)", flush=True)
        cap.release()
        print(f"  done {done} crops in {time.time() - t0:.0f}s", flush=True)
        cache.save()  # incremental persist after every dive
    n = len(cache.data)
    print("cache size now", n)
    ok, sha16 = cache.verify()
    assert ok, "weights sha changed during completion"


if __name__ == "__main__":
    main()
