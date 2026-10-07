"""Small-pool matchmaking. Public-only, fair by owner, retry-stable stacks.

UTC daily boundary; skips cool down 7 days. One automatic vote per account
and dive, independent of manual requests. No reservation across reviewers.
"""
from datetime import datetime, timedelta
from types import SimpleNamespace
from fastapi import HTTPException
from sqlalchemy import exists, func, select
from sqlalchemy.exc import IntegrityError
from app.models.dive import Dive
from app.models.diver import Diver
from app.models.photos_asset import PhotosAsset
from app.models.user_auth import AppUser, UserDiverAccess
from app.models.matchmaking import AutomaticRating, ReviewExclusion, ReviewStack, ReviewStackItem
from app.services import evaluation_access
from app.services.dive_access import owned_diver_ids


def community_vote_clause():
    """Current ownership applies even to votes cast before account binding."""
    return ~exists(select(1).select_from(UserDiverAccess).join(Dive, Dive.diver_id == UserDiverAccess.diver_id).where(
        Dive.id == AutomaticRating.dive_id, UserDiverAccess.access_kind == 'OWNER',
        UserDiverAccess.user_id == AutomaticRating.evaluator_user_id).correlate(AutomaticRating))


def eligible(db, user):
    active_owner = exists(select(1).select_from(UserDiverAccess).join(AppUser, AppUser.id == UserDiverAccess.user_id).where(
        UserDiverAccess.diver_id == Dive.diver_id, UserDiverAccess.access_kind == 'OWNER', AppUser.is_active.is_(True)))
    bound_owner = exists(select(1).where(UserDiverAccess.diver_id == Dive.diver_id, UserDiverAccess.access_kind == 'OWNER'))
    excluded = exists(select(1).where(ReviewExclusion.dive_id == Dive.id, ReviewExclusion.excluded.is_(True)))
    return db.query(Dive).filter(Dive.visibility == 'public', Dive.diver_id.isnot(None), Dive.video_uuid.isnot(None),
        ~Dive.diver_id.in_(owned_diver_ids(db, user.id)), (active_owner | ~bound_owner), ~excluded)


def authorize(db, user, dive_id, lock=False):
    if lock:
        # Lock first, then check mutable exclusions with a fresh statement.
        db.query(Dive).filter(Dive.id == dive_id).with_for_update().first()
    dive = eligible(db, user).filter(Dive.id == dive_id).populate_existing().first()
    if dive is None:
        raise HTTPException(404, 'Not found')
    asset = db.query(PhotosAsset).filter(PhotosAsset.video_uuid == dive.video_uuid).first()
    if asset is None:
        raise HTTPException(404, 'Not found')
    return dive, asset


def status(db, dive, asset):
    result = evaluation_access.media_status(db, SimpleNamespace(id=dive.id, dive_id=dive.id), asset)
    from app.api.v1.media import _backbone_playback_url
    if result.get('rendition') not in ('proxy_720p', 'original') and _backbone_playback_url(db, dive.video_uuid):
        result.update(status='ready', rendition='original', playback_url='available')
        result['available_renditions'] = list(dict.fromkeys([*result['available_renditions'], 'original']))
    base = f'/api/v1/evaluations/automatic/{dive.id}/media'
    result['poster_url'] = base + '/poster' if result['poster_url'] else None
    result['playback_url'] = base + '/play' if result['playback_url'] else None
    return result


def stack(db, user, key):
    row = db.query(ReviewStack).filter_by(user_id=user.id, key=key).first()
    if row is not None:
        return row
    # Serialize allocation for this account in PostgreSQL, including concurrent
    # on-demand and daily requests. SQLite tests rely on the unique key below.
    if db.bind.dialect.name == 'postgresql':
        from sqlalchemy import text
        db.execute(text('SELECT pg_advisory_xact_lock(73124, :uid)'), {'uid': user.id})
        row = db.query(ReviewStack).filter_by(user_id=user.id, key=key).first()
        if row is not None:
            db.commit()
            return row
    voted = exists(select(1).where(AutomaticRating.dive_id == Dive.id, AutomaticRating.evaluator_user_id == user.id))
    cooling = exists(select(1).select_from(ReviewStackItem).join(ReviewStack).where(
        ReviewStackItem.dive_id == Dive.id, ReviewStack.user_id == user.id,
        ReviewStackItem.skipped_at > datetime.utcnow() - timedelta(days=7)))
    outstanding = exists(select(1).select_from(ReviewStackItem).join(ReviewStack).where(
        ReviewStackItem.dive_id == Dive.id, ReviewStack.user_id == user.id,
        ReviewStack.created_at > datetime.utcnow() - timedelta(hours=24), ReviewStackItem.skipped_at.is_(None)))
    count = select(func.count(AutomaticRating.id)).where(AutomaticRating.dive_id == Dive.id, community_vote_clause()).correlate(Dive).scalar_subquery()
    candidates = eligible(db, user).filter(~voted, ~cooling, ~outstanding).order_by(count, Dive.dive_datetime.desc(), Dive.id)
    # Ready cache is filtered in SQL, so unavailable videos cannot hide the
    # playable corpus. Round-robin owners before taking a second dive each.
    from app.models.media import MediaCacheEntry
    ready = exists(select(1).select_from(PhotosAsset).join(MediaCacheEntry, MediaCacheEntry.photos_asset_id == PhotosAsset.id).where(
        PhotosAsset.video_uuid == Dive.video_uuid, MediaCacheEntry.status == 'ready',
        MediaCacheEntry.rendition.in_(('proxy_720p', 'original', 'proxy_360p'))))
    from app.config import get_settings
    settings = get_settings()
    if settings.user_auth_enabled and settings.b2_playback_canary_enabled:
        from app.models.media_backbone import MediaRevision, MediaBlobLocation
        backbone_ready = exists(select(1).select_from(MediaRevision).join(MediaBlobLocation,
            MediaBlobLocation.blob_sha256 == MediaRevision.blob_sha256).where(
            MediaRevision.video_uuid == Dive.video_uuid, MediaBlobLocation.environment == 'prod',
            MediaBlobLocation.verified.is_(True)))
        ready = ready | backbone_ready
    owner = select(func.min(UserDiverAccess.user_id)).select_from(UserDiverAccess).join(AppUser).where(
        UserDiverAccess.diver_id == Dive.diver_id, UserDiverAccess.access_kind == 'OWNER', AppUser.is_active.is_(True)
    ).correlate(Dive).scalar_subquery()
    rank = func.row_number().over(partition_by=func.coalesce(owner, -Dive.diver_id), order_by=(count, Dive.dive_datetime.desc(), Dive.id))
    ranked = candidates.filter(ready).order_by(None).add_columns(rank.label('owner_rank'), count.label('votes')).subquery()
    ids = db.query(ranked.c.id).order_by(ranked.c.owner_rank, ranked.c.votes, ranked.c.dive_datetime.desc(), ranked.c.id).limit(3).all()
    chosen = [dive_id for (dive_id,) in ids]
    row = ReviewStack(user_id=user.id, key=key)
    db.add(row)
    try:
        db.flush()
        for position, dive_id in enumerate(chosen):
            db.add(ReviewStackItem(stack_id=row.id, dive_id=dive_id, position=position, video_uuid=db.get(Dive, dive_id).video_uuid))
        db.commit()
    except IntegrityError:
        db.rollback()
        row = db.query(ReviewStack).filter_by(user_id=user.id, key=key).one()
    # A bounded POST-side warm-up: never schedule jobs from queue/media GETs.
    # Unready candidates are not assigned until a later selection can play them.
    import logging
    for dive in candidates.filter(~ready).limit(3).all():
        asset = db.query(PhotosAsset).filter_by(video_uuid=dive.video_uuid).first()
        if asset:
            try:
                evaluation_access.prepare_media(db, dive, asset, reason='automatic_review')
            except Exception:
                db.rollback()
                logging.getLogger(__name__).exception('Automatic review preparation failed for dive %s', dive.id)
    return row


def queue(db, user, stack_id):
    row = db.query(ReviewStack).filter_by(id=stack_id, user_id=user.id).first()
    if row is None:
        raise HTTPException(404, 'Not found')
    items = []
    for item in db.query(ReviewStackItem).filter_by(stack_id=row.id).order_by(ReviewStackItem.position):
        if item.skipped_at or db.query(AutomaticRating.id).filter_by(dive_id=item.dive_id, evaluator_user_id=user.id).first():
            continue
        try:
            dive, asset = authorize(db, user, item.dive_id)
        except HTTPException:
            continue
        if dive.video_uuid != item.video_uuid:
            continue
        media = status(db, dive, asset)
        if media['status'] != 'ready':
            continue
        name = db.query(Diver.display_name).filter_by(id=dive.diver_id).scalar()
        items.append({'request_id': dive.id, 'dive_id': dive.id, 'prompt': None,
            'dive': {'id': dive.id, 'video_uuid': dive.video_uuid, 'dive_code': dive.dive_code,
                'height': dive.height, 'platform_type': dive.platform_type, 'owner_display_name': name}, 'media': media})
    return {'batch_id': str(row.id), 'items': items, 'has_more': False}


def results(db, user, dive_id):
    rows = db.query(AutomaticRating).filter_by(dive_id=dive_id).filter(community_vote_clause()).order_by(AutomaticRating.id.desc()).limit(50).all()
    count, avg = db.query(func.count(AutomaticRating.id), func.avg(AutomaticRating.score_half_steps)).filter_by(dive_id=dive_id).filter(community_vote_clause()).one()
    mine = next((r for r in rows if r.evaluator_user_id == user.id), None)
    if mine is None:
        mine = db.query(AutomaticRating).filter_by(dive_id=dive_id, evaluator_user_id=user.id).first()
    names = dict(db.query(AppUser.id, AppUser.display_name).filter(AppUser.id.in_({r.evaluator_user_id for r in rows})).all())
    def payload(r):
        return {'id': r.id, 'request_id': dive_id, 'evaluator_user_id': r.evaluator_user_id,
            'score_half_steps': r.score_half_steps, 'comment': r.comment, 'created_at': r.created_at, 'author': names.get(r.evaluator_user_id)}
    return {'request_id': dive_id, 'rating_count': count, 'mean_score': round(avg / 2, 1) if count else None,
        'provisional': True, 'ratings': [payload(r) for r in rows], 'my_rating': payload(mine) if mine else None}


def rate(db, user, dive_id, score, comment, video_uuid):
    dive, asset = authorize(db, user, dive_id, lock=True)
    if dive.video_uuid != video_uuid:
        raise HTTPException(409, {'code': 'EVALUATION_CLOSED', 'message': 'Video changed; reload the selection'})
    old = db.query(AutomaticRating).filter_by(dive_id=dive_id, evaluator_user_id=user.id).first()
    if old:
        if old.score_half_steps != score or old.comment != comment:
            raise HTTPException(409, {'code': 'RATING_ALREADY_SUBMITTED', 'message': 'Vote is immutable'})
    else:
        assigned = db.query(ReviewStackItem).join(ReviewStack).filter(
            ReviewStack.user_id == user.id, ReviewStackItem.dive_id == dive_id, ReviewStackItem.video_uuid == video_uuid, ReviewStackItem.skipped_at.is_(None)).first()
        if not assigned or status(db, dive, asset)['status'] != 'ready':
            raise HTTPException(404, 'Not found')
        name = db.query(Diver.display_name).filter_by(id=dive.diver_id).scalar() or ''
        db.add(AutomaticRating(dive_id=dive_id, evaluator_user_id=user.id, score_half_steps=score, comment=comment,
            dive_code=dive.dive_code, height=dive.height, platform_type=dive.platform_type, dive_name=name, video_uuid=dive.video_uuid))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            winner = db.query(AutomaticRating).filter_by(dive_id=dive_id, evaluator_user_id=user.id).first()
            if winner is None:
                raise
            return rate(db, user, dive_id, score, comment, video_uuid)
    panel = results(db, user, dive_id)
    return {'rating': panel['my_rating'], 'results': panel}
