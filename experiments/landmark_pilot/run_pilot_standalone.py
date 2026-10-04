#!/usr/bin/env python3
"""Standalone pilot runner using experiment venv.

Runs landmark Baseline-A on pilot dives and persists results directly to DB.
Run from ~/dive-analyser/experiments/landmark_pilot/ with venv active.

Usage:
    source venv/bin/activate
    DB_PASSWORD=<pw> python3 run_pilot_standalone.py [--max-dives N] [--dive-id N]
"""
import sys
import json
import os
import argparse
import hashlib
import logging
import subprocess
from pathlib import Path
from dataclasses import asdict
from datetime import datetime

import psycopg2
import psycopg2.extras

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("run_pilot")

REPO_ROOT = Path(__file__).parent.parent.parent  # ~/dive-analyser
MEDIA_CACHE_ROOT = REPO_ROOT / "media" / "cache"
ARTIFACT_ROOT = REPO_ROOT / "media" / "analysis-artifacts"
PIPELINE_KEY = "temporal_landmarks_baseline_a_v1"
PIPELINE_VERSION = "1.0.0"
IMPL_VERSION = "baseline-a-2026-09-05"
WORKER_ID = "run_pilot_standalone_01"


def get_db_password():
    pw = os.environ.get("DB_PASSWORD")
    if not pw:
        result = subprocess.check_output(
            ["grep", "^POSTGRES_PASSWORD", str(REPO_ROOT / ".env")]
        ).decode().strip().split("=", 1)
        pw = result[1].strip() if len(result) > 1 else ""
    return pw


def connect_db():
    pw = get_db_password()
    return psycopg2.connect(
        host="localhost", port=5433, dbname="diving_analyzer_db",
        user="diving", password=pw
    )


def compute_fingerprint(dive_id, media_key, pipeline_key, pipeline_version, params):
    payload = json.dumps({
        "dive_id": dive_id,
        "media_key": media_key or "",
        "input_checksum": "",
        "pipeline_key": pipeline_key,
        "pipeline_version": pipeline_version,
        "parameters": params,
    }, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def enqueue_run(conn, dive_id, photos_asset_id, media_key, media_role, fingerprint):
    """Create analysis_run + analysis_job. Returns (run_id, job_id, created_new)."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        # Check for existing non-terminal run with same fingerprint
        cur.execute("""
            SELECT id, run_uuid, status FROM analysis_runs
            WHERE spec_fingerprint = %s AND status IN ('pending','running','succeeded')
            LIMIT 1
        """, (fingerprint,))
        existing = cur.fetchone()
        if existing:
            if existing["status"] == "succeeded":
                cur.execute("SELECT id FROM analysis_jobs WHERE run_id=%s AND status='succeeded' LIMIT 1", (existing["id"],))
                job = cur.fetchone()
                return existing["id"], job["id"] if job else None, False
            # pending/running
            cur.execute("SELECT id FROM analysis_jobs WHERE run_id=%s AND status IN ('pending','leased','running') LIMIT 1", (existing["id"],))
            job = cur.fetchone()
            return existing["id"], job["id"] if job else None, False

        # Create run
        cur.execute("""
            INSERT INTO analysis_runs (
                dive_id, photos_asset_id, media_key, media_role,
                pipeline_key, pipeline_version, canonical_parameters,
                spec_fingerprint, status, implementation_version,
                environment_meta, forced
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'pending',%s,%s,false)
            RETURNING id, run_uuid
        """, (
            dive_id, photos_asset_id, media_key, media_role,
            PIPELINE_KEY, PIPELINE_VERSION, json.dumps({}),
            fingerprint, IMPL_VERSION,
            json.dumps({"script": "run_pilot_standalone.py", "host": "deb-serv",
                        "python": sys.version[:10]}),
        ))
        run = cur.fetchone()
        run_id = run["id"]

        # Create job
        cur.execute("""
            INSERT INTO analysis_jobs (run_id, status, attempt, max_attempts)
            VALUES (%s, 'pending', 1, 3)
            RETURNING id
        """, (run_id,))
        job_id = cur.fetchone()["id"]
        conn.commit()
        return run_id, job_id, True


def lease_job(conn, job_id, run_id):
    """Lease the job and mark run as running."""
    now = datetime.utcnow()
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE analysis_jobs SET status='leased', claimed_by=%s, claimed_at=%s,
                claimed_until=%s + INTERVAL '10 minutes', last_heartbeat_at=%s, updated_at=%s
            WHERE id=%s
        """, (WORKER_ID, now, now, now, now, job_id))
        cur.execute("""
            UPDATE analysis_runs SET status='running', started_at=COALESCE(started_at, %s)
            WHERE id=%s
        """, (now, run_id))
        conn.commit()


def persist_landmarks(conn, run_id, landmarks):
    """Upsert landmarks into DB."""
    with conn.cursor() as cur:
        for lm in landmarks:
            cur.execute("""
                INSERT INTO analysis_landmarks 
                    (run_id, landmark_key, frame_index, timestamp_seconds, confidence,
                     source, applicability, algorithm_key, algorithm_version, uncertainty_window_frames)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (run_id, landmark_key) DO UPDATE SET
                    frame_index=EXCLUDED.frame_index, timestamp_seconds=EXCLUDED.timestamp_seconds,
                    confidence=EXCLUDED.confidence, applicability=EXCLUDED.applicability
            """, (
                run_id, lm.landmark_key, lm.frame_index, lm.timestamp_seconds,
                lm.confidence, lm.source, lm.applicability,
                lm.algorithm_key, lm.algorithm_version, lm.uncertainty_window_frames,
            ))
    conn.commit()


def persist_phases(conn, run_id, lm_by_key):
    """Persist flight phases from landmarks."""
    with conn.cursor() as cur:
        def upsert(phase_key, start_lk, end_lk):
            s = lm_by_key.get(start_lk)
            e = lm_by_key.get(end_lk)
            if not s or not e:
                return
            cur.execute("""
                INSERT INTO analysis_phases
                    (run_id, phase_key, start_landmark_key, end_landmark_key,
                     start_frame, end_frame, start_seconds, end_seconds, source,
                     algorithm_key, algorithm_version)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'AUTO','baseline_a_motion_centroid','1.0.0')
                ON CONFLICT (run_id, phase_key) DO UPDATE SET
                    start_frame=EXCLUDED.start_frame, end_frame=EXCLUDED.end_frame,
                    start_seconds=EXCLUDED.start_seconds, end_seconds=EXCLUDED.end_seconds
            """, (run_id, phase_key, start_lk, end_lk,
                  s.frame_index, e.frame_index, s.timestamp_seconds, e.timestamp_seconds))

        upsert("flight_ascent", "takeoff", "apex")
        upsert("flight_descent", "apex", "water_contact")
        upsert("flight", "takeoff", "water_contact")
    conn.commit()


def persist_metrics(conn, run_id, lm_by_key, total_frames):
    """Persist temporal metrics."""
    def upsert(key, version, value, unit, phase_key=None):
        if value is None:
            return
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO analysis_metrics
                    (run_id, metric_key, metric_version, value_numeric, unit, phase_key,
                     producer_key, producer_version)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT DO NOTHING
            """, (run_id, key, version, value, unit, phase_key, PIPELINE_KEY, PIPELINE_VERSION))

    t_to = lm_by_key.get("takeoff")
    t_ap = lm_by_key.get("apex")
    t_wc = lm_by_key.get("water_contact")

    def ts(lm):
        return lm.timestamp_seconds if lm and lm.applicability == "APPLICABLE" else None

    to_s, ap_s, wc_s = ts(t_to), ts(t_ap), ts(t_wc)

    if to_s and wc_s:
        upsert("flight_duration_seconds", "v1", round(wc_s - to_s, 4), "s", "flight")
    if to_s and ap_s:
        upsert("ascent_duration_seconds", "v1", round(ap_s - to_s, 4), "s", "flight_ascent")
    if ap_s and wc_s:
        upsert("descent_duration_seconds", "v1", round(wc_s - ap_s, 4), "s", "flight_descent")
    if to_s and ap_s and wc_s:
        fl = wc_s - to_s
        if fl > 0:
            upsert("ascent_fraction", "v1", round((ap_s - to_s) / fl, 4), "", "flight")

    for lm, mk in [(t_to, "takeoff"), (t_ap, "apex"), (t_wc, "water_contact")]:
        if lm and lm.confidence is not None:
            key_map = {
                "takeoff": "landmark_proposer_confidence_takeoff",
                "apex": "landmark_proposer_confidence_apex",
                "water_contact": "landmark_proposer_confidence_water_contact",
            }
            upsert(key_map[mk], "v1", lm.confidence, "")

    if total_frames and total_frames > 0:
        for lm, mk in [(t_to, "takeoff"), (t_ap, "apex"), (t_wc, "water_contact")]:
            if lm and lm.frame_index is not None:
                upsert(f"{mk}_frame_normalized", "v1",
                       round(lm.frame_index / total_frames, 4), "")
    conn.commit()


def persist_artifact(conn, run_id, dive_id, run_uuid, diag: dict):
    """Write diagnostic JSON artifact to filesystem and register in DB."""
    import shutil, hashlib as _h
    # Write to tmp
    tmp_dir = ARTIFACT_ROOT / "_tmp" / run_uuid
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = tmp_dir / "diagnostic.json"
    with open(tmp_path, "w") as f:
        json.dump(diag, f, indent=2)

    # Checksum
    cs = _h.sha256()
    with open(tmp_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            cs.update(chunk)
    checksum = cs.hexdigest()
    size = tmp_path.stat().st_size

    # Move to final
    final_dir = ARTIFACT_ROOT / str(dive_id) / run_uuid
    final_dir.mkdir(parents=True, exist_ok=True)
    final_path = final_dir / "diagnostic.json"
    try:
        tmp_path.rename(final_path)
    except OSError:
        shutil.copy2(str(tmp_path), str(final_path))
        tmp_path.unlink()

    # Clean up tmp
    shutil.rmtree(str(tmp_dir), ignore_errors=True)

    rel_path = str(Path(str(dive_id)) / run_uuid / "diagnostic.json")

    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO analysis_artifacts
                (run_id, artifact_key, artifact_type, storage_path, checksum_sha256,
                 size_bytes, format, status, is_debug, producer_key, producer_version)
            VALUES (%s,'diagnostic_json','diagnostic_json',%s,%s,%s,'json','ready',true,%s,%s)
            ON CONFLICT (run_id, artifact_key) DO UPDATE SET
                storage_path=EXCLUDED.storage_path, checksum_sha256=EXCLUDED.checksum_sha256,
                size_bytes=EXCLUDED.size_bytes, status='ready'
        """, (run_id, rel_path, checksum, size, PIPELINE_KEY, PIPELINE_VERSION))
    conn.commit()


def succeed_run(conn, job_id, run_id):
    now = datetime.utcnow()
    with conn.cursor() as cur:
        cur.execute("UPDATE analysis_jobs SET status='succeeded', completed_at=%s, updated_at=%s WHERE id=%s",
                    (now, now, job_id))
        cur.execute("UPDATE analysis_runs SET status='succeeded', completed_at=%s WHERE id=%s",
                    (now, run_id))
    conn.commit()


def fail_run(conn, job_id, run_id, error):
    now = datetime.utcnow()
    with conn.cursor() as cur:
        cur.execute("UPDATE analysis_jobs SET status='failed', last_error=%s, completed_at=%s WHERE id=%s",
                    (error[:500], now, job_id))
        cur.execute("UPDATE analysis_runs SET status='failed', error_summary=%s, completed_at=%s WHERE id=%s",
                    (error[:500], now, run_id))
    conn.commit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-dives", type=int, default=20)
    parser.add_argument("--dive-id", type=int)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    # Load proposer
    proposer_path = Path(__file__).parent / "proposer_baseline_a.py"
    import importlib.util
    spec = importlib.util.spec_from_file_location("proposer_baseline_a", proposer_path)
    proposer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(proposer)

    # Load manifest
    manifest_path = REPO_ROOT / "docs" / "science" / "PILOT_MANIFEST_V1.json"
    with open(manifest_path) as f:
        manifest = json.load(f)

    dives = manifest["dives"]
    if args.dive_id:
        dives = [d for d in dives if d["dive_id"] == args.dive_id]
    dives = dives[:args.max_dives]
    log.info("Processing %d pilot dives (dry_run=%s)", len(dives), args.dry_run)

    results = []
    for i, dive in enumerate(dives):
        dive_id = dive["dive_id"]
        media_key = dive["media_key"]
        photos_asset_id = dive["photos_asset_id"]
        log.info("[%d/%d] dive %d %s", i+1, len(dives), dive_id, dive["dive_code"])

        if args.dry_run:
            log.info("  [DRY RUN] skip")
            continue

        # Resolve clip path
        clip_path = MEDIA_CACHE_ROOT / "proxy_360p" / media_key[:2] / media_key[2:4] / f"{media_key}.mp4"
        if not clip_path.exists():
            log.error("  Clip not found: %s", clip_path)
            results.append({"dive_id": dive_id, "status": "failed", "error": "clip_not_found"})
            continue

        conn = connect_db()
        run_id = job_id = None
        try:
            fp = compute_fingerprint(dive_id, media_key, PIPELINE_KEY, PIPELINE_VERSION, {})
            run_id, job_id, created = enqueue_run(conn, dive_id, photos_asset_id, media_key, "proxy_360p", fp)

            # Check if already done
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT status, run_uuid FROM analysis_runs WHERE id=%s", (run_id,))
                run_row = cur.fetchone()

            if not created and run_row["status"] == "succeeded":
                log.info("  [SKIP] already succeeded: %s", run_row["run_uuid"])
                results.append({"dive_id": dive_id, "status": "skipped", "run_uuid": run_row["run_uuid"]})
                conn.close()
                continue

            run_uuid = run_row["run_uuid"]
            lease_job(conn, job_id, run_id)

            # Run proposer
            result = proposer.propose_landmarks(
                clip_path=str(clip_path),
                media_key=media_key,
                dive_id=dive_id,
                compute_checksum=True,
            )

            # Update input_checksum
            if result.input_checksum_sha256:
                with conn.cursor() as cur:
                    cur.execute("UPDATE analysis_runs SET input_checksum_sha256=%s WHERE id=%s",
                                (result.input_checksum_sha256, run_id))
                conn.commit()

            # Persist
            persist_landmarks(conn, run_id, result.landmarks)

            lm_by_key = {lm.landmark_key: lm for lm in result.landmarks
                         if lm.applicability == "APPLICABLE" and lm.frame_index is not None}
            persist_phases(conn, run_id, lm_by_key)
            persist_metrics(conn, run_id, lm_by_key, result.total_frames)

            diag = {
                "pipeline_key": PIPELINE_KEY, "pipeline_version": PIPELINE_VERSION,
                "run_uuid": str(run_uuid), "dive_id": dive_id,
                "fps": result.fps, "total_frames": result.total_frames,
                "duration_seconds": result.duration_seconds,
                "input_checksum_sha256": result.input_checksum_sha256,
                "landmarks": [asdict(lm) for lm in result.landmarks],
                "diagnostics": result.diagnostics,
                "generated_at": datetime.utcnow().isoformat(),
                "note": "EXPERIMENTAL — AUTO proposal, not validated",
            }
            persist_artifact(conn, run_id, dive_id, str(run_uuid), diag)
            succeed_run(conn, job_id, run_id)

            ordering_ok = result.diagnostics.get("ordering_valid", False)
            log.info("  OK ordering=%s lm_count=%d", ordering_ok, len(result.landmarks))
            results.append({
                "dive_id": dive_id, "status": "succeeded", "run_uuid": str(run_uuid),
                "ordering_valid": ordering_ok,
                "landmarks": {lm.landmark_key: lm.frame_index for lm in result.landmarks},
                "fps": result.fps,
                "duration": result.duration_seconds,
            })

        except Exception as e:
            log.error("  FAILED: %s", e)
            import traceback; traceback.print_exc()
            if run_id and job_id:
                try:
                    fail_run(conn, job_id, run_id, str(e))
                except Exception:
                    pass
            results.append({"dive_id": dive_id, "status": "failed", "error": str(e)})
        finally:
            conn.close()

    # Summary
    print(f"\n=== PILOT RUN SUMMARY ({len(results)} dives) ===")
    succeeded = [r for r in results if r.get("status") == "succeeded"]
    failed = [r for r in results if r.get("status") == "failed"]
    ordering_ok = [r for r in succeeded if r.get("ordering_valid")]
    print(f"Succeeded: {len(succeeded)}/{len(results)} | Ordering valid: {len(ordering_ok)}/{len(succeeded)}")
    for r in results:
        lm_str = ""
        if "landmarks" in r:
            lm_str = f" {r['landmarks']}"
        print(f"  dive {r['dive_id']:5d} {r.get('status','?'):12s}{lm_str}")

    # Save JSON report
    report_path = REPO_ROOT / "docs" / "science" / "PILOT_LANDMARK_PROPOSALS.json"
    with open(report_path, "w") as f:
        json.dump({
            "run_date": datetime.utcnow().isoformat(),
            "pipeline_key": PIPELINE_KEY,
            "pipeline_version": PIPELINE_VERSION,
            "n_dives": len(results),
            "n_succeeded": len(succeeded),
            "n_ordering_valid": len(ordering_ok),
            "dives": results,
        }, f, indent=2)
    log.info("Report saved: %s", report_path)


if __name__ == "__main__":
    main()
