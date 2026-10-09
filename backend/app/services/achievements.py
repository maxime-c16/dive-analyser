"""Member achievements (profile photo, first comment, ...).

Rules are evaluated from the live tables after the member's action, never
from a client claim, so the ledger can only contain things that really
happened. Every rule is a monotonic count compared with a target, which gives
progress bars for free and makes evaluation idempotent: re-running it can only
add missing unlocks, never remove one (a deleted comment does not revoke
"First comment").

Display text lives in the frontend locales (achievements.items.<key>); the
backend only owns keys, categories and targets. Delivery is the in-app toast
(GET /users/me/achievements/unseen), not the notification inbox, so a like or
comment still emits no inbox row for the dive owner.

Call sites use `award(...)`: it never raises and never leaves the caller's
session in a failed state, because the triggering action is already committed.
"""
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Dict, Iterable, List, Optional

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.achievement import UserAchievement
from app.models.dive import Dive
from app.models.direct_message import DirectMessage
from app.models.dive_share import DiveGuestLike, DiveShare
from app.models.dive_social import DiveComment, DiveLike
from app.models.evaluation import EvaluationRating, EvaluationRequest
from app.models.user_auth import AppUser
from app.services.dive_access import owned_diver_ids

logger = logging.getLogger(__name__)

# Action families that can unlock something. A hook only evaluates the rules
# listening to its trigger.
PROFILE = "profile"
LIKE = "like"
COMMENT = "comment"
MESSAGE = "message"
RATING = "rating"
SHARE = "share"
EVALUATION_REQUEST = "evaluation_request"

_MENTION_SCAN_LIMIT = 200


@dataclass(frozen=True)
class Rule:
    key: str
    category: str  # profile | community | jury | dives
    trigger: str
    target: int
    count: Callable[[Session, int], int]


def _profile_flags(db: Session, uid: int) -> tuple:
    row = db.query(AppUser.avatar_updated_at, AppUser.bio, AppUser.handle).filter(AppUser.id == uid).first()
    if row is None:
        return (False, False, False)
    return (row[0] is not None, bool((row[1] or "").strip()), bool(row[2]))


def _count(db: Session, column, *criteria) -> int:
    return int(db.query(func.count(column)).filter(*criteria).scalar() or 0)


def _comments_by(db: Session, uid: int, *, replies: Optional[bool] = None) -> int:
    criteria = [DiveComment.user_id == uid]
    if replies is True:
        criteria.append(DiveComment.parent_id.is_not(None))
    elif replies is False:
        criteria.append(DiveComment.parent_id.is_(None))
    return _count(db, DiveComment.id, *criteria)


def _has_mentioned(db: Session, uid: int) -> int:
    # JSON emptiness is not portable across SQLite/Postgres: scan a bounded
    # window of the member's latest comments and messages instead.
    for model in (DiveComment, DirectMessage):
        owner = DiveComment.user_id if model is DiveComment else DirectMessage.sender_id
        rows = (
            db.query(model.mentions).filter(owner == uid)
            .order_by(model.id.desc()).limit(_MENTION_SCAN_LIMIT).all()
        )
        if any(row[0] for row in rows):
            return 1
    return 0


def _likes_received(db: Session, uid: int) -> int:
    diver_ids = owned_diver_ids(db, uid)
    if not diver_ids:
        return 0
    member = _count(
        db, DiveLike.user_id,
        DiveLike.dive_id.in_(db.query(Dive.id).filter(Dive.diver_id.in_(diver_ids))),
        DiveLike.user_id != uid,
    )
    guests = _count(
        db, DiveGuestLike.guest_id,
        DiveGuestLike.dive_id.in_(db.query(Dive.id).filter(Dive.diver_id.in_(diver_ids))),
    )
    return member + guests


def _comments_received(db: Session, uid: int) -> int:
    diver_ids = owned_diver_ids(db, uid)
    if not diver_ids:
        return 0
    return _count(
        db, DiveComment.id,
        DiveComment.dive_id.in_(db.query(Dive.id).filter(Dive.diver_id.in_(diver_ids))),
        (DiveComment.user_id.is_(None)) | (DiveComment.user_id != uid),
    )


RULES: List[Rule] = [
    Rule("profile_photo", "profile", PROFILE, 1, lambda db, uid: int(_profile_flags(db, uid)[0])),
    Rule("profile_handle", "profile", PROFILE, 1, lambda db, uid: int(_profile_flags(db, uid)[2])),
    Rule("profile_bio", "profile", PROFILE, 1, lambda db, uid: int(_profile_flags(db, uid)[1])),
    Rule("profile_complete", "profile", PROFILE, 3, lambda db, uid: sum(_profile_flags(db, uid))),
    Rule("first_like", "community", LIKE, 1, lambda db, uid: _count(db, DiveLike.dive_id, DiveLike.user_id == uid)),
    Rule("likes_25", "community", LIKE, 25, lambda db, uid: _count(db, DiveLike.dive_id, DiveLike.user_id == uid)),
    Rule("first_comment", "community", COMMENT, 1, lambda db, uid: _comments_by(db, uid, replies=False)),
    Rule("first_reply", "community", COMMENT, 1, lambda db, uid: _comments_by(db, uid, replies=True)),
    Rule("comments_10", "community", COMMENT, 10, lambda db, uid: _comments_by(db, uid)),
    Rule("first_mention", "community", COMMENT, 1, _has_mentioned),
    Rule("first_message", "community", MESSAGE, 1, lambda db, uid: _count(db, DirectMessage.id, DirectMessage.sender_id == uid)),
    Rule("first_like_received", "community", LIKE, 1, _likes_received),
    Rule("first_comment_received", "community", COMMENT, 1, _comments_received),
    Rule("first_rating", "jury", RATING, 1, lambda db, uid: _count(db, EvaluationRating.id, EvaluationRating.evaluator_user_id == uid)),
    Rule("ratings_10", "jury", RATING, 10, lambda db, uid: _count(db, EvaluationRating.id, EvaluationRating.evaluator_user_id == uid)),
    Rule("first_evaluation_request", "jury", EVALUATION_REQUEST, 1, lambda db, uid: _count(db, EvaluationRequest.id, EvaluationRequest.created_by_user_id == uid)),
    Rule("first_share", "dives", SHARE, 1, lambda db, uid: _count(db, DiveShare.id, DiveShare.created_by == uid)),
]

RULES_BY_KEY: Dict[str, Rule] = {rule.key: rule for rule in RULES}

def unlocked_rows(db: Session, user_id: int) -> Dict[str, UserAchievement]:
    return {row.key: row for row in db.query(UserAchievement).filter_by(user_id=user_id).all()}


def evaluate(db: Session, user_id: int, triggers: Optional[Iterable[str]] = None) -> List[str]:
    """Unlock every rule whose target is reached; return the new keys.

    `triggers=None` evaluates the whole catalogue (profile page, backfill).
    """
    wanted = None if triggers is None else set(triggers)
    unlocked = set(unlocked_rows(db, user_id))
    new_keys: List[str] = []
    for rule in RULES:
        if rule.key in unlocked or (wanted is not None and rule.trigger not in wanted):
            continue
        if rule.count(db, user_id) >= rule.target:
            new_keys.append(rule.key)
    for key in new_keys:
        db.add(UserAchievement(user_id=user_id, key=key, unlocked_at=datetime.utcnow()))
    if not new_keys:
        return []
    try:
        db.commit()
    except IntegrityError:
        # A concurrent request unlocked the same key; keep what is stored.
        db.rollback()
        stored = set(unlocked_rows(db, user_id))
        new_keys = [key for key in new_keys if key in stored]
        return []
    return new_keys


def award(db: Session, user_id: Optional[int], *triggers: str) -> List[str]:
    """Best-effort evaluate after a committed action. Never raises.

    No trigger means the whole catalogue (backfill).
    """
    if user_id is None:
        return []
    try:
        return evaluate(db, user_id, triggers or None)
    except Exception:
        logger.exception("achievement evaluation failed for user %s", user_id)
        try:
            db.rollback()
        except Exception:
            pass
        return []


def award_dive_owners(db: Session, dive_id: int, exclude_user_id: Optional[int], *triggers: str) -> None:
    """Evaluate the members who own the dive's diver (likes/comments received)."""
    try:
        from app.models.user_auth import UserDiverAccess

        diver_id = db.query(Dive.diver_id).filter(Dive.id == dive_id).scalar()
        if diver_id is None:
            return
        owners = [
            uid for (uid,) in db.query(UserDiverAccess.user_id).filter(
                UserDiverAccess.diver_id == diver_id, UserDiverAccess.access_kind == "OWNER"
            ).all()
            if uid != exclude_user_id
        ]
    except Exception:
        logger.exception("achievement owner lookup failed for dive %s", dive_id)
        try:
            db.rollback()
        except Exception:
            pass
        return
    for uid in owners:
        award(db, uid, *triggers)


def catalog_for(db: Session, user_id: int, *, include_progress: bool = True) -> List[dict]:
    """Full catalogue with the member's unlock state (and progress when asked)."""
    rows = unlocked_rows(db, user_id)
    items = []
    for rule in RULES:
        row = rows.get(rule.key)
        item = dict(
            key=rule.key,
            category=rule.category,
            unlocked=row is not None,
            unlocked_at=row.unlocked_at.isoformat() if row else None,
            seen=bool(row and row.seen_at),
            target=rule.target,
        )
        if include_progress:
            item["progress"] = rule.target if row else min(rule.count(db, user_id), rule.target)
        items.append(item)
    return items
