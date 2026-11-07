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
    size: int = Field(default=5, ge=1, le=20, strict=True)


@router.post('/evaluations/automatic/stacks')
def create_stack(body: StackBody, request: Request, response: Response, db: Session = Depends(get_db)):
    _same_origin(request)
    user = _require_user(request, db)
    _secure_headers(response)
    key = 'daily:' + datetime.utcnow().date().isoformat() if body.daily else 'extra:' + str(body.client_session_id)
    row = service.stack(db, user, key, size=body.size)
    return {'session_id': row.id, 'created': True, 'expires_at': None}


@router.get('/evaluations/automatic/stacks/{stack_id}/queue')
def queue(stack_id: int, request: Request, response: Response, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    _secure_headers(response)
    return service.queue(db, user, stack_id)


@router.get('/evaluations/overview')
def overview(request: Request, response: Response, db: Session = Depends(get_db)):
    """One read for the Evaluations hub: today's selection, open requests, history size."""
    from sqlalchemy import func
    from app.models.evaluation import EvaluationRating
    from app.models.matchmaking import AutomaticRating
    from app.services import evaluation_queue
    user = _require_user(request, db)
    _secure_headers(response)
    judged_total = sum(db.query(func.count(model.id)).filter(model.evaluator_user_id == user.id).scalar()
        for model in (EvaluationRating, AutomaticRating))
    return {'today': service.today(db, user), 'requests_pending': evaluation_queue.pending_count(db, user),
        'judged_total': judged_total, 'judge': service.judge_profile(db, user)}


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
            MediaCacheEntry.status == 'ready', MediaCacheEntry.rendition == 'original').first()
        revision_id = service.original_revision_id(db, dive.video_uuid)
        if revision_id is not None and not cached_hq:
            return revision_id, user
    entry = _select_ready_entry(db, asset, rendition if kind == 'play' else None, playable=kind == 'play')
    return evaluation_access.serve_entry(entry, request, head_only=request.method == 'HEAD')


@router.api_route('/evaluations/automatic/{dive_id}/media/{kind}', methods=['GET', 'HEAD'])
def media(dive_id: int, kind: str, request: Request, rendition: str | None = None, db: Session = Depends(get_db)):
    # FastAPI runs this synchronous endpoint in its worker threadpool, including
    # the reused playback handler's synchronous ORM/grant operations.
    resolved = _resolve_media(dive_id, kind, request, rendition, db)
    if isinstance(resolved, tuple):
        from app.api.v1.media_playback import play_media_revision
        revision_id, user = resolved
        return play_media_revision(revision_id, request, Response(), db, user)
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
def mine(request: Request, response: Response, limit: int = Query(20, ge=1, le=50), offset: int = Query(0, ge=0),
         search: str = Query('', max_length=100), height: str = Query('', max_length=5),
         date_from: datetime | None = None,
         score_state: str = Query('all', pattern='^(all|scored|awaiting)$'),
         sort: str = Query('recent', pattern='^(recent|top|votes)$'), db: Session = Depends(get_db)):
    user = _require_user(request, db)
    _secure_headers(response)
    query = db.query(Dive).filter(Dive.diver_id.in_(owned_diver_ids(db, user.id)), Dive.visibility == 'public', Dive.video_uuid.isnot(None))
    from sqlalchemy import func, or_
    from app.models.matchmaking import AutomaticRating
    if search.strip():
        term = '%' + search.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        query = query.filter(or_(Dive.dive_code.ilike(term, escape='\\'), Dive.notes.ilike(term, escape='\\')))
    if height:
        query = query.filter(Dive.height == height)
    if date_from:
        query = query.filter(Dive.dive_datetime >= date_from)
    totals = db.query(AutomaticRating.dive_id.label('dive_id'), func.count(AutomaticRating.id).label('count'),
        func.avg(AutomaticRating.score_half_steps).label('mean')).filter(
            AutomaticRating.dive_id.in_(query.with_entities(Dive.id)), service.community_vote_clause()
        ).group_by(AutomaticRating.dive_id).subquery()
    query = query.outerjoin(totals, totals.c.dive_id == Dive.id)
    if score_state == 'scored':
        query = query.filter(totals.c.count > 0)
    elif score_state == 'awaiting':
        query = query.filter(totals.c.count.is_(None))
    total = query.count()
    order = [Dive.dive_datetime.desc(), Dive.id.desc()]
    if sort == 'top':
        order = [func.coalesce(totals.c.mean, -1).desc(), *order]
    elif sort == 'votes':
        order = [func.coalesce(totals.c.count, 0).desc(), *order]
    rows = query.outerjoin(ReviewExclusion, ReviewExclusion.dive_id == Dive.id).add_columns(
        ReviewExclusion.excluded, totals.c.count, totals.c.mean).order_by(*order).offset(offset).limit(limit).all()
    from app.api.v1.dives import _library_visuals
    visuals = _library_visuals(db, [dive.video_uuid for dive, *_ in rows])
    items = [{'dive_id': dive.id, 'dive_code': dive.dive_code, 'height': dive.height, 'dive_datetime': dive.dive_datetime.isoformat(), 'video_uuid': dive.video_uuid, 'excluded': bool(excluded),
        'rating_count': count or 0, 'mean_score': round(mean / 2, 1) if count else None, 'provisional': True,
        **visuals.get(dive.video_uuid, {})}
        for dive, excluded, count, mean in rows]
    return {'items': items, 'total': total, 'limit': limit, 'offset': offset, 'filter_version': 1}


@router.get('/evaluations/automatic/{dive_id}/results')
def results(dive_id: int, request: Request, response: Response,
            limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
            db: Session = Depends(get_db)):
    """A bounded score page for the owner or a member with a confirmed vote.

    Results grant no media access; a selection alone never reveals peer votes.
    """
    from app.models.matchmaking import AutomaticRating
    user = _require_user(request, db)
    dive = db.get(Dive, dive_id)
    if dive is None:
        raise HTTPException(404, 'Not found')
    voted = db.query(AutomaticRating.id).filter_by(dive_id=dive_id, evaluator_user_id=user.id).first()
    if dive.diver_id not in owned_diver_ids(db, user.id) and voted is None:
        raise HTTPException(404, 'Not found')
    _secure_headers(response)
    return service.results(db, user, dive_id, limit=limit, offset=offset)


@router.get('/dives/{dive_id}/evaluation')
def dive_evaluation(dive_id: int, request: Request, response: Response, db: Session = Depends(get_db)):
    """Player tab: which circuit takes this member's vote, and its results once allowed."""
    from app.services import dive_evaluation as player
    user = _require_user(request, db)
    _secure_headers(response)
    return player.context(db, user, player.visible_dive(db, dive_id))


@router.post('/dives/{dive_id}/evaluation/ratings')
def rate_dive(dive_id: int, body: RatingInput, request: Request, response: Response, db: Session = Depends(get_db)):
    """Player vote: the active request first, otherwise the public community circuit."""
    from app.services import dive_evaluation as player
    from app.services import achievements
    _same_origin(request)
    user = _require_user(request, db)
    out = player.rate(db, user, player.visible_dive(db, dive_id), body.score_half_steps, (body.comment or '').strip() or None)
    if out['circuit'] == 'request':
        achievements.award(db, user.id, achievements.RATING)
    _secure_headers(response)
    return out
