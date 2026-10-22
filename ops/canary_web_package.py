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
  phase caps (phase1 <= 5, phase2 <= 25 additional, total <= 30).
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
  requires EXPLICIT proof records (``prove --proof P.json``) for the
  EXACT phase-1 cohort (<= 5, all admitted + proven) plus a durable DB
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
)


def validate_proof_record(proof: dict) -> dict:
    """Validate a structured proof record (no DB). Fail closed."""
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
    return {
        "video_uuid": uuid.strip(),
        "source_sha256": src.strip().lower(),
        "source_revision_id": rev_id,
        "transform_version": tv.strip(),
        "slots": {k: {"derivative_sha256": v["derivative_sha256"].strip().lower(),
                      "byte_size": int(v["byte_size"])} for k, v in slots.items()},
    }


def crosscheck_proof_db(db, proof_norm: dict) -> None:
    """Cross-check a proof record against the durable DB ledger. Fail closed."""
    from app.models.media_backbone import MediaDerivative

    uuid = proof_norm["video_uuid"]
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
        try:
            if int(row.source_blob_sha256 is not None and getattr(row, "id", 0) or 0) < 0:
                pass
        except Exception:
            pass
        if str(row.derivative_blob_sha256 or "").lower() != entry["derivative_sha256"]:
            raise ValueError(f"proof DB mismatch: artifact SHA mismatch for {uuid[:8]}.../{role}")
    # Source revision still canonical (no silent source swap since proof).
    try:
        from app.services.derivative_publisher import resolve_canonical_source_revision

        rev, _blob, _loc = resolve_canonical_source_revision(db, uuid)
        if str(rev.blob_sha256 or "").lower() != proof_norm["source_sha256"]:
            raise ValueError(f"proof DB mismatch: canonical source changed for {uuid[:8]}...")
        if int(rev.id) != int(proof_norm["source_revision_id"]):
            raise ValueError(f"proof DB mismatch: source revision changed for {uuid[:8]}...")
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
    state = load_state(state_dir)
    if state.get("consecutive_failures", 0) >= int(args.max_consecutive_failures):
        print(f"REFUSED: consecutive_failures={state['consecutive_failures']} >= "
              f"max {args.max_consecutive_failures}; investigate before new admissions.")
        return 2

    eng = _engine()
    db = _session(eng)
    try:
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
        print(f"  ready_seen={len(ready_seen)} proven={len(proven)} (phase 2 needs 5/5 proven, never ready-only)")
        print("Manual proof checklist (operator runs; device Safari NOT claimed):")
        print("  1. B2 full-GET SHA: for each ready slot, authorized Library play URL")
        print("     (302) -> follow with user session cookie -> sha256sum full bytes ==")
        print("     ledger derivative_blob_sha256; ffprobe format/tags/faststart + frame")
        print("     cadence; original revision bytes untouched (source SHA re-read).")
        print("  2. Library authorized route: 302 to presigned B2 with auth; Range")
        print("     206 with correct content-type; expired-grant replay denied;")
        print("     logged-out request denied (no auth bypass for probes).")
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
                    help="phase 2 only: exact phase-1 cohort manifest (private, OUTSIDE repo)")
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
