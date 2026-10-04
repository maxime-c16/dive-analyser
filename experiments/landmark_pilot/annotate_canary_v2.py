#!/usr/bin/env python3
"""Canary annotation tool V2 — PTS-correct frame selection.

Serves a local web UI on port 8766 for PTS-correct temporal annotation
of a single canary video (IMG_1937.mov — 1m springboard, hurdle).

Mandatory landmarks (T / A / W):
  T — takeoff   : final departure into free flight
  A — apex      : highest point of trajectory
  W — water_contact : first body contact with water

Diagnostic landmarks (optional, H / B):
  H — hurdle_onset       : first horizontal movement in hurdle/approach phase
  B — board_recontact    : board loading / return to board after hurdle

PTS-correctness: frame_pts is read from the source video via ffprobe.
video.currentTime is mapped to a frame using bisect on the PTS array.
The stored timestamp is the exact PTS of the selected frame.

Usage (on Mac, in any directory):
    python3 annotate_canary_v2.py /Users/maximecauchy/Downloads/IMG_1937.mov

Output:
    highres_canary_v2_annotation.json (written in current directory)

Keyboard shortcuts:
    Space      — play / pause
    ← / →      — step 1 frame  (hold Shift for 5 frames)
    T          — mark takeoff at current frame
    A          — mark apex at current frame
    W          — mark water_contact at current frame
    H          — mark hurdle_onset at current frame (optional)
    B          — mark board_recontact at current frame (optional)
    S          — save / write JSON output
    Z          — clear last-modified landmark
"""

import argparse
import bisect
import hashlib
import http.server
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import webbrowser
from datetime import datetime, timezone

PORT = 8766
OUTPUT_FILENAME = "highres_canary_v2_annotation.json"
ANNOTATION_SCHEMA_VERSION = "v2_canary_pts_correct"
ANNOTATOR = "maxime@qwokka.fr"

LANDMARK_KEYS = ["takeoff", "apex", "water_contact", "hurdle_onset", "board_recontact"]
MANDATORY = {"takeoff", "apex", "water_contact"}
DIAGNOSTIC = {"hurdle_onset", "board_recontact"}
LANDMARK_LABEL = {
    "takeoff": "Takeoff (T) — final departure into free flight",
    "apex": "Apex (A) — highest point of trajectory",
    "water_contact": "Water Contact (W) — first body contact with water",
    "hurdle_onset": "Hurdle Onset (H) — optional diagnostic",
    "board_recontact": "Board Recontact (B) — optional diagnostic",
}


def find_ffprobe():
    for candidate in [
        "ffprobe",
        "/opt/homebrew/bin/ffprobe",
        "/usr/local/bin/ffprobe",
        "/Users/Shared/services/data/diveanalyzer/bin/ffprobe",
    ]:
        try:
            r = subprocess.run([candidate, "-version"], capture_output=True, timeout=5)
            if r.returncode == 0:
                return candidate
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    raise RuntimeError("ffprobe not found. Install via Homebrew: brew install ffmpeg")


def find_ffmpeg():
    for candidate in [
        "ffmpeg",
        "/opt/homebrew/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
        "/Users/Shared/services/data/diveanalyzer/bin/ffmpeg",
    ]:
        try:
            r = subprocess.run([candidate, "-version"], capture_output=True, timeout=5)
            if r.returncode == 0:
                return candidate
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    raise RuntimeError("ffmpeg not found. Install via Homebrew: brew install ffmpeg")


def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_pts(video_path: pathlib.Path, ffprobe_bin: str) -> list[float]:
    """Extract all decoded video frame PTS from the source video."""
    print(f"Extracting PTS timestamps from {video_path} ...", flush=True)
    data = json.loads(subprocess.check_output([
        ffprobe_bin, "-v", "error", "-select_streams", "v:0", "-show_frames",
        "-show_entries", "frame=best_effort_timestamp_time", "-of", "json",
        str(video_path)
    ], timeout=120))
    times = [float(f["best_effort_timestamp_time"]) for f in data["frames"]]
    if not times:
        raise ValueError("No frames found in video")
    if any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError("Non-monotonic PTS — cannot use for annotation")
    print(f"  {len(times)} frames, PTS range: {times[0]:.6f} – {times[-1]:.6f} s", flush=True)
    return times


def prepare_preview(source: pathlib.Path, ffmpeg_bin: str, tmp_dir: str) -> pathlib.Path:
    """Transcode source to browser-compatible H.264 (auto-rotated, 720p height)."""
    preview = pathlib.Path(tmp_dir) / "canary_preview.mp4"
    if preview.exists():
        print("Preview already exists, reusing.", flush=True)
        return preview
    print("Transcoding to browser-compatible H.264 preview (720p height) ...", flush=True)
    subprocess.run([
        ffmpeg_bin, "-y", "-i", str(source),
        "-vf", "scale=-2:720",
        "-c:v", "libx264", "-crf", "22", "-preset", "fast",
        "-an", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(preview)
    ], check=True, capture_output=True)
    print(f"  Preview: {preview}", flush=True)
    return preview


# ---------------------------------------------------------------------------
# Global shared state (protected by lock)
# ---------------------------------------------------------------------------
_lock = threading.Lock()
_landmarks: dict[str, dict | None] = {k: None for k in LANDMARK_KEYS}
_pts_times: list[float] = []
_source_info: dict = {}
_preview_path: pathlib.Path | None = None
_output_path: pathlib.Path | None = None


def _build_html() -> str:
    lm_html = ""
    for k in LANDMARK_KEYS:
        cls = "mandatory" if k in MANDATORY else "diagnostic"
        lm_html += f'<div class="lm-row {cls}" id="lm-{k}"><span class="lm-key">{LANDMARK_LABEL[k]}</span><span class="lm-val" id="lm-val-{k}">—</span><button onclick="clearLandmark(\'{k}\')" title="Clear">✕</button></div>\n'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Canary Annotator V2 — PTS-correct</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, sans-serif; background: #111; color: #eee; display: flex; flex-direction: column; height: 100vh; }}
header {{ padding: 8px 16px; background: #1a1a2e; display: flex; align-items: center; gap: 16px; flex-shrink: 0; }}
header h1 {{ font-size: 14px; font-weight: 600; color: #a0c4ff; }}
#status {{ font-size: 12px; color: #888; margin-left: auto; }}
main {{ display: flex; flex: 1; min-height: 0; gap: 12px; padding: 12px; }}
#video-col {{ flex: 1; display: flex; flex-direction: column; gap: 8px; min-width: 0; }}
video {{ width: 100%; max-height: calc(100vh - 200px); object-fit: contain; background: #000; border-radius: 6px; }}
#frame-info {{ font-family: monospace; font-size: 13px; color: #aaa; text-align: center; }}
#controls {{ display: flex; gap: 8px; justify-content: center; flex-wrap: wrap; }}
button.ctrl {{ background: #2a2a4a; border: 1px solid #444; color: #eee; padding: 4px 12px; border-radius: 4px; cursor: pointer; font-size: 12px; }}
button.ctrl:hover {{ background: #3a3a6a; }}
#panel {{ width: 340px; flex-shrink: 0; display: flex; flex-direction: column; gap: 8px; }}
.lm-row {{ padding: 10px 12px; border-radius: 6px; border: 1px solid #333; display: flex; align-items: center; gap: 8px; }}
.lm-row.mandatory {{ border-color: #4a6fa5; background: #0d1b2a; }}
.lm-row.diagnostic {{ border-color: #444; background: #1a1a1a; }}
.lm-row.set {{ border-color: #4caf50 !important; background: #0a2010 !important; }}
.lm-key {{ font-size: 11px; flex: 1; line-height: 1.3; }}
.lm-val {{ font-family: monospace; font-size: 13px; color: #4caf50; min-width: 80px; text-align: right; }}
button.lm-clear {{ background: none; border: none; color: #666; cursor: pointer; font-size: 14px; padding: 2px 4px; }}
button.lm-clear:hover {{ color: #f44; }}
#save-btn {{ margin-top: 8px; padding: 12px; background: #1a5c3a; border: 1px solid #2e7d52; color: #eee; border-radius: 6px; cursor: pointer; font-size: 14px; font-weight: 600; }}
#save-btn:hover {{ background: #2e7d52; }}
#save-btn:disabled {{ opacity: 0.5; cursor: not-allowed; }}
#shortcuts {{ font-size: 11px; color: #666; line-height: 1.8; padding: 10px 12px; background: #181818; border-radius: 6px; }}
#shortcuts kbd {{ background: #2a2a2a; border: 1px solid #444; border-radius: 3px; padding: 1px 5px; font-size: 10px; }}
</style>
</head>
<body>
<header>
  <h1>🎬 Canary Annotator V2 — PTS-correct</h1>
  <span id="status">Loading…</span>
</header>
<main>
  <div id="video-col">
    <video id="vid" controls preload="auto" src="/video"></video>
    <div id="frame-info">Frame — / — | PTS: —</div>
    <div id="controls">
      <button class="ctrl" onclick="stepFrame(-5)">⏮ −5</button>
      <button class="ctrl" onclick="stepFrame(-1)">◀ −1</button>
      <button class="ctrl" onclick="vid.paused?vid.play():vid.pause()">⏯ Play/Pause</button>
      <button class="ctrl" onclick="stepFrame(1)">+1 ▶</button>
      <button class="ctrl" onclick="stepFrame(5)">+5 ⏭</button>
    </div>
  </div>
  <div id="panel">
    <div style="font-size:11px;color:#888;padding:0 4px;">Apparatus: 1m springboard · hurdle · initial static</div>
    {lm_html}
    <button id="save-btn" onclick="saveLandmarks()">💾 Save (S) — Write JSON</button>
    <div id="shortcuts">
      <strong style="color:#aaa">Shortcuts</strong><br>
      <kbd>Space</kbd> play/pause &nbsp; <kbd>←</kbd><kbd>→</kbd> step 1 frame<br>
      <kbd>Shift+←</kbd><kbd>Shift+→</kbd> step 5 frames<br>
      <kbd>T</kbd> takeoff &nbsp; <kbd>A</kbd> apex &nbsp; <kbd>W</kbd> water contact<br>
      <kbd>H</kbd> hurdle onset (opt) &nbsp; <kbd>B</kbd> board recontact (opt)<br>
      <kbd>Z</kbd> clear last marked &nbsp; <kbd>S</kbd> save
    </div>
  </div>
</main>
<script>
const vid = document.getElementById('vid');
const frameInfo = document.getElementById('frame-info');
const statusEl = document.getElementById('status');
let framePts = [];
let lastMarked = null;

async function init() {{
  const r = await fetch('/api/state');
  const data = await r.json();
  framePts = data.pts_times;
  statusEl.textContent = `${{data.source_filename}} · ${{framePts.length}} frames · ${{data.duration_s.toFixed(3)}}s`;
  // Restore any existing landmarks
  for (const [k, v] of Object.entries(data.landmarks)) {{
    if (v) setLandmarkDisplay(k, v.frame_index, v.pts_seconds);
  }}
}}

function currentFrame() {{
  const t = vid.currentTime;
  if (!framePts.length) return {{frame: 0, pts: 0}};
  // bisect_right: find last frame with pts <= t
  let lo = 0, hi = framePts.length - 1;
  while (lo < hi) {{
    const mid = Math.ceil((lo + hi) / 2);
    if (framePts[mid] <= t) lo = mid; else hi = mid - 1;
  }}
  return {{frame: lo, pts: framePts[lo]}};
}}

vid.addEventListener('timeupdate', () => {{
  const {{frame, pts}} = currentFrame();
  frameInfo.textContent = `Frame ${{frame + 1}} / ${{framePts.length}} | PTS: ${{pts.toFixed(6)}} s`;
}});

function stepFrame(delta) {{
  const {{frame}} = currentFrame();
  const target = Math.max(0, Math.min(framePts.length - 1, frame + delta));
  vid.currentTime = framePts[target];
}}

const KEY_TO_LANDMARK = {{t:'takeoff', a:'apex', w:'water_contact', h:'hurdle_onset', b:'board_recontact'}};

document.addEventListener('keydown', e => {{
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'BUTTON') return;
  const k = e.key.toLowerCase();
  if (k === ' ') {{ e.preventDefault(); vid.paused ? vid.play() : vid.pause(); }}
  else if (e.key === 'ArrowLeft') {{ e.preventDefault(); stepFrame(e.shiftKey ? -5 : -1); }}
  else if (e.key === 'ArrowRight') {{ e.preventDefault(); stepFrame(e.shiftKey ? 5 : 1); }}
  else if (k === 's') {{ e.preventDefault(); saveLandmarks(); }}
  else if (k === 'z') {{ if (lastMarked) {{ clearLandmark(lastMarked); lastMarked = null; }} }}
  else if (KEY_TO_LANDMARK[k]) {{ e.preventDefault(); markLandmark(KEY_TO_LANDMARK[k]); }}
}});

function markLandmark(key) {{
  const {{frame, pts}} = currentFrame();
  setLandmarkDisplay(key, frame, pts);
  lastMarked = key;
  fetch('/api/set_landmark', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{key, frame_index: frame, pts_seconds: pts}})
  }});
}}

function setLandmarkDisplay(key, frame, pts) {{
  const valEl = document.getElementById(`lm-val-${{key}}`);
  const rowEl = document.getElementById(`lm-${{key}}`);
  if (valEl) valEl.textContent = `fr.${{frame}} / ${{pts.toFixed(4)}}s`;
  if (rowEl) rowEl.classList.add('set');
}}

function clearLandmark(key) {{
  const valEl = document.getElementById(`lm-val-${{key}}`);
  const rowEl = document.getElementById(`lm-${{key}}`);
  if (valEl) valEl.textContent = '—';
  if (rowEl) rowEl.classList.remove('set');
  fetch('/api/clear_landmark', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{key}})
  }});
}}

async function saveLandmarks() {{
  const btn = document.getElementById('save-btn');
  btn.disabled = true;
  btn.textContent = 'Saving…';
  const r = await fetch('/api/save', {{method: 'POST'}});
  const result = await r.json();
  if (result.ok) {{
    btn.textContent = `✓ Saved → ${{result.path}}`;
    btn.style.background = '#1a3a6a';
  }} else {{
    btn.textContent = `✗ Error: ${{result.error}}`;
    btn.style.background = '#5a1a1a';
    btn.disabled = false;
  }}
}}

init();
</script>
</body>
</html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # suppress per-request logs

    def send_json(self, data, code=200):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", ""):
            html = _build_html().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)
        elif path == "/api/state":
            with _lock:
                self.send_json({
                    "source_filename": _source_info.get("filename", ""),
                    "duration_s": _source_info.get("duration_s", 0),
                    "n_frames": len(_pts_times),
                    "pts_times": _pts_times,
                    "landmarks": {k: v for k, v in _landmarks.items()},
                })
        elif path == "/video":
            self._stream_video()
        else:
            self.send_response(404); self.end_headers()

    def _stream_video(self):
        if _preview_path is None or not _preview_path.exists():
            self.send_response(404); self.end_headers(); return
        size = _preview_path.stat().st_size
        range_h = self.headers.get("Range")
        start, end = 0, size - 1
        code = 200
        if range_h:
            import re
            m = re.match(r"bytes=(\d+)-(\d*)", range_h)
            if m:
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else size - 1
                end = min(end, size - 1)
                code = 206
        length = end - start + 1
        self.send_response(code)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with open(_preview_path, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(65536, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}

        if path == "/api/set_landmark":
            with _lock:
                _landmarks[body["key"]] = {
                    "frame_index": body["frame_index"],
                    "pts_seconds": body["pts_seconds"],
                }
            self.send_json({"ok": True})

        elif path == "/api/clear_landmark":
            with _lock:
                _landmarks[body["key"]] = None
            self.send_json({"ok": True})

        elif path == "/api/save":
            with _lock:
                lms = {k: v for k, v in _landmarks.items()}
                info = dict(_source_info)
            missing = [k for k in MANDATORY if lms.get(k) is None]
            if missing:
                self.send_json({"ok": False, "error": f"Mandatory landmarks not set: {missing}"})
                return
            doc = {
                "label": "HIGHRES_CANARY_V2_EXACT_ANNOTATION",
                "annotation_schema_version": ANNOTATION_SCHEMA_VERSION,
                "annotator": ANNOTATOR,
                "annotation_timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "source": info,
                "apparatus": "springboard",
                "height_m": 1,
                "hurdle": True,
                "initial_static": True,
                "landmarks": {
                    k: {
                        "state": ("HUMAN_SET" if v is not None else
                                  ("NOT_SET_OPTIONAL" if k in DIAGNOSTIC else "MISSING_MANDATORY")),
                        "frame_index": v["frame_index"] if v else None,
                        "frame_pts_seconds": v["pts_seconds"] if v else None,
                        "category": "mandatory" if k in MANDATORY else "diagnostic_optional",
                    }
                    for k, v in lms.items()
                },
                "previous_approximate_annotation": {
                    "takeoff_s": 3.5,
                    "apex_s": 4.2,
                    "water_contact_s": 4.9,
                    "method": "direct_visual_inspection",
                    "annotation_date": "2026-09-06",
                    "status": "SUPERSEDED_BY_THIS_DOCUMENT",
                    "reason": "Not performed with PTS-correct tool; apparatus was incorrectly characterized",
                },
            }
            try:
                out = _output_path
                with open(out, "w") as f:
                    json.dump(doc, f, indent=2)
                self.send_json({"ok": True, "path": str(out)})
            except Exception as e:
                self.send_json({"ok": False, "error": str(e)})
        else:
            self.send_response(404); self.end_headers()


def main():
    parser = argparse.ArgumentParser(description="Canary annotation tool V2")
    parser.add_argument("video", help="Path to source video (IMG_1937.mov)")
    parser.add_argument("--output", default=OUTPUT_FILENAME, help="Output JSON filename")
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()

    source = pathlib.Path(args.video).resolve()
    if not source.exists():
        print(f"Error: video not found: {source}", file=sys.stderr)
        sys.exit(1)

    ffprobe_bin = find_ffprobe()
    ffmpeg_bin = find_ffmpeg()

    # SHA256 of source
    print(f"Computing source SHA256 (may take a moment) …", flush=True)
    source_sha256 = sha256_file(source)
    print(f"  SHA256: {source_sha256}", flush=True)

    # PTS extraction
    pts = extract_pts(source, ffprobe_bin)

    # Transcode preview
    tmp_dir = tempfile.mkdtemp(prefix="canary_annotate_")
    preview = prepare_preview(source, ffmpeg_bin, tmp_dir)

    # Set globals
    global _pts_times, _source_info, _preview_path, _output_path
    _pts_times = pts
    _source_info = {
        "filename": source.name,
        "path": str(source),
        "sha256": source_sha256,
        "duration_s": pts[-1] + (pts[-1] - pts[-2]),  # approx
        "n_frames": len(pts),
        "pts_range": [pts[0], pts[-1]],
    }
    _preview_path = preview
    _output_path = pathlib.Path(args.output).resolve()

    server = http.server.HTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://localhost:{args.port}"
    print(f"\n{'='*60}", flush=True)
    print(f"  Canary Annotator V2 — PTS-correct", flush=True)
    print(f"  Source : {source.name}", flush=True)
    print(f"  Frames : {len(pts)}", flush=True)
    print(f"  Output : {_output_path}", flush=True)
    print(f"  URL    : {url}", flush=True)
    print(f"{'='*60}\n", flush=True)
    print("Opening browser …", flush=True)
    threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.", flush=True)


if __name__ == "__main__":
    main()
