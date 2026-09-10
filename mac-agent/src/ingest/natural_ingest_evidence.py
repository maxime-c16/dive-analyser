"""P9-B passive natural-ingest evidence capture (read-only composition).

When a genuinely new captioned production clip flows legacy-first through the
normal media-job pipeline, the continuous dual-write path records durable
artifacts under the production object-store state dir:

    <state_dir>/<uuid>.stage.json           trigger provenance (P9-B)
    <state_dir>/<uuid>.json                 ingest journal (state machine)
    <state_dir>/<uuid>.evidence.json        caption SHA/parity provenance
    <state_dir>/<uuid>.commit_receipt.json  authenticated commit receipt
    <state_dir>/metrics/<run_id>.json       run-unique metrics snapshots

This module composes those artifacts into ONE privacy-safe observation record
(`natural_ingest/<uuid>.json`, 0600) WITHOUT persisting any raw caption text:

    logical UUID, trigger timestamp, trigger reason/activation,
    legacy-success stage timestamp, dual-write final state, media SHA,
    object key, PROD storage-location id, remote verification ops,
    commit receipt ids, and playback availability (derived: a verified PROD
    location commit is the P7-proven playback precondition; explicit live
    playback checks remain server-side).

It NEVER mutates any of the underlying artifacts and NEVER touches Photos.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

JOURNAL_SUFFIX = ".json"
STAGE_SUFFIX = ".stage.json"
EVIDENCE_SUFFIX = ".evidence.json"
RECEIPT_SUFFIX = ".commit_receipt.json"
METRICS_DIRNAME = "metrics"
OUTPUT_DIRNAME = "natural_ingest"

TERMINAL_PLAYBACK_READY_STATES = {"CACHE_CLEANED"}


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _latest_metrics_for(state_dir: Path, video_uuid: str) -> dict | None:
    metrics_dir = state_dir / METRICS_DIRNAME
    if not metrics_dir.is_dir():
        return None
    best = None
    for path in sorted(metrics_dir.glob("*.json")):
        doc = _read_json(path)
        if not doc or doc.get("video_uuid") != video_uuid:
            continue
        if best is None or (doc.get("started_at") or "") >= (best.get("started_at") or ""):
            best = doc
    return best


def _safe_caption_summary(evidence: dict | None) -> dict:
    """Caption provenance WITHOUT raw text (privacy rule: no caption bytes)."""
    caption = (evidence or {}).get("caption") or {}
    shadow = (evidence or {}).get("shadow") or {}
    parity = (evidence or {}).get("parity") or {}
    return {
        "provider": caption.get("provider"),
        "available": caption.get("available"),
        "caption_sha256": caption.get("caption_sha256"),
        "caption_length": caption.get("caption_length"),
        "caption_utf8_bytes": caption.get("caption_utf8_bytes"),
        "shadow_provider": shadow.get("provider"),
        "shadow_sha256": shadow.get("shadow_sha256"),
        "parity": parity.get("status") if isinstance(parity, dict) else parity,
        "parsed": (evidence or {}).get("parsed"),
    }


def build_natural_ingest_evidence(state_dir: Path, video_uuid: str) -> dict:
    """Compose the observation record for one logical clip (read-only)."""
    state_dir = Path(state_dir)
    stage = _read_json(state_dir / f"{video_uuid}{STAGE_SUFFIX}") or {}
    journal = _read_json(state_dir / f"{video_uuid}{JOURNAL_SUFFIX}") or {}
    evidence = _read_json(state_dir / f"{video_uuid}{EVIDENCE_SUFFIX}")
    receipt = _read_json(state_dir / f"{video_uuid}{RECEIPT_SUFFIX}")
    metrics = _latest_metrics_for(state_dir, video_uuid)

    receipt_result = (receipt or {}).get("result") or {}
    final_state = metrics.get("final_state") if metrics else None
    journal_state = journal.get("state") or final_state

    record = {
        "schema": "natural_ingest_evidence_v1",
        "video_uuid": video_uuid,
        "trigger": {
            "request_reason": stage.get("request_reason"),
            "triggered_at": stage.get("triggered_at"),
            "activation": stage.get("activation"),
            "staged_bytes": stage.get("staged_bytes"),
            "copy_seconds": stage.get("copy_seconds"),
        },
        "legacy_success": {
            # stage_copy runs strictly AFTER legacy upload/finalize success
            # (media_jobs._process_job calls _trigger_dual_write after
            # upload_and_finalize), so the trigger timestamp is the earliest
            # durable post-legacy-success observation point.
            "observed_at": stage.get("triggered_at"),
            "staging_refused": bool(stage.get("staging_refused")),
            "backpressure_skip": bool(stage.get("backpressure_skip")),
            "skip_reason": stage.get("skip_reason"),
        },
        "dual_write": {
            "journal_state": journal_state,
            "final_state": final_state,
            "result": (metrics or {}).get("result"),
            "started_at": (metrics or {}).get("started_at"),
            "completed_at": (metrics or {}).get("completed_at"),
            "extra_photos_materializations": ((metrics or {}).get("staging") or {}).get(
                "extra_photos_materializations"
            ),
            "reused_legacy_bytes": ((metrics or {}).get("staging") or {}).get(
                "reused_legacy_bytes"
            ),
        },
        "media": {
            "sha256": (metrics or {}).get("media_sha256")
            or (journal.get("media") or {}).get("sha256"),
            "object_key": (metrics or {}).get("object_key")
            or (journal.get("media") or {}).get("object_key"),
        },
        "remote_verification": {
            "ops": (metrics or {}).get("ops_total") or {},
            "roundtrip_rule": "full remote GET SHA == local SHA (coordinator)",
        },
        "commit": {
            "transport": (receipt or {}).get("transport"),
            "environment": receipt_result.get("environment"),
            "blob_sha256": receipt_result.get("blob_sha256"),
            "media_blob_location_id": receipt_result.get("media_blob_location_id"),
            "media_revision_id": receipt_result.get("media_revision_id"),
            "caption_revision_id": receipt_result.get("caption_revision_id"),
            "ingest_state_id": receipt_result.get("ingest_state_id"),
        },
        "playback": {
            "prod_location_committed": bool(
                receipt_result.get("media_blob_location_id")
                and receipt_result.get("environment") == "prod"
            ),
            # P7-proven convergence: a verified PROD location commit makes the
            # revision B2-playable automatically; the live 302→206 proof is an
            # operator/server-side observation, not asserted here.
            "live_check": "operator_server_side",
        },
        "caption_summary": _safe_caption_summary(evidence),
    }
    return record


def is_natural_ingest_complete(record: dict) -> tuple[bool, list[str]]:
    """Gate check for CONTINUOUS_NATURAL_INGEST evidence completeness."""
    missing: list[str] = []
    if record["trigger"].get("request_reason") != "new_captioned_ingestion":
        missing.append("request_reason=new_captioned_ingestion")
    if not record["trigger"].get("triggered_at"):
        missing.append("trigger timestamp")
    if record["legacy_success"].get("staging_refused"):
        missing.append("legacy succeeded without staging refusal")
    if not record["dual_write"].get("reused_legacy_bytes"):
        missing.append("same legacy-materialized bytes reused")
    if record["dual_write"].get("extra_photos_materializations") != 0:
        missing.append("extra Photos materializations == 0")
    if not record["media"].get("sha256"):
        missing.append("media sha")
    if not record["commit"].get("media_blob_location_id"):
        missing.append("PROD location commit")
    if record["dual_write"].get("journal_state") not in TERMINAL_PLAYBACK_READY_STATES:
        missing.append("verified PROD terminal state (CACHE_CLEANED)")
    return (not missing, missing)


def write_record(state_dir: Path, video_uuid: str, record: dict) -> Path:
    out_dir = Path(state_dir) / OUTPUT_DIRNAME
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{video_uuid}.json"
    fd = os.open(out_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(record, fh, ensure_ascii=False, indent=2, sort_keys=True)
    return out_path


def capture(state_dir: Path, video_uuid: str) -> tuple[Path, dict]:
    record = build_natural_ingest_evidence(Path(state_dir), video_uuid)
    complete, missing = is_natural_ingest_complete(record)
    record["complete"] = complete
    record["missing"] = missing
    out_path = write_record(Path(state_dir), video_uuid, record)
    return out_path, record


def latest_video_uuid(state_dir: Path) -> str | None:
    """Most recent stage/journal artifact with trigger provenance."""
    state_dir = Path(state_dir)
    candidates: list[tuple[str, str]] = []
    for path in state_dir.glob(f"*{STAGE_SUFFIX}"):
        doc = _read_json(path) or {}
        if doc.get("triggered_at"):
            candidates.append((doc["triggered_at"], path.name[: -len(STAGE_SUFFIX)]))
    if not candidates:
        return None
    candidates.sort()
    return candidates[-1][1]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Compose the P9-B natural-ingest observation record "
        "(read-only; never mutates underlying artifacts)"
    )
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--video-uuid", default=None)
    parser.add_argument("--latest", action="store_true")
    args = parser.parse_args(argv)
    state_dir = Path(args.state_dir)
    video_uuid = args.video_uuid
    if video_uuid is None:
        if not args.latest:
            parser.error("provide --video-uuid or --latest")
        video_uuid = latest_video_uuid(state_dir)
        if video_uuid is None:
            print("NO_NATURAL_INGEST_EVIDENCE_YET", file=sys.stderr)
            return 3
    path, record = capture(state_dir, video_uuid)
    complete, missing = is_natural_ingest_complete(record)
    print(json.dumps({"path": str(path), "complete": complete, "missing": missing}))
    return 0 if complete else 1


if __name__ == "__main__":
    sys.exit(main())
