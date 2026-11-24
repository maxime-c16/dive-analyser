"""Official meet results: DiveRecorder PDF parsing, import, visibility."""
from datetime import date
from decimal import Decimal

import pytest

from tests.meet_pdf_fixture import HEADER, SAMPLE_LINES, make_pdf
from tests.test_calendar_domain import TODAY, _event, _occ, cal, flags  # noqa: F401
from app.api.v1 import meet_results as meet_api
from app.models.meet_results import MeetResult, MeetResultDive, MeetResultEntry, MeetResultEvent
from app.services.meet_results_pdf import MeetPdfError, parse_text

PDF = {"Content-Type": "application/pdf"}


def text(*lines):
    return "\n".join(lines)


# --- Parser ------------------------------------------------------------------

def test_parses_sample_sheet_with_penalties_and_failed_dive():
    meet = parse_text(text(*SAMPLE_LINES))
    assert meet.meet_date == date(2026, 11, 22)
    assert [e.title for e in meet.events] == ["Elite - Dames - 3m", "Elite - Messieurs - HV"]
    assert [e.board for e in meet.events] == ["3m", "HV"]
    assert meet.warnings == []
    berta = meet.events[0].entries[1]
    assert (berta.rank, berta.diver_name, berta.birth_year, berta.club_name) == (2, "Berta EXEMPLE", 2003, "Club Beta")
    # "45,00 4double": the glued 4 is the penalty code, not a number.
    assert berta.dives[1].penalty == 4 and berta.total == Decimal("45.00")
    failed = meet.events[1].entries[0].dives[0]
    assert failed.penalty == 1 and failed.points == 0 and failed.height == Decimal("7.5")
    assert meet.events[0].entries[0].dives[0].judge_half_steps == [12, 13, 12, 14, 13]


def test_page_break_repeats_title_and_continues_until_places_restart():
    lines = [HEADER, "Elite - Dames - 3m", "Ann A (2001) -- Club 1",
             "201B 3 1,8 6,0 6,0 6,0   18,0 32,40 32,40  x",
             HEADER, "Elite - Dames - 3m", "Bea B (2002) -- Club 2",
             "201B 3 1,8 5,0 5,0 5,0   15,0 27,00 27,00  x",
             HEADER, "Elite - Dames - 3m", "Cid C (2003) -- Club 1",
             "201B 3 1,8 7,0 7,0 7,0   21,0 37,80 37,80  x"]
    meet = parse_text(text(*lines))
    assert [[en.diver_name for en in e.entries] for e in meet.events] == [["Ann A", "Bea B"], ["Cid C"]]


def test_round_place_column_synchro_pairs_and_exit_states():
    lines = [HEADER, "Synchro - Dames - 3m",
             "Ann A (2001) -- Club X 1",
             "Bea B (2002) -- Club Y",
             # 11 judges: J1–J7, sum, points, total, J8–J11, then the place after this round.
             "301B 3 1,9 6,0 6,0 6,0 6,5 6,5 6,0 6,0   30,0 34,20 34,20 6,0 6,5 6,0 6,0 1  renversé",
             HEADER, "Elite - Messieurs - 3m",
             "Dan D -- Club Z (invité) (abandon)",
             "Eli E (1999) -- Club Z  #12345 1",
             "103B 3 1,6 5,0 5,0 5,0   15,0 24,00 24,00 1  avant",
             "Fay F (1998) -- Club Z (disqualifié) 2"]
    meet = parse_text(text(*lines))
    pair = meet.events[0].entries[0]
    assert (pair.diver_name, pair.club_name, pair.rank, pair.birth_year) == ("Ann A / Bea B", "Club X / Club Y", 1, None)
    assert len(pair.dives[0].judge_half_steps) == 11 and pair.dives[0].penalty is None
    dan, eli, fay = meet.events[1].entries
    assert (dan.status, dan.guest, dan.rank, dan.dives) == ("withdrawn", True, None, [])
    assert (eli.club_name, eli.rank, eli.dives[0].points) == ("Club Z", 1, Decimal("24.00"))
    assert (fay.status, fay.rank) == ("disqualified", 2)
    assert meet.warnings == []


def test_arithmetic_mismatch_is_a_warning_not_a_rewrite():
    meet = parse_text(text(HEADER, "E - 3m", "Ann A (2001) -- C 1", "201B 3 1,8 6,0 6,0 6,0   18,0 30,00 31,00  x"))
    dive = meet.events[0].entries[0].dives[0]
    assert (dive.points, dive.running_total) == (Decimal("30.00"), Decimal("31.00"))
    assert len(meet.warnings) == 2


def test_rejects_files_without_results():
    with pytest.raises(MeetPdfError) as err:
        parse_text("just some text\nnothing here")
    assert err.value.code == "no_results"


# --- API ---------------------------------------------------------------------

@pytest.fixture()
def meet(cal):  # noqa: F811
    db = cal["db"]
    event = _event(db, cal["cals"]["k"], "Championnats IDF", "club", event_type="competition")
    _occ(db, event, "meet-1", (date(2026, 11, 22) - TODAY).days)
    training = _event(db, cal["cals"]["k"], "Training", "club")
    db.commit()
    return dict(cal, meet_id=event.id, training_id=training.id)


def url(event_id, tail=""):
    return f"/api/v1/calendar/events/{event_id}/results{tail}"


def test_publisher_previews_then_saves_and_members_read(meet):
    coach = meet["login"]("coach")
    empty = coach.get(url(meet["meet_id"]))
    assert empty.status_code == 200 and empty.json() == {"can_import": True, "available": False, "results": None, "can_manage_links": False}

    preview = coach.post(url(meet["meet_id"], "/preview"), content=make_pdf(), headers=PDF)
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert (body["entry_count"], body["dive_count"], body["replaces"], body["date_matches"]) == (3, 6, False, True)
    assert meet["db"].query(MeetResult).count() == 0  # preview writes nothing

    saved = coach.put(url(meet["meet_id"], "?name=idf.pdf"), content=make_pdf(), headers=PDF)
    assert saved.status_code == 200, saved.text
    results = saved.json()["results"]
    assert results["source_name"] == "idf.pdf"
    women = results["events"][0]
    assert [e["diver_name"] for e in women["entries"]] == ["Anna TESTA", "Berta EXEMPLE"]
    assert women["entries"][1]["dives"][1] == {
        "dive_code": "304C", "height": 3.0, "dd": 2.1, "judges": [4.0, 3.5, 2.5, 3.5, 3.0], "cumul": 10.0,
        "points": 21.0, "running_total": 45.0, "penalty": 4}

    summary = meet["login"]("alice").get(url(meet["meet_id"], "?summary=true")).json()
    assert summary == {"can_import": False, "available": True, "results": None, "can_manage_links": False}
    alice = meet["login"]("alice").get(url(meet["meet_id"]))
    assert alice.status_code == 200
    assert alice.json()["can_import"] is False and alice.json()["results"]["events"][1]["title"] == "Elite - Messieurs - HV"
    assert meet["login"]("alice").put(url(meet["meet_id"]), content=make_pdf(), headers=PDF).status_code == 403
    # Not visible to another club: same answer as a missing event.
    assert meet["login"]("outsider").get(url(meet["meet_id"])).status_code == 404


def test_reimport_replaces_atomically_and_delete_cascades(meet):
    coach, db = meet["login"]("coach"), meet["db"]
    assert coach.put(url(meet["meet_id"]), content=make_pdf(), headers=PDF).status_code == 200
    shorter = make_pdf(SAMPLE_LINES[:11])
    assert coach.post(url(meet["meet_id"], "/preview"), content=shorter, headers=PDF).json()["replaces"] is True
    assert coach.put(url(meet["meet_id"]), content=shorter, headers=PDF).status_code == 200
    db.expire_all()
    assert (db.query(MeetResult).count(), db.query(MeetResultEvent).count(), db.query(MeetResultEntry).count(),
            db.query(MeetResultDive).count()) == (1, 1, 1, 2)
    # A broken file never removes the stored results.
    assert coach.put(url(meet["meet_id"]), content=b"%PDF-1.4 broken", headers=PDF).status_code == 422
    assert db.query(MeetResultDive).count() == 2
    assert coach.delete(url(meet["meet_id"])).status_code == 204
    db.expire_all()
    assert (db.query(MeetResult).count(), db.query(MeetResultDive).count()) == (0, 0)
    assert coach.delete(url(meet["meet_id"])).status_code == 404


def test_rejects_non_competitions_non_pdfs_oversize_and_foreign_origin(meet, monkeypatch):
    coach = meet["login"]("coach")
    training = coach.put(url(meet["training_id"]), content=make_pdf(), headers=PDF)
    assert training.status_code == 422 and training.json()["detail"]["code"] == "not_competition"
    assert coach.get(url(meet["training_id"])).json()["can_import"] is False
    not_pdf = coach.post(url(meet["meet_id"], "/preview"), content=b"hello", headers=PDF)
    assert not_pdf.status_code == 422 and not_pdf.json()["detail"]["code"] == "not_pdf"
    monkeypatch.setattr(meet_api, "MAX_PDF_BYTES", 100)
    assert coach.post(url(meet["meet_id"], "/preview"), content=make_pdf(), headers=PDF).status_code == 413
    foreign = coach.put(url(meet["meet_id"]), content=b"%PDF", headers={**PDF, "Origin": "https://evil.invalid"})
    assert foreign.status_code == 403


# --- Automatic account links ----------------------------------------------------

def _entry(name, club="KCPM Montreu", year=2001):
    from types import SimpleNamespace
    return SimpleNamespace(diver_name=name, club_name=club, birth_year=year)


def test_links_only_unambiguous_club_members(cal):  # noqa: F811
    from app.models.diver import Diver
    from app.models.user_auth import UserDiverAccess
    from app.services.meet_result_links import auto_links
    db, u = cal["db"], cal["users"]
    nina = Diver(display_name="NINA", canonical_name="nina")
    db.add(nina); db.flush()
    db.add(UserDiverAccess(user_id=u["una"].id, diver_id=nina.id, access_kind="OWNER"))
    db.commit()
    entries = [
        _entry("Alice MARTIN"),                      # 0 first name on the account
        _entry("Alice MARTIN"),                      # 1 same person in another event
        _entry("Nina BÉRAUD"),                       # 2 first name on an owned diver ("Una" owns NINA)
        _entry("Bob DURAND"), _entry("Bob PETIT"),   # 3, 4 two Bobs: neither
        _entry("Coach LAMBERT", club="Club Inconnu 2024"),  # 5 not an app club
        _entry("Una ROUX", club="Other Club"),       # 6 other club has no Una
        _entry("Alice MARTIN / Bob DURAND"),         # 7 synchro pair
        _entry("Manager KCPM", club="KCPM"),         # 8 short name; surname tokens all caps
    ]
    links = auto_links(db, entries)
    assert links == {0: u["alice"].id, 1: u["alice"].id, 2: u["una"].id, 8: u["manager"].id}


def test_full_name_beats_first_name_and_accents_are_ignored(cal):  # noqa: F811
    from app.services.meet_result_links import auto_links
    db, u = cal["db"], cal["users"]
    db.get(type(u["bob"]), u["bob"].id).display_name = "Éloïse Testard"
    db.get(type(u["coach"]), u["coach"].id).display_name = "Eloise"
    db.commit()
    # Coach matches the first name only; Bob matches the full name: the stronger tier wins.
    assert auto_links(db, [_entry("Éloïse TESTARD")]) == {0: u["bob"].id}


def test_links_are_stored_and_shown_only_to_club_mates(cal):  # noqa: F811
    db = cal["db"]
    event = _event(db, cal["cals"]["k"], "Open meet", "community", event_type="competition")
    _occ(db, event, "open-1", 1)
    db.commit()
    eid = event.id
    lines = [HEADER, "Elite - Dames - 3m", "Alice MARTIN (2001) -- KCPM Montreuil 1",
             "201B 3 1,8 6,0 6,0 6,0   18,0 32,40 32,40  x"]
    coach = cal["login"]("coach")
    assert coach.post(url(eid, "/preview"), content=make_pdf(lines), headers=PDF).json()["linked_count"] == 1
    assert coach.put(url(eid), content=make_pdf(lines), headers=PDF).status_code == 200
    db.expire_all()
    assert db.query(MeetResultEntry.user_id).scalar() == cal["users"]["alice"].id

    def row(name):
        return cal["login"](name).get(url(eid)).json()["results"]["events"][0]["entries"][0]
    assert row("alice")["is_me"] is True and row("alice")["account"]["display_name"] == "Alice"
    assert row("bob")["is_me"] is False and row("bob")["account"]["user_id"] == cal["users"]["alice"].id
    outsider = row("outsider")  # community event, other club: sees the sheet, not the account
    assert outsider["diver_name"] == "Alice MARTIN" and outsider["account"] is None


# --- Administrators manage links ------------------------------------------------

def _club_meet(cal, title, lines):  # noqa: F811
    from app.services import calendar_access as access
    from app.services.calendar_membership import admin_add_membership
    db, u = cal["db"], cal["users"]
    if access.active_membership(db, u["admin"], cal["clubs"]["k"].id) is None:
        # Like the real admin: a member of the club whose meets they manage.
        admin_add_membership(db, u["admin"], cal["clubs"]["k"].id, u["admin"].id, "member")
    event = _event(db, cal["cals"]["k"], title, "club", event_type="competition")
    _occ(db, event, f"{title}-1", 1)
    db.commit()
    eid = event.id
    assert cal["login"]("coach").put(url(eid), content=make_pdf(lines), headers=PDF).status_code == 200
    return eid


def _rows(cal, who, eid):
    return {e["diver_name"]: e for ev in cal["login"](who).get(url(eid)).json()["results"]["events"] for e in ev["entries"]}


def test_admin_ties_person_across_meets_and_frees_the_auto_match(cal):  # noqa: F811
    u = cal["users"]
    dive = "201B 3 1,8 6,0 6,0 6,0   18,0 32,40 32,40  x"
    sheet = [HEADER, "Elite - 3m", "Alice MARTIN (2001) -- KCPM Montreuil 1", dive,
             "Mathilde ROUX (2003) -- KCPM Montreuil 2", dive.replace("32,40 32,40", "32,40 32,40")]
    first = _club_meet(cal, "Meet A", sheet)
    second = _club_meet(cal, "Meet B", sheet)
    rows = _rows(cal, "admin", first)
    assert rows["Alice MARTIN"]["account"]["user_id"] == u["alice"].id and rows["Alice MARTIN"]["link_source"] == "auto"
    assert rows["Mathilde ROUX"]["account"] is None and rows["Mathilde ROUX"]["linkable"] is True
    # Members never see the bookkeeping.
    assert _rows(cal, "bob", first)["Alice MARTIN"]["link_source"] is None

    admin = cal["login"]("admin")
    found = admin.get("/api/v1/calendar/admin/meet-accounts?q=ali").json()["items"]
    assert [a["user_id"] for a in found] == [u["alice"].id]
    # Alice's account actually belongs to Mathilde: tie it, in every meet.
    mathilde = rows["Mathilde ROUX"]["id"]
    assert admin.put(f"/api/v1/calendar/results/entries/{mathilde}/link", json={"user_id": u["alice"].id}).status_code == 204
    for eid in (first, second):
        after = _rows(cal, "admin", eid)
        assert after["Mathilde ROUX"]["account"]["user_id"] == u["alice"].id
        assert after["Mathilde ROUX"]["link_source"] == "admin"
        assert after["Alice MARTIN"]["account"] is None  # the account left the automatic pool

    # A later import keeps the decision.
    third = _club_meet(cal, "Meet C", sheet)
    assert _rows(cal, "admin", third)["Mathilde ROUX"]["account"]["user_id"] == u["alice"].id

    # Back to automatic: everything returns to the matcher's answer.
    assert admin.delete(f"/api/v1/calendar/results/entries/{mathilde}/link").status_code == 204
    for eid in (first, second, third):
        back = _rows(cal, "admin", eid)
        assert back["Alice MARTIN"]["account"]["user_id"] == u["alice"].id and back["Mathilde ROUX"]["account"] is None


def test_admin_can_forbid_a_link_and_only_admins_manage(cal):  # noqa: F811
    sheet = [HEADER, "Elite - 3m", "Alice MARTIN (2001) -- KCPM Montreuil 1",
             "201B 3 1,8 6,0 6,0 6,0   18,0 32,40 32,40  x"]
    eid = _club_meet(cal, "Meet N", sheet)
    entry = _rows(cal, "admin", eid)["Alice MARTIN"]["id"]
    link = f"/api/v1/calendar/results/entries/{entry}/link"
    for who in ("coach", "alice"):
        assert cal["login"](who).put(link, json={"user_id": None}).status_code == 403
        assert cal["login"](who).delete(link).status_code == 403
    assert cal["login"]("coach").get("/api/v1/calendar/admin/meet-accounts?q=ali").status_code == 403
    admin = cal["login"]("admin")
    assert admin.put(link, json={"user_id": 999999}).json()["detail"]["code"] == "account_not_found"
    assert admin.put(link, json={"user_id": None}).status_code == 204
    row = _rows(cal, "admin", eid)["Alice MARTIN"]
    assert row["account"] is None and row["link_source"] == "admin"
    assert _rows(cal, "alice", eid)["Alice MARTIN"]["is_me"] is False
    assert admin.put(link, json={"user_id": None}, headers={"Origin": "https://evil.invalid"}).status_code == 403


def test_truncated_candidate_set_links_nobody(cal, monkeypatch):  # noqa: F811
    """A cap hit must never turn an ambiguous name into a unique match."""
    from app.services import meet_result_links as links
    db, u = cal["db"], cal["users"]
    assert links.auto_links(db, [_entry("Alice MARTIN")]) == {0: u["alice"].id}
    monkeypatch.setattr(links, "MAX_CANDIDATE_ROWS", 2)  # the club has more active members than that
    assert links.auto_links(db, [_entry("Alice MARTIN")]) == {}
