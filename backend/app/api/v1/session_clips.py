"""Session clip auto-detection runs, fast 5-minute triage, GT export, and Mac cut leases."""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import shutil
import subprocess
import threading
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.api.v1.dive_sharing import same_origin, secure_headers
from app.api.v1.session_videos import require_enabled
from app.config import get_settings
from app.database import get_db
from app.models.session_video import SessionVideo
from app.models.user_auth import AppUser
from app.security import verify_media_worker_key
from app.services import browser_upload
from app.services import session_clip_triage as triage
from app.services.media_agents import authenticate_media_agent, require_leasing_agent
from app.services.offload import run_to_completion
from app.services.write_guard import _valid_machine_api_key

router = APIRouter()

MAX_CUT_UPLOAD_BYTES = 250 * 1024 * 1024  # 250 MiB per cut clip
MIN_FREE_DISK_BYTES = 2 * MAX_CUT_UPLOAD_BYTES
MAX_CANDIDATE_META_BYTES = 4096
MAX_CLIP_RUN_JSON_BYTES = 2 * 1024 * 1024  # 2 MiB hard pre-parse cap for clip-run submission
MAX_CLIP_CONTROL_JSON_BYTES = 32 * 1024  # 32 KiB hard pre-parse cap for triage PATCH / worker JSON
# 1 slot per uvicorn process (production runs 2 workers -> max 2 concurrent fleet-wide).
_COMPLETE_SLOTS = threading.BoundedSemaphore(1)


async def _read_bounded_json(request: Request, max_bytes: int) -> Any:
    """Enforce a hard byte cap BEFORE buffering or parsing JSON (guards 2 GiB nginx proxy limit)."""
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > max_bytes:
                raise HTTPException(413, "Request body exceeds maximum allowed size")
        except ValueError:
            raise HTTPException(400, "Invalid Content-Length") from None
    buf = bytearray()
    async for chunk in request.stream():
        if not chunk:
            continue
        if len(buf) + len(chunk) > max_bytes:
            raise HTTPException(413, "Request body exceeds maximum allowed size")
        buf.extend(chunk)
    try:
        return json.loads(buf.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(422, "Request body must be valid UTF-8 JSON") from None


def _bounded_model_dep(model_cls: type[BaseModel], max_bytes: int):
    async def _parse_bounded(request: Request):
        raw = await _read_bounded_json(request, max_bytes)
        try:
            return model_cls.model_validate(raw)
        except ValidationError as exc:
            raise RequestValidationError(exc.errors()) from None

    return _parse_bounded


def _admin_or_api_key(
    request: Request,
    x_api_key: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> Optional[AppUser]:
    """Allow either a machine API key (CLI / detector script) or a signed-in manager."""
    if _valid_machine_api_key(request):
        return None
    if x_api_key:
        raise HTTPException(401, "Invalid API key")
    user = getattr(request.state, "member_user", None)
    if user is None:
        user = get_current_user(request, db)
    return user


def _worker_agent_auth(db: Session, agent_id: str, api_key: dict, *, leasing: bool = False):
    """Bind the presented worker key to the supplied agent_id (mirrors media.py)."""
    try:
        if leasing:
            return require_leasing_agent(db, agent_id, api_key["key"])
        return authenticate_media_agent(db, agent_id, api_key["key"])
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc


# ------------------------------------------------ Detection runs & GT export ---


class CandidateSubmitItem(BaseModel):
    start_s: float = Field(..., ge=0.0, allow_inf_nan=False)
    end_s: float = Field(..., gt=0.0, allow_inf_nan=False)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0, allow_inf_nan=False)
    label: Optional[str] = Field(default=None, max_length=80)
    meta: Optional[dict[str, Any]] = None

    @field_validator("meta")
    @classmethod
    def _validate_meta(cls, value: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
        if value is None:
            return None
        try:
            encoded = json.dumps(value, allow_nan=False).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise HTTPException(422, "meta must be valid finite JSON") from exc
        if len(encoded) > MAX_CANDIDATE_META_BYTES:
            raise HTTPException(422, f"meta exceeds {MAX_CANDIDATE_META_BYTES} bytes")
        return value


class ClipRunSubmitInput(BaseModel):
    detector_name: str = Field(..., min_length=1, max_length=80)
    detector_version: str = Field(..., min_length=1, max_length=80)
    params_json: Optional[dict[str, Any]] = None
    candidates: list[CandidateSubmitItem] = Field(..., max_length=triage.MAX_CANDIDATES_PER_RUN)

    @field_validator("params_json")
    @classmethod
    def _validate_params_json(cls, value: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
        if value is None:
            return None
        try:
            encoded = json.dumps(value, allow_nan=False).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise HTTPException(422, "params_json must be valid finite JSON") from exc
        if len(encoded) > MAX_CANDIDATE_META_BYTES:
            raise HTTPException(422, f"params_json exceeds {MAX_CANDIDATE_META_BYTES} bytes")
        return value


@router.get("/clip-triage/resolve-video", dependencies=[Depends(require_enabled)])
def resolve_session_video(
    filename: str = Query(..., min_length=1, max_length=255),
    response: Response = None,
    actor: Optional[AppUser] = Depends(_admin_or_api_key),
    db: Session = Depends(get_db),
):
    """Resolve a raw recording basename (e.g. IMG_2651.MOV) in SQL without row-cap misses."""
    target = PurePosixPath(filename.replace("\\", "/")).name.lower()
    if not target:
        raise HTTPException(422, "Invalid filename")
    escaped = target.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    query = db.query(SessionVideo).filter(
        SessionVideo.status == "ready",
        SessionVideo.deleted_at.is_(None),
        or_(
            func.lower(SessionVideo.object_key) == target,
            func.lower(SessionVideo.object_key).like(f"%/{escaped}", escape="\\"),
        ),
    )
    if actor is not None and not actor.is_admin:
        query = query.filter(SessionVideo.owner_user_id == actor.id)
    rows = (
        query.order_by(SessionVideo.recorded_at.desc().nullslast(), SessionVideo.id.desc())
        .limit(20)
        .all()
    )
    matches = [
        {
            "id": v.id,
            "session_id": v.session_id,
            "filename": PurePosixPath(v.object_key).name,
            "recorded_date": v.recorded_date.isoformat() if v.recorded_date else None,
            "duration_seconds": v.duration_seconds,
        }
        for v in rows
        if PurePosixPath(v.object_key).name.lower() == target
    ]
    if response is not None:
        secure_headers(response)
    return {"items": matches}


@router.post(
    "/session-videos/{video_id}/clip-runs",
    status_code=201,
    dependencies=[Depends(require_enabled)],
)
def submit_clip_run(
    video_id: int,
    request: Request,
    response: Response,
    payload: ClipRunSubmitInput = Depends(_bounded_model_dep(ClipRunSubmitInput, MAX_CLIP_RUN_JSON_BYTES)),
    actor: Optional[AppUser] = Depends(_admin_or_api_key),
    db: Session = Depends(get_db),
):
    if actor is not None:
        same_origin(request)
    result = triage.submit_clip_run(
        db,
        video_id=video_id,
        detector_name=payload.detector_name,
        detector_version=payload.detector_version,
        candidates=[c.model_dump() for c in payload.candidates],
        params_json=payload.params_json,
        submitted_by=actor,
    )
    secure_headers(response)
    return result


def _authorized_ready_video(db: Session, video_id: int, actor: Optional[AppUser]) -> SessionVideo:
    video = db.get(SessionVideo, video_id)
    if (
        video is None
        or video.status != "ready"
        or video.deleted_at is not None
        or (actor is not None and not triage.can_manage_video(actor, video))
    ):
        raise HTTPException(404, "Session video not found")
    return video


@router.get("/session-videos/{video_id}/clip-runs", dependencies=[Depends(require_enabled)])
def get_clip_runs(
    video_id: int,
    response: Response,
    limit: int = Query(default=triage.DEFAULT_RUNS_PAGE_LIMIT, ge=1, le=triage.MAX_RUNS_PAGE_LIMIT),
    offset: int = Query(default=0, ge=0),
    actor: Optional[AppUser] = Depends(_admin_or_api_key),
    db: Session = Depends(get_db),
):
    video = _authorized_ready_video(db, video_id, actor)
    secure_headers(response)
    page = triage.list_video_runs(db, video, limit=limit, offset=offset)
    return {"session_video_id": video.id, **page}


@router.get("/session-videos/{video_id}/clip-gt", dependencies=[Depends(require_enabled)])
def export_clip_gt(
    video_id: int,
    response: Response,
    limit: int = Query(default=triage.MAX_GT_PAGE_LIMIT, ge=1, le=triage.MAX_GT_PAGE_LIMIT),
    offset: int = Query(default=0, ge=0),
    actor: Optional[AppUser] = Depends(_admin_or_api_key),
    db: Session = Depends(get_db),
):
    video = _authorized_ready_video(db, video_id, actor)
    secure_headers(response)
    return triage.export_video_ground_truth(db, video, limit=limit, offset=offset, viewer=actor)


@router.get("/session-videos/{video_id}/clip-gt/export", dependencies=[Depends(require_enabled)])
def export_clip_gt_stream(
    video_id: int,
    cursor: Optional[str] = Query(default=None, max_length=512),
    max_bytes: int = Query(
        default=triage.GT_EXPORT_MAX_BYTES,
        ge=triage.GT_EXPORT_MIN_BYTES,
        le=triage.GT_EXPORT_MAX_BYTES,
    ),
    actor: Optional[AppUser] = Depends(_admin_or_api_key),
    db: Session = Depends(get_db),
):
    """Stream bounded Ground Truth JSON pages with explicit cursor continuation."""
    video = _authorized_ready_video(db, video_id, actor)
    cursor_state = triage.decode_gt_export_cursor(cursor)
    stem = PurePosixPath(video.object_key).stem
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._") or "video"
    resp = StreamingResponse(
        triage.iter_video_ground_truth_json(
            db,
            video,
            viewer=actor,
            cursor_state=cursor_state,
            max_bytes=max_bytes,
        ),
        media_type="application/json; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="gt-{safe_stem}-v{video.id}.json"',
        },
    )
    secure_headers(resp)
    return resp


# --------------------------------------------------------- Fast Triage UI API ---


@router.get("/clip-triage/summary", dependencies=[Depends(require_enabled)])
def triage_summary(
    response: Response,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    secure_headers(response)
    return triage.get_triage_summary(db, user)


@router.get("/clip-triage/sessions", dependencies=[Depends(require_enabled)])
def list_triage_sessions(
    response: Response,
    q: Optional[str] = Query(default=None, max_length=60),
    limit: int = Query(default=triage.DEFAULT_SESSION_PAGE_LIMIT, ge=1, le=triage.MAX_SESSION_PAGE_LIMIT),
    offset: int = Query(default=0, ge=0),
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    secure_headers(response)
    return triage.list_triage_sessions(db, user, q=q, limit=limit, offset=offset)


@router.get("/clip-triage/divers", dependencies=[Depends(require_enabled)])
def list_triage_divers(
    response: Response,
    q: Optional[str] = Query(default=None, max_length=120),
    session_id: Optional[int] = Query(default=None),
    limit: int = Query(default=triage.DEFAULT_DIVER_PAGE_LIMIT, ge=1, le=triage.MAX_DIVER_PAGE_LIMIT),
    offset: int = Query(default=0, ge=0),
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    secure_headers(response)
    authorized_sess_ids: list[int] = []
    if session_id is not None:
        v_q = db.query(SessionVideo.id).filter(
            *triage._manageable_video_filter(user),
            SessionVideo.session_id == session_id,
        )
        if v_q.limit(1).first() is not None:
            authorized_sess_ids = [session_id]
    return triage.list_triage_divers(
        db,
        user,
        authorized_session_ids=authorized_sess_ids,
        q=q,
        limit=limit,
        offset=offset,
    )


def _parse_exclude_ids(raw: Optional[str]) -> Optional[list[int]]:
    if not raw:
        return None
    parsed: list[int] = []
    for part in raw.split(","):
        tok = part.strip()
        if not tok:
            continue
        try:
            val = int(tok)
        except ValueError:
            raise HTTPException(422, "Invalid exclude_ids parameter") from None
        if val > 0:
            parsed.append(val)
        if len(parsed) >= 100:
            break
    return parsed or None


@router.get("/clip-triage/candidates", dependencies=[Depends(require_enabled)])
def list_triage_candidates(
    response: Response,
    tab: Literal["pending", "incomplete", "recent", "all"] = Query(default="pending"),
    session_id: Optional[int] = Query(default=None),
    session_video_id: Optional[int] = Query(default=None),
    limit: int = Query(default=triage.DEFAULT_PAGE_LIMIT, ge=1, le=triage.MAX_PAGE_LIMIT),
    offset: int = Query(default=0, ge=0),
    exclude_ids: Optional[str] = Query(default=None, max_length=1200),
    cursor: Optional[str] = Query(default=None, max_length=512),
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    secure_headers(response)
    return triage.list_triage_candidates(
        db,
        user,
        tab=tab,
        session_id=session_id,
        session_video_id=session_video_id,
        limit=limit,
        offset=offset,
        exclude_ids=_parse_exclude_ids(exclude_ids),
        cursor=cursor,
    )


@router.get("/clip-triage/candidates/{candidate_id}", dependencies=[Depends(require_enabled)])
def get_triage_candidate(
    candidate_id: int,
    response: Response,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    secure_headers(response)
    return triage.get_triage_candidate(db, user, candidate_id)


class CandidatePatchInput(BaseModel):
    triage_status: Optional[Literal["pending", "kept", "rejected"]] = None
    reject_reason: Optional[Literal["false_positive", "duplicate", "incomplete", "other"]] = None
    skip: Optional[bool] = None
    confirm_publish: Optional[bool] = None
    trimmed_start_s: Optional[float] = Field(default=None, ge=0.0, allow_inf_nan=False)
    trimmed_end_s: Optional[float] = Field(default=None, gt=0.0, allow_inf_nan=False)
    diver_id: Optional[int] = None
    dive_code: Optional[str] = Field(default=None, max_length=10)
    height: Optional[str] = Field(default=None, max_length=5)
    performance: Optional[str] = Field(default=None, max_length=1)
    phase1_performance: Optional[str] = Field(default=None, max_length=1)
    phase2_performance: Optional[str] = Field(default=None, max_length=1)
    notes: Optional[str] = Field(default=None, max_length=2000)
    visibility: Optional[Literal["private", "public"]] = None


@router.patch(
    "/clip-triage/candidates/{candidate_id}",
    dependencies=[Depends(require_enabled), Depends(same_origin)],
)
def patch_candidate(
    candidate_id: int,
    response: Response,
    payload: CandidatePatchInput = Depends(_bounded_model_dep(CandidatePatchInput, MAX_CLIP_CONTROL_JSON_BYTES)),
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(422, "Nothing to update")
    updated = triage.update_candidate(db, user, candidate_id, data)
    secure_headers(response)
    return updated


@router.post(
    "/clip-triage/candidates/{candidate_id}/retry-extraction",
    dependencies=[Depends(require_enabled), Depends(same_origin)],
)
def retry_extraction(
    candidate_id: int,
    response: Response,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    updated = triage.retry_candidate_extraction(db, user, candidate_id)
    secure_headers(response)
    return updated


# ---------------------------------------------- Mac-agent clip-cut worker API ---


class ClipCutLeaseInput(BaseModel):
    agent_id: str = Field(..., min_length=1, max_length=100)
    limit: int = Field(default=1, ge=1, le=4)


class ClipCutHeartbeatInput(BaseModel):
    agent_id: str = Field(..., min_length=1, max_length=100)
    lease_token: str = Field(..., min_length=8, max_length=64)
    cut_revision: int = Field(..., ge=1)


class ClipCutFailInput(ClipCutHeartbeatInput):
    error: str = Field(..., min_length=1, max_length=240)
    defer: bool = False


@router.post("/media/clip-cuts/lease", dependencies=[Depends(require_enabled)])
def lease_clip_cuts(
    payload: ClipCutLeaseInput = Depends(_bounded_model_dep(ClipCutLeaseInput, MAX_CLIP_CONTROL_JSON_BYTES)),
    api_key: dict = Depends(verify_media_worker_key),
    db: Session = Depends(get_db),
):
    agent = _worker_agent_auth(db, payload.agent_id, api_key, leasing=True)
    jobs = triage.lease_clip_cuts(db, agent_id=agent.id, limit=payload.limit)
    return {"jobs": jobs}


@router.post("/media/clip-cuts/{candidate_id}/heartbeat", dependencies=[Depends(require_enabled)])
def heartbeat_clip_cut(
    candidate_id: int,
    payload: ClipCutHeartbeatInput = Depends(_bounded_model_dep(ClipCutHeartbeatInput, MAX_CLIP_CONTROL_JSON_BYTES)),
    api_key: dict = Depends(verify_media_worker_key),
    db: Session = Depends(get_db),
):
    agent = _worker_agent_auth(db, payload.agent_id, api_key, leasing=False)
    return triage.heartbeat_clip_cut(
        db,
        candidate_id=candidate_id,
        agent_id=agent.id,
        lease_token=payload.lease_token,
        cut_revision=payload.cut_revision,
    )


@router.post("/media/clip-cuts/{candidate_id}/fail", dependencies=[Depends(require_enabled)])
def fail_clip_cut(
    candidate_id: int,
    payload: ClipCutFailInput = Depends(_bounded_model_dep(ClipCutFailInput, MAX_CLIP_CONTROL_JSON_BYTES)),
    api_key: dict = Depends(verify_media_worker_key),
    db: Session = Depends(get_db),
):
    agent = _worker_agent_auth(db, payload.agent_id, api_key, leasing=False)
    return triage.fail_clip_cut(
        db,
        candidate_id=candidate_id,
        agent_id=agent.id,
        lease_token=payload.lease_token,
        cut_revision=payload.cut_revision,
        error=payload.error,
        defer=payload.defer,
    )


def _probe_and_poster_mp4(
    mp4_path: Path,
    poster_path: Path,
    expected_duration_s: float,
) -> tuple[int, int, float, int, str]:
    """Validate uploaded H.264 MP4 against leased duration, derive dimensions, and render poster.jpg."""
    probe = subprocess.run(
        [
            "ffprobe",
            "-v", "error",
            "-protocol_whitelist", "file,pipe",
            "-f", "mov",
            "-show_streams",
            "-show_format",
            "-of", "json",
            str(mp4_path),
        ],
        capture_output=True,
        timeout=30,
    )
    if probe.returncode != 0:
        raise HTTPException(422, "Uploaded clip is not a valid MP4 video")
    try:
        meta = json.loads(probe.stdout.decode("utf-8", errors="replace") or "{}")
    except json.JSONDecodeError:
        raise HTTPException(422, "Unable to parse uploaded video metadata") from None

    vstream = next((s for s in meta.get("streams", []) if s.get("codec_type") == "video"), None)
    if vstream is None:
        raise HTTPException(422, "Uploaded clip contains no video stream")
    if (vstream.get("codec_name") or "").lower() != "h264":
        raise HTTPException(422, "Uploaded clip video stream must be H.264")
    try:
        width = int(vstream.get("width", 0))
        height = int(vstream.get("height", 0))
        duration = float(meta.get("format", {}).get("duration", 0))
    except (TypeError, ValueError):
        raise HTTPException(422, "Invalid video dimensions or duration") from None

    if (
        width <= 0
        or height <= 0
        or width * height > 4096 * 2160
        or not math.isfinite(duration)
        or duration <= 0.0
        or duration > triage.MAX_CLIP_SPAN_S + 2.0
    ):
        raise HTTPException(422, "Uploaded clip exceeds duration or resolution limits")

    tolerance = max(1.0, min(2.5, expected_duration_s * 0.15))
    if abs(duration - expected_duration_s) > tolerance:
        raise HTTPException(
            422,
            f"Uploaded clip duration ({duration:.2f}s) does not match expected window ({expected_duration_s:.2f}s)",
        )

    offset = min(max(0.1, duration * 0.35), max(0.1, duration - 0.1))
    poster_proc = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-nostdin",
            "-v", "error",
            "-protocol_whitelist", "file,pipe",
            "-ss", f"{offset:.2f}",
            "-i", str(mp4_path),
            "-frames:v", "1",
            "-q:v", "3",
            str(poster_path),
        ],
        capture_output=True,
        timeout=30,
    )
    if poster_proc.returncode != 0 or not poster_path.is_file() or poster_path.stat().st_size == 0:
        raise HTTPException(422, "Unable to render clip poster from uploaded video")

    p_bytes = poster_path.read_bytes()
    return width, height, duration, len(p_bytes), hashlib.sha256(p_bytes).hexdigest()


@router.post("/media/clip-cuts/{candidate_id}/complete", dependencies=[Depends(require_enabled)])
async def complete_clip_cut(
    candidate_id: int,
    request: Request,
    x_media_agent_id: str = Header(..., min_length=1, max_length=100),
    x_lease_token: str = Header(..., min_length=8, max_length=64),
    x_cut_revision: int = Header(..., ge=1),
    api_key: dict = Depends(verify_media_worker_key),
    db: Session = Depends(get_db),
):
    """Stream raw MP4 only AFTER agent auth, lease fence, size and disk checks.

    All synchronous DB locks run off the event loop via `run_to_completion(asyncio.to_thread(...))`.
    Validates H.264 MP4 via ffprobe, persists durable verified original to B2,
    registers MediaRevision + MediaCacheEntry, and publishes if confirmed.
    """
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_CUT_UPLOAD_BYTES:
                raise HTTPException(413, "Uploaded clip exceeds maximum allowed size")
        except ValueError:
            raise HTTPException(400, "Invalid Content-Length") from None

    # 1. Authenticate worker & pre-fence lease off the event loop BEFORE touching disk or streaming body.
    def _preflight() -> tuple[str, Optional[str], float]:
        agent = _worker_agent_auth(db, x_media_agent_id, api_key, leasing=False)
        _, cand = triage.require_valid_lease_context(
            db, candidate_id, agent.id, x_lease_token, x_cut_revision
        )
        clip_uuid_val = cand.clip_video_uuid
        expected_dur = max(0.5, float(cand.effective_end_s - cand.effective_start_s))
        db.rollback()  # Release read/lock tx before streaming/ffprobe/B2 I/O.
        return agent.id, clip_uuid_val, expected_dur

    agent_id, clip_uuid, expected_duration_s = await run_to_completion(asyncio.to_thread(_preflight))
    if not clip_uuid:
        raise HTTPException(409, "Clip identity missing")

    if not _COMPLETE_SLOTS.acquire(blocking=False):
        raise HTTPException(429, "Clip upload processor busy; retry shortly", headers={"Retry-After": "2"})

    folder: Optional[Path] = None
    # Mutated inside _finalize() right after DB commit so a mid-commit CancelledError
    # re-raised by run_to_completion NEVER deletes the just-committed local files!
    committed_flag = {"ok": False}
    try:
        root = Path(get_settings().media_cache_root).resolve() / "session-clips"
        root.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(root).free < MIN_FREE_DISK_BYTES:
            raise HTTPException(507, "Media staging disk temporarily full")

        folder = root / f"cand-{candidate_id}-r{x_cut_revision}-{uuid4().hex[:8]}"
        folder.mkdir(parents=True, exist_ok=True)
        mp4_path = folder / "original.mp4"
        poster_path = folder / "poster.jpg"

        # 2. Bounded streaming write directly to staging MP4.
        size = 0
        digest = hashlib.sha256()
        with mp4_path.open("xb") as handle:
            async for chunk in request.stream():
                if not chunk:
                    continue
                size += len(chunk)
                if size > MAX_CUT_UPLOAD_BYTES:
                    raise HTTPException(413, "Uploaded clip exceeds maximum allowed size")
                digest.update(chunk)
                await run_to_completion(asyncio.to_thread(handle.write, chunk))
        if size == 0:
            raise HTTPException(422, "Uploaded clip is empty")
        mp4_sha = digest.hexdigest()

        # 3. Record durable pre-upload B2 staging ledger, validate H.264 MP4 via ffprobe,
        # render poster, and roundtrip-verify B2 original.
        def _record_pre_upload_stage():
            settings = get_settings()
            if (
                settings.b2_upload_key_id
                and settings.b2_upload_key_secret
                and settings.b2_upload_region
                and settings.b2_upload_environment in ("dev", "prod")
            ):
                from app.services.media_backbone import environment_bucket

                bucket = environment_bucket(settings.b2_upload_environment)
                key = f"{settings.media_backbone_object_prefix}/{mp4_sha[:2]}/{mp4_sha}"
                triage.record_staging_b2_object(
                    db,
                    bucket=bucket,
                    object_key=key,
                    blob_sha256=mp4_sha,
                    byte_size=size,
                    candidate_id=candidate_id,
                )

        await run_to_completion(asyncio.to_thread(_record_pre_upload_stage))

        def _validate_and_persist():
            width, height, duration, p_size, p_sha = _probe_and_poster_mp4(
                mp4_path, poster_path, expected_duration_s
            )
            manifest = browser_upload.persist_original(
                None, clip_uuid, folder, register=False, source_name="original.mp4"
            )
            manifest["width"] = width
            manifest["height"] = height
            manifest["rendition_semantics"] = "session_clip_cut"
            manifest["source_provenance"] = {
                "source": "session_clip_cut",
                "candidate_id": candidate_id,
                "cut_revision": x_cut_revision,
            }
            manifest["ingest_impl_version"] = "session_clip_cut_v1"
            return width, height, duration, p_size, p_sha, manifest

        width, height, duration, p_size, p_sha, b2_manifest = await run_to_completion(
            asyncio.to_thread(_validate_and_persist)
        )

        # Ensure the exact uploaded (bucket, object_key) from persist_original is durably
        # tracked BEFORE finalization so a 409/revoked lease leaves a reclaimable orphan row.
        def _record_uploaded_stage():
            if b2_manifest.get("bucket") and b2_manifest.get("object_key"):
                triage.record_staging_b2_object(
                    db,
                    bucket=str(b2_manifest["bucket"]),
                    object_key=str(b2_manifest["object_key"]),
                    blob_sha256=str(b2_manifest.get("blob_sha256") or mp4_sha),
                    byte_size=int(b2_manifest.get("byte_size") or size),
                    candidate_id=candidate_id,
                )

        await run_to_completion(asyncio.to_thread(_record_uploaded_stage))

        # 4. Final locked DB commit & optional auto-publish off the event loop.
        def _finalize():
            res = triage.complete_clip_cut(
                db,
                candidate_id=candidate_id,
                agent_id=agent_id,
                lease_token=x_lease_token,
                cut_revision=x_cut_revision,
                mp4_path=mp4_path,
                mp4_sha256=mp4_sha,
                mp4_size_bytes=size,
                b2_manifest=b2_manifest,
                poster_path=poster_path,
                poster_sha256=p_sha,
                poster_size_bytes=p_size,
                width=width,
                height=height,
                duration_seconds=duration,
            )
            committed_flag["ok"] = True
            return res

        return await run_to_completion(asyncio.to_thread(_finalize))
    finally:
        _COMPLETE_SLOTS.release()
        if not committed_flag["ok"] and folder is not None:
            shutil.rmtree(folder, ignore_errors=True)
