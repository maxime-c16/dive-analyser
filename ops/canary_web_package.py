#!/usr/bin/env python3
"""Bounded web_package canary admission + verification tool (DRY-RUN default).

Local-only ops helper. Queues REAL ``web_package`` MediaJob rows through
the normal job machinery (same ``create_or_reuse_media_job`` as
ingestion) for an explicit private allowlist -- never a publisher
bypass, never fake HD, never broad ingestion. The Mac worker leases
and publishes through the reviewed fenced slot path; this tool only
admits (serially) and verifies.

Safety contract (enforced, not documented-only):

- DRY-RUN by default. Nothing writes without ``--apply``.
- Manifest is a PRIVATE JSON file OUTSIDE the repo (0600), e.g.
  ``~/.config/diveanalyzer/canary-manifest.json``::
      {"phase": 1, "clips": ["<video_uuid>", "..."]}
  Explicit UUIDs only. Never committed to Git (refused when the path
  sits inside a git checkout).
- Serial admission: at most ONE new queue per run, never while ANY
  package job is active fleet-wide (queued/active counts as blocking
  except terminal ready/failed/unavailable), never beyond the
  phase caps (phase1 <= 5, phase2 <= 25 additional, total <= 30).
- Idempotent/resumable: clips already ``ready`` (all applicable slots
  durable) are skipped; an existing active job for the clip blocks a
  duplicate; ``--state-dir`` records admitted/verified UUIDs so a
  rerun resumes where it stopped.
- Budget preflight (estimate) + server-side hard guard: the tool
  refuses when the worst-case package estimate does not fit the
  remaining 2 GiB; the slot route re-enforces the cap authoritatively
  at publish time (see ``canary_budget.check_publish_budget``).
- Stop conditions (fail closed): ``--mac-free-bytes`` /
  ``--server-cache-free-bytes`` are OPERATOR-PROVIDED host facts (this
  tool never SSHes/probes prod); ``--apply`` refuses without them or
  when below 8 GiB / 25 GiB. Consecutive failures >=
  ``--max-consecutive-failures`` (tracked in state) stop admission.
  Unknown source (no canonical revision, dims/size/duration unknown)
  skips the clip -- never guessed.
- Secrets: runtime config only (DATABASE_URL et al). This tool NEVER
  prints secrets, keys, signed URLs, or tokens. Status output is
  AGGREGATE (counts + bytes) plus per-clip state words, no byte dumps.

Subcommands (all read-only except ``admit --apply``)::

    inventory --manifest M            bounded readiness per clip
    admit [--apply] --manifest M --phase 1|2 --mac-free-bytes B \\
        --server-cache-free-bytes B   plan (default) or queue ONE job
    verify --manifest M               bounded terminal-state check +
                                      manual proof checklist

DB access uses ``DATABASE_URL`` from the runtime environment (same
convention as the server). No B2 writes, no job mutation in
``inventory``/``verify`` (read-only session, rolled back).
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

# NOTE: loaded by file path (not `from app.services...`) so `--help`
# and manifest validation work with stdlib-only python. DB-touching
# paths still need the backend venv (sqlalchemy + app models) at
# runtime -- run those with the backend venv python or equivalent.
def _load_canary_budget():
    import importlib.util as _ilu

    _p = REPO_ROOT / "backend" / "app" / "services" / "canary_budget.py"
    _spec = _ilu.spec_from_file_location("canary_budget_standalone", _p)
    _mod = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    return _mod


_cb = _load_canary_budget()
CANARY_BUDGET_BYTES = _cb.CANARY_BUDGET_BYTES
CANARY_JOB_MAX_ATTEMPTS = _cb.CANARY_JOB_MAX_ATTEMPTS
CANARY_JOB_PRIORITY = _cb.CANARY_JOB_PRIORITY
CANARY_PHASE1_MAX_CLIPS = _cb.CANARY_PHASE1_MAX_CLIPS
CANARY_TOTAL_MAX_CLIPS = _cb.CANARY_TOTAL_MAX_CLIPS
MIN_MAC_DATA_FREE_BYTES = _cb.MIN_MAC_DATA_FREE_BYTES
MIN_SERVER_CACHE_FREE_BYTES = _cb.MIN_SERVER_CACHE_FREE_BYTES
CanaryBudgetExceeded = _cb.CanaryBudgetExceeded
canary_ledger_bytes = _cb.canary_ledger_bytes
check_phase_count = _cb.check_phase_count
validate_manifest_uuids = _cb.validate_manifest_uuids
worst_case_package_bytes = _cb.worst_case_package_bytes

TERMINAL_JOB_STATUSES = {"ready", "failed", "unavailable"}
ACTIVE_JOB_STATUSES = {
    "queued",
    "waiting_for_mac",
    "claimed",
    "materializing",
    "exporting",
    "transcoding",
    "uploading",
    "verifying",
}


def _refuse_inside_git(path: Path) -> None:
    p = path.resolve()
    for parent in [p] + list(p.parents):
        if (parent / ".git").exists():
            raise SystemExit(
                f"REFUSED: manifest/state path {p} sits inside a git checkout "
                f"({parent}/.git). Keep canary manifests outside the repo (private 0600)."
            )


def _check_mode_0600(path: Path, what: str) -> None:
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        return
    if mode & 0o077:
        print(
            f"WARNING: {what} {path} has mode {oct(mode)} (expected 0600); "
            "fix with: chmod 600 " + str(path),
            file=sys.stderr,
        )


def load_manifest(path: Path) -> tuple[int, list[str]]:
    _refuse_inside_git(path)
    _check_mode_0600(path, "manifest")
    try:
        raw = json.loads(path.read_text())
    except FileNotFoundError:
        raise SystemExit(f"manifest not found: {path}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"manifest is not valid JSON: {exc}")
    phase = raw.get("phase", 1)
    try:
        phase = int(phase)
    except (TypeError, ValueError):
        raise SystemExit("manifest 'phase' must be 1 or 2")
    clips = raw.get("clips", [])
    if not isinstance(clips, list):
        raise SystemExit("manifest 'clips' must be a list of video_uuid strings")
    return phase, validate_manifest_uuids(clips)


def _engine():
    from sqlalchemy import create_engine

    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise SystemExit("DATABASE_URL is not set (runtime config required; no new tokens).")
    return create_engine(url, pool_pre_ping=True)


def _session(db_url_engine):
    from sqlalchemy.orm import sessionmaker

    return sessionmaker(bind=db_url_engine, autoflush=False)()


def clip_readiness(db, video_uuid: str) -> dict:
    """Bounded per-clip readiness (single-clip queries only, no scans)."""
    from app.models.photos_asset import PhotosAsset

    out: dict = {"video_uuid": video_uuid, "ok": False}
    asset = (
        db.query(PhotosAsset).filter(PhotosAsset.video_uuid == video_uuid).limit(1).first()
    )
    if asset is None:
        out.update(status="unknown_asset", reason="no photos_asset row for video_uuid")
        return out
    out["asset_id"] = asset.id
    try:
        from app.services.derivative_publisher import (
            MissingSourceError,
            resolve_canonical_source_revision,
        )

        rev, blob, _loc = resolve_canonical_source_revision(db, video_uuid)
    except MissingSourceError as exc:
        out.update(status="no_canonical_source", reason=str(exc)[:160])
        return out
    except Exception as exc:
        out.update(status="source_lookup_error", reason=f"{type(exc).__name__}")
        return out
    out["source_sha256"] = (rev.blob_sha256 or "")[:12] + "..."
    out["source_revision_id"] = int(rev.id)
    w = getattr(blob, "width", None)
    h = getattr(blob, "height", None)
    try:
        w, h = (int(w) if w else None), (int(h) if h else None)
    except (TypeError, ValueError):
        w, h = None, None
    size = getattr(blob, "byte_size", None)
    dur = getattr(blob, "duration_seconds", None)
    try:
        dur_f = float(dur) if dur is not None else None
    except (TypeError, ValueError):
        dur_f = None
    out["dims"] = f"{w}x{h}" if (w and h) else "unknown"
    out["source_bytes"] = size
    out["duration_s"] = dur_f
    if not (w and h and w > 0 and h > 0):
        out.update(status="dims_unknown", reason="canonical MediaBlob dims unknown; refusing (fail closed)")
        return out
    if not size or int(size) <= 0 or not dur_f or dur_f <= 0:
        out.update(status="source_unknown", reason="source size/duration unknown; refusing (fail closed)")
        return out
    try:
        from app.services.web_packages import check_small_source_alias  # noqa: F401
        from app.services.derivative_read import resolve_clip_derivatives

        clip = resolve_clip_derivatives(db, video_uuid)
        states = {r: (clip.roles.get(r).state if clip.roles.get(r) else "?") for r in ("hq", "light", "poster")}
    except Exception as exc:
        out.update(status="read_error", reason=f"{type(exc).__name__}")
        return out
    out["derivative_states"] = states
    if all(s == "ready" for s in states.values()):
        out.update(status="already_ready", ok=True, reason="all applicable slots durable")
        return out
    from app.models.media import MediaJob

    active = (
        db.query(MediaJob.id, MediaJob.status)
        .filter(
            MediaJob.photos_asset_id == asset.id,
            MediaJob.rendition == "web_package",
            MediaJob.status.in_(sorted(ACTIVE_JOB_STATUSES)),
        )
        .limit(5)
        .all()
    )
    if active:
        out.update(
            status="job_active",
            reason=f"{len(active)} active web_package job(s)",
            job_statuses=sorted({s for _, s in active}),
        )
        return out
    try:
        out["worst_case_bytes"] = worst_case_package_bytes(int(size), float(dur_f))
    except ValueError as exc:
        out.update(status="source_unknown", reason=str(exc)[:160])
        return out
    out.update(status="ready_to_admit", ok=True)
    return out


def fleet_package_blocked(db) -> dict:
    """Fleet-wide serial gate: any active web_package job blocks admission."""
    from app.models.media import MediaJob

    active = (
        db.query(MediaJob.id)
        .filter(
            MediaJob.rendition == "web_package",
            MediaJob.status.in_(sorted(ACTIVE_JOB_STATUSES)),
        )
        .limit(1)
        .all()
    )
    return {"blocked": len(active) > 0, "active_packages": len(active)}


def load_state(state_dir: Path) -> dict:
    _refuse_inside_git(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(state_dir, 0o700)
    except OSError:
        pass
    f = state_dir / "canary-state.json"
    _check_mode_0600(f, "state file")
    if not f.exists():
        return {"admitted": [], "verified": [], "consecutive_failures": 0}
    try:
        raw = json.loads(f.read_text())
    except json.JSONDecodeError:
        return {"admitted": [], "verified": [], "consecutive_failures": 0}
    return {
        "admitted": list(raw.get("admitted", [])),
        "verified": list(raw.get("verified", [])),
        "consecutive_failures": int(raw.get("consecutive_failures", 0) or 0),
    }


def save_state(state_dir: Path, state: dict) -> None:
    f = state_dir / "canary-state.json"
    tmp = state_dir / "canary-state.json.tmp"
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True))
    os.chmod(tmp, 0o600)
    os.replace(tmp, f)


def cmd_inventory(args) -> int:
    phase, clips = load_manifest(Path(args.manifest))
    eng = _engine()
    db = _session(eng)
    try:
        committed = canary_ledger_bytes(db)
        fleet = fleet_package_blocked(db)
        print(f"phase={phase} manifest_clips={len(clips)} "
              f"committed_derivative_bytes={committed} "
              f"remaining_budget_bytes={CANARY_BUDGET_BYTES - committed} "
              f"fleet_package_active={int(fleet['blocked'])}")
        shown = 0
        for uuid in clips[:30]:
            r = clip_readiness(db, uuid)
            ok = "OK " if r.get("ok") else "SKIP"
            extra = r.get("reason", r.get("status", ""))
            print(f"  [{ok}] {uuid[:8]}... status={r.get('status')} {extra}")
            shown += 1
        print(f"inventory done: {shown} clip(s) checked (bounded, LIMIT per clip). DRY-RUN: no writes.")
    finally:
        db.rollback()
        db.close()
    return 0


def cmd_admit(args) -> int:
    phase_arg = getattr(args, "phase", None)
    manifest_path = Path(args.manifest)
    state_dir = Path(args.state_dir).expanduser()
    phase_manifest, clips = load_manifest(manifest_path)
    phase = int(phase_arg) if phase_arg is not None else phase_manifest
    state = load_state(state_dir)
    if state.get("consecutive_failures", 0) >= int(args.max_consecutive_failures):
        print(f"REFUSED: consecutive_failures={state['consecutive_failures']} >= "
              f"max {args.max_consecutive_failures}; investigate before new admissions.")
        return 2
    try:
        check_phase_count(phase, len(clips), len(state.get("admitted", [])))
    except ValueError as exc:
        print(f"REFUSED: {exc}")
        return 2
    if phase == 2 and len(state.get("verified", [])) < CANARY_PHASE1_MAX_CLIPS and len(state.get("admitted", [])) >= CANARY_PHASE1_MAX_CLIPS:
        print("REFUSED: phase 2 requires 100% phase-1 proof recorded in state "
              "(all 5 verified); run `verify` first.")
        return 2

    eng = _engine()
    db = _session(eng)
    try:
        mac_free = args.mac_free_bytes
        srv_free = args.server_cache_free_bytes
        if args.apply and (mac_free is None or srv_free is None):
            print("REFUSED: --apply requires operator-provided --mac-free-bytes and "
                  "--server-cache-free-bytes (host facts, never probed from here).")
            return 2
        if mac_free is not None and int(mac_free) < MIN_MAC_DATA_FREE_BYTES:
            print(f"REFUSED: Mac Data free {int(mac_free)} < {MIN_MAC_DATA_FREE_BYTES} (8 GiB); stop new admissions.")
            return 2
        if srv_free is not None and int(srv_free) < MIN_SERVER_CACHE_FREE_BYTES:
            print(f"REFUSED: server cache volume free {int(srv_free)} < {MIN_SERVER_CACHE_FREE_BYTES} (25 GiB).")
            return 2
        committed = canary_ledger_bytes(db)
        remaining = CANARY_BUDGET_BYTES - committed
        fleet = fleet_package_blocked(db)
        if fleet["blocked"]:
            print("BLOCKED: a web_package job is already active fleet-wide; "
                  "serial admission -- wait for its terminal state, then re-run.")
            return 3
        admitted_set = set(state.get("admitted", []))
        plan = None
        for uuid in clips:
            r = clip_readiness(db, uuid)
            if r.get("status") in ("already_ready",):
                admitted_set.add(uuid)
                continue
            if not r.get("ok"):
                continue
            est = int(r["worst_case_bytes"])
            if est > remaining:
                print(f"REFUSED: clip {uuid[:8]}... worst-case {est} > remaining {remaining}; "
                      "budget preflight fails (estimate only; hard cap is server-enforced).")
                return 2
            plan = (uuid, r, est)
            break
        if plan is None:
            print("nothing_admittable: every manifest clip is ready/active/unknown; no queue change.")
            return 0
        uuid, r, est = plan
        if not args.apply:
            print(f"DRY-RUN plan: would queue ONE web_package job for {uuid[:8]}... "
                  f"(asset_id={r.get('asset_id')} priority={CANARY_JOB_PRIORITY} "
                  f"max_attempts={CANARY_JOB_MAX_ATTEMPTS} worst_case_bytes={est} "
                  f"remaining_budget_bytes={remaining}). Re-run with --apply to admit.")
            return 0
        from app.models.photos_asset import PhotosAsset
        from app.services.media_jobs import WEB_PACKAGE_RENDITION, create_or_reuse_media_job

        asset = db.query(PhotosAsset).filter(PhotosAsset.video_uuid == uuid).limit(1).first()
        if asset is None:
            print(f"REFUSED: asset vanished for {uuid[:8]}...")
            return 2
        media_key, job, created = create_or_reuse_media_job(
            db, asset, WEB_PACKAGE_RENDITION, "canary_web_package"
        )
        job.priority = CANARY_JOB_PRIORITY
        job.max_attempts = min(int(job.max_attempts or CANARY_JOB_MAX_ATTEMPTS), CANARY_JOB_MAX_ATTEMPTS)
        db.add(job)
        db.commit()
        admitted_set.add(uuid)
        state["admitted"] = sorted(admitted_set)
        save_state(state_dir, state)
        print(f"ADMITTED job_id={job.id} created={int(created)} priority={job.priority} "
              f"for {uuid[:8]}... (1 job this run; serial gate holds until terminal).")
        return 0
    except CanaryBudgetExceeded as exc:
        db.rollback()
        print(f"REFUSED: {exc}")
        return 2
    except SystemExit:
        raise
    except Exception as exc:
        db.rollback()
        print(f"ERROR: {type(exc).__name__}; no admission performed.")
        return 1
    finally:
        try:
            db.close()
        except Exception:
            pass


def cmd_verify(args) -> int:
    _, clips = load_manifest(Path(args.manifest))
    state_dir = Path(args.state_dir).expanduser()
    state = load_state(state_dir)
    eng = _engine()
    db = _session(eng)
    try:
        committed = canary_ledger_bytes(db)
        print(f"committed_derivative_bytes={committed} "
              f"remaining_budget_bytes={CANARY_BUDGET_BYTES - committed}")
        verified: set[str] = set(state.get("verified", []))
        for uuid in clips[:30]:
            r = clip_readiness(db, uuid)
            mark = "READY " if r.get("status") == "already_ready" else ("ACTIVE" if r.get("status") == "job_active" else "PENDING")
            print(f"  [{mark}] {uuid[:8]}... status={r.get('status')} {r.get('reason', '')}")
            if r.get("status") == "already_ready":
                verified.add(uuid)
        if verified != set(state.get("verified", [])):
            state["verified"] = sorted(verified)
            save_state(state_dir, state)
        print("---")
        print("Manual proof checklist (operator runs; device Safari NOT claimed):")
        print("  1. B2 full-GET SHA: for each ready slot, authorized Library play URL")
        print("     (302) -> follow with user session cookie -> sha256sum full bytes ==")
        print("     ledger derivative_blob_sha256; ffprobe format/tags/faststart + frame")
        print("     cadence; original revision bytes untouched (source SHA re-read).")
        print("  2. Library authorized route: 302 to presigned B2 with auth; Range")
        print("     206 with correct content-type; expired-grant replay denied;")
        print("     logged-out request denied (no auth bypass for probes).")
        print("  3. Record outcomes in state; phase 2 only after 5/5 READY + proofs.")
        print("verify done (read-only DB; no bytes fetched by this tool).")
    finally:
        db.rollback()
        db.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Bounded web_package canary ops (dry-run default).")
    ap.add_argument("--manifest", required=True, help="private JSON manifest OUTSIDE the repo (0600)")
    ap.add_argument("--state-dir", default="~/.config/diveanalyzer/canary",
                    help="private state dir OUTSIDE the repo (default: %(default)s)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("inventory", help="bounded read-only readiness")
    ad = sub.add_parser("admit", help="plan (default) or queue ONE job with --apply")
    ad.add_argument("--apply", action="store_true", help="explicit apply; without it, dry-run only")
    ad.add_argument("--phase", type=int, choices=[1, 2], default=None)
    ad.add_argument("--mac-free-bytes", type=int, default=None)
    ad.add_argument("--server-cache-free-bytes", type=int, default=None)
    ad.add_argument("--max-consecutive-failures", type=int, default=2)
    sub.add_parser("verify", help="bounded terminal-state check + proof checklist")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "inventory":
        return cmd_inventory(args)
    if args.cmd == "admit":
        return cmd_admit(args)
    if args.cmd == "verify":
        return cmd_verify(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
