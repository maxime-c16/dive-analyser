"""Session-only messaging. Membership is required even for administrators.

Fetching never implies delivery or reading: the recipient explicitly acknowledges
received/visible messages. Dive cards re-check access on every read; sending never
grants access. Notification text carries no private message content.
"""
from datetime import datetime
from uuid import UUID
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.api.v1.auth import get_current_user, _origin_allowed
from app.api.v1.users import _identity
from app.database import get_db
from app.models.user_auth import AppUser
from app.models.dive import Dive
from app.models.media import MediaCacheEntry
from app.models.direct_message import Conversation, ConversationParticipant, ConversationTitle, DirectMessage, MessageReceipt, MessageReaction
from app.services.mentions import MentionInput, validate_mentions
from app.services.user_access import _dive_access
from app.services.dive_access import owned_diver_ids
from app.services.media_cache import playback_url
from app.services import achievements, notification_service

router = APIRouter(prefix='/messages')


def writer(request: Request, user=Depends(get_current_user)):
    if not _origin_allowed(request):
        raise HTTPException(403, 'Origin not allowed')
    return user


def conversation(db, user, id, lock=False):
    query = db.query(Conversation).join(ConversationParticipant).filter(
        Conversation.id == id, ConversationParticipant.user_id == user.id,
        ConversationParticipant.left_at.is_(None))
    row = query.with_for_update(of=Conversation).first() if lock else query.first()
    if row is None:
        raise HTTPException(404, 'Conversation not found')
    return row


def iso(value):
    return value.isoformat() + 'Z' if value else None


def message_payloads(db, user, rows):
    ids = [m.id for m in rows]
    receipts, reactions = {}, {}
    for r in db.query(MessageReceipt).filter(MessageReceipt.message_id.in_(ids)).all():
        receipts.setdefault(r.message_id, []).append(dict(user_id=r.user_id, delivered_at=iso(r.delivered_at), read_at=iso(r.read_at)))
    for r in db.query(MessageReaction).filter(MessageReaction.message_id.in_(ids)).all():
        reactions.setdefault(r.message_id, []).append(dict(user_id=r.user_id, emoji=r.emoji))
    dive_ids = {m.dive_id for m in rows if m.dive_id is not None}
    dives = {d.id: d for d in db.query(Dive).filter(Dive.id.in_(dive_ids)).all()} if dive_ids else {}
    owned = set(owned_diver_ids(db, user.id)) if dives else set()
    posters = {}
    asset_ids = {d.photos_asset_id for d in dives.values() if d.photos_asset_id}
    if asset_ids:
        for p in db.query(MediaCacheEntry).filter(MediaCacheEntry.photos_asset_id.in_(asset_ids), MediaCacheEntry.rendition == 'poster', MediaCacheEntry.status == 'ready').all():
            posters[p.photos_asset_id] = playback_url(p)
    result = []
    for m in rows:
        dive = dives.get(m.dive_id)
        card = None
        if m.has_dive:
            card = dict(available=False)
            if dive is not None and ((dive.diver_id is not None and (dive.visibility == "public" or dive.diver_id in owned)) or (dive.diver_id is None and user.is_admin)):
                card = dict(available=True, id=dive.id, dive_code=dive.dive_code, height=dive.height, poster_url=posters.get(dive.photos_asset_id))
        result.append(dict(id=m.id, conversation_id=m.conversation_id, sender_id=m.sender_id, client_id=m.client_id,
                           body=m.body, mentions=m.mentions or [], dive=card, created_at=iso(m.created_at),
                           receipts=receipts.get(m.id, []), reactions=reactions.get(m.id, [])))
    return result


class StartInput(BaseModel):
    user_id: int = Field(gt=0)


@router.post('/conversations')
def start(payload: StartInput, user=Depends(writer), db: Session = Depends(get_db)):
    if payload.user_id == user.id:
        raise HTTPException(422, 'Choose another member')
    target = db.query(AppUser).filter_by(id=payload.user_id, is_active=True).first()
    if target is None:
        raise HTTPException(404, 'Member not found')
    key = ':'.join(map(str, sorted([user.id, target.id])))
    row = db.query(Conversation).filter_by(direct_key=key).first()
    if row is None:
        row = Conversation(kind='direct', direct_key=key)
        db.add(row)
        try:
            db.flush()
            db.add_all([ConversationParticipant(conversation_id=row.id, user_id=id) for id in (user.id, target.id)])
            db.commit()
        except IntegrityError:
            db.rollback()
            row = db.query(Conversation).filter_by(direct_key=key).one()
    conversation(db, user, row.id)
    return dict(id=row.id)


MAX_GROUP_MEMBERS = 16


class GroupInput(BaseModel):
    user_ids: list[int] = Field(min_length=2, max_length=MAX_GROUP_MEMBERS - 1)
    title: str = Field('', max_length=60)


class TitleInput(BaseModel):
    title: str = Field('', max_length=60)


def _clean_title(value: str) -> str:
    return ' '.join(value.split())


def _set_title(db, conversation_id: int, user_id: int, title: str):
    row = db.get(ConversationTitle, conversation_id)
    if not title:
        if row is not None:
            db.delete(row)
        return
    if row is None:
        db.add(ConversationTitle(conversation_id=conversation_id, title=title, updated_by=user_id))
    else:
        row.title, row.updated_by, row.updated_at = title, user_id, datetime.utcnow()


def _titles(db, ids) -> dict[int, str]:
    return dict(db.query(ConversationTitle.conversation_id, ConversationTitle.title).filter(ConversationTitle.conversation_id.in_(ids)).all()) if ids else {}


@router.post('/conversations/group', status_code=201)
def start_group(payload: GroupInput, user=Depends(writer), db: Session = Depends(get_db)):
    """A new group with you and at least two other active members.

    Unlike direct conversations, groups are never deduplicated: the same
    people may keep several groups (a training squad, a trip).
    """
    ids = sorted({i for i in payload.user_ids if i > 0} - {user.id})
    if len(ids) < 2:
        raise HTTPException(422, 'Choose at least two other members')
    found = {row.id for row in db.query(AppUser.id).filter(AppUser.id.in_(ids), AppUser.is_active.is_(True)).all()}
    if found != set(ids):
        raise HTTPException(404, 'Member not found')
    row = Conversation(kind='group')
    db.add(row)
    db.flush()
    db.add_all([ConversationParticipant(conversation_id=row.id, user_id=i) for i in [user.id, *ids]])
    _set_title(db, row.id, user.id, _clean_title(payload.title))
    db.commit()
    return dict(id=row.id)


@router.put('/conversations/{id}/title')
def rename_group(id: int, payload: TitleInput, user=Depends(writer), db: Session = Depends(get_db)):
    """Any current member may name or rename a group; an empty title clears it."""
    row = conversation(db, user, id, lock=True)
    if row.kind != 'group':
        raise HTTPException(409, 'Only groups have a name')
    title = _clean_title(payload.title)
    _set_title(db, id, user.id, title)
    db.commit()
    return dict(title=title or None)


@router.post('/conversations/{id}/leave', status_code=204)
def leave_group(id: int, user=Depends(writer), db: Session = Depends(get_db)):
    """Leave a group: it disappears from your inbox and unread count; history stays for the others."""
    row = conversation(db, user, id, lock=True)
    if row.kind != 'group':
        raise HTTPException(409, 'Only groups can be left')
    db.query(ConversationParticipant).filter_by(conversation_id=id, user_id=user.id).update({'left_at': datetime.utcnow()})
    db.commit()


@router.get('/conversations')
def inbox(before: str | None = None, limit: int = Query(30, ge=1, le=50), user=Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(Conversation).join(ConversationParticipant).filter(ConversationParticipant.user_id == user.id, ConversationParticipant.left_at.is_(None))
    if before:
        try:
            stamp, id = before.rsplit(',', 1)
            stamp, id = datetime.fromisoformat(stamp), int(id)
        except ValueError:
            raise HTTPException(422, 'Invalid cursor')
        query = query.filter(or_(Conversation.updated_at < stamp, and_(Conversation.updated_at == stamp, Conversation.id < id)))
    rows = query.order_by(Conversation.updated_at.desc(), Conversation.id.desc()).limit(limit + 1).all()
    ids = [row.id for row in rows[:limit]]
    members_by_conv = {}
    for cid, member in db.query(ConversationParticipant.conversation_id, AppUser).join(AppUser, AppUser.id == ConversationParticipant.user_id).filter(ConversationParticipant.conversation_id.in_(ids), ConversationParticipant.left_at.is_(None)).all():
        members_by_conv.setdefault(cid, []).append(_identity(member))
    latest_ids = db.query(func.max(DirectMessage.id)).filter(DirectMessage.conversation_id.in_(ids)).group_by(DirectMessage.conversation_id)
    latest_rows = db.query(DirectMessage).filter(DirectMessage.id.in_(latest_ids)).all()
    latest = {m['conversation_id']: m for m in message_payloads(db, user, latest_rows)}
    unread = dict(db.query(DirectMessage.conversation_id, func.count(MessageReceipt.message_id)).join(MessageReceipt, MessageReceipt.message_id == DirectMessage.id).filter(DirectMessage.conversation_id.in_(ids), MessageReceipt.user_id == user.id, MessageReceipt.read_at.is_(None)).group_by(DirectMessage.conversation_id).all())
    titles = _titles(db, ids)
    items = [dict(id=row.id, kind=row.kind, title=titles.get(row.id), members=members_by_conv.get(row.id, []), updated_at=iso(row.updated_at),
                  unread_count=unread.get(row.id, 0), latest=latest.get(row.id)) for row in rows[:limit]]
    return dict(items=items, next_before=f'{rows[limit-1].updated_at.isoformat()},{rows[limit-1].id}' if len(rows) > limit else None)


@router.get('/unread-count')
def unread_count(user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Total unread across every conversation, not just one inbox page.

    The badge needs one number the client cannot derive by paging: the inbox
    caps each page, so older unread conversations would silently disappear
    from the sum. Single aggregate over the same rows inbox() counts.
    """
    total = db.query(func.count(MessageReceipt.message_id)).join(
        DirectMessage, DirectMessage.id == MessageReceipt.message_id
    ).join(Conversation, Conversation.id == DirectMessage.conversation_id).join(
        ConversationParticipant, ConversationParticipant.conversation_id == Conversation.id
    ).filter(
        ConversationParticipant.user_id == user.id,
        ConversationParticipant.left_at.is_(None),
        MessageReceipt.user_id == user.id,
        MessageReceipt.read_at.is_(None),
    ).scalar()
    return dict(unread_count=int(total or 0))


@router.get('/conversations/{id}')
def details(id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    row = conversation(db, user, id)
    members = db.query(AppUser).join(ConversationParticipant, ConversationParticipant.user_id == AppUser.id).filter(ConversationParticipant.conversation_id == id, ConversationParticipant.left_at.is_(None)).all()
    return dict(id=id, kind=row.kind, title=_titles(db, [id]).get(id), members=[_identity(u) for u in members])


@router.get('/conversations/{id}/messages')
def messages(id: int, before: int | None = Query(None, gt=0), limit: int = Query(50, ge=1, le=50), user=Depends(get_current_user), db: Session = Depends(get_db)):
    conversation(db, user, id)
    query = db.query(DirectMessage).filter_by(conversation_id=id)
    if before:
        query = query.filter(DirectMessage.id < before)
    rows = query.order_by(DirectMessage.id.desc()).limit(limit + 1).all()
    return dict(items=message_payloads(db, user, list(reversed(rows[:limit]))), next_before=rows[limit-1].id if len(rows) > limit else None)


class SendInput(BaseModel):
    client_id: UUID
    body: str = Field(default='', max_length=2000)
    dive_id: int | None = Field(default=None, gt=0)
    mentions: list[MentionInput] = Field(default_factory=list, max_length=10)


@router.post('/conversations/{id}/messages', status_code=201)
def send(id: int, payload: SendInput, background_tasks: BackgroundTasks, user=Depends(writer), db: Session = Depends(get_db)):
    conv = conversation(db, user, id, lock=True)
    existing = db.query(DirectMessage).filter_by(sender_id=user.id, client_id=str(payload.client_id)).first()
    if existing:
        if existing.conversation_id != id:
            raise HTTPException(409, 'Retry key belongs to another conversation')
        return message_payloads(db, user, [existing])[0]
    body = payload.body.strip()
    if not body and payload.dive_id is None:
        raise HTTPException(422, 'Write a message or select a dive')
    mentions = validate_mentions(db, payload.body, payload.mentions)
    trim = len(payload.body) - len(payload.body.lstrip())
    mentions = [dict(m, start=m['start'] - trim, end=m['end'] - trim) for m in mentions]
    members = db.query(AppUser).join(ConversationParticipant, ConversationParticipant.user_id == AppUser.id).filter(ConversationParticipant.conversation_id == id, ConversationParticipant.left_at.is_(None)).all()
    if len(members) < 2 or any(not m.is_active for m in members):
        raise HTTPException(409, 'A participant is unavailable')
    if payload.dive_id is not None:
        dive = db.query(Dive).filter_by(id=payload.dive_id).first()
        if dive is None or any(not _dive_access(db, m, dive).allowed for m in members):
            raise HTTPException(404, 'Dive unavailable to a participant')
    row = DirectMessage(conversation_id=id, sender_id=user.id, client_id=str(payload.client_id), body=body, mentions=mentions, dive_id=payload.dive_id, has_dive=int(payload.dive_id is not None))
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.query(DirectMessage).filter_by(sender_id=user.id, client_id=str(payload.client_id)).first()
        if existing is None:
            raise
        if existing.conversation_id != id:
            raise HTTPException(409, 'Retry key belongs to another conversation')
        return message_payloads(db, user, [existing])[0]
    db.add_all([MessageReceipt(message_id=row.id, user_id=m.id) for m in members if m.id != user.id])
    conv.updated_at = row.created_at
    db.commit()
    # Inbox creation is durable; push is deferred. Retry keys avoid duplicate events.
    try:
        pending = [notification_service.create(db, user_id=m.id, type='direct_message', title='New message', body=f'{user.display_name} sent you a message.', conversation_id=id, defer_push=True) for m in members if m.id != user.id]
        notification_service.schedule_push(background_tasks, [r for r in pending if r is not None])
    except Exception:
        db.rollback()
        import logging
        logging.getLogger(__name__).exception('message notification failed for conversation %s', id)
    achievements.award(db, user.id, achievements.MESSAGE, achievements.COMMENT)
    return message_payloads(db, user, [row])[0]


class ReceiptInput(BaseModel):
    message_ids: list[int] = Field(min_length=1, max_length=50)
    read: bool = False


@router.post('/conversations/{id}/receipts', status_code=204)
def acknowledge(id: int, payload: ReceiptInput, user=Depends(writer), db: Session = Depends(get_db)):
    conversation(db, user, id)
    rows = db.query(MessageReceipt).join(DirectMessage, DirectMessage.id == MessageReceipt.message_id).filter(DirectMessage.conversation_id == id, MessageReceipt.user_id == user.id, MessageReceipt.message_id.in_(payload.message_ids)).with_for_update(of=MessageReceipt).all()
    if len(rows) != len(set(payload.message_ids)):
        raise HTTPException(404, 'Message not found')
    now = datetime.utcnow()
    for row in rows:
        if row.delivered_at is None:
            row.delivered_at = now
        if payload.read and row.read_at is None:
            row.read_at = now
    db.commit()


class ReactionInput(BaseModel):
    reacted: bool


@router.put('/conversations/{id}/messages/{message_id}/reaction')
def react(id: int, message_id: int, payload: ReactionInput, user=Depends(writer), db: Session = Depends(get_db)):
    conversation(db, user, id, lock=True)
    row = db.query(DirectMessage).filter_by(id=message_id, conversation_id=id).first()
    if row is None:
        raise HTTPException(404, 'Message not found')
    existing = db.query(MessageReaction).filter_by(message_id=message_id, user_id=user.id).first()
    if payload.reacted and existing is None:
        db.add(MessageReaction(message_id=message_id, user_id=user.id, emoji='❤️'))
    elif not payload.reacted and existing:
        db.delete(existing)
    db.commit()
    return message_payloads(db, user, [row])[0]
