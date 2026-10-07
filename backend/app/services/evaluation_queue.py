"""Jury sessions and the evaluation queue (issue #67).

A session is server-side bookkeeping for one account, never a permission:
eligibility (active request + ready media + current-owner attribution +
evaluation scope) and the absence of an existing vote are re-verified at
every read and inside the rating transaction. Queue reads atomically mark
proposals (unique session_id/request_id) under a client-stable batch_id so a
retry returns the same items instead of losing the batch. Nothing here
reserves a video — several members judge simultaneously — and nothing here
prepares media from a GET.
"""
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import and_, exists, func, not_, select
from sqlalchemy.orm import Session

from app.models.dive import Dive
from app.models.diver import Diver
from app.models.evaluation import (
    EvaluationRating,
    EvaluationRequest,
    EvaluationSession,
    EvaluationSessionRequest,
)
from app.models.media import MediaCacheEntry
from app.models.photos_asset import PhotosAsset
from app.services import evaluation_access
from app.services.dive_access import owned_diver_ids

SESSION_TTL_HOURS = 24
CANDIDATE_PAGE = 100

# Playable cache renditions, same preference as the media transport; a verified
# backbone revision also counts as ready (bytes play through /revisions/…).
_PLAYABLE_RENDITIONS = ("proxy_720p", "original", "proxy_360p")


def _now() -> datetime:
    return datetime.utcnow()


def create_session(db: Session, user_id: int, client_session_id: str) -> tuple[EvaluationSession, bool]:
    """Idempotent for ONE client_session_id (a retried POST returns the same
    live session). A fresh client id always places a NEW session on return:
    previous per-session skips are gone, stored votes stay excluded. Returns
    an expired-but-unexpired-window session untouched (410 collapses the call)."""
    by_client = (
        db.query(EvaluationSession)
        .filter(
            EvaluationSession.user_id == user_id,
            EvaluationSession.client_session_id == client_session_id,
        )
        .order_by(EvaluationSession.id.desc())
        .first()
    )
    if by_client is not None:
        if by_client.revoked_at is None and by_client.expires_at > _now():
            return by_client, False
        raise HTTPException(410, "SESSION_EXPIRED")
    row = EvaluationSession(
        user_id=user_id,
        client_session_id=client_session_id,
        expires_at=_now() + timedelta(hours=SESSION_TTL_HOURS),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, True


def get_own_session(db: Session, user, session_id: int) -> EvaluationSession:
    """Session of THIS account or uniform 404; an expired session is 410."""
    row = db.query(EvaluationSession).filter(EvaluationSession.id == session_id).first()
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "Not found")
    if row.revoked_at is not None or row.expires_at <= _now():
        raise HTTPException(410, "SESSION_EXPIRED")
    return row


def _votes_count_subquery():
    return (
        select(func.count(EvaluationRating.id))
        .where(EvaluationRating.request_id == EvaluationRequest.id)
        .correlate(EvaluationRequest)
        .scalar_subquery()
    )


def _eligible_query(db: Session, user, db_query_mode: str = "all"):
    """Eligible-request core (inside the lifted evaluation scope).

    Filters: active request, attributed dive with a video identity, not one of
    the account's own dives, no existing vote. Deterministic order: fewest
    votes, then oldest, then id. Media readiness is filtered by the caller in
    one batched SQL probe — never prepared from here.
    """
    my_diver_ids = set(owned_diver_ids(db, user.id))
    has_my_vote = exists(
        select(1).where(
            EvaluationRating.request_id == EvaluationRequest.id,
            EvaluationRating.evaluator_user_id == user.id,
        )
    )
    filters = [
        EvaluationRequest.active.is_(True),
        Dive.diver_id.isnot(None),
        Dive.video_uuid.isnot(None),
        not_(has_my_vote),
    ]
    if my_diver_ids:
        filters.append(not_(Dive.diver_id.in_(my_diver_ids)))
    return (
        db.query(EvaluationRequest, Dive)
        .join(Dive, Dive.id == EvaluationRequest.dive_id)
        .filter(and_(*filters))
        .order_by(_votes_count_subquery().asc(), EvaluationRequest.created_at.asc(), EvaluationRequest.id.asc())
    )


def _ready_video_uuids(db: Session, pairs: list[tuple[EvaluationRequest, Dive]]) -> set[str]:
    """Batch media-readiness probe (one SQL pass for a whole page).

    Readiness is limited to media the evaluation transport can actually serve:
    a PhotosAsset cache entry with a READY playable rendition. A bare
    MediaRevision row proves bytes exist somewhere in the backbone — not that
    the evaluation scope (poster/play/prepare under /evaluations/requests/…)
    can serve them — so a revision-only dive is NOT queue-ready (review-bot
    High finding: it would have entered the queue without playable media and
    crashed _item_payload on its absent asset).
    """
    uuids = [dive.video_uuid for _, dive in pairs if dive.video_uuid]
    if not uuids:
        return set()
    cached = (
        db.query(PhotosAsset.video_uuid)
        .join(MediaCacheEntry, MediaCacheEntry.photos_asset_id == PhotosAsset.id)
        .filter(
            PhotosAsset.video_uuid.in_(uuids),
            MediaCacheEntry.status == "ready",
            MediaCacheEntry.rendition.in_(_PLAYABLE_RENDITIONS),
        )
        .distinct()
        .all()
    )
    return {row[0] for row in cached}


def _owner_display_name(db: Session, diver_id: int | None) -> str | None:
    if diver_id is None:
        return None
    return db.query(Diver.display_name).filter(Diver.id == diver_id).scalar()


def _item_payload(db: Session, request_row: EvaluationRequest, dive: Dive) -> dict:
    asset = db.query(PhotosAsset).filter(PhotosAsset.video_uuid == dive.video_uuid).first()
    if asset is None:
        # Out of transport scope (no servable cache entry): readable missing
        # state instead of a crash — the item is ineligible for playback.
        media = {"status": "missing", "poster_url": None, "playback_url": None}
    else:
        media = evaluation_access.media_status(db, request_row, asset)
    return {
        "request_id": request_row.id,
        "dive_id": dive.id,
        "prompt": request_row.prompt,
        "dive": {
            "id": dive.id,
            "video_uuid": dive.video_uuid,
            "dive_code": dive.dive_code,
            "height": dive.height,
            "platform_type": dive.platform_type,
            "owner_display_name": _owner_display_name(db, dive.diver_id),
        },
        "media": {
            "status": media["status"],
            "poster_url": media["poster_url"],
            "playback_url": media["playback_url"],
        },
    }


def _retry_item(db: Session, user, request_id: int) -> dict:
    """Re-verify a previously proposed request for a batch retry.

    Closed/deleted/context-lost requests come back flagged unavailable without
    any media URL; a request voted between loads flags unavailable too (its
    results remain reachable through the dedicated results endpoint)."""
    request_row = db.get(EvaluationRequest, request_id)
    dive = db.get(Dive, request_row.dive_id) if request_row else None
    my_ids = set(owned_diver_ids(db, user.id))
    still_eligible = bool(
        request_row is not None
        and request_row.active
        and dive is not None
        and dive.diver_id is not None
        and dive.video_uuid is not None
        and dive.diver_id not in my_ids
        and not bool(
            db.query(EvaluationRating)
            .filter(
                EvaluationRating.request_id == request_row.id,
                EvaluationRating.evaluator_user_id == user.id,
            )
            .first()
        )
    )
    if not still_eligible:
        return {"request_id": request_id, "dive_id": request_row.dive_id if request_row else None, "unavailable": True}
    item = _item_payload(db, request_row, dive)
    item["unavailable"] = False
    return item


def _has_more(db: Session, user, session: EvaluationSession) -> bool:
    """Bounded probe for remaining eligible requests (indicative only)."""
    marks = select(EvaluationSessionRequest.request_id).where(
        EvaluationSessionRequest.session_id == session.id
    )
    query = _eligible_query(db, user).filter(
        ~EvaluationRequest.id.in_(marks)
    )
    first_pair = query.first()
    return bool(
        first_pair and first_pair[0].id in _ready_video_uuids(db, [first_pair])
    )


def queue_payload(db: Session, user, session: EvaluationSession, limit: int, raw_batch_id: str) -> dict:
    """Atomic batch allocation under the client's stable batch id.

    Unknown batch id ⇒ items are allocated INTO it right away (request-side
    idempotency: first read and its retries are the same call). Known batch id
    ⇒ same items, re-verified, with `unavailable` marking for closed/removed
    requests and after-the-fact votes.
    """
    from uuid import UUID

    try:
        batch_id = str(UUID(raw_batch_id))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(422, "Invalid batch identity")
    with evaluation_access.evaluation_media_scope(db):
        existing = (
            db.query(EvaluationSessionRequest)
            .filter(
                EvaluationSessionRequest.session_id == session.id,
                EvaluationSessionRequest.batch_id == batch_id,
            )
            .order_by(EvaluationSessionRequest.id.asc())
            .all()
        )
        if existing:
            return {
                "batch_id": batch_id,
                "items": [_retry_item(db, user, row.request_id) for row in existing],
                "has_more": _has_more(db, user, session),
            }

        marked_in_session = select(EvaluationSessionRequest.request_id).where(
            EvaluationSessionRequest.session_id == session.id
        )
        base_query = _eligible_query(db, user).filter(~EvaluationRequest.id.in_(marked_in_session))
        items: list[dict] = []
        items_pairs: list[tuple[EvaluationRequest, Dive]] = []
        has_more = False
        offset = 0
        while len(items_pairs) <= limit:
            candidates = base_query.offset(offset).limit(CANDIDATE_PAGE).all()
            if not candidates:
                break
            offset += len(candidates)
            ready_uuids = _ready_video_uuids(db, candidates)
            for request_row, dive in candidates:
                if not ready_uuids or dive.video_uuid not in ready_uuids:
                    continue
                if len(items_pairs) == limit:
                    has_more = True  # probe value: an eligible-ready request remains
                    break
                items_pairs.append((request_row, dive))
            if has_more:
                break
        # Atomic marking: unique (session_id, request_id) — a conflicting
        # insert keeps the request in its earlier batch of this session, so no
        # reader duplicates a proposal.
        for request_row, dive in items_pairs:
            try:
                db.add(
                    EvaluationSessionRequest(
                        session_id=session.id, request_id=request_row.id, batch_id=batch_id, state="proposed",
                    )
                )
                db.commit()
                items.append(_item_payload(db, request_row, dive))
            except Exception:
                db.rollback()
        if len(items) < limit and not has_more:
            has_more = _has_more(db, user, session)
        return {"batch_id": batch_id, "items": items, "has_more": bool(has_more)}


def mark_skipped(db: Session, user, session: EvaluationSession, request_id: int) -> dict:
    """Idempotent pass; exclusion lives only inside this session."""
    row = (
        db.query(EvaluationSessionRequest)
        .filter(
            EvaluationSessionRequest.session_id == session.id,
            EvaluationSessionRequest.request_id == request_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(404, "Not found")
    if row.state != "skipped":
        row.state = "skipped"
        db.commit()
    return {"request_id": request_id, "state": "skipped"}
