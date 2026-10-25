"""Small-pool matchmaking. Public-only, fair by owner, retry-stable stacks.

UTC daily boundary; skips cool down 7 days. One vote per account and dive
across both circuits: a request-circuit vote blocks an automatic vote and
vice versa (each circuit still stores its own rows). No reservation across
reviewers.

While a member's judging style is still hidden, their stacks lead with dives
the panel already scored so early votes meet a comparison fast.
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


# Community votes the style meter compares before revealing (frontend JudgeMeter).
STYLE_REVEALED_AT = 3


def compared_votes(db, user, sample=50):
    """Votes in the member's recent window that other members also scored.

    Mirrors judge_profile()'s sample so the warm-up ordering in stack() ends
    exactly when the judging-style meter reveals.
    """
    mine = db.query(AutomaticRating.dive_id).filter(
        AutomaticRating.evaluator_user_id == user.id).order_by(AutomaticRating.id.desc()).limit(sample).subquery()
    others = db.query(AutomaticRating.dive_id).filter(
        AutomaticRating.evaluator_user_id != user.id, community_vote_clause(),
        AutomaticRating.dive_id.in_(select(mine.c.dive_id))).subquery()
    return db.query(func.count()).select_from(AutomaticRating).filter(
        AutomaticRating.evaluator_user_id == user.id,
        AutomaticRating.dive_id.in_(select(others.c.dive_id))).scalar()


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


def verified_original_clause():
    """Match the original playback route's fail-closed storage contract."""
    from app.config import get_settings
    from app.models.media_backbone import MediaRevision, MediaBlobLocation
    locations = select(func.count(MediaBlobLocation.id)).where(
        MediaBlobLocation.blob_sha256 == MediaRevision.blob_sha256,
        MediaBlobLocation.environment == 'prod', MediaBlobLocation.verified.is_(True)
    ).correlate(MediaRevision).scalar_subquery()
    valid = exists(select(1).where(
        MediaBlobLocation.blob_sha256 == MediaRevision.blob_sha256,
        MediaBlobLocation.environment == 'prod', MediaBlobLocation.verified.is_(True),
        MediaBlobLocation.storage_backend == 'b2',
        MediaBlobLocation.bucket == get_settings().media_backbone_prod_bucket,
        MediaBlobLocation.object_key != ''
    ).correlate(MediaRevision))
    return (locations == 1) & valid


def original_revision_id(db, video_uuid):
    from app.config import get_settings
    from app.models.media_backbone import MediaRevision
    from app.services.media_backbone import derived_semantics_exclusion_clause
    settings = get_settings()
    if not (settings.user_auth_enabled and settings.b2_playback_canary_enabled):
        return None
    return db.query(MediaRevision.id).filter(MediaRevision.video_uuid == video_uuid,
        MediaRevision.rendition_semantics != 'browser_original',
        derived_semantics_exclusion_clause(MediaRevision.rendition_semantics),
        verified_original_clause()).order_by(MediaRevision.id.desc()).limit(1).scalar()


def status(db, dive, asset):
    revision_id = original_revision_id(db, dive.video_uuid)
    result = evaluation_access.media_status(db, SimpleNamespace(id=dive.id, dive_id=dive.id), asset, backbone_available=bool(revision_id))
    if result.get('rendition') != 'original' and revision_id:
        result.update(status='ready', rendition='original', playback_url='available')
        result['available_renditions'] = list(dict.fromkeys([*result['available_renditions'], 'original']))
    base = f'/api/v1/evaluations/automatic/{dive.id}/media'
    result['poster_url'] = base + '/poster' if result['poster_url'] else None
    result['playback_url'] = base + '/play' if result['playback_url'] else None
    result['full_quality_url'] = base + '/play?rendition=original' if result.get('full_quality_url') else None
    if result.get('preview_url'):
        result['preview_url'] = base + '/play?' + result['preview_url'].split('?', 1)[1]
    return result


def _ready_clause():
    """Only assign ready browser previews, never cloud-only originals.

    Original quality remains available through the authorized media route.
    Cold clips enter a later selection after bounded background preparation.
    """
    from app.models.media import MediaCacheEntry
    return exists(select(1).select_from(PhotosAsset).join(MediaCacheEntry, MediaCacheEntry.photos_asset_id == PhotosAsset.id).where(
        PhotosAsset.video_uuid == Dive.video_uuid, MediaCacheEntry.status == 'ready',
        MediaCacheEntry.rendition.in_(('proxy_720p', 'proxy_360p'))))


def stack(db, user, key, size=5):
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
    # Until the meter reveals the style, each owner's bucket leads with the
    # dives the panel already scored so a new judge meets a comparison fast;
    # afterwards the fair least-scored-first spread resumes.
    warming = compared_votes(db, user) < STYLE_REVEALED_AT
    vote_order = count.desc() if warming else count
    candidates = eligible(db, user).filter(~voted, ~cooling, ~outstanding).order_by(vote_order, Dive.dive_datetime.desc(), Dive.id)
    # Ready cache is filtered in SQL, so unavailable videos cannot hide the
    # playable corpus. Round-robin owners before taking a second dive each.
    ready = _ready_clause()
    owner = select(func.min(UserDiverAccess.user_id)).select_from(UserDiverAccess).join(AppUser).where(
        UserDiverAccess.diver_id == Dive.diver_id, UserDiverAccess.access_kind == 'OWNER', AppUser.is_active.is_(True)
    ).correlate(Dive).scalar_subquery()
    rank = func.row_number().over(partition_by=func.coalesce(owner, -Dive.diver_id), order_by=(vote_order, Dive.dive_datetime.desc(), Dive.id))
    ranked = candidates.filter(ready).order_by(None).add_columns(rank.label('owner_rank'), count.label('votes')).subquery()
    ids = db.query(ranked.c.id).order_by(ranked.c.owner_rank, ranked.c.votes.desc() if warming else ranked.c.votes,
        ranked.c.dive_datetime.desc(), ranked.c.id).limit(size).all()
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
                evaluation_access.prepare_media(db, dive, asset, reason='automatic_review_warmup')
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
        # Assignment is stable even if its preview expires after allocation.
        # Return cold media so the player can prepare/retry it; queue GETs
        # must not enqueue work or silently remove an assigned dive.
        name = db.query(Diver.display_name).filter_by(id=dive.diver_id).scalar()
        items.append({'request_id': dive.id, 'dive_id': dive.id, 'prompt': None,
            'dive': {'id': dive.id, 'video_uuid': dive.video_uuid, 'dive_code': dive.dive_code,
                'height': dive.height, 'platform_type': dive.platform_type, 'owner_display_name': name}, 'media': media})
    return {'batch_id': str(row.id), 'items': items, 'has_more': False}


def results(db, user, dive_id, limit=50, offset=0):
    rows = db.query(AutomaticRating).filter_by(dive_id=dive_id).filter(community_vote_clause()).order_by(AutomaticRating.id.desc()).offset(offset).limit(limit).all()
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


def rate(db, user, dive_id, score, comment, video_uuid, require_assignment=True):
    """Immutable automatic vote. The jury stack path requires the dive to be
    assigned in the voter's selection; the player path (any eligible public
    dive the member can watch) passes ``require_assignment=False``."""
    dive, asset = authorize(db, user, dive_id, lock=True)
    if dive.video_uuid != video_uuid:
        raise HTTPException(409, {'code': 'EVALUATION_CLOSED', 'message': 'Video changed; reload the selection'})
    old = db.query(AutomaticRating).filter_by(dive_id=dive_id, evaluator_user_id=user.id).first()
    if old:
        if old.score_half_steps != score or old.comment != comment:
            raise HTTPException(409, {'code': 'RATING_ALREADY_SUBMITTED', 'message': 'Vote is immutable'})
    else:
        # Cross-circuit single vote (bot review PR 127): the shared dive lock
        # taken by authorize() above serializes this check against a
        # concurrent request-circuit vote on the same dive.
        from app.models.evaluation import EvaluationRating
        request_row = evaluation_access.request_for_dive(db, dive_id)
        if request_row is not None and db.query(EvaluationRating.id).filter_by(
                request_id=request_row.id, evaluator_user_id=user.id).first() is not None:
            raise HTTPException(409, {'code': 'RATING_ALREADY_SUBMITTED',
                'message': 'This dive was already rated in the request circuit (one vote per member and dive)'})
        assigned = not require_assignment or db.query(ReviewStackItem).join(ReviewStack).filter(
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
            return rate(db, user, dive_id, score, comment, video_uuid, require_assignment)
    panel = results(db, user, dive_id)
    return {'rating': panel['my_rating'], 'results': panel}


def _stack_progress(db, user, row, items, voted):
    judged = sum(1 for i in items if i.dive_id in voted)
    skipped = sum(1 for i in items if i.skipped_at and i.dive_id not in voted)
    pending = any(not i.skipped_at and i.dive_id not in voted for i in items)
    remaining = len(queue(db, user, row.id)['items']) if pending else 0
    return {'stack_id': row.id, 'daily': row.key.startswith('daily:'), 'total': len(items),
        'judged': judged, 'skipped': skipped, 'remaining': remaining}


def today(db, user):
    """Read-only UTC-day progress; load daily + newest resumable stack."""
    now = datetime.utcnow()
    start = datetime(now.year, now.month, now.day)
    daily_row = db.query(ReviewStack).filter_by(user_id=user.id, key='daily:' + start.date().isoformat()).first()
    voted_item = exists(select(1).where(AutomaticRating.evaluator_user_id == user.id,
        AutomaticRating.dive_id == ReviewStackItem.dive_id).correlate(ReviewStackItem))
    resumable_item = eligible(db, user).filter(Dive.id == ReviewStackItem.dive_id,
        Dive.video_uuid == ReviewStackItem.video_uuid,
        exists(select(1).where(PhotosAsset.video_uuid == Dive.video_uuid))).exists()
    unfinished = exists(select(1).where(ReviewStackItem.stack_id == ReviewStack.id,
        ReviewStackItem.skipped_at.is_(None), ~voted_item, resumable_item).correlate(ReviewStack))
    resume_row = db.query(ReviewStack).filter(ReviewStack.user_id == user.id,
        ReviewStack.created_at >= start, unfinished).order_by(ReviewStack.id.desc()).first()
    rows = [daily_row] if daily_row is not None else []
    if resume_row is not None and (daily_row is None or resume_row.id != daily_row.id):
        rows.append(resume_row)
    # Progress reads are batched, independent of the number of earlier stacks.
    items = db.query(ReviewStackItem).filter(ReviewStackItem.stack_id.in_([r.id for r in rows])).all() if rows else []
    voted = {dive_id for (dive_id,) in db.query(AutomaticRating.dive_id).filter(
        AutomaticRating.evaluator_user_id == user.id,
        AutomaticRating.dive_id.in_({i.dive_id for i in items}))} if items else set()
    grouped = {r.id: [] for r in rows}
    for item in items:
        grouped[item.stack_id].append(item)
    stacks = {r.id: _stack_progress(db, user, r, grouped[r.id], voted) for r in rows}
    judged_today = db.query(func.count(AutomaticRating.id)).filter(
        AutomaticRating.evaluator_user_id == user.id, AutomaticRating.created_at >= start).scalar()
    return {'date': start.date().isoformat(), 'resets_at': (start + timedelta(days=1)).isoformat() + 'Z',
        'daily': stacks.get(daily_row.id) if daily_row is not None else None,
        'resume': next((stacks[r.id] for r in (resume_row, daily_row)
            if r is not None and stacks[r.id]['remaining']), None),
        'judged_today': judged_today, 'votes': today_votes(db, user, start)}


def _with_panels(db, rows, evaluator_user_id):
    """My votes next to the OTHER members' mean on the same dives."""
    ids = list({r.dive_id for r in rows})
    if not ids:
        return []
    totals = {dive_id: (count, total) for dive_id, count, total in db.query(
        AutomaticRating.dive_id, func.count(AutomaticRating.id), func.sum(AutomaticRating.score_half_steps)
    ).filter(AutomaticRating.dive_id.in_(ids), community_vote_clause(),
        AutomaticRating.evaluator_user_id != evaluator_user_id).group_by(AutomaticRating.dive_id)}
    out = []
    for r in rows:
        others, total = totals.get(r.dive_id, (0, 0))
        out.append({'dive_id': r.dive_id, 'dive_code': r.dive_code, 'height': r.height, 'diver': r.dive_name or None,
            'score_half_steps': r.score_half_steps,
            'panel_count': others, 'panel_mean': round(total / others / 2, 1) if others else None})
    return out


def today_votes(db, user, start):
    rows = db.query(AutomaticRating).filter(AutomaticRating.evaluator_user_id == user.id,
        AutomaticRating.created_at >= start).order_by(AutomaticRating.id.desc()).limit(30).all()
    return _with_panels(db, rows, user.id)


def judge_profile(db, user, sample=50):
    """Judging tendency vs the rest of the panel, plus the daily streak."""
    rows = db.query(AutomaticRating).filter(AutomaticRating.evaluator_user_id == user.id).order_by(
        AutomaticRating.id.desc()).limit(sample).all()
    compared = compared_votes(db, user, sample)
    bias = round(sum(v['score_half_steps'] / 2 - v['panel_mean']
                     for v in _with_panels(db, rows, user.id) if v['panel_mean'] is not None) / compared, 2) if compared else None
    days = {d if isinstance(d, str) else d.isoformat() for (d,) in db.query(func.date(AutomaticRating.created_at)).filter(
        AutomaticRating.evaluator_user_id == user.id).distinct().order_by(func.date(AutomaticRating.created_at).desc()).limit(400)}
    day = datetime.utcnow().date()
    if day.isoformat() not in days:
        day -= timedelta(days=1)  # a streak stays alive until today's selection is missed
    streak = 0
    while day.isoformat() in days:
        streak += 1
        day -= timedelta(days=1)
    return {'compared': compared, 'bias': bias, 'streak': streak}
