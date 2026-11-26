#!/usr/bin/env python3
"""Push auto-detected dive clip timestamps to Dive Analyser without losing prior triage.

Zero external dependencies (Python stdlib only).

Note on URL:
  Point --url / DIVE_ANALYSER_URL at the LAN/Tailscale-private HTTPS front door
  (e.g. https://deb-serv:6443) or local loopback (http://127.0.0.1:8000).
  The public Tailscale Funnel proxy requires a browser session cookie and does
  not forward machine X-API-Key requests.

Examples:
  DIVE_ANALYSER_URL=https://deb-serv:6443 \
  DIVE_ANALYSER_API_KEY=... \
  python3 tools/push_clip_candidates.py \
      --filename IMG_2651.MOV \
      --detector core_detection --version v1.4 \
      runs/v1.4/candidates.json

  # Export human-triaged Ground Truth back to JSON for detector evaluation:
  python3 tools/push_clip_candidates.py \
      --filename IMG_2651.MOV --export-gt gt_2651.json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

MAX_CANDIDATES_PER_BATCH = 500
MAX_CLIP_SPAN_S = 60.0
STREAM_CHUNK_BYTES = 65536
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
_COUNTS_HEAD_RE = re.compile(r'"counts"\s*:\s*(\{[^}]+\})')
_NEXT_CURSOR_TAIL_RE = re.compile(r'"next_cursor"\s*:\s*(null|"([^"\\]+)")')


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse 3xx redirects so X-API-Key is never forwarded across origins."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SystemExit(
            f"Refusing HTTP {code} redirect to {newurl!r}: check --url (X-API-Key is never forwarded across redirects)"
        )


_OPENER = urllib.request.build_opener(_NoRedirectHandler)


def _validate_base_url(base_url: str, *, allow_http: bool) -> str:
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme not in ("https", "http") or not parsed.netloc:
        raise SystemExit(f"Invalid --url {base_url!r}: expected https://<host>")
    if parsed.scheme == "http" and not allow_http and (parsed.hostname or "").lower() not in LOOPBACK_HOSTS:
        raise SystemExit(
            f"Refusing plaintext HTTP to non-loopback host {parsed.hostname!r} (pass --allow-http to override)"
        )
    return base_url.rstrip("/")


def _sanitize_json_value(value: Any) -> Any:
    """Recursively replace non-finite floats so outgoing JSON is strict RFC 8259 / JSONB safe."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): _sanitize_json_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_json_value(v) for v in value]
    return value


def _request_json(
    base_url: str,
    path: str,
    api_key: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = base_url.rstrip("/") + path
    headers = {"Accept": "application/json", "X-API-Key": api_key}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(_sanitize_json_value(payload), allow_nan=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with _OPENER.open(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:400]
        raise SystemExit(f"HTTP {exc.code} on {method} {path}: {body}") from None
    except urllib.error.URLError as exc:
        raise SystemExit(f"Network error on {method} {path}: {exc.reason}") from None


def _first_present(entry: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in entry and entry[key] is not None:
            return entry[key]
    return None


def _normalize_candidates(raw: Any, *, pre_roll: float, post_roll: float) -> list[dict[str, Any]]:
    """Accept list[{start_s, end_s}], {candidates: [...]}, or {events: [{t_s, ...}]}."""
    if isinstance(raw, dict):
        items = raw.get("candidates")
        if items is None:
            items = raw.get("events")
        if items is None:
            items = raw.get("clips")
        if items is None:
            items = []
    elif isinstance(raw, list):
        items = raw
    else:
        raise SystemExit("Unsupported JSON shape: expected a list or an object with 'candidates'/'events'")

    normalized: list[dict[str, Any]] = []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        if entry.get("start_s") is not None and entry.get("end_s") is not None:
            start_s = float(entry["start_s"])
            end_s = float(entry["end_s"])
        elif entry.get("start") is not None and entry.get("end") is not None:
            start_s = float(entry["start"])
            end_s = float(entry["end"])
        else:
            point = _first_present(entry, "t_s", "event_time_s", "time_s")
            if point is None:
                continue
            t = float(point)
            start_s = max(0.0, t - pre_roll)
            end_s = t + post_roll

        if not (math.isfinite(start_s) and math.isfinite(end_s)):
            continue
        start_r = round(start_s, 3)
        end_r = round(end_s, 3)
        if start_r < 0.0 or end_r <= start_r or (end_r - start_r) > MAX_CLIP_SPAN_S:
            continue

        out: dict[str, Any] = {"start_s": start_r, "end_s": end_r}
        conf = _first_present(entry, "confidence", "score")
        if conf is not None:
            conf_f = float(conf)
            if math.isfinite(conf_f) and 0.0 <= conf_f <= 1.0:
                out["confidence"] = round(conf_f, 4)
        if entry.get("label"):
            out["label"] = str(entry["label"])[:80]
        raw_meta = {
            k: v
            for k, v in entry.items()
            if k not in ("start_s", "end_s", "start", "end", "confidence", "score", "label")
        }
        meta = _sanitize_json_value(raw_meta)
        if meta:
            out["meta"] = meta
        normalized.append(out)
    return normalized


def _resolve_video_id(base_url: str, api_key: str, filename: str) -> int:
    q = urllib.parse.urlencode({"filename": filename})
    data = _request_json(base_url, f"/api/v1/clip-triage/resolve-video?{q}", api_key)
    matches = data.get("items") or []
    if not matches:
        raise SystemExit(f"No ready SessionVideo found matching filename {filename!r}")
    if len(matches) > 1:
        ids = ", ".join(f"id={m['id']} ({m.get('recorded_date')})" for m in matches[:5])
        raise SystemExit(f"Multiple SessionVideos match {filename!r}: {ids}. Pass --video-id explicitly.")
    return int(matches[0]["id"])


def _stream_export_gt_page(
    base_url: str,
    api_key: str,
    video_id: int,
    out_path: Path,
    *,
    cursor: str | None = None,
) -> tuple[int, dict[str, int] | None, str | None]:
    """Stream one bounded Ground Truth JSON page directly to disk in 64 KiB chunks."""
    path = f"/api/v1/session-videos/{video_id}/clip-gt/export"
    if cursor:
        path = f"{path}?{urllib.parse.urlencode({'cursor': cursor})}"
    url = base_url.rstrip("/") + path
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "X-API-Key": api_key},
        method="GET",
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_name(f"{out_path.name}.tmp.{os.getpid()}")
    total_bytes = 0
    head_buf = bytearray()
    tail_buf = bytearray()
    try:
        with _OPENER.open(req, timeout=120) as resp, tmp_path.open("wb") as handle:
            while True:
                chunk = resp.read(STREAM_CHUNK_BYTES)
                if not chunk:
                    break
                handle.write(chunk)
                total_bytes += len(chunk)
                if len(head_buf) < 4096:
                    head_buf.extend(chunk[: 4096 - len(head_buf)])
                tail_buf.extend(chunk[-2048:])
                if len(tail_buf) > 2048:
                    del tail_buf[:-2048]
        os.replace(tmp_path, out_path)
    except urllib.error.HTTPError as exc:
        tmp_path.unlink(missing_ok=True)
        body = exc.read().decode("utf-8", errors="replace")[:400]
        raise SystemExit(f"HTTP {exc.code} on GET {path}: {body}") from None
    except urllib.error.URLError as exc:
        tmp_path.unlink(missing_ok=True)
        raise SystemExit(f"Network error on GET {path}: {exc.reason}") from None
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise

    counts: dict[str, int] | None = None
    match = _COUNTS_HEAD_RE.search(head_buf.decode("utf-8", errors="replace"))
    if match:
        try:
            parsed = json.loads(match.group(1))
            if isinstance(parsed, dict):
                counts = {
                    "positives": int(parsed.get("positives", 0)),
                    "negatives": int(parsed.get("negatives", 0)),
                    "trimmed": int(parsed.get("trimmed", 0)),
                }
        except (ValueError, TypeError):
            counts = None

    next_cursor: str | None = None
    tail_match = _NEXT_CURSOR_TAIL_RE.search(tail_buf.decode("utf-8", errors="replace"))
    if tail_match and tail_match.group(2):
        next_cursor = tail_match.group(2)
    return total_bytes, counts, next_cursor


MAX_GT_EXPORT_PAGES = 10_000


def _stream_export_gt(
    base_url: str,
    api_key: str,
    video_id: int,
    out_path: Path,
) -> tuple[int, dict[str, int] | None, int]:
    """Stream bounded GT export pages directly to disk, following explicit next_cursor continuation.

    Returns (total_bytes, first_page_counts, page_count). Retains only the
    current cursor, so memory stays constant regardless of page count.
    """
    cursor: str | None = None
    page_num = 1
    total_bytes = 0
    first_counts: dict[str, int] | None = None

    while True:
        target = (
            out_path
            if page_num == 1
            else out_path.with_name(f"{out_path.stem}.part{page_num}{out_path.suffix}")
        )
        nbytes, counts, next_cursor = _stream_export_gt_page(
            base_url, api_key, video_id, target, cursor=cursor
        )
        total_bytes += nbytes
        if first_counts is None:
            first_counts = counts
        if not next_cursor:
            break
        if next_cursor == cursor:
            raise SystemExit(f"GT export cursor did not advance after page {page_num}")
        if page_num >= MAX_GT_EXPORT_PAGES:
            raise SystemExit(f"GT export exceeded {MAX_GT_EXPORT_PAGES} pages; aborting")
        cursor = next_cursor
        page_num += 1
    return total_bytes, first_counts, page_num


def main() -> None:
    parser = argparse.ArgumentParser(description="Push detected dive clip timestamps to Dive Analyser")
    parser.add_argument("input_json", nargs="?", help="JSON file of detected candidates or events")
    parser.add_argument("--url", default=os.environ.get("DIVE_ANALYSER_URL", ""), help="LAN/direct app base URL")
    parser.add_argument("--api-key", default=os.environ.get("DIVE_ANALYSER_API_KEY", ""), help="Machine API key")
    parser.add_argument("--allow-http", action="store_true", help="Allow plaintext http:// to non-loopback hosts")
    parser.add_argument("--video-id", type=int, help="Target session_videos.id")
    parser.add_argument("--filename", help="Resolve session_videos.id by recording filename (e.g. IMG_2651.MOV)")
    parser.add_argument("--detector", default="core_detection", help="Detector name")
    parser.add_argument("--version", default="dev", help="Detector version/tag")
    parser.add_argument("--pre-roll", type=float, default=8.0, help="Pre-roll seconds when input has point timestamps")
    parser.add_argument("--post-roll", type=float, default=6.0, help="Post-roll seconds when input has point timestamps")
    parser.add_argument("--export-gt", help="Write triaged Ground Truth JSON to this path")
    args = parser.parse_args()

    if not args.url:
        raise SystemExit("Set DIVE_ANALYSER_URL or pass --url")
    if not args.api_key:
        raise SystemExit("Set DIVE_ANALYSER_API_KEY or pass --api-key")
    if not args.video_id and not args.filename:
        raise SystemExit("Pass --video-id or --filename")

    base_url = _validate_base_url(args.url, allow_http=args.allow_http)
    video_id = args.video_id or _resolve_video_id(base_url, args.api_key, args.filename)

    if args.input_json:
        raw = json.loads(Path(args.input_json).read_text(encoding="utf-8"))
        candidates = _normalize_candidates(raw, pre_roll=args.pre_roll, post_roll=args.post_roll)
        batches = [
            candidates[i : i + MAX_CANDIDATES_PER_BATCH]
            for i in range(0, max(1, len(candidates)), MAX_CANDIDATES_PER_BATCH)
        ]
        total_created = 0
        total_deduped = 0
        total_preserved = 0
        run_ids: list[int] = []
        for idx, batch in enumerate(batches, 1):
            version = args.version if len(batches) == 1 else f"{args.version}-part{idx}"
            res = _request_json(
                base_url,
                f"/api/v1/session-videos/{video_id}/clip-runs",
                args.api_key,
                method="POST",
                payload={
                    "detector_name": args.detector,
                    "detector_version": version,
                    "candidates": batch,
                },
            )
            run_ids.append(int(res["run_id"]))
            total_created += int(res["created_count"])
            total_deduped += int(res["deduped_count"])
            total_preserved += int(res["preserved_triaged_count"])
        run_desc = f"Run #{run_ids[0]}" if len(run_ids) == 1 else f"Runs {run_ids}"
        print(
            f"{run_desc} ({args.detector} {args.version}) on video #{video_id}: "
            f"+{total_created} nouveaux · {total_deduped} fusionnés "
            f"({total_preserved} déjà triés conservés)"
        )

    if args.export_gt:
        out = Path(args.export_gt)
        total_bytes, counts, page_count = _stream_export_gt(base_url, args.api_key, video_id, out)
        dest = str(out) if page_count == 1 else f"{out} (+{page_count - 1} part(s))"
        if counts is not None:
            print(
                f"GT exporté → {dest} ({counts['positives']} vrais plongeons, "
                f"{counts['negatives']} faux positifs, {counts['trimmed']} bornes ajustées)"
            )
        else:
            print(f"GT exporté → {dest} ({total_bytes} octets)")

    if not args.input_json and not args.export_gt:
        print(f"Resolved video_id={video_id}")


if __name__ == "__main__":
    main()
