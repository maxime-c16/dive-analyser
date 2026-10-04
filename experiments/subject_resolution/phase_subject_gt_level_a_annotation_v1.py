#!/usr/bin/env python3
"""DIVE_ANALYZER_SUBJECT_GT_LEVEL_A_ANNOTATION_V1 — Level-A subject GT for STANDING.

Deterministic annotation queue from the frozen SUBJECT_GT_MINIMUM_ANNOTATION_PLAN_V1,
lightweight blind annotation UI, mechanical validation, and authority freeze.

Subcommands:
  queue      regenerate the deterministic Level-A queue (metadata only, in Git)
  extract    extract queue frames from frozen proxies (outside Git)
  serve      run the blind annotation UI (127.0.0.1 only)
  validate   mechanical Phase-7 validation of the draft annotations
  freeze     freeze the Level-A authority artifact (Phase 9)

Human authority invariant: only HUMAN_REVIEWED annotations written by the human
annotator through the UI are collected. No model output may become GT.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
STANDING_DIVES = ["133", "311", "676", "2387"]
FAMILY = "STANDING"
LABEL = "DIVE_ANALYZER_SUBJECT_GT_LEVEL_A_ANNOTATION_V1"
QUEUE_LABEL = "SUBJECT_GT_LEVEL_A_QUEUE_STANDING_V1"

D5_CACHE = REPO / "runs/subject_resolution/R5_FULLCLIP_CANDIDATES_COHORT_V1.json"
LOC_ANN = REPO / "docs/science/localization_annotations_v1"
WORK_DIR = REPO / "runs/subject_gt_level_a_v1"
QUEUE_PATH = REPO / f"docs/science/{QUEUE_LABEL}.json"
DRAFT_PATH = WORK_DIR / "annotations_draft.json"
EXTRA_CONF_FLOOR = 0.05     # project hint floor (D4/D5 batch convention)
EXTRA_DIST_MAX = 0.10       # frozen plan: "two people within ~0.1 normalized distance"
EXTRA_IOU_MAX = 0.50        # distinct detections only
EXTRA_OFFSET_S = 0.25       # midpoint between base grid points
GRID_STEP_S = 0.5
WINDOW_TAIL_S = 0.5         # eval window [0, water_contact + 0.5 s]

# Existing human annotation sources eligible for reuse (exact frame_index match).
# ONLY DEVELOPMENT_DESIGN event frames carry subject-identity semantics ("intended
# subject" anchors, used as such by prior packets). D4/D5 batch mining boxes were
# collected as generic diver boxes for detector repair; upgrading them to subject
# identity silently would be a semantics violation, so those frames are labeled
# fresh with subject semantics instead (historical artifacts stay untouched).
REUSE_SOURCES = [
    ("DEVELOPMENT_DESIGN", LOC_ANN / "DEVELOPMENT_DESIGN"),
    ("D4_ANNOTATION_BATCH", LOC_ANN / "D4_ANNOTATION_BATCH/manifest.json"),
    ("D5_ANNOTATION_BATCH", LOC_ANN / "D5_ANNOTATION_BATCH/manifest.json"),
]
REUSE_ELIGIBLE_SOURCES = {"DEVELOPMENT_DESIGN"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_existing_human_annotations() -> dict:
    """All existing HUMAN_REVIEWED annotations for the STANDING cohort dives,
    keyed by (dive_id, frame_index)."""
    out = {}
    for source, path in REUSE_SOURCES:
        if path.is_dir():
            for p in sorted(path.glob("*.json")):
                d = json.loads(p.read_text())
                if str(d.get("dive_id")) not in STANDING_DIVES:
                    continue
                if d.get("state") != "HUMAN_REVIEWED":
                    continue
                key = (str(d["dive_id"]), int(d["frame_index"]))
                out[key] = {
                    "source_artifact": source,
                    "source_file": str(p.relative_to(REPO)),
                    "bbox": d.get("bbox"),
                    "visibility": d.get("visibility"),
                    "annotator": d.get("annotator"),
                    "annotated_at": d.get("annotated_at") or d.get("reviewed_at"),
                    "width": d.get("width"),
                    "height": d.get("height"),
                }
        else:
            m = json.loads(path.read_text())
            for fr in m.get("frames", []):
                if str(fr.get("dive_id")) not in STANDING_DIVES:
                    continue
                ann = fr.get("annotation") or {}
                if ann.get("state") != "HUMAN_REVIEWED":
                    continue
                key = (str(fr["dive_id"]), int(fr["frame_index"]))
                out[key] = {
                    "source_artifact": source,
                    "source_file": str(path.relative_to(REPO)),
                    "source_frame_id": fr.get("frame_id"),
                    "bbox": ann.get("bbox"),
                    "visibility": ann.get("visibility"),
                    "annotator": ann.get("annotator"),
                    "annotated_at": ann.get("annotated_at"),
                    "width": fr.get("width"),
                    "height": fr.get("height"),
                }
    return out


def water_contacts() -> dict:
    """Frozen temporal authority: DEVELOPMENT_DESIGN water_contact frame indices."""
    out = {}
    for dive in STANDING_DIVES:
        p = LOC_ANN / "DEVELOPMENT_DESIGN" / f"{dive}_water_contact.json"
        d = json.loads(p.read_text())
        out[dive] = {
            "frame_index": int(d["frame_index"]),
            "fps": float(d["fps"]),
            "source_file": str(p.relative_to(REPO)),
            "sha256": sha256_file(p),
        }
    return out


def close_pairs_at(dive: str, frame_index: int, cache_dives: dict) -> list:
    """Deterministic close-person evidence from the frozen D5 candidate cache."""
    dv = cache_dives[dive]
    by_fi = {f["fi"] - 1: f for f in dv["frames"]}
    f = by_fi.get(frame_index)
    if not f:
        return []
    cands = [c for c in f["c"] if c["conf"] >= EXTRA_CONF_FLOOR]
    pairs = []
    for i in range(len(cands)):
        for j in range(i + 1, len(cands)):
            a, b = cands[i], cands[j]
            ax1, ay1 = a["cx"] - a["bw"] / 2, a["cy"] - a["bh"] / 2
            ax2, ay2 = a["cx"] + a["bw"] / 2, a["cy"] + a["bh"] / 2
            bx1, by1 = b["cx"] - b["bw"] / 2, b["cy"] - b["bh"] / 2
            bx2, by2 = b["cx"] + b["bw"] / 2, b["cy"] + b["bh"] / 2
            iw = max(0.0, min(ax2, bx2) - max(ax1, bx1))
            ih = max(0.0, min(ay2, by2) - max(ay1, by1))
            inter = iw * ih
            union = a["bw"] * a["bh"] + b["bw"] * b["bh"] - inter
            iou = inter / union if union > 0 else 0.0
            dist = ((a["cx"] - b["cx"]) ** 2 + (a["cy"] - b["cy"]) ** 2) ** 0.5
            dist_norm = dist / ((a["bh"] + b["bh"]) / 2)
            if iou < EXTRA_IOU_MAX and dist_norm < EXTRA_DIST_MAX:
                pairs.append({
                    "dist_norm": round(dist_norm, 4),
                    "iou": round(iou, 4),
                    "confs": [round(a["conf"], 4), round(b["conf"], 4)],
                })
    pairs.sort(key=lambda p: (p["dist_norm"], p["iou"]))
    return pairs


def build_queue() -> dict:
    cache = json.loads(D5_CACHE.read_text())
    wcs = water_contacts()
    existing = load_existing_human_annotations()
    items: list[dict] = []
    seen: set[tuple[str, int]] = set()

    def add(dive: str, frame_index: int, reason: str, evidence=None):
        key = (dive, frame_index)
        if key in seen:
            return None
        fps = cache["dives"][dive]["fps"]
        fi1 = frame_index + 1
        pts = None
        for f in cache["dives"][dive]["frames"]:
            if f["fi"] == fi1:
                pts = f["pts_s"]
                break
        if pts is None:
            raise SystemExit(f"queue frame {dive} fi={fi1} not in frozen cache")
        cand = existing.get(key)
        reused = cand if cand and cand["source_artifact"] in REUSE_ELIGIBLE_SOURCES else None
        item = {
            "id": f"L1A_{dive}_f{frame_index:05d}",
            "dive_id": int(dive),
            "family": FAMILY,
            "frame_index": frame_index,
            "pts_s": pts,
            "rel_clip_time_s": round(frame_index / fps, 4),
            "reason": reason,
            "existing_human_annotation": bool(reused),
            "reused_from": reused,
            "status": "REUSED_EXISTING_HUMAN_ANCHOR" if reused else "PENDING_HUMAN",
        }
        if evidence is not None:
            item["close_pair_evidence"] = evidence
        seen.add(key)
        items.append(item)
        return item

    per_dive_plan = {}
    for dive in STANDING_DIVES:
        wc = wcs[dive]
        if abs(wc["fps"] - cache["dives"][dive]["fps"]) > 1e-6:
            raise SystemExit(f"fps mismatch for {dive}")
        wc_s = wc["frame_index"] / wc["fps"]
        window_end = wc_s + WINDOW_TAIL_S
        k_max = int(window_end / GRID_STEP_S)
        base_frames = [round(k * GRID_STEP_S * wc["fps"]) for k in range(k_max + 1)]
        extras = []
        for t_k, fi in zip(
            [k * GRID_STEP_S for k in range(k_max + 1)], base_frames
        ):
            pairs = close_pairs_at(dive, fi, cache["dives"])
            if not pairs:
                continue
            t_extra = t_k + EXTRA_OFFSET_S
            if t_extra > window_end:
                t_extra = t_k - EXTRA_OFFSET_S
            fi_extra = round(t_extra * wc["fps"])
            if fi_extra < 0 or (dive, fi_extra) in seen:
                continue
            if fi_extra not in base_frames:
                extras.append((fi_extra, {"from_base_frame": fi, "pairs": pairs[:1]}))
        per_dive_plan[dive] = {
            "water_contact_frame_index": wc["frame_index"],
            "water_contact_s": round(wc_s, 4),
            "window_end_s": round(window_end, 4),
            "base_grid_points": k_max + 1,
            "close_person_extra_points": len(extras),
        }
        for k in range(k_max + 1):
            add(dive, base_frames[k], "level_a_base_grid_0.5s")
        for fi_extra, ev in extras:
            add(dive, fi_extra, "level_a_close_person_extra_0.25s", ev)

    items.sort(key=lambda it: (STANDING_DIVES.index(str(it["dive_id"])), it["frame_index"]))
    reused = [it for it in items if it["existing_human_annotation"]]
    q = {
        "label": QUEUE_LABEL,
        "packet": LABEL,
        "created": queue_created_stamp(),
        "plan": "SUBJECT_GT_MINIMUM_ANNOTATION_PLAN_V1 (frozen)",
        "rules": {
            "eval_window_s": "[0, water_contact + 0.5]",
            "water_contact_authority": "DEVELOPMENT_DESIGN water_contact frame_index / fps",
            "base_grid": "0.5 s spacing from t=0 while t <= window_end; frame = round(t*fps)",
            "extra_anchor_rule": (
                f"at a base frame, if two distinct frozen-D5 candidates "
                f"(conf>={EXTRA_CONF_FLOOR}, IoU<{EXTRA_IOU_MAX}) have center distance "
                f"< {EXTRA_DIST_MAX} mean-bh normalized, add one anchor at +{EXTRA_OFFSET_S}s "
                "(or -0.25s if past window end)"
            ),
            "reuse_rule": "existing HUMAN_REVIEWED annotation at the exact frame_index is reused, never re-asked",
        },
        "inputs": {
            "d5_cache": str(D5_CACHE.relative_to(REPO)),
            "d5_cache_sha256": sha256_file(D5_CACHE),
            "proxy_sha256": {d: cache["dives"][d]["proxy_sha256"] for d in STANDING_DIVES},
            "water_contact_sources": {
                d: {"file": wcs[d]["source_file"], "sha256": wcs[d]["sha256"]}
                for d in STANDING_DIVES
            },
        },
        "per_dive_plan": per_dive_plan,
        "counts": {
            "requested_total": len(items),
            "reused_existing": len(reused),
            "new_human_required": len(items) - len(reused),
            "per_dive": {
                d: {
                    "requested": sum(1 for it in items if str(it["dive_id"]) == d),
                    "reused": sum(
                        1 for it in items if str(it["dive_id"]) == d and it["existing_human_annotation"]
                    ),
                }
                for d in STANDING_DIVES
            },
        },
        "items": items,
    }
    return q


def queue_created_stamp() -> str:
    """Deterministic stamp derived from inputs, not wall clock (queue must be
    byte-reproducible)."""
    payload = sha256_file(D5_CACHE)
    for dive in STANDING_DIVES:
        p = LOC_ANN / "DEVELOPMENT_DESIGN" / f"{dive}_water_contact.json"
        payload += sha256_file(p)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


# ---------------------------------------------------------------- extraction

def cmd_extract(args):
    import cv2

    q = json.loads(QUEUE_PATH.read_text())
    frames_dir = WORK_DIR / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"label": "SUBJECT_GT_LEVEL_A_FRAMES_V1", "frames": {}}
    man_path = WORK_DIR / "frames_manifest.json"
    if man_path.exists():
        manifest = json.loads(man_path.read_text())
    by_dive: dict[str, list[int]] = {}
    for it in q["items"]:
        by_dive.setdefault(str(it["dive_id"]), []).append(it["frame_index"])
    for dive, idxs in sorted(by_dive.items()):
        proxy = REPO / "media/perception_decomposition_v1/proxies" / f"{dive}.mp4"
        want = sorted(set(idxs))
        have = {
            i for i in want
            if (frames_dir / dive / f"f{i:05d}.jpg").exists()
            and str(i) in manifest["frames"].get(str(dive), {})
        }
        if len(have) == len(want):
            continue
        outdir = frames_dir / dive
        outdir.mkdir(parents=True, exist_ok=True)
        cap = cv2.VideoCapture(str(proxy))
        assert cap.isOpened(), f"cannot open {proxy}"
        need = set(want) - have
        max_need = max(need)
        i = 0
        while i <= max_need:
            ok, frame = cap.read()
            if not ok:
                raise SystemExit(f"proxy {dive} ended before frame {max_need}")
            if i in need:
                fp = outdir / f"f{i:05d}.jpg"
                tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
                tmp.close()
                cv2.imwrite(tmp.name, frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
                shutil.move(tmp.name, fp)
                manifest["frames"].setdefault(str(dive), {})[str(i)] = {
                    "file": str(fp.relative_to(REPO)),
                    "sha256": sha256_file(fp),
                    "proxy_sha256": sha256_file(proxy),
                }
            i += 1
        cap.release()
    man_path.write_text(json.dumps(manifest, indent=1, sort_keys=True))
    n = sum(len(v) for v in manifest["frames"].values())
    print(f"extracted/verified {n} frames -> {frames_dir}")


# ---------------------------------------------------------------- server

_UI = """<!doctype html>
<html><head><meta charset="utf-8"><title>Level-A Subject GT</title>
<style>
 body{font-family:-apple-system,Helvetica,sans-serif;background:#111;color:#eee;margin:0;display:flex;flex-direction:column;align-items:center}
 header{width:100%;background:#222;padding:8px 16px;box-sizing:border-box;display:flex;justify-content:space-between;align-items:center}
 #stage{position:relative;margin:12px 0;border:1px solid #444;cursor:crosshair}
 #stage canvas{display:block}
 #btns{display:flex;gap:10px;margin:8px}
 button{padding:10px 18px;font-size:15px;border:0;border-radius:6px;cursor:pointer}
 #save{background:#2e7d32;color:#fff} #nv{background:#b71c1c;color:#fff}
 #back,#next{background:#444;color:#eee}
 #msg{min-height:20px;color:#ffb74d}
 #help{color:#999;font-size:12px;max-width:560px;text-align:center;margin-bottom:20px}
</style></head><body>
<header><div id="diveinfo">—</div><div id="progress">—</div></header>
<div id="stage"><canvas id="cv" width="404" height="720"></canvas></div>
<div id="btns">
 <button id="back">&larr; BACK</button>
 <button id="save">SAVE SUBJECT BOX</button>
 <button id="nv">NOT_VISIBLE</button>
 <button id="next">NEXT &rarr;</button>
</div>
<div id="msg"></div>
<div id="help">Drag on the image to draw the box around the INTENDED SUBJECT
(the diver performing the dive). Re-draw to adjust. SAVE commits the box,
NOT_VISIBLE records that the subject is not identifiable/visible in this frame.
Keyboard: &larr;/&rarr; navigate, s save, n not-visible. Progress saves immediately.</div>
<script>
const SCALE=2; let items=[],pos=0,rect=null,drag=null,img=null;
const cv=document.getElementById('cv'),ctx=cv.getContext('2d');
async function api(p,o){const r=await fetch(p,o);return r.json();}
function draw(){
 ctx.fillStyle='#000';ctx.fillRect(0,0,cv.width,cv.height);
 if(img)ctx.drawImage(img,0,0,cv.width,cv.height);
 if(rect){ctx.strokeStyle='#00e676';ctx.lineWidth=2;
  ctx.strokeRect(rect[0]*SCALE,rect[1]*SCALE,(rect[2]-rect[0])*SCALE,(rect[3]-rect[1])*SCALE);}
}
async function load(){
 const st=await api('/api/state');
 items=st.items;
 // jump to first unresolved unless all done
 if(!items.some(i=>!i.resolved)) pos=items.length-1; else if(items[pos]&&items[pos].resolved) pos=items.findIndex(i=>!i.resolved);
 show();
}
async function show(){
 if(pos<0)pos=0; if(pos>=items.length)pos=items.length-1;
 const it=items[pos];
 document.getElementById('diveinfo').textContent=
  `dive ${it.dive_id}  |  frame ${it.frame_index}  |  t=${it.pts_s.toFixed(3)}s  |  item ${pos+1}/${items.length}`;
 const done=items.filter(i=>i.resolved).length;
 document.getElementById('progress').textContent=`annotated ${done}/${items.length}`;
 rect=it.bbox?it.bbox.slice():null;
 img=new Image();img.onload=draw;img.src=`/frames/${it.dive_id}/f${String(it.frame_index).padStart(5,'0')}.jpg`;
 document.getElementById('msg').textContent='';
}
function evpos(e){const r=cv.getBoundingClientRect();
 return [Math.round((e.clientX-r.left)/SCALE),Math.round((e.clientY-r.top)/SCALE)];}
cv.addEventListener('mousedown',e=>{drag=evpos(e);rect=[drag[0],drag[1],drag[0],drag[1]];});
cv.addEventListener('mousemove',e=>{if(!drag)return;const p=evpos(e);
 rect=[Math.min(drag[0],p[0]),Math.min(drag[1],p[1]),Math.max(drag[0],p[0]),Math.max(drag[1],p[1])];draw();});
window.addEventListener('mouseup',()=>{drag=null;});
async function commit(kind){
 const it=items[pos];
 const body={id:it.id,dive_id:it.dive_id,frame_index:it.frame_index,annotator:'maxime'};
 if(kind=='nv'){body.visibility='not_visible';body.bbox=null;}
 else{if(!rect||rect[2]-rect[0]<2||rect[3]-rect[1]<2){msg('Draw a box first.');return;}
  body.visibility='visible';body.bbox=rect;}
 const r=await api('/api/annotate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 if(!r.ok){msg(r.error||'save failed');return;}
 it.resolved=true;it.bbox=body.bbox;it.visibility=body.visibility;
 msg('saved'); if(pos<items.length-1){pos++;show();}
}
function msg(t){document.getElementById('msg').textContent=t;}
document.getElementById('save').onclick=()=>commit('box');
document.getElementById('nv').onclick=()=>commit('nv');
document.getElementById('next').onclick=()=>{if(pos<items.length-1){pos++;show();}};
document.getElementById('back').onclick=()=>{if(pos>0){pos--;show();}};
window.addEventListener('keydown',e=>{
 if(e.key=='ArrowRight'&&pos<items.length-1){pos++;show();}
 if(e.key=='ArrowLeft'&&pos>0){pos--;show();}
 if(e.key=='s')commit('box'); if(e.key=='n')commit('nv');});
load();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    queue: dict = None
    manifest: dict = None

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, _UI.encode(), "text/html")
        elif self.path == "/api/state":
            draft = json.loads(DRAFT_PATH.read_text()) if DRAFT_PATH.exists() else {"items": {}}
            items = []
            for it in self.queue["items"]:
                ann = draft["items"].get(it["id"])
                items.append({
                    "id": it["id"], "dive_id": it["dive_id"],
                    "frame_index": it["frame_index"], "pts_s": it["pts_s"],
                    "resolved": bool(ann),
                    "bbox": ann.get("bbox") if ann else None,
                    "visibility": ann.get("visibility") if ann else None,
                })
            self._send(200, json.dumps({"items": items}).encode())
        elif self.path.startswith("/frames/"):
            rel = self.path.lstrip("/")
            fp = (WORK_DIR / rel.replace("frames/", "frames/", 1)).resolve()
            base = (WORK_DIR / "frames").resolve()
            if not str(fp).startswith(str(base)) or not fp.exists():
                self._send(404, b"not found", "text/plain")
                return
            self._send(200, fp.read_bytes(), "image/jpeg")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        if self.path != "/api/annotate":
            self._send(404, b"not found", "text/plain")
            return
        n = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(n))
        qitem = {it["id"]: it for it in self.queue["items"]}.get(req.get("id"))
        if not qitem:
            self._send(400, json.dumps({"ok": False, "error": "unknown item"}).encode())
            return
        vis = req.get("visibility")
        bbox = req.get("bbox")
        if vis not in ("visible", "not_visible"):
            self._send(400, json.dumps({"ok": False, "error": "bad visibility"}).encode())
            return
        if vis == "visible":
            ok, err = bbox_valid(bbox, 202, 360)
            if not ok:
                self._send(400, json.dumps({"ok": False, "error": err}).encode())
                return
        else:
            bbox = None
        draft = json.loads(DRAFT_PATH.read_text()) if DRAFT_PATH.exists() else {"items": {}}
        dive = str(qitem["dive_id"])
        fmeta = self.manifest["frames"].get(dive, {}).get(str(qitem["frame_index"]))
        draft["items"][req["id"]] = {
            "dive_id": qitem["dive_id"],
            "family": FAMILY,
            "frame_index": qitem["frame_index"],
            "pts_s": qitem["pts_s"],
            "rel_clip_time_s": qitem["rel_clip_time_s"],
            "reason": qitem["reason"],
            "bbox": bbox,
            "visibility": vis,
            "authority": "HUMAN_REVIEWED",
            "annotator": req.get("annotator", "maxime"),
            "source_identity": "intended Dive Analyzer subject (diver performing the dive)",
            "media_sha256": fmeta["proxy_sha256"] if fmeta else None,
            "image_sha256": fmeta["sha256"] if fmeta else None,
            "representation": "proxy_360p_native_decoded_frame",
            "width": 202,
            "height": 360,
            "created_at": draft_now(),
        }
        tmp = DRAFT_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(draft, indent=1, sort_keys=True))
        tmp.replace(DRAFT_PATH)
        self._send(200, json.dumps({"ok": True}).encode())


def bbox_valid(b, w, h):
    if not isinstance(b, list) or len(b) != 4:
        return False, "bbox must be [x1,y1,x2,y2]"
    x1, y1, x2, y2 = b
    if not all(isinstance(v, (int, float)) for v in b):
        return False, "bbox values must be numeric"
    if x2 <= x1 or y2 <= y1:
        return False, "non-positive width/height"
    if x1 < 0 or y1 < 0 or x2 > w or y2 > h:
        return False, "bbox outside frame bounds"
    return True, ""


def draft_now():
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def cmd_serve(args):
    q = json.loads(QUEUE_PATH.read_text())
    man = json.loads((WORK_DIR / "frames_manifest.json").read_text())
    Handler.queue = q
    Handler.manifest = man
    if not DRAFT_PATH.exists():
        DRAFT_PATH.parent.mkdir(parents=True, exist_ok=True)
        DRAFT_PATH.write_text(json.dumps({"items": {}}, indent=1))
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"annotation UI: http://127.0.0.1:{args.port}  (Ctrl-C to stop)")
    srv.serve_forever()


# ---------------------------------------------------------------- validate

def cmd_validate(args):
    q = json.loads(QUEUE_PATH.read_text())
    draft = json.loads(DRAFT_PATH.read_text())
    errors = []
    resolved = 0
    for it in q["items"]:
        ann = draft["items"].get(it["id"])
        if not ann:
            errors.append(f"{it['id']}: unresolved")
            continue
        resolved += 1
        if ann.get("authority") != "HUMAN_REVIEWED":
            errors.append(f"{it['id']}: authority not HUMAN_REVIEWED")
        if ann.get("annotator") != "maxime":
            errors.append(f"{it['id']}: annotator not maxime")
        if ann.get("dive_id") != it["dive_id"] or ann.get("frame_index") != it["frame_index"]:
            errors.append(f"{it['id']}: source/frame identity mismatch")
        if ann.get("visibility") == "visible":
            ok, err = bbox_valid(ann.get("bbox"), 202, 360)
            if not ok:
                errors.append(f"{it['id']}: {err}")
        elif ann.get("visibility") != "not_visible":
            errors.append(f"{it['id']}: bad visibility {ann.get('visibility')}")
        if not ann.get("image_sha256") or not ann.get("media_sha256"):
            errors.append(f"{it['id']}: missing frame provenance")
    # duplicate/conflicting annotations
    by_key = {}
    for iid, ann in draft["items"].items():
        key = (str(ann["dive_id"]), int(ann["frame_index"]))
        if key in by_key:
            a, b = draft["items"][by_key[key]], ann
            if a.get("bbox") != b.get("bbox") or a.get("visibility") != b.get("visibility"):
                errors.append(f"conflicting duplicate annotations at {key}")
        else:
            by_key[key] = iid
    # reused anchors preserved
    for it in q["items"]:
        if it["existing_human_annotation"] and it["reused_from"]:
            r = it["reused_from"]
            ann = draft["items"].get(it["id"])
            if ann is not None:
                if ann.get("visibility") != r["visibility"]:
                    errors.append(f"{it['id']}: reused anchor visibility altered")
    nv = sum(1 for it in q["items"]
             if (draft["items"].get(it["id"]) or {}).get("visibility") == "not_visible")
    report = {
        "label": "SUBJECT_GT_LEVEL_A_VALIDATION_V1",
        "queue_items": len(q["items"]),
        "resolved": resolved,
        "unresolved": len(q["items"]) - resolved,
        "not_visible_count": nv,
        "visible_count": sum(
            1 for it in q["items"]
            if (draft["items"].get(it["id"]) or {}).get("visibility") == "visible"),
        "reused_existing": q["counts"]["reused_existing"],
        "errors": errors,
        "verdict": "PASS" if not errors and resolved == len(q["items"]) else "FAIL",
    }
    out = WORK_DIR / "validation_v1.json"
    out.write_text(json.dumps(report, indent=1, sort_keys=True))
    print(json.dumps(report, indent=1))
    return 0 if report["verdict"] == "PASS" else 1


# ---------------------------------------------------------------- freeze

def cmd_freeze(args):
    q = json.loads(QUEUE_PATH.read_text())
    draft = json.loads(DRAFT_PATH.read_text())
    val = json.loads((WORK_DIR / "validation_v1.json").read_text())
    if val["verdict"] != "PASS":
        raise SystemExit("validation FAIL — refusing to freeze")
    outdir = LOC_ANN / "SUBJECT_GT_LEVEL_A_STANDING_V1"
    outdir.mkdir(parents=True, exist_ok=True)
    file_shas = {}
    for it in q["items"]:
        ann = dict(draft["items"][it["id"]])
        ann["id"] = it["id"]
        ann["queue_reason"] = it["reason"]
        if it["existing_human_annotation"]:
            ann["provenance"] = {
                "origin": "REUSED_EXISTING_HUMAN_ANCHOR",
                "source_artifact": it["reused_from"]["source_artifact"],
                "source_file": it["reused_from"]["source_file"],
                "original_annotated_at": it["reused_from"]["annotated_at"],
            }
        else:
            ann["provenance"] = {"origin": "NEW_LEVEL_A_ANNOTATION", "queue": QUEUE_LABEL}
        fp = outdir / f"{it['id']}.json"
        fp.write_text(json.dumps(ann, indent=1, sort_keys=True))
        file_shas[fp.name] = sha256_file(fp)
    per_dive = Counter(str(draft["items"][it["id"]]["dive_id"]) for it in q["items"])
    nv = val["not_visible_count"]
    manifest = {
        "authority": "SUBJECT_GT_LEVEL_A_STANDING_V1",
        "packet": LABEL,
        "created_at": draft_now(),
        "level": "LEVEL_A_REFERENCE_CORRECTNESS",
        "family": FAMILY,
        "dives": STANDING_DIVES,
        "annotator": "maxime",
        "schema": {
            "bbox": "[x1,y1,x2,y2] px on 202x360 proxy_360p_native_decoded_frame",
            "visibility": "visible | not_visible",
            "authority": "HUMAN_REVIEWED",
        },
        "annotation_count": len(q["items"]),
        "per_dive_counts": dict(sorted(per_dive.items())),
        "not_visible_count": nv,
        "reused_existing_anchors": q["counts"]["reused_existing"],
        "new_human_annotations": q["counts"]["new_human_required"],
        "source_identities": {
            d: "intended Dive Analyzer subject (diver performing the dive)"
            for d in STANDING_DIVES
        },
        "proxy_sha256": q["inputs"]["proxy_sha256"],
        "queue_label": QUEUE_LABEL,
        "queue_sha256": sha256_file(QUEUE_PATH),
        "plan": "SUBJECT_GT_MINIMUM_ANNOTATION_PLAN_V1",
        "level_b_note": "NOT dense trajectory GT; no interpolation is authoritative (Level-B unauthorized)",
        "files_sha256": dict(sorted(file_shas.items())),
    }
    art_sha = hashlib.sha256(
        json.dumps(manifest["files_sha256"], sort_keys=True).encode()
    ).hexdigest()
    manifest["artifact_sha256"] = art_sha
    (outdir / "MANIFEST.json").write_text(json.dumps(manifest, indent=1, sort_keys=True))
    print(f"frozen {len(q['items'])} Level-A anchors -> {outdir}")
    print(f"artifact_sha256 {art_sha}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("queue")
    sub.add_parser("extract")
    p = sub.add_parser("serve")
    p.add_argument("--port", type=int, default=8765)
    sub.add_parser("validate")
    sub.add_parser("freeze")
    args = ap.parse_args()
    if args.cmd == "queue":
        q = build_queue()
        QUEUE_PATH.write_text(json.dumps(q, indent=1, sort_keys=True))
        print(json.dumps(q["counts"], indent=1))
        print(json.dumps(q["per_dive_plan"], indent=1))
    elif args.cmd == "extract":
        cmd_extract(args)
    elif args.cmd == "serve":
        cmd_serve(args)
    elif args.cmd == "validate":
        raise SystemExit(cmd_validate(args))
    elif args.cmd == "freeze":
        cmd_freeze(args)


if __name__ == "__main__":
    main()
