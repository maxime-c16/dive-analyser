import pytest
from fastapi import HTTPException
from app.services.judge_room import Room, ghost_scores, points, truth
from app.api.v1.judge_rooms import player_for
from types import SimpleNamespace


def room(mode="classic"):
    r = Room("K7QX", "u1", mode=mode)
    r.players = {
        "u1": dict(id="u1", name="A", points=0, streak=0),
        "u2": dict(id="u2", name="B", points=0, streak=0),
    }
    r.playlist = [dict(id=1, duration=4, stored=[("a", 12)])]
    return r


def test_lifecycle_and_deadlines():
    r = room()
    r.start(100)
    assert r.starts == 103 and r.closes == 112
    r.votes = {"u1": 12, "u2": 10}
    r.advance(111)
    assert r.phase == "judge"
    r.advance(112)
    assert r.phase == "reveal"
    assert len(r.results[0]["scores"]) == 5
    assert len(r.results[0]["cuts"]) == 2
    r.advance(121)
    assert r.phase == "results"
    assert r.players["u1"]["points"] > 0


def test_ghost_determinism():
    assert ghost_scores("A", 0, 12, 4) == ghost_scores("A", 0, 12, 4)
    assert all(0 <= s <= 20 for s in ghost_scores("A", 0, 20, 4))
    assert ghost_scores("A", 1, 12, 4) != ghost_scores("A", 0, 12, 4)


def test_truth_and_leave_one_out():
    assert truth([("echo", 20), ("other", 10)], [12], exclude="echo") == 11
    assert truth([], []) is None
    assert truth([("human", 10)], [14]) == 12


def test_points():
    assert points(12, 12) == 20
    assert points(13, 12) == 20
    assert points(18, 12) == 0
    assert points(12, 12, 2) > 20
    assert points(12, None) == 0


def test_mole_and_secrecy():
    r = room("mole")
    r.assign_mole()
    other = room("mole")
    other.assign_mole()
    assert r.mole == other.mole
    assert r.mole is None or r.mole in [p["id"] for p in r.panel()]
    assert r.snapshot("u1", 100)["mole"] is None
    outcomes = []
    for i in range(100):
        r.code = str(i)
        r.assign_mole()
        outcomes.append(r.mole)
    assert None in outcomes and any(v is not None for v in outcomes)


def test_guest_scope_and_rejoin():
    r = room()
    r.tokens = {"secret": "u1"}
    assert player_for(r, SimpleNamespace(cookies={"jr_K7QX": "secret"})) == "u1"
    with pytest.raises(HTTPException):
        player_for(r, SimpleNamespace(cookies={"jr_ABCD": "secret"}))
    with pytest.raises(HTTPException):
        player_for(r, SimpleNamespace(cookies={"jr_K7QX": "wrong"}))
    assert len(r.players) == 2


def test_no_bot_in_truth_and_hidden_scores():
    r = room()
    r.start(100)
    r.votes = {"u1": 10, "u2": 14}
    assert r.snapshot("u1", 105)["result"] is None
    r.reveal(112)
    assert r.results[0]["target"] == 12
    assert "stored" not in r.snapshot("u1", 113)["playlist"][0]


def test_mole_ballot_bonus():
    r = room("mole")
    r.phase = "mole"
    r.mole = None
    r.closes = 200
    r.ballots = {"u1": None, "u2": "mum"}
    r.advance(150)
    assert r.phase == "results" and r.players["u1"]["points"] == 30
    assert r.players["u2"]["points"] == 0


from tests.test_member_dive_visibility import workspace
from app.models.judge_room import JudgeRoomRating
from app.services.judge_room import rooms


def test_api_guest_scope_persistence_and_visibility(workspace, monkeypatch):
    db, login, dives, users, _ = workspace
    client = login("alice")
    response = client.post("/api/v1/rooms", json={})
    assert response.status_code == 200, response.text
    state = response.json()
    code = state["code"]
    prefix = f"/api/v1/rooms/{code}"
    assert {d["id"] for d in state["playlist"]} == {
        dives["alice-public"],
        dives["bob-public"],
    }
    assert (
        client.post(
            prefix + "/actions",
            json={"action": "configure", "mode": "classic", "source": "latest"},
        ).status_code
        == 200
    )
    # Save the host cookie; a guest has a separate room-only capability.
    host_cookies = dict(client.cookies)
    client.cookies.clear()
    assert client.get(prefix).status_code == 403
    assert client.post(prefix + "/join", json={"nickname": "Guest"}).status_code == 200
    assert client.get("/api/v1/dives").status_code == 401
    assert (
        client.get(f'{prefix}/media/{dives["alice-private"]}/video').status_code == 404
    )
    assert (
        client.get(f'{prefix}/media/{dives["alice-public"]}/video').status_code == 200
    )
    assert client.post(prefix + "/actions", json={"action": "start"}).status_code == 403
    guest_cookies = dict(client.cookies)
    client.cookies.clear()
    client.cookies.update(host_cookies)
    assert client.post(prefix + "/actions", json={"action": "start"}).status_code == 200
    room = rooms[code]
    monkeypatch.setattr("app.api.v1.judge_rooms.time.time", lambda: room.starts + 1)
    assert (
        client.post(
            prefix + "/actions", json={"action": "score", "score": 13}
        ).status_code
        == 200
    )
    assert (
        client.post(
            prefix + "/actions", json={"action": "score", "score": 13}
        ).status_code
        == 409
    )
    assert db.query(JudgeRoomRating).filter_by(room_id=room.game_id).count() == 1
    client.cookies.clear()
    client.cookies.update(guest_cookies)
    assert (
        client.post(prefix + "/join", json={"nickname": "Changed"}).json()["phase"]
        == "judge"
    )
    assert len(room.players) == 2
    assert (
        client.post(
            prefix + "/actions", json={"action": "score", "score": 10}
        ).status_code
        == 200
    )
    assert (
        db.query(JudgeRoomRating)
        .filter_by(room_id=room.game_id, user_id=None)
        .one()
        .nickname
        == "Guest"
    )
    # Visibility is revalidated at the media boundary after joining.
    dive = db.get(
        __import__("app.models.dive", fromlist=["Dive"]).Dive, dives["alice-public"]
    )
    dive.visibility = "private"
    db.commit()
    assert (
        client.get(f'{prefix}/media/{dives["alice-public"]}/video').status_code == 404
    )
    rooms.pop(code)


def test_room_capacity_host_policy_and_csrf(workspace):
    _, login, _, _, _ = workspace
    client = login("alice")
    assert (
        client.post(
            "/api/v1/rooms", json={}, headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    state = client.post("/api/v1/rooms", json={}).json()
    code = state["code"]
    prefix = f"/api/v1/rooms/{code}"
    for i in range(7):
        client.cookies.clear()
        assert (
            client.post(prefix + "/join", json={"nickname": str(i)}).status_code == 200
        )
    client.cookies.clear()
    assert (
        client.post(prefix + "/join", json={"nickname": "overflow"}).status_code == 409
    )
    assert client.get(prefix + "/media/1/video").status_code == 403
    assert client.post("/api/v1/rooms", json={}).status_code == 401
    rooms.pop(code)


def test_guess_code_hides_identity_and_awards_speed_without_ratings():
    r = room("code")
    r.playlist = [
        dict(
            id=1,
            duration=4,
            stored=[],
            dive_code="103C",
            dd=2.8,
            diver_name="Alice",
            choices=["101B", "103C", "105B", "107C"],
        )
    ]
    r.start(100)
    state = r.snapshot("u1", 104)
    assert state["playlist"][0]["diver_name"] == "Alice"
    assert state["playlist"][0]["dive_code"] is None
    assert state["playlist"][0]["dd"] is None
    r.votes = {"u1": "103C", "u2": "103C"}
    r.answer_times = {"u1": 1, "u2": 6}
    r.reveal(112)
    assert r.results[0]["gains"]["u1"] > r.results[0]["gains"]["u2"] > 0
    assert r.results[0]["correct_code"] == "103C"
    assert r.snapshot("u1", 113)["result"]["correct_code"] == "103C"


def test_shadow_opt_in_is_account_scoped(workspace):
    db, login, _, users, _ = workspace
    client = login("bob")
    assert client.get("/api/v1/rooms/preferences/shadow").json() == {"enabled": False}
    assert (
        client.post(
            "/api/v1/rooms/preferences/shadow", json={"enabled": True}
        ).status_code
        == 200
    )
    assert client.get("/api/v1/rooms/preferences/shadow").json() == {"enabled": True}
    assert login("alice").get("/api/v1/rooms/preferences/shadow").json() == {
        "enabled": False
    }


def test_guess_api_rejects_rating_and_unknown_choices(workspace, monkeypatch):
    db, login, dives, _, _ = workspace
    client = login("alice")
    created = client.post("/api/v1/rooms", json={}).json()
    code = created["code"]
    r = rooms[code]
    r.mode = "code"
    r.playlist = [
        dict(
            id=dives["alice-public"],
            duration=4,
            stored=[],
            dive_code="101B",
            height="3m",
            choices=["101B", "103B", "105B", "107B"],
            diver_name="alice",
        )
    ]
    assert (
        client.post(
            f"/api/v1/rooms/{code}/actions", json={"action": "start"}
        ).status_code
        == 200
    )
    monkeypatch.setattr("app.api.v1.judge_rooms.time.time", lambda: r.starts + 1)
    assert (
        client.post(
            f"/api/v1/rooms/{code}/actions", json={"action": "score", "score": 10}
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/v1/rooms/{code}/actions", json={"action": "answer", "choice": "999X"}
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/v1/rooms/{code}/actions", json={"action": "answer", "choice": "101B"}
        ).status_code
        == 200
    )
    assert db.query(JudgeRoomRating).filter_by(room_id=r.game_id).count() == 0
    rooms.pop(code)


def test_websocket_rejoins_with_room_capability(workspace, monkeypatch):
    from contextlib import contextmanager
    from app.api.v1 import judge_rooms

    db, login, _, _, _ = workspace
    client = login("alice")
    state = client.post("/api/v1/rooms", json={}).json()
    code = state["code"]

    @contextmanager
    def connection():
        yield db

    monkeypatch.setattr(judge_rooms, "SessionLocal", connection)
    with client.websocket_connect(f"/api/v1/rooms/{code}/live") as socket:
        snapshot = socket.receive_json()
        assert snapshot["me"] == state["me"]
        assert snapshot["code"] == code
        assert "stored" not in snapshot["playlist"][0]
    client.cookies.clear()
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/api/v1/rooms/{code}/live"):
            pass
    rooms.pop(code)
