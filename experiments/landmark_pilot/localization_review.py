#!/usr/bin/env python3
"""File-backed localization companion to annotate.py; never connects to production DB.

Preparation is a blind annotation operation on both splits. Development consumers
must use only DEVELOPMENT_DESIGN; INTERNAL_EVAL images/labels remain sealed.
"""
import argparse
import hashlib
import http.server
import json
import math
from pathlib import Path
import secrets
import urllib.parse

ROOT = Path(__file__).resolve().parents[2]
SCIENCE = ROOT / "docs/science"
ARTIFACTS = ROOT / "media/perception_decomposition_v1/localization"
LABELS = SCIENCE / "localization_annotations_v1"
SPLITS = ("DEVELOPMENT_DESIGN", "INTERNAL_EVAL")


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_label(payload, row):
    visibility = payload.get("visibility")
    if visibility not in ("visible", "partial", "occluded", "out_of_frame", "ambiguous"):
        raise ValueError("Select visibility")
    box = payload.get("bbox")
    if box is not None:
        if not isinstance(box, list) or len(box) != 4:
            raise ValueError("Box requires four coordinates")
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in box):
            raise ValueError("Box coordinates must be finite numbers")
        x1, y1, x2, y2 = box
        if not (0 <= x1 < x2 <= row["width"] and 0 <= y1 < y2 <= row["height"]):
            raise ValueError("Box must be within the image")
    if visibility in ("visible", "partial") and box is None:
        raise ValueError("Visible diver requires a box")
    if visibility in ("occluded", "out_of_frame") and box is not None:
        raise ValueError("Clear the box for an invisible diver")
    note = payload.get("note", "")
    if not isinstance(note, str) or len(note) > 2000:
        raise ValueError("Invalid note")
    if visibility == "ambiguous" and not note.strip():
        raise ValueError("Describe the ambiguity")
    return {"bbox": box, "visibility": visibility, "note": note,
            "annotator": "maxime", "state": "HUMAN_REVIEWED"}


def prepare():
    import cv2
    import yaml
    split = json.loads((SCIENCE / "TEMPORAL_LANDMARK_INTERNAL_EVAL_V1.json").read_text())
    gt = json.loads((SCIENCE / "TEMPORAL_LANDMARK_GROUND_TRUTH_V2_PTS_REPAIR.json").read_text())
    dives = json.loads((SCIENCE / "PILOT_MANIFEST_V1.json").read_text())["dives"]
    counts = {}
    for subset in SPLITS:
        out = ARTIFACTS / subset
        out.mkdir(parents=True, exist_ok=True)
        rows = []
        for dive in dives:
            did = dive["dive_id"]
            if did not in split[subset]["dive_ids"]:
                continue
            annotation = SCIENCE / "pilot_annotations_v2" / subset / f"dive_{did}.yaml"
            if sha256(annotation) != gt["per_file_checksums"][str(did)]:
                raise ValueError(f"Ground truth checksum mismatch: {did}")
            labels = yaml.safe_load(annotation.read_text())["landmarks"]
            key = dive["media_key"]
            video = ROOT / "media/cache/proxy_360p" / key[:2] / key[2:4] / f"{key}.mp4"
            checksum = sha256(video)
            cap = cv2.VideoCapture(str(video))
            if not cap.isOpened():
                raise ValueError(f"Cannot decode {did}")
            try:
                wanted = {int(v["frame_index"]): [] for v in labels.values()
                          if v["state"] in ("HUMAN_ACCEPTED", "HUMAN_CORRECTED") and v["frame_index"] is not None}
                for phase, label in labels.items():
                    if label["state"] in ("HUMAN_ACCEPTED", "HUMAN_CORRECTED") and label["frame_index"] is not None:
                        wanted[int(label["frame_index"])].append(phase)
                fi = 0
                while wanted:
                    ok, frame = cap.read()
                    if not ok:
                        raise ValueError(f"Landmark outside decoded clip: {did}")
                    if fi in wanted:
                        for phase in wanted.pop(fi):
                            rid = f"{did}_{phase}"
                            image = out / f"{rid}.png"
                            if not cv2.imwrite(str(image), frame):
                                raise OSError("Frame write failed")
                            rows.append({"id": rid, "dive_id": did, "phase": phase,
                                         "frame_index": fi, "split": subset,
                                         "width": frame.shape[1], "height": frame.shape[0],
                                         "fps": cap.get(cv2.CAP_PROP_FPS),
                                         "image_sha256": sha256(image), "media_sha256": checksum,
                                         "media_key": key, "temporal_annotation_sha256": sha256(annotation),
                                         "representation": "proxy_360p_native_decoded_frame",
                                         "bbox": None, "state": "UNREVIEWED"})
                    fi += 1
            finally:
                cap.release()
        (out / "manifest.json").write_text(json.dumps(rows, indent=2) + "\n")
        counts[subset] = len(rows)
    print(json.dumps({"prepared_counts": counts, "labels_modified": False}))


HTML = r'''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Diver Localization Review</title>
<style>*{box-sizing:border-box}body{margin:0;background:#17191b;color:#eef0f2;font:14px system-ui}
header,footer{padding:12px 18px;display:flex;gap:12px;align-items:center;flex-wrap:wrap;border-bottom:1px solid #45484b}
h1{font-size:18px;margin:0}main{padding:16px;max-width:1150px;margin:auto}canvas{display:block;width:auto;height:auto;max-width:100%;max-height:calc(100dvh - 230px);margin:auto;touch-action:none;background:#000}
button,select,input{font:inherit;padding:8px;background:#292e31;color:white;border:1px solid #798186;border-radius:4px}button{cursor:pointer}button:disabled{opacity:.4}
#save{background:#216c51}#note{flex:1;min-width:160px}#status{min-height:24px;color:#8ce0b6}#frame{margin:10px 0}footer{padding-left:0;padding-right:0}</style>
<header><h1>Diver Localization</h1><span id="progress"></span><select id="split"><option>DEVELOPMENT_DESIGN</option><option>INTERNAL_EVAL</option></select></header>
<main><div id="frame"></div><canvas id="canvas"></canvas><footer>
<button id="prev" title="Previous frame" aria-label="Previous frame">&#8592;</button><button id="next" title="Next frame" aria-label="Next frame">&#8594;</button>
<button id="clear" title="Clear box" aria-label="Clear box">&#215;</button>
<select id="visibility" aria-label="Visibility"><option value="">Visibility</option><option value="visible">Visible</option><option value="partial">Partially visible</option><option value="occluded">Occluded</option><option value="out_of_frame">Out of frame</option><option value="ambiguous">Ambiguous</option></select>
<input id="note" placeholder="Annotation note" aria-label="Annotation note"><button id="save">Save review</button></footer><div id="status" role="status"></div></main>
<script>
const token=new URLSearchParams(location.search).get('token');
const el=id=>document.getElementById(id), c=el('canvas'), ctx=c.getContext('2d');
let rows=[],index=0,box=null,start=null,img=new Image(),dirty=false;
async function api(path,opts={}){const r=await fetch(path,{...opts,headers:{'X-Review-Token':token,'Content-Type':'application/json'}});const d=await r.json();if(!r.ok)throw Error(d.error);return d}
function draw(){ctx.drawImage(img,0,0);if(box){ctx.strokeStyle='#00ff85';ctx.lineWidth=2;ctx.strokeRect(box[0],box[1],box[2]-box[0],box[3]-box[1])}}
async function load(){rows=await api('/rows?split='+el('split').value);index=0;await show()}
async function show(){let r=rows[index];box=r.label?.bbox||null;el('visibility').value=r.label?.visibility||'';el('note').value=r.label?.note||'';el('frame').textContent=`Dive ${r.dive_id} | ${r.phase.replaceAll('_',' ')} | Frame ${r.frame_index} | ${r.width} x ${r.height}`;
el('progress').textContent=`${rows.filter(r=>r.label).length}/${rows.length} reviewed`;el('prev').disabled=index===0;el('next').disabled=index===rows.length-1;
c.width=r.width;c.height=r.height;img=new Image();img.onload=draw;img.src='/frame?split='+r.split+'&id='+r.id+'&token='+encodeURIComponent(token);dirty=false;el('status').textContent='';}
function point(e){let r=c.getBoundingClientRect();return [Math.max(0,Math.min(c.width,(e.clientX-r.left)*c.width/r.width)),Math.max(0,Math.min(c.height,(e.clientY-r.top)*c.height/r.height))]}
c.onpointerdown=e=>{start=point(e);c.setPointerCapture(e.pointerId)};
c.onpointermove=e=>{if(!start)return;let p=point(e);box=[Math.min(start[0],p[0]),Math.min(start[1],p[1]),Math.max(start[0],p[0]),Math.max(start[1],p[1])];dirty=true;draw()};
c.onpointerup=e=>{start=null;if(!el('visibility').value)el('visibility').value='visible'};
el('clear').onclick=()=>{box=null;dirty=true;draw()};
el('visibility').onchange=el('note').oninput=()=>dirty=true;
async function move(n){if(dirty&&!confirm('Discard unsaved changes?'))return;index+=n;await show()}
el('prev').onclick=()=>move(-1);el('next').onclick=()=>move(1);el('split').onchange=()=>{if(dirty&&!confirm('Discard unsaved changes?')){el('split').value=rows[index].split;return}load().catch(fail)};
function fail(e){el('status').textContent=e.message}
el('save').onclick=async()=>{try{let r=rows[index];r.label=await api('/label?split='+r.split+'&id='+r.id,{method:'POST',body:JSON.stringify({bbox:box,visibility:el('visibility').value,note:el('note').value})});dirty=false;el('progress').textContent=`${rows.filter(r=>r.label).length}/${rows.length} reviewed`;el('status').textContent='Saved';if(index<rows.length-1){index++;await show()}else el('status').textContent='All frames in this split reached. '+rows.filter(r=>r.label).length+'/'+rows.length+' reviewed.'}catch(e){fail(e)}};
window.onbeforeunload=e=>{if(dirty){e.preventDefault();e.returnValue=''}};load().catch(fail);
</script></html>'''


def serve(port):
    for subset in SPLITS:
        if not (ARTIFACTS / subset / "manifest.json").exists():
            raise ValueError("Preparation incomplete; review cannot start")
    token = secrets.token_urlsafe(32)

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, data, status=200, kind="application/json"):
            body = json.dumps(data).encode() if kind == "application/json" else data
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

        def dispatch(self, write=False):
            url = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(url.query)
            supplied = self.headers.get("X-Review-Token") or q.get("token", [""])[0]
            if not secrets.compare_digest(supplied, token):
                return self.respond({"error": "Review token required"}, 403)
            if url.path == "/" and not write:
                return self.respond(HTML.encode(), kind="text/html; charset=utf-8")
            subset = q.get("split", [""])[0]
            if subset not in SPLITS:
                raise ValueError("Invalid split")
            rows = json.loads((ARTIFACTS / subset / "manifest.json").read_text())
            if url.path == "/rows" and not write:
                for row in rows:
                    p = LABELS / subset / (row["id"] + ".json")
                    if p.exists():
                        row["label"] = json.loads(p.read_text())
                return self.respond(rows)
            row = next((r for r in rows if r["id"] == q.get("id", [""])[0]), None)
            if row is None:
                raise ValueError("Unknown frame")
            if url.path == "/frame" and not write:
                return self.respond((ARTIFACTS / subset / (row["id"] + ".png")).read_bytes(), kind="image/png")
            if url.path == "/label" and write:
                size = int(self.headers.get("Content-Length", 0))
                if not 0 < size <= 8192:
                    raise ValueError("Invalid request size")
                payload = validate_label(json.loads(self.rfile.read(size)), row)
                import datetime
                label = {**row, **payload, "reviewed_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
                path = LABELS / subset / (row["id"] + ".json")
                path.parent.mkdir(parents=True, exist_ok=True)
                temp = path.with_suffix(".tmp")
                temp.write_text(json.dumps(label, indent=2) + "\n")
                temp.replace(path)
                return self.respond(label)
            self.respond({"error": "Not found"}, 404)

        def do_GET(self):
            try:
                self.dispatch()
            except (ValueError, OSError) as exc:
                self.respond({"error": str(exc)}, 400)

        def do_POST(self):
            try:
                self.dispatch(write=True)
            except (ValueError, OSError) as exc:
                self.respond({"error": str(exc)}, 400)

    server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    print(f"http://localhost:{port}/?token={token}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "serve"))
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    prepare() if args.command == "prepare" else serve(args.port)
