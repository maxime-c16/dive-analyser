#!/usr/bin/env python3
"""D4 Annotation server for DETECTOR_D4_REOPEN batch. Port 8892.

Presents failure-driven frames from dives 2341, 2555, 2680, 676, 2541.
Shows D3 hints (what the detector currently finds) to guide annotation.
Press S to save "diver visible", X to save "no diver", A/D to navigate.

ANNOTATION INSTRUCTIONS:
- If a diver is visible in the frame: draw a tight bbox around their body and press S.
- If NO diver is visible (background/pre-dive/post-entry): press X.
- Do NOT annotate pool structures, spectators, or board as divers.
- If diver is partially visible at frame edge: draw bbox around visible portion.
- Box every clearly visible diver (synchronized diving: box all of them).
"""
import json, os, datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

REPO = '/home/mcauchy/dive-analyser'
MANIFEST_PATH = os.path.join(REPO, 'docs/science/localization_annotations_v1/D4_ANNOTATION_BATCH/manifest.json')
FRAMES_DIR = os.path.join(REPO, 'docs/science/localization_annotations_v1/D4_ANNOTATION_BATCH/frames')
PORT = 8892

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
#sidebar { width: 300px; padding: 12px; background: #1a1a1a; border-left: 1px solid #333; display: flex; flex-direction: column; gap: 10px; overflow-y: auto; }
.meta { font-size: 11px; color: #aaa; line-height: 1.6; }
.purpose { font-size: 12px; color: #fa0; background: #2a2a00; padding: 6px 8px; border-radius: 4px; }
.btn { padding: 8px 12px; border: none; border-radius: 6px; cursor: pointer; font-size: 13px; font-weight: 600; }
.btn-green { background: #2a7; color: #fff; }
.btn-red { background: #a33; color: #fff; }
.btn-blue { background: #27a; color: #fff; }
.btn-gray { background: #444; color: #eee; }
.btn:disabled { opacity: 0.4; cursor: default; }
#bbox-display { font-size: 11px; font-family: monospace; background: #2a2a2a; padding: 8px; border-radius: 4px; min-height: 60px; }
#status { font-size: 11px; padding: 6px 8px; border-radius: 4px; background: #2a2a2a; }
#d3-hint { font-size: 11px; color: #f87; background: #2a1a1a; padding: 8px; border-radius: 4px; }
#tip { font-size: 11px; color: #888; margin-top: auto; }
"""

JS_TEMPLATE = """
const FRAME_IDX = TMPL_FRAME_IDX;
const D3_HINTS = TMPL_D3_HINTS;
const FRAME_FILE = 'TMPL_FRAME_FILE';

const canvas = document.getElementById('c');
const ctx = canvas.getContext('2d');
const img = new Image();
let drawing = false, sx, sy, ex, ey;
let bbox = null;

img.onload = function() {
  canvas.width = img.naturalWidth;
  canvas.height = img.naturalHeight;
  redraw();
};
img.src = '/frame/' + FRAME_FILE;

function redraw() {
  ctx.clearRect(0,0,canvas.width,canvas.height);
  ctx.drawImage(img,0,0);
  // Draw D3 hint boxes in orange
  D3_HINTS.forEach(function(h) {
    const b = h.xyxy_px;
    ctx.strokeStyle = 'rgba(255,140,0,0.8)';
    ctx.lineWidth = 2;
    ctx.strokeRect(b[0],b[1],b[2]-b[0],b[3]-b[1]);
    ctx.fillStyle='rgba(255,140,0,0.7)';
    ctx.font='10px monospace';
    ctx.fillText('D3:'+h.conf.toFixed(3), b[0]+2, b[1]+12);
  });
  // Draw user bbox in green
  if(bbox) {
    ctx.strokeStyle='#2fa'; ctx.lineWidth=2;
    ctx.strokeRect(bbox[0],bbox[1],bbox[2]-bbox[0],bbox[3]-bbox[1]);
  }
}

canvas.addEventListener('mousedown', function(e) {
  const r = canvas.getBoundingClientRect();
  const scaleX = canvas.width/r.width;
  const scaleY = canvas.height/r.height;
  sx = (e.clientX-r.left)*scaleX; sy = (e.clientY-r.top)*scaleY;
  drawing = true;
});
canvas.addEventListener('mousemove', function(e) {
  if(!drawing) return;
  const r = canvas.getBoundingClientRect();
  const scaleX = canvas.width/r.width;
  const scaleY = canvas.height/r.height;
  ex = (e.clientX-r.left)*scaleX; ey = (e.clientY-r.top)*scaleY;
  bbox = [Math.min(sx,ex),Math.min(sy,ey),Math.max(sx,ex),Math.max(sy,ey)];
  redraw();
  updateBboxDisplay();
});
canvas.addEventListener('mouseup', function() {
  drawing = false;
  if(bbox && (bbox[2]-bbox[0])>5 && (bbox[3]-bbox[1])>5) {
    document.getElementById('save-btn').disabled = false;
  }
});

function updateBboxDisplay() {
  if(!bbox) { document.getElementById('bbox-display').textContent='No bbox drawn yet.'; return; }
  document.getElementById('bbox-display').textContent =
    'x1='+bbox[0].toFixed(1)+' y1='+bbox[1].toFixed(1)+' x2='+bbox[2].toFixed(1)+' y2='+bbox[3].toFixed(1)+'\\n'+
    'w='+(bbox[2]-bbox[0]).toFixed(1)+' h='+(bbox[3]-bbox[1]).toFixed(1);
}
function useFirstD3Hint() {
  if(!D3_HINTS.length) return;
  const b = D3_HINTS[0].xyxy_px;
  bbox = [b[0],b[1],b[2],b[3]];
  updateBboxDisplay(); redraw();
  document.getElementById('save-btn').disabled = false;
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
  if(e.key==='s'||e.key==='S') save('visible');
  if(e.key==='x'||e.key==='X') save('not_visible');
  if(e.key==='a'||e.key==='ArrowLeft') nav(-1);
  if(e.key==='d'||e.key==='ArrowRight') nav(1);
});
"""

def build_html(fr, idx, total, done):
    hints = fr.get('d3_hints_at_conf005', [])
    ann = fr.get('annotation')
    purpose = fr.get('purpose', '').replace('_', ' ')
    has_diver_hint = fr.get('has_diver_hint')
    hint_str = 'expected diver' if has_diver_hint else ('background' if has_diver_hint is False else 'unknown')

    meta = (
        f"<b>Frame {idx+1}/{total}</b><br>"
        f"Dive {fr['dive_id']} &middot; pts≈{fr.get('pts_approx_s', '?')}s<br>"
        f"Purpose: {purpose}<br>"
        f"Expected content: <b>{hint_str}</b><br>"
        f"<span style='color:#{'4a4' if ann and ann.get('state')=='HUMAN_REVIEWED' else 'a44'}'>"
        f"{'&#x2713; Done (' + (ann.get('visibility','?')) + ')' if ann and ann.get('state')=='HUMAN_REVIEWED' else '&#x25CB; Pending'}</span>"
    )

    d3_hint = f"D3 fires {len(hints)} box(es) at conf≥0.05 (orange = D3 prediction, may be WRONG location)" if hints else "D3: no candidate above conf=0.05 for this frame."
    has_d3_dis = '' if hints else ' disabled'
    status = f"Saved: {ann.get('visibility','?')}" if ann and ann.get('state')=='HUMAN_REVIEWED' else "Not saved yet"

    js = (JS_TEMPLATE
          .replace('TMPL_FRAME_IDX', str(idx))
          .replace('TMPL_D3_HINTS', json.dumps(hints))
          .replace('TMPL_FRAME_FILE', os.path.basename(fr['frame_file']))
          .replace('TMPL_TOTAL', str(total)))

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>D4 Annotation — {idx+1}/{total}</title>
<style>{CSS}</style>
</head>
<body>
<div id="header">
  <h1>&#127919; D4 Detector Reopen — Frame {idx+1}/{total} &nbsp;|&nbsp; {done}/{total} done</h1>
  <button class="btn btn-gray" onclick="nav(-1)">&#8592; Prev</button>
  <button class="btn btn-gray" onclick="nav(1)">Next &#8594;</button>
</div>
<div id="main">
  <div id="canvas-wrap"><canvas id="c"></canvas></div>
  <div id="sidebar">
    <div class="purpose">{purpose}</div>
    <div class="meta">{meta}</div>
    <div id="d3-hint">{d3_hint}</div>
    <div id="bbox-display">No bbox drawn yet.<br>Click + drag to draw tightly around the diver body.</div>
    <button class="btn btn-blue"{has_d3_dis} onclick="useFirstD3Hint()">Use D3 best box (check carefully!)</button>
    <button class="btn btn-green" id="save-btn" disabled onclick="save('visible')">&#10003; S — diver VISIBLE (save bbox)</button>
    <button class="btn btn-red" onclick="save('not_visible')">&#10007; X — NO diver visible</button>
    <button class="btn btn-gray" onclick="clearBbox()">Clear bbox</button>
    <div id="status">{status}</div>
    <div id="tip">
      <b>Keys:</b> S=save visible &nbsp; X=no diver &nbsp; A/D=navigate<br><br>
      <b>Box every clearly visible diver</b> body tightly (not splash, board, spectators).<br>
      If diver at frame edge: box the visible portion.<br>
      Orange boxes = D3 predictions (often WRONG — verify before using!).<br>
      Goal: teach D3 where the diver actually is vs background noise.
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
            done = sum(1 for f in frames if f.get('annotation', {}).get('state') == 'HUMAN_REVIEWED')
            html = build_html(frames[idx], idx, len(frames), done)
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
            vis = body['visibility']
            bbox = body.get('bbox')
            manifest['frames'][idx]['annotation'] = {
                'state': 'HUMAN_REVIEWED',
                'visibility': vis,
                'bbox': [round(x, 4) for x in bbox] if bbox else None,
                'annotator': 'maxime',
                'annotated_at': datetime.datetime.utcnow().isoformat() + '+00:00',
            }
            save_manifest(manifest)
            done = sum(1 for f in manifest['frames'] if f.get('annotation', {}).get('state') == 'HUMAN_REVIEWED')
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
    done = sum(1 for f in manifest['frames'] if f.get('annotation', {}).get('state') == 'HUMAN_REVIEWED')
    total = len(manifest['frames'])
    print(f"D4 Annotation server: http://192.168.1.57:{PORT}")
    print(f"Progress: {done}/{total} frames annotated")
    print("Press Ctrl+C to stop")
    server.serve_forever()
