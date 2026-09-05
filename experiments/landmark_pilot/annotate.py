#!/usr/bin/env python3
"""Minimal landmark annotation / correction tool.

Serves a local web UI on port 8765 for reviewing and correcting Baseline-A
landmark proposals from the pilot run.

Usage (from server):
    cd ~/dive-analyser/experiments/landmark_pilot
    source venv/bin/activate
    python3 annotate.py

Then on Mac:
    ssh -i ~/.ssh/qwokka -L 8765:localhost:8765 mcauchy@192.168.1.57 -N &
    open http://localhost:8765
"""
import http.server
import json
import os
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path

import psycopg2
import psycopg2.extras

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).parent.parent.parent  # ~/dive-analyser
MEDIA_CACHE_ROOT = REPO_ROOT / "media" / "cache"
MANIFEST_PATH = REPO_ROOT / "docs" / "science" / "PILOT_MANIFEST_V1.json"
PIPELINE_KEY = "temporal_landmarks_baseline_a_v1"
WORKER_ID = "annotate_tool_v1"
PORT = 8765

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _get_db_password():
    pw = os.environ.get("DB_PASSWORD")
    if not pw:
        result = subprocess.check_output(
            ["grep", "^POSTGRES_PASSWORD", str(REPO_ROOT / ".env")]
        ).decode().strip().split("=", 1)
        pw = result[1].strip() if len(result) > 1 else ""
    return pw


def _connect():
    pw = _get_db_password()
    return psycopg2.connect(
        host="localhost", port=5433, dbname="diving_analyzer_db",
        user="diving", password=pw,
        connect_timeout=5,
    )


# ---------------------------------------------------------------------------
# Load pilot manifest
# ---------------------------------------------------------------------------

def _load_manifest():
    with open(MANIFEST_PATH) as f:
        data = json.load(f)
    return {d["dive_id"]: d for d in data["dives"]}


MANIFEST = _load_manifest()


def _proxy_path(media_key: str) -> Path | None:
    """Return the proxy_360p file path for a media_key, or None if missing."""
    p = MEDIA_CACHE_ROOT / "proxy_360p" / media_key[:2] / media_key[2:4] / f"{media_key}.mp4"
    return p if p.exists() else None


# ---------------------------------------------------------------------------
# DB queries
# ---------------------------------------------------------------------------

def _latest_run_for_dive(cur, dive_id: int):
    cur.execute("""
        SELECT r.id, r.status, r.created_at
        FROM analysis_runs r
        WHERE r.dive_id = %s
          AND r.pipeline_key = %s
          AND r.status NOT IN ('failed', 'cancelled', 'superseded')
        ORDER BY r.created_at DESC
        LIMIT 1
    """, (dive_id, PIPELINE_KEY))
    return cur.fetchone()


def _landmarks_for_run(cur, run_id):
    cur.execute("""
        SELECT landmark_key, frame_index, timestamp_seconds,
               confidence, applicability, source,
               algorithm_key, algorithm_version
        FROM analysis_landmarks
        WHERE run_id = %s
        ORDER BY
            CASE landmark_key
                WHEN 'takeoff'       THEN 1
                WHEN 'apex'          THEN 2
                WHEN 'water_contact' THEN 3
                ELSE 4
            END
    """, (run_id,))
    rows = cur.fetchall()
    result = {}
    for row in rows:
        result[row[0]] = {
            "landmark_key": row[0],
            "frame_index": row[1],
            "timestamp_seconds": float(row[2]) if row[2] is not None else None,
            "confidence": float(row[3]) if row[3] is not None else None,
            "applicability": row[4],
            "source": row[5],
            "algorithm_key": row[6],
            "algorithm_version": row[7],
        }
    return result


def _get_all_pilot_data():
    conn = _connect()
    try:
        with conn.cursor() as cur:
            dives = []
            for dive_id, info in MANIFEST.items():
                run_row = _latest_run_for_dive(cur, dive_id)
                proxy = _proxy_path(info["media_key"])
                entry = {
                    "dive_id": dive_id,
                    "dive_code": info.get("dive_code", ""),
                    "height": info.get("height", ""),
                    "session_date": info.get("session_date", ""),
                    "group": info.get("group", ""),
                    "proxy_available": proxy is not None,
                    "run_uuid": None,
                    "run_status": None,
                    "landmarks": {},
                    "ordering_valid": False,
                }
                if run_row:
                    entry["run_uuid"] = str(run_row[0])
                    entry["run_status"] = run_row[1]
                    entry["landmarks"] = _landmarks_for_run(cur, run_row[0])
                    lm = entry["landmarks"]
                    t = lm.get("takeoff", {}).get("frame_index")
                    a = lm.get("apex", {}).get("frame_index")
                    w = lm.get("water_contact", {}).get("frame_index")
                    if t is not None and a is not None and w is not None:
                        entry["ordering_valid"] = (t < a < w)
                dives.append(entry)
            dives.sort(key=lambda d: d["group"])
            return dives
    finally:
        conn.close()


def _get_dive_data(dive_id: int):
    conn = _connect()
    try:
        with conn.cursor() as cur:
            run_row = _latest_run_for_dive(cur, dive_id)
            if not run_row:
                return None
            run_uuid = str(run_row[0])
            landmarks = _landmarks_for_run(cur, run_row[0])
            info = MANIFEST.get(dive_id, {})
            proxy = _proxy_path(info.get("media_key", ""))
            return {
                "dive_id": dive_id,
                "dive_code": info.get("dive_code", ""),
                "height": info.get("height", ""),
                "session_date": info.get("session_date", ""),
                "run_uuid": run_uuid,
                "proxy_available": proxy is not None,
                "landmarks": landmarks,
            }
    finally:
        conn.close()


def _save_landmarks(dive_id: int, corrections: dict, not_applicable_keys: list):
    """
    corrections: dict landmark_key -> {frame_index, timestamp_seconds}
    not_applicable_keys: list of landmark_keys to mark NOT_APPLICABLE
    Inserts new HUMAN rows; existing rows are deleted for those keys first.
    """
    conn = _connect()
    try:
        with conn.cursor() as cur:
            run_row = _latest_run_for_dive(cur, dive_id)
            if not run_row:
                return {"error": "no run found for dive"}
            run_id = run_row[0]

            for lk in list(corrections.keys()) + list(not_applicable_keys):
                cur.execute(
                    "DELETE FROM analysis_landmarks WHERE run_id=%s AND landmark_key=%s",
                    (run_id, lk)
                )

            for lk, vals in corrections.items():
                fi = vals.get("frame_index")
                ts = vals.get("timestamp_seconds")
                cur.execute("""
                    INSERT INTO analysis_landmarks
                        (run_id, landmark_key, frame_index, timestamp_seconds,
                         confidence, applicability, source,
                         algorithm_key, algorithm_version, uncertainty_window_frames)
                    VALUES (%s, %s, %s, %s, 1.0, 'APPLICABLE', 'HUMAN',
                            'annotate_tool', 'v1', 0)
                """, (run_id, lk, fi, ts))

            for lk in not_applicable_keys:
                cur.execute("""
                    INSERT INTO analysis_landmarks
                        (run_id, landmark_key, frame_index, timestamp_seconds,
                         confidence, applicability, source,
                         algorithm_key, algorithm_version, uncertainty_window_frames)
                    VALUES (%s, %s, NULL, NULL, 1.0, 'NOT_APPLICABLE', 'HUMAN',
                            'annotate_tool', 'v1', 0)
                """, (run_id, lk))

        conn.commit()
        return {"ok": True}
    except Exception as e:
        conn.rollback()
        return {"error": str(e)}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# HTML page
# ---------------------------------------------------------------------------

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Landmark Annotator — Baseline A Pilot</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,sans-serif;background:#111;color:#eee;display:flex;height:100vh;overflow:hidden}
#sidebar{width:260px;min-width:200px;overflow-y:auto;background:#1a1a1a;border-right:1px solid #333;padding:8px}
#sidebar h2{font-size:13px;color:#888;padding:4px 0 8px;text-transform:uppercase;letter-spacing:.05em}
.dive-item{padding:6px 8px;border-radius:5px;cursor:pointer;font-size:13px;display:flex;align-items:center;gap:6px;margin-bottom:2px}
.dive-item:hover{background:#2a2a2a}
.dive-item.active{background:#2d4d6e}
.badge{font-size:11px;padding:2px 5px;border-radius:3px;font-weight:600}
.badge-ok{background:#1a4a1a;color:#4f4}
.badge-uncertain{background:#4a2200;color:#f84}
.badge-na{background:#333;color:#888}
.badge-human{background:#1a3a4a;color:#4af}
#main{flex:1;display:flex;flex-direction:column;overflow:hidden}
#toolbar{background:#1e1e1e;border-bottom:1px solid #333;padding:8px 14px;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
#toolbar h1{font-size:15px;margin-right:auto}
#toolbar button{background:#2a2a2a;border:1px solid #444;color:#eee;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:13px}
#toolbar button:hover{background:#3a3a3a}
#toolbar button.primary{background:#1a5a9e;border-color:#2a7ad0;color:#fff}
#toolbar button.danger{background:#6e1a1a;border-color:#c02020}
#content{display:flex;flex:1;overflow:hidden}
#video-panel{flex:1;display:flex;flex-direction:column;padding:10px;gap:8px;overflow-y:auto}
video{width:100%;border-radius:6px;background:#000;max-height:62vh;object-fit:contain}
#frame-info{font-size:13px;color:#aaa;font-family:monospace}
#controls{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
#controls button{background:#2a2a2a;border:1px solid #444;color:#eee;padding:5px 11px;border-radius:4px;cursor:pointer;font-size:13px}
#controls button:hover{background:#3a3a3a}
.lm-btn{border-left:3px solid transparent!important}
.lm-btn.takeoff{border-left-color:#f90!important}
.lm-btn.apex{border-left-color:#4af!important}
.lm-btn.water_contact{border-left-color:#4f8!important}
#lm-panel{width:310px;min-width:260px;background:#1a1a1a;border-left:1px solid #333;padding:12px;overflow-y:auto}
#lm-panel h2{font-size:13px;color:#888;text-transform:uppercase;letter-spacing:.05em;margin-bottom:10px}
.lm-row{margin-bottom:14px;padding:10px;background:#222;border-radius:6px}
.lm-row h3{font-size:13px;font-weight:600;margin-bottom:6px;display:flex;align-items:center;gap:6px}
.lm-dot{width:10px;height:10px;border-radius:50%;display:inline-block}
.dot-takeoff{background:#f90}
.dot-apex{background:#4af}
.dot-water_contact{background:#4f8}
.lm-fields{font-size:12px;color:#bbb;line-height:1.8;font-family:monospace}
.lm-fields input{width:80px;background:#333;border:1px solid #555;color:#eee;padding:2px 5px;border-radius:3px;font-size:12px;font-family:monospace}
.lm-badge{font-size:11px;padding:2px 5px;border-radius:3px;display:inline-block;margin-top:4px}
.lm-badge.APPLICABLE{background:#1a4a1a;color:#4f4}
.lm-badge.UNCERTAIN{background:#4a2200;color:#f84}
.lm-badge.NOT_APPLICABLE{background:#333;color:#888}
.lm-badge.HUMAN{background:#1a3a4a;color:#4af}
.lm-set-btn{font-size:11px;padding:3px 8px;background:#2d4d6e;border:1px solid #3a6a9e;color:#cdf;border-radius:3px;cursor:pointer;margin-top:4px}
.lm-na-btn{font-size:11px;padding:3px 8px;background:#3a1a1a;border:1px solid #6a3030;color:#fcc;border-radius:3px;cursor:pointer;margin-top:4px}
#save-bar{padding:10px 12px;border-top:1px solid #333;background:#181818}
#save-bar button{width:100%;padding:8px;font-size:14px;border-radius:5px;cursor:pointer;border:none}
#save-btn{background:#1a5a1a;color:#fff}
#save-btn:hover{background:#256a25}
#status-msg{font-size:12px;color:#8f8;margin-top:6px;text-align:center;min-height:16px}
.speed-btn{font-size:11px!important;padding:3px 7px!important}
</style>
</head>
<body>
<div id="sidebar">
  <h2>Pilot Dives</h2>
  <div id="dive-list"></div>
</div>
<div id="main">
  <div id="toolbar">
    <h1 id="dive-title">Select a dive</h1>
    <button onclick="prevDive()">← Prev</button>
    <button onclick="nextDive()">Next →</button>
  </div>
  <div id="content">
    <div id="video-panel">
      <video id="vid" controls preload="auto"></video>
      <div id="frame-info">No dive selected</div>
      <div id="controls">
        <button onclick="stepFrame(-10)">-10f</button>
        <button onclick="stepFrame(-1)">-1f</button>
        <button onclick="togglePlay()">▶ Play</button>
        <button onclick="stepFrame(1)">+1f</button>
        <button onclick="stepFrame(10)">+10f</button>
        <span style="color:#666;font-size:12px">|</span>
        <button class="speed-btn" onclick="setSpeed(0.1)">0.1×</button>
        <button class="speed-btn" onclick="setSpeed(0.25)">0.25×</button>
        <button class="speed-btn" onclick="setSpeed(0.5)">0.5×</button>
        <button class="speed-btn" onclick="setSpeed(1.0)">1×</button>
        <span style="color:#666;font-size:12px">|</span>
        <button class="lm-btn takeoff" onclick="setLandmark('takeoff')">Set Takeoff [T]</button>
        <button class="lm-btn apex" onclick="setLandmark('apex')">Set Apex [A]</button>
        <button class="lm-btn water_contact" onclick="setLandmark('water_contact')">Set Water [W]</button>
      </div>
    </div>
    <div id="lm-panel">
      <h2>Landmarks</h2>
      <div id="lm-rows"></div>
      <div id="save-bar">
        <button id="save-btn" onclick="saveLandmarks()">💾 Save Corrections</button>
        <div id="status-msg"></div>
      </div>
    </div>
  </div>
</div>
<script>
let dives = [];
let currentDiveIdx = -1;
let fps = 30;
let pendingCorrections = {};  // landmark_key -> {frame_index, timestamp_seconds}
let notApplicableKeys = new Set();

const vid = document.getElementById('vid');
const frameInfo = document.getElementById('frame-info');
const lmRows = document.getElementById('lm-rows');
const statusMsg = document.getElementById('status-msg');

async function loadDives() {
  const r = await fetch('/api/dives');
  dives = await r.json();
  renderSidebar();
  if (dives.length > 0) selectDive(0);
}

function renderSidebar() {
  const el = document.getElementById('dive-list');
  el.innerHTML = '';
  dives.forEach((d, i) => {
    const div = document.createElement('div');
    div.className = 'dive-item' + (i === currentDiveIdx ? ' active' : '');
    div.onclick = () => selectDive(i);
    const hasHuman = Object.values(d.landmarks||{}).some(l => l.source === 'HUMAN');
    const allValid = d.ordering_valid;
    let badge = '';
    if (hasHuman) badge = '<span class="badge badge-human">✎</span>';
    else if (allValid) badge = '<span class="badge badge-ok">✓</span>';
    else badge = '<span class="badge badge-uncertain">!</span>';
    div.innerHTML = `${badge}<span>#${d.dive_id} ${d.dive_code} <small style="color:#777">${d.height}</small></span>`;
    el.appendChild(div);
  });
}

async function selectDive(idx) {
  currentDiveIdx = idx;
  pendingCorrections = {};
  notApplicableKeys = new Set();
  renderSidebar();

  const d = dives[idx];
  document.getElementById('dive-title').textContent =
    `#${d.dive_id} — ${d.dive_code} ${d.height} (${d.session_date})`;

  if (d.proxy_available) {
    vid.src = `/video/${d.dive_id}`;
    vid.load();
    // detect fps when metadata loads
    vid.onloadedmetadata = () => {
      fps = detectFps(d);
      updateFrameInfo();
    };
  } else {
    vid.src = '';
    frameInfo.textContent = 'No proxy video available';
  }

  renderLandmarks(d);
  statusMsg.textContent = '';
}

function detectFps(d) {
  // infer from known frames or default 60
  const lms = d.landmarks || {};
  return 60; // default; will be overridden if the video metadata provides it
}

vid.addEventListener('timeupdate', updateFrameInfo);
vid.addEventListener('seeked', updateFrameInfo);

function updateFrameInfo() {
  const t = vid.currentTime;
  const f = Math.round(t * fps);
  frameInfo.textContent = `Frame ~${f}  |  Time ${t.toFixed(4)}s  |  FPS assumed ${fps}`;
}

function currentFrame() {
  return Math.round(vid.currentTime * fps);
}

function stepFrame(n) {
  if (!fps) return;
  vid.pause();
  vid.currentTime = Math.max(0, vid.currentTime + n / fps);
}

function togglePlay() {
  if (vid.paused) vid.play(); else vid.pause();
}

function setSpeed(s) {
  vid.playbackRate = s;
}

function goToFrame(f) {
  vid.currentTime = f / fps;
}

function setLandmark(key) {
  const f = currentFrame();
  const ts = vid.currentTime;
  pendingCorrections[key] = {frame_index: f, timestamp_seconds: ts};
  notApplicableKeys.delete(key);
  renderLandmarks(dives[currentDiveIdx]);
  statusMsg.textContent = `Set ${key} → frame ${f} (unsaved)`;
  statusMsg.style.color = '#fa4';
}

function markNotApplicable(key) {
  notApplicableKeys.add(key);
  delete pendingCorrections[key];
  renderLandmarks(dives[currentDiveIdx]);
  statusMsg.textContent = `Marked ${key} NOT_APPLICABLE (unsaved)`;
  statusMsg.style.color = '#fa4';
}

function renderLandmarks(d) {
  const LM_KEYS = ['takeoff', 'apex', 'water_contact'];
  const COLORS = {takeoff:'#f90', apex:'#4af', water_contact:'#4f8'};
  const db = d.landmarks || {};
  lmRows.innerHTML = '';

  LM_KEYS.forEach(key => {
    const orig = db[key] || {};
    const pending = pendingCorrections[key];
    const isNa = notApplicableKeys.has(key);
    const display = isNa ? null : (pending || orig);

    const row = document.createElement('div');
    row.className = 'lm-row';

    const source = isNa ? 'HUMAN' : (pending ? 'HUMAN' : (orig.source || '—'));
    const applicability = isNa ? 'NOT_APPLICABLE' : (pending ? 'APPLICABLE' : (orig.applicability || '—'));
    const fi = display ? display.frame_index : null;
    const ts = display ? display.timestamp_seconds : null;
    const modified = isNa || !!pending;

    row.innerHTML = `
      <h3>
        <span class="lm-dot dot-${key}"></span>
        ${key.replace('_', ' ')}
        ${modified ? '<small style="color:#fa4">● unsaved</small>' : ''}
      </h3>
      <div class="lm-fields">
        Frame: <input type="number" id="fi-${key}" value="${fi !== null ? fi : ''}"
          onchange="manualEdit('${key}', 'frame_index', this.value)">
        &nbsp;Time: ${ts !== null ? ts.toFixed(3)+'s' : '—'}
        <br>
        <span class="lm-badge ${applicability}">${applicability}</span>
        <span class="lm-badge" style="background:#1c1c1c;color:#888">${source}</span>
        ${orig.confidence !== undefined && orig.confidence !== null ? `<span style="color:#777;font-size:11px"> conf:${orig.confidence.toFixed(2)}</span>` : ''}
        <br>
        <button class="lm-set-btn" onclick="setLandmark('${key}')">Set to current frame</button>
        ${fi !== null ? `<button class="lm-set-btn" onclick="goToFrame(${fi})" style="background:#333;border-color:#555;color:#ccc">Go to frame</button>` : ''}
        <button class="lm-na-btn" onclick="markNotApplicable('${key}')">NOT_APPLICABLE</button>
      </div>`;

    lmRows.appendChild(row);
  });
}

function manualEdit(key, field, value) {
  const f = parseInt(value);
  if (isNaN(f)) return;
  notApplicableKeys.delete(key);
  if (!pendingCorrections[key]) pendingCorrections[key] = {};
  pendingCorrections[key].frame_index = f;
  pendingCorrections[key].timestamp_seconds = f / fps;
  statusMsg.textContent = `Editing ${key} frame=${f} (unsaved)`;
  statusMsg.style.color = '#fa4';
}

async function saveLandmarks() {
  if (currentDiveIdx < 0) return;
  const d = dives[currentDiveIdx];
  if (Object.keys(pendingCorrections).length === 0 && notApplicableKeys.size === 0) {
    statusMsg.textContent = 'Nothing to save.';
    statusMsg.style.color = '#888';
    return;
  }
  const payload = {
    corrections: pendingCorrections,
    not_applicable: Array.from(notApplicableKeys),
  };
  const r = await fetch(`/api/landmarks/${d.dive_id}`, {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify(payload),
  });
  const result = await r.json();
  if (result.ok) {
    statusMsg.textContent = '✓ Saved successfully';
    statusMsg.style.color = '#4f4';
    pendingCorrections = {};
    notApplicableKeys = new Set();
    // refresh dive data
    const refresh = await fetch('/api/dives');
    dives = await refresh.json();
    renderSidebar();
    renderLandmarks(dives[currentDiveIdx]);
  } else {
    statusMsg.textContent = 'Error: ' + (result.error || 'unknown');
    statusMsg.style.color = '#f44';
  }
}

function prevDive() {
  if (currentDiveIdx > 0) selectDive(currentDiveIdx - 1);
}
function nextDive() {
  if (currentDiveIdx < dives.length - 1) selectDive(currentDiveIdx + 1);
}

document.addEventListener('keydown', e => {
  if (e.target.tagName === 'INPUT') return;
  if (e.key === 'ArrowLeft') stepFrame(e.shiftKey ? -10 : -1);
  else if (e.key === 'ArrowRight') stepFrame(e.shiftKey ? 10 : 1);
  else if (e.key === ' ') { e.preventDefault(); togglePlay(); }
  else if (e.key === 't' || e.key === 'T') setLandmark('takeoff');
  else if (e.key === 'a' || e.key === 'A') setLandmark('apex');
  else if (e.key === 'w' || e.key === 'W') setLandmark('water_contact');
  else if (e.key === 's' || e.key === 'S') saveLandmarks();
  else if (e.key === 'ArrowUp') prevDive();
  else if (e.key === 'ArrowDown') nextDive();
});

loadDives();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# HTTP request handler
# ---------------------------------------------------------------------------

class Handler(http.server.BaseHTTPRequestHandler):
    """Single-threaded request handler for the annotation tool."""

    def log_message(self, fmt, *args):
        pass  # silence default apache-style logs

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, html: str):
        body = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path

        if path == "/" or path == "":
            self.send_html(HTML_PAGE)
            return

        if path == "/api/dives":
            try:
                data = _get_all_pilot_data()
                self.send_json(data)
            except Exception as e:
                self.send_json({"error": str(e)}, 500)
            return

        m = re.match(r"^/api/landmarks/(\d+)$", path)
        if m and self.command == "GET":
            dive_id = int(m.group(1))
            try:
                data = _get_dive_data(dive_id)
                if data is None:
                    self.send_json({"error": "not found"}, 404)
                else:
                    self.send_json(data)
            except Exception as e:
                self.send_json({"error": str(e)}, 500)
            return

        m = re.match(r"^/video/(\d+)$", path)
        if m:
            dive_id = int(m.group(1))
            info = MANIFEST.get(dive_id)
            if not info:
                self.send_response(404); self.end_headers(); return
            video_path = _proxy_path(info["media_key"])
            if not video_path:
                self.send_response(404); self.end_headers(); return
            self._stream_file(video_path, "video/mp4")
            return

        self.send_response(404); self.end_headers()

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path

        m = re.match(r"^/api/landmarks/(\d+)$", path)
        if m:
            dive_id = int(m.group(1))
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                payload = json.loads(body)
                corrections = payload.get("corrections", {})
                not_applicable = payload.get("not_applicable", [])
                result = _save_landmarks(dive_id, corrections, not_applicable)
                self.send_json(result)
            except Exception as e:
                self.send_json({"error": str(e)}, 500)
            return

        self.send_response(404); self.end_headers()

    def _stream_file(self, path: Path, content_type: str):
        size = path.stat().st_size
        # Support partial content for seeking
        range_header = self.headers.get("Range")
        if range_header:
            m = re.match(r"bytes=(\d+)-(\d*)", range_header)
            if m:
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else size - 1
                end = min(end, size - 1)
                length = end - start + 1
                self.send_response(206)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(length))
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                with open(path, "rb") as f:
                    f.seek(start)
                    remaining = length
                    while remaining > 0:
                        chunk = f.read(min(65536, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
                return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(size))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        with open(path, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(f"Landmark Annotation Tool")
    print(f"  Loaded {len(MANIFEST)} dives from {MANIFEST_PATH.name}")
    print(f"  Listening on http://localhost:{PORT}")
    print(f"")
    print(f"  From Mac: ssh -i ~/.ssh/qwokka -L {PORT}:localhost:{PORT} mcauchy@192.168.1.57 -N")
    print(f"  Then open: http://localhost:{PORT}")
    print(f"")
    print(f"  Keyboard shortcuts (in browser):")
    print(f"    Space          — play/pause")
    print(f"    ← / →          — step 1 frame (Shift: 10 frames)")
    print(f"    ↑ / ↓          — prev/next dive")
    print(f"    T              — set takeoff to current frame")
    print(f"    A              — set apex to current frame")
    print(f"    W              — set water contact to current frame")
    print(f"    S              — save corrections")
    print(f"")
    server = http.server.HTTPServer(("127.0.0.1", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutdown.")
