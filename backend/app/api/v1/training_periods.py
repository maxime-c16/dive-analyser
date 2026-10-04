"""Training period CRUD with overlap-preserving date semantics."""

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.training_period import TrainingPeriod
from app.security import verify_api_key
from app.services.diver_identity import invalidate_analysis_cache

router = APIRouter(prefix="/training-periods", tags=["training-periods"])
PERIOD_TYPES = {"season", "training_block", "competition_preparation", "return_to_training", "custom"}


class TrainingPeriodInput(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    period_type: str = Field("custom", max_length=40)
    start_date: date
    end_date: date
    description: str | None = None
    active: bool = True

    @model_validator(mode="after")
    def validate_period(self):
        if self.period_type not in PERIOD_TYPES:
            raise ValueError("Unsupported training period type")
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


def _serialize(period: TrainingPeriod) -> dict:
    return {"id": period.id, "name": period.name, "period_type": period.period_type, "start_date": period.start_date, "end_date": period.end_date, "description": period.description, "active": period.active}


@router.get("")
async def list_training_periods(active_only: bool = True, db: Session = Depends(get_db)):
    stmt = select(TrainingPeriod).order_by(TrainingPeriod.start_date.desc(), TrainingPeriod.id.desc())
    if active_only:
        stmt = stmt.where(TrainingPeriod.active.is_(True))
    return [_serialize(period) for period in db.execute(stmt).scalars().all()]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_training_period(request: TrainingPeriodInput, db: Session = Depends(get_db), _: dict = Depends(verify_api_key)):
    period = TrainingPeriod(**request.model_dump())
    db.add(period)
    invalidate_analysis_cache(db)
    db.commit()
    db.refresh(period)
    return _serialize(period)


@router.put("/{period_id}")
async def update_training_period(period_id: int, request: TrainingPeriodInput, db: Session = Depends(get_db), _: dict = Depends(verify_api_key)):
    period = db.get(TrainingPeriod, period_id)
    if not period:
        raise HTTPException(status_code=404, detail="Training period not found")
    for field, value in request.model_dump().items():
        setattr(period, field, value)
    period.updated_at = datetime.utcnow()
    invalidate_analysis_cache(db)
    db.commit()
    db.refresh(period)
    return _serialize(period)


@router.delete("/{period_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_training_period(period_id: int, db: Session = Depends(get_db), _: dict = Depends(verify_api_key)):
    period = db.get(TrainingPeriod, period_id)
    if not period:
        raise HTTPException(status_code=404, detail="Training period not found")
    db.delete(period)
    invalidate_analysis_cache(db)
    db.commit()
    return None
