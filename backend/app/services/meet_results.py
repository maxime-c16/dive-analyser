"""Store and read official meet results for a competition calendar event.

Writers: `replace` and `delete` (under the calendar event's row lock and the
same publish permission as editing the event), and the administrator link
decisions `set_link` / `clear_link`. Imports and link decisions also share
one transaction lock (`meet_result_links.lock_links`). Readers see results exactly when they can see the event.
Reads are bounded by the import caps in meet_results_pdf (a fixed number of
queries, independent of row count).

Account links (services/meet_result_links) are made at import. A link is
shown only to the linked account itself and to viewers sharing an active club
with it: the sheet's full name tied to an app identity is club knowledge,
not something a community-wide event should reveal.
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.calendar import Calendar, CalendarEvent, ClubMembership, EventOccurrence
from app.models.diver import Diver
from app.models.meet_results import MeetPersonLink, MeetResult, MeetResultDive, MeetResultEntry, MeetResultEvent
from app.models.user_auth import AppUser, UserDiverAccess
from app.services import calendar_events as events
from app.services.calendar_events import fail
from app.services.meet_result_links import decisions, key_of, lock_links, resolve
from app.services.meet_results_pdf import ParsedMeet
from app.services.member_avatar import avatar_identity


def _require_competition(event: CalendarEvent) -> None:
    if event.event_type != "competition":
        fail(422, "not_competition", "Results can only be attached to a competition")


def can_import(db: Session, user: AppUser, event: CalendarEvent, calendar: Calendar) -> bool:
    return event.event_type == "competition" and events.can_edit(db, user, calendar)


def check_import(db: Session, user: AppUser, event_id: int) -> None:
    """Cheap authorization before an upload is read (re-checked under lock on write)."""
    event, calendar = events.visible_event(db, user, event_id)
    _require_competition(event)
    if not events.can_edit(db, user, calendar):
        fail(403, "forbidden", "Only the organizer or an authorized club publisher can change this event")
    db.rollback()


def date_matches(db: Session, event: CalendarEvent, meet_date: Optional[date]) -> Optional[bool]:
    """Whether the sheet's printed date is one of the event's local days.
    None when the sheet has no date."""
    if meet_date is None:
        return None
    rows = db.query(EventOccurrence).filter(EventOccurrence.event_id == event.id,
                                            EventOccurrence.status != "cancelled").limit(200).all()
    for o in rows:
        if o.is_all_day:
            first, last = o.start_date, o.end_date - timedelta(days=1)  # end date is exclusive
        else:
            first = events.utc_to_local(o.starts_at, event.timezone).date()
            last = events.utc_to_local(o.ends_at, event.timezone).date()
        if first <= meet_date <= last:
            return True
    return False


def preview(db: Session, user: AppUser, event_id: int, parsed: ParsedMeet) -> dict:
    # Read-only: same permission as saving, without the event row lock.
    event, calendar = events.visible_event(db, user, event_id)
    _require_competition(event)
    if not events.can_edit(db, user, calendar):
        fail(403, "forbidden", "Only the organizer or an authorized club publisher can change this event")
    replaces = db.query(MeetResult.id).filter(MeetResult.calendar_event_id == event.id).first() is not None
    # Count only links this importer could see on the page: a preview must not
    # reveal whether a hidden account matches a name on the sheet.
    linked = {uid for uid, _src in resolve(db, _flat(parsed)).values() if uid}
    out = {
        "meet_date": parsed.meet_date.isoformat() if parsed.meet_date else None,
        "date_matches": date_matches(db, event, parsed.meet_date),
        "events": [{"title": e.title, "board": e.board, "entries": len(e.entries)} for e in parsed.events],
        "entry_count": parsed.entry_count, "dive_count": parsed.dive_count,
        "warnings": parsed.warnings, "warnings_truncated": parsed.warnings_truncated, "replaces": replaces,
        "linked_count": len(_visible_accounts(db, user, linked)),
    }
    db.rollback()  # nothing was written
    return out


def _flat(parsed: ParsedMeet) -> list:
    return [en for e in parsed.events for en in e.entries]


def replace(db: Session, user: AppUser, event_id: int, parsed: ParsedMeet, source_name: str, raw: bytes) -> None:
    event, _calendar = events.editable_event(db, user, event_id)
    _require_competition(event)
    lock_links(db)
    # Bulk SQL delete: ON DELETE CASCADE removes the previous events/entries/dives.
    db.query(MeetResult).filter(MeetResult.calendar_event_id == event.id).delete(synchronize_session=False)
    result = MeetResult(calendar_event_id=event.id, source_name=source_name.strip()[:200] or "results.pdf",
                        source_sha256=hashlib.sha256(raw).hexdigest(), meet_date=parsed.meet_date,
                        imported_by_user_id=user.id)
    db.add(result)
    db.flush()
    rows = [MeetResultEvent(result_id=result.id, position=i, title=e.title, board=e.board)
            for i, e in enumerate(parsed.events)]
    db.add_all(rows)
    db.flush()
    links = resolve(db, _flat(parsed))
    entries = [(MeetResultEntry(event_id=row.id, position=j, rank=en.rank, diver_name=en.diver_name,
                                birth_year=en.birth_year, club_name=en.club_name, total=en.total,
                                status=en.status, guest=en.guest), en)
               for row, e in zip(rows, parsed.events) for j, en in enumerate(e.entries)]
    for i, (row, _en) in enumerate(entries):
        row.person_key = key_of(_en)
        row.user_id, row.link_source = links.get(i, (None, None))
    db.add_all([m for m, _ in entries])
    db.flush()
    db.add_all([MeetResultDive(entry_id=m.id, position=k, dive_code=d.dive_code, height=d.height, dd=d.dd,
                               judge_half_steps=d.judge_half_steps, cumul=d.cumul, points=d.points,
                               running_total=d.running_total, penalty=d.penalty)
                for m, en in entries for k, d in enumerate(en.dives)])


def delete(db: Session, user: AppUser, event_id: int) -> None:
    event, _calendar = events.editable_event(db, user, event_id)
    lock_links(db)  # never under an admin relink of the same rows
    if db.query(MeetResult).filter(MeetResult.calendar_event_id == event.id).delete(synchronize_session=False) == 0:
        fail(404, "results_not_found", "No results for this event")


def _num(value) -> Optional[float]:
    return None if value is None else float(value)


def _visible_accounts(db: Session, viewer: AppUser, user_ids: set[int]) -> dict[int, dict]:
    """Linked accounts the viewer may see: themselves, a shared active club,
    or any account for an administrator (who manages the links)."""
    if not user_ids:
        return {}
    if viewer.is_admin:
        rows = db.query(AppUser).filter(AppUser.id.in_(user_ids), AppUser.is_active.is_(True)).all()
        return {u.id: {"user_id": u.id, "display_name": u.display_name, **avatar_identity(u)} for u in rows}
    active = (ClubMembership.status == "active", ClubMembership.ended_at.is_(None))
    mine = {cid for (cid,) in db.query(ClubMembership.club_id).filter(ClubMembership.user_id == viewer.id, *active)}
    shared = {uid for (uid,) in db.query(ClubMembership.user_id).filter(
        ClubMembership.user_id.in_(user_ids), ClubMembership.club_id.in_(mine or {-1}), *active)}
    allowed = (shared | {viewer.id}) & user_ids
    rows = db.query(AppUser).filter(AppUser.id.in_(allowed), AppUser.is_active.is_(True)).all() if allowed else []
    return {u.id: {"user_id": u.id, "display_name": u.display_name, **avatar_identity(u)} for u in rows}


def read(db: Session, user: AppUser, event_id: int, summary: bool = False) -> dict:
    """`summary` answers only whether results exist (one indexed lookup)."""
    event, calendar = events.visible_event(db, user, event_id)
    out = {"can_import": can_import(db, user, event, calendar), "available": False, "results": None,
           "can_manage_links": bool(user.is_admin)}
    if summary:
        out["available"] = db.query(MeetResult.id).filter(MeetResult.calendar_event_id == event.id).first() is not None
        return out
    # One statement = one snapshot: a re-import committing mid-read can never
    # mix the old result with the new rows (or return an empty ranking).
    rows = db.query(MeetResult, MeetResultEvent, MeetResultEntry, MeetResultDive).outerjoin(
        MeetResultEvent, MeetResultEvent.result_id == MeetResult.id).outerjoin(
        MeetResultEntry, MeetResultEntry.event_id == MeetResultEvent.id).outerjoin(
        MeetResultDive, MeetResultDive.entry_id == MeetResultEntry.id).filter(
        MeetResult.calendar_event_id == event.id).order_by(
        MeetResultEvent.position, MeetResultEntry.position, MeetResultDive.position).all()
    if not rows:
        return out
    out["available"] = True
    result = rows[0][0]
    meet_events, entries, dives = {}, {}, []
    for _r, ev, en, d in rows:
        if ev is not None:
            meet_events.setdefault(ev.id, ev)
        if en is not None:
            entries.setdefault(en.id, en)
        if d is not None:
            dives.append(d)
    meet_events, entries = list(meet_events.values()), list(entries.values())
    dives_by_entry: dict[int, list] = {}
    for d in dives:
        dives_by_entry.setdefault(d.entry_id, []).append({
            "dive_code": d.dive_code, "height": _num(d.height), "dd": _num(d.dd),
            "judges": [h / 2 for h in d.judge_half_steps], "cumul": _num(d.cumul), "points": _num(d.points),
            "running_total": _num(d.running_total), "penalty": d.penalty})
    accounts = _visible_accounts(db, user, {en.user_id for en in entries if en.user_id})
    entries_by_event: dict[int, list] = {}
    for en in entries:
        entries_by_event.setdefault(en.event_id, []).append({
            "id": en.id, "rank": en.rank, "diver_name": en.diver_name, "birth_year": en.birth_year,
            "club_name": en.club_name, "total": _num(en.total), "status": en.status,
            "guest": en.guest, "is_me": en.user_id == user.id, "account": accounts.get(en.user_id),
            # Link bookkeeping is for administrators only.
            "link_source": en.link_source if user.is_admin else None,
            "account_inactive": bool(en.user_id and en.user_id not in accounts) if user.is_admin else None,
            "linkable": en.person_key is not None if user.is_admin else None,
            "dives": dives_by_entry.get(en.id, [])})
    out["results"] = {
        "source_name": result.source_name, "meet_date": result.meet_date.isoformat() if result.meet_date else None,
        "imported_at": result.imported_at.isoformat() + "Z",
        "events": [{"id": e.id, "title": e.title, "board": e.board, "entries": entries_by_event.get(e.id, [])}
                   for e in meet_events],
    }
    return out


# --- Administrator link management --------------------------------------------

RELINK_MEETS = 100     # meets considered per batch
RELINK_ROWS = 5000     # result rows loaded per batch (a meet has at most 2,000)


def relink_all(db: Session) -> None:
    """Recompute links in every meet: a decision changes who is in the
    automatic pool, so a suppressed or freed match can be anywhere.

    Walks meets by id in batches of at most RELINK_ROWS rows. Per batch: one
    query sizes the batch, one loads its rows, one loads their admin
    decisions, and candidate pools are loaded once into a cache that lives
    for that batch only. Rows are flushed and released before the next batch,
    so retained memory is one batch and queries grow with batches, not meets."""
    after = 0
    while True:
        sizes = db.query(MeetResult.id, func.count(MeetResultEntry.id)).outerjoin(
            MeetResultEvent, MeetResultEvent.result_id == MeetResult.id).outerjoin(
            MeetResultEntry, MeetResultEntry.event_id == MeetResultEvent.id).filter(
            MeetResult.id > after).group_by(MeetResult.id).order_by(MeetResult.id).limit(RELINK_MEETS).all()
        if not sizes:
            return
        batch, total = [], 0
        for rid, count in sizes:
            if batch and total + count > RELINK_ROWS:
                break
            batch.append(rid)
            total += count
        loaded = db.query(MeetResultEntry, MeetResultEvent.result_id).join(
            MeetResultEvent, MeetResultEvent.id == MeetResultEntry.event_id).filter(
            MeetResultEvent.result_id.in_(batch)).order_by(
            MeetResultEvent.result_id, MeetResultEntry.event_id, MeetResultEntry.position).all()
        by_meet: dict[int, list] = {}
        for row, rid in loaded:
            by_meet.setdefault(rid, []).append(row)
        decided = decisions(db, {key_of(row) for row, _rid in loaded})
        cache: dict = {}
        for rows in by_meet.values():
            links = resolve(db, rows, cache, decided)
            for i, row in enumerate(rows):
                row.user_id, row.link_source = links.get(i, (None, None))
        db.flush()
        for row, _rid in loaded:
            db.expunge(row)
        after = batch[-1]


def _admin_entry(db: Session, admin: AppUser, entry_id: int) -> MeetResultEntry:
    row = db.query(MeetResultEntry, MeetResult.calendar_event_id).join(
        MeetResultEvent, MeetResultEvent.id == MeetResultEntry.event_id).join(
        MeetResult, MeetResult.id == MeetResultEvent.result_id).filter(MeetResultEntry.id == entry_id).one_or_none()
    if row is None:
        fail(404, "entry_not_found", "Result not found")
    events.visible_event(db, admin, row[1])  # hidden event -> same 404 as missing
    if row[0].person_key is None:
        fail(422, "pair_not_linkable", "Synchro pairs cannot be linked to one account")
    return row[0]


def set_link(db: Session, admin: AppUser, entry_id: int, user_id: Optional[int]) -> None:
    """Tie this person to `user_id` in every meet, or never link them (None)."""
    lock_links(db)  # first: everything below is read after any concurrent decision
    entry = _admin_entry(db, admin, entry_id)
    if user_id is not None and db.query(AppUser.id).filter(AppUser.id == user_id, AppUser.is_active.is_(True)).first() is None:
        fail(422, "account_not_found", "Account not found")
    key = entry.person_key
    decision = db.query(MeetPersonLink).filter(MeetPersonLink.person_key == key).with_for_update().one_or_none()
    if decision is None:
        decision = MeetPersonLink(person_key=key)
        db.add(decision)
    decision.user_id, decision.decided_by_user_id, decision.decided_at = user_id, admin.id, datetime.utcnow()
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        fail(409, "conflict", "Conflicting concurrent change")
    relink_all(db)


def clear_link(db: Session, admin: AppUser, entry_id: int) -> None:
    """Drop the administrator decision: this person is matched automatically again.
    Relinks even without a decision, which repairs rows left behind when a
    deleted account removed its decision."""
    lock_links(db)
    entry = _admin_entry(db, admin, entry_id)
    decision = db.query(MeetPersonLink).filter(MeetPersonLink.person_key == entry.person_key).with_for_update().one_or_none()
    if decision is not None:
        db.delete(decision)
        db.flush()
    relink_all(db)


def account_candidates(db: Session, q: str, limit: int = 10) -> list[dict]:
    """Active accounts whose name, or an owned diver's name, contains `q`."""
    q = q.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    if len(q) < 2:
        return []
    needle = f"%{q}%"
    owned = db.query(UserDiverAccess.user_id).join(Diver, Diver.id == UserDiverAccess.diver_id).filter(
        UserDiverAccess.access_kind == "OWNER", func.lower(Diver.display_name).like(needle, escape="\\"))
    users = db.query(AppUser).filter(AppUser.is_active.is_(True), or_(
        func.lower(AppUser.display_name).like(needle, escape="\\"), AppUser.id.in_(owned))).order_by(
        AppUser.display_name, AppUser.id).limit(limit).all()
    divers: dict[int, list[str]] = {}
    if users:
        for uid, name in db.query(UserDiverAccess.user_id, Diver.display_name).join(
                Diver, Diver.id == UserDiverAccess.diver_id).filter(
                UserDiverAccess.user_id.in_([u.id for u in users]), UserDiverAccess.access_kind == "OWNER").limit(200):
            divers.setdefault(uid, []).append(name)
    return [{"user_id": u.id, "display_name": u.display_name, "diver_names": sorted(set(divers.get(u.id, []))),
             **avatar_identity(u)} for u in users]
