"""Preparation sheets: account isolation, optimistic writes and ranked own clips."""
from datetime import datetime
from app.models.dive import Dive
from app.models.evaluation import EvaluationRequest, EvaluationRating
from tests.test_member_dive_visibility import workspace
from tests.test_calendar_domain import cal, flags


def create(client, **changes):
    payload = {"title": "Printemps", "height": "3m", "slots": [{"code": "101B", "alternatives": [{"code": "103B"}]}]}
    return client.post("/api/v1/series", json={**payload, **changes})


def update_payload(sheet, **changes):
    return {"title": sheet["title"], "height": sheet["height"], "event_id": sheet["event_id"],
            "expected_version": sheet["version"], "slots": [
                {"code": s["code"], "clip_id": s.get("clip_id"),
                 "alternatives": [{"code": a["code"], "clip_id": a.get("clip_id")} for a in s["alternatives"]]}
                for s in sheet["slots"]], **changes}


def test_draft_dd_alternatives_and_reload(workspace):
    _, login, dives, _, _ = workspace
    client = login("alice")
    response = create(client)
    assert response.status_code == 201, response.text
    sheet = response.json()
    assert sheet["height"] == "3m" and sheet["shared_with"] == []
    assert sheet["slots"][0]["dd"] > 0
    assert sheet["slots"][0]["clip"]["id"] in (dives["alice-public"], dives["alice-private"])
    assert sheet["slots"][0]["alternatives"][0]["clip"] is None
    # Empty drafts remain valid, and order/alternatives persist across reload.
    saved = client.put(f'/api/v1/series/{sheet["id"]}', json=update_payload(sheet, slots=[]))
    assert saved.status_code == 200, saved.text
    assert client.get(f'/api/v1/series/{sheet["id"]}').json()["slots"] == []
    assert client.get("/api/v1/series").json()[0]["slot_count"] == 0
    assert "no-store" in response.headers["cache-control"]


def test_private_share_read_only_revoke_and_clip_redaction(workspace):
    _, login, _, users, _ = workspace
    sheet = create(login("alice")).json()
    path = f'/api/v1/series/{sheet["id"]}'
    assert login("bob").get(path).status_code == 404
    assert login("bob").get("/api/v1/series").json() == []
    assert login("bob").put(path, json=update_payload(sheet)).status_code == 404
    shared = login("alice").put(path + "/sharing", json={"expected_version": 1, "user_ids": [users["bob"].id]})
    assert shared.status_code == 200, shared.text
    read = login("bob").get(path).json()
    assert not read["can_edit"] and read["slots"][0]["clip"] is None
    assert read["shared_with"] == [] and read["event_id"] is None
    assert login("bob").put(path + "/sharing", json={"expected_version": 2, "user_ids": []}).status_code == 404
    revoked = login("alice").put(path + "/sharing", json={"expected_version": 2, "user_ids": []})
    assert revoked.status_code == 200
    assert login("bob").get(path).status_code == 404


def test_stale_write_and_fixed_height(workspace):
    _, login, _, _, _ = workspace
    client = login("alice")
    sheet = create(client).json()
    path = f'/api/v1/series/{sheet["id"]}'
    assert client.put(path, json=update_payload(sheet, height="1m")).status_code == 422
    assert client.put(path, json=update_payload(sheet, title="Nouveau")).status_code == 200
    assert client.put(path, json=update_payload(sheet, title="Ancien")).status_code == 409
    assert client.get(path).json()["title"] == "Nouveau"


def test_clip_ownership_height_and_code_checked(workspace):
    _, login, dives, _, _ = workspace
    client = login("alice")
    for clip_id, code, height in [(dives["bob-public"], "101B", "3m"),
                                   (dives["alice-public"], "103B", "3m"),
                                   (dives["alice-public"], "101B", "1m")]:
        r = create(client, height=height, slots=[{"code": code, "clip_id": clip_id}])
        assert r.status_code == 422, r.text
    assert create(client, slots=[{"code": "101B", "clip_id": dives["alice-private"]}]).status_code == 201


def test_clip_ranking_prefers_mean_then_recent_and_excludes_other_accounts(workspace):
    db, login, dives, users, _ = workspace
    client = login("alice")
    # Set exact dates so fallback/ties are deterministic.
    a = db.get(Dive, dives["alice-public"]); a.dive_datetime = datetime(2026, 1, 1)
    b = db.get(Dive, dives["alice-private"]); b.dive_datetime = datetime(2026, 2, 1)
    db.commit()
    endpoint = "/api/v1/series/clips?code=101B&height=3m"
    assert client.get(endpoint).json()[0]["id"] == dives["alice-private"]
    request = EvaluationRequest(dive_id=dives["alice-public"], active=False, created_by_user_id=users["alice"].id)
    db.add(request); db.flush()
    db.add(EvaluationRating(request_id=request.id, evaluator_user_id=users["bob"].id,
                           score_half_steps=16, dive_code="101B", height="3m", dive_name="alice"))
    db.commit()
    ranked = client.get(endpoint).json()
    assert ranked[0]["id"] == dives["alice-public"] and ranked[0]["mean_score"] == 8
    assert len(ranked) == 2
    assert client.get("/api/v1/series/clips?code=101B&height=1m").json() == []
    assert create(client).json()["slots"][0]["clip"]["id"] == dives["alice-public"]


def test_undefined_dd_and_unknown_rules_do_not_block(workspace):
    _, login, _, _, _ = workspace
    r = create(login("alice"), slots=[{"code": "101D"}])
    assert r.status_code == 201
    assert r.json()["slots"][0]["dd"] is None
    assert create(login("alice"), slots=[{"code": "nope"}]).status_code == 422


def test_unauthenticated_cross_origin_and_unavailable_event(workspace):
    _, login, _, _, _ = workspace
    client = login("alice")
    client.cookies.clear()
    assert client.get("/api/v1/series").status_code == 401
    client = login("alice")
    assert client.post("/api/v1/series", headers={"Origin": "https://evil.example"},
                       json={"title": "x", "height": "1m"}).status_code == 403
    assert create(client, event_id=999999).status_code == 404


def test_competition_attachment_checks_visibility_and_keeps_separate_heights(cal):
    from app.models.dive_series import DiveSeries
    DiveSeries.__table__.create(cal["db"].get_bind(), checkfirst=True)
    client = cal["login"]("alice")
    event_id = cal["events"]["fed"].id
    a = create(client, height="1m", event_id=event_id)
    b = create(client, height="3m", event_id=event_id)
    assert a.status_code == b.status_code == 201, (a.text, b.text)
    listed = client.get(f"/api/v1/series?event_id={event_id}").json()
    assert {s["height"] for s in listed} == {"1m", "3m"}
    assert create(client, event_id=cal["events"]["oclub"].id).status_code == 404
    assert create(client, event_id=cal["events"]["ga"].id).status_code == 404


def test_six_default_slots_five_slot_switch_and_partial_draft_persist(workspace):
    _, login, _, _, _ = workspace
    client = login("alice")
    r = client.post("/api/v1/series", json={"title": "Six places", "height": "3m"})
    assert r.status_code == 201, r.text
    sheet = r.json()
    assert len(sheet["slots"]) == sheet["total_slots"] == 6
    assert sheet["slot_count"] == 0
    slots = [{"code": "101B"}, {"code": ""}, {"code": "201B"}, {"code": ""}, {"code": ""}]
    saved = client.put(f'/api/v1/series/{sheet["id"]}', json=update_payload(sheet, slots=slots))
    assert saved.status_code == 200, saved.text
    sheet = saved.json()
    assert [s["code"] for s in sheet["slots"]] == ["101B", "", "201B", "", ""]
    assert sheet["slot_count"] == 2 and sheet["total_slots"] == 5
    listed = client.get("/api/v1/series").json()[0]
    assert listed["slot_count"] == 2 and listed["total_slots"] == 5
    assert client.get(f'/api/v1/series/{sheet["id"]}').json()["slots"] == sheet["slots"]
    # Blank placeholders grant no means to attach a clip of a different code.
    invalid = update_payload(sheet, slots=[{"code": "", "clip_id": 1}])
    assert client.put(f'/api/v1/series/{sheet["id"]}', json=invalid).status_code == 422


def test_recorded_phase_scores_rank_clips_and_survive_manual_selection(workspace):
    db, login, dives, _, _ = workspace
    a = db.get(Dive, dives["alice-public"])
    b = db.get(Dive, dives["alice-private"])
    a.performance = "G"; a.phase1_performance = "G"; a.phase2_performance = "G"
    b.performance = "M"; b.phase1_performance = "G"; b.phase2_performance = "M"
    a.dive_datetime = datetime(2026, 1, 1)
    b.dive_datetime = datetime(2026, 2, 1)
    db.commit()
    client = login("alice")
    ranked = client.get("/api/v1/series/clips?code=101B&height=3m").json()
    assert [c["id"] for c in ranked] == [dives["alice-public"], dives["alice-private"]]
    assert ranked[0]["performance_score"] == 7
    assert ranked[1]["performance_score"] == 5.62
    assert ranked[0]["mean_score"] is None and ranked[0]["rating_count"] == 0
    sheet = create(client, slots=[{"code": "101B", "clip_id": dives["alice-private"]}]).json()
    assert sheet["slots"][0]["clip"]["performance_score"] == 5.62


def test_recent_clip_policy_is_saved_and_manual_choice_remains_pinned(workspace):
    db, login, dives, _, _ = workspace
    a = db.get(Dive, dives["alice-public"])
    b = db.get(Dive, dives["alice-private"])
    a.performance = "P"; a.phase1_performance = None; a.phase2_performance = None
    b.performance = "B"; b.phase1_performance = None; b.phase2_performance = None
    a.dive_datetime = datetime(2026, 1, 1); b.dive_datetime = datetime(2026, 2, 1)
    db.commit()
    client = login("alice")
    endpoint = "/api/v1/series/clips?code=101B&height=3m"
    assert client.get(endpoint).json()[0]["id"] == dives["alice-public"]
    assert client.get(endpoint + "&policy=recent").json()[0]["id"] == dives["alice-private"]
    sheet = create(client, clip_policy="recent", slots=[{"code": "101B"}, {"code": "101B", "clip_id": dives["alice-public"]}]).json()
    reloaded = client.get(f'/api/v1/series/{sheet["id"]}').json()
    assert reloaded["clip_policy"] == "recent"
    assert [s["clip"]["id"] for s in reloaded["slots"]] == [dives["alice-private"], dives["alice-public"]]
    changed = client.put(f'/api/v1/series/{sheet["id"]}', json=update_payload(sheet, clip_policy="best")).json()
    assert changed["clip_policy"] == "best"
    assert changed["slots"][0]["clip"]["id"] == dives["alice-public"]
