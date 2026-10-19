"""Durable per-user notification inbox (PR1 backend foundation).

Ownership rules:
- Every write is addressed to an explicit user_id resolved server-side
  (UserDiverAccess for diver-scoped events, parent comment author for
  replies). The API layer never takes a user_id from the client.
- Reads and state changes are always scoped to the session user, so one
  member can never read or mark another member's row (API maps miss → 404).
- Preference checks default to DEFAULTS when no row exists; a disabled
  type returns None without writing (anti-spam).
"""
import logging
from datetime import datetime
from typing import Dict, List, Optional, Sequence

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from app.models.notification import Notification, NotificationPref
from app.models.user_auth import UserDiverAccess

logger = logging.getLogger(__name__)

NOTIF_TYPES = frozenset({
    "new_video",
    "video_ready",
    "new_comment",
    "comment_reply",
    "direct_message",
    "milestone",
    "sync_error",
    "guest_activity",
})

DEFAULTS: Dict[str, bool] = {
    "new_video": True,
    "video_ready": True,
    "new_comment": True,
    "comment_reply": True,
    "direct_message": True,
    "milestone": True,
    "sync_error": True,
    "guest_activity": False,
}

# Calendar alert types (Task05). Written only by the calendar alerts worker
# (calendar_alerts) through stage(); exposed by the preferences API only when
# CALENDAR_ENABLED, so the feature-off contract stays byte-identical.
# - invitation: you were invited to an event
# - change: time/venue change or cancellation of something you take part in
#   (interest, invitation, or your assigned group's training)
# - reminder: previous-day reminder for sessions you marked "Interested"
# - group_reminder: previous-day reminder for every session of your assigned
#   training group (opt-in: routine sessions, no response expected)
# - follow: followed events/calendars (never from imported edits)
CALENDAR_DEFAULTS: Dict[str, bool] = {
    "calendar_invitation": True,
    "calendar_change": True,
    "calendar_reminder": True,
    "calendar_group_reminder": False,
    "calendar_follow": True,
}
CALENDAR_TYPES = frozenset(CALENDAR_DEFAULTS)
_ALL_DEFAULTS: Dict[str, bool] = {**DEFAULTS, **CALENDAR_DEFAULTS}

_MAX_LIST_LIMIT = 100
_TITLE_MAX = 200
_BODY_MAX = 600

# Bound background push scheduling: ids travel in batches of at most this
# many per background task (IN query stays small; push_service sends every
# scheduled row in MAX_PUSH_SENDS_PER_CHUNK chunks anyway). Large requests
# schedule one task per batch — never truncated.
_MAX_PUSH_IDS_PER_SCHEDULE = 50


def _validate_type(notif_type: str) -> None:
    if notif_type not in NOTIF_TYPES and notif_type not in CALENDAR_TYPES:
        raise ValueError(f"Unknown notification type: {notif_type}")


def _pref_defaults(db: Session) -> Dict[str, bool]:
    """Types the preferences API exposes: calendar ones only when enabled."""
    from app.services.calendar_launch import enabled

    if enabled(db):
        return dict(_ALL_DEFAULTS)
    return dict(DEFAULTS)


def is_enabled(db: Session, user_id: int, notif_type: str) -> bool:
    """Preference for one user/type; DEFAULTS when no override row exists."""
    _validate_type(notif_type)
    row = (
        db.query(NotificationPref)
        .filter_by(user_id=user_id, notif_type=notif_type)
        .first()
    )
    if row is None:
        return _ALL_DEFAULTS[notif_type]
    return bool(row.enabled)


def create(
    db: Session,
    *,
    user_id: int,
    type: str,
    title: str,
    body: str = "",
    dive_id: Optional[int] = None,
    defer_push: bool = False,
    conversation_id: Optional[int] = None,
) -> Optional[Notification]:
    """Create one inbox row, or None when the type is disabled for the user.

    Inbox commit stays synchronous (callers depend on it). Push is inline
    by default (tests, journey background) but request-path callers pass
    defer_push=True and schedule fanout_in_background via BackgroundTasks
    so blocking pywebpush never runs on the single uvicorn event loop.
    """
    _validate_type(type)
    try:
        if not is_enabled(db, user_id, type):
            return None
        row = Notification(
            user_id=user_id,
            type=type,
            title=(title or "")[:_TITLE_MAX],
            body=(body or "")[:_BODY_MAX] or None,
            dive_id=dive_id,
            conversation_id=conversation_id,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
    except Exception:
        # A failure here must never poison the caller's session: hooks
        # swallow notif errors and keep using `db` afterwards.
        try:
            db.rollback()
        except Exception:
            pass
        raise
    if defer_push:
        return row
    # Best-effort Web Push mirror (PR3): skipped when VAPID is unconfigured,
    # prunes dead endpoints, never raises, never logs secrets.
    try:
        from app.services import push_service

        push_service.fanout_for_rows(db, [row])
    except Exception:
        logger.exception("push fan-out failed for user %s", user_id)
        try:
            db.rollback()
        except Exception:
            pass
    return row


def fanout_in_background(notification_ids: Sequence[int]) -> None:
    """Background push entry: fresh SessionLocal, bounded, never raises.

    Scheduled via FastAPI BackgroundTasks from request-path endpoints
    (dives.upload, videos.sync/batch, dive_social.comment). Starlette runs
    sync background tasks in its threadpool, so blocking pywebpush calls
    never touch the single uvicorn event loop. Uses its OWN SessionLocal —
    never the request session (already closed when background runs).
    Bounded: ids are re-fetched in _MAX_PUSH_IDS_PER_SCHEDULE pages (IN
    query stays small), every row fanned out in MAX_PUSH_SENDS_PER_CHUNK
    chunks (push_service). Rollback before close; logs user ids and counts
    only, never endpoints/keys.
    """
    ids = [int(i) for i in (notification_ids or [])]
    if not ids:
        return
    try:
        from app.services import push_service

        if not push_service.is_push_configured():
            return
    except Exception:
        # is_push_configured only reads settings; a failure here means
        # push cannot send anyway — skip DB work entirely.
        return
    # Import here so tests can monkeypatch app.database.SessionLocal and
    # so module import never cycles with push_service.
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        from app.services import push_service

        for start in range(0, len(ids), _MAX_PUSH_IDS_PER_SCHEDULE):
            chunk = ids[start : start + _MAX_PUSH_IDS_PER_SCHEDULE]
            rows = (
                db.query(Notification).filter(Notification.id.in_(chunk)).limit(len(chunk)).all()
            )
            if not rows:
                continue
            push_service.fanout_for_rows(db, rows)
    except Exception as exc:
        logger.error("background push fan-out failed (%s)", type(exc).__name__)
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        try:
            db.rollback()
        except Exception:
            pass
        try:
            db.close()
        except Exception:
            pass


def schedule_push(background_tasks: Optional[BackgroundTasks], rows: Sequence[Notification]) -> None:
    """Queue fanout_in_background for committed inbox rows (best-effort).

    Extracts ids only (never ORM objects — the request session closes
    before background runs). No-op when there is nothing to push or no
    background queue (rare direct-call edge: inbox already committed).
    Large requests are split into _MAX_PUSH_IDS_PER_SCHEDULE batches, one
    background task per batch, so every row is fanned out (never
    truncated).
    """
    if background_tasks is None or not rows:
        return
    try:
        ids = [row.id for row in rows if getattr(row, "id", None) is not None]
    except Exception:
        return
    if not ids:
        return
    try:
        for start in range(0, len(ids), _MAX_PUSH_IDS_PER_SCHEDULE):
            background_tasks.add_task(
                fanout_in_background, ids[start : start + _MAX_PUSH_IDS_PER_SCHEDULE]
            )
    except Exception as exc:
        logger.error("push schedule failed (%s)", type(exc).__name__)


def notify_owners_for_diver(
    db: Session,
    *,
    diver_id: Optional[int],
    exclude_user_id: Optional[int] = None,
    type: str,
    title: str,
    body: str = "",
    dive_id: Optional[int] = None,
    defer_push: bool = False,
) -> List[Notification]:
    """One row per owner of diver_id (minus the actor). Prefs still apply.

    Single-commit batch: exactly one commit for the inbox rows. Push is
    inline by default but request-path callers pass defer_push=True and
    schedule fanout_in_background via BackgroundTasks (off event loop).
    """
    _validate_type(type)
    if diver_id is None:
        return []
    try:
        user_ids = [
            row[0]
            for row in db.query(UserDiverAccess.user_id)
            .filter(UserDiverAccess.diver_id == diver_id)
            .limit(500)
            .all()
        ]
    except Exception:
        logger.exception("notification owner fetch failed for diver %s", diver_id)
        try:
            db.rollback()
        except Exception:
            pass
        return []
    targets = [
        uid
        for uid in dict.fromkeys(user_ids)
        if exclude_user_id is None or uid != exclude_user_id
    ]
    if not targets:
        return []
    try:
        pref_rows = (
            db.query(NotificationPref)
            .filter(
                NotificationPref.user_id.in_(targets),
                NotificationPref.notif_type == type,
            )
            .all()
        )
    except Exception:
        logger.exception("notification pref fetch failed for diver %s", diver_id)
        try:
            db.rollback()
        except Exception:
            pass
        return []
    default_enabled = DEFAULTS[type]
    enabled_by_user = {row.user_id: bool(row.enabled) for row in pref_rows}
    # No override row → DEFAULTS[type] (mirrors is_enabled used by create()).
    enabled_ids = [
        uid for uid in targets if enabled_by_user.get(uid, default_enabled)
    ]
    if not enabled_ids:
        return []
    title_t = (title or "")[:_TITLE_MAX]
    body_t = (body or "")[:_BODY_MAX] or None
    created = [
        Notification(
            user_id=uid,
            type=type,
            title=title_t,
            body=body_t,
            dive_id=dive_id,
        )
        for uid in enabled_ids
    ]
    try:
        db.add_all(created)
        db.flush()
        ids = [row.id for row in created]
        db.commit()
        # One re-select instead of one refresh (SELECT) per recipient.
        rows = (
            db.query(Notification).filter(Notification.id.in_(ids)).all()
            if ids
            else []
        )
    except Exception:
        logger.exception("notification batch create failed for diver %s", diver_id)
        try:
            db.rollback()
        except Exception:
            pass
        return []
    # Best-effort Web Push mirror (PR3): only enabled types produced rows,
    # fan-out re-checks prefs per recipient anyway. Never raises. Skipped
    # when defer_push (request path schedules fanout_in_background instead).
    if defer_push:
        return rows
    try:
        from app.services import push_service

        push_service.fanout_for_rows(db, rows)
    except Exception:
        logger.exception("push fan-out failed for diver %s", diver_id)
        try:
            db.rollback()
        except Exception:
            pass
    return rows


def list_for_user(
    db: Session, user_id: int, limit: int = 50, unread_only: bool = False
) -> List[Notification]:
    """Newest-first inbox rows for exactly one user; LIMIT capped at 100."""
    limit = max(1, min(int(limit or 50), _MAX_LIST_LIMIT))
    query = db.query(Notification).filter(Notification.user_id == user_id)
    if unread_only:
        query = query.filter(Notification.read_at.is_(None))
    return (
        query.order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(limit)
        .all()
    )


def count_unread(db: Session, user_id: int) -> int:
    return (
        db.query(Notification)
        .filter(Notification.user_id == user_id, Notification.read_at.is_(None))
        .count()
    )


def mark_read(
    db: Session, user_id: int, notif_id: int
) -> Optional[Notification]:
    """Mark one row read iff it belongs to the user; else None (→ 404)."""
    row = (
        db.query(Notification)
        .filter(Notification.id == notif_id, Notification.user_id == user_id)
        .first()
    )
    if row is None:
        return None
    if row.read_at is None:
        row.read_at = datetime.utcnow()
        db.commit()
        db.refresh(row)
    return row


def mark_all_read(db: Session, user_id: int) -> int:
    """Mark the whole inbox read for exactly one user; returns rows touched."""
    now = datetime.utcnow()
    count = (
        db.query(Notification)
        .filter(Notification.user_id == user_id, Notification.read_at.is_(None))
        .update({Notification.read_at: now}, synchronize_session=False)
    )
    db.commit()
    return int(count or 0)


def get_prefs(db: Session, user_id: int) -> Dict[str, bool]:
    """Complete type → enabled map (DEFAULTS plus stored overrides)."""
    prefs = _pref_defaults(db)
    rows = (
        db.query(NotificationPref).filter_by(user_id=user_id).limit(len(_ALL_DEFAULTS)).all()
    )
    for row in rows:
        if row.notif_type in prefs:
            prefs[row.notif_type] = bool(row.enabled)
    return prefs


def list_explicit_types(db: Session, user_id: int) -> List[str]:
    """Types with a stored override row (explicit user choice, any value)."""
    rows = (
        db.query(NotificationPref.notif_type)
        .filter_by(user_id=user_id)
        .limit(len(_ALL_DEFAULTS))
        .all()
    )
    exposed = _pref_defaults(db)
    return sorted({row[0] for row in rows if row[0] in exposed})


def set_pref(
    db: Session, user_id: int, type: str, enabled: bool
) -> NotificationPref:
    """Upsert one preference override; raises ValueError on unknown type."""
    if type not in _pref_defaults(db):
        raise ValueError(f"Unknown notification type: {type}")
    row = (
        db.query(NotificationPref)
        .filter_by(user_id=user_id, notif_type=type)
        .first()
    )
    if row is None:
        row = NotificationPref(user_id=user_id, notif_type=type, enabled=bool(enabled))
        db.add(row)
    else:
        row.enabled = bool(enabled)
    db.commit()
    db.refresh(row)
    return row


def stage(
    db: Session,
    *,
    user_id: int,
    type: str,
    title: str,
    body: str = "",
) -> Notification:
    """Transaction-aware inbox insert (Task05 calendar path): add + flush,
    never commit, no preference check and no push. The caller owns the
    transaction (it re-checks preferences and eligibility, commits the row
    together with its delivery state, then pushes best-effort). create()
    and notify_owners_for_diver() keep their self-committing contract."""
    _validate_type(type)
    row = Notification(
        user_id=user_id,
        type=type,
        title=(title or "")[:_TITLE_MAX],
        body=(body or "")[:_BODY_MAX] or None,
    )
    db.add(row)
    db.flush()
    return row
