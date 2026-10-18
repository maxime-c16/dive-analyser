"""Snapshot parsing, current authorization, cancellation and DST; no sends."""
from datetime import datetime, timedelta
from app.models.calendar import CalendarEvent, EventOccurrence, EventInvitation
from app.services.calendar_ics import render
from tests.test_calendar_domain import cal, flags  # noqa: F401

API = "/api/v1/calendar"


def parse(content):
    assert content.endswith(b"\r\n")
    assert all(len(line) <= 75 for line in content.split(b"\r\n"))
    lines = content.replace(b"\r\n ", b"").decode().split("\r\n")
    assert lines.count("BEGIN:VEVENT") == lines.count("END:VEVENT") == 1
    return dict(line.split(":", 1) for line in lines if ":" in line)


def export(cal, key, who="alice"):
    return cal["login"](who).get(f"{API}/occurrences/{cal['occ'][key].id}/export.ics")


def test_authenticated_export_current_visibility_no_media(cal, flags):
    response = export(cal, "ga")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["content-disposition"] == f'attachment; filename="calendar-{cal["occ"]["ga"].id}.ics"'
    assert response.headers["content-type"].startswith("text/calendar")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert parse(response.content)["SUMMARY"] == "Groupe A training"
    assert not any(k in response.text for k in ("ATTENDEE", "filmed_session", "chat.example", "example.test"))
    for key in ("gb", "oclub", "draft"):
        assert export(cal, key).status_code == 404
    assert export(cal, "invite", "outsider").status_code == 404
    assert export(cal, "invite", "una").status_code == 200
    db = cal["db"]
    invitation = db.query(EventInvitation).filter_by(event_id=cal["events"]["invite"].id).one()
    invitation.status = "revoked"
    invitation.revoked_at = datetime.utcnow()
    db.commit()
    assert export(cal, "invite", "una").status_code == 404
    cal["client"].cookies.clear()
    assert cal["client"].get(f"{API}/occurrences/{cal['occ']['ga'].id}/export.ics").status_code == 401
    flags.calendar_enabled = False
    assert export(cal, "ga").status_code == 404


def test_all_day_cancel_stable_uid_sequence(cal):
    first = parse(export(cal, "club").content)
    db = cal["db"]
    occurrence = db.get(EventOccurrence, cal["occ"]["club"].id)
    assert first["DTSTART;VALUE=DATE"] == occurrence.start_date.strftime("%Y%m%d")
    assert first["DTEND;VALUE=DATE"] == occurrence.end_date.strftime("%Y%m%d")
    event = db.get(CalendarEvent, occurrence.event_id)
    result = cal["login"]("coach").post(f"{API}/events/{event.id}/cancel", json={"expected_version": event.version})
    assert result.status_code == 200, result.text
    after = parse(export(cal, "club").content)
    assert after["UID"] == first["UID"] and after["STATUS"] == "CANCELLED"
    assert int(after["SEQUENCE"]) > int(first["SEQUENCE"])
    assert after["DTSTART;VALUE=DATE"] == first["DTSTART;VALUE=DATE"]
    datetime.strptime(after["DTSTAMP"], "%Y%m%dT%H%M%SZ")


def test_utf8_folding_injection_independent_versions(cal):
    db = cal["db"]
    event = db.get(CalendarEvent, cal["events"]["ga"].id)
    occurrence = db.get(EventOccurrence, cal["occ"]["ga"].id)
    event.title = "é🦆" * 45 + "\r\nEND:VEVENT\r\nBEGIN:VEVENT"
    event.description = "back\\slash;comma,\nline\t"
    event.venue_name = 'bad/../../name"\r\nX-EVIL:yes'
    db.commit()
    first = parse(export(cal, "ga").content)
    assert "\\nEND:VEVENT\\nBEGIN:VEVENT" in first["SUMMARY"]
    assert "back\\\\slash\\;comma\\,\\nline" in first["DESCRIPTION"]
    assert "X-EVIL" not in first
    from app.services.calendar_ics import text
    assert text("a\x00\tb") == "ab"
    event = db.get(CalendarEvent, cal["events"]["ga"].id)
    occurrence = db.get(EventOccurrence, cal["occ"]["ga"].id)
    event.version += 4
    a = parse(render(event, occurrence).encode())
    occurrence.version += 1
    b = parse(render(event, occurrence).encode())
    assert a["UID"] == b["UID"] == first["UID"]
    assert int(b["SEQUENCE"]) == int(a["SEQUENCE"]) + 1


def test_dst_instants(cal):
    db = cal["db"]
    event = db.get(CalendarEvent, cal["events"]["ga"].id)
    occurrence = db.get(EventOccurrence, cal["occ"]["ga"].id)
    for start in (datetime(2027, 3, 28, 0, 30), datetime(2027, 10, 31, 0, 30)):
        occurrence.starts_at, occurrence.ends_at = start, start + timedelta(hours=2)
        body = parse(render(event, occurrence).encode())
        assert datetime.strptime(body["DTSTART"], "%Y%m%dT%H%M%SZ") == start
        assert body["DTEND"] == (start + timedelta(hours=2)).strftime("%Y%m%dT%H%M%SZ")
        assert body["X-DIVE-ANALYSER-TIMEZONE"] == "Europe/Paris"
