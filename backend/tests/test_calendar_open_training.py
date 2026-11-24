"""Club open-training windows before competitions (2 calendar weeks opt-in)."""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import sessionmaker

from app.models.calendar import (
    Calendar, CalendarAlertDelivery, CalendarEvent, EventOccurrence,
)
from app.models.user_auth import AppUser
from app.services import calendar_access as access
from app.services import calendar_alerts as alerts
from app.services import calendar_membership as membership
from app.services import calendar_openings as openings
from app.services import session_calendar
from app.services.sessions import create_session
from tests.test_calendar_domain import TODAY, cal, flags  # noqa: F401 (pytest fixtures)


def _headers():
    return {"Origin": "http://testserver"}


def _paris_utc(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=ZoneInfo("Europe/Paris")) \
        .astimezone(timezone.utc).replace(tzinfo=None)


def _setup_kcpm_window(cal):
    """Build a federal competition on Sunday next week and Débutants (ga) +
    Confirmés (gb) sessions inside and outside its 2-week training window."""
    db = cal["db"]
    days_until_sunday = (6 - TODAY.weekday()) % 7
    comp_day = TODAY + timedelta(days=days_until_sunday + 7)
    win_start, win_end = openings.default_opening_window(comp_day)

    comp = CalendarEvent(
        calendar_id=cal["cals"]["fed"].id, event_type="competition", audience="community",
        status="published", title="Régionale Hiver", timezone="Europe/Paris",
    )
    db.add(comp)
    db.flush()
    db.add(EventOccurrence(
        event_id=comp.id, occurrence_key="reg-hiver", is_all_day=True,
        start_date=comp_day, end_date=comp_day + timedelta(days=1),
        window_start=_paris_utc(comp_day, 0), window_end=_paris_utc(comp_day + timedelta(days=1), 0),
    ))

    ev_deb = cal["events"]["ga"]  # Alice = Débutants
    ev_conf = cal["events"]["gb"]  # Bob = Confirmés

    def add_training(ev, key, day, hour=19):
        s, e = _paris_utc(day, hour), _paris_utc(day, hour + 2)
        occ = EventOccurrence(
            event_id=ev.id, occurrence_key=key, is_all_day=False,
            starts_at=s, ends_at=e, window_start=s, window_end=e,
        )
        db.add(occ)
        db.flush()
        return occ

    # Pick a session inside the window that is also strictly in the future for reminder tests.
    inside_day = max(win_start + timedelta(days=1), TODAY + timedelta(days=2))
    if inside_day > win_end:
        inside_day = win_end
    deb_inside = add_training(ev_deb, "deb-inside", inside_day)
    deb_before = add_training(ev_deb, "deb-before", win_start - timedelta(days=2))
    deb_after = add_training(ev_deb, "deb-after", comp_day)
    conf_inside = add_training(ev_conf, "conf-inside", inside_day)
    out = dict(
        comp_id=comp.id, comp_day=comp_day, win_start=win_start, win_end=win_end,
        ev_deb_id=ev_deb.id, ev_conf_id=ev_conf.id,
        deb_inside_id=deb_inside.id, deb_before_id=deb_before.id,
        deb_after_id=deb_after.id, conf_inside_id=conf_inside.id,
    )
    db.commit()
    db.expunge_all()
    return out


def test_default_opening_window_two_calendar_weeks():
    # Competition on Sunday 22 Nov 2026 -> Mon 9 Nov .. Sat 21 Nov (previous week + competition week)
    assert openings.default_opening_window(date(2026, 11, 22)) == (date(2026, 11, 9), date(2026, 11, 21))
    # Competition on Sunday 6 Dec 2026 -> Mon 23 Nov .. Sat 5 Dec
    assert openings.default_opening_window(date(2026, 12, 6)) == (date(2026, 11, 23), date(2026, 12, 5))
    # Competition on Saturday 13 Jun 2026 -> Mon 1 Jun .. Fri 12 Jun
    assert openings.default_opening_window(date(2026, 6, 13)) == (date(2026, 6, 1), date(2026, 6, 12))
    # Competition on Thursday 18 Jun 2026 -> Mon 8 Jun .. Wed 17 Jun
    assert openings.default_opening_window(date(2026, 6, 18)) == (date(2026, 6, 8), date(2026, 6, 17))
    # Competition on Monday 15 Jun 2026 -> Mon 1 Jun .. Sun 14 Jun (2 full weeks before Monday)
    assert openings.default_opening_window(date(2026, 6, 15)) == (date(2026, 6, 1), date(2026, 6, 14))


def test_open_training_visibility_opt_in_attendance_and_revocation(cal):
    s = _setup_kcpm_window(cal)
    db = cal["db"]
    club_id = cal["clubs"]["k"].id
    g_conf_id = cal["groups"]["b"].id  # Bob = Confirmés
    alice_id, bob_id = cal["users"]["alice"].id, cal["users"]["bob"].id
    q_from = (s["win_start"] - timedelta(days=5)).isoformat() + "T00:00:00Z"
    q_to = (s["comp_day"] + timedelta(days=3)).isoformat() + "T00:00:00Z"

    # Before opening: Bob (Confirmés) cannot see Groupe A (Débutants) sessions at all.
    bob = cal["login"]("bob")
    assert bob.get(f"/api/v1/calendar/occurrences/{s['deb_inside_id']}").status_code == 404
    assert bob.get(f"/api/v1/calendar/events/{s['ev_deb_id']}").status_code == 404
    before_ids = {o["id"] for o in bob.get("/api/v1/calendar/occurrences", params={"from": q_from, "to": q_to}).json()["items"]}
    assert s["deb_inside_id"] not in before_ids
    assert s["conf_inside_id"] in before_ids

    # Manager checks competition opening scopes -> sees KCPM + default 2 calendar weeks.
    mgr = cal["login"]("manager")
    scopes = mgr.get(f"/api/v1/calendar/events/{s['comp_id']}/training-openings")
    assert scopes.status_code == 200
    body = scopes.json()
    assert body["default_starts_on"] == s["win_start"].isoformat()
    assert body["default_ends_on"] == s["win_end"].isoformat()
    assert len(body["clubs"]) == 1 and body["clubs"][0]["club_id"] == club_id

    # Manager opens all club training sessions to Confirmés for this federal competition (dates auto-filled).
    created = mgr.post(
        f"/api/v1/calendar/clubs/{club_id}/training-openings",
        json={"eligible_group_id": g_conf_id, "competition_event_id": s["comp_id"]},
        headers=_headers(),
    )
    assert created.status_code == 201, created.text
    op = created.json()
    assert op["starts_on"] == s["win_start"].isoformat()
    assert op["ends_on"] == s["win_end"].isoformat()
    assert op["competition_title"] == "Régionale Hiver"

    # Duplicate opening for same competition + group is rejected (409).
    dup = mgr.post(
        f"/api/v1/calendar/clubs/{club_id}/training-openings",
        json={"eligible_group_id": g_conf_id, "competition_event_id": s["comp_id"]},
        headers=_headers(),
    )
    assert dup.status_code == 409

    # Bob now sees ONLY Groupe A occurrences inside the 2-week window, marked open_access=True.
    bob = cal["login"]("bob")
    page = bob.get("/api/v1/calendar/occurrences", params={"from": q_from, "to": q_to}).json()["items"]
    by_id = {o["id"]: o for o in page}
    assert s["deb_inside_id"] in by_id
    assert by_id[s["deb_inside_id"]]["open_access"] is True
    assert s["deb_before_id"] not in by_id
    assert s["deb_after_id"] not in by_id
    assert by_id[s["conf_inside_id"]]["open_access"] is False

    # Direct-ID checks: outside occurrences stay 404; event detail never leaks occurrences outside the window.
    assert bob.get(f"/api/v1/calendar/occurrences/{s['deb_before_id']}").status_code == 404
    assert bob.get(f"/api/v1/calendar/occurrences/{s['deb_after_id']}").status_code == 404
    ev_detail = bob.get(f"/api/v1/calendar/events/{s['ev_deb_id']}")
    assert ev_detail.status_code == 200
    ev_occ_ids = {o["id"] for o in ev_detail.json()["occurrences"]}
    assert s["deb_inside_id"] in ev_occ_ids
    assert s["deb_before_id"] not in ev_occ_ids
    assert s["deb_after_id"] not in ev_occ_ids

    # Detail of open session: opt-in only (can_report_absence=False), Bob not counted in going yet.
    detail = bob.get(f"/api/v1/calendar/occurrences/{s['deb_inside_id']}").json()
    assert detail["open_access"] is True
    assert detail["can_report_absence"] is False
    assert detail["going"]["interested"] == 1  # only Alice
    assert bob.put(f"/api/v1/calendar/occurrences/{s['deb_inside_id']}/absence",
                   json={"absent": True}, headers=_headers()).status_code == 403

    # Bob taps "Je viens" -> joins going & occurrence_members (used for shared sessions), still no absence right.
    joined = bob.put(
        f"/api/v1/calendar/occurrences/{s['deb_inside_id']}/interest",
        json={"state": "interested"},
        headers=_headers(),
    )
    assert joined.status_code == 200
    jbody = joined.json()
    assert jbody["my_interest"] == "interested"
    assert jbody["can_report_absence"] is False
    assert jbody["going"]["interested"] == 2
    assert {p["user_id"] for p in jbody["going"]["people"]} == {alice_id, bob_id}
    member_ids = {u.id for u in session_calendar.occurrence_members(db, s["deb_inside_id"]).all()}
    assert member_ids == {alice_id, bob_id}

    # Reminders: Bob gets a planned calendar_reminder and passes dispatch visibility check.
    Session = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    deb_inside_row = db.get(EventOccurrence, s["deb_inside_id"])
    ev_deb_row = db.get(CalendarEvent, s["ev_deb_id"])
    due = alerts.reminder_due(deb_inside_row, ev_deb_row)
    stats = alerts.plan_reminders(Session, due + timedelta(minutes=5), batch=50)
    assert stats["reminders_planned"] >= 1
    rem = db.query(CalendarAlertDelivery).filter_by(
        kind="reminder", user_id=bob_id, occurrence_id=s["deb_inside_id"]
    ).one()
    rem_id = rem.id
    assert alerts.suppression_reason(db, rem, due + timedelta(minutes=10)) is None

    # Alice (Débutants), Una (unassigned), and Outsider still CANNOT see unauthorized sessions.
    assert cal["login"]("alice").get(f"/api/v1/calendar/occurrences/{s['conf_inside_id']}").status_code == 404
    assert cal["login"]("una").get(f"/api/v1/calendar/occurrences/{s['deb_inside_id']}").status_code == 404
    assert cal["login"]("outsider").get(f"/api/v1/calendar/occurrences/{s['deb_inside_id']}").status_code == 404

    # Bob withdraws "Je viens" -> immediately leaves going & reminder is suppressed.
    bob = cal["login"]("bob")
    left = bob.put(
        f"/api/v1/calendar/occurrences/{s['deb_inside_id']}/interest",
        json={"state": None},
        headers=_headers(),
    )
    assert left.status_code == 200
    assert left.json()["going"]["interested"] == 1
    assert alerts.suppression_reason(db, db.get(CalendarAlertDelivery, rem_id), due + timedelta(minutes=10)) == "not_interested"

    # Re-join, then manager deletes the opening -> access, attendance, and pending reminder immediately revoked.
    bob.put(f"/api/v1/calendar/occurrences/{s['deb_inside_id']}/interest",
            json={"state": "interested"}, headers=_headers())
    mgr = cal["login"]("manager")
    deleted = mgr.delete(f"/api/v1/calendar/clubs/{club_id}/training-openings/{op['id']}", headers=_headers())
    assert deleted.status_code == 204
    assert {u.id for u in session_calendar.occurrence_members(db, s["deb_inside_id"]).all()} == {alice_id}
    assert alerts.suppression_reason(db, db.get(CalendarAlertDelivery, rem_id), due + timedelta(minutes=10)) == "no_access"

    bob = cal["login"]("bob")
    assert bob.get(f"/api/v1/calendar/occurrences/{s['deb_inside_id']}").status_code == 404
    assert bob.get(f"/api/v1/calendar/events/{s['ev_deb_id']}").status_code == 404


def test_open_training_permissions_and_validation(cal, flags):
    s = _setup_kcpm_window(cal)
    db = cal["db"]
    club_id = cal["clubs"]["k"].id
    g_conf_id = cal["groups"]["b"].id
    g_other_id = cal["groups"]["o"].id

    # Add a coach without can_publish to verify publisher-only authorization.
    coach_nopub = AppUser(email="coachnopub@example.test", display_name="CoachNoPub", role="friend", is_active=True)
    db.add(coach_nopub)
    db.flush()
    membership.admin_add_membership(db, cal["users"]["admin"], club_id, coach_nopub.id, "coach")
    db.commit()
    nopub_token = create_session(db, user_id=coach_nopub.id, ttl_seconds=3600)[0]
    db.expunge_all()

    # Plain member can list club openings (read-only) but cannot create; outsider gets 404.
    bob = cal["login"]("bob")
    listed = bob.get(f"/api/v1/calendar/clubs/{club_id}/training-openings")
    assert listed.status_code == 200 and listed.json()["can_manage"] is False
    assert bob.post(
        f"/api/v1/calendar/clubs/{club_id}/training-openings",
        json={"eligible_group_id": g_conf_id, "starts_on": s["win_start"].isoformat(), "ends_on": s["win_end"].isoformat()},
        headers=_headers(),
    ).status_code == 403
    assert bob.get(f"/api/v1/calendar/events/{s['comp_id']}/training-openings").json()["clubs"] == []

    outsider = cal["login"]("outsider")
    assert outsider.get(f"/api/v1/calendar/clubs/{club_id}/training-openings").status_code == 404
    assert outsider.post(
        f"/api/v1/calendar/clubs/{club_id}/training-openings",
        json={"eligible_group_id": g_conf_id, "starts_on": s["win_start"].isoformat(), "ends_on": s["win_end"].isoformat()},
        headers=_headers(),
    ).status_code == 404

    # Coach without can_publish is forbidden.
    cal["client"].cookies.clear()
    cal["client"].cookies.set(flags.auth_cookie_name, nopub_token)
    assert cal["client"].post(
        f"/api/v1/calendar/clubs/{club_id}/training-openings",
        json={"eligible_group_id": g_conf_id, "starts_on": s["win_start"].isoformat(), "ends_on": s["win_end"].isoformat()},
        headers=_headers(),
    ).status_code == 403

    # Coach WITH can_publish succeeds, but invalid inputs are rejected.
    coach = cal["login"]("coach")
    assert coach.post(
        f"/api/v1/calendar/clubs/{club_id}/training-openings",
        json={"eligible_group_id": g_other_id, "starts_on": s["win_start"].isoformat(), "ends_on": s["win_end"].isoformat()},
        headers=_headers(),
    ).status_code == 422

    # Draft competition cannot be linked (prevents leaking draft title to club members).
    draft_comp = CalendarEvent(
        calendar_id=cal["cals"]["k"].id, event_type="competition", audience="club", status="draft",
        title="Brouillon secret", timezone="Europe/Paris",
    )
    db.add(draft_comp)
    db.commit()
    draft_comp_id = draft_comp.id
    db.expunge_all()
    assert coach.post(
        f"/api/v1/calendar/clubs/{club_id}/training-openings",
        json={"eligible_group_id": g_conf_id, "competition_event_id": draft_comp_id,
              "starts_on": s["win_start"].isoformat(), "ends_on": s["win_end"].isoformat()},
        headers=_headers(),
    ).status_code == 422

    # Valid custom window created & deleted by authorized coach.
    ok = coach.post(
        f"/api/v1/calendar/clubs/{club_id}/training-openings",
        json={"eligible_group_id": g_conf_id, "label": "Prépa 1m",
              "starts_on": s["win_start"].isoformat(), "ends_on": s["win_end"].isoformat()},
        headers=_headers(),
    )
    assert ok.status_code == 201
    oid = ok.json()["id"]
    assert coach.delete(f"/api/v1/calendar/clubs/{club_id}/training-openings/{oid}", headers=_headers()).status_code == 204


def test_calendar_still_works_when_openings_table_missing(cal, monkeypatch):
    s = _setup_kcpm_window(cal)
    club_id = cal["clubs"]["k"].id
    monkeypatch.setattr(access, "openings_schema_ready", lambda db: False)
    bob = cal["login"]("bob")
    q_from = (s["win_start"] - timedelta(days=5)).isoformat() + "T00:00:00Z"
    q_to = (s["comp_day"] + timedelta(days=3)).isoformat() + "T00:00:00Z"
    res = bob.get("/api/v1/calendar/occurrences", params={"from": q_from, "to": q_to})
    assert res.status_code == 200
    assert bob.get(f"/api/v1/calendar/clubs/{club_id}/training-openings").status_code == 503


def test_open_access_and_event_scopes_not_truncated_across_clubs(cal):
    """Two clubs with >100 total openings must never truncate open_access or event scopes."""
    from app.models.calendar import ClubTrainingOpening
    s = _setup_kcpm_window(cal)
    db = cal["db"]
    admin = db.get(AppUser, cal["users"]["admin"].id)
    manager = db.get(AppUser, cal["users"]["manager"].id)
    bob = db.get(AppUser, cal["users"]["bob"].id)
    club_k = cal["clubs"]["k"]
    club_o = cal["clubs"]["o"]
    g_conf_k = cal["groups"]["b"]
    g_other_a = cal["groups"]["o"]

    # Manager and Bob also belong to club_o; club_o has two groups (g_other_a = Débutants, g_other_b = Confirmés).
    membership.admin_add_membership(db, admin, club_o.id, manager.id, "manager")
    membership.admin_add_membership(db, admin, club_o.id, bob.id, "member")
    g_other_b = membership.create_group(db, manager, club_o.id, "other-b", "Other Confirmés")
    membership.assign_group(db, manager, club_o.id, bob.id, g_other_b.id, TODAY - timedelta(days=30))

    # Create a training occurrence in club_o's other group (g_other_a) inside the 2-week window.
    cal_other_a = db.query(Calendar).filter_by(kind="group", training_group_id=g_other_a.id).one()
    ev_other_a = CalendarEvent(
        calendar_id=cal_other_a.id, event_type="training", audience="group", status="published",
        title="Other Débutants", timezone="Europe/Paris",
    )
    db.add(ev_other_a)
    db.flush()
    inside_day = max(s["win_start"] + timedelta(days=1), TODAY + timedelta(days=2))
    if inside_day > s["win_end"]:
        inside_day = s["win_end"]
    occ_other_a = EventOccurrence(
        event_id=ev_other_a.id, occurrence_key="other-inside", is_all_day=False,
        starts_at=_paris_utc(inside_day, 18), ends_at=_paris_utc(inside_day, 20),
        window_start=_paris_utc(inside_day, 18), window_end=_paris_utc(inside_day, 20),
    )
    db.add(occ_other_a)

    # Fill club_k to its full per-club cap (100 openings, including one per extra group on comp_id)
    # so a global 100-row cap would drop club_o's opening.
    ws, we = openings.utc_bounds_for_local_dates(s["win_start"], s["win_end"], "Europe/Paris")
    for i in range(openings.MAX_OPENINGS_PER_CLUB):
        extra_g = membership.create_group(db, manager, club_k.id, f"extra-{i}", f"Extra {i}") if i < 100 else g_conf_k
        db.add(ClubTrainingOpening(
            club_id=club_k.id,
            eligible_group_id=g_conf_k.id if i == 0 else extra_g.id,
            competition_event_id=s["comp_id"],
            starts_on=s["win_start"], ends_on=s["win_end"],
            window_start=ws, window_end=we,
        ))
    # Now add club_o's opening AFTER the 100 rows of club_k (higher ID).
    db.add(ClubTrainingOpening(
        club_id=club_o.id,
        eligible_group_id=g_other_b.id,
        competition_event_id=s["comp_id"],
        starts_on=s["win_start"], ends_on=s["win_end"],
        window_start=ws, window_end=we,
    ))
    occ_other_id = occ_other_a.id
    club_o_id = club_o.id
    db.commit()
    db.expunge_all()

    # 1. Bob sees club_o's session with open_access=True (not dropped by a global 100-row cap).
    bob_client = cal["login"]("bob")
    q_from = (s["win_start"] - timedelta(days=5)).isoformat() + "T00:00:00Z"
    q_to = (s["comp_day"] + timedelta(days=3)).isoformat() + "T00:00:00Z"
    items = {o["id"]: o for o in bob_client.get("/api/v1/calendar/occurrences", params={"from": q_from, "to": q_to}).json()["items"]}
    assert occ_other_id in items and items[occ_other_id]["open_access"] is True

    # 2. Manager sees club_o's opening in event_training_openings alongside club_k's 100 openings.
    mgr_client = cal["login"]("manager")
    scopes = mgr_client.get(f"/api/v1/calendar/events/{s['comp_id']}/training-openings").json()
    by_club = {c["club_id"]: c for c in scopes["clubs"]}
    assert len(by_club[club_o_id]["openings"]) == 1


def test_transferred_member_active_absence_excludes_open_visitor(cal):
    """A member who reported absence while assigned to group A, then transferred to
    eligible group B and opted in, stays excluded from occurrence_members (matching alerts)."""
    s = _setup_kcpm_window(cal)
    db = cal["db"]
    club_id = cal["clubs"]["k"].id
    g_conf_id = cal["groups"]["b"].id
    alice_id = cal["users"]["alice"].id

    # Manager opens club training sessions to Confirmés (group B).
    mgr = cal["login"]("manager")
    assert mgr.post(
        f"/api/v1/calendar/clubs/{club_id}/training-openings",
        json={"eligible_group_id": g_conf_id, "competition_event_id": s["comp_id"]},
        headers=_headers(),
    ).status_code == 201

    # Alice (currently in group A = Débutants) reports absence on deb_inside.
    alice = cal["login"]("alice")
    assert alice.put(
        f"/api/v1/calendar/occurrences/{s['deb_inside_id']}/absence",
        json={"absent": True},
        headers=_headers(),
    ).status_code == 200

    # Coach transfers Alice from group A to group B (Confirmés) effective today (before deb_inside).
    coach = cal["login"]("coach")
    assert coach.put(
        f"/api/v1/calendar/clubs/{club_id}/group-assignment",
        json={"user_id": alice_id, "group_id": g_conf_id, "effective_from": TODAY.isoformat()},
        headers=_headers(),
    ).status_code == 200

    # Alice (now an eligible visitor in Confirmés) opts in with "Je viens".
    alice = cal["login"]("alice")
    joined = alice.put(
        f"/api/v1/calendar/occurrences/{s['deb_inside_id']}/interest",
        json={"state": "interested"},
        headers=_headers(),
    )
    assert joined.status_code == 200

    # Because her prior absence report is still active, occurrence_members & going exclude her
    # — matching calendar_alerts.suppression_reason == "absent".
    assert joined.json()["going"]["interested"] == 0
    assert {u.id for u in session_calendar.occurrence_members(db, s["deb_inside_id"]).all()} == set()
    Session = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    deb_row = db.get(EventOccurrence, s["deb_inside_id"])
    ev_row = db.get(CalendarEvent, s["ev_deb_id"])
    due = alerts.reminder_due(deb_row, ev_row)
    alerts.plan_reminders(Session, due + timedelta(minutes=5), batch=50)
    rem = db.query(CalendarAlertDelivery).filter_by(
        kind="reminder", user_id=alice_id, occurrence_id=s["deb_inside_id"]
    ).one()
    assert alerts.suppression_reason(db, rem, due + timedelta(minutes=10)) == "absent"


def test_event_detail_withholds_series_recurrence_when_only_open_access(cal):
    """Access via a temporary opening must not expose series-wide recurrence metadata."""
    from datetime import time
    from app.models.calendar import CalendarEventRecurrence, CalendarRecurrenceExclusion

    s = _setup_kcpm_window(cal)
    db = cal["db"]
    club_id = cal["clubs"]["k"].id
    g_conf_id = cal["groups"]["b"].id

    ev_deb = db.get(CalendarEvent, s["ev_deb_id"])
    ev_deb.recurrence_rule = "FREQ=WEEKLY;BYDAY=TU"
    db.add(CalendarEventRecurrence(
        event_id=ev_deb.id, weekdays=2, start_time=time(19, 0), end_time=time(21, 0),
        first_date=TODAY - timedelta(days=30), until_date=TODAY + timedelta(days=120),
        pattern_from=TODAY - timedelta(days=30),
    ))
    db.add(CalendarRecurrenceExclusion(event_id=ev_deb.id, local_date=TODAY + timedelta(days=45)))
    db.commit()
    db.expunge_all()

    mgr = cal["login"]("manager")
    assert mgr.post(
        f"/api/v1/calendar/clubs/{club_id}/training-openings",
        json={"eligible_group_id": g_conf_id, "competition_event_id": s["comp_id"]},
        headers=_headers(),
    ).status_code == 201

    # Bob (Confirmés, open-access only) sees only occurrences in the window, with series metadata withheld.
    bob = cal["login"]("bob")
    bob_ev = bob.get(f"/api/v1/calendar/events/{s['ev_deb_id']}").json()
    assert bob_ev["recurrence_rule"] is None
    assert bob_ev["recurrence"] is None
    assert bob_ev["itinerary"] == []
    assert bob_ev["changes"] == []
    assert s["deb_inside_id"] in {o["id"] for o in bob_ev["occurrences"]}
    assert s["deb_after_id"] not in {o["id"] for o in bob_ev["occurrences"]}

    # Alice (assigned to Débutants) still sees full series recurrence.
    alice = cal["login"]("alice")
    alice_ev = alice.get(f"/api/v1/calendar/events/{s['ev_deb_id']}").json()
    assert alice_ev["recurrence_rule"] == "FREQ=WEEKLY;BYDAY=TU"
    assert alice_ev["recurrence"] is not None
    assert len(alice_ev["recurrence"]["excluded_dates"]) == 1


def test_club_openings_redacts_competition_title_when_audience_becomes_private(cal):
    """If a linked competition later changes to invited-only, non-invitee members must not see its title."""
    s = _setup_kcpm_window(cal)
    db = cal["db"]
    club_id = cal["clubs"]["k"].id
    g_conf_id = cal["groups"]["b"].id

    # Published club competition linked to an opening.
    club_comp = CalendarEvent(
        calendar_id=cal["cals"]["k"].id, event_type="competition", audience="club",
        status="published", title="Sélectif Club", timezone="Europe/Paris",
    )
    db.add(club_comp)
    db.flush()
    db.add(EventOccurrence(
        event_id=club_comp.id, occurrence_key="sel-club", is_all_day=True,
        start_date=s["comp_day"], end_date=s["comp_day"] + timedelta(days=1),
        window_start=_paris_utc(s["comp_day"], 0), window_end=_paris_utc(s["comp_day"] + timedelta(days=1), 0),
    ))
    comp_id = club_comp.id
    db.commit()
    db.expunge_all()

    mgr = cal["login"]("manager")
    created = mgr.post(
        f"/api/v1/calendar/clubs/{club_id}/training-openings",
        json={"eligible_group_id": g_conf_id, "competition_event_id": comp_id},
        headers=_headers(),
    )
    assert created.status_code == 201

    # Bob sees the title while audience is "club".
    bob = cal["login"]("bob")
    items = bob.get(f"/api/v1/calendar/clubs/{club_id}/training-openings").json()["items"]
    assert items[0]["competition_title"] == "Sélectif Club"

    # Publisher later changes the competition to invited-only (Bob is not invited).
    ev = db.get(CalendarEvent, comp_id)
    ev.audience = "invited"
    db.commit()
    db.expunge_all()

    items_after = bob.get(f"/api/v1/calendar/clubs/{club_id}/training-openings").json()["items"]
    assert items_after[0]["competition_title"] is None
    assert items_after[0]["competition_event_id"] is None


def test_event_opening_scopes_paginates_clubs_via_cursor(cal, monkeypatch):
    """Club scopes paginate with after_club_id without dropping or duplicating clubs."""
    s = _setup_kcpm_window(cal)
    db = cal["db"]
    admin = db.get(AppUser, cal["users"]["admin"].id)
    manager = db.get(AppUser, cal["users"]["manager"].id)
    club_k_id, club_o_id = cal["clubs"]["k"].id, cal["clubs"]["o"].id
    membership.admin_add_membership(db, admin, club_o_id, manager.id, "manager")
    db.commit()
    db.expunge_all()

    monkeypatch.setattr(openings, "CLUB_SCOPE_PAGE_SIZE", 1)
    mgr = cal["login"]("manager")
    p1 = mgr.get(f"/api/v1/calendar/events/{s['comp_id']}/training-openings").json()
    assert len(p1["clubs"]) == 1 and p1["next_cursor"] == p1["clubs"][0]["club_id"]
    p2 = mgr.get(
        f"/api/v1/calendar/events/{s['comp_id']}/training-openings",
        params={"after_club_id": p1["next_cursor"]},
    ).json()
    assert len(p2["clubs"]) == 1 and p2["next_cursor"] is None
    assert {p1["clubs"][0]["club_id"], p2["clubs"][0]["club_id"]} == {club_k_id, club_o_id}
