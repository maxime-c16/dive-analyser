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
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.notification import Notification, NotificationPref
from app.models.user_auth import UserDiverAccess

logger = logging.getLogger(__name__)

NOTIF_TYPES = frozenset({
    "new_video",
    "video_ready",
    "new_comment",
    "comment_reply",
    "milestone",
    "sync_error",
    "guest_activity",
})

DEFAULTS: Dict[str, bool] = {
    "new_video": True,
    "video_ready": True,
    "new_comment": True,
    "comment_reply": True,
    "milestone": True,
    "sync_error": True,
    "guest_activity": False,
}

_MAX_LIST_LIMIT = 100
_TITLE_MAX = 200
_BODY_MAX = 600


def _validate_type(notif_type: str) -> None:
    if notif_type not in NOTIF_TYPES:
        raise ValueError(f"Unknown notification type: {notif_type}")


def is_enabled(db: Session, user_id: int, notif_type: str) -> bool:
    """Preference for one user/type; DEFAULTS when no override row exists."""
    _validate_type(notif_type)
    row = (
        db.query(NotificationPref)
        .filter_by(user_id=user_id, notif_type=notif_type)
        .first()
    )
    if row is None:
        return DEFAULTS[notif_type]
    return bool(row.enabled)


def create(
    db: Session,
    *,
    user_id: int,
    type: str,
    title: str,
    body: str = "",
    dive_id: Optional[int] = None,
) -> Optional[Notification]:
    """Create one inbox row, or None when the type is disabled for the user."""
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


def notify_owners_for_diver(
    db: Session,
    *,
    diver_id: Optional[int],
    exclude_user_id: Optional[int] = None,
    type: str,
    title: str,
    body: str = "",
    dive_id: Optional[int] = None,
) -> List[Notification]:
    """One row per owner of diver_id (minus the actor). Prefs still apply."""
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
    # fan-out re-checks prefs per recipient anyway. Never raises.
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
    prefs = dict(DEFAULTS)
    rows = (
        db.query(NotificationPref).filter_by(user_id=user_id).limit(len(NOTIF_TYPES)).all()
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
        .limit(len(NOTIF_TYPES))
        .all()
    )
    return sorted({row[0] for row in rows if row[0] in NOTIF_TYPES})


def set_pref(
    db: Session, user_id: int, type: str, enabled: bool
) -> NotificationPref:
    """Upsert one preference override; raises ValueError on unknown type."""
    _validate_type(type)
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
