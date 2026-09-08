#!/usr/bin/env python3
"""Build DIVER_LOCALIZATION_DATASET_D4 — Phase F.

Sources:
  A. D2 YOLO positives (85 images, existing v1_*/v2_* split preserved)
  B. D3 hard negatives (35 not_visible from DEVELOPMENT_DESIGN_V2, D3 split)
  C. D4 batch (22 frames: 19 pos + 3 neg, split by failure-dive rule)

Split rules for D4 batch:
  - Dive 2341 -> HOLDOUT (withheld evaluation dive)
  - Dive 2555, 2680, 676, 2541, 2625, 2169 -> TRAIN
"""
import json, os, shutil, hashlib

REPO = os.path.expanduser("~/dive-analyser")
os.chdir(REPO)

D2_YOLO = "docs/science/localization_annotations_v1/DATASET_D2_YOLO"
V2_DIR = "docs/science/localization_annotations_v1/DEVELOPMENT_DESIGN_V2"
D4_BATCH_DIR = "docs/science/localization_annotations_v1/D4_ANNOTATION_BATCH"
D3_MANIFEST = "docs/science/localization_annotations_v1/DATASET_D3_YOLO/DATASET_D3_MANIFEST.json"
OUT = "/tmp/d4_work/DIVER_LOCALIZATION_DATASET_D4"
MANIFEST_OUT = "docs/science/DATASET_D4_MANIFEST.json"

PARIS_KEY = "d122262be8e7a8721ab2f6a71721bb3544403da78324138d026360ef9820eaae"
HOLDOUT_DIVES = {2341}

def sha256(p):
    h = hashlib.sha256()
    with open(p,'rb') as f:
        for chunk in iter(lambda: f.read(1<<20), b''): h.update(chunk)
    return h.hexdigest()

def make_dirs():
    for sp in ['train','val','holdout']:
        os.makedirs(f"{OUT}/images/{sp}", exist_ok=True)
        os.makedirs(f"{OUT}/labels/{sp}", exist_ok=True)

def copy_pair(src_img, src_lbl, split, frame_id, source, dive_id, is_pos, records):
    assert PARIS_KEY not in open(src_lbl).read() if os.path.exists(src_lbl) else True
    dst_img = f"{OUT}/images/{split}/{frame_id}.jpg"
    dst_lbl = f"{OUT}/labels/{split}/{frame_id}.txt"
    shutil.copy2(src_img, dst_img)
    shutil.copy2(src_lbl, dst_lbl) if os.path.exists(src_lbl) else open(dst_lbl,'w').close()
    records.append({"frame_id": frame_id, "split": split, "source": source,
                    "dive_id": dive_id, "is_positive": is_pos,
                    "image_sha256": sha256(dst_img)})

def bbox_to_yolo(bbox, w, h):
    x1,y1,x2,y2 = bbox
    return (x1+x2)/2/w, (y1+y2)/2/h, (x2-x1)/w, (y2-y1)/h

make_dirs()
records = []
splits_count = {'train':{'pos':0,'neg':0}, 'val':{'pos':0,'neg':0}, 'holdout':{'pos':0,'neg':0}}

# ── A. D2 YOLO positives (preserve split) ─────────────────────────────────────
d2_added = 0
for sp in ['train','val','holdout']:
    idir = f"{D2_YOLO}/images/{sp}"
    ldir = f"{D2_YOLO}/labels/{sp}"
    if not os.path.isdir(idir): continue
    for fname in sorted(os.listdir(idir)):
        if not fname.endswith('.jpg'): continue
        fid = fname[:-4]
        src_img = f"{idir}/{fname}"
        src_lbl = f"{ldir}/{fid}.txt"
        # Infer dive_id from filename
        if fid.startswith('v1_'):
            parts = fid[3:].rsplit('_',1)
            dive_id = int(parts[0]) if parts[0].isdigit() else -1
        elif fid.startswith('v2_d'):
            dive_id = int(fid[4:].split('_')[0])
        else:
            dive_id = -1
        copy_pair(src_img, src_lbl, sp, f"d2_{fid}", "D2", dive_id, True, records)
        splits_count[sp]['pos'] += 1
        d2_added += 1
print(f"A. D2 positives: {d2_added}")

# ── B. D3 hard negatives (preserve D3 split) ──────────────────────────────────
v2 = json.load(open(f"{V2_DIR}/manifest.json"))
d3m = json.load(open(D3_MANIFEST))
neg_map = {}
for fid in d3m['neg_train_sources']: neg_map[fid] = 'train'
for fid in d3m['neg_val_sources']: neg_map[fid] = 'val'
for fid in d3m['neg_holdout_sources']: neg_map[fid] = 'holdout'

v2_map = {f['frame_id']: f for f in v2['frames']}
neg_added = 0
for fid, sp in sorted(neg_map.items()):
    src_img = f"{V2_DIR}/frames/{fid}.jpg"
    if not os.path.exists(src_img):
        print(f"  WARN neg missing: {src_img}")
        continue
    f_meta = v2_map.get(fid, {})
    mk = f_meta.get('media_key','')
    if mk == PARIS_KEY:
        print(f"  PARIS BLOCK neg: {fid}")
        continue
    dive_id = f_meta.get('dive_id', -1)
    dst_img = f"{OUT}/images/{sp}/neg_{fid}.jpg"
    dst_lbl = f"{OUT}/labels/{sp}/neg_{fid}.txt"
    shutil.copy2(src_img, dst_img)
    open(dst_lbl,'w').close()  # empty label = hard negative
    records.append({"frame_id": f"neg_{fid}", "split": sp, "source": "D3_HARD_NEGATIVE",
                    "dive_id": dive_id, "is_positive": False,
                    "image_sha256": sha256(dst_img)})
    splits_count[sp]['neg'] += 1
    neg_added += 1
print(f"B. D3 hard negatives: {neg_added}")

# ── C. D4 annotation batch ────────────────────────────────────────────────────
d4m = json.load(open(f"{D4_BATCH_DIR}/manifest.json"))
d4_pos = d4_neg = 0

for f in d4m['frames']:
    ann = f.get('annotation', {})
    if ann.get('state') != 'HUMAN_REVIEWED':
        print(f"  WARN not reviewed: {f['frame_id']}")
        continue
    mk = f.get('media_key','')
    if mk == PARIS_KEY:
        print(f"  PARIS BLOCK D4: {f['frame_id']}")
        continue
    dive = f['dive_id']
    vis = ann.get('visibility','')
    bbox = ann.get('bbox')
    is_pos = (vis == 'visible' and bbox is not None)

    sp = 'holdout' if dive in HOLDOUT_DIVES else 'train'

    src_img = f"{D4_BATCH_DIR}/{f['frame_file']}"
    if not os.path.exists(src_img):
        print(f"  WARN D4 missing: {src_img}")
        continue
    w, h = f.get('width', 202), f.get('height', 360)
    fid = f"d4_{f['frame_id']}"
    dst_img = f"{OUT}/images/{sp}/{fid}.jpg"
    dst_lbl = f"{OUT}/labels/{sp}/{fid}.txt"
    shutil.copy2(src_img, dst_img)
    if is_pos:
        cx,cy,bw,bh = bbox_to_yolo(bbox, w, h)
        with open(dst_lbl,'w') as lf: lf.write(f"0 {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}\n")
    else:
        open(dst_lbl,'w').close()
    records.append({"frame_id": fid, "split": sp, "source": "D4_ANNOTATION_BATCH",
                    "dive_id": dive, "is_positive": is_pos,
                    "image_sha256": sha256(dst_img)})
    splits_count[sp]['pos' if is_pos else 'neg'] += 1
    if is_pos: d4_pos += 1
    else: d4_neg += 1

print(f"C. D4 batch: {d4_pos} pos + {d4_neg} neg")

# ── dataset.yaml ──────────────────────────────────────────────────────────────
with open(f"{OUT}/dataset.yaml",'w') as f:
    f.write(f"""path: {OUT}
train: images/train
val: images/val
test: images/holdout

nc: 1
names:
  0: visible_diver

# DIVER_LOCALIZATION_DATASET_D4
# A: D2 YOLO positives (85, split preserved)
# B: D3 hard negatives (35, split preserved)
# C: D4 annotation batch (22 new, failure-drive split)
# Holdout failure dives: 2341 (withheld evaluation)
# Paris firewall: no IMG_1937.mov / dive 2819
# Training requires amp=False (MPS AMP gradient collapse)
""")

# ── Summary + manifest ────────────────────────────────────────────────────────
print()
print("=== D4 DATASET ===")
total = 0
for sp in ['train','val','holdout']:
    p,n = splits_count[sp]['pos'], splits_count[sp]['neg']
    print(f"  {sp}: {p} pos + {n} neg = {p+n}")
    total += p+n
print(f"  TOTAL: {total}")

manifest = {
    "label": "DIVER_LOCALIZATION_DATASET_D4",
    "date": "2026-09-08",
    "class_def": "class 0 = visible_diver",
    "paris_firewall": "VERIFIED — no IMG_1937.mov frames",
    "splits": {sp: {"positive": splits_count[sp]['pos'], "negative": splits_count[sp]['neg'],
                    "total": splits_count[sp]['pos']+splits_count[sp]['neg']} for sp in splits_count},
    "sources": {"D2": d2_added, "D3_HARD_NEGATIVE": neg_added,
                "D4_ANNOTATION_BATCH_POS": d4_pos, "D4_ANNOTATION_BATCH_NEG": d4_neg},
    "holdout_failure_dives": [2341],
    "train_failure_dives": [2555, 2680, 676, 2541],
    "records": records,
}
with open(MANIFEST_OUT,'w') as f: json.dump(manifest, f, indent=2)
print(f"\nDataset: {OUT}")
print(f"Manifest: {MANIFEST_OUT}")
print("DONE")
