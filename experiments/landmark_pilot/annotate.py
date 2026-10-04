#!/usr/bin/env python3
"""Landmark annotation / correction tool — v2.

Serves a local web UI on port 8765 for reviewing and correcting Baseline-A
landmark proposals from the pilot run.

v2 additions over v1:
  - All 20 pilot dives accessible (not only the 8 UNCERTAIN ones)
  - Explicit Accept (unchanged) action — marks AUTO landmarks as HUMAN_ACCEPTED
  - AMBIGUOUS marking per landmark
  - YAML ground-truth files written to docs/science/pilot_annotations/
  - Sidebar shows reviewed/accepted/corrected/ambiguous/unreviewed state
  - Annotation schema version v1

Usage (from server):
    cd ~/dive-analyser/experiments/landmark_pilot
    source venv/bin/activate
    python3 annotate.py

Then on Mac:
    ssh -i ~/.ssh/qwokka -L 8765:localhost:8765 mcauchy@192.168.1.57 -N &
    open http://localhost:8765

Keyboard shortcuts (in browser):
    Space          — play/pause
    ← / →          — step 1 frame (Shift: 10 frames)
    ↑ / ↓          — prev/next dive
    T              — set takeoff to current frame
    A              — set apex to current frame
    W              — set water contact to current frame
    B              — toggle AMBIGUOUS for focused landmark
    S              — save / finalize review
    Enter          — accept all unchanged
"""
import datetime
import decimal
import http.server
import json
import os
import re
import subprocess
import sys
import urllib.parse
from functools import lru_cache
from pathlib import Path

import psycopg2
import psycopg2.extras
import yaml
from repair_annotation_timebase import frame_timestamps


# Custom JSON encoder: converts Decimal → float so psycopg2 numeric fields serialize cleanly
class _DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, decimal.Decimal):
            return float(o)
        return super().default(o)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).parent.parent.parent  # ~/dive-analyser
MEDIA_CACHE_ROOT = REPO_ROOT / "media" / "cache"
MANIFEST_PATH = REPO_ROOT / "docs" / "science" / "PILOT_MANIFEST_V1.json"
PILOT_ANNOTATIONS_DIR = REPO_ROOT / "docs" / "science" / "pilot_annotations"
ANNOTATION_SCHEMA_VERSION = "v1"
ANNOTATOR = "maxime"
PIPELINE_KEY = "temporal_landmarks_baseline_a_v1"
WORKER_ID = "annotate_tool_v2"
PORT = 8765
LM_KEYS = ["takeoff", "apex", "water_contact"]

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


@lru_cache(maxsize=24)
def _presentation_times(path: str, mtime_ns: int) -> list:
    return frame_timestamps(Path(path))


# ---------------------------------------------------------------------------
# YAML ground-truth helpers
# ---------------------------------------------------------------------------

def _annotation_yaml_path(dive_id: int) -> Path:
    return PILOT_ANNOTATIONS_DIR / f"dive_{dive_id}.yaml"


def _load_annotation_yaml(dive_id: int) -> dict | None:
    p = _annotation_yaml_path(dive_id)
    if not p.exists():
        return None
    try:
        with open(p) as f:
            return yaml.safe_load(f)
    except Exception:
        return None  # corrupt/stale file; treat as unreviewed


def _to_float(v):
    """Convert Decimal or None to float or None — safe for YAML serialization."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _write_annotation_yaml(
    dive_id: int,
    lm_states: dict,          # landmark_key -> "HUMAN_ACCEPTED"|"HUMAN_CORRECTED"|"NOT_APPLICABLE"|"AMBIGUOUS"
    lm_frames: dict,          # landmark_key -> {frame_index, timestamp_seconds} for human value (None for N/A)
    auto_landmarks: dict,     # landmark_key -> {frame_index, timestamp_seconds, confidence, applicability}
    run_uuid: str,
) -> Path:
    """Write canonical YAML ground-truth annotation for a dive."""
    PILOT_ANNOTATIONS_DIR.mkdir(parents=True, exist_ok=True)
    info = MANIFEST.get(dive_id, {})
    landmarks_out = {}
    for lk in LM_KEYS:
        state = lm_states.get(lk, "HUMAN_ACCEPTED")
        auto = auto_landmarks.get(lk, {})
        human = lm_frames.get(lk, {})
        if state == "NOT_APPLICABLE":
            fi_h, ts_h = None, None
        else:
            fi_h = human.get("frame_index") if human else auto.get("frame_index")
            ts_h = human.get("timestamp_seconds") if human else auto.get("timestamp_seconds")
        auto_ts = _to_float(auto.get("timestamp_seconds"))
        auto_conf = _to_float(auto.get("confidence"))
        landmarks_out[lk] = {
            "state": state,
            "frame_index": int(fi_h) if fi_h is not None else None,
            "timestamp_seconds": round(_to_float(ts_h), 6) if ts_h is not None else None,
            "auto_frame_index": int(auto["frame_index"]) if auto.get("frame_index") is not None else None,
            "auto_timestamp_seconds": round(auto_ts, 6) if auto_ts is not None else None,
            "auto_confidence": round(auto_conf, 4) if auto_conf is not None else None,
            "auto_applicability": auto.get("applicability"),
        }
    doc = {
        "dive_id": dive_id,
        "annotation_schema_version": ANNOTATION_SCHEMA_VERSION,
        "annotator": ANNOTATOR,
        "annotation_timestamp": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_uuid": run_uuid,
        "media_checksum_sha256": info.get("media_key", ""),
        "landmarks": landmarks_out,
    }
    p = _annotation_yaml_path(dive_id)
    with open(p, "w") as f:
        yaml.dump(doc, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    return p


def _yaml_review_status(dive_id: int) -> str:
    """
    Returns one of: 'unreviewed', 'accepted', 'corrected', 'ambiguous', 'partial'.
    """
    ann = _load_annotation_yaml(dive_id)
    if ann is None:
        return "unreviewed"
    lms = ann.get("landmarks", {})
    states = {lk: lms.get(lk, {}).get("state", "unreviewed") for lk in LM_KEYS}
    if any(s == "AMBIGUOUS" for s in states.values()):
        return "ambiguous"
    if any(s == "HUMAN_CORRECTED" for s in states.values()):
        return "corrected"
    if all(s in ("HUMAN_ACCEPTED", "NOT_APPLICABLE") for s in states.values()):
        return "accepted"
    return "partial"


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


def _landmarks_for_run(cur, run_id) -> dict:
    cur.execute("""
        SELECT landmark_key, frame_index, timestamp_seconds,
               confidence, applicability, source,
               algorithm_key, algorithm_version, uncertainty_window_frames
        FROM analysis_landmarks
        WHERE run_id = %s
        ORDER BY landmark_key
    """, (run_id,))
    out = {}
    for row in cur.fetchall():
        out[row[0]] = {
            "frame_index": row[1],
            "timestamp_seconds": row[2],
            "confidence": float(row[3]) if row[3] is not None else None,
            "applicability": row[4],
            "source": row[5],
            "algorithm_key": row[6],
            "algorithm_version": row[7],
            "uncertainty_window_frames": row[8],
        }
    return out


def _get_all_pilot_data() -> list:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            dives = []
            for dive_id, info in MANIFEST.items():
                run_row = _latest_run_for_dive(cur, dive_id)
                proxy = _proxy_path(info["media_key"])
                review_status = _yaml_review_status(dive_id)
                entry = {
                    "dive_id": dive_id,
                    "dive_code": info.get("dive_code", ""),
                    "height": info.get("height", ""),
                    "session_date": info.get("session_date", ""),
                    "group": info.get("group", ""),
                    "proxy_available": proxy is not None,
                    "frame_times": _presentation_times(str(proxy), proxy.stat().st_mtime_ns) if proxy else [],
                    "run_uuid": None,
                    "run_status": None,
                    "landmarks": {},
                    "ordering_valid": False,
                    "review_status": review_status,
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
            dives.sort(key=lambda d: (d["group"], d["dive_id"]))
            return dives
    finally:
        conn.close()


def _get_dive_data(dive_id: int) -> dict | None:
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
                "run_uuid": run_uuid,
                "landmarks": landmarks,
                "proxy_available": proxy is not None,
                "review_status": _yaml_review_status(dive_id),
            }
    finally:
        conn.close()


def _save_and_annotate(
    dive_id: int,
    corrections: dict,         # landmark_key -> {frame_index, timestamp_seconds}
    not_applicable_keys: list, # landmark_keys to mark NOT_APPLICABLE
    ambiguous_keys: list,      # landmark_keys to mark AMBIGUOUS (no DB change)
) -> dict:
    """
    Saves corrections/N/A to DB, writes YAML for all 3 landmarks.
    Non-corrected, non-N/A, non-ambiguous landmarks are marked HUMAN_ACCEPTED.
    Returns {"ok": True} or {"error": ...}.
    """
    conn = _connect()
    try:
        with conn.cursor() as cur:
            run_row = _latest_run_for_dive(cur, dive_id)
            if not run_row:
                return {"error": "no run found for dive"}
            run_id = run_row[0]
            run_uuid = str(run_id)

            # Read current auto landmarks before any modifications
            auto_lms = _landmarks_for_run(cur, run_id)

            # DB: delete rows for corrected + N/A keys
            for lk in list(corrections.keys()) + list(not_applicable_keys):
                cur.execute(
                    "DELETE FROM analysis_landmarks WHERE run_id=%s AND landmark_key=%s",
                    (run_id, lk)
                )

            # DB: insert corrected landmarks
            for lk, vals in corrections.items():
                fi = vals.get("frame_index")
                ts = vals.get("timestamp_seconds")
                cur.execute("""
                    INSERT INTO analysis_landmarks
                        (run_id, landmark_key, frame_index, timestamp_seconds,
                         confidence, applicability, source,
                         algorithm_key, algorithm_version, uncertainty_window_frames)
                    VALUES (%s, %s, %s, %s, 1.0, 'APPLICABLE', 'HUMAN',
                            'annotate_tool', 'v2', 0)
                """, (run_id, lk, fi, ts))

            # DB: insert NOT_APPLICABLE landmarks
            for lk in not_applicable_keys:
                cur.execute("""
                    INSERT INTO analysis_landmarks
                        (run_id, landmark_key, frame_index, timestamp_seconds,
                         confidence, applicability, source,
                         algorithm_key, algorithm_version, uncertainty_window_frames)
                    VALUES (%s, %s, NULL, NULL, 1.0, 'NOT_APPLICABLE', 'HUMAN',
                            'annotate_tool', 'v2', 0)
                """, (run_id, lk))

            conn.commit()

            # Determine YAML state for all 3 landmarks
            lm_states = {}
            lm_frames = {}
            for lk in LM_KEYS:
                if lk in corrections:
                    lm_states[lk] = "HUMAN_CORRECTED"
                    lm_frames[lk] = corrections[lk]
                elif lk in not_applicable_keys:
                    lm_states[lk] = "NOT_APPLICABLE"
                    lm_frames[lk] = {}
                elif lk in ambiguous_keys:
                    lm_states[lk] = "AMBIGUOUS"
                    lm_frames[lk] = {}
                else:
                    lm_states[lk] = "HUMAN_ACCEPTED"
                    lm_frames[lk] = {}   # will use auto value in writer

            _write_annotation_yaml(dive_id, lm_states, lm_frames, auto_lms, run_uuid)

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
<title>Landmark Annotator v2 — Baseline A Pilot</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,sans-serif;background:#111;color:#eee;display:flex;height:100vh;overflow:hidden}
#sidebar{width:270px;min-width:200px;overflow-y:auto;background:#1a1a1a;border-right:1px solid #333;padding:8px}
#sidebar h2{font-size:13px;color:#888;padding:4px 0 8px;text-transform:uppercase;letter-spacing:.05em}
.dive-item{padding:6px 8px;border-radius:5px;cursor:pointer;font-size:13px;display:flex;align-items:center;gap:6px;margin-bottom:2px}
.dive-item:hover{background:#2a2a2a}
.dive-item.active{background:#2d4d6e}
.badge{font-size:11px;padding:2px 5px;border-radius:3px;font-weight:600;white-space:nowrap}
.badge-unreviewed{background:#4a2200;color:#f84}
.badge-accepted{background:#1a4a1a;color:#4f4}
.badge-corrected{background:#1a3a4a;color:#4af}
.badge-ambiguous{background:#3a2a1a;color:#fa8}
.badge-partial{background:#4a3a00;color:#fd4}
#main{flex:1;display:flex;flex-direction:column;overflow:hidden}
#toolbar{background:#1e1e1e;border-bottom:1px solid #333;padding:8px 14px;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
#toolbar h1{font-size:15px;margin-right:auto}
#toolbar button{background:#2a2a2a;border:1px solid #444;color:#eee;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:13px}
#toolbar button:hover{background:#3a3a3a}
#accept-btn{background:#1a5a1a;border-color:#2a8a2a;color:#fff}
#accept-btn:hover{background:#226a22}
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
#lm-panel{width:330px;min-width:270px;background:#1a1a1a;border-left:1px solid #333;padding:12px;overflow-y:auto}
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
.lm-badge.AMBIGUOUS{background:#3a2a1a;color:#fa8}
.lm-set-btn{font-size:11px;padding:3px 8px;background:#2d4d6e;border:1px solid #3a6a9e;color:#cdf;border-radius:3px;cursor:pointer;margin-top:4px;margin-right:4px}
.lm-na-btn{font-size:11px;padding:3px 8px;background:#3a1a1a;border:1px solid #6a3030;color:#fcc;border-radius:3px;cursor:pointer;margin-top:4px;margin-right:4px}
.lm-amb-btn{font-size:11px;padding:3px 8px;background:#3a2a1a;border:1px solid #6a5030;color:#fda;border-radius:3px;cursor:pointer;margin-top:4px;margin-right:4px}
.lm-amb-btn.active{background:#5a3a10;border-color:#9a7030;color:#ffcc44}
#save-bar{padding:10px 12px;border-top:1px solid #333;background:#181818}
#save-bar button{width:100%;padding:8px;font-size:14px;border-radius:5px;cursor:pointer;border:none;margin-bottom:6px}
#save-btn{background:#1a5a9e;color:#fff}
#save-btn:hover{background:#256ab0}
#status-msg{font-size:12px;color:#8f8;margin-top:6px;text-align:center;min-height:16px}
.speed-btn{font-size:11px!important;padding:3px 7px!important}
#progress-bar{padding:4px 8px;font-size:11px;color:#888;border-top:1px solid #222;background:#161616}
</style>
</head>
<body>
<div id="sidebar">
  <h2>Pilot Dives (<span id="reviewed-count">0</span>/20 reviewed)</h2>
  <div id="dive-list"></div>
</div>
<div id="main">
  <div id="toolbar">
    <h1 id="dive-title">Select a dive</h1>
    <button onclick="prevDive()">← Prev</button>
    <button onclick="nextDive()">Next →</button>
    <button id="accept-btn" onclick="acceptAll()" title="Mark all auto landmarks as accepted (Enter)">✓ Accept All [↵]</button>
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
        <button id="save-btn" onclick="saveLandmarks()">💾 Save Corrections [S]</button>
        <div id="status-msg"></div>
      </div>
    </div>
  </div>
  <div id="progress-bar">
    YAML annotation written to docs/science/pilot_annotations/ on each save/accept.
  </div>
</div>
<script>
let dives = [];
let currentDiveIdx = -1;
let fps = 30;
let frameTimes = [];
let pendingCorrections = {};   // landmark_key -> {frame_index, timestamp_seconds}
let notApplicableKeys = new Set();
let ambiguousKeys = new Set();

const vid = document.getElementById('vid');
const frameInfo = document.getElementById('frame-info');
const lmRows = document.getElementById('lm-rows');
const statusMsg = document.getElementById('status-msg');

async function loadDives() {
  try {
    const r = await fetch('/api/dives');
    const data = await r.json();
    if (!Array.isArray(data)) {
      document.getElementById('dive-list').textContent = 'Error: ' + JSON.stringify(data);
      return;
    }
    dives = data;
    updateReviewedCount();
    renderSidebar();
    if (dives.length > 0) selectDive(0);
  } catch(e) {
    document.getElementById('dive-list').textContent = 'Failed to load: ' + e.message;
  }
}

function reviewStatusBadge(d) {
  const s = d.review_status;
  if (s === 'accepted') return '<span class="badge badge-accepted">✓ accepted</span>';
  if (s === 'corrected') return '<span class="badge badge-corrected">✎ corrected</span>';
  if (s === 'ambiguous') return '<span class="badge badge-ambiguous">~ ambiguous</span>';
  if (s === 'partial')   return '<span class="badge badge-partial">⊘ partial</span>';
  // unreviewed
  const allValid = d.ordering_valid;
  if (allValid) return '<span class="badge badge-unreviewed">! auto-ok</span>';
  return '<span class="badge badge-unreviewed">! unreviewed</span>';
}

function updateReviewedCount() {
  const done = dives.filter(d => ['accepted','corrected','ambiguous','partial'].includes(d.review_status)).length;
  document.getElementById('reviewed-count').textContent = done;
}

function renderSidebar() {
  const el = document.getElementById('dive-list');
  el.innerHTML = '';
  dives.forEach((d, i) => {
    const div = document.createElement('div');
    div.className = 'dive-item' + (i === currentDiveIdx ? ' active' : '');
    div.onclick = () => selectDive(i);
    div.innerHTML = `${reviewStatusBadge(d)}<span>#${d.dive_id} ${d.dive_code} <small style="color:#777">${d.height}</small></span>`;
    el.appendChild(div);
  });
}

async function selectDive(idx) {
  if (idx < 0 || idx >= dives.length) return;
  currentDiveIdx = idx;
  pendingCorrections = {};
  notApplicableKeys = new Set();
  ambiguousKeys = new Set();
  renderSidebar();

  const d = dives[idx];
  if (!d) { console.error('dive not found at idx', idx); return; }
  document.getElementById('dive-title').textContent =
    `#${d.dive_id} — ${d.dive_code} ${d.height} (${d.session_date || '?'})`;

  if (d.proxy_available) {
    vid.src = `/video/${d.dive_id}`;
    vid.load();
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
  frameTimes = d.frame_times || [];
  return frameTimes.length > 1 ? 1 / (frameTimes[1] - frameTimes[0]) : 0;
}

vid.addEventListener('timeupdate', updateFrameInfo);
vid.addEventListener('seeked', updateFrameInfo);

function updateFrameInfo() {
  const t = vid.currentTime;
  const f = currentFrame();
  frameInfo.textContent = `Frame ~${f}  |  Time ${t.toFixed(4)}s  |  FPS ${fps}`;
}

function currentFrame() {
  if (!frameTimes.length) return null;
  let low = 0, high = frameTimes.length;
  while (low < high) {
    const mid = Math.floor((low + high) / 2);
    if (frameTimes[mid] <= vid.currentTime + 0.000001) low = mid + 1;
    else high = mid;
  }
  return Math.max(0, low - 1);
}

function stepFrame(n) {
  if (!frameTimes.length) return;
  vid.pause();
  goToFrame(Math.max(0, Math.min(frameTimes.length - 1, currentFrame() + n)));
}

function togglePlay() {
  if (vid.paused) vid.play(); else vid.pause();
}

function setSpeed(s) {
  vid.playbackRate = s;
}

function goToFrame(f) {
  if (Number.isInteger(f) && f >= 0 && f < frameTimes.length) vid.currentTime = frameTimes[f];
}

function setLandmark(key) {
  const f = currentFrame();
  if (f === null) return;
  const ts = vid.currentTime;
  pendingCorrections[key] = {frame_index: f, timestamp_seconds: ts};
  notApplicableKeys.delete(key);
  ambiguousKeys.delete(key);
  renderLandmarks(dives[currentDiveIdx]);
  statusMsg.textContent = `Set ${key} → frame ${f} (unsaved)`;
  statusMsg.style.color = '#fa4';
}

function markNotApplicable(key) {
  notApplicableKeys.add(key);
  ambiguousKeys.delete(key);
  delete pendingCorrections[key];
  renderLandmarks(dives[currentDiveIdx]);
  statusMsg.textContent = `Marked ${key} NOT_APPLICABLE (unsaved)`;
  statusMsg.style.color = '#fa4';
}

function toggleAmbiguous(key) {
  if (ambiguousKeys.has(key)) {
    ambiguousKeys.delete(key);
    statusMsg.textContent = `Cleared AMBIGUOUS for ${key}`;
  } else {
    ambiguousKeys.add(key);
    notApplicableKeys.delete(key);
    delete pendingCorrections[key];
    statusMsg.textContent = `Marked ${key} AMBIGUOUS (unsaved)`;
  }
  statusMsg.style.color = '#fa8';
  renderLandmarks(dives[currentDiveIdx]);
}

function renderLandmarks(d) {
  const LM_KEYS = ['takeoff', 'apex', 'water_contact'];
  const db = d.landmarks || {};
  lmRows.innerHTML = '';

  LM_KEYS.forEach(key => {
    const orig = db[key] || {};
    const pending = pendingCorrections[key];
    const isNa = notApplicableKeys.has(key);
    const isAmb = ambiguousKeys.has(key);
    const display = isNa ? null : (isAmb ? orig : (pending || orig));

    const row = document.createElement('div');
    row.className = 'lm-row';

    let stateLabel = orig.applicability || '—';
    let sourceLabel = orig.source || '—';
    let modifiedNote = '';

    if (pending) { stateLabel = 'APPLICABLE'; sourceLabel = 'HUMAN'; modifiedNote = '● unsaved correction'; }
    if (isNa)   { stateLabel = 'NOT_APPLICABLE'; sourceLabel = 'HUMAN'; modifiedNote = '● unsaved N/A'; }
    if (isAmb)  { stateLabel = 'AMBIGUOUS'; sourceLabel = 'HUMAN'; modifiedNote = '● unsaved ambiguous'; }

    const fi = display ? display.frame_index : null;
    const ts = display ? display.timestamp_seconds : null;

    row.innerHTML = `
      <h3>
        <span class="lm-dot dot-${key}"></span>
        ${key.replace(/_/g, ' ')}
        ${modifiedNote ? `<small style="color:#fa4">${modifiedNote}</small>` : ''}
      </h3>
      <div class="lm-fields">
        Frame: <input type="number" id="fi-${key}" value="${fi !== null ? fi : ''}"
          onchange="manualEdit('${key}', this.value)">
        &nbsp;Time: ${ts !== null ? ts.toFixed(3)+'s' : '—'}
        <br>
        <span class="lm-badge ${stateLabel}">${stateLabel}</span>
        <span class="lm-badge" style="background:#1c1c1c;color:#888">${sourceLabel}</span>
        ${orig.confidence !== undefined && orig.confidence !== null ? `<span style="color:#777;font-size:11px"> conf:${orig.confidence.toFixed(2)}</span>` : ''}
        <br>
        <button class="lm-set-btn" onclick="setLandmark('${key}')">Set to current frame</button>
        ${fi !== null ? `<button class="lm-set-btn" onclick="goToFrame(${fi})" style="background:#333;border-color:#555;color:#ccc">Go to frame</button>` : ''}
        <br>
        <button class="lm-na-btn" onclick="markNotApplicable('${key}')">NOT_APPLICABLE</button>
        <button class="lm-amb-btn ${isAmb ? 'active' : ''}" onclick="toggleAmbiguous('${key}')">AMBIGUOUS</button>
      </div>`;

    lmRows.appendChild(row);
  });
}

function manualEdit(key, value) {
  const f = parseInt(value);
  if (isNaN(f) || f < 0 || f >= frameTimes.length) return;
  notApplicableKeys.delete(key);
  ambiguousKeys.delete(key);
  if (!pendingCorrections[key]) pendingCorrections[key] = {};
  pendingCorrections[key].frame_index = f;
  pendingCorrections[key].timestamp_seconds = frameTimes[f];
  statusMsg.textContent = `Editing ${key} frame=${f} (unsaved)`;
  statusMsg.style.color = '#fa4';
}

async function saveLandmarks() {
  if (currentDiveIdx < 0) return;
  const d = dives[currentDiveIdx];
  const payload = {
    corrections: pendingCorrections,
    not_applicable: Array.from(notApplicableKeys),
    ambiguous: Array.from(ambiguousKeys),
  };
  statusMsg.textContent = 'Saving…';
  statusMsg.style.color = '#888';
  const r = await fetch(`/api/landmarks/${d.dive_id}`, {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify(payload),
  });
  const result = await r.json();
  await _afterSave(result);
}

async function acceptAll() {
  if (currentDiveIdx < 0) return;
  const d = dives[currentDiveIdx];
  statusMsg.textContent = 'Accepting…';
  statusMsg.style.color = '#888';
  const r = await fetch(`/api/landmarks/${d.dive_id}`, {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ corrections: {}, not_applicable: [], ambiguous: [] }),
  });
  const result = await r.json();
  await _afterSave(result);
}

async function _afterSave(result) {
  if (result.ok) {
    statusMsg.textContent = '✓ Saved — YAML written';
    statusMsg.style.color = '#4f4';
    pendingCorrections = {};
    notApplicableKeys = new Set();
    ambiguousKeys = new Set();
    try {
      const refresh = await fetch('/api/dives');
      const data = await refresh.json();
      if (Array.isArray(data)) {
        dives = data;
        updateReviewedCount();
        renderSidebar();
        if (dives[currentDiveIdx]) renderLandmarks(dives[currentDiveIdx]);
      }
    } catch(e) {
      console.error('refresh failed:', e);
    }
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
  // Prevent all arrow/space defaults to stop browser video controls interfering
  if (['ArrowLeft','ArrowRight','ArrowUp','ArrowDown',' '].includes(e.key)) {
    e.preventDefault();
  }
  if (e.key === 'ArrowLeft') stepFrame(e.shiftKey ? -10 : -1);
  else if (e.key === 'ArrowRight') stepFrame(e.shiftKey ? 10 : 1);
  else if (e.key === ' ') togglePlay();
  else if (e.key === 't' || e.key === 'T') setLandmark('takeoff');
  else if (e.key === 'a' || e.key === 'A') setLandmark('apex');
  else if (e.key === 'w' || e.key === 'W') setLandmark('water_contact');
  else if (e.key === 's' || e.key === 'S') saveLandmarks();
  else if (e.key === 'Enter') acceptAll();
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
        body = json.dumps(data, cls=_DecimalEncoder).encode()
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
        if m:
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
                ambiguous = payload.get("ambiguous", [])
                result = _save_and_annotate(dive_id, corrections, not_applicable, ambiguous)
                self.send_json(result)
            except Exception as e:
                self.send_json({"error": str(e)}, 500)
            return

        self.send_response(404); self.end_headers()

    def _stream_file(self, path: Path, content_type: str):
        size = path.stat().st_size
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
    PILOT_ANNOTATIONS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Landmark Annotation Tool v2")
    print(f"  Loaded {len(MANIFEST)} dives from {MANIFEST_PATH.name}")
    print(f"  YAML output: {PILOT_ANNOTATIONS_DIR}")
    print(f"  Listening on http://localhost:{PORT}")
    print(f"")
    print(f"  From Mac:")
    print(f"    ssh -i ~/.ssh/qwokka -L {PORT}:localhost:{PORT} mcauchy@192.168.1.57 -N &")
    print(f"    open http://localhost:{PORT}")
    print(f"")
    print(f"  Keyboard shortcuts (in browser):")
    print(f"    Space          — play/pause")
    print(f"    ← / →          — step 1 frame (Shift: 10 frames)")
    print(f"    ↑ / ↓          — prev/next dive")
    print(f"    T              — set takeoff to current frame")
    print(f"    A              — set apex to current frame")
    print(f"    W              — set water contact to current frame")
    print(f"    S              — save corrections + write YAML")
    print(f"    Enter          — accept all (unchanged) + write YAML")
    print(f"")
    review_counts = {"unreviewed": 0, "accepted": 0, "corrected": 0, "ambiguous": 0, "partial": 0}
    for did in MANIFEST:
        s = _yaml_review_status(did)
        review_counts[s] = review_counts.get(s, 0) + 1
    reviewed = sum(v for k, v in review_counts.items() if k != "unreviewed")
    print(f"  Review progress: {reviewed}/{len(MANIFEST)} dives reviewed")
    for k, v in review_counts.items():
        if v > 0:
            print(f"    {k}: {v}")
    print(f"")
    server = http.server.HTTPServer(("127.0.0.1", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutdown.")
