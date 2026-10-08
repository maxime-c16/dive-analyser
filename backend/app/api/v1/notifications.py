"""Authenticated notification inbox (PR1, backend only).

Session pattern mirrors dive_social.py/updates.py: the session cookie is
the only identity source (get_current_user → 401 when signed out) and no
user_id is ever taken from the client. A row that does not belong to the
caller reads as missing (404), never as forbidden.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.config import get_settings
from app.database import get_db
from app.models.notification import PushSubscription
from app.services import notification_service
from app.services.push_service import MAX_SUBSCRIPTIONS_PER_USER, is_allowed_push_endpoint, is_push_configured

import logging

logger = logging.getLogger(__name__)

router = APIRouter()


def _payload(row) -> dict:
    return {
        "id": row.id,
        "type": row.type,
        "title": row.title,
        "body": row.body,
        "dive_id": row.dive_id,
        "conversation_id": row.conversation_id,
        "read_at": row.read_at.isoformat() + "Z" if row.read_at else None,
        "created_at": row.created_at.isoformat() + "Z" if row.created_at else None,
    }


class PrefInput(BaseModel):
    type: str = Field(min_length=1, max_length=64)
    enabled: bool


class PushKeysInput(BaseModel):
    p256dh: str = Field(min_length=1, max_length=512)
    auth: str = Field(min_length=1, max_length=512)


class PushSubscriptionInput(BaseModel):
    endpoint: str = Field(min_length=1, max_length=2048)
    keys: PushKeysInput
    device_label: str | None = Field(default=None, max_length=100)


class PushSubscriptionDelete(BaseModel):
    endpoint: str = Field(min_length=1, max_length=2048)


@router.get("/notifications")
def list_notifications(
    unread_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=100),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    items = notification_service.list_for_user(
        db, user.id, limit=limit, unread_only=unread_only
    )
    return {
        "items": [_payload(row) for row in items],
        "unread_count": notification_service.count_unread(db, user.id),
    }


@router.post("/notifications/{notif_id}/read")
def read_notification(
    notif_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)
):
    row = notification_service.mark_read(db, user.id, notif_id)
    if row is None:
        raise HTTPException(404, "Notification not found")
    return _payload(row)


@router.post("/notifications/read-all")
def read_all_notifications(
    user=Depends(get_current_user), db: Session = Depends(get_db)
):
    return {"marked": notification_service.mark_all_read(db, user.id)}


@router.get("/notification-prefs")
def get_prefs(user=Depends(get_current_user), db: Session = Depends(get_db)):
    return {
        "prefs": notification_service.get_prefs(db, user.id),
        "explicit": notification_service.list_explicit_types(db, user.id),
    }


@router.put("/notification-prefs")
def put_pref(
    payload: PrefInput, user=Depends(get_current_user), db: Session = Depends(get_db)
):
    try:
        row = notification_service.set_pref(
            db, user.id, payload.type, payload.enabled
        )
    except ValueError:
        raise HTTPException(422, "Unknown notification type")
    return {"type": row.notif_type, "enabled": bool(row.enabled)}


@router.get("/push-config")
def get_push_config(user=Depends(get_current_user)):
    """VAPID public key for Web Push opt-in; "" unless fully configured.

    Shares is_push_configured() with fan-out: a partial setup (public key
    without private key or subject) reads as disabled so the UI never
    offers a broken opt-in.
    """
    if not is_push_configured():
        return {"publicKey": ""}
    return {"publicKey": get_settings().vapid_public_key.strip()}


@router.post("/push-subscriptions")
def upsert_push_subscription(
    payload: PushSubscriptionInput,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Register (or refresh) one device endpoint for exactly one user.

    Upsert is keyed by endpoint globally, but an endpoint owned by another
    account reads as missing (404), never as forbidden — same ownership
    rule as the inbox. Stored devices per user are bounded; the oldest
    subscription is evicted on overflow.

    Race-safe: two concurrent inserts of the same endpoint hit the unique
    constraint — the loser rolls back, re-reads the winner and updates its
    keys/label instead of returning 500. DB failures never log endpoint
    URLs, keys, statements or exception messages (bound params would leak
    secrets) — only the exception type name plus user id.
    """
    # SSRF guard: only exact public browser push services (https, allowlisted
    # host, no non-443 port). Rejected before any DB read so an attacker
    # endpoint never probes ownership (404) vs validation (422).
    if not is_allowed_push_endpoint(payload.endpoint):
        raise HTTPException(422, "Push endpoint not allowed")
    try:
        existing = (
            db.query(PushSubscription)
            .filter(PushSubscription.endpoint == payload.endpoint)
            .first()
        )
    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass
        logger.error(
            "push subscription fetch failed for user %s (%s)",
            user.id,
            type(exc).__name__,
        )
        raise HTTPException(500, "Push subscription unavailable")
    if existing is not None and existing.user_id != user.id:
        raise HTTPException(404, "Push subscription not found")
    label = (payload.device_label or "").strip()[:100] or None
    if existing is None:
        row = PushSubscription(
            user_id=user.id,
            endpoint=payload.endpoint,
            p256dh=payload.keys.p256dh,
            auth=payload.keys.auth,
            device_label=label,
        )
        db.add(row)
        try:
            db.flush()
            # Bounded per-user devices: evict oldest first on overflow.
            overflow_ids = [
                row_id
                for (row_id,) in db.query(PushSubscription.id)
                .filter(PushSubscription.user_id == user.id)
                .order_by(PushSubscription.id.desc())
                .offset(MAX_SUBSCRIPTIONS_PER_USER)
                .limit(100)
                .all()
            ]
            if overflow_ids:
                db.query(PushSubscription).filter(
                    PushSubscription.id.in_(overflow_ids)
                ).delete(synchronize_session=False)
            db.commit()
            db.refresh(row)
        except IntegrityError as exc:
            # Concurrent insert of the same endpoint won the race: roll
            # back (session saine, cf. pattern PR1) and fall through to
            # the update path on the winner row.
            try:
                db.rollback()
            except Exception:
                pass
            logger.warning(
                "push subscription race for user %s (%s)",
                user.id,
                type(exc).__name__,
            )
            try:
                winner = (
                    db.query(PushSubscription)
                    .filter(PushSubscription.endpoint == payload.endpoint)
                    .first()
                )
            except Exception as exc2:
                try:
                    db.rollback()
                except Exception:
                    pass
                logger.error(
                    "push subscription race re-read failed for user %s (%s)",
                    user.id,
                    type(exc2).__name__,
                )
                raise HTTPException(500, "Push subscription unavailable")
            if winner is None:
                # Winner vanished concurrently (delete raced insert):
                # retry the insert once, then give up with sanitized 500.
                retry = PushSubscription(
                    user_id=user.id,
                    endpoint=payload.endpoint,
                    p256dh=payload.keys.p256dh,
                    auth=payload.keys.auth,
                    device_label=label,
                )
                db.add(retry)
                try:
                    db.commit()
                    db.refresh(retry)
                except Exception as exc3:
                    try:
                        db.rollback()
                    except Exception:
                        pass
                    logger.error(
                        "push subscription retry failed for user %s (%s)",
                        user.id,
                        type(exc3).__name__,
                    )
                    raise HTTPException(500, "Push subscription unavailable")
                row = retry
            elif winner.user_id != user.id:
                raise HTTPException(404, "Push subscription not found")
            else:
                winner.p256dh = payload.keys.p256dh
                winner.auth = payload.keys.auth
                winner.device_label = label
                try:
                    db.commit()
                    db.refresh(winner)
                except Exception as exc3:
                    try:
                        db.rollback()
                    except Exception:
                        pass
                    logger.error(
                        "push subscription race update failed for user %s (%s)",
                        user.id,
                        type(exc3).__name__,
                    )
                    raise HTTPException(500, "Push subscription unavailable")
                row = winner
        except Exception as exc:
            # Non-IntegrityError path (flush/evict/commit/refresh): never
            # interpolate the exception or use exc_info — the message and
            # traceback embed bound params (endpoint + p256dh/auth keys).
            try:
                db.rollback()
            except Exception:
                pass
            logger.error(
                "push subscription save failed for user %s (%s)",
                user.id,
                type(exc).__name__,
            )
            raise HTTPException(500, "Push subscription unavailable")
    else:
        existing.p256dh = payload.keys.p256dh
        existing.auth = payload.keys.auth
        existing.device_label = label
        try:
            db.commit()
            db.refresh(existing)
        except Exception as exc:
            try:
                db.rollback()
            except Exception:
                pass
            logger.error(
                "push subscription update failed for user %s (%s)",
                user.id,
                type(exc).__name__,
            )
            raise HTTPException(500, "Push subscription unavailable")
        row = existing
    return {"endpoint": row.endpoint, "device_label": row.device_label}


@router.delete("/push-subscriptions")
def delete_push_subscription(
    payload: PushSubscriptionDelete,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove one device endpoint iff it belongs to the caller (else 404)."""
    try:
        row = (
            db.query(PushSubscription)
            .filter(
                PushSubscription.endpoint == payload.endpoint,
                PushSubscription.user_id == user.id,
            )
            .first()
        )
    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass
        logger.error(
            "push subscription fetch failed for user %s (%s)",
            user.id,
            type(exc).__name__,
        )
        raise HTTPException(500, "Push subscription unavailable")
    if row is None:
        raise HTTPException(404, "Push subscription not found")
    try:
        db.delete(row)
        db.commit()
    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass
        logger.error(
            "push subscription delete failed for user %s (%s)",
            user.id,
            type(exc).__name__,
        )
        raise HTTPException(500, "Push subscription unavailable")
    return {"deleted": True}
