"""Calendar domain, authorization and membership foundation (Task02).

Portable by default (in-memory SQLite, FK enforcement ON). Set
CALENDAR_TEST_DATABASE_URL to a DISPOSABLE PostgreSQL database whose name
starts with calendar_test_: the schema is then built from the real SQL
migration (applied twice for idempotency) on top of the pre-calendar tables,
and model/migration parity is checked. SQLite runs do not prove PostgreSQL
behavior; the PostgreSQL run is the migration/constraint evidence.
"""
import os
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import calendar as calendar_api
from app.config import get_settings
from app.database import Base, get_db
from app.main import app
from app.models.calendar import (
    Calendar, CalendarEvent, CalendarSubscription, Club, ClubMembership, EventInvitation, EventOccurrence,
    EventResource, OccurrenceInterest, OccurrenceAbsenceReport, TrainingGroup, TrainingGroupMembership,
)
from app.models.user_auth import AppUser
from app.services import calendar_access as access
from app.services import calendar_membership as membership
from app.services import diver_invites
from app.services.sessions import create_session

PG_URL = os.environ.get("CALENDAR_TEST_DATABASE_URL")
MIGRATION = Path(__file__).parents[1] / "migrations" / "add_calendar_domain.sql"
INVITE = "calendar-test-invite"
PASSWORD = "correct horse battery staple"
TODAY = datetime.utcnow().date()


def _calendar_tables():
    return [t for t in Base.metadata.sorted_tables if t.info.get("sql_migration_only")]


def _legacy_tables():
    seed = {"app_users", "user_credentials", "user_sessions", "login_attempts", "divers", "user_diver_access",
            "sessions", "diver_invites", "security_audit_log"}
    tables = {Base.metadata.tables[name] for name in seed if name in Base.metadata.tables}
    while True:
        deps = {fk.column.table for t in tables for fk in t.foreign_keys}
        if deps <= tables:
            return [t for t in Base.metadata.sorted_tables if t in tables]
        tables |= deps


def _apply_migration(engine):
    conn = engine.raw_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(MIGRATION.read_text())
        conn.commit()
    finally:
        conn.close()


def make_engine(with_calendar=True):
    if PG_URL:
        url = make_url(PG_URL)
        assert url.database.startswith("calendar_test_"), "Disposable calendar_test_* database required"
        engine = create_engine(url)
        with engine.begin() as conn:
            conn.exec_driver_sql("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
        Base.metadata.create_all(engine, tables=_legacy_tables())
        if with_calendar:
            _apply_migration(engine)
            _apply_migration(engine)  # idempotent re-run
        return engine
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    event.listen(engine, "connect", lambda conn, _rec: conn.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine, tables=_legacy_tables() + (_calendar_tables() if with_calendar else []))
    return engine


@pytest.fixture()
def flags():
    settings = get_settings()
    saved = (settings.user_auth_enabled, settings.calendar_enabled, settings.friend_registration_enabled,
             settings.friend_invite_codes)
    settings.user_auth_enabled, settings.calendar_enabled = True, True
    settings.friend_registration_enabled, settings.friend_invite_codes = True, INVITE
    calendar_api._schema_ready = False
    yield settings
    (settings.user_auth_enabled, settings.calendar_enabled, settings.friend_registration_enabled,
     settings.friend_invite_codes) = saved
    calendar_api._schema_ready = False


def _harness(engine):
    db = sessionmaker(bind=engine, expire_on_commit=False)()

    def override():
        try:
            yield db
        finally:
            db.rollback()
            db.expunge_all()
    app.dependency_overrides[get_db] = override
    return db, TestClient(app)


def _occ(db, event, key, day_offset, hour=18, hours=2, all_day_days=0):
    day = TODAY + timedelta(days=day_offset)
    if all_day_days:
        start = datetime.combine(day, time())
        row = EventOccurrence(event_id=event.id, occurrence_key=key, is_all_day=True, start_date=day,
                              end_date=day + timedelta(days=all_day_days), window_start=start,
                              window_end=start + timedelta(days=all_day_days))
    else:
        start = datetime.combine(day, time(hour))
        row = EventOccurrence(event_id=event.id, occurrence_key=key, starts_at=start,
                              ends_at=start + timedelta(hours=hours), window_start=start,
                              window_end=start + timedelta(hours=hours))
    db.add(row)
    db.flush()
    return row


def _event(db, calendar, title, audience, status="published", organizer=None, event_type="training"):
    row = CalendarEvent(calendar_id=calendar.id, title=title, audience=audience, status=status,
                        event_type=event_type, timezone="Europe/Paris", organizer_user_id=organizer,
                        cancelled_at=datetime.utcnow() if status == "cancelled" else None)
    db.add(row)
    db.flush()
    return row


@pytest.fixture()
def cal(flags):
    engine = make_engine()
    db, client = _harness(engine)
    names = ("admin", "manager", "coach", "alice", "bob", "una", "outsider", "ocoach", "omanager", "idle")
    u = {}
    for name in names:
        u[name] = AppUser(email=f"{name}@example.test", display_name=name.title(), role="friend",
                          is_admin=name == "admin", is_active=name != "idle")
        db.add(u[name])
    db.flush()
    k = membership.create_club(db, u["admin"], "kcpm", "KCPM Montreuil", "KCPM", "Europe/Paris", True)
    o = membership.create_club(db, u["admin"], "other", "Other Club", None, "Europe/Paris", False)
    for club, name, role in ((k, "manager", "manager"), (k, "coach", "coach"), (k, "alice", "member"),
                             (k, "bob", "member"), (k, "una", "member"), (o, "outsider", "member"),
                             (o, "ocoach", "coach"), (o, "omanager", "manager")):
        membership.admin_add_membership(db, u["admin"], club.id, u[name].id, role)
    membership.update_membership(db, u["manager"], k.id, access.active_membership(db, u["coach"], k.id).id,
                                 None, True, True)
    ga = membership.create_group(db, u["manager"], k.id, "groupe-a", "Groupe A")
    gb = membership.create_group(db, u["manager"], k.id, "groupe-b", "Groupe B")
    og = membership.create_group(db, u["omanager"], o.id, "other-a", "Other A")
    start = TODAY - timedelta(days=30)
    membership.assign_group(db, u["coach"], k.id, u["alice"].id, ga.id, start)
    membership.assign_group(db, u["coach"], k.id, u["bob"].id, gb.id, start)
    cals = {c.kind + (f"-{c.training_group_id}" if c.training_group_id else f"-{c.club_id}"): c
            for c in db.query(Calendar).all()}
    kc, oc = cals[f"club-{k.id}"], cals[f"club-{o.id}"]
    gac, gbc = cals[f"group-{ga.id}"], cals[f"group-{gb.id}"]
    fed = Calendar(kind="federal", name="Federal dates")
    personal = Calendar(kind="personal", owner_user_id=u["alice"].id, name="Alice outings")
    db.add_all([fed, personal])
    db.flush()
    e = {
        "ga": _event(db, gac, "Groupe A training", "group"),
        "gb": _event(db, gbc, "Groupe B training", "group"),
        "club": _event(db, kc, "Club camp", "club", event_type="camp"),
        "draft": _event(db, kc, "Draft club event", "club", status="draft", organizer=u["coach"].id),
        "cancelled": _event(db, kc, "Cancelled club event", "club", status="cancelled"),
        "ocomm": _event(db, oc, "Other open meet", "community", event_type="competition"),
        "oclub": _event(db, oc, "Other club only", "club"),
        "invite": _event(db, personal, "Alice outing", "invited", organizer=u["alice"].id, event_type="outing"),
        "fed": _event(db, fed, "Federal championship", "community", event_type="competition"),
    }
    o_ = {key: _occ(db, ev, f"{key}-1", 1) for key, ev in e.items() if key != "club"}
    o_["club"] = _occ(db, e["club"], "club-1", 3, all_day_days=2)
    db.add(EventInvitation(event_id=e["invite"].id, invitee_user_id=u["una"].id, invited_by_user_id=u["alice"].id))
    db.add_all([
        EventResource(event_id=e["ocomm"].id, kind="official_info", label="Official page", url="https://example.test/meet"),
        EventResource(event_id=e["ocomm"].id, kind="club_chat", label="Other chat", url="https://chat.example.test/x",
                      restricted_to_club=True),
        EventResource(club_id=k.id, kind="club_chat", label="KCPM chat", url="https://chat.example.test/k"),
        EventResource(event_id=e["ga"].id, kind="rules", label="Group A plan"),
    ])
    db.commit()
    tokens = {n: create_session(db, user_id=u[n].id, ttl_seconds=3600)[0] for n in names if n != "idle"}
    db.expunge_all()

    def login(name):
        client.cookies.clear()
        client.cookies.set(flags.auth_cookie_name, tokens[name])
        return client
    yield dict(db=db, login=login, users=u, events=e, occ=o_, clubs=dict(k=k, o=o), groups=dict(a=ga, b=gb, o=og),
               cals=dict(k=kc, o=oc, a=gac, b=gbc, fed=fed, personal=personal), client=client)
    client.close()
    app.dependency_overrides.clear()
    db.close()
    engine.dispose()


WINDOW = f"from={TODAY.isoformat()}T00:00:00Z&to={(TODAY + timedelta(days=30)).isoformat()}T00:00:00Z"


def titles(client, extra=""):
    response = client.get(f"/api/v1/calendar/occurrences?{WINDOW}{extra}")
    assert response.status_code == 200, response.text
    return {item["event"]["title"] for item in response.json()["items"]}


def status(client, path):
    return client.get(f"/api/v1/calendar{path}").status_code


# --- Visibility matrix -------------------------------------------------------------

def test_member_sees_only_own_group_in_list_and_direct_detail(cal):
    alice, e, o = cal["login"]("alice"), cal["events"], cal["occ"]
    seen = titles(alice)
    assert "Groupe A training" in seen and "Groupe B training" not in seen
    assert {"Club camp", "Cancelled club event", "Other open meet", "Federal championship", "Alice outing"} <= seen
    assert not seen & {"Draft club event", "Other club only"}
    assert status(alice, f"/occurrences/{o['gb'].id}") == 404
    assert status(alice, f"/events/{e['gb'].id}") == 404
    assert status(alice, f"/occurrences/{o['ga'].id}") == 200
    assert titles(alice, f"&calendar_id={cal['cals']['b'].id}") == set()
    kinds = {(c["kind"], c["training_group_id"]) for c in alice.get("/api/v1/calendar/calendars").json()["items"]}
    assert ("group", cal["groups"]["a"].id) in kinds and ("group", cal["groups"]["b"].id) not in kinds
    assert ("club", None) in kinds and ("federal", None) in kinds
    # The detail never leaks a missing-vs-private difference.
    assert status(alice, "/occurrences/999999") == 404


def test_coach_sees_both_groups_of_own_club_only(cal):
    coach, ocoach, e = cal["login"]("coach"), None, cal["events"]
    seen = titles(coach)
    assert {"Groupe A training", "Groupe B training", "Draft club event"} <= seen
    assert "Other club only" not in seen
    ocoach = cal["login"]("ocoach")
    seen = titles(ocoach)
    assert not seen & {"Groupe A training", "Groupe B training", "Club camp"}
    assert {"Other club only", "Other open meet"} <= seen
    for key in ("ga", "gb", "club"):
        assert status(ocoach, f"/events/{e[key].id}") == 404


def test_unassigned_member_sees_club_wide_but_no_private_group(cal):
    una = cal["login"]("una")
    seen = titles(una)
    assert {"Club camp", "Other open meet", "Federal championship", "Alice outing"} <= seen
    assert not seen & {"Groupe A training", "Groupe B training"}
    clubs = una.get("/api/v1/calendar/me").json()["clubs"]
    assert len(clubs) == 1 and clubs[0]["group"] is None and clubs[0]["membership"]["role"] == "member"


def test_drafts_publishers_only_and_cancellation_is_history(cal):
    e = cal["events"]
    assert status(cal["login"]("alice"), f"/events/{e['draft'].id}") == 404
    assert status(cal["login"]("coach"), f"/events/{e['draft'].id}") == 200
    detail = cal["login"]("alice").get(f"/api/v1/calendar/events/{e['cancelled'].id}").json()
    assert detail["status"] == "cancelled"


def test_invitation_is_a_distinct_revocable_grant_and_following_grants_nothing(cal):
    db, e, u = cal["db"], cal["events"], cal["users"]
    assert status(cal["login"]("una"), f"/events/{e['invite'].id}") == 200
    assert cal["login"]("una").get(f"/api/v1/calendar/events/{e['invite'].id}").json()["my_invitation"] == "pending"
    assert status(cal["login"]("bob"), f"/events/{e['invite'].id}") == 404
    db.add(CalendarSubscription(calendar_id=cal["cals"]["b"].id, user_id=u["alice"].id))
    db.add(CalendarSubscription(calendar_id=cal["cals"]["personal"].id, user_id=u["bob"].id))
    db.commit()
    assert "Groupe B training" not in titles(cal["login"]("alice"))
    assert status(cal["login"]("bob"), f"/events/{e['invite'].id}") == 404
    invitation = db.query(EventInvitation).one()
    invitation.status, invitation.revoked_at = "revoked", datetime.utcnow()
    db.commit()
    assert status(cal["login"]("una"), f"/events/{e['invite'].id}") == 404


def test_private_resources_stay_scoped(cal):
    e, k, o = cal["events"], cal["clubs"]["k"], cal["clubs"]["o"]
    labels = {r["label"] for r in cal["login"]("alice").get(f"/api/v1/calendar/events/{e['ocomm'].id}").json()["resources"]}
    assert labels == {"Official page"}
    labels = {r["label"] for r in cal["login"]("outsider").get(f"/api/v1/calendar/events/{e['ocomm'].id}").json()["resources"]}
    assert labels == {"Official page", "Other chat"}
    assert [r["label"] for r in cal["login"]("alice").get(f"/api/v1/calendar/clubs/{k.id}/resources").json()] == ["KCPM chat"]
    assert status(cal["login"]("outsider"), f"/clubs/{k.id}/resources") == 404
    assert status(cal["login"]("alice"), f"/clubs/{o.id}/resources") == 404
    occ = cal["login"]("alice").get(f"/api/v1/calendar/occurrences/{cal['occ']['ga'].id}").json()
    assert [r["label"] for r in occ["resources"]] == ["Group A plan"]


def test_roster_lists_app_accounts_without_group_leakage(cal):
    k = cal["clubs"]["k"]
    roster = cal["login"]("alice").get(f"/api/v1/calendar/clubs/{k.id}/members").json()["items"]
    assert {r["display_name"] for r in roster} == {"Manager", "Coach", "Alice", "Bob", "Una"}
    assert all(r["group_id"] is None for r in roster)
    staff = {r["display_name"]: r["group_id"] for r in cal["login"]("coach").get(f"/api/v1/calendar/clubs/{k.id}/members").json()["items"]}
    assert staff["Alice"] == cal["groups"]["a"].id and staff["Bob"] == cal["groups"]["b"].id and staff["Una"] is None
    assert status(cal["login"]("outsider"), f"/clubs/{k.id}/members") == 404


def test_bounded_window_and_sql_filtering_before_pagination(cal):
    db, e = cal["db"], cal["events"]
    for i in range(6):  # earlier private rows that must not consume alice's page
        _occ(db, db.get(CalendarEvent, e["gb"].id), f"gb-early-{i}", 0, hour=6 + i, hours=1)
    db.commit()
    alice = cal["login"]("alice")
    url = f"/api/v1/calendar/occurrences?{WINDOW}&limit=2"
    seen, cursor = [], None
    for _ in range(10):
        page = alice.get(url + (f"&cursor={cursor}" if cursor else "")).json()
        seen += page["items"]
        cursor = page["next_cursor"]
        if not cursor:
            break
    ids = [item["id"] for item in seen]
    # ga, club camp, cancelled, other open meet, invited outing, federal
    assert len(ids) == len(set(ids)) == 6
    assert all(item["event"]["title"] != "Groupe B training" for item in seen)
    all_day = next(item for item in seen if item["is_all_day"])
    assert all_day["end_date"] > all_day["start_date"] and all_day["starts_at"] is None
    base = "/api/v1/calendar/occurrences"
    assert alice.get(f"{base}?from={TODAY}T00:00:00Z&to={TODAY + timedelta(days=101)}T00:00:00Z").status_code == 422
    assert alice.get(f"{base}?from={TODAY}T00:00:00Z&to={TODAY}T00:00:00Z").status_code == 422
    assert alice.get(f"{base}?{WINDOW}&limit=500").status_code == 422
    assert alice.get(f"{base}?{WINDOW}&cursor=bogus").status_code == 422
    assert alice.get(f"{base}?from={TODAY + timedelta(days=40)}T00:00:00Z&to={TODAY + timedelta(days=50)}T00:00:00Z").json()["items"] == []


def test_effective_dated_transfer_preserves_history(cal):
    db, u, k, g, o = cal["db"], cal["users"], cal["clubs"]["k"], cal["groups"], cal["occ"]
    coach = cal["login"]("coach")
    tomorrow = TODAY + timedelta(days=1)
    url = f"/api/v1/calendar/clubs/{k.id}/group-assignment"
    response = coach.put(url, json={"user_id": u["alice"].id, "group_id": g["b"].id, "effective_from": tomorrow.isoformat()})
    assert response.status_code == 200, response.text
    rows = db.query(TrainingGroupMembership).filter_by(user_id=u["alice"].id).order_by(TrainingGroupMembership.id).all()
    assert [(r.group_id, r.effective_to) for r in rows] == [(g["a"].id, tomorrow), (g["b"].id, None)]
    assert status(cal["login"]("alice"), f"/occurrences/{o['ga'].id}") == 200  # still Groupe A today
    alice = db.get(AppUser, u["alice"].id)
    later = {e.title for _o, e, _c in access.visible_occurrences(db, alice, on=tomorrow)}
    assert "Groupe B training" in later and "Groupe A training" not in later
    coach = cal["login"]("coach")
    assert coach.put(url, json={"user_id": u["alice"].id, "group_id": g["a"].id,
                                "effective_from": tomorrow.isoformat()}).status_code == 422
    assert coach.put(url, json={"user_id": u["alice"].id, "group_id": g["b"].id}).json()["effective_from"] == tomorrow.isoformat()


def test_departed_member_loses_private_access(cal):
    db, u, k, e = cal["db"], cal["users"], cal["clubs"]["k"], cal["events"]
    invited = _event(db, db.get(Calendar, cal["cals"]["k"].id), "Club invite-only", "invited")
    db.add(EventInvitation(event_id=invited.id, invitee_user_id=u["alice"].id))
    db.commit()
    invited_id = invited.id
    alice = cal["login"]("alice")
    assert status(alice, f"/events/{invited_id}") == 200
    assert alice.post(f"/api/v1/calendar/clubs/{k.id}/leave").json()["status"] == "left"
    for key in ("ga", "club"):
        assert status(alice, f"/events/{e[key].id}") == 404
    assert status(alice, f"/events/{invited_id}") == 404
    assert status(alice, f"/clubs/{k.id}/members") == 404
    assert alice.get("/api/v1/calendar/me").json()["clubs"] == []
    assert "Other open meet" in titles(alice)  # community audience is unaffected
    history = db.query(ClubMembership).filter_by(user_id=u["alice"].id).one()
    assert history.status == "left" and history.ended_at is not None
    assignment = db.query(TrainingGroupMembership).filter_by(user_id=u["alice"].id).one()
    assert assignment.effective_to == TODAY
    assert db.query(EventInvitation).filter_by(invitee_user_id=u["alice"].id, event_id=invited_id).one().status == "revoked"
    # Manager removal works the same way and keeps history.
    bob_m = access.active_membership(db, db.get(AppUser, u["bob"].id), k.id).id
    manager = cal["login"]("manager")
    assert manager.post(f"/api/v1/calendar/clubs/{k.id}/memberships/{bob_m}/end").json()["status"] == "removed"
    assert status(cal["login"]("bob"), f"/events/{e['gb'].id}") == 404


# --- Administration and authorization -------------------------------------------------

def test_admin_club_creation_legacy_link_and_manager_appointment(cal):
    db, u = cal["db"], cal["users"]
    admin = cal["login"]("admin")
    created = admin.post("/api/v1/calendar/admin/clubs", json={"slug": "new-club", "name": "New Club"})
    assert created.status_code == 201, created.text
    club_id = created.json()["id"]
    assert db.query(Calendar).filter_by(kind="club", club_id=club_id).count() == 1
    assert admin.post("/api/v1/calendar/admin/clubs", json={"slug": "new-club", "name": "Dup"}).status_code == 409
    assert admin.post("/api/v1/calendar/admin/clubs", json={"slug": "tz", "name": "TZ", "timezone": "Mars/Base"}).status_code == 422
    url = f"/api/v1/calendar/admin/clubs/{club_id}/memberships"
    linked = admin.post(url, json={"user_id": u["una"].id})
    assert linked.status_code == 201 and linked.json()["source"] == "admin_legacy"
    assert admin.post(url, json={"user_id": u["una"].id}).status_code == 409
    assert admin.post(url, json={"user_id": u["idle"].id}).status_code == 422
    assert admin.post(url, json={"user_id": u["bob"].id, "role": "manager"}).json()["role"] == "manager"
    for name in ("manager", "alice"):
        assert cal["login"](name).post("/api/v1/calendar/admin/clubs", json={"slug": "x-club", "name": "X"}).status_code == 403
        assert cal["login"](name).post(url, json={"user_id": u["alice"].id}).status_code == 403


def test_admin_is_not_a_club_publisher_or_private_reader(cal):
    db, e = cal["db"], cal["events"]
    admin_user = db.get(AppUser, cal["users"]["admin"].id)
    assert not access.can_publish_to_calendar(db, admin_user, db.get(Calendar, cal["cals"]["k"].id))
    assert access.can_publish_to_calendar(db, admin_user, db.get(Calendar, cal["cals"]["fed"].id))
    for key in ("ga", "club", "draft"):
        assert status(cal["login"]("admin"), f"/events/{e[key].id}") == 404
    coach = db.get(AppUser, cal["users"]["coach"].id)
    assert access.can_publish_to_calendar(db, coach, db.get(Calendar, cal["cals"]["a"].id))
    assert not access.can_publish_to_calendar(db, coach, db.get(Calendar, cal["cals"]["o"].id))
    alice = db.get(AppUser, cal["users"]["alice"].id)
    assert not access.can_publish_to_calendar(db, alice, db.get(Calendar, cal["cals"]["k"].id))
    assert access.can_publish_to_calendar(db, alice, db.get(Calendar, cal["cals"]["personal"].id))


def test_role_changes_are_per_club_and_never_self_elevating(cal):
    db, u, k, o = cal["db"], cal["users"], cal["clubs"]["k"], cal["clubs"]["o"]
    alice_m = access.active_membership(db, db.get(AppUser, u["alice"].id), k.id).id
    manager_m = access.active_membership(db, db.get(AppUser, u["manager"].id), k.id).id
    url = f"/api/v1/calendar/clubs/{k.id}/memberships/{alice_m}"
    assert cal["login"]("alice").patch(url, json={"role": "coach", "can_publish": True}).status_code == 403
    assert cal["login"]("coach").patch(url, json={"role": "coach"}).status_code == 403
    assert cal["login"]("ocoach").patch(url, json={"role": "coach"}).status_code == 404
    assert cal["login"]("omanager").patch(url, json={"role": "coach"}).status_code == 404
    assert cal["login"]("manager").patch(url, json={"role": "manager"}).status_code == 403
    assert cal["login"]("admin").patch(url, json={"can_publish": True}).status_code == 403
    granted = cal["login"]("manager").patch(url, json={"role": "coach", "can_publish": True})
    assert granted.status_code == 200 and granted.json()["can_publish"] is True
    assert cal["login"]("manager").patch(url, json={"role": "member"}).json()["can_publish"] is False
    manager_url = f"/api/v1/calendar/clubs/{k.id}/memberships/{manager_m}"
    assert cal["login"]("admin").patch(manager_url, json={"role": "member"}).status_code == 409  # last manager
    assert cal["login"]("manager").post(f"/api/v1/calendar/clubs/{k.id}/leave").status_code == 409
    assert cal["login"]("admin").patch(url, json={"role": "manager"}).json()["role"] == "manager"
    assert cal["login"]("admin").patch(manager_url, json={"role": "member"}).status_code == 200
    assert cal["login"]("alice").get(f"/api/v1/calendar/clubs/{o.id}/members").status_code == 404


def test_group_assignment_authorization_and_cross_club_rejection(cal):
    db, u, k, g = cal["db"], cal["users"], cal["clubs"]["k"], cal["groups"]
    url = f"/api/v1/calendar/clubs/{k.id}/group-assignment"
    body = {"user_id": u["una"].id, "group_id": g["a"].id}
    assert cal["login"]("alice").put(url, json=body).status_code == 403
    assert cal["login"]("ocoach").put(url, json=body).status_code == 404
    assert cal["login"]("admin").put(url, json=body).status_code == 404  # admin is not club staff
    assert cal["login"]("coach").put(url, json={**body, "group_id": g["o"].id}).status_code == 422
    assert cal["login"]("coach").put(url, json={**body, "user_id": u["outsider"].id}).status_code == 422
    assert cal["login"]("coach").put(url, json={**body, "user_id": u["idle"].id}).status_code == 422
    coach_m = access.active_membership(db, db.get(AppUser, u["coach"].id), k.id).id
    cal["login"]("manager").patch(f"/api/v1/calendar/clubs/{k.id}/memberships/{coach_m}",
                                  json={"can_assign_groups": False})
    assert cal["login"]("coach").put(url, json=body).status_code == 403
    assert cal["login"]("manager").put(url, json=body).status_code == 200
    assert "Groupe A training" in titles(cal["login"]("una"))
    assert cal["login"]("manager").put(url, json={"user_id": u["una"].id, "group_id": None,
                                                  "effective_from": (TODAY + timedelta(days=1)).isoformat()}).json() is None


def test_inactive_actor_is_rejected(cal, flags):
    db = cal["db"]
    token = create_session(db, user_id=cal["users"]["idle"].id, ttl_seconds=3600)[0]
    client = cal["client"]
    client.cookies.clear()
    client.cookies.set(flags.auth_cookie_name, token)
    assert client.get("/api/v1/calendar/me").status_code == 401
    alice = db.get(AppUser, cal["users"]["alice"].id)
    alice.is_active = False
    db.commit()
    assert access.visible_events(db, alice).count() == 0
    assert access.active_membership(db, alice, cal["clubs"]["k"].id) is None


def test_write_origin_guard(cal):
    response = cal["login"]("admin").post("/api/v1/calendar/admin/clubs", headers={"Origin": "https://evil.test"},
                                          json={"slug": "evil", "name": "Evil"})
    assert response.status_code == 403


# --- Signup -------------------------------------------------------------------------------

def _register(client, email, **extra):
    response = client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD,
                                                          "invite_code": INVITE, **extra})
    # The Secure session cookie is not resent over the test client's http.
    token = response.cookies.get(get_settings().auth_cookie_name)
    if token:
        client.cookies.set(get_settings().auth_cookie_name, token)
    return response


def test_signup_club_choice_creates_plain_active_membership(cal):
    db, k, o = cal["db"], cal["clubs"]["k"], cal["clubs"]["o"]
    client = cal["client"]
    client.cookies.clear()
    assert client.get("/api/v1/auth/signup-clubs").json() == [{"id": k.id, "name": "KCPM Montreuil", "short_name": "KCPM"}]
    response = _register(client, "joiner@example.test", club_id=k.id)
    assert response.status_code == 201, response.text
    m = db.query(ClubMembership).filter_by(user_id=response.json()["user_id"]).one()
    assert (m.club_id, m.role, m.status, m.source, m.can_publish, m.can_assign_groups) == (k.id, "member", "active", "signup", False, False)
    assert db.query(TrainingGroupMembership).filter_by(user_id=m.user_id).count() == 0
    me = client.get("/api/v1/calendar/me").json()["clubs"][0]
    assert me["self_declared"] is True and me["group"] is None
    assert not {"Groupe A training", "Groupe B training"} & titles(client)
    client.cookies.clear()
    independent = _register(client, "solo@example.test")
    assert independent.status_code == 201
    assert db.query(ClubMembership).filter_by(user_id=independent.json()["user_id"]).count() == 0
    client.cookies.clear()
    for club_id in (o.id, 999999):  # closed or missing club: nothing is created
        assert _register(client, f"closed{club_id}@example.test", club_id=club_id).status_code == 422
        assert db.query(AppUser).filter_by(email=f"closed{club_id}@example.test").count() == 0


def test_invite_signup_with_club_is_transactional(cal):
    db, k, o = cal["db"], cal["clubs"]["k"], cal["clubs"]["o"]
    from app.models.diver import Diver
    diver = Diver(display_name="Lea", canonical_name="lea")
    db.add(diver)
    db.commit()
    token, _ = diver_invites.mint_invite(db, diver_id=diver.id, created_by_user_id=cal["users"]["admin"].id)
    client = cal["client"]
    client.cookies.clear()
    body = {"token": token, "email": "lea@example.test", "password": PASSWORD}
    refused = client.post("/api/v1/auth/register-invite", json={**body, "club_id": o.id})
    assert refused.status_code == 422 and refused.json()["code"] == "club_unavailable"
    assert client.post("/api/v1/auth/invite/peek", json={"token": token}).status_code == 200  # not consumed
    accepted = client.post("/api/v1/auth/register-invite", json={**body, "club_id": k.id})
    assert accepted.status_code == 201, accepted.text
    m = db.query(ClubMembership).filter_by(user_id=accepted.json()["user_id"]).one()
    assert (m.club_id, m.role, m.source) == (k.id, "member", "signup")


def test_feature_off_keeps_existing_signup_and_hides_calendar(cal, flags):
    flags.calendar_enabled = False
    client = cal["client"]
    client.cookies.clear()
    assert client.get("/api/v1/auth/signup-clubs").status_code == 404
    assert _register(client, "flagoff@example.test", club_id=cal["clubs"]["k"].id).status_code == 422
    assert _register(client, "flagoff@example.test").status_code == 201
    assert client.get("/api/v1/calendar/me").status_code == 404
    assert cal["login"]("coach").get(f"/api/v1/calendar/events/{cal['events']['ga'].id}").status_code == 404
    client.cookies.clear()
    assert client.get("/api/v1/calendar/me").status_code == 401  # session boundary first, no leak


def test_old_app_works_before_calendar_migration(flags):
    engine = make_engine(with_calendar=False)
    db, client = _harness(engine)
    try:
        assert not inspect(engine).has_table("clubs")
        flags.calendar_enabled = False
        assert _register(client, "legacy@example.test").status_code == 201
        assert client.get("/api/v1/calendar/me").status_code == 404
        flags.calendar_enabled = True
        assert client.get("/api/v1/calendar/me").status_code == 503
        client.cookies.clear()
        assert client.post("/api/v1/auth/register-invite", json={
            "token": "unused-token-for-schema-test", "email": "new@example.test",
            "password": PASSWORD, "club_id": 1}).status_code == 503
    finally:
        client.close()
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()


def test_init_db_never_creates_calendar_tables():
    from app import database
    engine = create_engine("sqlite://")
    original = database.engine
    database.engine = engine
    try:
        database.init_db()
    finally:
        database.engine = original
    names = set(inspect(engine).get_table_names())
    assert "app_users" in names and not names & {t.name for t in _calendar_tables()}


# --- Constraints ----------------------------------------------------------------------------

def _rejects(db, *rows):
    db.add_all(rows)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_database_constraints(cal):
    db, u, k, o, g, occ = cal["db"], cal["users"], cal["clubs"]["k"], cal["clubs"]["o"], cal["groups"], cal["occ"]
    alice_m = db.query(ClubMembership).filter_by(user_id=u["alice"].id, club_id=k.id).one()
    _rejects(db, ClubMembership(club_id=k.id, user_id=u["alice"].id, source="manager"))  # duplicate active
    _rejects(db, TrainingGroupMembership(club_id=k.id, group_id=g["b"].id, club_membership_id=alice_m.id,
                                         user_id=u["alice"].id, effective_from=TODAY))  # second open assignment
    _rejects(db, TrainingGroupMembership(club_id=k.id, group_id=g["o"].id, club_membership_id=alice_m.id,
                                         user_id=u["alice"].id, effective_from=TODAY - timedelta(days=400),
                                         effective_to=TODAY - timedelta(days=300)))  # cross-club group
    _rejects(db, TrainingGroupMembership(club_id=o.id, group_id=g["o"].id, club_membership_id=alice_m.id,
                                         user_id=u["alice"].id, effective_from=TODAY - timedelta(days=400),
                                         effective_to=TODAY - timedelta(days=300)))  # cross-club membership
    _rejects(db, Calendar(kind="group", club_id=o.id, training_group_id=g["a"].id, name="bad"))
    _rejects(db, Calendar(kind="club", name="no club"))
    _rejects(db, OccurrenceInterest(occurrence_id=occ["ga"].id, user_id=u["alice"].id, state="interested"),
             OccurrenceInterest(occurrence_id=occ["ga"].id, user_id=u["alice"].id, state="maybe"))
    _rejects(db, OccurrenceInterest(occurrence_id=occ["ga"].id, user_id=u["bob"].id, state="going"))
    _rejects(db, OccurrenceAbsenceReport(occurrence_id=occ["ga"].id, user_id=u["bob"].id),
             OccurrenceAbsenceReport(occurrence_id=occ["ga"].id, user_id=u["bob"].id))
    _rejects(db, EventInvitation(event_id=cal["events"]["invite"].id, invitee_user_id=u["una"].id))
    start = datetime.combine(TODAY, time(10))
    _rejects(db, EventOccurrence(event_id=cal["events"]["ga"].id, occurrence_key="ga-1", starts_at=start,
                                 ends_at=start + timedelta(hours=1), window_start=start, window_end=start + timedelta(hours=1)))
    _rejects(db, EventOccurrence(event_id=cal["events"]["ga"].id, occurrence_key="mixed", is_all_day=True,
                                 start_date=TODAY, end_date=TODAY + timedelta(days=1), starts_at=start,
                                 window_start=start, window_end=start + timedelta(days=1)))
    _rejects(db, EventResource(kind="rules", label="ownerless"))
    # Interest and absence are independent rows for the same person.
    db.add_all([OccurrenceInterest(occurrence_id=occ["ga"].id, user_id=u["alice"].id, state="interested"),
                OccurrenceAbsenceReport(occurrence_id=occ["ga"].id, user_id=u["alice"].id)])
    db.commit()
    item = cal["login"]("alice").get(f"/api/v1/calendar/occurrences/{occ['ga'].id}").json()
    assert item["my_interest"] == "interested" and item["my_absence_reported"] is True
    assert cal["login"]("coach").get(f"/api/v1/calendar/occurrences/{occ['ga'].id}").json()["my_interest"] is None


@pytest.mark.skipif(not PG_URL, reason="PostgreSQL parity needs CALENDAR_TEST_DATABASE_URL")
def test_postgres_migration_matches_models(cal):
    insp = inspect(cal["db"].get_bind())
    for table in _calendar_tables():
        columns = {c["name"]: c for c in insp.get_columns(table.name)}
        assert set(columns) == {c.name for c in table.columns}, table.name
        for c in table.columns:
            assert columns[c.name]["nullable"] == c.nullable, (table.name, c.name)
        indexes = {i["name"] for i in insp.get_indexes(table.name)} | {
            u["name"] for u in insp.get_unique_constraints(table.name)}
        expected = {i.name for i in table.indexes}
        assert expected <= indexes, (table.name, expected - indexes)
        checks = {c["name"] for c in insp.get_check_constraints(table.name)}
        assert {c.name for c in table.constraints if c.__class__.__name__ == "CheckConstraint"} <= checks
        fks = {(tuple(f["constrained_columns"]), f["referred_table"], (f.get("options") or {}).get("ondelete"))
               for f in insp.get_foreign_keys(table.name)}
        for fk in table.foreign_key_constraints:
            ondelete = fk.ondelete.upper() if fk.ondelete else None
            assert (tuple(fk.column_keys), fk.referred_table.name, ondelete) in fks, (table.name, fk.column_keys)


def test_backdated_reassignment_cannot_overlap_closed_history(cal):
    k, users, groups = cal["clubs"]["k"], cal["users"], cal["groups"]
    coach = cal["login"]("coach")
    url = f"/api/v1/calendar/clubs/{k.id}/group-assignment"
    end = TODAY + timedelta(days=1)
    assert coach.put(url, json={"user_id": users["alice"].id,
        "group_id": None, "effective_from": end.isoformat()}).status_code == 200
    conflict = coach.put(url, json={"user_id": users["alice"].id,
        "group_id": groups["b"].id, "effective_from": TODAY.isoformat()})
    assert conflict.status_code == 422
    assert coach.put(url, json={"user_id": users["alice"].id,
        "group_id": groups["b"].id, "effective_from": end.isoformat()}).status_code == 200


@pytest.mark.skipif(not PG_URL, reason="Requires PostgreSQL row locking")
def test_concurrent_manager_demotions_cannot_orphan_club(cal):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from fastapi import HTTPException

    db = cal["db"]
    club_id, admin_id = cal["clubs"]["k"].id, cal["users"]["admin"].id
    manager = access.active_membership(db, cal["users"]["manager"], club_id)
    second = access.active_membership(db, cal["users"]["bob"], club_id)
    second.role = "manager"
    ids = (manager.id, second.id)
    db.commit()
    factory = sessionmaker(bind=db.get_bind())
    barrier = Barrier(2)

    def demote(mid):
        with factory() as session:
            actor = session.get(AppUser, admin_id)
            barrier.wait(timeout=10)
            try:
                membership.update_membership(session, actor, club_id, mid, "member", None, None)
                session.commit()
                return 200
            except HTTPException as exc:
                session.rollback()
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(demote, ids))
    assert sorted(results) == [200, 409]
    assert db.query(ClubMembership).filter_by(club_id=club_id, role="manager", status="active").count() == 1
