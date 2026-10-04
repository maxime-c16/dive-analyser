#!/usr/bin/env python3
"""Annotation server for DEVELOPMENT_DESIGN_V2. Port 8891."""
import json, os, datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

REPO = '/home/mcauchy/dive-analyser'
MANIFEST_PATH = os.path.join(REPO, 'docs/science/localization_annotations_v1/DEVELOPMENT_DESIGN_V2/manifest.json')
FRAMES_DIR = os.path.join(REPO, 'docs/science/localization_annotations_v1/DEVELOPMENT_DESIGN_V2/frames')
PORT = 8891

def load_manifest():
    with open(MANIFEST_PATH) as f:
        return json.load(f)

def save_manifest(manifest):
    with open(MANIFEST_PATH, 'w') as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        f.write('\n')

CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, sans-serif; background: #111; color: #eee; }
#header { padding: 10px 16px; background: #222; display: flex; gap: 16px; align-items: center; border-bottom: 1px solid #444; }
#header h1 { font-size: 14px; flex: 1; }
#main { display: flex; height: calc(100vh - 48px); }
#canvas-wrap { flex: 1; overflow: hidden; display: flex; align-items: center; justify-content: center; background: #000; }
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
#tip { font-size: 11px; color: #888; margin-top: auto; }
"""

JS_TEMPLATE = """
const FRAME_IDX = TMPL_FRAME_IDX;
const COCO_BBOXES = TMPL_COCO_BBOXES;

const canvas = document.getElementById('c');
const ctx = canvas.getContext('2d');
const img = new Image();
let drawing = false, sx, sy, ex, ey;
let bbox = null;

img.onload = () => {
  canvas.width = img.naturalWidth;
  canvas.height = img.naturalHeight;
  const wrap = document.getElementById('canvas-wrap');
  const scale = Math.min(wrap.clientWidth / img.naturalWidth, wrap.clientHeight / img.naturalHeight, 1.0);
  canvas.style.width = (img.naturalWidth * scale) + 'px';
  canvas.style.height = (img.naturalHeight * scale) + 'px';
  redraw();
};
img.src = '/frame/TMPL_FRAME_FILE';

function getPos(e) {
  const rect = canvas.getBoundingClientRect();
  return { x: (e.clientX - rect.left) * canvas.width / rect.width,
           y: (e.clientY - rect.top)  * canvas.height / rect.height };
}
canvas.addEventListener('mousedown', e => { const p=getPos(e); sx=p.x; sy=p.y; drawing=true; });
canvas.addEventListener('mousemove', e => { if(!drawing) return; const p=getPos(e); ex=p.x; ey=p.y; redraw(); drawRect(sx,sy,ex,ey,'#0f0',true); });
canvas.addEventListener('mouseup',   e => {
  if(!drawing) return; drawing=false;
  const p=getPos(e); ex=p.x; ey=p.y;
  bbox=[Math.min(sx,ex),Math.min(sy,ey),Math.max(sx,ex),Math.max(sy,ey)];
  updateBboxDisplay(); redraw();
  document.getElementById('save-btn').disabled=false;
});

function drawRect(x1,y1,x2,y2,color,dashed) {
  ctx.strokeStyle=color; ctx.lineWidth=2;
  ctx.setLineDash(dashed?[4,4]:[]);
  ctx.strokeRect(x1,y1,x2-x1,y2-y1);
  ctx.setLineDash([]);
}
function redraw() {
  ctx.drawImage(img,0,0);
  COCO_BBOXES.forEach(b => {
    const bb=b.bbox_xyxy;
    ctx.strokeStyle='rgba(255,165,0,0.6)'; ctx.lineWidth=1; ctx.setLineDash([3,3]);
    ctx.strokeRect(bb[0],bb[1],bb[2]-bb[0],bb[3]-bb[1]);
    ctx.fillStyle='rgba(255,165,0,0.8)'; ctx.font='10px sans-serif'; ctx.setLineDash([]);
    ctx.fillText('COCO '+(b.conf*100).toFixed(0)+'%', bb[0]+2, bb[1]>12?bb[1]-3:bb[1]+12);
  });
  if(bbox) drawRect(bbox[0],bbox[1],bbox[2],bbox[3],'#0f0',false);
}
function updateBboxDisplay() {
  if(!bbox){ document.getElementById('bbox-display').textContent='No bbox drawn yet.'; return; }
  document.getElementById('bbox-display').innerHTML =
    'x1='+bbox[0].toFixed(1)+' y1='+bbox[1].toFixed(1)+'<br>'+
    'x2='+bbox[2].toFixed(1)+' y2='+bbox[3].toFixed(1)+'<br>'+
    'w='+(bbox[2]-bbox[0]).toFixed(1)+' h='+(bbox[3]-bbox[1]).toFixed(1);
}
function useCoco() {
  if(!COCO_BBOXES.length) return;
  const b=COCO_BBOXES[0].bbox_xyxy;
  bbox=[b[0],b[1],b[2],b[3]];
  updateBboxDisplay(); redraw();
  document.getElementById('save-btn').disabled=false;
}
function clearBbox() { bbox=null; redraw(); updateBboxDisplay(); document.getElementById('save-btn').disabled=true; }
function save(vis) {
  fetch('/save',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({frame_idx:FRAME_IDX,visibility:vis,bbox:bbox})})
  .then(r=>r.json()).then(d=>{
    document.getElementById('status').textContent=d.message;
    if(d.ok) setTimeout(()=>nav(1),350);
  });
}
function nav(delta) {
  const next=FRAME_IDX+delta;
  if(next<0||next>=TMPL_TOTAL) return;
  window.location.href='/?idx='+next;
}
document.addEventListener('keydown', e=>{
  if(e.key==='s') save('visible');
  if(e.key==='x') save('not_visible');
  if(e.key==='a'||e.key==='ArrowLeft') nav(-1);
  if(e.key==='d'||e.key==='ArrowRight') nav(1);
});
"""

def build_html(fr, idx, total, done, manifest_frames):
    coco = fr.get('coco_candidates', [])
    ann = fr.get('annotation')

    meta = (
        f"<b>Frame {idx+1}/{total}</b><br>"
        f"Dive {fr['dive_id']} &middot; {fr['dive_code']} &middot; {fr['platform_type']} {fr['height']}<br>"
        f"Date: {fr['date']} ({fr['temporal_bucket']})<br>"
        f"{'&#x1F4E6; HURDLE dive' if fr['hurdle_flag']=='HURDLE' else '&#x1F3CA; Standard dive'}<br>"
        f"PTS: ~{fr['pts_approx_s']}s / {fr['duration_s']}s total<br>"
        f"<span style='color:#{'4a4' if ann else 'a44'}'>"
        f"{'&#x2713; Annotated ('+ann['visibility']+')' if ann else '&#x25CB; Not yet annotated'}</span>"
    )
    coco_hint = f"COCO: {len(coco)} person(s) pre-detected" if coco else "COCO: no person detected in this frame"
    coco_dis = '' if coco else ' disabled'
    status = f"Last saved: {ann['visibility']}" if ann else "Not saved yet"

    js = (JS_TEMPLATE
          .replace('TMPL_FRAME_IDX', str(idx))
          .replace('TMPL_COCO_BBOXES', json.dumps(coco))
          .replace('TMPL_FRAME_FILE', os.path.basename(fr['frame_file']))
          .replace('TMPL_TOTAL', str(total)))

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Annotation V2 — {idx+1}/{total}</title>
<style>{CSS}</style>
</head>
<body>
<div id="header">
  <h1>&#127919; Annotation V2 &mdash; Frame {idx+1}/{total} &nbsp;|&nbsp; {fr['dive_id']} {fr['dive_code']} {fr['platform_type']}{fr['height']} &nbsp;|&nbsp; {done}/{total} done</h1>
  <button class="btn btn-gray" onclick="nav(-1)">&#8592; Prev</button>
  <button class="btn btn-gray" onclick="nav(1)">Next &#8594;</button>
</div>
<div id="main">
  <div id="canvas-wrap"><canvas id="c"></canvas></div>
  <div id="sidebar">
    <div class="meta">{meta}</div>
    <div id="coco-hint">{coco_hint}</div>
    <div id="bbox-display">No bbox drawn yet.<br>Click + drag to draw around the diver.</div>
    <button class="btn btn-blue"{coco_dis} onclick="useCoco()">Use COCO best bbox</button>
    <button class="btn btn-green" id="save-btn" disabled onclick="save('visible')">&#10003; Save &mdash; diver VISIBLE</button>
    <button class="btn btn-red" onclick="save('not_visible')">&#10007; Save &mdash; diver NOT visible</button>
    <button class="btn btn-gray" onclick="clearBbox()">Clear bbox</button>
    <div id="status">{status}</div>
    <div id="tip">
      <b>Keys:</b> S=save visible &nbsp; X=not visible &nbsp; A/D or &#8592;&#8594;=navigate<br><br>
      Draw bbox tightly around the diver body (not splash/board/spectators).<br>
      If diver is underwater or behind apparatus, press X.
    </div>
  </div>
</div>
<script>{js}</script>
</body>
</html>"""

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == '/':
            qs = parse_qs(parsed.query)
            idx = max(0, int(qs.get('idx', ['0'])[0]))
            manifest = load_manifest()
            frames = manifest['frames']
            idx = min(idx, len(frames)-1)
            done = sum(1 for f in frames if f.get('annotation') is not None)
            html = build_html(frames[idx], idx, len(frames), done, frames)
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
                self.send_header('Content-Length', str(len(data)))
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
            manifest['frames'][idx]['annotation'] = {
                'visibility': body['visibility'],
                'bbox': body.get('bbox'),
                'annotator': 'maxime',
                'annotated_at': datetime.datetime.utcnow().isoformat() + '+00:00',
                'state': 'HUMAN_REVIEWED',
            }
            save_manifest(manifest)
            done = sum(1 for f in manifest['frames'] if f.get('annotation') is not None)
            total = len(manifest['frames'])
            resp = {'ok': True, 'message': f"Saved ({done}/{total} done)"}
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(resp).encode())
        else:
            self.send_response(404); self.end_headers()

if __name__ == '__main__':
    server = HTTPServer(('0.0.0.0', PORT), Handler)
    manifest = load_manifest()
    done = sum(1 for f in manifest['frames'] if f.get('annotation') is not None)
    print(f"Annotation server: http://localhost:{PORT}")
    print(f"Progress: {done}/{len(manifest['frames'])} frames annotated")
    server.serve_forever()
