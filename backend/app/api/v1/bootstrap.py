"""One round trip for everything the app shell reads when a session starts.

Opening the app used to fire /auth/me plus four shell reads at once (message
badge, notification bell, achievement toaster, release notes). On a single
worker those requests queue behind each other, and each pays its own session
lookup and connection checkout. This endpoint resolves the session once and
returns the same payloads the individual routes return, so the client seeds
each widget from it and keeps the existing routes for polling.

A failing section is omitted rather than failing the whole response: the
client then falls back to that widget's own request.
"""
import logging

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.v1 import achievements, auth, messages, notifications, updates
from app.database import get_db
from app.models.user_auth import AppUser

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/bootstrap")
def bootstrap(
    response: Response,
    user: AppUser = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    payload = {"me": auth.me(response, user, db)}
    sections = {
        "messages_unread": lambda: messages.unread_count(user=user, db=db),
        "notifications": lambda: notifications.list_notifications(
            unread_only=False, limit=50, before_id=None, user=user, db=db
        ),
        "achievements_unseen": lambda: achievements.my_unseen_achievements(response, user, db),
        "updates": lambda: updates.read_updates(bool(user.is_admin)),
    }
    for name, read in sections.items():
        try:
            payload[name] = read()
        except Exception:
            logger.exception("bootstrap section %s failed", name)
            try:
                db.rollback()
            except Exception:
                pass
    # auth.me already applied the private, no-store headers.
    return payload
