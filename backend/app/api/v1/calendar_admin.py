"""Club preparation for app administrators, including while calendars are off.

This router deliberately lives outside /calendar. It never relaxes member APIs.
Imports can only read operator-staged bundles beneath a private root, never a
browser-supplied server path or URL. Preview hashes are rechecked by apply.
"""
import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, inspect, or_
from sqlalchemy.orm import Session

from app.api.v1.admin_users import require_admin
from app.api.v1.calendar import (admin_writer, club_out, commit, group_out, membership_out, private_responses)
from app.database import get_db
from app.models.calendar import (Calendar, CalendarEvent, CalendarLaunchControl, Club, ClubMembership,
                                EventOccurrence, TrainingGroup, TrainingGroupMembership)
from app.models.user_auth import AppUser
from app.schemas import calendar as s
from app.services import calendar_access as access, calendar_alerts as alerts
from app.services import calendar_import as importer, calendar_launch as launch, calendar_membership as membership
from app.models.security_audit_log import SecurityAuditEvent


def schema(db: Session = Depends(get_db)):
    if not launch.installed(db) or not inspect(db.connection()).has_table("calendar_alert_deliveries"):
        raise HTTPException(503, "Club administration migration is not installed")


router = APIRouter(prefix="/admin/clubs", dependencies=[Depends(require_admin), Depends(schema), Depends(private_responses)])


def audit(db, actor, action, **metadata):
    db.add(SecurityAuditEvent(event_type="club_administration", actor_context="admin-ui",
                             actor_note=str(actor.id), metadata_json=json.dumps({"action": action, **metadata})))


def club(db, club_id):
    c = db.query(Club).filter(Club.id == club_id, Club.archived_at.is_(None)).one_or_none()
    if c is None:
        raise HTTPException(404, "Club not found")
    return c


def readiness(db, club_id):
    club(db, club_id)
    active = (ClubMembership.club_id == club_id, ClubMembership.ended_at.is_(None), AppUser.is_active.is_(True))
    manager_count = db.query(ClubMembership).join(AppUser, AppUser.id == ClubMembership.user_id).filter(*active, ClubMembership.role == "manager").count()
    current = db.query(TrainingGroupMembership.user_id).filter(
        TrainingGroupMembership.club_id == club_id, TrainingGroupMembership.effective_from <= access.today(),
        or_(TrainingGroupMembership.effective_to.is_(None), TrainingGroupMembership.effective_to > access.today()))
    unassigned = db.query(ClubMembership).join(AppUser, AppUser.id == ClubMembership.user_id).filter(
        *active, ClubMembership.role == "member", ~ClubMembership.user_id.in_(current)).count()
    groups = db.query(TrainingGroup).filter_by(club_id=club_id, archived_at=None).count()
    occurrences = db.query(EventOccurrence).join(CalendarEvent).join(Calendar).filter(
        Calendar.club_id == club_id, CalendarEvent.status == "published", EventOccurrence.status == "scheduled").count()
    state = db.get(CalendarLaunchControl, 1)
    worker = alerts.health(db)
    problems = []
    if not manager_count:
        problems.append("manager_missing")
    if not groups:
        problems.append("groups_missing")
    if unassigned:
        problems.append("members_unassigned")
    if not occurrences:
        problems.append("events_missing")
    if not launch.probe_ready(state):
        problems.append("scheduled_checks_missing")
    problems += [p for p in worker["problems"] if p not in (
        "feature_disabled", "worker_never_succeeded", "worker_stale")]
    return dict(managers=manager_count, groups=groups, unassigned_members=unassigned,
                occurrences=occurrences, scheduled_checks=state.probe_count if state else 0,
                last_check_at=state.last_probe_at if state else None,
                worker_ready=worker["ready"], problems=problems)


@router.get("")
def list_clubs(after: int = Query(0, ge=0), db: Session = Depends(get_db)):
    rows = db.query(Club).filter(Club.archived_at.is_(None), Club.id > after).order_by(Club.id).limit(51).all()
    return {"items": [club_out(c) for c in rows[:50]], "next_cursor": rows[49].id if len(rows) > 50 else None,
            "calendar_enabled": launch.enabled(db)}


@router.post("", status_code=201)
def create_club(payload: s.ClubCreate, actor=Depends(admin_writer), db: Session = Depends(get_db)):
    c = membership.create_club(db, actor, **payload.model_dump())
    audit(db, actor, "create_club", club_id=c.id)
    commit(db)
    return club_out(c)


@router.get("/{club_id}")
def detail(club_id: int, after: int = Query(0, ge=0), db: Session = Depends(get_db)):
    c = club(db, club_id)
    groups = db.query(TrainingGroup).filter_by(club_id=club_id, archived_at=None).order_by(TrainingGroup.id).limit(500).all()
    rows = db.query(ClubMembership, AppUser).join(AppUser, AppUser.id == ClubMembership.user_id).filter(
        ClubMembership.club_id == club_id, ClubMembership.ended_at.is_(None), ClubMembership.id > after,
        AppUser.is_active.is_(True)).order_by(ClubMembership.id).limit(101).all()
    page = rows[:100]
    assignments = {uid: {"group_id": gid, "effective_from": start} for uid, gid, start in db.query(
        TrainingGroupMembership.user_id, TrainingGroupMembership.group_id, TrainingGroupMembership.effective_from).filter(
        TrainingGroupMembership.club_id == club_id, TrainingGroupMembership.user_id.in_([u.id for _, u in page]),
        TrainingGroupMembership.effective_from <= access.today(),
        or_(TrainingGroupMembership.effective_to.is_(None), TrainingGroupMembership.effective_to > access.today())).limit(100)}
    return {"club": club_out(c), "groups": [group_out(g) for g in groups],
            "members": [{"membership": membership_out(m), "display_name": u.display_name,
                         "email": u.email, "assignment": assignments.get(u.id)} for m, u in page],
            "next_cursor": page[-1][0].id if len(rows) > 100 else None, "readiness": readiness(db, club_id),
            "calendar_enabled": launch.enabled(db)}


@router.post("/{club_id}/memberships", status_code=201)
def add_member(club_id: int, payload: s.AdminMembershipCreate, actor=Depends(admin_writer), db: Session = Depends(get_db)):
    m = membership.admin_add_membership(db, actor, club_id, payload.user_id, payload.role)
    audit(db, actor, "add_member", club_id=club_id, user_id=m.user_id, role=m.role)
    commit(db)
    return membership_out(m)


@router.get("/{club_id}/candidates")
def candidates(club_id: int, q: str = Query(..., min_length=1, max_length=160), db: Session = Depends(get_db)):
    club(db, club_id)
    value = q.strip()
    if not value:
        return {"items": []}
    value = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    existing = db.query(ClubMembership.user_id).filter(ClubMembership.club_id == club_id,
                                                      ClubMembership.ended_at.is_(None))
    rows = db.query(AppUser.id, AppUser.display_name, AppUser.email).filter(
        AppUser.is_active.is_(True), ~AppUser.id.in_(existing),
        or_(AppUser.display_name.ilike(f"%{value}%", escape="\\"), AppUser.email.ilike(f"%{value}%", escape="\\"))) \
        .order_by(AppUser.display_name, AppUser.id).limit(20).all()
    return {"items": [{"user_id": uid, "display_name": name, "email": email} for uid, name, email in rows]}


@router.patch("/{club_id}/memberships/{membership_id}")
def update_member(club_id: int, membership_id: int, payload: s.MembershipUpdate,
                  actor=Depends(admin_writer), db: Session = Depends(get_db)):
    m = membership.update_membership(db, actor, club_id, membership_id, **payload.model_dump(), admin_ui=True)
    audit(db, actor, "update_member", club_id=club_id, user_id=m.user_id, **payload.model_dump(exclude_none=True))
    commit(db)
    return membership_out(m)


@router.post("/{club_id}/memberships/{membership_id}/end")
def remove_member(club_id: int, membership_id: int, actor=Depends(admin_writer), db: Session = Depends(get_db)):
    m = membership.end_membership(db, actor, club_id, membership_id)
    audit(db, actor, "remove_member", club_id=club_id, user_id=m.user_id)
    commit(db)
    return membership_out(m)


@router.post("/{club_id}/groups", status_code=201)
def create_group(club_id: int, payload: s.GroupCreate, actor=Depends(admin_writer), db: Session = Depends(get_db)):
    g = membership.create_group(db, actor, club_id, **payload.model_dump())
    audit(db, actor, "create_group", club_id=club_id, group_id=g.id)
    commit(db)
    return group_out(g)


@router.put("/{club_id}/group-assignment")
def assign(club_id: int, payload: s.GroupAssignment, actor=Depends(admin_writer), db: Session = Depends(get_db)):
    membership.assign_group(db, actor, club_id, **payload.model_dump(), admin_ui=True)
    audit(db, actor, "assign_group", club_id=club_id, **payload.model_dump(mode="json"))
    commit(db)
    return {"saved": True}


class Activation(BaseModel):
    enabled: bool
    sources_reviewed: bool = False
    roles_reviewed: bool = False
    device_tested: bool = False
    retention_reviewed: bool = False
    timer_verified: bool = False


class BulkMembers(BaseModel):
    action: Literal["add", "role", "group", "remove"]
    # For add: app-user IDs. For all other actions: membership IDs, avoiding
    # changes to another season's or another club's membership by accident.
    ids: list[int] = Field(min_length=1, max_length=100)
    role: s.ClubRole = "member"
    group_id: int | None = Field(None, gt=0)
    effective_from: date | None = None
    can_publish: bool | None = None
    can_assign_groups: bool | None = None


@router.post("/{club_id}/members/bulk")
def bulk_members(club_id: int, payload: BulkMembers, actor=Depends(admin_writer), db: Session = Depends(get_db)):
    membership._usable_club(db, club_id)
    ids = sorted(set(payload.ids))
    if any(i <= 0 for i in ids) or len(ids) != len(payload.ids):
        raise HTTPException(422, "Choose distinct valid accounts or memberships")
    if payload.action == "add":
        for uid in ids:
            membership.admin_add_membership(db, actor, club_id, uid, payload.role)
    else:
        rows = db.query(ClubMembership).filter(ClubMembership.club_id == club_id,
            ClubMembership.id.in_(ids), ClubMembership.ended_at.is_(None)).order_by(ClubMembership.id).with_for_update().all()
        if len(rows) != len(ids):
            raise HTTPException(409, "The selection changed. Refresh members and select again.")
        for row in rows:
            if payload.action == "role":
                membership.update_membership(db, actor, club_id, row.id, payload.role,
                    payload.can_publish, payload.can_assign_groups, admin_ui=True)
            elif payload.action == "group":
                if payload.effective_from is None:
                    raise HTTPException(422, "Choose an effective date for this batch")
                membership.assign_group(db, actor, club_id, row.user_id, payload.group_id,
                                        payload.effective_from, admin_ui=True)
            else:
                membership.end_membership(db, actor, club_id, row.id)
    # A failure above rolls back every preceding mutation via get_db. No service
    # commits inside the loop; last-manager and cross-club rules still apply.
    audit(db, actor, "bulk_" + payload.action, club_id=club_id, count=len(ids),
          ids=ids, role=payload.role if payload.action in ("add", "role") else None,
          group_id=payload.group_id if payload.action == "group" else None)
    commit(db)
    return {"changed": len(ids)}


@router.put("/{club_id}/activation")
def activate(club_id: int, payload: Activation, actor=Depends(admin_writer), db: Session = Depends(get_db)):
    membership._usable_club(db, club_id)
    row = db.query(CalendarLaunchControl).filter_by(id=1).with_for_update().one_or_none()
    if row is None:
        row = CalendarLaunchControl(id=1)
        db.add(row)
        db.flush()
    checks = payload.model_dump(exclude={"enabled"})
    if payload.enabled:
        report = readiness(db, club_id)
        if report["problems"] or not all(checks.values()):
            raise HTTPException(409, detail={"code": "launch_not_ready", "problems": report["problems"],
                                             "message": "Complete the launch checks before enabling calendars"})
    row.enabled, row.changed_at, row.changed_by_user_id = payload.enabled, datetime.utcnow(), actor.id
    row.accepted_checks = checks
    audit(db, actor, "activate" if payload.enabled else "pause", club_id=club_id, checks=checks)
    commit(db)
    return {"enabled": row.enabled}


def private_root():
    # Dedicated private volume. Never store source attachments in media-cache,
    # which is served by nginx. Browser callers cannot override this path.
    return Path(os.environ.get("CALENDAR_PRIVATE_ROOT", "/app/calendar-private")).resolve()


def staged(bundle_id):
    if not bundle_id or len(bundle_id) > 64 or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-" for ch in bundle_id):
        raise HTTPException(422, "Invalid bundle identifier")
    folder = (private_root() / "inbox" / bundle_id).resolve()
    if not folder.is_relative_to(private_root() / "inbox") or not (folder / "bundle.json").is_file():
        raise HTTPException(404, "Prepared source bundle not found")
    # Resolve every source to the bundle's own sources directory before calling
    # the importer. No absolute paths from the source JSON are trusted here.
    path = (folder / "bundle.json").resolve()
    if not path.is_relative_to(folder) or path.stat().st_size > 5 * 1024 * 1024:
        raise HTTPException(422, "Invalid prepared source bundle")
    try:
        bundle = importer.load_bundle(path)
    except (ValueError, OSError):
        raise HTTPException(422, "Invalid prepared source bundle")
    if not isinstance(bundle.data, dict) or not isinstance(bundle.data.get("sources"), dict) or len(bundle.data["sources"]) > 10:
        raise HTTPException(422, "Invalid prepared source bundle")
    for source in bundle.data.get("sources", {}).values():
        if not isinstance(source, dict):
            raise HTTPException(422, "Invalid prepared source attachment")
        if not isinstance(source.get("file"), str):
            raise HTTPException(422, "Invalid prepared source attachment")
        filename = Path(source["file"]).name
        target = (folder / "sources" / filename).resolve()
        if not filename or not target.is_relative_to(folder) or not target.is_file() or target.stat().st_size > 25 * 1024 * 1024:
            raise HTTPException(422, "A prepared source attachment is missing")
        source["file"] = str(target)
    return bundle


@router.get("/{club_id}/imports")
def imports(club_id: int, db: Session = Depends(get_db)):
    club(db, club_id)
    root = private_root() / "inbox"
    # Bounded filesystem inventory; source content is only read on selection.
    from itertools import islice
    items = []
    if root.is_dir():
        for entry in islice(root.iterdir(), 100):
            if entry.is_dir() and (entry / "bundle.json").is_file() and entry.resolve().is_relative_to(root):
                items.append({"id": entry.name, "label": entry.name})
    return {"items": sorted(items, key=lambda i: i["id"])}


class ImportInput(BaseModel):
    bundle_id: str = Field(min_length=1, max_length=64)
    season_start: date
    groups: dict[str, int] = Field(min_length=1, max_length=50)
    plan_hash: str | None = Field(None, pattern=r"^[a-f0-9]{64}$")
    batch_id: str | None = Field(None, pattern=r"^[a-f0-9]{32}$")


@router.post("/{club_id}/imports/{action}")
def import_bundle(club_id: int, action: Literal["preview", "apply"], payload: ImportInput,
                  actor=Depends(admin_writer), db: Session = Depends(get_db)):
    c = club(db, club_id)
    bundle = staged(payload.bundle_id)
    for key in ("training_occurrences", "competition_candidates", "resources"):
        rows = bundle.data.get(key, [])
        if not isinstance(rows, list) or len(rows) > 2000 or any(not isinstance(row, dict) for row in rows):
            raise HTTPException(422, "Invalid or oversized prepared source bundle")
    ids = set(payload.groups.values())
    if len(ids) != len(payload.groups):
        raise HTTPException(422, "Choose a distinct target group for each source group")
    groups = db.query(TrainingGroup).filter(TrainingGroup.club_id == club_id, TrainingGroup.archived_at.is_(None),
                                          TrainingGroup.id.in_(ids)).limit(50).all()
    if {g.id for g in groups} != ids:
        raise HTTPException(422, "Choose groups belonging to this club")
    by_id = {g.id: g for g in groups}
    opts = importer.Options(club_slug=c.slug, groups={key: (by_id[gid].slug, by_id[gid].name)
                                                   for key, gid in payload.groups.items()}, season_start=payload.season_start)
    try:
        if action == "preview":
            result = importer.preview(db, bundle, opts, private_root() / "artifacts", actor)
            # Deliberately omit server paths and raw attachment/workbook cells.
            return {"batch_id": result["batch_id"], "plan_hash": result["plan_hash"], "summary": result["summary"],
                    "plan": {"training": result["plan"]["training"]}}
        if not payload.plan_hash or not payload.batch_id:
            raise HTTPException(422, "Preview this import before applying it")
        result = importer.apply(db, bundle, opts, private_root() / "artifacts", actor,
                                payload.plan_hash, payload.batch_id)
        audit(db, actor, "import_applied", club_id=club_id, batch_id=payload.batch_id)
        commit(db)
        return {"applied": True, "summary": result.get("summary", {})}
    except (importer.ImportError_, ValueError, KeyError, OSError):
        db.rollback()
        raise HTTPException(409, detail={"code": "import_refused", "message": "Source or club data changed or are invalid. Check the prepared bundle and preview again."})
