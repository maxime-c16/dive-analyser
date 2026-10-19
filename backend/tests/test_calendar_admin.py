"""Administration remains usable while public calendar access stays closed."""
from datetime import datetime, timedelta
import json

from sqlalchemy.orm import sessionmaker

from tests.test_calendar_domain import cal, flags  # noqa: F401
from app.models.calendar import CalendarLaunchControl, ClubMembership
from app.models.security_audit_log import SecurityAuditEvent
from app.services import calendar_launch, calendar_alerts

API = "/api/v1/admin/clubs"


def control(cal, **values):
    db = cal["db"]
    row = db.get(CalendarLaunchControl, 1)
    if row is None:
        row = CalendarLaunchControl(id=1)
        db.add(row)
    for key, value in values.items():
        setattr(row, key, value)
    db.commit()
    return row


def test_prepare_while_off_is_admin_only_and_does_not_open_public_routes(cal, flags):
    flags.calendar_enabled = False
    c = cal["client"]
    assert c.get(API).status_code == 401
    assert cal["login"]("alice").get(API).status_code == 403
    assert cal["login"]("coach").get(API).status_code == 403
    admin = cal["login"]("admin")
    response = admin.get(API)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert len(response.json()["items"]) == 2
    assert admin.get("/api/v1/calendar/me").status_code == 404
    assert admin.get("/api/v1/auth/me").json()["features"]["calendar"] is False
    created = admin.post(API, json={"slug": "new-club", "name": "New club"})
    assert created.status_code == 201, created.text
    assert created.json()["self_join_enabled"] is False
    assert admin.post(API, json={"slug": "bad-origin", "name": "No"}, headers={"Origin": "https://evil.invalid"}).status_code == 403


def test_admin_prepares_roster_without_joining_and_preserves_last_manager(cal, flags):
    flags.calendar_enabled = False
    c, db = cal["login"]("admin"), cal["db"]
    cid = cal["clubs"]["k"].id
    m = next(m for m in c.get(f"{API}/{cid}").json()["members"] if m["display_name"] == "Alice")
    mid = m["membership"]["id"]
    assert c.patch(f"{API}/{cid}/memberships/{mid}", json={"role": "coach", "can_publish": True}).status_code == 200
    group = c.post(f"{API}/{cid}/groups", json={"slug": "new-group", "name": "New group"})
    assert group.status_code == 201
    assert c.put(f"{API}/{cid}/group-assignment", json={"user_id": m["membership"]["user_id"], "group_id": group.json()["id"]}).status_code == 200
    manager_id = db.query(ClubMembership.id).filter_by(club_id=cid, role="manager").scalar()
    assert c.patch(f"{API}/{cid}/memberships/{manager_id}", json={"role": "member"}).status_code == 409
    assert c.post(f"{API}/{cid}/memberships/{manager_id}/end").status_code == 409
    assert c.post(f"{API}/{cid}/memberships", json={"user_id": cal["users"]["outsider"].id, "role": "manager"}).status_code == 201
    assert c.post(f"{API}/{cid}/memberships", json={"user_id": cal["users"]["outsider"].id}).status_code == 409
    assert db.query(SecurityAuditEvent).filter_by(event_type="club_administration").count() >= 4


def test_roster_cursor_pages_do_not_silently_truncate(cal):
    from app.models.user_auth import AppUser
    from app.services.calendar_membership import admin_add_membership
    db, cid = cal["db"], cal["clubs"]["k"].id
    for i in range(105):
        u = AppUser(email=f"page-{i}@example.test", display_name=f"Page {i}", role="friend", is_admin=False, is_active=True)
        db.add(u); db.flush()
        admin_add_membership(db, cal["users"]["admin"], cid, u.id, "member")
    db.commit()
    c = cal["login"]("admin")
    first = c.get(f"{API}/{cid}").json()
    assert len(first["members"]) == 100 and first["next_cursor"]
    second = c.get(f"{API}/{cid}?after={first['next_cursor']}").json()
    assert len(second["members"]) == 10 and second["next_cursor"] is None
    assert not {m["membership"]["id"] for m in first["members"]} & {m["membership"]["id"] for m in second["members"]}


def test_activation_is_gated_pause_is_immediate_and_shared_with_auth(cal, flags):
    flags.calendar_enabled = False
    cid, db = cal["clubs"]["k"].id, cal["db"]
    c = cal["login"]("admin")
    checks = dict(sources_reviewed=True, roles_reviewed=True, device_tested=True, retention_reviewed=True, timer_verified=True)
    row = control(cal, enabled=False)
    assert c.put(f"{API}/{cid}/activation", json={"enabled": True, **checks}).status_code == 409
    assert c.put(f"{API}/{cid}/group-assignment", json={"user_id": cal["users"]["una"].id, "group_id": cal["groups"]["a"].id}).status_code == 200
    control(cal, probe_count=2, last_probe_at=datetime.utcnow())
    assert c.put(f"{API}/{cid}/activation", json={"enabled": True}).status_code == 409
    response = c.put(f"{API}/{cid}/activation", json={"enabled": True, **checks})
    assert response.status_code == 200, response.text
    assert c.get("/api/v1/auth/me").json()["features"]["calendar"] is True
    assert c.get("/api/v1/calendar/me").status_code == 200
    assert c.put(f"{API}/{cid}/activation", json={"enabled": False}).status_code == 200
    assert c.get("/api/v1/calendar/me").status_code == 404
    assert not calendar_launch.enabled(db)
    assert c.get("/api/v1/auth/me").json()["features"]["calendar"] is False
    events = [json.loads(e.metadata_json)["action"] for e in db.query(SecurityAuditEvent).filter_by(event_type="club_administration")]
    assert events == ["assign_group", "activate", "pause"]


def test_disabled_worker_observations_do_not_send_and_expire(cal, flags):
    # A database pause wins over the legacy environment default too.
    flags.calendar_enabled = True
    row = control(cal, enabled=False)
    factory = sessionmaker(bind=cal["db"].get_bind())
    now = datetime.utcnow()
    calls = []
    assert calendar_alerts.run_once(factory, now=now, sender=lambda *a: calls.append(a))["status"] == "disabled"
    assert calendar_alerts.run_once(factory, now=now + timedelta(seconds=20))["status"] == "disabled"
    cal["db"].refresh(row)
    assert row.probe_count == 1
    calendar_alerts.run_once(factory, now=now + timedelta(minutes=1))
    cal["db"].refresh(row)
    assert calendar_launch.probe_ready(row, now + timedelta(minutes=1))
    assert not calendar_launch.probe_ready(row, now + timedelta(minutes=17))
    assert not calls


def test_staged_sources_cannot_escape_private_storage(cal, tmp_path, monkeypatch):
    monkeypatch.setenv("CALENDAR_PRIVATE_ROOT", str(tmp_path))
    cid, c = cal["clubs"]["k"].id, cal["login"]("admin")
    folder = tmp_path / "inbox" / "demo"
    folder.mkdir(parents=True)
    (folder / "bundle.json").write_text(json.dumps({"sources": {"beginners": {"file": "/etc/passwd"}}}))
    payload = {"bundle_id": "demo", "season_start": "2026-09-01", "groups": {"beginners": cal["groups"]["a"].id}}
    assert c.post(f"{API}/{cid}/imports/preview", json=payload).status_code == 422
    payload["bundle_id"] = ".."
    assert c.post(f"{API}/{cid}/imports/preview", json=payload).status_code == 422
    payload["bundle_id"] = "demo"
    payload["groups"]["beginners"] = cal["groups"]["o"].id
    assert c.post(f"{API}/{cid}/imports/apply", json=payload).status_code == 422


def test_reviewed_import_applies_once_and_stale_preview_is_refused(cal, tmp_path, monkeypatch):
    from tests.test_calendar_task03 import synthetic_bundle
    from app.models.calendar import EventOccurrence
    monkeypatch.setenv("CALENDAR_PRIVATE_ROOT", str(tmp_path))
    folder = tmp_path / "inbox" / "season"
    folder.mkdir(parents=True)
    path = synthetic_bundle(folder)
    path.rename(folder / "bundle.json")
    c, cid = cal["login"]("admin"), cal["clubs"]["k"].id
    body = {"bundle_id": "season", "season_start": "2026-09-01",
            "groups": {"beginners": cal["groups"]["a"].id, "advanced": cal["groups"]["b"].id}}
    url = f"{API}/{cid}/imports"
    assert c.get(url).json()["items"] == [{"id": "season", "label": "season"}]
    preview = c.post(f"{url}/preview", json=body)
    assert preview.status_code == 200, preview.text
    plan = preview.json()
    assert plan["summary"]["training"]["create"] == 5
    assert str(tmp_path) not in preview.text and "SECRET" not in preview.text
    count = cal["db"].query(EventOccurrence).count()
    reviewed = {**body, "batch_id": plan["batch_id"], "plan_hash": plan["plan_hash"]}
    assert c.post(f"{url}/apply", json=reviewed).status_code == 200
    assert cal["db"].query(EventOccurrence).count() == count + 6  # 5 sessions + 1 draft meet
    assert c.post(f"{url}/apply", json=reviewed).status_code == 409
    plan2 = c.post(f"{url}/preview", json=body).json()
    assert plan2["summary"]["training"]["unchanged"] == 5
    assert plan2["summary"]["training"]["create"] == 0
    # Corrected source bytes invalidate the reviewed hash rather than silently
    # applying another proposal with the old confirmation.
    bundle = json.loads((folder / "bundle.json").read_text())
    bundle["training_occurrences"][0]["venue_code"] = "INSEP"
    (folder / "bundle.json").write_text(json.dumps(bundle))
    assert c.post(f"{url}/apply", json={**body, "batch_id": plan2["batch_id"], "plan_hash": plan2["plan_hash"]}).status_code == 409


def test_bulk_roles_are_atomic_cross_club_safe_and_keep_a_manager(cal):
    c, db, cid = cal["login"]("admin"), cal["db"], cal["clubs"]["k"].id
    rows = c.get(f"{API}/{cid}").json()["members"]
    ids = {m["display_name"]: m["membership"]["id"] for m in rows}
    url = f"{API}/{cid}/members/bulk"
    extra = c.post(f"{API}/{cid}/memberships", json={"user_id": cal["users"]["outsider"].id, "role": "manager"}).json()["id"]
    # One manager is changed first, then the batch tries to remove the last manager:
    # the whole operation must fail, including any previous row changes.
    assert c.post(url, json={"action": "role", "ids": [ids["Manager"], extra], "role": "member"}).status_code == 409
    after = {m["display_name"]: m["membership"]["role"] for m in c.get(f"{API}/{cid}").json()["members"]}
    assert after["Manager"] == "manager" and after["Outsider"] == "manager"
    foreign_id = db.query(ClubMembership.id).filter_by(club_id=cal["clubs"]["o"].id, role="member").scalar()
    assert c.post(url, json={"action": "remove", "ids": [ids["Alice"], foreign_id]}).status_code == 409
    response = c.post(url, json={"action": "role", "ids": [ids["Alice"], ids["Bob"]], "role": "coach", "can_publish": True})
    assert response.status_code == 200 and response.json()["changed"] == 2
    rows = c.get(f"{API}/{cid}").json()["members"]
    assert all(m["membership"]["role"] == "coach" and m["membership"]["can_publish"] for m in rows if m["display_name"] in ("Alice", "Bob"))
    assert c.post(url, json={"action": "remove", "ids": list(range(1, 102))}).status_code == 422
    assert c.post(url, json={"action": "remove", "ids": [ids["Alice"], ids["Alice"]]}).status_code == 422


def test_bulk_add_and_assign_all_or_nothing(cal):
    c, db, cid = cal["login"]("admin"), cal["db"], cal["clubs"]["k"].id
    rows = c.get(f"{API}/{cid}").json()["members"]
    ids = {m["display_name"]: m["membership"]["id"] for m in rows}
    url = f"{API}/{cid}/members/bulk"
    # Existing membership in a later target refuses the entire attachment batch.
    outsider, alice = cal["users"]["admin"].id, cal["users"]["alice"].id
    assert c.post(url, json={"action": "add", "ids": [outsider, alice], "role": "member"}).status_code == 409
    assert not db.query(ClubMembership.id).filter_by(club_id=cid, user_id=outsider).first()
    body = {"action": "group", "ids": [ids["Alice"], ids["Bob"]], "group_id": cal["groups"]["a"].id,
            "effective_from": datetime.utcnow().date().isoformat()}
    assert c.post(url, json=body).json()["changed"] == 2
    rows = c.get(f"{API}/{cid}").json()["members"]
    assert all(m["assignment"]["group_id"] == body["group_id"] for m in rows if m["display_name"] in ("Alice", "Bob"))
    assert cal["login"]("manager").post(url, json=body).status_code == 403


def test_account_candidates_exclude_attached_and_inactive_accounts(cal):
    c, cid = cal["login"]("admin"), cal["clubs"]["k"].id
    url = f"{API}/{cid}/candidates"
    assert c.get(url, params={"q": "Alice"}).json()["items"] == []
    assert c.get(url, params={"q": "idle"}).json()["items"] == []
    found = c.get(url, params={"q": "Outsider"}).json()["items"]
    assert [u["user_id"] for u in found] == [cal["users"]["outsider"].id]
    assert c.get(url, params={"q": "%"}).json()["items"] == []
    assert c.get(url, params={"q": " "}).json()["items"] == []
