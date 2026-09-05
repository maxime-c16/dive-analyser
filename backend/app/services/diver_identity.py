"""Safe exact-match diver normalization used by sync and backfills."""

import re

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.cache import AnalyticsCache
from app.models.diver import Diver, DiverAlias


def canonicalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


def display_name(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def get_primary_diver(db: Session) -> Diver:
    diver = db.execute(select(Diver).where(Diver.is_primary_user.is_(True)).order_by(Diver.id)).scalars().first()
    if diver:
        return diver
    configured = display_name(get_settings().primary_diver_name) or "Primary diver"
    diver = Diver(display_name=configured, canonical_name=canonicalize_name(configured), is_primary_user=True)
    db.add(diver)
    db.flush()
    return diver


def resolve_diver(db: Session, person_name: str | None, *, create: bool = True) -> Diver | None:
    if not person_name or not person_name.strip():
        return get_primary_diver(db)
    canonical = canonicalize_name(person_name)
    diver = db.execute(
        select(Diver)
        .outerjoin(DiverAlias, DiverAlias.diver_id == Diver.id)
        .where(or_(Diver.canonical_name == canonical, DiverAlias.canonical_alias == canonical))
    ).scalars().first()
    if diver or not create:
        return diver
    diver = Diver(display_name=display_name(person_name), canonical_name=canonical)
    db.add(diver)
    db.flush()
    return diver


def invalidate_analysis_cache(db: Session) -> None:
    db.execute(delete(AnalyticsCache).where(AnalyticsCache.cache_key.like("dive-analysis:v2:%")))
