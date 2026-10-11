"""Evaluation-scope authorization and media transport (ticket 1).

The Dive visibility model is untouched: private dives stay invisible to the
Library, analytics and derived data through the request-wide ORM filter in
``dive_access``. Evaluation access is a separate, narrow server scope:

* an authenticated member + an ACTIVE evaluation request grants media access
  to that one dive inside Évaluations only (status/poster/playback/preparation
  endpoints below);
* every call re-verifies the member, the active state and the
  request↔dive↔media correspondence. No client boolean is authoritative;
* deactivating the request removes the eligibility immediately (uniform 404,
  no existence disclosure);
* B2 originals use redirects signed for at most five minutes, after each
  request re-authorizes the evaluation. Cached media uses authenticated URLs. Browser
  caching is limited (``Cache-Control: private, max-age=300``, account-scoped
  URLs) and documented here — after deactivation a browser may keep media for
  up to five minutes; server eligibility is revoked at once.

Old-schema compatibility (mirrors the fediverse pattern): reads treat missing
``evaluation_requests`` as "no requests"; writes fail closed with 503 until
``add_evaluation_requests.sql`` is applied.

The request-wide ORM filter also scopes models linked by dive_id, so reads
inside the evaluation scope must not rely on ORM visibility of private dives.
``evaluation_media_scope`` removes the request context ONLY around an
explicitly authorized block (not a global bypass): the caller must already
have validated the member and the active request before entering it, and no
Dive rows are mutated inside.
"""
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.models.dive import Dive
from app.models.evaluation import EvaluationRequest
from app.models.media import MediaCacheEntry, MediaJob
from app.models.photos_asset import PhotosAsset

REQUEST_TABLE = EvaluationRequest.__tablename__

# Same playback preference as the Library media transport; posters are never
# playback sources.
_PLAYABLE_PREFERENCE = {"original": 0, "proxy_720p": 1, "proxy_360p": 2}
_ACTIVE_JOB_STATUSES = ("queued", "waiting_for_mac")
PROMPT_MAX = 1000

# Documented cache limit for evaluation media responses (see module docstring).
MEDIA_CACHE_SECONDS = 300


def _existing_tables(db: Session) -> set[str]:
    try:
        return set(inspect(db.get_bind()).get_table_names())
    except Exception:
        return set()


_table_state: bool | None = None


def _tables_cached() -> bool:
    """Process-lifetime cache of the migration state.

    The check must NEVER run inside an open transaction: on StaticPool tests,
    ``inspect(bind)`` double-checks out the single shared connection and its
    release resets (rolls back) the session's pending work. One check per
    process is enough — the tables are static for its lifetime.
    """
    global _table_state
    return _table_state is True


def migration_pending(db: Session) -> bool:
    global _table_state
    if _table_state is None:
        _table_state = REQUEST_TABLE in _existing_tables(db)
    return not _table_state


def summary(row) -> Optional[dict]:
    """Owner-only summary shape (identical to the mutation response)."""
    if row is None:
        return None
    return {
        "id": row.id,
        "dive_id": row.dive_id,
        "active": bool(row.active),
        "prompt": row.prompt,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def request_for_dive(db: Session, dive_id: int) -> Optional[EvaluationRequest]:
    if migration_pending(db):
        return None
    return db.query(EvaluationRequest).filter(EvaluationRequest.dive_id == dive_id).first()


def request_map(db: Session, dive_ids) -> dict[int, dict]:
    """Batch evaluation summary for Library serialization (one query, no N+1)."""
    ids = {int(i) for i in dive_ids}
    if not ids or migration_pending(db):
        return {}
    rows = db.query(EvaluationRequest).filter(EvaluationRequest.dive_id.in_(ids)).all()
    return {row.dive_id: summary(row) for row in rows}


@contextmanager
def evaluation_media_scope(db: Session):
    """Temporarily lift the request-wide member filter for authorized work.

    The caller must have completed every authorization check (member, active
    request, request↔media correspondence) BEFORE entering this block; inside,
    reads behave like operator reads so private-dive media can be located.
    The context is always restored. Never mutate Dive rows inside.
    """
    from app.services.dive_access import CONTEXT_KEY

    context = db.info.get(CONTEXT_KEY)
    db.info.pop(CONTEXT_KEY, None)
    try:
        yield
    finally:
        if context is not None:
            db.info[CONTEXT_KEY] = context


def authorize_evaluation_media(db: Session, user, request_id: int) -> tuple[EvaluationRequest, Dive, PhotosAsset]:
    """Validate the whole evaluation-media chain or fail closed.

    Raises 404 uniformly for unknown/inactive requests, unknown media or a
    request that does not own its media: no existence disclosure.
    """
    if user is None or not user.is_active:
        raise HTTPException(404, "Not found")
    with evaluation_media_scope(db):
        request_row = db.get(EvaluationRequest, request_id)
        if request_row is None or not request_row.active:
            raise HTTPException(404, "Not found")
        dive = db.get(Dive, request_row.dive_id)
        if dive is None or not dive.video_uuid:
            raise HTTPException(404, "Not found")
        asset = db.query(PhotosAsset).filter(PhotosAsset.video_uuid == dive.video_uuid).first()
        if asset is None or asset.video_uuid != dive.video_uuid:
            raise HTTPException(404, "Not found")
        return request_row, dive, asset


def _ready_entries(db: Session, asset_id: int) -> list[MediaCacheEntry]:
    return (
        db.query(MediaCacheEntry)
        .filter(MediaCacheEntry.photos_asset_id == asset_id, MediaCacheEntry.status == "ready")
        .order_by(MediaCacheEntry.created_at.desc())
        .all()
    )


def _playable_entry(entries: list[MediaCacheEntry]) -> Optional[MediaCacheEntry]:
    playable = [entry for entry in entries if entry.rendition in _PLAYABLE_PREFERENCE]
    if not playable:
        return None
    return min(playable, key=lambda entry: _PLAYABLE_PREFERENCE[entry.rendition])


def _poster_entry(entries: list[MediaCacheEntry]) -> Optional[MediaCacheEntry]:
    for entry in entries:
        if entry.rendition == "poster":
            return entry
    return None


def _active_job(db: Session, asset_id: int) -> bool:
    return (
        db.query(MediaJob)
        .filter(
            MediaJob.photos_asset_id == asset_id,
            MediaJob.status.in_(_ACTIVE_JOB_STATUSES),
            MediaJob.attempts < MediaJob.max_attempts,
        )
        .first()
        is not None
    )


def backbone_originals(db, video_uuids):
    """Exact verified PROD authority for an already-authorized media scope."""
    from app.config import get_settings
    from app.models.media_backbone import MediaRevision
    from app.services.matchmaking import verified_original_clause
    from sqlalchemy import func
    settings = get_settings()
    if not (settings.user_auth_enabled and settings.b2_playback_canary_enabled) or not video_uuids:
        return {}
    return dict(db.query(MediaRevision.video_uuid, func.max(MediaRevision.id)).filter(
        MediaRevision.video_uuid.in_(video_uuids),
        MediaRevision.rendition_semantics != 'browser_original',
        verified_original_clause()).group_by(MediaRevision.video_uuid).all())


def media_status(
    db: Session,
    request_row: EvaluationRequest,
    asset: PhotosAsset,
    prefetched: tuple[list[MediaCacheEntry], bool] | None = None,
    backbone_available: bool | None = None,
) -> dict:
    """Stable media transport fields for ticket 3 (jury player).

    Callers that already probed media in a BATCH (jury queue payloads) pass
    `prefetched` = (ready entries for this asset, active-media-job flag): the
    derivation runs without per-item database round trips. The derivation is
    the single source of truth for both paths.
    """
    base = f"/api/v1/evaluations/requests/{request_row.id}/media"
    if prefetched is None:
        with evaluation_media_scope(db):
            entries = _ready_entries(db, asset.id)
            has_active = _active_job(db, asset.id)
    else:
        entries, has_active = prefetched
    if backbone_available is None:
        with evaluation_media_scope(db):
            backbone_available = bool(backbone_originals(db, [asset.video_uuid]).get(asset.video_uuid))
    playable = _playable_entry(entries)
    original = next((entry for entry in entries if entry.rendition == 'original'), None)
    full_quality = bool(original or backbone_available)
    preview = next((entry for rendition in ('proxy_720p', 'proxy_360p') for entry in entries if entry.rendition == rendition), None)
    poster = _poster_entry(entries)
    if playable is not None or full_quality:
        status_value = "ready"
    elif has_active:
        status_value = "preparing"
    else:
        status_value = "missing"
    return {
        "request_id": request_row.id,
        "dive_id": request_row.dive_id,
        "video_uuid": asset.video_uuid,
        "status": status_value,
        # Rendition actually resolved for playback (original→720p
        # →360p; the member can select another ready one via ?rendition=).
        "rendition": "original" if full_quality else playable.rendition if playable else None,
        "poster_url": f"{base}/poster" if poster else None,
        "playback_url": f"{base}/play" if playable or full_quality else None,
        "full_quality_url": f"{base}/play?rendition=original" if full_quality else None,
        "preview_url": f"{base}/play?rendition={preview.rendition}" if preview else None,
        "available_renditions": sorted({entry.rendition for entry in entries} | ({"original"} if full_quality else set())),
    }


def prepare_media(db: Session, dive: Dive, asset: PhotosAsset, reason: str = "evaluation_request") -> tuple[list[str], list[str]]:
    """Idempotently queue missing renditions through the existing pipeline.

    Best-effort and always called AFTER the caller's commit: a failure here is
    recoverable (retry/preparation endpoint) and must never roll back the
    toggle itself. At most the 720p proxy and the poster are requested — never
    a mass preparation. Returns (created, reused) rendition name lists: a retry
    answers created=[] and reuses the still-active jobs.
    """
    created: list[str] = []
    reused: list[str] = []
    with evaluation_media_scope(db):
        from app.services.media_jobs import create_or_reuse_media_job

        entries = _ready_entries(db, asset.id)
        good_playable = any(entry.rendition in ("proxy_720p", "original") for entry in entries)
        try:
            if not good_playable:
                _, _, was_created = create_or_reuse_media_job(db, asset=asset, rendition="proxy_720p", reason=reason)
                (created if was_created else reused).append("proxy_720p")
            if _poster_entry(entries) is None:
                _, _, was_created = create_or_reuse_media_job(db, asset=asset, rendition="poster", reason=reason)
                (created if was_created else reused).append("poster")
            db.commit()
        except Exception:
            db.rollback()
            raise
    return created, reused


def set_request(
    db: Session,
    dive: Dive,
    user_id: int,
    active: bool,
    prompt: Optional[str],
    prompt_set: bool,
) -> EvaluationRequest:
    """Create or update the single request of a dive (upsert by dive_id).

    ``prompt_set=False`` keeps the stored text (deactivation preserves the
    comment); an explicitly provided prompt — even empty — replaces it.
    """
    if migration_pending(db):
        raise HTTPException(503, "Evaluation migration pending")
    if active:
        if dive.diver_id is None:
            raise HTTPException(422, "Attribution required before requesting an evaluation")
        if not dive.video_uuid:
            raise HTTPException(422, "Video required before requesting an evaluation")
    if prompt_set and prompt is not None and len(prompt) > PROMPT_MAX:
        raise HTTPException(422, f"Prompt limited to {PROMPT_MAX} characters")
    row = db.query(EvaluationRequest).filter(EvaluationRequest.dive_id == dive.id).first()
    if row is None:
        row = EvaluationRequest(
            dive_id=dive.id,
            active=active,
            prompt=(prompt or "").strip() or None if prompt_set else None,
            created_by_user_id=user_id,
        )
        db.add(row)
        db.flush()
    else:
        row.active = active
        if prompt_set:
            row.prompt = (prompt or "").strip() or None
        db.add(row)
    return row


def serve_entry(path_value: str, content_type: Optional[str], request, head_only: bool):
    """Stream a verified cache file with range support (backend-side only)."""
    from app.api.v1.media import _serve_media_file

    response = _serve_media_file(
        Path(path_value),
        content_type or "application/octet-stream",
        request,
        head_only=head_only,
    )
    # Short, account-scoped browser caching; the server re-verifies eligibility
    # on every request (documented limit, see module docstring).
    response.headers["Cache-Control"] = f"private, max-age={MEDIA_CACHE_SECONDS}"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response
