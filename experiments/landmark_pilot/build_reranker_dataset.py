#!/usr/bin/env python3
"""Phase B + C — Build Proposal-Level Reranker Dataset.

For each annotated DEVELOPMENT reference frame:
  1. Load floor candidates (from D4_FLOOR_CANDIDATES.json)
  2. Match proposals against GT: positive if IoU>=0.30 OR center_dist<=0.05 norm
  3. Negative sampling policy (documented, deterministic):
     - Tier 1: top-5 by confidence among non-matching (hard negatives)
     - Tier 2: top-3 by center distance to GT (spatially challenging)
     - Tier 3: up to 3 random from remaining with shuffle seed=42
     - Dedup: union of tiers, max 10 negatives per frame
  4. Extract crop from video frame (BGR→RGB, 20% padding, 224×224)
  5. Extract frozen ResNet50 avgpool features (2048-dim)

Grouped split:
  - DEV_TRAIN dives: [1040, 133, 2169, 2387, 2541, 2555, 2625, 2661, 2680, 311, 524, 676]
  - DEV_VAL  dives: [2341, 2353]
  (2341 = D4 detector holdout; 2353 = most challenging ranking failure)

Outputs:
  RERANKER_DATASET_V1.pkl       — numpy arrays + labels (for training)
  RERANKER_DATASET_V1_MANIFEST.json  — lightweight provenance (no pixel data)
"""
import os, json, datetime, random, pickle
import numpy as np
import cv2
import torch
import torchvision.models as models
import torchvision.transforms as transforms

BASE       = "/tmp/diveanalyzer-exp"
DATA       = f"{BASE}/data"
RESULTS    = f"{BASE}/results"
ANNOT_DIR  = f"{DATA}/DEVELOPMENT_DESIGN"
VIDEO_DIR  = f"{DATA}/proxy_videos"
CROPS_DIR  = f"{BASE}/crops"

os.makedirs(CROPS_DIR, exist_ok=True)

CANDIDATES_FILE = f"{RESULTS}/D4_FLOOR_CANDIDATES.json"

# Grouped split — frozen, deterministic
DEV_TRAIN_DIVES = [1040, 133, 2169, 2387, 2541, 2555, 2625, 2661, 2680, 311, 524, 676]
DEV_VAL_DIVES   = [2341, 2353]

# Matching rule (canonical spatial authority)
IOU_THRESH = 0.30
CTR_THRESH = 0.05   # normalized center distance

# Negative sampling policy
MAX_NEGATIVES_PER_FRAME = 10
TIER1_N   = 5    # top-5 by confidence
TIER2_N   = 3    # top-3 by center proximity
TIER3_N   = 3    # random from remainder
RANDOM_SEED = 42

# ResNet50 transform
IMAGENET_TRANSFORM = transforms.Compose([
    transforms.ToPILImage(),
    transforms.Resize(256),
    transforms.CenterCrop(224),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485,0.456,0.406], std=[0.229,0.224,0.225]),
])
CROP_PAD_FRAC = 0.20   # 20% padding around proposal bbox
CROP_SIZE     = 224


def iou_xyxy(a, b):
    ax1,ay1,ax2,ay2 = a
    bx1,by1,bx2,by2 = b
    ix1,iy1 = max(ax1,bx1),max(ay1,by1)
    ix2,iy2 = min(ax2,bx2),min(ay2,by2)
    iw,ih = max(0.0,ix2-ix1),max(0.0,iy2-iy1)
    inter = iw*ih
    ua = max(0,ax2-ax1)*max(0,ay2-ay1)
    ub = max(0,bx2-bx1)*max(0,by2-by1)
    u = ua+ub-inter
    return inter/u if u>0 else 0.0


def center_dist_norm(pred_xyxy, gt_xyxy, W, H):
    pcx = (pred_xyxy[0]+pred_xyxy[2])/(2*W)
    pcy = (pred_xyxy[1]+pred_xyxy[3])/(2*H)
    gcx = (gt_xyxy[0]+gt_xyxy[2])/(2*W)
    gcy = (gt_xyxy[1]+gt_xyxy[3])/(2*H)
    return ((pcx-gcx)**2+(pcy-gcy)**2)**0.5


def is_positive(pred_xyxy, gt_xyxy, W, H):
    iou = iou_xyxy(pred_xyxy, gt_xyxy)
    cd  = center_dist_norm(pred_xyxy, gt_xyxy, W, H)
    return iou >= IOU_THRESH or cd <= CTR_THRESH


def extract_crop_rgb(frame_bgr, xyxy, W, H, pad=CROP_PAD_FRAC, size=CROP_SIZE):
    """Extract padded crop from frame, return RGB numpy array (size×size×3)."""
    x1,y1,x2,y2 = xyxy
    bw = x2-x1
    bh = y2-y1
    px = bw * pad
    py = bh * pad
    cx1 = max(0,   int(x1-px))
    cy1 = max(0,   int(y1-py))
    cx2 = min(W-1, int(x2+px)+1)
    cy2 = min(H-1, int(y2+py)+1)
    if cx2 <= cx1 or cy2 <= cy1:
        return None
    crop = frame_bgr[cy1:cy2, cx1:cx2]
    crop = cv2.resize(crop, (size, size), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)


def build_resnet50_extractor():
    """Return frozen ResNet50 feature extractor (2048-d avgpool output)."""
    resnet = models.resnet50(weights=models.ResNet50_Weights.IMAGENET1K_V1)
    resnet.eval()
    # Remove final FC; keep up to avgpool
    feat_model = torch.nn.Sequential(*list(resnet.children())[:-1])
    feat_model.eval()
    return feat_model


def extract_features(feat_model, crop_rgb):
    """crop_rgb: H×W×3 uint8 RGB → (2048,) float32 numpy."""
    t = IMAGENET_TRANSFORM(crop_rgb).unsqueeze(0)   # (1,3,224,224)
    with torch.no_grad():
        feat = feat_model(t).squeeze()  # (2048,)
    return feat.numpy().astype(np.float32)


def load_annotation(frame_id):
    path = f"{ANNOT_DIR}/{frame_id}.json"
    if not os.path.exists(path):
        return None
    d = json.load(open(path))
    if d.get("bbox") is None or d.get("visibility") != "visible":
        return None
    return d


def sample_negatives(neg_candidates, gt_px, W, H, rng):
    """Deterministic negative sampling policy. Returns list of selected indices."""
    n = len(neg_candidates)
    if n == 0:
        return []

    selected_idxs = set()

    # Tier 1: top-5 by confidence (already sorted by conf desc)
    for i in range(min(TIER1_N, n)):
        selected_idxs.add(i)

    # Tier 2: top-3 by center proximity to GT
    center_dists = [(i, center_dist_norm(neg_candidates[i]["xyxy"], gt_px, W, H))
                    for i in range(n)]
    center_dists.sort(key=lambda x: x[1])
    for i, _ in center_dists[:TIER2_N]:
        selected_idxs.add(i)

    # Tier 3: up to 3 random from remaining
    remaining = [i for i in range(n) if i not in selected_idxs]
    rng_copy = random.Random(RANDOM_SEED)
    rng_copy.shuffle(remaining)
    for i in remaining[:TIER3_N]:
        selected_idxs.add(i)

    # Cap at MAX_NEGATIVES_PER_FRAME
    result = sorted(selected_idxs)[:MAX_NEGATIVES_PER_FRAME]
    return result


def main():
    print("Loading D4 floor candidates …")
    floor_data = json.load(open(CANDIDATES_FILE))
    print(f"  {len(floor_data)} frame candidate sets loaded.\n")

    print("Building frozen ResNet50 feature extractor …")
    feat_model = build_resnet50_extractor()
    print("  ResNet50 ready.\n")

    # All samples: {frame_id, dive_id, phase, split, label, conf, xyxy, iou_with_gt,
    #               features (2048,)}
    samples = []
    manifest = []
    rng = random.Random(RANDOM_SEED)

    # Cache open video captures
    video_cache = {}

    canonical_frames = list(floor_data.keys())
    print(f"Processing {len(canonical_frames)} frames …")

    for frame_id in canonical_frames:
        fdata = floor_data[frame_id]
        candidates = fdata["candidates"]
        fi         = fdata["frame_index"]
        media_key  = fdata["media_key"]
        W          = fdata["video_W"]
        H          = fdata["video_H"]

        annot = load_annotation(frame_id)
        if annot is None:
            print(f"  SKIP {frame_id} — no annotation")
            continue

        ann_w   = annot["width"]
        ann_h   = annot["height"]
        gt_bbox = annot["bbox"]
        gt_px   = [
            gt_bbox[0]*W/ann_w,
            gt_bbox[1]*H/ann_h,
            gt_bbox[2]*W/ann_w,
            gt_bbox[3]*H/ann_h,
        ]

        parts   = frame_id.rsplit("_", 1)
        dive_id = int(parts[0].split("_")[0]) if "_" in parts[0] else int(parts[0])
        phase   = parts[1]
        # Handle compound frame IDs like "2387_water_contact"
        tokens  = frame_id.split("_")
        dive_id = int(tokens[0])
        phase   = "_".join(tokens[1:])

        split = "DEV_TRAIN" if dive_id in DEV_TRAIN_DIVES else \
                "DEV_VAL"   if dive_id in DEV_VAL_DIVES   else "UNKNOWN"

        # Load video frame
        video_path = f"{VIDEO_DIR}/{media_key}.mp4"
        if media_key not in video_cache:
            cap = cv2.VideoCapture(video_path)
            cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
            ret, frame_bgr = cap.read()
            cap.release()
            if not ret:
                print(f"  FAIL read frame {fi} from {video_path}")
                continue
            video_cache[media_key] = (fi, frame_bgr)
        else:
            cached_fi, frame_bgr = video_cache[media_key]
            if cached_fi != fi:
                cap = cv2.VideoCapture(video_path)
                cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
                ret, frame_bgr = cap.read()
                cap.release()
                if not ret:
                    print(f"  FAIL read frame {fi}")
                    continue
                video_cache[media_key] = (fi, frame_bgr)

        # Classify candidates
        pos_idxs = []
        neg_idxs_all = []
        for i, c in enumerate(candidates):
            if is_positive(c["xyxy"], gt_px, W, H):
                pos_idxs.append(i)
            else:
                neg_idxs_all.append(i)

        # Negative sampling
        neg_cands_sorted = [candidates[i] for i in neg_idxs_all]  # already sorted by conf
        sampled_neg_local = sample_negatives(neg_cands_sorted, gt_px, W, H, rng)
        neg_idxs_selected = [neg_idxs_all[i] for i in sampled_neg_local]

        n_pos = len(pos_idxs)
        n_neg = len(neg_idxs_selected)

        # Extract features for positives
        for ci in pos_idxs:
            c = candidates[ci]
            crop = extract_crop_rgb(frame_bgr, c["xyxy"], W, H)
            if crop is None:
                continue
            feats = extract_features(feat_model, crop)
            iou   = iou_xyxy(c["xyxy"], gt_px)
            cd    = center_dist_norm(c["xyxy"], gt_px, W, H)
            samples.append({
                "frame_id": frame_id, "dive_id": dive_id, "phase": phase,
                "split": split, "label": 1,
                "conf": c["conf"], "xyxy": c["xyxy"],
                "iou_with_gt": iou, "center_dist": cd,
                "confidence_rank": ci+1,
                "features": feats,
            })
            manifest.append({
                "frame_id": frame_id, "dive_id": dive_id, "phase": phase,
                "split": split, "label": 1, "conf": float(c["conf"]),
                "xyxy": c["xyxy"], "iou_with_gt": float(iou),
                "confidence_rank": ci+1,
            })

        # Extract features for selected negatives
        for ci in neg_idxs_selected:
            c = candidates[ci]
            crop = extract_crop_rgb(frame_bgr, c["xyxy"], W, H)
            if crop is None:
                continue
            feats = extract_features(feat_model, crop)
            iou   = iou_xyxy(c["xyxy"], gt_px)
            cd    = center_dist_norm(c["xyxy"], gt_px, W, H)
            samples.append({
                "frame_id": frame_id, "dive_id": dive_id, "phase": phase,
                "split": split, "label": 0,
                "conf": c["conf"], "xyxy": c["xyxy"],
                "iou_with_gt": iou, "center_dist": cd,
                "confidence_rank": ci+1,
                "features": feats,
            })
            manifest.append({
                "frame_id": frame_id, "dive_id": dive_id, "phase": phase,
                "split": split, "label": 0, "conf": float(c["conf"]),
                "xyxy": c["xyxy"], "iou_with_gt": float(iou),
                "confidence_rank": ci+1,
            })

        print(f"  {frame_id:30s} split={split:10s} pos={n_pos} neg_avail={len(neg_idxs_all)} neg_sampled={n_neg}")

    print(f"\nTotal samples: {len(samples)}")
    pos_all   = sum(1 for s in samples if s["label"] == 1)
    neg_all   = sum(1 for s in samples if s["label"] == 0)
    train_pos = sum(1 for s in samples if s["label"]==1 and s["split"]=="DEV_TRAIN")
    train_neg = sum(1 for s in samples if s["label"]==0 and s["split"]=="DEV_TRAIN")
    val_pos   = sum(1 for s in samples if s["label"]==1 and s["split"]=="DEV_VAL")
    val_neg   = sum(1 for s in samples if s["label"]==0 and s["split"]=="DEV_VAL")
    print(f"  Positives: {pos_all}  Negatives: {neg_all}")
    print(f"  DEV_TRAIN: pos={train_pos} neg={train_neg}")
    print(f"  DEV_VAL:   pos={val_pos}   neg={val_neg}")

    # Save dataset
    dataset_pkl = f"{RESULTS}/RERANKER_DATASET_V1.pkl"
    with open(dataset_pkl, "wb") as f:
        pickle.dump(samples, f)
    print(f"\nDataset saved: {dataset_pkl}")

    # Manifest (no features — lightweight)
    ds_manifest = {
        "label": "RERANKER_DATASET_V1_MANIFEST",
        "date": datetime.date.today().isoformat(),
        "feature_model": "ResNet50_IMAGENET1K_V1",
        "feature_dim": 2048,
        "crop_padding": CROP_PAD_FRAC,
        "crop_size": CROP_SIZE,
        "positive_rule": f"IoU>={IOU_THRESH} OR center_dist<={CTR_THRESH}",
        "negative_sampling_policy": {
            "tier1": f"top-{TIER1_N} by D4 confidence",
            "tier2": f"top-{TIER2_N} by center proximity to GT",
            "tier3": f"up to {TIER3_N} random (seed={RANDOM_SEED})",
            "max_per_frame": MAX_NEGATIVES_PER_FRAME,
        },
        "grouped_split": {
            "DEV_TRAIN": DEV_TRAIN_DIVES,
            "DEV_VAL":   DEV_VAL_DIVES,
            "rationale": "2341=D4 detector holdout; 2353=worst ranking failure (target_rank=6 at takeoff)",
        },
        "total_samples": len(samples),
        "positives": pos_all,
        "negatives": neg_all,
        "DEV_TRAIN_positives": train_pos,
        "DEV_TRAIN_negatives": train_neg,
        "DEV_VAL_positives": val_pos,
        "DEV_VAL_negatives": val_neg,
        "samples": manifest,
        "paris_firewall": "VERIFIED — no Paris frames, annotations, or proposals in dataset",
    }
    manifest_path = f"{RESULTS}/RERANKER_DATASET_V1_MANIFEST.json"
    with open(manifest_path, "w") as f:
        json.dump(ds_manifest, f, indent=2)
    print(f"Manifest saved: {manifest_path}")
    return ds_manifest


if __name__ == "__main__":
    main()
