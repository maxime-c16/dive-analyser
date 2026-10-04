"""Normalized diver directory and explicit aliases."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models.diver import Diver, DiverAlias
from app.security import verify_api_key
from app.services.diver_identity import canonicalize_name, display_name, invalidate_analysis_cache

router = APIRouter(prefix="/divers", tags=["divers"])


class DiverUpdate(BaseModel):
    display_name: str | None = Field(None, min_length=1, max_length=100)
    is_primary_user: bool | None = None
    active: bool | None = None


class AliasCreate(BaseModel):
    alias: str = Field(..., min_length=1, max_length=100)
    source: str = Field("manual", max_length=30)


def _serialize(diver: Diver) -> dict:
    return {
        "id": diver.id, "display_name": diver.display_name, "canonical_name": diver.canonical_name,
        "is_primary_user": diver.is_primary_user, "active": diver.active,
        "aliases": [{"id": alias.id, "alias": alias.alias, "source": alias.source} for alias in diver.aliases],
    }


@router.get("")
async def list_divers(active_only: bool = True, db: Session = Depends(get_db)):
    stmt = select(Diver).options(selectinload(Diver.aliases)).order_by(Diver.is_primary_user.desc(), Diver.display_name)
    if active_only:
        stmt = stmt.where(Diver.active.is_(True))
    return [_serialize(diver) for diver in db.execute(stmt).scalars().all()]


@router.put("/{diver_id}")
async def update_diver(diver_id: int, request: DiverUpdate, db: Session = Depends(get_db), _: dict = Depends(verify_api_key)):
    diver = db.get(Diver, diver_id)
    if not diver:
        raise HTTPException(status_code=404, detail="Diver not found")
    if request.display_name is not None:
        canonical = canonicalize_name(request.display_name)
        conflict = db.execute(select(Diver).where(Diver.canonical_name == canonical, Diver.id != diver.id)).scalar_one_or_none()
        if conflict:
            raise HTTPException(status_code=409, detail="Canonical diver name already exists")
        diver.display_name = display_name(request.display_name)
        diver.canonical_name = canonical
    if request.is_primary_user is not None:
        if request.is_primary_user:
            for existing in db.execute(select(Diver).where(Diver.is_primary_user.is_(True), Diver.id != diver.id)).scalars():
                existing.is_primary_user = False
        diver.is_primary_user = request.is_primary_user
    if request.active is not None:
        diver.active = request.active
    diver.updated_at = datetime.utcnow()
    invalidate_analysis_cache(db)
    db.commit()
    db.refresh(diver)
    return _serialize(diver)


@router.post("/{diver_id}/aliases", status_code=status.HTTP_201_CREATED)
async def add_alias(diver_id: int, request: AliasCreate, db: Session = Depends(get_db), _: dict = Depends(verify_api_key)):
    diver = db.get(Diver, diver_id)
    if not diver:
        raise HTTPException(status_code=404, detail="Diver not found")
    canonical = canonicalize_name(request.alias)
    if db.execute(select(DiverAlias).where(DiverAlias.canonical_alias == canonical)).scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Alias already exists")
    alias = DiverAlias(diver_id=diver.id, alias=display_name(request.alias), canonical_alias=canonical, source=request.source)
    db.add(alias)
    invalidate_analysis_cache(db)
    db.commit()
    db.refresh(alias)
    return {"id": alias.id, "diver_id": diver.id, "alias": alias.alias, "source": alias.source}
