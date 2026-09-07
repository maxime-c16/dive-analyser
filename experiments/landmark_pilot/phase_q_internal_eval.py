#!/usr/bin/env python3
"""Phase Q — Bounded Multi-Dive Internal Evaluation.

Run DIVER_DETECTOR_D2_V8N on 6 internal development-design proxy videos
(360p landscape) to assess in-distribution detection performance.

These are DEVELOPMENT_DESIGN dives — not used for training, not the Paris canary.
NO GT event labels are used; this is a pure detection rate / recall check.
Dive 192 is INTERNAL_EVAL (the internal canary).

Dive mapping:
  192  → 203C  (INTERNAL_EVAL)
  311  → 401C
  2169 → 101B
  2387 → 5411C
  2555 → 5132D
  2661 → 010B
"""

import sys, json, hashlib, time
from pathlib import Path

# venv with ultralytics
VENV_PY = Path("/home/mcauchy/dive-analyser/experiments/landmark_pilot/venv_c/bin/python3")

WEIGHTS_PATH = Path(
    "/home/mcauchy/dive-analyser/experiments/landmark_pilot/runs/DIVER_DETECTOR_D2_V8N_best.pt"
)
WEIGHTS_SHA_PREFIX = "488828723dff1be6"

# Proxy paths on server host
PROXY_BASE = Path("/home/mcauchy/dive-analyser/media/cache/proxy_360p")

DIVES = [
    {"dive_id": 192,  "dive_code": "203C",  "split": "INTERNAL_EVAL",
     "sha_prefix": "f52ad790",
     "proxy": "f5/2a/f52ad7906a20758544d8563fe422ba7ef6dffdf16ac5643a50d6dc46d8228aab.mp4"},
    {"dive_id": 311,  "dive_code": "401C",  "split": "DEVELOPMENT_DESIGN",
     "sha_prefix": "dc1d176e",
     "proxy": "dc/1d/dc1d176ed1ed24e004a6634f0ee91ae3e5150645a85380f33db399f55bedf10c.mp4"},
    {"dive_id": 2169, "dive_code": "101B",  "split": "DEVELOPMENT_DESIGN",
     "sha_prefix": "85c81842",
     "proxy": "85/c8/85c81842b1f892d0919d8db1dcaee3ed01a93d294d3cc350643b198988e844b0.mp4"},
    {"dive_id": 2387, "dive_code": "5411C", "split": "DEVELOPMENT_DESIGN",
     "sha_prefix": "e7bb8646",
     "proxy": "e7/bb/e7bb8646edf66df370f0ff4958c1bf4736cb41df0e461428084fa6fa6486fc4a.mp4"},
    {"dive_id": 2555, "dive_code": "5132D", "split": "DEVELOPMENT_DESIGN",
     "sha_prefix": "dd7a8621",
     "proxy": "dd/7a/dd7a8621a89bd00af627560e2121dec4bacecb313d8b5ecd5027d91f2f9c9e44.mp4"},
    {"dive_id": 2661, "dive_code": "010B",  "split": "DEVELOPMENT_DESIGN",
     "sha_prefix": "23b13b30",
     "proxy": "23/b1/23b13b30ebf4915a039bef8d0eff9c31a6a19df8142bb781ed5895290f203184.mp4"},
]

CONF = 0.25
IOU = 0.45
IMGSZ = 640

OUT_PATH = Path(__file__).parent / "phase_q_internal_eval_result.json"


def sha256_prefix(path: Path, n: int = 16) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:n]


def run_inference_on_video(model, video_path: Path) -> dict:
    """Run model on video, return per-frame detection stats."""
    frames = []
    for frame_idx, r in enumerate(model.predict(
        source=str(video_path),
        conf=CONF, iou=IOU, imgsz=IMGSZ,
        device="cpu",  # server CPU (no MPS, no CUDA)
        stream=True, verbose=False,
    )):
        if r.boxes is not None and len(r.boxes) > 0:
            confs = r.boxes.conf.cpu().numpy().tolist()
            best_i = int(r.boxes.conf.argmax())
            xyxyn = r.boxes.xyxyn.cpu().numpy()
            best_cx = float((xyxyn[best_i][0] + xyxyn[best_i][2]) / 2)
            best_cy = float((xyxyn[best_i][1] + xyxyn[best_i][3]) / 2)
            frames.append({
                "frame_idx": frame_idx,
                "n_detections": len(confs),
                "best_conf": float(r.boxes.conf[best_i]),
                "best_cx": best_cx,
                "best_cy": best_cy,
            })
        else:
            frames.append({"frame_idx": frame_idx, "n_detections": 0,
                           "best_conf": 0.0, "best_cx": None, "best_cy": None})
    return frames


def analyze(frames: list) -> dict:
    n = len(frames)
    detected = [f for f in frames if f["n_detections"] > 0]
    rate = len(detected) / n if n > 0 else 0.0
    confs = [f["best_conf"] for f in detected]
    cy_vals = [f["best_cy"] for f in detected if f.get("best_cy") is not None]
    cy_mean = sum(cy_vals) / len(cy_vals) if cy_vals else None
    cy_std = (sum((v - cy_mean) ** 2 for v in cy_vals) / len(cy_vals)) ** 0.5 if cy_vals else None
    return {
        "n_frames": n,
        "n_detected": len(detected),
        "detection_rate": round(rate, 4),
        "mean_conf_when_detected": round(sum(confs) / len(confs), 4) if confs else 0.0,
        "cy_mean": round(cy_mean, 4) if cy_mean is not None else None,
        "cy_std": round(cy_std, 4) if cy_std is not None else None,
    }


def main():
    print("=" * 60)
    print("PHASE Q — Bounded Multi-Dive Internal Evaluation")
    print("=" * 60)
    print(f"Model: DIVER_DETECTOR_D2_V8N  conf={CONF}  iou={IOU}  imgsz={IMGSZ}  device=cpu")
    print()

    # Verify weights
    actual_sha = sha256_prefix(WEIGHTS_PATH, 16)
    assert actual_sha == WEIGHTS_SHA_PREFIX, f"Weights SHA mismatch: {actual_sha}"
    print(f"Weights verified: {actual_sha}...")

    from ultralytics import YOLO
    model = YOLO(str(WEIGHTS_PATH))
    print("Model loaded.\n")

    results = []
    for dive in DIVES:
        proxy = PROXY_BASE / dive["proxy"]
        if not proxy.exists():
            print(f"  SKIP dive {dive['dive_id']}: proxy not found at {proxy}")
            results.append({**dive, "error": "proxy_not_found", "stats": None})
            continue

        print(f"  Dive {dive['dive_id']} ({dive['dive_code']}, {dive['split']}): {proxy.name[:16]}...")
        t0 = time.monotonic()
        frames = run_inference_on_video(model, proxy)
        elapsed = time.monotonic() - t0
        stats = analyze(frames)
        print(f"    → n_frames={stats['n_frames']}, detected={stats['n_detected']}, "
              f"rate={stats['detection_rate']:.3f}, mean_conf={stats['mean_conf_when_detected']:.3f} "
              f"({elapsed:.1f}s)")
        results.append({**dive, "stats": stats, "elapsed_s": round(elapsed, 1)})

    # Summary
    valid = [r for r in results if r.get("stats")]
    mean_rate = sum(r["stats"]["detection_rate"] for r in valid) / len(valid) if valid else 0.0
    print(f"\nSummary: mean detection_rate={mean_rate:.3f} across {len(valid)} dives")

    output = {
        "label": "PHASE_Q_INTERNAL_EVAL",
        "date": "2026-09-07",
        "model": "DIVER_DETECTOR_D2_V8N",
        "weights_sha_prefix": WEIGHTS_SHA_PREFIX,
        "config": {"conf": CONF, "iou": IOU, "imgsz": IMGSZ, "device": "cpu"},
        "n_dives": len(DIVES),
        "n_evaluated": len(valid),
        "mean_detection_rate": round(mean_rate, 4),
        "per_dive": results,
        "interpretation": {
            "purpose": "In-distribution check: does D2 detect at all on the training-pool proxies?",
            "paris_canary_rate": 0.0,
            "comparison": "If mean_rate >> 0, generalization failure is domain-specific (external venue), not model capacity.",
        },
    }
    OUT_PATH.write_text(json.dumps(output, indent=2) + "\n")
    print(f"\nResult written to {OUT_PATH}")
    print(json.dumps({k: v for k, v in output.items() if k != "per_dive"}, indent=2))
    return output


if __name__ == "__main__":
    main()
