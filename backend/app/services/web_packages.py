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
``{"source_sha256", "source_revision_id", "source_width", "source_height",
"transform_version", "hq_aliased_to", "slots": {slot:
{"derivative_sha256", "size_bytes"}}}``. The pin (source SHA + revision +
dims + transform) is persisted at lease; a job without a complete pin is
rejected fail-closed (no web_package job predates pinning, so there is no
legacy unpinned shape to honor). Legacy code ignores it. A job is
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
    _empty = {"source_sha256": None, "source_revision_id": None, "source_width": None,
              "source_height": None, "transform_version": None, "hq_aliased_to": None, "slots": {}}
    raw = getattr(job, "finalized_slots", None)
    if raw is None or raw == [] or raw == {}:
        return dict(_empty)
    if isinstance(raw, list):
        # Legacy unexpected shape: treat as slot list without pinning.
        slots: dict[str, Any] = {}
        for entry in raw:
            if isinstance(entry, dict) and entry.get("slot") and entry.get("derivative_sha256"):
                slots[entry["slot"]] = {
                    "derivative_sha256": entry["derivative_sha256"],
                    "size_bytes": entry.get("size_bytes"),
                }
        out = dict(_empty)
        out["slots"] = slots
        return out
    if isinstance(raw, dict):
        slots_raw = raw.get("slots", {})
        slots = dict(slots_raw) if isinstance(slots_raw, dict) else {}
        return {
            "source_sha256": raw.get("source_sha256") or raw.get("expected_source_sha256"),
            "source_revision_id": raw.get("source_revision_id"),
            "source_width": raw.get("source_width"),
            "source_height": raw.get("source_height"),
            "transform_version": raw.get("transform_version"),
            "hq_aliased_to": raw.get("hq_aliased_to"),
            "slots": slots,
        }
    return dict(_empty)


def set_finalized_state(job, state: dict[str, Any]) -> None:
    job.finalized_slots = {
        "source_sha256": state.get("source_sha256"),
        "source_revision_id": state.get("source_revision_id"),
        "source_width": state.get("source_width"),
        "source_height": state.get("source_height"),
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

    from sqlalchemy import cast, literal, select, Text

    from app.config import get_settings
    from app.models.media import MediaAgent

    if not get_settings().media_web_packages_enabled:
        return False
    cutoff = datetime.utcnow() - timedelta(minutes=15)
    # Bounded DB-side capability check: exact JSON-array membership via the
    # quote-delimited token (JSON encodes "web_package" with surrounding
    # quotes, so LIKE '%"web_package"%' cannot match not_web_package or
    # web_package_v2). Portable: PostgreSQL JSON cast to TEXT and SQLite
    # JSON TEXT both compare here; no ORM load, LIMIT 1, no Python fallback.
    stmt = (
        select(literal(1))
        .select_from(MediaAgent)
        .where(
            MediaAgent.active.is_(True),
            MediaAgent.leasing_enabled.is_(True),
            MediaAgent.last_seen_at.is_not(None),
            MediaAgent.last_seen_at >= cutoff,
            cast(MediaAgent.capabilities, Text).like('%"web_package"%'),
        )
        .limit(1)
    )
    return db.execute(stmt).scalar_one_or_none() is not None


def _server_source_dims(db, source_sha256: str) -> tuple[int | None, int | None]:
    """Server-verified canonical source dims (fail closed, never client trust).

    Preferred truth is ``MediaBlob.width/height`` for the pinned canonical
    SHA (populated by verified ingest). ``PhotosAsset`` dims are NOT used:
    they may reflect a non-canonical edited rendition (SAR/rotation) and
    cannot prove the camera bytes the encoder hashed. When the blob has no
    dims, return (None, None) so the alias path refuses (fail closed) instead
    of trusting the worker claim.
    """
    if not source_sha256:
        return None, None
    try:
        from app.models.media_backbone import MediaBlob

        blob = db.get(MediaBlob, source_sha256.lower()) if db is not None else None
        if blob is not None and blob.width and blob.height:
            try:
                w, h = int(blob.width), int(blob.height)
                if w > 0 and h > 0:
                    return w, h
            except (TypeError, ValueError):
                pass
    except Exception:
        pass
    return None, None


def _expected_short_side_dims(source_w: int, source_h: int, short_target: int) -> tuple[int, int]:
    """Mirror encoder ``short_side_target_dims`` (never upscale, always even).

    Used to validate exact target dims (no up/down beyond cap, ratio/SAR and
    orientation preserved). Duplicated here so the server does not import the
    Mac encoder.
    """
    if source_w < 2 or source_h < 2:
        raise ValueError(f"invalid source dims {source_w}x{source_h}")

    def _even_ceil(x: float) -> int:
        import math

        n = int(math.ceil(x))
        return n if n % 2 == 0 else n + 1

    short = min(source_w, source_h)
    long = max(source_w, source_h)
    portrait = source_h > source_w
    if short_target >= short:
        return (source_w - (source_w % 2), source_h - (source_h % 2))
    long_t = _even_ceil(long * short_target / short)
    max_long_even = long - (long % 2)
    if long_t > max_long_even:
        long_t = max_long_even
    target_even = short_target if short_target % 2 == 0 else short_target - 1
    if portrait:
        return (target_even, long_t)
    return (long_t, target_even)


def check_small_source_alias(
    *,
    db,
    job,
    slot: str,
    hq_aliased_to: str | None,
    claimed_w: int | None,
    claimed_h: int | None,
    probed_w: int | None,
    probed_h: int | None,
    source_sha256: str | None = None,
) -> list[str]:
    """Validate the hq_aliased_to claim against server truth, return applicable slots.

    Server truth is the LEASE-PINNED canonical source dims (``source_width`` /
    ``source_height`` persisted at lease from ``MediaBlob.width/height``),
    falling back to a live ``MediaBlob`` read only when the pin predates dims
    persistence. The worker claim (``claimed_w/h``) is NEVER trusted: it is
    accepted only as a consistency hint when server dims are known, and the
    alias is refused when server dims are unknown (fail closed). An alias
    requires a genuinely small source (short side < 1080) and, for the light
    slot, exact expected dims (no upscale, no over-cap, ratio/SAR and
    orientation preserved via the encoder's short-side rule).

    Non-alias slots: when server dims are known, hq/light/poster must ALL
    match exact expected dims (poster rides the encoder's light-scale branch,
    so poster expected == light expected). When server dims are unknown the
    alias is refused but non-alias slots are admitted on caps/format alone
    (even dims, short side within cap) — the server then CANNOT prove
    no-upscale; that residual is documented, enforced upstream by the
    reviewed worker encoder on the SHA-pinned source, and the canary must
    prefer sources with known canonical dims. No source-original download
    exists server-side to probe here, and client claims are never adopted.
    """
    if hq_aliased_to is not None and hq_aliased_to != "light":
        raise ValueError("hq_aliased_to must be 'light' when present")
    # Resolve the pinned source SHA: explicit param wins, else the job pin,
    # else the lease-time persisted pin. Never the worker claim.
    _pin_sha = source_sha256
    _pin_w = _pin_h = None
    if not _pin_sha:
        try:
            _st = get_finalized_state(job)
            _pin_sha = _st.get("source_sha256") or ""
            _pin_w, _pin_h = _st.get("source_width"), _st.get("source_height")
        except Exception:
            _pin_sha = ""
    else:
        try:
            _st = get_finalized_state(job)
            _pin_w, _pin_h = _st.get("source_width"), _st.get("source_height")
        except Exception:
            pass
    def _known_dims() -> tuple[int | None, int | None]:
        try:
            if _pin_w and _pin_h and int(_pin_w) > 0 and int(_pin_h) > 0:
                return int(_pin_w), int(_pin_h)
        except (TypeError, ValueError):
            pass
        if _pin_sha:
            return _server_source_dims(db, str(_pin_sha))
        return None, None
    if hq_aliased_to != "light":
        # Non-alias: when server dims + probed dims are both known, enforce
        # exact target dims for hq/light/poster (no up/down beyond cap,
        # ratio/SAR + orientation preserved). Poster rides the encoder's
        # light-scale branch: poster expected == light expected. When server
        # dims are unknown, caps are enforced by validate_slot_artifact;
        # exactness is checked when possible (documented residual).
        if probed_w is not None and probed_h is not None and _pin_sha:
            server_w, server_h = _known_dims()
            if server_w is not None and server_h is not None and slot in ("hq", "light", "poster"):
                try:
                    cap_target = _SHORT_SIDE_HQ_CAP if slot == "hq" else _SHORT_SIDE_LIGHT_CAP
                    exp_w, exp_h = _expected_short_side_dims(server_w, server_h, cap_target)
                except ValueError as exc:
                    raise ValueError(f"{slot} target dims invalid: {exc}") from exc
                if (int(probed_w), int(probed_h)) != (exp_w, exp_h):
                    raise ValueError(
                        f"{slot} dims {probed_w}x{probed_h} != expected {exp_w}x{exp_h} "
                        f"for source {server_w}x{server_h}"
                    )
        return list(PACKAGE_SLOTS)
    server_w, server_h = _known_dims()
    if server_w is None or server_h is None:
        raise ValueError("hq_aliased_to rejected: canonical source dims unknown; refusing alias (fail closed)")
    ref_short = _short_side(server_w, server_h)
    if ref_short is None or ref_short >= _SHORT_SIDE_HQ_CAP:
        raise ValueError(f"hq_aliased_to rejected: server source short side {ref_short} is not small")
    if slot == "light":
        if probed_w is None or probed_h is None:
            raise ValueError("light slot dims unreadable; cannot prove small-source alias")
        try:
            exp_w, exp_h = _expected_short_side_dims(server_w, server_h, _SHORT_SIDE_LIGHT_CAP)
        except ValueError as exc:
            raise ValueError(f"hq_aliased_to rejected: {exc}") from exc
        if (int(probed_w), int(probed_h)) != (exp_w, exp_h):
            raise ValueError(
                f"hq_aliased_to rejected: light dims {probed_w}x{probed_h} != expected {exp_w}x{exp_h} "
                f"for source {server_w}x{server_h}"
            )
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


def _ffmpeg_decode_ok(path: Path) -> bool | None:
    """Bounded decode probe: can ffmpeg decode the file to null (fail closed).

    Uses ``-xerror`` so corrupt/truncated packets FAIL (a plain decode
    returns 0 while concealing packet errors — proven by the real-MP4 tier:
    a 75%-truncated faststart file probes clean but must not validate).
    Returns True when decode succeeds, False when ffmpeg proves corrupt, None
    when ffmpeg is unavailable (caller fails closed for hq/light).
    """
    try:
        out = subprocess.run(
            ["ffmpeg", "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=60,
        )
        return out.returncode == 0
    except FileNotFoundError:
        return None
    except Exception:
        return False


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
    wrong containers, non-BT.709 outputs, non-faststart MP4s (None counts as
    failure), and undecodable packets (bounded ffmpeg decode to null).
    Packages must be SDR BT.709 H.264 High / yuv420p / MP4 faststart; posters
    must be real JPEGs (magic + mjpeg codec) with valid dims.
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
        profile = str(video.get("profile", "") or "")
        if profile.lower() != "high":
            raise ValueError(f"{slot} must be H.264 High profile (got {profile!r})")
        for _key in ("color_transfer", "color_primaries", "color_space"):
            _val = str(video.get(_key, "") or "").lower()
            if _val != "bt709":
                raise ValueError(f"{slot} must be BT.709 ({_key}={_val!r}); packages must be tone-mapped SDR")
        fmt_name = str((data.get("format", {}) or {}).get("format_name", "") or "").lower()
        if "mp4" not in fmt_name and "mov" not in fmt_name:
            raise ValueError(f"{slot} must be MP4 container (got {fmt_name!r})")
        if not width or not height or width <= 0 or height <= 0:
            raise ValueError(f"{slot} has invalid dims")
        if width % 2 or height % 2:
            raise ValueError(f"{slot} dims must be even (got {width}x{height})")
        _fast = _mp4_faststart_ok(path)
        if _fast is not True:
            raise ValueError(f"{slot} is not faststart (moov before mdat required, got {_fast})")
        short = _short_side(int(width), int(height))
        cap = _SHORT_SIDE_HQ_CAP if slot == "hq" else _SHORT_SIDE_LIGHT_CAP
        if short is not None and short > cap:
            raise ValueError(f"{slot} short side {short} exceeds cap {cap}")
        if _ffmpeg_decode_ok(path) is not True:
            raise ValueError(f"{slot} failed bounded decode probe; refusing corrupt packets")
    else:
        if video.get("codec_name") not in ("mjpeg", "jpg", "jpeg"):
            raise ValueError(f"poster must be JPEG (got {video.get('codec_name')!r})")
        if not width or not height or width <= 0 or height <= 0:
            raise ValueError("poster has invalid dims")
        if int(width) % 2 or int(height) % 2:
            raise ValueError(f"poster dims must be even (got {width}x{height})")
        _pshort = _short_side(int(width), int(height))
        if _pshort is not None and _pshort > _SHORT_SIDE_LIGHT_CAP:
            raise ValueError(f"poster short side {_pshort} exceeds cap {_SHORT_SIDE_LIGHT_CAP}")
    return {"width": int(width), "height": int(height), "codec": video.get("codec_name"), "pix_fmt": video.get("pix_fmt")}


def _is_ledger_slot_durable(db, *, video_uuid: str, source_sha256: str, role: str,
                            transform_version: str, derivative_sha256: str) -> bool:
    """True when the ledger + PROD replica prove this slot durable (fail closed).

    Requires a ``ready`` ``MediaDerivative`` row with the exact identity +
    bytes, plus a verified PROD B2 replica for the derivative bytes. DEV-only
    replicas, ``stale``/``verifying`` rows, removed rows, or SHA mismatches
    never count — so a DEV publish can never mark a production job ready, and
    a pruned/stale ledger cannot fake readiness.
    """
    try:
        from sqlalchemy import select

        from app.models.media_backbone import MediaBlobLocation, MediaDerivative

        row = db.execute(
            select(MediaDerivative).where(
                MediaDerivative.video_uuid == video_uuid,
                MediaDerivative.source_blob_sha256 == source_sha256.lower(),
                MediaDerivative.role == role,
                MediaDerivative.transform_version == transform_version,
            )
        ).scalar_one_or_none()
        if row is None or row.status != "ready":
            return False
        if str(row.derivative_blob_sha256 or "").lower() != derivative_sha256.lower():
            return False
        loc = db.execute(
            select(MediaBlobLocation).where(
                MediaBlobLocation.blob_sha256 == derivative_sha256.lower(),
                MediaBlobLocation.environment == "prod",
                MediaBlobLocation.verified.is_(True),
                MediaBlobLocation.storage_backend == "b2",
            ).limit(1)
        ).scalar_one_or_none()
        return loc is not None
    except Exception:
        return False


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
    claimed_transform_version: str | None = None,
):
    """Build the publisher pre-commit hook for one slot.

    Runs with the ledger row lock held, inside the committing unit: validates
    the D2 lease (owner/expiry/token via ``_guarded_job`` with row lock),
    the lease-pinned source/revision/version (claimed == pin == ctx on EVERY
    slot, explicit transform echo required — no ctx fallback, token bound to
    the same attempt), then accumulates the slot into
    ``finalized_slots`` and marks the job ready ONLY when every applicable
    slot is VERIFIED DURABLE in the ledger (PROD replica required; DEV never
    counts). The current slot is trusted via the publisher's roundtrip proof
    (same TX); prior slots are re-read from the ledger (stale/removed never
    counts). Idempotent per-slot retries (same bytes) dedupe; different bytes
    conflict. Alias cannot flip mid-package.
    """
    from app.services.media_jobs import LEASED_JOB_STATUSES, _guarded_job

    _slot = slot
    _applicable = list(applicable)

    def _hook(db, ctx, *, derivative_sha, derivative_size, object_key, bucket, environment) -> None:
        from datetime import datetime

        if _slot not in _applicable:
            raise ValueError(f"slot {_slot!r} is not applicable for this package")
        # Applicable must match the alias (cannot smuggle hq when aliased).
        _expected_applicable = ["light", "poster"] if hq_aliased_to == "light" else ["hq", "light", "poster"]
        if sorted(_applicable) != sorted(_expected_applicable):
            raise ValueError(f"applicable {sorted(_applicable)} does not match hq_aliased_to={hq_aliased_to!r}")
        # Row-locked authoritative lease recheck: expiry, owner, token. A
        # mid-upload re-lease (even to the SAME agent) carries a new token,
        # so the stale attempt's token mismatches here and its verified B2
        # bytes stay a safe orphan. The job row lock is held through commit
        # (FOR UPDATE in this TX), so expiry cannot slip between this check
        # and the commit; reclaim blocks on the same row lock.
        try:
            job = _guarded_job(db, job_id, agent_id, lease_token, None, lock=True)
        except ValueError:
            # Job vanished — fail closed without promoting.
            from app.services.derivative_publisher import StaleSourceError

            raise StaleSourceError("package job not found; refusing ready") from None
        if getattr(job, "rendition", None) != "web_package":
            raise ValueError("package slot guard requires a web_package job")
        # Lease-pinned identity: claimed == pin == ctx on EVERY slot.
        # The pin was persisted at lease (source SHA + revision + version).
        # Fail closed on a missing pin: no web_package job predates lease
        # pinning (the rendition never queued before this flag), so a job
        # without a pin is never "legacy" — it is corrupt/stale and must
        # re-lease, never bind from worker claims. A source change between
        # lease and first slot REJECTS (not retags), and a transform
        # mismatch on any slot rejects. No ctx fallback for a missing
        # claim: tests and callers must echo the lease transform explicitly.
        state = get_finalized_state(job)
        _pinned_source = (state.get("source_sha256") or "")
        _pinned_version = state.get("transform_version")
        _pinned_rev = state.get("source_revision_id")
        _pinned_alias = state.get("hq_aliased_to")
        _claimed_source = (claimed_source_sha256 or "").lower()
        _ctx_source = (ctx.source_blob_sha256 or "").lower()
        _ctx_version = (ctx.transform_version or "")
        if not _pinned_source or not _pinned_version or _pinned_rev is None:
            from app.services.derivative_publisher import StaleSourceError

            raise StaleSourceError(
                "package job has no lease pin (source/revision/version); re-lease required"
            )
        if not claimed_transform_version or not str(claimed_transform_version).strip():
            raise ValueError("package slot request is missing the lease transform pin")
        if transform_version is None or not str(transform_version).strip():
            raise ValueError("package slot guard is missing the lease transform pin")
        _claimed_version = str(claimed_transform_version).strip()
        if str(transform_version).strip() != _claimed_version:
            raise ValueError(
                f"package transform mismatch: guard {_claimed_version!r} != request {transform_version!r}"
            )
        if _claimed_source != _pinned_source.lower():
            from app.services.derivative_publisher import StaleSourceError

            raise StaleSourceError(
                "package slot source does not match lease pin; refusing ready (source changed since lease)"
            )
        if _ctx_source != _pinned_source.lower():
            from app.services.derivative_publisher import StaleSourceError

            raise StaleSourceError("package slot source does not match canonical source; refusing ready")
        if _claimed_version != str(_pinned_version).strip():
            raise ValueError(
                f"package transform mismatch: claimed {_claimed_version!r} != lease pin {_pinned_version!r}"
            )
        if str(_ctx_version or "").strip() != str(_pinned_version).strip():
            from app.services.derivative_publisher import StaleSourceError

            raise StaleSourceError(
                f"package transform drifted: ctx {_ctx_version!r} != lease pin {_pinned_version!r}"
            )
        try:
            _ctx_rev_id = int(getattr(ctx, "source_revision_id", 0) or 0) or None
        except (TypeError, ValueError):
            _ctx_rev_id = None
        try:
            _pin_rev_id = int(_pinned_rev) if _pinned_rev is not None else None
        except (TypeError, ValueError):
            _pin_rev_id = None
        if _pin_rev_id is None or _ctx_rev_id != _pin_rev_id:
            from app.services.derivative_publisher import StaleSourceError

            raise StaleSourceError(
                "package source revision changed since lease; refusing ready"
            )
        # Alias cannot flip mid-package. The lease persists
        # hq_aliased_to=None meaning "not yet decided": the FIRST slot (no
        # EARLIER slots finalized yet) decides it; once any earlier slot is
        # finalized the alias is pinned — including None (an hq-finalized
        # package can never become light-aliased later: NONE -> light
        # after an hq slot rejects here).
        _prior_slots = {k: v for k, v in state.get("slots", {}).items() if k != _slot}
        if _prior_slots:
            if hq_aliased_to != _pinned_alias:
                raise ValueError("hq_aliased_to changed between slots in one package")
        if job.status == "ready":
            # Idempotent replay after completion: only the exact same bytes
            # for an already-finalized slot dedupe; anything else is stale.
            prev = state.get("slots", {}).get(_slot)
            if prev is not None and str(prev.get("derivative_sha256", "")).lower() == derivative_sha.lower():
                return
            from app.services.derivative_publisher import StaleSourceError

            raise StaleSourceError("package job already ready; refusing additional slot bytes")
        if job.status not in LEASED_JOB_STATUSES and job.status != "verifying":
            raise PermissionError(f"media_job_invalid_state:{job.status}")
        # Lease state is enforced by _guarded_job above (owner/expiry/token).
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
        # The lease pin is authoritative and already proven above
        # (claimed == pin == ctx for source, revision and transform). The
        # only decision a slot records is the alias: the lease persists
        # hq_aliased_to=None ("not yet decided") and the first slot sets it;
        # later slots must agree (enforced above against earlier slots, and
        # rechecked here against the stored value).
        if state.get("hq_aliased_to") is None:
            state["hq_aliased_to"] = hq_aliased_to
        if hq_aliased_to != state.get("hq_aliased_to"):
            raise ValueError("hq_aliased_to changed between slots in one package")
        set_finalized_state(job, state)
        # Ready ONLY when every applicable slot is VERIFIED DURABLE in the
        # ledger (PROD replica). The current slot is proven by this TX's
        # roundtrip (upload + full-byte verify already passed, ledger commit
        # follows atomically below) — but only when publishing in PROD. DEV
        # publishes never mark ready. Prior slots are re-read from the ledger:
        # stale/removed/mismatched bytes never count.
        _video_uuid = job.asset.video_uuid if getattr(job, "asset", None) is not None else ctx.video_uuid
        _pin_source = str(state.get("source_sha256") or _ctx_source)
        _pin_version = str(state.get("transform_version") or _ctx_version)
        _all_durable = True
        for _role in _applicable:
            _entry = state.get("slots", {}).get(_role)
            if _entry is None:
                _all_durable = False
                break
            if _role == _slot:
                if str(environment or "").lower() != "prod":
                    _all_durable = False
                    break
                continue
            if not _is_ledger_slot_durable(
                db,
                video_uuid=_video_uuid,
                source_sha256=_pin_source,
                role=_role,
                transform_version=_pin_version,
                derivative_sha256=str(_entry.get("derivative_sha256") or ""),
            ):
                _all_durable = False
                break
        # The current slot's own ledger row commits atomically below; the
        # durable proof for it is this TX (roundtrip verified + PROD env).
        # Prior slots must already be durable per the loop above.
        if _all_durable and str(environment or "").lower() == "prod":
            # Final gate: the current slot's env must be PROD (checked above
            # via the loop's _role == _slot branch) and every prior slot must
            # be ledger-durable. Mark ready.
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
