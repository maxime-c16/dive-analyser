"""Authenticated automatic jury and experimental per-dive community scores."""
from datetime import datetime
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.database import get_db
from app.api.v1.evaluations import _require_user, _same_origin, _secure_headers, _select_ready_entry, RatingInput
from app.models.dive import Dive
from app.models.matchmaking import ReviewExclusion, ReviewStack, ReviewStackItem
from app.services import matchmaking as service, evaluation_access
from app.services.dive_access import owned_diver_ids, require_dive_owner

def require_schema(request: Request, db: Session = Depends(get_db)):
    _require_user(request, db)
    from sqlalchemy import inspect
    tables = set(inspect(db.connection()).get_table_names())
    if not {'review_exclusions', 'review_stacks', 'review_stack_items', 'automatic_ratings'} <= tables:
        raise HTTPException(503, 'AUTOMATIC_REVIEW_MIGRATION_PENDING')


router = APIRouter(dependencies=[Depends(require_schema)])


class StackBody(BaseModel):
    client_session_id: UUID
    daily: bool = True


@router.post('/evaluations/automatic/stacks')
def create_stack(body: StackBody, request: Request, response: Response, db: Session = Depends(get_db)):
    _same_origin(request)
    user = _require_user(request, db)
    _secure_headers(response)
    key = 'daily:' + datetime.utcnow().date().isoformat() if body.daily else 'extra:' + str(body.client_session_id)
    row = service.stack(db, user, key)
    return {'session_id': row.id, 'created': True, 'expires_at': None}


@router.get('/evaluations/automatic/stacks/{stack_id}/queue')
def queue(stack_id: int, request: Request, response: Response, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    _secure_headers(response)
    return service.queue(db, user, stack_id)


class SkipBody(BaseModel):
    request_id: int


@router.post('/evaluations/automatic/stacks/{stack_id}/skip')
def skip(stack_id: int, body: SkipBody, request: Request, db: Session = Depends(get_db)):
    _same_origin(request)
    user = _require_user(request, db)
    item = db.query(ReviewStackItem).join(ReviewStack).filter(ReviewStack.id == stack_id,
        ReviewStack.user_id == user.id, ReviewStackItem.dive_id == body.request_id).first()
    if item is None:
        raise HTTPException(404, 'Not found')
    if item.skipped_at is None:
        item.skipped_at = datetime.utcnow()
        db.commit()
    return {'skipped': True}


class AutomaticRatingBody(RatingInput):
    video_uuid: str = Field(..., min_length=1, max_length=100)


@router.post('/evaluations/automatic/{dive_id}/ratings')
def rate(dive_id: int, body: AutomaticRatingBody, request: Request, response: Response, db: Session = Depends(get_db)):
    _same_origin(request)
    user = _require_user(request, db)
    _secure_headers(response)
    return service.rate(db, user, dive_id, body.score_half_steps, (body.comment or '').strip() or None, body.video_uuid)


@router.get('/evaluations/automatic/{dive_id}/media/status')
def media_status(dive_id: int, request: Request, response: Response, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    _secure_headers(response)
    dive, asset = service.authorize(db, user, dive_id)
    return service.status(db, dive, asset)


def _resolve_media(dive_id, kind, request, rendition, db):
    user = _require_user(request, db)
    if kind not in ('play', 'poster'):
        raise HTTPException(404, 'Not found')
    dive, asset = service.authorize(db, user, dive_id)
    if kind == 'play' and (rendition == 'original' or rendition is None):
        from app.models.media import MediaCacheEntry
        cached_hq = db.query(MediaCacheEntry.id).filter(MediaCacheEntry.photos_asset_id == asset.id,
            MediaCacheEntry.status == 'ready', MediaCacheEntry.rendition == ('original' if rendition else 'proxy_720p')).first()
        revision_id = service.original_revision_id(db, dive.video_uuid)
        if revision_id is not None and not cached_hq:
            return revision_id, user
    entry = _select_ready_entry(db, asset, rendition if kind == 'play' else None, playable=kind == 'play')
    return evaluation_access.serve_entry(entry.storage_path, entry.content_type, request, head_only=request.method == 'HEAD')


@router.api_route('/evaluations/automatic/{dive_id}/media/{kind}', methods=['GET', 'HEAD'])
async def media(dive_id: int, kind: str, request: Request, rendition: str | None = None, db: Session = Depends(get_db)):
    from starlette.concurrency import run_in_threadpool
    resolved = await run_in_threadpool(_resolve_media, dive_id, kind, request, rendition, db)
    if isinstance(resolved, tuple):
        from app.api.v1.media_playback import play_media_revision
        revision_id, user = resolved
        return await play_media_revision(revision_id, request, Response(), db, user)
    return resolved


@router.post('/evaluations/automatic/{dive_id}/media/prepare')
def prepare(dive_id: int, request: Request, response: Response, db: Session = Depends(get_db)):
    _same_origin(request)
    user = _require_user(request, db)
    _secure_headers(response)
    dive, asset = service.authorize(db, user, dive_id)
    created, reused = evaluation_access.prepare_media(db, dive, asset, reason='automatic_review')
    return {**service.status(db, dive, asset), 'created_jobs': created, 'reused_jobs': reused}


class ExclusionBody(BaseModel):
    excluded: bool


@router.put('/dives/{dive_id}/automatic-review')
def exclusion(dive_id: int, body: ExclusionBody, request: Request, db: Session = Depends(get_db)):
    _same_origin(request)
    user = _require_user(request, db)
    dive = db.query(Dive).filter_by(id=dive_id).with_for_update().first()
    if dive is None:
        raise HTTPException(404, 'Not found')
    require_dive_owner(db, user, dive)
    row = db.get(ReviewExclusion, dive_id)
    if row is None:
        db.add(ReviewExclusion(dive_id=dive_id, excluded=body.excluded))
    else:
        row.excluded = body.excluded
    db.commit()
    return {'excluded': body.excluded}


@router.get('/evaluations/automatic/mine')
def mine(request: Request, response: Response, limit: int = Query(20, ge=1, le=50), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    user = _require_user(request, db)
    _secure_headers(response)
    query = db.query(Dive).filter(Dive.diver_id.in_(owned_diver_ids(db, user.id)), Dive.visibility == 'public', Dive.video_uuid.isnot(None))
    from sqlalchemy import func
    from app.models.matchmaking import AutomaticRating
    totals = db.query(AutomaticRating.dive_id.label('dive_id'), func.count(AutomaticRating.id).label('count'),
        func.avg(AutomaticRating.score_half_steps).label('mean')).filter(service.community_vote_clause()).group_by(AutomaticRating.dive_id).subquery()
    rows = query.outerjoin(ReviewExclusion, ReviewExclusion.dive_id == Dive.id).outerjoin(totals, totals.c.dive_id == Dive.id).add_columns(
        ReviewExclusion.excluded, totals.c.count, totals.c.mean).order_by(Dive.dive_datetime.desc(), Dive.id).offset(offset).limit(limit).all()
    items = [{'dive_id': dive.id, 'dive_code': dive.dive_code, 'height': dive.height, 'excluded': bool(excluded),
        'rating_count': count or 0, 'mean_score': round(mean / 2, 1) if count else None, 'provisional': True}
        for dive, excluded, count, mean in rows]
    return {'items': items, 'total': query.count(), 'limit': limit, 'offset': offset}
