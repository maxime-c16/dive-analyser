#!/usr/bin/env python3
"""Phase D v3 — Paris full trajectory at op_conf (faster).

Uses D5-A at conf=0.05 (operating threshold) for continuous trajectory.
For anchor frames, also tries conf=0.001 (floor) with cap=50 for R1 reranking.
"""
import os, sys, json, pickle, hashlib, datetime
import cv2
import numpy as np

BASE = os.path.expanduser("~/dive-analyser")
PARIS_VIDEO = f"{BASE}/experiments/landmark_pilot/paris_source/IMG_1937.mov"
MODEL_D5 = f"{BASE}/models/frozen/DIVER_DETECTOR_D5_A_V8N_best.pt"
R1_PKL = f"{BASE}/models/frozen/R1_RERANKER.pkl"
RESULTS_DIR = f"{BASE}/docs/science"
sys.path.insert(0, f"{BASE}/experiments/landmark_pilot")

PARIS_SHA = "d122262be8e7a8721ab2f6a71721bb3544403da78324138d026360ef9820eaae"
GT = {"takeoff_s": 3.120, "apex_s": 3.570, "water_contact_s": 4.220}
GT_BOXES = {
    "takeoff":       [522.927, 542.721, 819.962, 892.428],
    "apex":          [495.202, 353.479, 665.758, 657.236],
    "water_contact": [302.188, 687.179, 525.878, 1076.603],
}
EXTRACT_START_S = 2.3
EXTRACT_END_S = 5.5
OP_CONF = 0.05      # Fast continuous trajectory
FLOOR_CONF = 0.01   # Anchor frame floor (capped to avoid NMS timeout)
FLOOR_CAP = 50
IOU_MATCH = 0.30
DIST_MATCH = 0.05
CROP_PADDING = 0.20

import torch, torchvision.transforms as T
from torchvision.models import resnet50, ResNet50_Weights
from ultralytics import YOLO

def sha256f(p):
    h = hashlib.sha256()
    with open(p,"rb") as f:
        for c in iter(lambda: f.read(65536), b""): h.update(c)
    return h.hexdigest()

def box_iou(b1,b2):
    x1=max(b1[0],b2[0]);y1=max(b1[1],b2[1]);x2=min(b1[2],b2[2]);y2=min(b1[3],b2[3])
    i=max(0,x2-x1)*max(0,y2-y1)
    return i/((b1[2]-b1[0])*(b1[3]-b1[1])+(b2[2]-b2[0])*(b2[3]-b2[1])-i+1e-9)

def cdist(b1,b2,W,H):
    c1x=(b1[0]+b1[2])/2/W; c1y=(b1[1]+b1[3])/2/H
    c2x=(b2[0]+b2[2])/2/W; c2y=(b2[1]+b2[3])/2/H
    return ((c1x-c2x)**2+(c1y-c2y)**2)**0.5

def match_gt(pred,gt,W,H):
    iou=box_iou(pred,gt); d=cdist(pred,gt,W,H)
    return (iou>=IOU_MATCH or d<=DIST_MATCH), float(iou)

def crop_box(frame, box):
    H,W=frame.shape[:2]; x1,y1,x2,y2=box
    pw,ph=(x2-x1)*CROP_PADDING,(y2-y1)*CROP_PADDING
    c=frame[max(0,int(y1-ph)):min(H,int(y2+ph)),max(0,int(x1-pw)):min(W,int(x2+pw))]
    return c if c.size>0 and min(c.shape[:2])>=2 else None

import warnings; warnings.filterwarnings('ignore')
print("Phase D v3 — Paris Full Trajectory (fast, op_conf)")
print("SHA verify...", end=" ", flush=True)
sha = sha256f(PARIS_VIDEO)
assert sha == PARIS_SHA; print("✓")

print("Loading D5-A (CPU)...", flush=True)
yolo = YOLO(MODEL_D5)

print("Loading R1 + ResNet50...", flush=True)
with open(R1_PKL,"rb") as f: r1 = pickle.load(f)
sc = r1["scaler"]; clf = r1["clf"]
bb = resnet50(weights=ResNet50_Weights.IMAGENET1K_V1)
bb.fc = torch.nn.Identity(); bb.eval().cpu()
tfm = T.Compose([T.ToPILImage(),T.Resize(256),T.CenterCrop(224),T.ToTensor(),
                 T.Normalize([0.485,0.456,0.406],[0.229,0.224,0.225])])

cap = cv2.VideoCapture(PARIS_VIDEO)
fps = cap.get(cv2.CAP_PROP_FPS); total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)); H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
print(f"Video: {W}x{H} @ {fps:.3f}fps, {total} frames")

start_fi = int(EXTRACT_START_S * fps); end_fi = min(total-1, int(EXTRACT_END_S * fps))
gt_fi = {k: round(v*fps) for k,v in GT.items()}
anchor_fis = set(gt_fi.values())
print(f"Frames {start_fi}–{end_fi} ({end_fi-start_fi+1} total), GT: {gt_fi}")

trajectory = []; anchor_frames = {}; anchor_cands = {}
cap.set(cv2.CAP_PROP_POS_FRAMES, start_fi)
fi = start_fi
print("Pass 1: D5-A inference...", flush=True)
while fi <= end_fi:
    ret, frame = cap.read()
    if not ret: break
    pts_s = fi / fps
    is_anchor = any(abs(fi-af)<=2 for af in anchor_fis)

    preds = yolo(frame, conf=OP_CONF, iou=0.45, imgsz=640, verbose=False, device="cpu")
    br = preds[0].boxes
    if br is None or len(br)==0:
        trajectory.append({"fi":fi,"pts_s":round(pts_s,4),"n_candidates":0,
                           "selected_box":None,"selected_cy_norm":None,
                           "selected_bbox_h_norm":None,"selected_conf":None,"status":"NO_DET"})
        if is_anchor: anchor_frames[fi] = frame
        fi += 1; continue

    confs = br.conf.cpu().numpy(); boxes = br.xyxy.cpu().numpy()
    order = np.argsort(-confs); confs=confs[order]; boxes=boxes[order]
    sel = boxes[0].tolist(); sel_cf = float(confs[0])
    sel_cy = (sel[1]+sel[3])/2/H; sel_h = (sel[3]-sel[1])/H
    trajectory.append({"fi":fi,"pts_s":round(pts_s,4),"n_candidates":len(confs),
                       "selected_box":[round(v,1)for v in sel],"selected_cy_norm":round(sel_cy,5),
                       "selected_bbox_h_norm":round(sel_h,5),"selected_conf":round(sel_cf,4),"status":"OK"})
    if is_anchor:
        anchor_frames[fi]=frame; anchor_cands[fi]=(boxes, confs)
    if fi % 30 == 0:
        print(f"  fi={fi} t={pts_s:.2f}s cy={sel_cy:.3f} conf={sel_cf:.3f}", flush=True)
    fi += 1
cap.release()
print(f"Pass 1 done: {len(trajectory)} frames", flush=True)

# Pass 2: anchor frames with floor conf + R1 (cap=50)
print("Pass 2: R1 on anchor frames...", flush=True)
anchor_d5_r1 = {}

def batch_feats(frame, boxes):
    tensors = []
    for b in boxes:
        c = crop_box(frame, b.tolist())
        if c is None: tensors.append(torch.zeros(3,224,224))
        else: tensors.append(tfm(cv2.cvtColor(c,cv2.COLOR_BGR2RGB)))
    if not tensors: return np.zeros((0,2048))
    with torch.no_grad(): return bb(torch.stack(tensors)).numpy()

for phase, gt_box in GT_BOXES.items():
    target_fi = gt_fi[phase + "_s"]
    stored_fi = min(anchor_frames.keys(), key=lambda f:abs(f-target_fi)) if anchor_frames else None
    if stored_fi is None or abs(stored_fi-target_fi)>3:
        anchor_d5_r1[phase] = {"error":"NO_ANCHOR_FRAME"}; continue
    frame = anchor_frames[stored_fi]
    # Re-run at floor conf but capped
    preds = yolo(frame, conf=FLOOR_CONF, iou=0.45, imgsz=640, verbose=False, device="cpu")
    br = preds[0].boxes
    if br is None or len(br)==0:
        anchor_d5_r1[phase] = {"error":"NO_DETECTION_AT_FLOOR"}; continue
    confs = br.conf.cpu().numpy(); boxes = br.xyxy.cpu().numpy()
    order = np.argsort(-confs)[:FLOOR_CAP]; confs=confs[order]; boxes=boxes[order]
    feats = batch_feats(frame, boxes)
    scores = clf.predict_proba(sc.transform(feats))[:,1]
    r1_idx = int(np.argmax(scores)); r1_box = boxes[r1_idx].tolist()
    d5_m, d5_iou = match_gt(boxes[0].tolist(), gt_box, W, H)
    r1_m, r1_iou = match_gt(r1_box, gt_box, W, H)
    anchor_d5_r1[phase] = {
        "fi":stored_fi,"pts_s":round(stored_fi/fps,3),
        "d5_rank1_correct":d5_m,"d5_rank1_iou":round(d5_iou,4),
        "r1_rank1_correct":r1_m,"r1_rank1_iou":round(r1_iou,4),
    }
    print(f"  {phase}: D5={'✓' if d5_m else '✗'}(IoU={d5_iou:.3f}) R1={'✓' if r1_m else '✗'}(IoU={r1_iou:.3f})", flush=True)

# ── Six-criteria gate ─────────────────────────────────────────────────────────
c1 = anchor_d5_r1.get("takeoff",{}).get("d5_rank1_correct", False)
c2 = anchor_d5_r1.get("apex",{}).get("d5_rank1_correct", False)
c3 = anchor_d5_r1.get("water_contact",{}).get("d5_rank1_correct", False)

flight_frames = [t for t in trajectory if GT["takeoff_s"]-0.05<=t["pts_s"]<=GT["water_contact_s"]+0.05]
n_flight = len(flight_frames)
n_ok = sum(1 for t in flight_frames if t.get("selected_box"))
coverage = n_ok/max(n_flight,1); c4 = coverage>=0.80

max_gap_s=0.0; gs=None
for t in flight_frames:
    if not t.get("selected_box"):
        if gs is None: gs=t["pts_s"]
        max_gap_s = max(max_gap_s, t["pts_s"]-gs+1/fps)
    else: gs=None
c5 = max_gap_s<=0.25

ok_t=[t for t in flight_frames if t.get("selected_cy_norm")]
rl=0; mr=0.0; pc=None
for t in ok_t:
    cy=t["selected_cy_norm"]
    if pc is not None and abs(cy-pc)>0.20: rl+=1; mr=max(mr,rl/fps)
    else: rl=0
    pc=cy
c6 = mr<=0.5

gate = "TRAJECTORY_INPUT_PASS" if all([c1,c2,c3,c4,c5,c6]) else "TRAJECTORY_INPUT_FAIL"
print(f"\n── Six-criteria ──")
print(f"  C1 takeoff: {'✓' if c1 else '✗'}  C2 apex: {'✓' if c2 else '✗'}  C3 wc: {'✓' if c3 else '✗'}")
print(f"  C4 coverage: {'✓' if c4 else '✗'} {coverage:.1%} ({n_ok}/{n_flight})")
print(f"  C5 gap: {'✓' if c5 else '✗'} {max_gap_s:.3f}s  C6 wrong-target: {'✓' if c6 else '✗'} {mr:.3f}s")
print(f"  GATE: {gate}", flush=True)

out = {
    "label":"PARIS_FULL_TRAJECTORY_V1","date":datetime.date.today().isoformat(),
    "paris_sha":PARIS_SHA,"fps":round(fps,4),"video_size":f"{W}x{H}",
    "pipeline":"D5_FRAMEWISE_PLUS_R1_AT_ANCHORS","continuous_selector":"D5_OP_CONF_TOP1",
    "op_conf":OP_CONF,"n_frames_total":len(trajectory),"n_flight_frames":n_flight,
    "anchor_validation_d5_only":{p:{"correct":anchor_d5_r1.get(p,{}).get("d5_rank1_correct",False),
                                    "iou":anchor_d5_r1.get(p,{}).get("d5_rank1_iou")} for p in GT_BOXES},
    "anchor_validation_d5_r1":{p:{"correct":anchor_d5_r1.get(p,{}).get("r1_rank1_correct",False),
                                   "iou":anchor_d5_r1.get(p,{}).get("r1_rank1_iou")} for p in GT_BOXES},
    "six_criteria":{"c1_takeoff_identity":c1,"c2_apex_identity":c2,"c3_wc_identity":c3,
                    "c4_flight_coverage":round(coverage,4),"c4_pass":c4,
                    "c5_max_gap_s":round(max_gap_s,4),"c5_pass":c5,
                    "c6_max_wrong_run_s":round(mr,4),"c6_pass":c6},
    "trajectory_gate":gate,"trajectory":trajectory,
}
with open(f"{RESULTS_DIR}/PARIS_FULL_TRAJECTORY_V1.json","w") as f:
    json.dump(out, f, indent=2)
print(f"\nSaved: {RESULTS_DIR}/PARIS_FULL_TRAJECTORY_V1.json")
