"""Account-owned series. Sharing grants the sheet, never private media."""
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import func, select, union_all
from sqlalchemy.orm import Session

from app.api.v1.auth import _origin_allowed, get_current_user
from app.database import get_db
from app.models.dive import Dive
from app.models.dive_series import DiveSeries
from app.models.evaluation import EvaluationRating, EvaluationRequest
from app.models.matchmaking import AutomaticRating
from app.models.user_auth import AppUser
from app.services.dive_access import owned_diver_ids
from app.services.world_aquatics_dd import OfficialDDUndefined, REFERENCE_LABEL, calculate_official_dd

from app.services.performance_scoring import recorded_score_10_expression

Height = Literal["1m", "3m", "5m", "7.5m", "10m"]


def private(response: Response):
    response.headers["Cache-Control"] = "private, no-store"


def writer(request: Request, user: AppUser = Depends(get_current_user)):
    if not _origin_allowed(request):
        raise HTTPException(403, "Origin not allowed")
    return user


router = APIRouter(prefix="/series", dependencies=[Depends(private)])


class Choice(BaseModel):
    code: str = Field(..., pattern=r"^[1-6][0-9]{2,3}[ABCD]$")
    clip_id: int | None = Field(None, gt=0)

    @field_validator("code", mode="before")
    @classmethod
    def clean_code(cls, value):
        return value.strip().upper() if isinstance(value, str) else value


class Slot(Choice):
    # Empty positions are deliberate draft placeholders; their order matters.
    code: str = Field("", pattern=r"^(?:[1-6][0-9]{2,3}[ABCD])?$")
    alternatives: list[Choice] = Field(default_factory=list, max_length=5)


class Sheet(BaseModel):
    title: str = Field(..., min_length=1, max_length=160)
    height: Height
    clip_policy: Literal["best", "recent"] = "best"
    event_id: int | None = Field(None, gt=0)
    slots: list[Slot] = Field(default_factory=lambda: [Slot() for _ in range(6)], max_length=20)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Title required")
        return value


class Update(Sheet):
    expected_version: int = Field(..., ge=1)


class Sharing(BaseModel):
    expected_version: int = Field(..., ge=1)
    user_ids: list[int] = Field(..., max_length=30)


def owned(db, user, series_id, lock=False):
    q = db.query(DiveSeries).filter(DiveSeries.id == series_id, DiveSeries.owner_user_id == user.id)
    row = (q.with_for_update() if lock else q).first()
    if row is None:
        raise HTTPException(404, "Series not found")
    return row


def current_version(row, expected):
    if row.version != expected:
        raise HTTPException(409, "Series changed; reload before saving")


def validate_event(db, user, event_id):
    if event_id is None:
        return
    from app.services.calendar_launch import enabled
    from app.services.calendar_access import visible_events
    from app.models.calendar import CalendarEvent
    if not enabled(db):
        raise HTTPException(404, "Competition unavailable")
    event = visible_events(db, user).filter(CalendarEvent.id == event_id).first()
    if event is None or event.event_type != "competition":
        raise HTTPException(404, "Competition unavailable")


def rating_totals():
    # Only ratings of the current code/height count, not stale snapshots.
    votes = union_all(
        select(EvaluationRequest.dive_id.label("dive_id"), EvaluationRating.score_half_steps.label("score"))
        .join(EvaluationRating, EvaluationRating.request_id == EvaluationRequest.id)
        .join(Dive, Dive.id == EvaluationRequest.dive_id)
        .where(EvaluationRating.dive_code == Dive.dive_code, EvaluationRating.height == Dive.height),
        select(AutomaticRating.dive_id, AutomaticRating.score_half_steps)
        .join(Dive, Dive.id == AutomaticRating.dive_id)
        .where(AutomaticRating.dive_code == Dive.dive_code, AutomaticRating.height == Dive.height,
               AutomaticRating.video_uuid == Dive.video_uuid),
    ).subquery()
    return select(votes.c.dive_id, func.avg(votes.c.score).label("mean"),
                  func.count().label("count")).group_by(votes.c.dive_id).subquery()


def clips(db, owner_id, code, height, limit=50, clip_id=None, policy="best"):
    owner_ids = owned_diver_ids(db, owner_id)
    if not owner_ids:
        return []
    totals = rating_totals()
    recorded = recorded_score_10_expression()
    rows = (db.query(Dive, totals.c.mean, totals.c.count, recorded.label("performance_score"))
            .outerjoin(totals, totals.c.dive_id == Dive.id)
            .filter(Dive.diver_id.in_(owner_ids),
                    Dive.dive_code == code, Dive.height == height, Dive.video_uuid.is_not(None))
            .filter(Dive.id == clip_id if clip_id is not None else True)
            .order_by(*([func.coalesce(totals.c.mean / 2.0, recorded).desc().nullslast()] if policy == "best" else []), Dive.dive_datetime.desc(), Dive.id.desc())
            .limit(limit).all())
    return [clip_payload(dive, mean, count, performance_score) for dive, mean, count, performance_score in rows]


def clip_payload(dive, mean, count, performance_score):
    return {"id": dive.id, "video_uuid": dive.video_uuid, "date": dive.dive_datetime, "mean_score": round(float(mean) / 2, 2) if mean is not None else None,
            "performance_score": round(float(performance_score), 2) if performance_score is not None else None,
            "rating_count": int(count or 0), "url": f"/dives?clip={dive.id}&scope=all"}


def validate_clips(db, user, payload):
    ids = owned_diver_ids(db, user.id)
    for slot in payload.slots:
        for choice in [slot, *slot.alternatives]:
            if choice.clip_id is not None:
                dive = db.query(Dive).filter(Dive.id == choice.clip_id, Dive.diver_id.in_(ids)).first()
                if (dive is None or dive.dive_code != choice.code or dive.height != payload.height
                        or not dive.video_uuid):
                    raise HTTPException(422, "Clip must belong to you and match the code and height")


def project(db, user, row, detail=True):
    own = row.owner_user_id == user.id
    result = {"id": row.id, "title": row.title, "height": row.height, "event_id": row.event_id,
              "clip_policy": row.clip_policy, "version": row.version, "can_edit": own, "updated_at": row.updated_at,
              "slot_count": sum(bool(s["code"]) for s in row.slots), "total_slots": len(row.slots),
              "shared_with": [], "slots": [],
              "dd_reference": REFERENCE_LABEL}
    if not detail:
        return result
    # Do not expose private calendar titles or recipients to shared-sheet readers.
    if not own:
        result["event_id"] = None
    else:
        result["shared_with"] = [{"id": u.id, "name": u.display_name} for u in
                                db.query(AppUser).filter(AppUser.id.in_(row.shared_with)).all()]
    cache = {}
    # Batch-fetch manually selected clips in one query instead of one per
    # choice. Stale selections (deleted, transferred, or code/height
    # mismatch) resolve to clip_id None so a reloaded sheet saves cleanly.
    selected_ids = set()
    for slot in row.slots:
        for choice in [slot, *slot.get("alternatives", [])]:
            if own and choice.get("code") and choice.get("clip_id"):
                selected_ids.add(choice["clip_id"])
    selected_map = {}
    if selected_ids:
        owner_ids = owned_diver_ids(db, row.owner_user_id)
        if owner_ids:
            totals = rating_totals()
            recorded = recorded_score_10_expression()
            for dive, mean, count, performance_score in (
                    db.query(Dive, totals.c.mean, totals.c.count, recorded.label("performance_score"))
                    .outerjoin(totals, totals.c.dive_id == Dive.id)
                    .filter(Dive.id.in_(selected_ids), Dive.diver_id.in_(owner_ids),
                            Dive.video_uuid.is_not(None)).all()):
                selected_map[dive.id] = (dive, clip_payload(dive, mean, count, performance_score))
    def choice_out(choice):
        code = choice["code"]
        try:
            dd = float(calculate_official_dd(code, row.height).dd)
        except OfficialDDUndefined:
            dd = None
        clip = None
        effective_clip_id = choice.get("clip_id") if own else None
        # Sheet sharing intentionally grants no new media rights. The owner
        # retains normal playback; collaborators see the technical sheet only.
        if own and code:
            if code not in cache:
                cache[code] = clips(db, row.owner_user_id, code, row.height, limit=1, policy=row.clip_policy)
            if effective_clip_id:
                entry = selected_map.get(effective_clip_id)
                if entry and entry[0].dive_code == code and entry[0].height == row.height:
                    clip = entry[1]
                else:
                    effective_clip_id = None
            elif cache[code]:
                clip = cache[code][0]
        elif own:
            effective_clip_id = None
        return {**choice, "clip_id": effective_clip_id, "dd": dd, "clip": clip}
    result["slots"] = [{**choice_out(slot), "alternatives": [choice_out(c) for c in slot.get("alternatives", [])]}
                       for slot in row.slots]
    return result


@router.get("")
def list_series(event_id: int | None = None, user=Depends(get_current_user), db: Session = Depends(get_db),
                limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    q = db.query(DiveSeries).filter(DiveSeries.owner_user_id == user.id)
    if event_id is not None:
        q = q.filter(DiveSeries.event_id == event_id)
    return [project(db, user, row, False) for row in q.order_by(DiveSeries.updated_at.desc(), DiveSeries.id.desc())
            .offset(offset).limit(limit).all()]


@router.get("/clips")
def candidate_clips(code: str, height: Height, policy: Literal["best", "recent"] = "best", user=Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        choice = Choice(code=code)
    except ValidationError:
        raise HTTPException(422, "Invalid dive code")
    return clips(db, user.id, choice.code, height, policy=policy)


@router.post("", status_code=201)
def create(payload: Sheet, user=Depends(writer), db: Session = Depends(get_db)):
    validate_event(db, user, payload.event_id)
    validate_clips(db, user, payload)
    row = DiveSeries(owner_user_id=user.id, **payload.model_dump())
    db.add(row)
    db.commit()
    return project(db, user, row)


@router.get("/{series_id}")
def get_series(series_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.get(DiveSeries, series_id)
    if row is None or (row.owner_user_id != user.id and user.id not in row.shared_with):
        raise HTTPException(404, "Series not found")
    return project(db, user, row)


@router.put("/{series_id}")
def update(series_id: int, payload: Update, user=Depends(writer), db: Session = Depends(get_db)):
    row = owned(db, user, series_id, lock=True)
    current_version(row, payload.expected_version)
    if payload.height != row.height:
        raise HTTPException(422, "Height is fixed for this series")
    if payload.event_id != row.event_id:
        validate_event(db, user, payload.event_id)
    validate_clips(db, user, payload)
    row.title, row.slots, row.event_id = payload.title, [s.model_dump() for s in payload.slots], payload.event_id
    row.clip_policy = payload.clip_policy
    row.version += 1
    row.updated_at = datetime.utcnow()
    db.commit()
    return project(db, user, row)


@router.put("/{series_id}/sharing")
def share(series_id: int, payload: Sharing, user=Depends(writer), db: Session = Depends(get_db)):
    row = owned(db, user, series_id, lock=True)
    current_version(row, payload.expected_version)
    ids = sorted(set(payload.user_ids) - {user.id})
    if db.query(AppUser).filter(AppUser.id.in_(ids), AppUser.is_active.is_(True)).count() != len(ids):
        raise HTTPException(422, "Member unavailable")
    row.shared_with = ids
    row.version += 1
    row.updated_at = datetime.utcnow()
    db.commit()
    return project(db, user, row)
