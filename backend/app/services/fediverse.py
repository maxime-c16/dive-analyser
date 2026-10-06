"""Shared fediverse opt-in helpers (Option 1: manual cross-post only).

The dives table is never altered, so dive reads must keep working before
``add_fediverse_optin.sql`` is applied (the repo applies SQL migrations by
hand after deploy). Every helper therefore treats missing fediverse tables
as "everything OFF" for reads, and writes fail closed with 503 so the UI
can report "migration pending" instead of 500ing dive endpoints.
"""
from fastapi import HTTPException
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.models.fediverse import DiveFediverseOptin, UserFediversePrefs

PREFS_TABLE = UserFediversePrefs.__tablename__
OPTINS_TABLE = DiveFediverseOptin.__tablename__


def _existing_tables(db: Session) -> set[str]:
    try:
        names = set(inspect(db.get_bind()).get_table_names())
    except Exception:
        return set()
    return names


def global_enabled(db: Session, user_id: int) -> bool:
    if PREFS_TABLE not in _existing_tables(db):
        return False
    row = db.get(UserFediversePrefs, user_id)
    return bool(row.enabled) if row else False


def per_dive_enabled(db: Session, dive_id: int) -> bool:
    if OPTINS_TABLE not in _existing_tables(db):
        return False
    row = db.get(DiveFediverseOptin, dive_id)
    return bool(row.enabled) if row else False


def optin_map(db: Session, dive_ids: list[int]) -> set[int]:
    """Batch opt-in lookup for list serialization (one query, not N+1)."""
    ids = {int(i) for i in dive_ids}
    if not ids or OPTINS_TABLE not in _existing_tables(db):
        return set()
    rows = (
        db.query(DiveFediverseOptin.dive_id)
        .filter(
            DiveFediverseOptin.dive_id.in_(ids),
            DiveFediverseOptin.enabled.is_(True),
        )
        .all()
    )
    return {row[0] for row in rows}


def set_global_enabled(db: Session, user_id: int, enabled: bool) -> bool:
    if PREFS_TABLE not in _existing_tables(db):
        raise HTTPException(503, "Fediverse migration pending")
    row = db.get(UserFediversePrefs, user_id)
    if row is None:
        row = UserFediversePrefs(user_id=user_id, enabled=enabled)
        db.add(row)
    else:
        row.enabled = enabled
    db.commit()
    return bool(enabled)


def set_per_dive_enabled(db: Session, dive_id: int, enabled: bool) -> bool:
    if OPTINS_TABLE not in _existing_tables(db):
        raise HTTPException(503, "Fediverse migration pending")
    row = db.get(DiveFediverseOptin, dive_id)
    if enabled:
        if row is None:
            row = DiveFediverseOptin(dive_id=dive_id, enabled=True)
            db.add(row)
        else:
            row.enabled = True
    elif row is not None:
        db.delete(row)
    db.commit()
    return bool(enabled)
