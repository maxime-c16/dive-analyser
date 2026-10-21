"""D3b2 fenced web-package slot publication (DEFAULT DISABLED).

One ``web_package`` job produces ``hq``/``light``/``poster`` in a single
Mac pass. The worker uploads each slot's bytes to a single-step slot route;
the server validates the bytes (ffprobe actual video, SHA/size, HDR reject,
small-source alias checked against server dims — never client-only trust),
publishes them through the D3b1 ``derivative_publisher`` (content-addressed
B2 upload + full-byte roundtrip verify), and commits the ledger row plus the
job's ``finalized_slots`` atomically under a fenced guard.

Fencing: the publisher owns its DB unit and exposes ``pre_commit_hook``,
which runs with the ledger row lock held, inside the committing unit, BEFORE
any ready decision (including idempotent replays). The hook re-validates the
D2 lease (owner + expiry + token, row-locked via ``_guarded_job``) and the
source identity (claimed SHA == canonical SHA pinned at lease == current
canonical). A mid-upload re-lease (even to the SAME agent) or a source
change is rejected there; the verified B2 bytes stay a safe orphan, never
promoted. No DB row lock is held during the network phase.

``finalized_slots`` (NULL = empty, backward compatible) is a dict
``{"source_sha256", "transform_version", "hq_aliased_to", "slots": {slot:
{"derivative_sha256", "size_bytes"}}}``. Legacy code ignores it. A job is
ready ONLY when every applicable slot is VERIFIED DURABLE in the ledger
(cache-only never counts). ``PackageResult.ready`` on the Mac means
LOCAL-VALIDATED only, never durable — the distinction is explicit.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

PACKAGE_SLOTS = ("hq", "light", "poster")

_SHORT_SIDE_HQ_CAP = 1080
_SHORT_SIDE_LIGHT_CAP = 720


def _short_side(w: int | None, h: int | None) -> int | None:
    if not w or not h or w <= 0 or h <= 0:
        return None
    return min(int(w), int(h))


def get_finalized_state(job) -> dict[str, Any]:
    """Normalize job.finalized_slots (NULL/[]/{} backward compatible)."""
    raw = getattr(job, "finalized_slots", None)
    if raw is None or raw == [] or raw == {}:
        return {"source_sha256": None, "transform_version": None, "hq_aliased_to": None, "slots": {}}
    if isinstance(raw, list):
        # Legacy unexpected shape: treat as slot list without pinning.
        slots: dict[str, Any] = {}
        for entry in raw:
            if isinstance(entry, dict) and entry.get("slot") and entry.get("derivative_sha256"):
                slots[entry["slot"]] = {
                    "derivative_sha256": entry["derivative_sha256"],
                    "size_bytes": entry.get("size_bytes"),
                }
        return {"source_sha256": None, "transform_version": None, "hq_aliased_to": None, "slots": slots}
    if isinstance(raw, dict):
        slots_raw = raw.get("slots", {})
        slots = dict(slots_raw) if isinstance(slots_raw, dict) else {}
        return {
            "source_sha256": raw.get("source_sha256") or raw.get("expected_source_sha256"),
            "transform_version": raw.get("transform_version"),
            "hq_aliased_to": raw.get("hq_aliased_to"),
            "slots": slots,
        }
    return {"source_sha256": None, "transform_version": None, "hq_aliased_to": None, "slots": {}}


def set_finalized_state(job, state: dict[str, Any]) -> None:
    job.finalized_slots = {
        "source_sha256": state.get("source_sha256"),
        "transform_version": state.get("transform_version"),
        "hq_aliased_to": state.get("hq_aliased_to"),
        "slots": dict(state.get("slots", {})),
    }


def applicable_slots(hq_aliased_to: str | None) -> list[str]:
    if hq_aliased_to == "light":
        return ["light", "poster"]
    return ["hq", "light", "poster"]


def package_worker_available(db) -> bool:
    """True when a healthy package-capable worker just checked in.

    Gated queueing only: the worker must be active, leasing-enabled,
    advertise the ``web_package`` capability, and have heartbeat within the
    last 15 minutes. No exceptions — without this the queue decision falls
    back to legacy poster + 720p so no package job ever strands.
    """
    from datetime import datetime, timedelta

    from sqlalchemy import select

    from app.config import get_settings
    from app.models.media import MediaAgent

    if not get_settings().media_web_packages_enabled:
        return False
    cutoff = datetime.utcnow() - timedelta(minutes=15)
    agents = list(
        db.execute(
            select(MediaAgent).where(
                MediaAgent.active.is_(True),
                MediaAgent.leasing_enabled.is_(True),
                MediaAgent.last_seen_at.is_not(None),
                MediaAgent.last_seen_at >= cutoff,
            )
        )
        .scalars()
        .all()
    )
    return any("web_package" in (agent.capabilities or []) for agent in agents)


def _server_source_dims(job) -> tuple[int | None, int | None]:
    asset = getattr(job, "asset", None)
    if asset is None:
        return None, None
    try:
        w, h = int(asset.width or 0) or None, int(asset.height or 0) or None
    except (TypeError, ValueError):
        return None, None
    return w, h


def check_small_source_alias(
    *,
    job,
    slot: str,
    hq_aliased_to: str | None,
    claimed_w: int | None,
    claimed_h: int | None,
    probed_w: int | None,
    probed_h: int | None,
) -> list[str]:
    """Validate the hq_aliased_to claim against server truth, return applicable slots.

    Server dims (PhotosAsset width/height from ingestion) are preferred over
    the worker's claimed dims — the claim is checked, never trusted alone.
    An alias requires a genuinely small source (short side < 1080) and, for
    the light slot, proof of no upscale against the server dims.
    """
    if hq_aliased_to is not None and hq_aliased_to != "light":
        raise ValueError("hq_aliased_to must be 'light' when present")
    if hq_aliased_to != "light":
        return list(PACKAGE_SLOTS)
    server_w, server_h = _server_source_dims(job)
    ref_w, ref_h = server_w, server_h
    ref_source = "server"
    if ref_w is None or ref_h is None:
        # No server dims: fall back to the worker claim, but still enforce
        # small-source + no-upscale against the probed slot bytes.
        ref_w, ref_h, ref_source = claimed_w, claimed_h, "claimed"
    if ref_w is None or ref_h is None:
        raise ValueError("hq_aliased_to requires known source dimensions")
    ref_short = _short_side(ref_w, ref_h)
    if ref_short is None or ref_short >= _SHORT_SIDE_HQ_CAP:
        raise ValueError(f"hq_aliased_to rejected: {ref_source} source short side {ref_short} is not small")
    if slot == "light":
        probed_short = _short_side(probed_w, probed_h)
        if probed_short is None:
            raise ValueError("light slot dims unreadable; cannot prove small-source alias")
        if probed_short >= _SHORT_SIDE_HQ_CAP:
            raise ValueError("hq_aliased_to rejected: light output is not small-source sized")
        if probed_short > ref_short:
            raise ValueError("hq_aliased_to rejected: light output upscaled beyond source")
    return ["light", "poster"]


def _ffprobe_streams(path: Path) -> dict:
    out = subprocess.check_output(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        timeout=60,
    ).decode()
    return json.loads(out)


def _mp4_faststart_ok(path: Path) -> bool | None:
    try:
        with open(path, "rb") as handle:
            pos, total = 0, path.stat().st_size
            atoms: list[str] = []
            while pos < total:
                handle.seek(pos)
                header = handle.read(16)
                if len(header) < 8:
                    break
                size = int.from_bytes(header[:4], "big")
                kind = header[4:8].decode("latin1")
                if size == 1:
                    size = int.from_bytes(header[8:16], "big")
                elif size == 0:
                    size = total - pos
                if size <= 0:
                    break
                atoms.append(kind)
                pos += size
        if "moov" in atoms and "mdat" in atoms:
            return atoms.index("moov") < atoms.index("mdat")
        return None
    except OSError:
        return None


_HDR_TRANSFERS = {"smpte2084", "arib-std-b67", "smpte2084pq"}


def validate_slot_artifact(
    *,
    path: Path,
    slot: str,
    expected_sha256: str,
    expected_size: int,
) -> dict[str, Any]:
    """Fail-closed slot format check on ACTUAL bytes (never client claims).

    Returns probed ``{"width", "height", "codec", ...}`` for the alias check.
    Rejects corrupt/truncated/wrong-size bytes (SHA/size), unreadable media,
    wrong containers, and HDR-tagged outputs (packages must be SDR BT.709).
    """
    if slot not in PACKAGE_SLOTS:
        raise ValueError(f"unknown package slot {slot!r}")
    actual_size = path.stat().st_size
    if actual_size != expected_size:
        raise ValueError(f"{slot} size mismatch: staged {actual_size} != claimed {expected_size}")
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected_sha256.lower():
        raise ValueError(f"{slot} checksum mismatch")
    if slot == "poster":
        with open(path, "rb") as handle:
            magic = handle.read(3)
        if magic[:2] != b"\xff\xd8":
            raise ValueError("poster is not a JPEG (bad magic)")
    try:
        data = _ffprobe_streams(path)
    except Exception as exc:
        raise ValueError(f"{slot} unreadable by ffprobe: {exc}") from exc
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise ValueError(f"{slot} has no video stream")
    transfer = str(video.get("color_transfer", "") or "").lower()
    if transfer in _HDR_TRANSFERS:
        raise ValueError(f"{slot} is HDR-tagged ({transfer}); packages must be tone-mapped SDR")
    width, height = video.get("width"), video.get("height")
    if slot in ("hq", "light"):
        if video.get("codec_name") != "h264":
            raise ValueError(f"{slot} must be H.264 (got {video.get('codec_name')!r})")
        if video.get("pix_fmt") != "yuv420p":
            raise ValueError(f"{slot} must be yuv420p SDR (got {video.get('pix_fmt')!r})")
        if not width or not height or width <= 0 or height <= 0:
            raise ValueError(f"{slot} has invalid dims")
        if width % 2 or height % 2:
            raise ValueError(f"{slot} dims must be even (got {width}x{height})")
        if _mp4_faststart_ok(path) is False:
            raise ValueError(f"{slot} is not faststart (moov after mdat)")
        short = _short_side(int(width), int(height))
        cap = _SHORT_SIDE_HQ_CAP if slot == "hq" else _SHORT_SIDE_LIGHT_CAP
        if short is not None and short > cap:
            raise ValueError(f"{slot} short side {short} exceeds cap {cap}")
    else:
        if not width or not height or width <= 0 or height <= 0:
            raise ValueError("poster has invalid dims")
    return {"width": int(width), "height": int(height), "codec": video.get("codec_name"), "pix_fmt": video.get("pix_fmt")}


def make_slot_guard(
    *,
    job_id: int,
    agent_id: str,
    lease_token: str | None,
    claimed_source_sha256: str,
    slot: str,
    applicable: list[str],
    hq_aliased_to: str | None,
    transform_version: str | None,
):
    """Build the publisher pre-commit hook for one slot.

    Runs with the ledger row lock held, inside the committing unit: validates
    the D2 lease (owner/expiry/token via ``_guarded_job`` with row lock),
    the source pin (claimed == ctx == current canonical is checked by the
    publisher drift guards; here we bind the job to the same pin), then
    accumulates the slot into ``finalized_slots`` and marks the job ready
    ONLY when every applicable slot is durably recorded. Idempotent per-slot
    retries (same bytes) dedupe; different bytes conflict.
    """
    from app.services.media_jobs import LEASED_JOB_STATUSES, _guarded_job

    _slot = slot
    _applicable = list(applicable)

    def _hook(db, ctx, *, derivative_sha, derivative_size, object_key, bucket, environment) -> None:
        from datetime import datetime

        if _slot not in _applicable:
            raise ValueError(f"slot {_slot!r} is not applicable for this package")
        if claimed_source_sha256.lower() != ctx.source_blob_sha256.lower():
            from app.services.derivative_publisher import StaleSourceError

            raise StaleSourceError("package slot source does not match canonical source; refusing ready")
        # Row-locked authoritative lease recheck: expiry, owner, token. A
        # mid-upload re-lease (even to the SAME agent) carries a new token,
        # so the stale attempt's token mismatches here and its verified B2
        # bytes stay a safe orphan.
        try:
            job = _guarded_job(db, job_id, agent_id, lease_token, None, lock=True)
        except ValueError:
            # Job vanished — fail closed without promoting.
            from app.services.derivative_publisher import StaleSourceError

            raise StaleSourceError("package job not found; refusing ready") from None
        if getattr(job, "rendition", None) != "web_package":
            raise ValueError("package slot guard requires a web_package job")
        if job.status == "ready":
            # Idempotent replay after completion: only the exact same bytes
            # for an already-finalized slot dedupe; anything else is stale.
            state = get_finalized_state(job)
            prev = state.get("slots", {}).get(_slot)
            if prev is not None and str(prev.get("derivative_sha256", "")).lower() == derivative_sha.lower():
                return
            from app.services.derivative_publisher import StaleSourceError

            raise StaleSourceError("package job already ready; refusing additional slot bytes")
        if job.status not in LEASED_JOB_STATUSES and job.status != "verifying":
            raise PermissionError(f"media_job_invalid_state:{job.status}")
        # Lease state is enforced by _guarded_job above (owner/expiry/token).
        state = get_finalized_state(job)
        prev = state.get("slots", {}).get(_slot)
        if prev is not None:
            if str(prev.get("derivative_sha256", "")).lower() != derivative_sha.lower():
                from app.services.derivative_publisher import DerivativeIdentityConflict

                raise DerivativeIdentityConflict(
                    "package slot already finalized with different bytes; refusing overwrite"
                )
            # Same-bytes retry: fall through to the ledger dedupe below.
        else:
            state.setdefault("slots", {})[_slot] = {
                "derivative_sha256": derivative_sha,
                "size_bytes": derivative_size,
            }
        # Pin the derivation identity on first slot; later slots must agree.
        if state.get("source_sha256") is None:
            state["source_sha256"] = ctx.source_blob_sha256
            state["transform_version"] = transform_version or ctx.transform_version
            state["hq_aliased_to"] = hq_aliased_to
        else:
            if str(state["source_sha256"]).lower() != ctx.source_blob_sha256.lower():
                from app.services.derivative_publisher import StaleSourceError

                raise StaleSourceError("package source changed between slots; refusing ready")
            if hq_aliased_to != state.get("hq_aliased_to"):
                raise ValueError("hq_aliased_to changed between slots in one package")
        set_finalized_state(job, state)
        finalized = {s for s in state["slots"]}
        if all(s in finalized for s in _applicable):
            job.status = "ready"
            job.progress = 100
            job.completed_at = datetime.utcnow()
        else:
            if job.status not in ("verifying", "uploading", "transcoding"):
                job.status = "verifying"
            job.progress = max(int(getattr(job, "progress", 0) or 0), 50)
        job.updated_at = datetime.utcnow()
        db.add(job)
        db.flush()

    return _hook
