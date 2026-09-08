#!/usr/bin/env python3
"""D5 Annotation server v2 — embeds images as base64 data URIs.
Port 8892. Controls: S=visible (draw bbox first), X=not visible, A/D=navigate.
"""
import json, os, datetime, base64
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

REPO          = '/home/mcauchy/dive-analyser'
BATCH_DIR     = os.path.join(REPO, 'docs/science/localization_annotations_v1/D5_ANNOTATION_BATCH')
MANIFEST_PATH = os.path.join(BATCH_DIR, 'manifest.json')
FRAMES_DIR    = os.path.join(BATCH_DIR, 'frames')
PORT = 8892


def load_manifest():
    with open(MANIFEST_PATH) as f:
        return json.load(f)


def save_manifest(m):
    with open(MANIFEST_PATH, 'w') as f:
        json.dump(m, f, indent=2, ensure_ascii=False)
        f.write('\n')


def img_b64(frame_file):
    path = os.path.join(FRAMES_DIR, frame_file)
    if not os.path.exists(path):
        return ""
    with open(path, 'rb') as f:
        return base64.b64encode(f.read()).decode()


CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, sans-serif; background: #111; color: #eee; user-select: none; }
#hdr { padding: 10px 16px; background: #222; display: flex; gap: 12px; align-items: center;
       border-bottom: 2px solid #555; }
#hdr h1 { font-size: 14px; flex: 1; }
#main { display: flex; height: calc(100vh - 50px); }
#cv-wrap { flex: 1; overflow: hidden; display: flex; align-items: center; justify-content: center;
           background: #222; position: relative; }
#wrap-inner { position: relative; display: inline-block; }
#bg-img { display: block; max-width: 100%; max-height: calc(100vh - 50px); }
#ov { position: absolute; top: 0; left: 0; width: 100%; height: 100%;
      cursor: crosshair; pointer-events: all; }
#sidebar { width: 280px; padding: 12px; background: #1a1a1a; border-left: 1px solid #444;
           display: flex; flex-direction: column; gap: 10px; overflow-y: auto; }
.meta { font-size: 11px; color: #aaa; line-height: 1.7; }
.purpose { font-size: 12px; color: #fa0; background: #2a2200; padding: 6px 8px; border-radius: 4px; border:1px solid #554400; }
.btn { padding: 9px 12px; border: none; border-radius: 6px; cursor: pointer; font-size: 13px; font-weight: 600; width: 100%; }
.btn-green { background: #1a7a4a; color: #fff; border: 1px solid #2fa; }
.btn-red   { background: #7a1a1a; color: #fff; border: 1px solid #f44; }
.btn-blue  { background: #1a4a7a; color: #fff; border: 1px solid #4af; }
.btn-gray  { background: #333; color: #ccc; }
.btn:disabled { opacity: 0.3; cursor: default; }
.btn:hover:not(:disabled) { filter: brightness(1.2); }
#bbox-info { font-size: 11px; font-family: monospace; background: #222; padding: 8px;
             border-radius: 4px; min-height: 56px; color: #8f8; border: 1px solid #333; }
#status { font-size: 12px; padding: 6px 8px; border-radius: 4px; background: #222;
          border: 1px solid #333; text-align: center; }
#d4-hint { font-size: 11px; color: #fa8; background: #1a1000; padding: 8px; border-radius: 4px; border:1px solid #443; }
#tip { font-size: 11px; color: #777; margin-top: auto; line-height: 1.6; }
#progress { font-size: 11px; color: #4af; }
"""

PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>D5 Annotate {idx1}/{total}</title>
<style>{css}</style>
</head><body>
<div id="hdr">
  <h1>🎯 D5 Mining — Frame {idx1}/{total} &nbsp;|&nbsp; {done}/{total} done</h1>
  <button class="btn btn-gray" style="width:auto;padding:6px 14px" onclick="nav(-1)">◀ Prev</button>
  <button class="btn btn-gray" style="width:auto;padding:6px 14px" onclick="nav(1)">Next ▶</button>
</div>
<div id="main">
  <div id="cv-wrap">
    <div id="wrap-inner">
      <img id="bg-img" src="data:image/jpeg;base64,{b64}" draggable="false">
      <canvas id="ov"></canvas>
    </div>
  </div>
  <div id="sidebar">
    <div class="purpose">{purpose}</div>
    <div class="meta">{meta}</div>
    <div id="d4-hint">{d4hint}</div>
    <div id="bbox-info">No bbox drawn yet.<br>Click and drag on the image to draw a box around the diver.</div>
    <button class="btn btn-blue" id="hint-btn" onclick="useHint()" {hint_dis}>⬛ Use D4 best box (verify!)</button>
    <button class="btn btn-green" id="save-btn" disabled onclick="save('visible')">✓ &nbsp;S — Diver VISIBLE</button>
    <button class="btn btn-red" onclick="save('not_visible')">✗ &nbsp;X — NO diver visible</button>
    <button class="btn btn-gray" onclick="clearBbox()">↺ Clear bbox</button>
    <div id="status">{saved_str}</div>
    <div id="progress">{done}/{total} frames annotated</div>
    <div id="tip"><b>Keyboard:</b> S = diver visible &nbsp;·&nbsp; X = no diver &nbsp;·&nbsp; A/← = prev &nbsp;·&nbsp; D/→ = next<br><br>
      Draw a tight box around the TARGET diver's body.<br>
      If partial (edge of frame): box the visible part.<br>
      Orange = D4 detector hints — verify, they may be wrong.</div>
  </div>
</div>
<script>
const HINTS = {hints_json};
const IDX   = {idx};
const TOTAL = {total};

// Scale overlay canvas to match displayed img size
const bgImg = document.getElementById('bg-img');
const ov    = document.getElementById('ov');
const ctx   = ov.getContext('2d');
let natW, natH, dispW, dispH;

function syncCanvas() {{
  dispW = bgImg.offsetWidth;
  dispH = bgImg.offsetHeight;
  natW  = bgImg.naturalWidth;
  natH  = bgImg.naturalHeight;
  ov.width  = dispW;
  ov.height = dispH;
  redraw();
}}

bgImg.addEventListener('load', syncCanvas);
window.addEventListener('resize', syncCanvas);
// Also sync after layout (image may already be cached)
if (bgImg.complete) setTimeout(syncCanvas, 50);

let bbox = null;
let drawing = false, sx, sy;

function toImgCoords(cx, cy) {{
  return [cx * natW / dispW, cy * natH / dispH];
}}

function toCanvCoords(ix, iy) {{
  return [ix * dispW / natW, iy * dispH / natH];
}}

ov.addEventListener('mousedown', function(e) {{
  const r = ov.getBoundingClientRect();
  sx = e.clientX - r.left;
  sy = e.clientY - r.top;
  drawing = true;
}});

ov.addEventListener('mousemove', function(e) {{
  if (!drawing) return;
  const r  = ov.getBoundingClientRect();
  const ex = e.clientX - r.left;
  const ey = e.clientY - r.top;
  // Store in image coords
  const [ix1, iy1] = toImgCoords(Math.min(sx,ex), Math.min(sy,ey));
  const [ix2, iy2] = toImgCoords(Math.max(sx,ex), Math.max(sy,ey));
  bbox = [ix1, iy1, ix2, iy2];
  redraw();
  updateInfo();
}});

ov.addEventListener('mouseup', function() {{
  drawing = false;
  if (bbox && (bbox[2]-bbox[0]) > 3 && (bbox[3]-bbox[1]) > 3) {{
    document.getElementById('save-btn').disabled = false;
  }}
}});

function redraw() {{
  ctx.clearRect(0, 0, dispW, dispH);
  // D4 hints in orange
  HINTS.forEach(function(h) {{
    const b = h.xyxy_px;
    const [x1, y1] = toCanvCoords(b[0], b[1]);
    const [x2, y2] = toCanvCoords(b[2], b[3]);
    ctx.strokeStyle = 'rgba(255,165,0,0.95)';
    ctx.lineWidth = 2;
    ctx.strokeRect(x1, y1, x2-x1, y2-y1);
    ctx.fillStyle = 'rgba(255,165,0,0.85)';
    ctx.font = 'bold 11px monospace';
    ctx.fillText('D4 ' + h.conf.toFixed(2), x1+2, y1 > 14 ? y1-3 : y1+12);
  }});
  // User bbox in cyan
  if (bbox) {{
    const [x1, y1] = toCanvCoords(bbox[0], bbox[1]);
    const [x2, y2] = toCanvCoords(bbox[2], bbox[3]);
    ctx.strokeStyle = '#2fffc0';
    ctx.lineWidth = 2;
    ctx.strokeRect(x1, y1, x2-x1, y2-y1);
    ctx.fillStyle = 'rgba(0,255,180,0.08)';
    ctx.fillRect(x1, y1, x2-x1, y2-y1);
  }}
}}

function updateInfo() {{
  if (!bbox) {{ document.getElementById('bbox-info').textContent = 'No bbox drawn yet.'; return; }}
  document.getElementById('bbox-info').innerHTML =
    'x1=' + bbox[0].toFixed(1) + ' y1=' + bbox[1].toFixed(1) + '<br>' +
    'x2=' + bbox[2].toFixed(1) + ' y2=' + bbox[3].toFixed(1) + '<br>' +
    'w='  + (bbox[2]-bbox[0]).toFixed(1) + ' h=' + (bbox[3]-bbox[1]).toFixed(1);
}}

function useHint() {{
  if (!HINTS.length) return;
  const b = HINTS[0].xyxy_px;
  bbox = [b[0], b[1], b[2], b[3]];
  redraw(); updateInfo();
  document.getElementById('save-btn').disabled = false;
}}

function clearBbox() {{
  bbox = null; redraw(); updateInfo();
  document.getElementById('save-btn').disabled = true;
}}

function save(vis) {{
  if (vis === 'visible' && !bbox) {{ alert('Draw a bbox first (or press X if no diver).'); return; }}
  fetch('/save', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{frame_idx: IDX, visibility: vis, bbox: bbox}})
  }}).then(r => r.json()).then(d => {{
    document.getElementById('status').textContent = d.message;
    document.getElementById('progress').textContent = d.done + '/' + TOTAL + ' frames annotated';
    if (d.ok) setTimeout(() => nav(1), 300);
  }});
}}

function nav(delta) {{
  const n = IDX + delta;
  if (n < 0 || n >= TOTAL) return;
  window.location.href = '/?idx=' + n;
}}

document.addEventListener('keydown', function(e) {{
  if (e.target.tagName === 'INPUT') return;
  if (e.key === 's' || e.key === 'S') save('visible');
  if (e.key === 'x' || e.key === 'X') save('not_visible');
  if (e.key === 'a' || e.key === 'ArrowLeft')  nav(-1);
  if (e.key === 'd' || e.key === 'ArrowRight') nav(1);
}});

// Auto-sync on load
window.addEventListener('load', function() {{ setTimeout(syncCanvas, 10); }});
</script>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass  # silence

    def do_GET(self):
        p = urlparse(self.path)
        if p.path == '/':
            qs  = parse_qs(p.query)
            idx = int(qs.get('idx', ['0'])[0])
            self._serve_page(idx)
        elif p.path == '/favicon.ico':
            self.send_response(204); self.end_headers()
        else:
            self.send_response(404); self.end_headers()

    def _serve_page(self, idx):
        manifest = load_manifest()
        frames   = manifest['frames']
        idx      = max(0, min(idx, len(frames)-1))
        fr       = frames[idx]
        total    = len(frames)
        done     = sum(1 for f in frames
                       if f.get('annotation') and f['annotation'].get('state') == 'HUMAN_REVIEWED')

        ann   = fr.get('annotation') or {}
        phase = fr.get('phase', '')
        dive  = fr.get('dive_id', '?')
        rank  = fr.get('source_failure_rank', '?')
        off   = fr.get('offset_from_gt', 0)
        fi    = fr.get('frame_index', '?')
        reason = fr.get('reason', '')
        hints  = fr.get('d4_hints_at_conf005', [])
        state  = ann.get('state', '')
        b64    = img_b64(fr['frame_file'])

        saved_color = '#4a4' if state == 'HUMAN_REVIEWED' else '#a44'
        saved_str   = (f"✓ Saved: {ann.get('visibility','?')}"
                       if state == 'HUMAN_REVIEWED' else "◯ Not saved yet")

        purpose  = f"dive {dive} · {phase.replace('_',' ')} · D4 rank={rank} · offset={off:+d}"
        meta     = (f"<b>Frame {idx+1}/{total}</b><br>"
                    f"Dive {dive} · {phase} · fi={fi}<br>"
                    f"Reason: {reason}<br>D4 floor rank: {rank}<br>"
                    f"<span style='color:{saved_color}'>{saved_str}</span>")
        d4hint   = (f"D4 fires <b>{len(hints)}</b> box(es) at conf≥0.05 — orange = suggestions, verify carefully"
                    if hints else "<b>D4: no candidate at conf≥0.05</b> — look carefully for a diver!")
        hint_dis = '' if hints else 'disabled'

        html = PAGE.format(
            css=CSS,
            idx1=idx+1, idx=idx, total=total, done=done,
            b64=b64,
            purpose=purpose, meta=meta,
            d4hint=d4hint,
            hints_json=json.dumps(hints),
            hint_dis=hint_dis,
            saved_str=saved_str,
        )
        data = html.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if self.path != '/save':
            self.send_response(404); self.end_headers(); return
        n    = int(self.headers['Content-Length'])
        body = json.loads(self.rfile.read(n))
        manifest = load_manifest()
        idx  = body['frame_idx']
        vis  = body['visibility']
        bbox = body.get('bbox')
        manifest['frames'][idx]['annotation'] = {
            'state': 'HUMAN_REVIEWED',
            'visibility': vis,
            'bbox': [round(x, 4) for x in bbox] if bbox else None,
            'annotator': 'maxime',
            'annotated_at': datetime.datetime.utcnow().isoformat() + '+00:00',
        }
        save_manifest(manifest)
        done  = sum(1 for f in manifest['frames']
                    if f.get('annotation') and f['annotation'].get('state') == 'HUMAN_REVIEWED')
        total = len(manifest['frames'])
        resp  = {'ok': True, 'done': done, 'message': f"Saved — {done}/{total} done"}
        data  = json.dumps(resp).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == '__main__':
    manifest = load_manifest()
    done  = sum(1 for f in manifest['frames']
                if f.get('annotation') and f['annotation'].get('state') == 'HUMAN_REVIEWED')
    total = len(manifest['frames'])
    print(f"D5 Annotation server v2 — http://192.168.1.57:{PORT}")
    print(f"Progress: {done}/{total} annotated")
    print("Ctrl+C to stop")
    HTTPServer(('0.0.0.0', PORT), Handler).serve_forever()
