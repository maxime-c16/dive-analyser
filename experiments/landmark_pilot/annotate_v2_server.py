#!/usr/bin/env python3
"""
Annotation server for DEVELOPMENT_DESIGN_V2.
Serves frames and accepts bbox annotations via a browser UI.
Run: python3 annotate_v2_server.py
Open: http://localhost:8891
"""
import json, os, base64, hashlib, datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

REPO = '/home/mcauchy/dive-analyser'
MANIFEST_PATH = os.path.join(REPO, 'docs/science/localization_annotations_v1/DEVELOPMENT_DESIGN_V2/manifest.json')
FRAMES_DIR = os.path.join(REPO, 'docs/science/localization_annotations_v1/DEVELOPMENT_DESIGN_V2/frames')
OUT_DIR = os.path.join(REPO, 'docs/science/localization_annotations_v1/DEVELOPMENT_DESIGN_V2')
PORT = 8891

def load_manifest():
    with open(MANIFEST_PATH) as f:
        return json.load(f)

def save_manifest(manifest):
    with open(MANIFEST_PATH, 'w') as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        f.write('\n')

HTML = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Diver Annotation V2 — {progress}</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, sans-serif; background: #111; color: #eee; }
#header { padding: 10px 16px; background: #222; display: flex; gap: 16px; align-items: center; border-bottom: 1px solid #444; }
#header h1 { font-size: 14px; flex: 1; }
#main { display: flex; gap: 0; height: calc(100vh - 48px); }
#canvas-wrap { flex: 1; overflow: hidden; display: flex; align-items: center; justify-content: center; background: #000; position: relative; }
canvas { cursor: crosshair; max-width: 100%; max-height: 100%; }
#sidebar { width: 280px; padding: 12px; background: #1a1a1a; border-left: 1px solid #333; display: flex; flex-direction: column; gap: 10px; overflow-y: auto; }
.meta { font-size: 11px; color: #aaa; line-height: 1.6; }
.btn { padding: 8px 12px; border: none; border-radius: 6px; cursor: pointer; font-size: 13px; font-weight: 600; }
.btn-green { background: #2a7; color: #fff; }
.btn-red { background: #a33; color: #fff; }
.btn-blue { background: #27a; color: #fff; }
.btn-gray { background: #444; color: #eee; }
.btn:disabled { opacity: 0.4; cursor: default; }
#bbox-display { font-size: 11px; font-family: monospace; background: #2a2a2a; padding: 8px; border-radius: 4px; min-height: 60px; }
#status { font-size: 11px; padding: 6px 8px; border-radius: 4px; background: #2a2a2a; }
#coco-hint { font-size: 11px; color: #7af; background: #1a2a3a; padding: 8px; border-radius: 4px; }
</style>
</head>
<body>
<div id="header">
  <h1>🎯 Diver Annotation V2 — Frame <span id="hdr-idx">{idx}</span>/{total} &nbsp;|&nbsp; {dive_info} &nbsp;|&nbsp; <span id="hdr-done">{done}</span> annotated</h1>
  <button class="btn btn-gray" onclick="nav(-1)">← Prev</button>
  <button class="btn btn-gray" onclick="nav(1)">Next →</button>
</div>
<div id="main">
  <div id="canvas-wrap">
    <canvas id="c"></canvas>
  </div>
  <div id="sidebar">
    <div class="meta" id="meta">{meta_html}</div>
    <div id="coco-hint">{coco_hint}</div>
    <div id="bbox-display">No bbox drawn yet.<br>Click + drag on the image to draw a bbox around the diver.</div>
    <button class="btn btn-blue" onclick="useCoco()" id="use-coco-btn" {coco_disabled}>Use COCO best bbox</button>
    <button class="btn btn-green" onclick="save('visible')" id="save-btn" disabled>✓ Save — diver visible</button>
    <button class="btn btn-red" onclick="save('not_visible')">✗ Save — diver NOT visible</button>
    <button class="btn btn-gray" onclick="clearBbox()">Clear bbox</button>
    <div id="status">{status_html}</div>
    <div style="font-size:11px;color:#888;margin-top:auto">
      <b>Instructions:</b><br>
      Draw bbox tightly around the diver's body (not water splash).<br>
      If diver is fully hidden (underwater, behind board), click "NOT visible".<br>
      Press S to save visible, X for not visible, A/D for prev/next.
    </div>
  </div>
</div>
<script>
const FRAME_IDX = {frame_idx_js};
const COCO_BBOXES = {coco_bboxes_js};
const IMG_W = {img_w}, IMG_H = {img_h};

const canvas = document.getElementById('c');
const ctx = canvas.getContext('2d');
const img = new Image();
let drawing = false, sx, sy, ex, ey;
let bbox = null; // [x1,y1,x2,y2] in image coords

img.onload = () => {
  canvas.width = img.naturalWidth;
  canvas.height = img.naturalHeight;
  // Scale to fit
  const wrap = document.getElementById('canvas-wrap');
  const scale = Math.min(wrap.clientWidth / img.naturalWidth, wrap.clientHeight / img.naturalHeight, 1);
  canvas.style.width = (img.naturalWidth * scale) + 'px';
  canvas.style.height = (img.naturalHeight * scale) + 'px';
  redraw();
};
img.src = '/frame/{frame_file}';

function getPos(e) {
  const rect = canvas.getBoundingClientRect();
  const scaleX = canvas.width / rect.width;
  const scaleY = canvas.height / rect.height;
  return { x: (e.clientX - rect.left) * scaleX, y: (e.clientY - rect.top) * scaleY };
}
canvas.addEventListener('mousedown', e => { const p = getPos(e); sx=p.x; sy=p.y; drawing=true; });
canvas.addEventListener('mousemove', e => { if(!drawing) return; const p=getPos(e); ex=p.x; ey=p.y; redraw(); drawCurrentRect(); });
canvas.addEventListener('mouseup', e => {
  if(!drawing) return; drawing=false;
  const p=getPos(e); ex=p.x; ey=p.y;
  bbox = [Math.min(sx,ex), Math.min(sy,ey), Math.max(sx,ex), Math.max(sy,ey)];
  updateBboxDisplay(); redraw(); drawFinalRect();
  document.getElementById('save-btn').disabled = false;
});

function drawCurrentRect() {
  ctx.strokeStyle='#0f0'; ctx.lineWidth=2; ctx.setLineDash([4,4]);
  ctx.strokeRect(Math.min(sx,ex), Math.min(sy,ey), Math.abs(ex-sx), Math.abs(ey-sy));
}
function drawFinalRect() {
  if(!bbox) return;
  ctx.strokeStyle='#0f0'; ctx.lineWidth=2; ctx.setLineDash([]);
  ctx.strokeRect(bbox[0], bbox[1], bbox[2]-bbox[0], bbox[3]-bbox[1]);
}
function redraw() {
  ctx.drawImage(img, 0, 0);
  COCO_BBOXES.forEach((b,i) => {
    ctx.strokeStyle='rgba(255,165,0,0.5)'; ctx.lineWidth=1; ctx.setLineDash([2,2]);
    ctx.strokeRect(b.bbox_xyxy[0], b.bbox_xyxy[1], b.bbox_xyxy[2]-b.bbox_xyxy[0], b.bbox_xyxy[3]-b.bbox_xyxy[1]);
    ctx.fillStyle='rgba(255,165,0,0.7)'; ctx.font='10px sans-serif'; ctx.setLineDash([]);
    ctx.fillText('COCO '+(b.conf*100).toFixed(0)+'%', b.bbox_xyxy[0]+2, b.bbox_xyxy[1]-3);
  });
  drawFinalRect();
}
function updateBboxDisplay() {
  if(!bbox) { document.getElementById('bbox-display').textContent='No bbox.'; return; }
  document.getElementById('bbox-display').innerHTML =
    'x1='+bbox[0].toFixed(1)+' y1='+bbox[1].toFixed(1)+'<br>x2='+bbox[2].toFixed(1)+' y2='+bbox[3].toFixed(1)+'<br>'+
    'w='+(bbox[2]-bbox[0]).toFixed(1)+' h='+(bbox[3]-bbox[1]).toFixed(1);
}
function useCoco() {
  if(!COCO_BBOXES.length) return;
  const b = COCO_BBOXES[0].bbox_xyxy;
  bbox = [b[0], b[1], b[2], b[3]];
  updateBboxDisplay(); redraw();
  document.getElementById('save-btn').disabled = false;
}
function clearBbox() {
  bbox=null; redraw(); updateBboxDisplay();
  document.getElementById('save-btn').disabled=true;
}
function save(visibility) {
  const payload = { frame_idx: FRAME_IDX, visibility, bbox };
  fetch('/save', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload) })
    .then(r=>r.json()).then(d => {
      document.getElementById('status').textContent = d.message;
      if(d.ok) setTimeout(()=>nav(1), 400);
    });
}
function nav(delta) {
  const next = FRAME_IDX + delta;
  if(next < 0 || next >= {total}) return;
  window.location.href = '/?idx=' + next;
}
document.addEventListener('keydown', e => {
  if(e.key==='s') save('visible');
  if(e.key==='x') save('not_visible');
  if(e.key==='a' || e.key==='ArrowLeft') nav(-1);
  if(e.key==='d' || e.key==='ArrowRight') nav(1);
});
</script>
</body>
</html>"""

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # quiet

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == '/':
            qs = parse_qs(parsed.query)
            idx = int(qs.get('idx', ['0'])[0])
            manifest = load_manifest()
            frames = manifest['frames']
            if idx >= len(frames): idx = len(frames) - 1
            if idx < 0: idx = 0
            fr = frames[idx]

            done = sum(1 for f in frames if f.get('annotation') is not None)
            coco = fr.get('coco_candidates', [])
            coco_hint = f"COCO: {len(coco)} person(s) detected" if coco else "COCO: no person detected"
            coco_disabled = '' if coco else 'disabled'
            coco_bboxes_js = json.dumps(coco)

            # Get image dimensions
            img_path = os.path.join(FRAMES_DIR, os.path.basename(fr['frame_file']))
            import subprocess
            r = subprocess.run(['ffprobe', '-v', 'quiet', '-show_entries',
                'stream=width,height', '-of', 'csv=p=0', img_path],
                capture_output=True, text=True)
            dims = r.stdout.strip().split('\n')[0].split(',') if r.returncode == 0 else ['640','360']
            img_w, img_h = dims[0], dims[1]

            ann = fr.get('annotation')
            status_html = f"Saved: {ann['visibility'] if ann else 'Not saved yet'}"
            meta_html = (
                f"<b>Frame {idx+1}/{len(frames)}</b><br>"
                f"Dive {fr['dive_id']} · {fr['dive_code']} · {fr['platform_type']} {fr['height']}<br>"
                f"Date: {fr['date']} ({fr['temporal_bucket']})<br>"
                f"{'🏊 HURDLE dive' if fr['hurdle_flag']=='HURDLE' else '🏊 Standard dive'}<br>"
                f"PTS: ~{fr['pts_approx_s']}s of {fr['duration_s']}s<br>"
                f"<span style='color:#{'4a4' if ann else 'a44'}'>{'✓ Annotated' if ann else '○ Not yet annotated'}</span>"
            )
            dive_info = f"D{fr['dive_id']} {fr['dive_code']} {fr['platform_type']}{fr['height']}"

            html = HTML.format(
                progress=f"{done}/{len(frames)}",
                idx=idx+1, total=len(frames), done=done,
                dive_info=dive_info,
                meta_html=meta_html,
                coco_hint=coco_hint,
                coco_disabled=coco_disabled,
                coco_bboxes_js=coco_bboxes_js,
                frame_idx_js=idx,
                frame_file=os.path.basename(fr['frame_file']),
                img_w=img_w, img_h=img_h,
                status_html=status_html,
            )
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(html.encode())

        elif parsed.path.startswith('/frame/'):
            fname = parsed.path[len('/frame/'):]
            fpath = os.path.join(FRAMES_DIR, fname)
            if os.path.exists(fpath):
                with open(fpath, 'rb') as f:
                    data = f.read()
                self.send_response(200)
                self.send_header('Content-Type', 'image/jpeg')
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_response(404); self.end_headers()

        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        if self.path == '/save':
            length = int(self.headers['Content-Length'])
            body = json.loads(self.rfile.read(length))
            manifest = load_manifest()
            idx = body['frame_idx']
            fr = manifest['frames'][idx]
            fr['annotation'] = {
                'visibility': body['visibility'],
                'bbox': body.get('bbox'),
                'annotator': 'maxime',
                'annotated_at': datetime.datetime.utcnow().isoformat() + '+00:00',
                'state': 'HUMAN_REVIEWED',
            }
            save_manifest(manifest)
            done = sum(1 for f in manifest['frames'] if f.get('annotation') is not None)
            resp = {'ok': True, 'message': f"Saved ({done}/{len(manifest['frames'])} done)"}
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(resp).encode())
        else:
            self.send_response(404); self.end_headers()

if __name__ == '__main__':
    server = HTTPServer(('0.0.0.0', PORT), Handler)
    print(f"Annotation server: http://localhost:{PORT}")
    print(f"Manifest: {MANIFEST_PATH}")
    print(f"Frames: {FRAMES_DIR}")
    manifest = load_manifest()
    done = sum(1 for f in manifest['frames'] if f.get('annotation') is not None)
    print(f"Progress: {done}/{len(manifest['frames'])} frames annotated")
    server.serve_forever()
