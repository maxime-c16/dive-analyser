#!/usr/bin/env python3
"""DIVE_ANALYZER_INDEPENDENT_SUBJECT_GT_EXPANSION_V1 — Phases 8-11 + 12.

Level-B subject-identity GT annotation for the 6 NEW independent dives.

- deterministic, byte-reproducible queue (reused frozen Level-A constants:
  GRID_STEP_S 0.5, EXTRA_CONF_FLOOR 0.05, EXTRA_DIST_MAX 0.10,
  EXTRA_IOU_MAX 0.50, EXTRA_OFFSET_S 0.25);
- eval interval: FULL CLIP (no event-GT authority exists for the new dives;
  window_end = last frozen-cache frame);
- blind local web UI: no A0/A1 ranking, no V3 support, no OSNet score, no
  selector result — manual bbox only;
- Phase 10 human-assisted propagation: a DRAFT box may be shown for an
  unresolved item when deterministic continuation (best-IoU supported
  frozen-D5 candidate vs the nearest earlier human box of the same dive,
  IoU>=0.40, within 1.0 s) is available. The draft is NEVER stored without
  an explicit human action: SAVE accepts/re-draws it (method recorded),
  NOT_VISIBLE rejects it. Every stored item is HUMAN_REVIEWED.
- validate + freeze produce the SUBJECT_GT_LEVEL_B_INDEPENDENT_V1 authority
  under docs/science/localization_annotations_v1/.

Usage:
  python3 experiments/subject_resolution/phase_subject_gt_level_b_annotation_v1.py queue
  ... same extract / serve / validate / freeze commands as Level-A.
"""

import argparse
import datetime
import hashlib
import json
import shutil
import tempfile
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = Path(__file__).parents[2]

LABEL = "DIVE_ANALYZER_INDEPENDENT_SUBJECT_GT_EXPANSION_V1"
QUEUE_LABEL = "SUBJECT_GT_LEVEL_B_QUEUE_INDEPENDENT_V1"

D5_CACHE = BASE / "runs/subject_resolution/R5_FULLCLIP_CANDIDATES_INDEP_V1.json"
LOC_ANN = BASE / "docs/science/localization_annotations_v1"
WORK_DIR = BASE / "runs/subject_gt_level_b_v1"
QUEUE_PATH = BASE / f"docs/science/{QUEUE_LABEL}.json"
DRAFT_PATH = WORK_DIR / "annotations_draft.json"

# Selected independent dives (Phase 2/3 selection; metadata + generic scene
# evidence only — see docs/science/DIVE_ANALYZER_INDEPENDENT_SUBJECT_GT_EXPANSION_V1.md)
SELECTED_DIVES = ["1304", "2223", "2204", "2526", "2583", "2839"]
FAMILY = {
    "1304": "STANDING_APPROACH",
    "2223": "STANDING",
    "2204": "STANDING_APPROACH",
    "2526": "HURDLE_ORDINARY",
    "2583": "STANDING",
    "2839": "HURDLE_ORDINARY",
}
DIVER = {
    "1304": "FANNY",
    "2223": "LOUIS",
    "2204": "FANNY",
    "2526": "MAT",
    "2583": "MAXIME",
    "2839": "MAXIME",
}
DIVES_BY_DATE = SELECTED_DIVES

GRID_STEP_S = 0.5
EXTRA_CONF_FLOOR = 0.05     # frozen Level-A extra-anchor floor (reused)
EXTRA_DIST_MAX = 0.10       # frozen "two people within ~0.1 mean-bh" (reused)
EXTRA_IOU_MAX = 0.50        # frozen distinct-detection rule (reused)
EXTRA_OFFSET_S = 0.25       # frozen midpoint extra rule (reused)

DRAFT_SUPPORTED_CONF = 0.05  # deterministic-tracking draft: person-plausible floor
DRAFT_MIN_IOU = 0.40         # deterministic continuation gate vs previous human box
DRAFT_MAX_DT_S = 1.0         # draft only from the nearest earlier anchor within 1 s


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def frame_pts(cache_dives: dict, dive: str, frame_index: int):
    fi1 = frame_index + 1
    for f in cache_dives[dive]["frames"]:
        if f["fi"] == fi1:
            return f
    return None


def box_xyxy(c):
    return (c["cx"] - c["bw"] / 2, c["cy"] - c["bh"] / 2,
            c["cx"] + c["bw"] / 2, c["cy"] + c["bh"] / 2)


def iou_xyxy(a, b):
    iw = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    ih = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = iw * ih
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def close_pairs_at(dive: str, frame_index: int, cache_dives: dict) -> list:
    """Deterministic close-person evidence from the frozen D5 candidate cache
    (same frozen rule as SUBJECT_GT_LEVEL_A_QUEUE_STANDING_V1)."""
    f = frame_pts(cache_dives, dive, frame_index)
    if not f:
        return []
    cands = [c for c in f["c"] if c["conf"] >= EXTRA_CONF_FLOOR]
    pairs = []
    for i in range(len(cands)):
        for j in range(i + 1, len(cands)):
            a, b = cands[i], cands[j]
            ab, bb = box_xyxy(a), box_xyxy(b)
            ia = iou_xyxy(ab, bb)
            dist_norm = (((a["cx"] - b["cx"]) ** 2 + (a["cy"] - b["cy"]) ** 2)
                         ** 0.5) / ((a["bh"] + b["bh"]) / 2)
            if ia < EXTRA_IOU_MAX and dist_norm < EXTRA_DIST_MAX:
                pairs.append({
                    "dist_norm": round(dist_norm, 4),
                    "iou": round(ia, 4),
                    "confs": [round(a["conf"], 4), round(b["conf"], 4)],
                })
    pairs.sort(key=lambda p: (p["dist_norm"], p["iou"]))
    return pairs


def frame_pts(cache_dives: dict, dive: str, frame_index: int):
    return frame_pts_or_none(cache_dives, dive, frame_index)


def frame_pts_or_none(cache_dives: dict, dive: str, frame_index: int):
    fi1 = frame_index + 1
    for f in cache_dives[dive]["frames"]:
        if f["fi"] == fi1:
            return f
    return None


def build_queue() -> dict:
    cache = json.loads(D5_CACHE.read_text())
    cache_dives = cache["dives"]
    items: list[dict] = []
    seen: set[tuple[str, int]] = set()

    def add(dive: str, frame_index: int, reason: str, evidence=None):
        key = (dive, frame_index)
        if key in seen:
            return None
        f = frame_pts_or_none(cache_dives, dive, frame_index)
        if f is None:
            return None
        fps = cache_dives[dive]["fps"]
        item = {
            "id": f"L1B_{dive}_f{frame_index:05d}",
            "dive_id": int(dive),
            "diver": DIVER[dive],
            "family": FAMILY[dive],
            "frame_index": frame_index,
            "pts_s": f["pts_s"],
            "rel_clip_time_s": round(frame_index / fps, 4),
            "reason": reason,
            "status": "PENDING_HUMAN",
        }
        if evidence is not None:
            item["close_pair_evidence"] = evidence
        seen.add(key)
        items.append(item)
        return item

    per_dive_plan = {}
    for dive in DIVES_BY_DATE:
        fps = cache_dives[dive]["fps"]
        end_s = cache_dives[dive]["interval_s"][1]
        k_max = int(end_s / GRID_STEP_S)
        base_frames = [round(k * GRID_STEP_S * fps) for k in range(k_max + 1)]
        extras = []
        for t_k, fi in zip([k * GRID_STEP_S for k in range(k_max + 1)],
                           base_frames):
            pairs = close_pairs_at(dive, fi, cache_dives)
            if not pairs:
                continue
            t_extra = t_k + EXTRA_OFFSET_S
            if t_extra > end_s:
                t_extra = t_k - EXTRA_OFFSET_S
            fi_extra = round(t_extra * fps)
            if fi_extra < 0 or (dive, fi_extra) in seen:
                continue
            if fi_extra not in base_frames and \
                    frame_pts_or_none(cache_dives, dive, fi_extra):
                extras.append((fi_extra, {"from_base_frame": fi,
                                          "pairs": pairs[:1]}))
        per_dive_plan[dive] = {
            "clip_end_s": round(end_s, 4),
            "base_grid_points": k_max + 1,
            "close_person_extra_points": len(extras),
        }
        for k in range(k_max + 1):
            add(dive, base_frames[k], "level_b_base_grid_0.5s_full_clip")
        for fi_extra, ev in extras:
            add(dive, fi_extra, "level_b_close_person_extra_0.25s", ev)

    items.sort(key=lambda it: (DIVES_BY_DATE.index(str(it["dive_id"])),
                               it["frame_index"]))
    q = {
        "label": QUEUE_LABEL,
        "packet": LABEL,
        "created": queue_created_stamp(),
        "plan": "SUBJECT_GT_LEVEL_B_ANNOTATION_PLAN_V1 (this packet)",
        "rules": {
            "eval_interval_s": "[0, clip_end] (full clip; no event-GT "
                               "authority exists for the new dives)",
            "base_grid": "0.5 s spacing from t=0 while t <= clip_end; "
                         "frame = round(t*fps)",
            "extra_anchor_rule": (
                f"at a base frame, if two distinct frozen-D5 candidates "
                f"(conf>={EXTRA_CONF_FLOOR}, IoU<{EXTRA_IOU_MAX}) have center "
                f"distance < {EXTRA_DIST_MAX} mean-bh normalized, add one "
                f"anchor at +{EXTRA_OFFSET_S}s (or -0.25s if past clip end)"
            ),
            "draft_rule": (
                "Phase 10 human-assisted propagation: for an unresolved item, "
                f"if the nearest earlier human box of the same dive is within "
                f"{DRAFT_MAX_DT_S}s, the supported (conf>={DRAFT_SUPPORTED_CONF}) "
                f"frozen-D5 candidate with the highest IoU (gate "
                f">={DRAFT_MIN_IOU}) is offered as a DRAFT box; a draft is "
                "never authority without explicit human ACCEPT/CORRECT"
            ),
            "blindness": "no A0/A1 ranking, no V3 support score, no OSNet "
                         "identity score, no selector result is shown or stored",
        },
        "inputs": {
            "d5_cache": str(D5_CACHE.relative_to(BASE)),
            "d5_cache_sha256": sha256_file(D5_CACHE),
            "proxy_sha256": {d: cache_dives[d]["proxy_sha256"]
                             for d in SELECTED_DIVES},
        },
        "per_dive_plan": per_dive_plan,
        "counts": {
            "requested_total": len(items),
            "new_human_required": len(items),
            "per_dive": {
                d: sum(1 for it in items if str(it["dive_id"]) == d)
                for d in SELECTED_DIVES
            },
        },
        "items": items,
    }
    return q


def queue_created_stamp() -> str:
    return sha256_file(D5_CACHE)[:16]


# ---------------------------------------------------------------- extraction

def cmd_extract(args):
    import cv2

    q = json.loads(QUEUE_PATH.read_text())
    frames_dir = WORK_DIR / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"label": "SUBJECT_GT_LEVEL_B_FRAMES_V1", "frames": {}}
    man_path = WORK_DIR / "frames_manifest.json"
    if man_path.exists():
        manifest = json.loads(man_path.read_text())
    by_dive: dict[str, list[int]] = {}
    for it in q["items"]:
        by_dive.setdefault(str(it["dive_id"]), []).append(it["frame_index"])
    for dive, idxs in sorted(by_dive.items()):
        proxy = BASE / "media/perception_decomposition_v1/proxies" / f"{dive}.mp4"
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
                    "file": str(fp.relative_to(BASE)),
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
<html><head><meta charset="utf-8"><title>Level-B Subject Identity GT</title>
<style>
 body{font-family:-apple-system,Helvetica,sans-serif;background:#111;color:#eee;margin:0;display:flex;flex-direction:column;align-items:center}
 header{width:100%;background:#222;padding:8px 16px;box-sizing:border-box;display:flex;justify-content:space-between;align-items:center}
 #stage{position:relative;margin:12px 0;border:1px solid #444;cursor:crosshair}
 #stage canvas{display:block}
 #btns{display:flex;gap:10px;margin:8px;flex-wrap:wrap;justify-content:center}
 button{padding:10px 18px;font-size:15px;border:0;border-radius:6px;cursor:pointer}
 #save{background:#2e7d32;color:#fff} #nv{background:#b71c1c;color:#fff}
 #back,#next{background:#444;color:#eee}
 #msg{min-height:20px;color:#ffb74d}
 #help{color:#999;font-size:12px;max-width:600px;text-align:center;margin-bottom:20px}
</style></head><body>
<header><div id="diveinfo">&mdash;</div><div id="progress">&mdash;</div></header>
<div id="stage"><canvas id="cv" width="404" height="720"></canvas></div>
<div id="btns">
 <button id="back">&larr; BACK</button>
 <button id="save">SAVE SUBJECT BOX</button>
 <button id="accept">ACCEPT DRAFT</button>
 <button id="nv">NOT_VISIBLE</button>
 <button id="next">NEXT &rarr;</button>
</div>
<div id="msg"></div>
<div id="help">Draw the box around the INTENDED SUBJECT (the diver performing
the dive) in this frame. If a blue DRAFT box is shown it is only a suggestion
from deterministic continuation &mdash; press ACCEPT DRAFT to keep it as-is,
or redraw over it and SAVE to correct it. Every saved box is human-reviewed.
NOT_VISIBLE records the subject is not identifiable/visible in this frame.
Keyboard: &larr;/&rarr; navigate, s save, a accept draft, n not-visible.</div>
<script>
const SCALE=2; let items=[],pos=0,rect=null,drag=null,img=null,draft=null;
const cv=document.getElementById('cv'),ctx=cv.getContext('2d');
async function api(p,o){const r=await fetch(p,o);return r.json();}
function draw(){
 ctx.fillStyle='#000';ctx.fillRect(0,0,cv.width,cv.height);
 if(img)ctx.drawImage(img,0,0,cv.width,cv.height);
 if(draft){ctx.strokeStyle='#40c4ff';ctx.lineWidth=2;
  ctx.strokeRect(draft[0]*SCALE,draft[1]*SCALE,(draft[2]-draft[0])*SCALE,(draft[3]-draft[1])*SCALE);}
 if(rect){ctx.strokeStyle='#00e676';ctx.lineWidth=2;
  ctx.strokeRect(rect[0]*SCALE,rect[1]*SCALE,(rect[2]-rect[0])*SCALE,(rect[3]-rect[1])*SCALE);}
}
async function load(){
 const st=await api('/api/state');
 items=st.items;
 if(!items.some(i=>!i.resolved)) pos=items.length-1; else if(items[pos]&&items[pos].resolved) pos=items.findIndex(i=>!i.resolved);
 show();
}
async function show(){
 if(pos<0)pos=0; if(pos>=items.length)pos=items.length-1;
 const it=items[pos];
 document.getElementById('diveinfo').textContent=
  `dive ${it.dive_id} (${it.diver})  |  frame ${it.frame_index}  |  t=${it.pts_s.toFixed(3)}s  |  item ${pos+1}/${items.length}`;
 const done=items.filter(i=>i.resolved).length;
 document.getElementById('progress').textContent=`annotated ${done}/${items.length}`;
 rect=it.bbox?it.bbox.slice():null;
 draft=it.draft?it.draft.bbox.slice():null;
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
 if(kind=='nv'){body.visibility='not_visible';body.bbox=null;body.method='human_not_visible';}
 else{
  if(!rect||rect[2]-rect[0]<2||rect[3]-rect[1]<2){msg('Draw a box first.');return;}
  body.visibility='visible';body.bbox=rect;
  body.method=(draft&&JSON.stringify(draft)===JSON.stringify(rect))?'human_accepted_propagation_draft':'human_drawn_or_corrected';
 }
 const r=await api('/api/annotate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 if(!r.ok){msg(r.error||'save failed');return;}
 it.resolved=true;it.bbox=body.bbox;it.visibility=body.visibility;it.method=body.method;
 msg('saved'); if(pos<items.length-1){pos++;show();}
}
function msg(t){document.getElementById('msg').textContent=t;}
document.getElementById('save').onclick=()=>commit('box');
document.getElementById('nv').onclick=()=>commit('nv');
document.getElementById('accept').onclick=()=>{
 if(draft){rect=draft.slice();commit('box');} else msg('No draft on this item.');
};
document.getElementById('next').onclick=()=>{if(pos<items.length-1){pos++;show();}};
document.getElementById('back').onclick=()=>{if(pos>0){pos--;show();}};
window.addEventListener('keydown',e=>{
 if(e.key=='ArrowRight'&&pos<items.length-1){pos++;show();}
 if(e.key=='ArrowLeft'&&pos>0){pos--;show();}
 if(e.key=='s')commit('box'); if(e.key=='a')document.getElementById('accept').onclick();
 if(e.key=='n')commit('nv');});
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

    def _draft_for(self, it: int, draft: dict):
        """Deterministic Phase-10 draft: best-IoU supported frozen-D5
        candidate vs the nearest earlier human box of the same dive."""
        dive = str(it["dive_id"])
        prev = None
        for other in self.queue["items"]:
            if str(other["dive_id"]) != dive or other["frame_index"] >= it["frame_index"]:
                continue
            ann = draft["items"].get(other["id"])
            if ann and ann.get("visibility") == "visible" and ann.get("bbox"):
                prev = (other, ann["bbox"])
        if not prev:
            return None
        pitem, pbox = prev
        dt = it["pts_s"] - pitem["pts_s"]
        if dt <= 0 or dt > DRAFT_MAX_DT_S:
            return None
        f = frame_pts_or_none(self.cache_dives, dive, it["frame_index"])
        if not f:
            return None
        pb = (pbox[0] / 202, pbox[1] / 360, (pbox[2] - pbox[0]) / 202,
              (pbox[3] - pbox[1]) / 360)
        best = None
        for c in f["c"]:
            if c["conf"] < DRAFT_SUPPORTED_CONF:
                continue
            cb = box_xyxy(c)
            v = iou_xyxy(pb, cb)
            if v >= DRAFT_MIN_IOU and (best is None or v > best[0]):
                best = (v, c)
        if not best:
            return None
        v, c = best
        return {"bbox": [round(c["cx"] * 202 - c["bw"] * 202 / 2),
                         round(c["cy"] * 360 - c["bh"] * 360 / 2),
                         round(c["cx"] * 202 + c["bw"] * 202 / 2),
                         round(c["cy"] * 360 + c["bh"] * 360 / 2)],
                "det_iou": round(v, 4), "det_conf": round(c["conf"], 4),
                "from_frame": pitem["frame_index"]}

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, _UI.encode(), "text/html")
        elif self.path == "/api/state":
            draft = json.loads(DRAFT_PATH.read_text()) if DRAFT_PATH.exists() else {"items": {}}
            items = []
            for it in self.queue["items"]:
                ann = draft["items"].get(it["id"])
                d = None if ann else self._draft_for(it, draft)
                items.append({
                    "id": it["id"], "dive_id": it["dive_id"],
                    "diver": it.get("diver"),
                    "frame_index": it["frame_index"], "pts_s": it["pts_s"],
                    "resolved": bool(ann),
                    "bbox": ann.get("bbox") if ann else None,
                    "visibility": ann.get("visibility") if ann else None,
                    "method": ann.get("method") if ann else None,
                    "draft": d,
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
        method = req.get("method", "human_drawn_or_corrected")
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
            method = "human_not_visible"
        if method not in ("human_drawn_or_corrected",
                          "human_accepted_propagation_draft",
                          "human_not_visible"):
            self._send(400, json.dumps({"ok": False, "error": "bad method"}).encode())
            return
        draft = json.loads(DRAFT_PATH.read_text()) if DRAFT_PATH.exists() else {"items": {}}
        dive = str(qitem["dive_id"])
        fmeta = self.manifest["frames"].get(dive, {}).get(str(qitem["frame_index"]))
        draft["items"][req["id"]] = {
            "dive_id": qitem["dive_id"],
            "diver": qitem.get("diver"),
            "family": qitem["family"],
            "frame_index": qitem["frame_index"],
            "pts_s": qitem["pts_s"],
            "rel_clip_time_s": qitem["rel_clip_time_s"],
            "reason": qitem["reason"],
            "bbox": bbox,
            "visibility": vis,
            "method": method,
            "authority": "HUMAN_REVIEWED",
            "annotator": req.get("annotator", "maxime"),
            "source_identity": "intended Dive Analyzer subject "
                               "(diver performing the dive)",
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
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def cmd_serve(args):
    q = json.loads(QUEUE_PATH.read_text())
    man = json.loads((WORK_DIR / "frames_manifest.json").read_text())
    Handler.queue = q
    Handler.manifest = man
    Handler.cache_dives = json.loads(D5_CACHE.read_text())["dives"]
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
    methods = Counter()
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
        if ann.get("method") not in ("human_drawn_or_corrected",
                                     "human_accepted_propagation_draft",
                                     "human_not_visible"):
            errors.append(f"{it['id']}: bad annotation method")
        methods[ann.get("method")] += 1
        if ann.get("visibility") == "visible":
            ok, err = bbox_valid(ann.get("bbox"), 202, 360)
            if not ok:
                errors.append(f"{it['id']}: {err}")
        elif ann.get("visibility") != "not_visible":
            errors.append(f"{it['id']}: bad visibility {ann.get('visibility')}")
        if not ann.get("image_sha256") or not ann.get("media_sha256"):
            errors.append(f"{it['id']}: missing frame provenance")
        if not ann.get("source_identity"):
            errors.append(f"{it['id']}: missing source identity")
    by_key = {}
    for iid, ann in draft["items"].items():
        key = (str(ann["dive_id"]), int(ann["frame_index"]))
        if key in by_key:
            a, b = draft["items"][by_key[key]], ann
            if a.get("bbox") != b.get("bbox") or a.get("visibility") != b.get("visibility"):
                errors.append(f"conflicting duplicate annotations at {key}")
        else:
            by_key[key] = iid
    nv = sum(1 for it in q["items"]
             if (draft["items"].get(it["id"]) or {}).get("visibility") == "not_visible")
    report = {
        "label": "SUBJECT_GT_LEVEL_B_VALIDATION_V1",
        "queue_items": len(q["items"]),
        "resolved": resolved,
        "unresolved": len(q["items"]) - resolved,
        "not_visible_count": nv,
        "visible_count": sum(
            1 for it in q["items"]
            if (draft["items"].get(it["id"]) or {}).get("visibility") == "visible"),
        "method_counts": dict(methods),
        "draft_used_count": methods.get("human_accepted_propagation_draft", 0),
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
    outdir = LOC_ANN / "SUBJECT_GT_LEVEL_B_INDEPENDENT_V1"
    outdir.mkdir(parents=True, exist_ok=True)
    file_shas = {}
    for it in q["items"]:
        ann = dict(draft["items"][it["id"]])
        ann["id"] = it["id"]
        ann["queue_reason"] = it["reason"]
        ann["provenance"] = {
            "origin": "NEW_LEVEL_B_ANNOTATION",
            "queue": QUEUE_LABEL,
            "packet": LABEL,
            "d5_cache_sha256": q["inputs"]["d5_cache_sha256"],
        }
        if it.get("close_pair_evidence"):
            ann["close_pair_evidence"] = it["close_pair_evidence"]
        fp = outdir / f"{it['id']}.json"
        fp.write_text(json.dumps(ann, indent=1, sort_keys=True))
        file_shas[fp.name] = sha256_file(fp)
    per_dive = Counter(str(draft["items"][it["id"]]["dive_id"]) for it in q["items"])
    manifest = {
        "authority": "SUBJECT_GT_LEVEL_B_INDEPENDENT_V1",
        "packet": LABEL,
        "created_at": draft_now(),
        "level": "LEVEL_B_SUBJECT_IDENTITY",
        "family": FAMILY,
        "dives": SELECTED_DIVES,
        "divers": DIVER,
        "annotator": "maxime",
        "schema": {
            "bbox": "[x1,y1,x2,y2] px on 202x360 proxy_360p_native_decoded_frame",
            "visibility": "visible | not_visible",
            "method": "human_drawn_or_corrected | "
                      "human_accepted_propagation_draft | human_not_visible",
            "authority": "HUMAN_REVIEWED (propagated drafts are authority "
                         "ONLY after explicit human accept/correct; "
                         "no silent interpolation is authoritative)",
            "source_identity": "intended Dive Analyzer subject (diver "
                               "performing the dive); track identity is "
                               "derived offline by IoU matching against "
                               "these human boxes, never self-labeled",
        },
        "annotation_count": len(q["items"]),
        "per_dive_counts": dict(sorted(per_dive.items())),
        "not_visible_count": val["not_visible_count"],
        "method_counts": val["method_counts"],
        "source_identities": {
            d: {"diver": DIVER[d],
                "product_authority": "SUBJECT_AUTHORITY_STRONG "
                                     "(dives.person_name <-> divers alias 1:1; "
                                     "caption names the athlete)"}
            for d in SELECTED_DIVES
        },
        "proxy_sha256": q["inputs"]["proxy_sha256"],
        "queue_label": QUEUE_LABEL,
        "queue_sha256": sha256_file(QUEUE_PATH),
        "plan": "SUBJECT_GT_LEVEL_B_ANNOTATION_PLAN_V1",
        "level_a_untouched": "SUBJECT_GT_LEVEL_A_STANDING_V1 sha d805aac2... "
                             "and HURDLE authorities not mutated",
        "files_sha256": dict(sorted(file_shas.items())),
    }
    art_sha = hashlib.sha256(
        json.dumps(manifest["files_sha256"], sort_keys=True).encode()
    ).hexdigest()
    manifest["artifact_sha256"] = art_sha
    (outdir / "MANIFEST.json").write_text(json.dumps(manifest, indent=1, sort_keys=True))
    print(f"frozen {len(q['items'])} Level-B anchors -> {outdir}")
    print(f"artifact_sha256 {art_sha}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("queue")
    sub.add_parser("extract")
    p = sub.add_parser("serve")
    p.add_argument("--port", type=int, default=8766)
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
