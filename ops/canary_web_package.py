#!/usr/bin/env python3
"""Bounded web_package canary admission + verification tool (DRY-RUN default).

Local-only ops helper. Queues REAL ``web_package`` MediaJob rows through
the normal job machinery (same ``create_or_reuse_media_job`` as
ingestion) for an explicit private allowlist -- never a publisher
bypass, never fake HD, never broad ingestion. The Mac worker leases
and publishes through the reviewed fenced slot path; this tool only
admits (serially), records readiness, and records explicit proofs.

Safety contract (enforced, not documented-only):

- DRY-RUN by default. Nothing writes without ``--apply`` (admit) or
  ``prove`` (explicit proof record).
- Manifests are PRIVATE JSON files OUTSIDE the repo (0600), e.g.
  ``~/.config/diveanalyzer/canary-manifest.json``::
      {"phase": 1, "clips": ["<video_uuid>", "..."]}
  Explicit UUIDs only. Never committed to Git (refused when the path
  sits inside a git checkout).
- Serial admission: at most ONE new queue per run, never while ANY
  package job is active fleet-wide (queued/active counts as blocking
  except terminal ready/failed/unavailable), never beyond the
  phase caps (first admission <= 5, phase2 <= 25 additional only after
  EXACTLY 5 distinct phase-1 proven, total <= 30).
  Concurrent admits serialize on a PG advisory lock + a local
  state-dir file lock (held only for the short DB decision, never
  across network).
- Idempotent/resumable: clips already ``ready`` (all applicable slots
  durable) are skipped; an existing active job blocks a duplicate and
  is reused after a crash (DB is authoritative, ``--state-dir`` is a
  resume hint, never the cap authority); caps count only NEW unique
  IDs so re-listing an admitted clip costs zero.
- Budget (hard, orphans included): the tool refuses when the
  worst-case package estimate does not fit the remaining 2 GiB; the
  publisher enforces the cap authoritatively with an atomic exact-key
  reservation ledger (``canary_budget.reserve_canary_upload`` on the
  ACTUAL bytes with bucket+object_key) BEFORE B2 bytes stream, and the
  canary slot route adds a prestream size-cap-only advisory gate (no
  durable row: untrusted claims never consume committed budget for
  another job). Same-key retry dedupes; overshoot is refused with 409.
- ``ready`` != ``proven``: ``verify`` records ledger-readiness only
  (``ready_seen``) and prints the manual proof checklist. Phase 2
  requires EXPLICIT proof records (``prove --proof P.json``) for
  EXACTLY 5 distinct phase-1 clips (all admitted + proven; a smaller
  first wave never unlocks phase 2) plus a durable DB
  cohort check (a reset state dir can never bypass total-30).
- Stop conditions (fail closed): ``--apply`` requires ``--host-facts``
  (private JSON with free bytes, memory pressure, fresh ``checked_at``
  <= 15 min, absolute disk paths; the tool never SSHes/probes prod)
  showing Mac Data free >= 8 GiB, server cache >= 25 GiB, and
  ``mac_memory_pressure == "normal"``. Consecutive failures >=
  ``--max-consecutive-failures`` (tracked in state) stop admission.
  Unknown source (no canonical revision, dims/size/duration unknown)
  skips the clip -- never guessed.
- Secrets: runtime config only (DATABASE_URL et al). This tool NEVER
  prints secrets, keys, signed URLs, or tokens. Status output is
  AGGREGATE (counts + bytes) plus per-clip state words, no byte dumps.

Subcommands (``admit --apply`` and ``prove`` write; all else read-only)::

    inventory --manifest M            bounded readiness per clip
    admit [--apply] --manifest M --phase 1|2 --host-facts F.json
        [--phase1-manifest P1]        plan (default) or queue ONE job
    verify --manifest M               bounded readiness check (records
                                      ready_seen only, never proven) +
                                      manual proof checklist
    prove --manifest M --proof P.json validate a structured proof
                                      record against the DB ledger and
                                      mark the clip proven

DB access uses ``DATABASE_URL`` from the runtime environment (same
convention as the server). No B2 writes, no job mutation in
``inventory``/``verify`` (read-only session, rolled back).
"""

from __future__ import annotations

import argparse
import contextlib
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
#: Hard cap for --max-consecutive-failures: the stop is 2 by design
#: (mirrors CANARY_JOB_MAX_ATTEMPTS). Larger values would let
#: --max999 bypass the user-2 stop, so they are refused fail-closed.
MAX_CONSECUTIVE_FAILURES_HARD_CAP = 2
#: Bounded scan for the durable failure streak (fleet <= 30; 10 is ample
#: to prove a trailing streak of 2 without an unbounded table scan).
CANARY_FAILURE_SCAN_LIMIT = 10
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


@contextlib.contextmanager
def _admit_file_lock(state_dir: Path):
    """Local serial lock for concurrent admits (held for DB decision only)."""
    state_dir.mkdir(parents=True, exist_ok=True)
    lock_path = state_dir / "canary-admit.lock"
    try:
        import fcntl  # POSIX only

        fh = open(lock_path, "w")
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            fh.close()
    except ImportError:
        # Non-POSIX: PG advisory lock still serializes across hosts.
        yield


def _pg_admit_lock(db) -> None:
    try:
        _cb._advisory_xact_lock(db, _cb._CANARY_ADMIT_LOCK)
    except Exception:
        pass


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


def validate_max_consecutive_failures(raw) -> int:
    """Require a positive bounded limit (1..2). Fail closed.

    The stop is 2 by design; --max999 (or 0/negative) would bypass the
    user-2 stop or disable it, so anything outside 1..2 is refused.
    """
    try:
        v = int(raw)
    except (TypeError, ValueError):
        raise ValueError(
            f"--max-consecutive-failures must be 1..{MAX_CONSECUTIVE_FAILURES_HARD_CAP}"
        )
    if v < 1 or v > MAX_CONSECUTIVE_FAILURES_HARD_CAP:
        raise ValueError(
            f"--max-consecutive-failures must be 1..{MAX_CONSECUTIVE_FAILURES_HARD_CAP} "
            f"(got {v}); larger values would bypass the 2-failure stop"
        )
    return v


def db_consecutive_canary_failures(db, limit: int = CANARY_FAILURE_SCAN_LIMIT) -> int:
    """Trailing consecutive canary failures from DURABLE job outcomes.

    Bounded scan of the latest canary web_package jobs (newest first,
    one row per job so retries/idempotent re-runs never double-count
    the same job). Terminal ``failed``/``unavailable`` extend the
    streak; terminal ``ready`` resets it (a durable success breaks the
    streak); active (non-terminal) rows are skipped. Only
    ``job.status == "failed"`` (or unavailable) counts -- lease attempt
    counters alone never count. A reset state dir cannot bypass this:
    the DB is authoritative. Any DB error raises (callers fail closed).
    """
    from app.models.media import MediaJob

    cap = max(int(limit), 1)
    try:
        rows = (
            db.query(MediaJob.status)
            .filter(
                MediaJob.rendition == "web_package",
                MediaJob.request_reason == _cb.CANARY_JOB_REASON,
            )
            .order_by(MediaJob.id.desc())
            .limit(cap + 1)
            .all()
        )
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        raise
    streak = 0
    for (status,) in rows[:cap]:
        s = str(status or "")
        if s in ("failed", "unavailable"):
            streak += 1
            continue
        if s == "ready":
            break
        continue
    return streak


def load_state(state_dir: Path) -> dict:
    _refuse_inside_git(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(state_dir, 0o700)
    except OSError:
        pass
    f = state_dir / "canary-state.json"
    _check_mode_0600(f, "state file")
    base = {"admitted": [], "ready_seen": [], "proven": [], "consecutive_failures": 0}
    if not f.exists():
        return base
    try:
        raw = json.loads(f.read_text())
    except json.JSONDecodeError:
        return base
    # Migrate legacy `verified` (auto-ready) -> `ready_seen`, NEVER proven.
    legacy_verified = list(raw.get("verified", []) or [])
    ready_seen = list(raw.get("ready_seen", []) or legacy_verified or [])
    return {
        "admitted": list(raw.get("admitted", []) or []),
        "ready_seen": ready_seen,
        "proven": list(raw.get("proven", []) or []),
        "consecutive_failures": int(raw.get("consecutive_failures", 0) or 0),
    }


def save_state(state_dir: Path, state: dict) -> None:
    f = state_dir / "canary-state.json"
    tmp = state_dir / "canary-state.json.tmp"
    payload = {
        "admitted": sorted(set(state.get("admitted", []) or [])),
        "ready_seen": sorted(set(state.get("ready_seen", []) or [])),
        "proven": sorted(set(state.get("proven", []) or [])),
        "consecutive_failures": int(state.get("consecutive_failures", 0) or 0),
    }
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
    os.chmod(tmp, 0o600)
    os.replace(tmp, f)


def _db_admitted_uuids(db) -> set[str]:
    # Fail closed: a DB/cohort error must refuse admission, never look
    # like an empty cohort that bypasses the total-30 cap.
    return set(_cb.db_admitted_uuids(db))


def _load_phase1_cohort(path_arg) -> list[str]:
    if not path_arg:
        return []
    _, clips = load_manifest(Path(path_arg))
    return clips


PROOF_REQUIRED_CHECKS = (
    "b2_full_get_sha_match",
    "ffprobe_clean",
    "frame_cadence_match",
    "library_auth_302",
    "range_206",
    "grant_expiry_checked",
    "logged_out_denied",
    "source_bytes_sha_match",
    "original_storage_integrity_checked",
)

#: Exact method string emitted by the B2 source re-read collector.
SOURCE_INTEGRITY_METHOD = "full_get_after_publication"

# Cadence timing tolerances (mirror the collector: exact frames, timing
# within container rounding; per-frame PTS exact never claimed).
_CADENCE_DURATION_TOL_S = 0.15
_CADENCE_FPS_REL_TOL = 0.02
_CADENCE_FPS_ABS_TOL = 0.15


def _validate_source_integrity_evidence(proof: dict, slots: dict) -> dict:
    """Validate B2 source re-read evidence (fail closed, no DB).

    Proofs containing video slots (hq/light) MUST carry
    ``source_integrity_evidence`` from an actual credential-free B2
    full GET of the canonical original AFTER publication::

        {"sha": "<64hex>", "size": 123,
         "measured_at": "<ISO-8601>", "method": "full_get_after_publication"}

    - ``sha`` must equal the proof ``source_sha256`` (bound canonical
      bytes; local scratch/claims never trusted).
    - ``size`` must be a positive int (cross-checked against the DB blob
      in ``crosscheck_proof_db``).
    - ``method`` must be exactly ``full_get_after_publication`` (local
      hash/metadata methods refused).
    - Secret-bearing keys (url, presigned, location, query, signature,
      credential, token, cookie, authorization) are refused as leaks.
    """
    video_roles = {r for r in slots if r in ("hq", "light")}
    ev = proof.get("source_integrity_evidence")
    if not video_roles:
        if ev is not None:
            raise ValueError("proof: source_integrity_evidence is video-only; omit it")
        return {}
    if not isinstance(ev, dict):
        raise ValueError("proof: source_integrity_evidence is required for video slots "
                         "(actual B2 source re-read, not local scratch)")
    for banned in ("url", "presigned", "location", "query", "signature",
                   "credential", "token", "cookie", "authorization", "secret"):
        for key in ev:
            if banned in str(key).lower():
                raise ValueError(f"proof: source_integrity_evidence.{key} must not carry secrets/URLs")
        for key, value in ev.items():
            if isinstance(value, str) and banned in value.lower() and "://" in value:
                raise ValueError("proof: source_integrity_evidence must not embed URLs/secrets")
    sha = ev.get("sha")
    if not isinstance(sha, str):
        raise ValueError("proof: source_integrity_evidence.sha is required")
    _cb.normalize_object_sha(sha)
    if sha.strip().lower() != str(proof.get("source_sha256", "")).strip().lower():
        raise ValueError("proof: source_integrity_evidence.sha must equal proof source_sha256 "
                         "(bound canonical bytes)")
    try:
        size = int(ev.get("size"))
    except (TypeError, ValueError):
        raise ValueError("proof: source_integrity_evidence.size must be a positive int")
    if size <= 0:
        raise ValueError("proof: source_integrity_evidence.size must be a positive int")
    measured = str(ev.get("measured_at") or "").strip()
    if not measured:
        raise ValueError("proof: source_integrity_evidence.measured_at (ISO-8601) is required")
    try:
        from datetime import datetime as _dt

        _dt.fromisoformat(measured.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("proof: source_integrity_evidence.measured_at must be ISO-8601")
    if ev.get("method") != SOURCE_INTEGRITY_METHOD:
        raise ValueError(f"proof: source_integrity_evidence.method must be {SOURCE_INTEGRITY_METHOD!r} "
                         "(actual B2 re-read only)")
    return {
        "sha": sha.strip().lower(),
        "size": size,
        "measured_at": measured,
        "method": SOURCE_INTEGRITY_METHOD,
    }


def _validate_cadence_evidence(proof: dict, slots: dict) -> dict:
    """Validate role-aware cadence evidence (fail closed, no DB).

    Proofs containing video slots (hq and/or light -- every allowed
    shape contains light) MUST carry ``cadence_evidence`` binding the
    SHA-pinned source census to per-slot output censuses::

        {"source_sha256": "<64hex>", "source_frames": 600,
         "source_fps": 60.0, "source_duration": 10.0,
         "outputs": {"hq": {"frames": 600, "fps": 60.0, "duration": 10.0},
                     "light": {...}},
         "vfr": false, "pts_exact_claimed": false}

    - ``source_sha256`` must equal the proof ``source_sha256`` (bound
      reference, never an unpinned claim).
    - ``outputs`` keys must equal EXACTLY the video slots present in
      the proof (hq/light present; poster is explicitly N/A and never
      appears here -- a poster entry is refused as a faked video claim).
    - Every output ``frames`` must EXACTLY equal ``source_frames`` (a
      nominal 60->30 transcode fails even though the output count is
      positive); fps/duration within tolerance (VFR preserved by
      count+duration).
    - ``pts_exact_claimed`` must be False: per-frame PTS exactness is
      NOT proven by the bounded count census (would need a PTS series);
      claiming true is refused as fabrication.
    """
    video_roles = {r for r in slots if r in ("hq", "light")}
    ev = proof.get("cadence_evidence")
    if not video_roles:
        if ev is not None:
            raise ValueError("proof: cadence_evidence is video-only (poster is N/A); omit it")
        return {}
    if not isinstance(ev, dict):
        raise ValueError("proof: cadence_evidence is required for video slots (hq/light)")
    src_ev = ev.get("source_sha256")
    if not isinstance(src_ev, str):
        raise ValueError("proof: cadence_evidence.source_sha256 is required")
    _cb.normalize_object_sha(src_ev)
    if src_ev.strip().lower() != str(proof.get("source_sha256", "")).strip().lower():
        raise ValueError("proof: cadence_evidence.source_sha256 must equal proof source_sha256 (bound reference)")
    try:
        sf = int(ev.get("source_frames"))
        sfps = float(ev.get("source_fps"))
        sdur = float(ev.get("source_duration"))
    except (TypeError, ValueError):
        raise ValueError("proof: cadence_evidence needs source_frames int + source_fps/duration numbers")
    if sf <= 0 or sfps <= 0 or sdur <= 0:
        raise ValueError("proof: cadence_evidence source census must be positive")
    outputs = ev.get("outputs")
    if not isinstance(outputs, dict) or set(outputs) != set(video_roles):
        raise ValueError(
            f"proof: cadence_evidence.outputs must cover exactly the video slots {sorted(video_roles)} "
            "(poster is N/A, never listed)"
        )
    for role in sorted(video_roles):
        entry = outputs.get(role)
        if not isinstance(entry, dict):
            raise ValueError(f"proof: cadence_evidence.outputs.{role} must be an object")
        try:
            of, ofps, odur = int(entry.get("frames")), float(entry.get("fps")), float(entry.get("duration"))
        except (TypeError, ValueError):
            raise ValueError(f"proof: cadence_evidence.outputs.{role} needs frames/fps/duration numbers")
        if of != sf:
            raise ValueError(
                f"proof: cadence_evidence.outputs.{role} frames {of} != source {sf} "
                "(60->30 must fail)"
            )
        if abs(odur - sdur) > max(_CADENCE_DURATION_TOL_S, 0.01 * max(sdur, 1e-6)):
            raise ValueError(f"proof: cadence_evidence.outputs.{role} duration drift (source={sdur} output={odur})")
        if abs(ofps - sfps) > max(_CADENCE_FPS_ABS_TOL, _CADENCE_FPS_REL_TOL * max(sfps, 1e-6)):
            raise ValueError(f"proof: cadence_evidence.outputs.{role} fps drift (source={sfps} output={ofps})")
    if not isinstance(ev.get("vfr"), bool):
        raise ValueError("proof: cadence_evidence.vfr must be boolean")
    if ev.get("pts_exact_claimed") is not False:
        raise ValueError("proof: cadence_evidence.pts_exact_claimed must be false (per-frame PTS exact NOT proven)")
    return {
        "source_sha256": src_ev.strip().lower(),
        "source_frames": sf,
        "source_fps": sfps,
        "source_duration": sdur,
        "outputs": {k: {"frames": int(v["frames"]), "fps": float(v["fps"]), "duration": float(v["duration"])}
                    for k, v in outputs.items()},
        "vfr": bool(ev.get("vfr")),
        "pts_exact_claimed": False,
    }


def validate_proof_record(proof: dict) -> dict:
    """Validate a structured proof record (no DB). Fail closed.

    Schema allows ``hq+light+poster`` (full proof) or ``light+poster``
    (claimed small-source alias). The alias shape is NOT trusted here:
    ``crosscheck_proof_db`` requires a SERVER-TRUSTED DB producer alias
    proof (``web_package`` job ``finalized_slots`` pin matching the proof
    source/revision/version with ``hq_aliased_to == "light"``, durable
    complete, plus resolver validation) and otherwise requires HQ.

    All ``PROOF_REQUIRED_CHECKS`` (incl. ``source_bytes_sha_match`` for
    the canonical source bytes AND ``original_storage_integrity_checked``
    for the actual B2 source re-read) must be true. Proofs containing video
    slots must additionally carry ``cadence_evidence`` (source-bound
    exact frame count + timing tolerance; poster is explicitly N/A and
    never listed there; per-frame PTS exact must stay false) AND
    ``source_integrity_evidence`` (B2 full-GET-after-publication sha/size
    cross-checked against the canonical SHA/size; local scratch/metadata
    alone never suffices).
    """
    if not isinstance(proof, dict):
        raise ValueError("proof must be a JSON object")
    uuid = proof.get("video_uuid")
    if not isinstance(uuid, str) or not uuid.strip() or len(uuid) > 100 or "|" in uuid:
        raise ValueError("proof: video_uuid must be a non-empty string (<=100, no '|')")
    src = proof.get("source_sha256")
    if not isinstance(src, str):
        raise ValueError("proof: source_sha256 is required")
    _cb.normalize_object_sha(src)
    try:
        rev_id = int(proof.get("source_revision_id"))
    except (TypeError, ValueError):
        raise ValueError("proof: source_revision_id must be an int")
    if rev_id <= 0:
        raise ValueError("proof: source_revision_id must be > 0")
    tv = proof.get("transform_version")
    if not isinstance(tv, str) or not tv.strip():
        raise ValueError("proof: transform_version is required")
    slots = proof.get("slots")
    if not isinstance(slots, dict) or not slots:
        raise ValueError("proof: slots must be a non-empty object")
    allowed_roles = {"hq", "light", "poster"}
    if set(slots) - allowed_roles:
        raise ValueError(f"proof: unknown slot roles {sorted(set(slots) - allowed_roles)}")
    if set(slots) not in ({"hq", "light", "poster"}, {"light", "poster"}):
        raise ValueError("proof: slots must be hq+light+poster or light+poster (aliased)")
    for role, entry in slots.items():
        if not isinstance(entry, dict):
            raise ValueError(f"proof: slots.{role} must be an object")
        _cb.normalize_object_sha(entry.get("derivative_sha256", ""))
        _cb.validate_canary_slot_size(role, entry.get("byte_size"))
    checks = proof.get("checks")
    if not isinstance(checks, dict):
        raise ValueError("proof: checks must be an object")
    for name in PROOF_REQUIRED_CHECKS:
        if checks.get(name) is not True:
            raise ValueError(f"proof: checks.{name} must be true (evidence required)")
    recorded = str(proof.get("recorded_at") or "").strip()
    if not recorded:
        raise ValueError("proof: recorded_at (ISO-8601) is required")
    try:
        from datetime import datetime as _dt

        _dt.fromisoformat(recorded.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("proof: recorded_at must be ISO-8601")
    op = str(proof.get("operator") or "").strip()
    if not op:
        raise ValueError("proof: operator is required")
    cadence = _validate_cadence_evidence(proof, slots)
    integrity = _validate_source_integrity_evidence(proof, slots)
    return {
        "video_uuid": uuid.strip(),
        "source_sha256": src.strip().lower(),
        "source_revision_id": rev_id,
        "transform_version": tv.strip(),
        "slots": {k: {"derivative_sha256": v["derivative_sha256"].strip().lower(),
                      "byte_size": int(v["byte_size"])} for k, v in slots.items()},
        "cadence_evidence": cadence,
        "source_integrity_evidence": integrity,
    }


def _require_server_alias_for_light_poster(db, proof_norm: dict) -> None:
    """Require a SERVER-TRUSTED DB producer alias proof for light+poster.

    A ``light+poster`` proof (no HQ) is accepted ONLY when the durable DB
    proves the producer aliased HQ to light for THIS exact source pin:

    - a ``web_package`` ``MediaJob`` for the clip whose ``finalized_slots``
      pin (``source_sha256`` + ``source_revision_id`` + ``transform_version``)
      matches the proof, with ``hq_aliased_to == "light"``, ``light`` + ``poster``
      slots present (same artifact SHAs as the proof, no ``hq`` slot), and
      job ``status == "ready"`` (durable complete -- a verifying/partial job
      never proves the alias); AND
    - the durable resolver still validates the alias for the proof transform
      (``resolve_clip_derivatives`` reports ``hq`` ``state == "ready"`` with
      ``aliased_to == "light"`` -- i.e. no distinct HQ ledger row exists for
      the current canonical source + transform and light is servable).

    The proof JSON claim and coded-dims inference alone NEVER suffice: an
    unknown alias (no matching job pin, forged ``hq_aliased_to``, stale
    pin, or resolver disagreement) requires HQ and is refused fail-closed.
    """
    from app.models.media import MediaJob
    from app.models.photos_asset import PhotosAsset

    uuid = proof_norm["video_uuid"]
    asset = (
        db.query(PhotosAsset)
        .filter(PhotosAsset.video_uuid == uuid)
        .limit(1)
        .first()
    )
    if asset is None:
        raise ValueError(
            f"proof DB mismatch: HQ proof required for {uuid[:8]}... "
            "(no server alias proof for light+poster)"
        )
    try:
        from app.services.web_packages import get_finalized_state
    except Exception as exc:
        raise ValueError(f"proof DB check failed: {type(exc).__name__}")
    jobs = (
        db.query(MediaJob)
        .filter(
            MediaJob.photos_asset_id == asset.id,
            MediaJob.rendition == "web_package",
        )
        .order_by(MediaJob.id.desc())
        .limit(10)
        .all()
    )
    matched = False
    for job in jobs:
        try:
            state = get_finalized_state(job)
        except Exception:
            continue
        if str(state.get("source_sha256") or "").lower() != str(proof_norm["source_sha256"]).lower():
            continue
        try:
            if int(state.get("source_revision_id")) != int(proof_norm["source_revision_id"]):
                continue
        except (TypeError, ValueError):
            continue
        if str(state.get("transform_version") or "").strip() != str(proof_norm["transform_version"]).strip():
            continue
        if state.get("hq_aliased_to") != "light":
            continue
        slots_state = state.get("slots") or {}
        if "light" not in slots_state or "poster" not in slots_state:
            continue
        if "hq" in slots_state:
            continue
        try:
            if str(slots_state["light"].get("derivative_sha256") or "").lower() != str(
                proof_norm["slots"]["light"]["derivative_sha256"]
            ).lower():
                continue
            if str(slots_state["poster"].get("derivative_sha256") or "").lower() != str(
                proof_norm["slots"]["poster"]["derivative_sha256"]
            ).lower():
                continue
        except (AttributeError, KeyError, TypeError):
            continue
        if getattr(job, "status", None) != "ready":
            continue
        matched = True
        break
    if not matched:
        raise ValueError(
            f"proof DB mismatch: HQ proof required for {uuid[:8]}... "
            "(no server alias proof for light+poster)"
        )
    try:
        from app.services.derivative_read import resolve_clip_derivatives

        clip = resolve_clip_derivatives(
            db, uuid, transform_version=str(proof_norm["transform_version"]).strip()
        )
        hq = clip.roles.get("hq") if getattr(clip, "roles", None) else None
        if (
            hq is None
            or getattr(hq, "aliased_to", None) != "light"
            or getattr(hq, "state", None) != "ready"
        ):
            raise ValueError(
                f"proof DB mismatch: server alias not validated for {uuid[:8]}... "
                "(resolver requires HQ)"
            )
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"proof DB check failed: {type(exc).__name__}")


def crosscheck_proof_db(db, proof_norm: dict) -> None:
    """Cross-check a proof record against the durable DB ledger. Fail closed.

    Requires ``hq+light+poster`` unless a SERVER-TRUSTED DB producer alias
    proof shows ``hq`` aliased to ``light`` (see
    ``_require_server_alias_for_light_poster``). Every provided slot must
    match a READY ledger row (source SHA + artifact SHA) and its durable
    blob size; the canonical source/revision must still match the proof.
    Explicit source-integrity evidence: the canonical source blob row
    must still exist (a deleted source fails closed -- revision metadata
    alone never suffices) and the resolver must still return a verified
    PROD replica for the pinned SHA. The collector's B2 source re-read
    evidence (``source_integrity_evidence``: sha/size/method
    ``full_get_after_publication``) MUST match the canonical SHA/size;
    local scratch hashes/metadata alone never suffice. Unknown alias
    state requires HQ (refused fail-closed).
    """
    from app.models.media_backbone import MediaBlob, MediaDerivative

    uuid = proof_norm["video_uuid"]
    roles = set(proof_norm.get("slots", {}))
    if roles == {"light", "poster"}:
        _require_server_alias_for_light_poster(db, proof_norm)
    elif roles != {"hq", "light", "poster"}:
        raise ValueError(
            f"proof DB mismatch: HQ proof required for {uuid[:8]}... "
            f"(unexpected slots {sorted(roles)})"
        )
    for role, entry in proof_norm["slots"].items():
        row = (
            db.query(MediaDerivative)
            .filter(
                MediaDerivative.video_uuid == uuid,
                MediaDerivative.role == role,
                MediaDerivative.transform_version == proof_norm["transform_version"],
                MediaDerivative.status == "ready",
            )
            .limit(1)
            .first()
        )
        if row is None:
            raise ValueError(f"proof DB mismatch: no READY ledger row for {uuid[:8]}.../{role}")
        if str(row.source_blob_sha256 or "").lower() != proof_norm["source_sha256"]:
            raise ValueError(f"proof DB mismatch: source SHA drift for {uuid[:8]}.../{role}")
        if str(row.derivative_blob_sha256 or "").lower() != entry["derivative_sha256"]:
            raise ValueError(f"proof DB mismatch: artifact SHA mismatch for {uuid[:8]}.../{role}")
        try:
            blob = db.get(MediaBlob, str(entry["derivative_sha256"]).lower())
        except Exception as exc:
            raise ValueError(f"proof DB check failed: {type(exc).__name__}")
        if blob is None:
            raise ValueError(f"proof DB mismatch: no durable blob for {uuid[:8]}.../{role}")
        try:
            if int(blob.byte_size) != int(entry["byte_size"]):
                raise ValueError(f"proof DB mismatch: artifact size mismatch for {uuid[:8]}.../{role}")
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError(f"proof DB check failed: {type(exc).__name__}")
    # Source revision still canonical (no silent source swap since proof).
    # Explicit source-integrity evidence: blob row + verified replica,
    # not revision metadata alone, PLUS B2 re-read evidence cross-check.
    try:
        from app.services.derivative_publisher import resolve_canonical_source_revision

        rev, _blob, _loc = resolve_canonical_source_revision(db, uuid)
        if str(rev.blob_sha256 or "").lower() != proof_norm["source_sha256"]:
            raise ValueError(f"proof DB mismatch: canonical source changed for {uuid[:8]}...")
        if int(rev.id) != int(proof_norm["source_revision_id"]):
            raise ValueError(f"proof DB mismatch: source revision changed for {uuid[:8]}...")
        try:
            src_blob = db.get(MediaBlob, str(proof_norm["source_sha256"]).lower())
        except Exception as exc:
            raise ValueError(f"proof DB check failed: {type(exc).__name__}")
        if src_blob is None:
            raise ValueError(f"proof DB mismatch: canonical source bytes missing for {uuid[:8]}...")
        try:
            blob_size = int(src_blob.byte_size)
        except (TypeError, ValueError):
            raise ValueError(f"proof DB mismatch: canonical source size unreadable for {uuid[:8]}...")
        if blob_size <= 0:
            raise ValueError(f"proof DB mismatch: canonical source size invalid for {uuid[:8]}...")
        # B2 re-read evidence MUST match the canonical bytes (fail closed:
        # metadata/local scratch alone never suffices).
        ev = proof_norm.get("source_integrity_evidence") or {}
        if not isinstance(ev, dict) or not ev:
            raise ValueError(f"proof DB mismatch: missing B2 source re-read evidence for {uuid[:8]}...")
        if str(ev.get("sha", "")).lower() != proof_norm["source_sha256"]:
            raise ValueError(f"proof DB mismatch: source evidence SHA drift for {uuid[:8]}...")
        try:
            ev_size = int(ev.get("size"))
        except (TypeError, ValueError):
            raise ValueError(f"proof DB mismatch: source evidence size unreadable for {uuid[:8]}...")
        if ev_size != blob_size:
            raise ValueError(f"proof DB mismatch: source evidence size mismatch for {uuid[:8]}... "
                             f"(evidence {ev_size} != canonical {blob_size})")
        if ev.get("method") != SOURCE_INTEGRITY_METHOD:
            raise ValueError(f"proof DB mismatch: source evidence method invalid for {uuid[:8]}...")
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"proof DB check failed: {type(exc).__name__}")


def _require_fresh_phase1_proofs(db, state_dir: Path, phase1_cohort: list[str]) -> None:
    """Fail closed unless every phase-1 clip has a fresh stored proof.

    Loads ``state_dir/proofs/proof-<uuid>.json`` for each cohort UUID,
    validates the schema, and cross-checks it against the CURRENT DB
    (canonical source SHA + revision, READY ledger rows per slot). The
    operator is trusted to record honest evidence, but a STALE proof
    (source moved, revision bumped, artifact missing, ledger not ready)
    never passes -- the mutable ``proven`` list alone never suffices.
    """
    proofs_dir = Path(state_dir).expanduser() / "proofs"
    for uuid in phase1_cohort:
        p = proofs_dir / f"proof-{uuid}.json"
        if not p.is_file():
            raise ValueError(
                f"phase 2 blocked: no stored proof artifact for {uuid[:8]}... "
                f"(expected {p}); re-prove against current DB"
            )
        try:
            raw = json.loads(p.read_text())
        except Exception:
            raise ValueError(
                f"phase 2 blocked: stored proof for {uuid[:8]}... is unreadable; re-prove"
            )
        try:
            norm = validate_proof_record(raw)
        except ValueError as exc:
            raise ValueError(f"phase 2 blocked: stored proof invalid for {uuid[:8]}...: {exc}")
        if norm["video_uuid"] != uuid:
            raise ValueError(
                f"phase 2 blocked: stored proof identity mismatch for {uuid[:8]}..."
            )
        try:
            crosscheck_proof_db(db, norm)
        except ValueError as exc:
            raise ValueError(f"phase 2 blocked: stale proof for {uuid[:8]}...: {exc}")


def cmd_inventory(args) -> int:
    phase, clips = load_manifest(Path(args.manifest))
    eng = _engine()
    db = _session(eng)
    try:
        try:
            committed = canary_ledger_bytes(db)
            committed_txt = str(committed)
            remaining_txt = str(CANARY_BUDGET_BYTES - committed)
        except Exception as exc:
            # Read-only path: report unavailable, never a false 0.
            try:
                db.rollback()
            except Exception:
                pass
            print(f"phase={phase} manifest_clips={len(clips)} "
                  f"accounted_bytes=unavailable ({type(exc).__name__}) "
                  f"remaining_budget_bytes=unavailable "
                  f"fleet_package_active=unknown")
            shown = 0
            for uuid in clips[:30]:
                r = clip_readiness(db, uuid)
                ok = "OK " if r.get("ok") else "SKIP"
                extra = r.get("reason", r.get("status", ""))
                print(f"  [{ok}] {uuid[:8]}... status={r.get('status')} {extra}")
                shown += 1
            print(f"inventory done: {shown} clip(s) checked (bounded, LIMIT per clip). DRY-RUN: no writes.")
            return 0
        fleet = fleet_package_blocked(db)
        print(f"phase={phase} manifest_clips={len(clips)} "
              f"accounted_bytes={committed_txt} (reservations+ready, orphans included) "
              f"remaining_budget_bytes={remaining_txt} "
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
    try:
        fail_limit = validate_max_consecutive_failures(
            getattr(args, "max_consecutive_failures", 2)
        )
    except ValueError as exc:
        print(f"REFUSED: {exc}")
        return 2
    state = load_state(state_dir)

    eng = _engine()
    db = _session(eng)
    try:
        try:
            db_fail_streak = db_consecutive_canary_failures(db)
        except Exception as exc:
            try:
                db.rollback()
            except Exception:
                pass
            print(f"REFUSED: consecutive-failure cohort unverifiable ({type(exc).__name__}); "
                  "no admission without a provable streak.")
            return 2
        if int(state.get("consecutive_failures", 0) or 0) != int(db_fail_streak):
            state["consecutive_failures"] = int(db_fail_streak)
            try:
                save_state(state_dir, state)
            except Exception:
                pass
        if int(db_fail_streak) >= int(fail_limit):
            print(f"REFUSED: consecutive_failures={int(db_fail_streak)} >= "
                  f"max {int(fail_limit)}; investigate before new admissions.")
            return 2
        try:
            db_known = _db_admitted_uuids(db)
        except Exception as exc:
            try:
                db.rollback()
            except Exception:
                pass
            print(f"REFUSED: web_package cohort unverifiable ({type(exc).__name__}); "
                  "no admission without a provable total.")
            return 2
        file_known = set(state.get("admitted", []) or [])
        known = set(db_known) | set(file_known)
        total_admitted = len(known)
        new_ids = [u for u in clips if u not in known]
        if phase == 1:
            try:
                _cb.check_phase_count_new_only(1, len(new_ids), total_admitted)
            except ValueError as exc:
                print(f"REFUSED: {exc}")
                return 2
            if len(clips) > CANARY_PHASE1_MAX_CLIPS:
                print(f"REFUSED: phase 1 manifest lists {len(clips)} > {CANARY_PHASE1_MAX_CLIPS}")
                return 2
        elif phase == 2:
            phase1_cohort = _load_phase1_cohort(getattr(args, "phase1_manifest", None))
            try:
                _cb.check_phase2_eligible(
                    phase1_cohort=phase1_cohort,
                    proven_uuids=set(state.get("proven", []) or []),
                    db_total_admitted=db_known,
                    new_count=len(new_ids),
                )
                _cb.check_phase_count_new_only(2, len(new_ids), len(db_known))
                # Fresh-proof authority: the mutable `proven` list is only a
                # hint. Each phase-1 clip must have a STORED proof artifact
                # (state_dir/proofs/proof-<uuid>.json) that validates against
                # the CURRENT DB (source SHA + revision + READY rows). A
                # stale proof (source changed since the proof, artifact
                # replaced/missing, ledger not ready) blocks phase 2 even
                # when the proven list claims 5/5.
                _require_fresh_phase1_proofs(db, state_dir, phase1_cohort)
            except ValueError as exc:
                print(f"REFUSED: {exc}")
                return 2
        else:
            print(f"REFUSED: unknown phase {phase!r}")
            return 2

        if args.apply:
            facts_arg = getattr(args, "host_facts", None)
            if not facts_arg:
                print("REFUSED: --apply requires --host-facts F.json (fresh, with memory pressure); "
                      "legacy --mac-free-bytes/--server-cache-free-bytes alone are stale-prone and refused.")
                return 2
            _refuse_inside_git(Path(facts_arg))
            try:
                facts = _cb.load_host_facts(facts_arg)
                _cb.validate_host_facts(facts)
            except ValueError as exc:
                print(f"REFUSED: {exc}")
                return 2
        else:
            mac_free = getattr(args, "mac_free_bytes", None)
            srv_free = getattr(args, "server_cache_free_bytes", None)
            if mac_free is not None and int(mac_free) < MIN_MAC_DATA_FREE_BYTES:
                print(f"REFUSED: Mac Data free {int(mac_free)} < {MIN_MAC_DATA_FREE_BYTES} (8 GiB); stop new admissions.")
                return 2
            if srv_free is not None and int(srv_free) < MIN_SERVER_CACHE_FREE_BYTES:
                print(f"REFUSED: server cache volume free {int(srv_free)} < {MIN_SERVER_CACHE_FREE_BYTES} (25 GiB).")
                return 2
        try:
            committed = canary_ledger_bytes(db)
        except Exception as exc:
            try:
                db.rollback()
            except Exception:
                pass
            print(f"REFUSED: canary budget unverifiable ({type(exc).__name__}); "
                  "no admission without a provable budget.")
            return 2
        remaining = CANARY_BUDGET_BYTES - committed
        fleet = fleet_package_blocked(db)
        if fleet["blocked"]:
            print("BLOCKED: a web_package job is already active fleet-wide; "
                  "serial admission -- wait for its terminal state, then re-run.")
            return 3
        admitted_set = set(state.get("admitted", []) or [])
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
            if admitted_set != set(state.get("admitted", []) or []):
                state["admitted"] = sorted(admitted_set)
                save_state(state_dir, state)
            print("nothing_admittable: every manifest clip is ready/active/unknown; no queue change.")
            return 0
        uuid, r, est = plan
        if not args.apply:
            print(f"DRY-RUN plan: would queue ONE web_package job for {uuid[:8]}... "
                  f"(asset_id={r.get('asset_id')} priority={CANARY_JOB_PRIORITY} "
                  f"max_attempts={CANARY_JOB_MAX_ATTEMPTS} worst_case_bytes={est} "
                  f"remaining_budget_bytes={remaining} new_ids={len(new_ids)}). Re-run with --apply to admit.")
            return 0
        with _admit_file_lock(state_dir):
            _pg_admit_lock(db)
            # Re-check serial gate + budget inside the lock (TOCTOU-safe).
            fleet2 = fleet_package_blocked(db)
            if fleet2["blocked"]:
                print("BLOCKED: a web_package job became active before the queue commit; no write.")
                return 3
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
        try:
            committed = canary_ledger_bytes(db)
            print(f"accounted_bytes={committed} (reservations+ready, orphans included) "
                  f"remaining_budget_bytes={CANARY_BUDGET_BYTES - committed}")
        except Exception as exc:
            try:
                db.rollback()
            except Exception:
                pass
            print(f"accounted_bytes=unavailable ({type(exc).__name__}) "
                  f"remaining_budget_bytes=unavailable")
        ready_seen: set[str] = set(state.get("ready_seen", []) or [])
        for uuid in clips[:30]:
            r = clip_readiness(db, uuid)
            if r.get("status") == "already_ready":
                mark = "READY "
                ready_seen.add(uuid)
            elif r.get("status") == "job_active":
                mark = "ACTIVE"
            else:
                mark = "PENDING"
            print(f"  [{mark}] {uuid[:8]}... status={r.get('status')} {r.get('reason', '')}")
        if ready_seen != set(state.get("ready_seen", []) or []):
            state["ready_seen"] = sorted(ready_seen)
            save_state(state_dir, state)
        proven = set(state.get("proven", []) or [])
        print("---")
        print("READY means ledger-durable (all applicable slots ready).")
        print("PROVEN requires an explicit proof record (prove --proof P.json):")
        print(f"  ready_seen={len(ready_seen)} proven={len(proven)} (phase 2 needs EXACTLY 5/5 distinct phase-1 proven, never ready-only; smaller wave never unlocks)")
        print("Manual proof checklist (operator runs; device Safari NOT claimed):")
        print("  1. B2 full-GET SHA: for each ready slot, authorized Library play URL")
        print("     (302) -> follow with user session cookie -> sha256sum full bytes ==")
        print("     ledger derivative_blob_sha256; ffprobe format/tags/faststart clean;")
        print("     video cadence SOURCE-BOUND B2 re-read (hq/light: operator-supplied")
        print("     --source-storage-url-file presigned original, credential-free full")
        print("     GET after derivative GET, bytes hashed == DB-canonical source SHA/size;")
        print("     exact decoded frame count + fps/duration tolerance via bounded")
        print("     -count_frames census; 60->30 fails; VFR by count+duration with")
        print("     per-frame PTS exact NOT claimed; local --source-reference alone")
        print("     never proves B2; poster is a still, video cadence explicitly N/A);")
        print("     original revision bytes intact (B2 re-read evidence + DB blob row")
        print("     + verified replica).")
        print("  2. Library authorized route: 302 to presigned B2 with auth; Range")
        print("     206 with STRICT content-type (video/mp4 hq/light, image/jpeg poster);")
        print("     expired-grant replay denied; logged-out denied (401/403/404 only).")
        print("  3. Record evidence with: prove --proof <proof.json> (schema + DB")
        print("     cross-check enforced; ready-only never marks proven).")
        print("verify done (read-only DB; no bytes fetched by this tool).")
    finally:
        db.rollback()
        db.close()
    return 0


def cmd_prove(args) -> int:
    _, clips = load_manifest(Path(args.manifest))
    manifest_set = set(clips)
    state_dir = Path(args.state_dir).expanduser()
    proof_path = Path(args.proof)
    _refuse_inside_git(proof_path)
    _check_mode_0600(proof_path, "proof file")
    try:
        proof_raw = json.loads(proof_path.read_text())
    except FileNotFoundError:
        print(f"REFUSED: proof not found: {proof_path}")
        return 2
    except json.JSONDecodeError as exc:
        print(f"REFUSED: proof is not valid JSON: {exc}")
        return 2
    try:
        norm = validate_proof_record(proof_raw)
    except ValueError as exc:
        print(f"REFUSED: {exc}")
        return 2
    if norm["video_uuid"] not in manifest_set:
        print(f"REFUSED: proof clip {norm['video_uuid'][:8]}... not in manifest; refusing")
        return 2
    eng = _engine()
    db = _session(eng)
    try:
        try:
            crosscheck_proof_db(db, norm)
        except ValueError as exc:
            print(f"REFUSED: {exc}")
            return 2
        state = load_state(state_dir)
        proven = set(state.get("proven", []) or [])
        ready_seen = set(state.get("ready_seen", []) or [])
        ready_seen.add(norm["video_uuid"])
        proven.add(norm["video_uuid"])
        state["ready_seen"] = sorted(ready_seen)
        state["proven"] = sorted(proven)
        proofs_dir = state_dir / "proofs"
        proofs_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(proofs_dir, 0o700)
        except OSError:
            pass
        dest = proofs_dir / f"proof-{norm['video_uuid']}.json"
        tmp = proofs_dir / f"proof-{norm['video_uuid']}.json.tmp"
        tmp.write_text(json.dumps(proof_raw, indent=2, sort_keys=True))
        os.chmod(tmp, 0o600)
        os.replace(tmp, dest)
        save_state(state_dir, state)
        print(f"PROVEN {norm['video_uuid'][:8]}... ({len(proven)} proven; proof stored, DB cross-checked).")
        return 0
    finally:
        try:
            db.rollback()
        except Exception:
            pass
        try:
            db.close()
        except Exception:
            pass


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
    ad.add_argument("--phase1-manifest", default=None,
                    help="phase 2 only: EXACTLY 5 distinct phase-1 clips manifest (private, OUTSIDE repo)")
    ad.add_argument("--host-facts", default=None,
                    help="private host-facts JSON OUTSIDE the repo (required for --apply)")
    ad.add_argument("--mac-free-bytes", type=int, default=None,
                    help="legacy dry-run hint only; --apply requires --host-facts")
    ad.add_argument("--server-cache-free-bytes", type=int, default=None,
                    help="legacy dry-run hint only; --apply requires --host-facts")
    ad.add_argument("--max-consecutive-failures", type=int, default=2)
    sub.add_parser("verify", help="bounded readiness check (records ready_seen only, never proven)")
    pv = sub.add_parser("prove", help="validate a structured proof record and mark proven")
    pv.add_argument("--proof", required=True, help="private proof JSON OUTSIDE the repo (0600)")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "inventory":
        return cmd_inventory(args)
    if args.cmd == "admit":
        return cmd_admit(args)
    if args.cmd == "verify":
        return cmd_verify(args)
    if args.cmd == "prove":
        return cmd_prove(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
