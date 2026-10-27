import pytest
from fastapi import HTTPException
from app.config import get_settings
from app.services.judge_room import Room, GHOSTS, ghost_scores, points, truth
from app.api.v1.judge_rooms import player_for
from types import SimpleNamespace


@pytest.fixture(autouse=True)
def _plain_http_room_cookies():
    # The TestClient speaks plain HTTP and drops Secure cookies; mirror the
    # AUTH_COOKIE_SECURE=false local-test override used elsewhere.
    settings = get_settings()
    prev = settings.auth_cookie_secure
    settings.auth_cookie_secure = False
    yield
    settings.auth_cookie_secure = prev


def test_room_cookie_secure_flag_follows_settings(workspace, monkeypatch):
    _, login, _, _, _ = workspace
    monkeypatch.setattr(get_settings(), "auth_cookie_secure", True)
    response = login("alice").post("/api/v1/rooms", json={})
    assert response.status_code == 200, response.text
    assert "Secure" in response.headers.get("set-cookie", "")


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
    r.connections = {"a": "u1", "b": "u2"}
    r.start(100)
    assert r.phase == "loading" and r.starts == r.closes == 0
    r.signal("u1", "ready", 0, r.game_id, 101)
    assert r.phase == "loading"
    r.signal("u2", "ready", 0, r.game_id, 102)
    assert r.phase == "watching" and r.starts == 103 and r.closes == 0
    r.advance(106)
    assert r.phase == "watching"
    r.advance(107)
    assert r.phase == "judge" and r.closes == 117
    r.votes = {"u1": 12}
    r.advance(116)
    assert r.phase == "judge"
    r.votes["u2"] = 10
    r.advance(116)
    assert r.phase == "reveal"
    assert len(r.results[0]["scores"]) == 5 and len(r.results[0]["cuts"]) == 2
    r.advance(126)
    assert r.phase == "results"
    assert r.players["u1"]["points"] > 0


def test_ready_timeout_disconnect_and_stale_signals():
    r = room()
    r.connections = {"a": "u1", "b": "u2"}
    r.start(100)
    r.signal("u1", "ready", 1, r.game_id, 101)
    r.signal("u1", "ready", 0, "old-game", 101)
    assert not r.ready
    r.signal("u1", "ready", 0, r.game_id, 102)
    r.advance(114.9)
    assert r.phase == "loading"
    r.advance(115)
    assert r.phase == "watching" and r.starts == 116
    r = room()
    r.connections = {"a": "u1", "b": "u2"}
    r.start(100)
    r.signal("u1", "ready", 0, r.game_id, 101)
    del r.connections["b"]
    r.advance(102)
    assert r.phase == "watching"


def test_client_ended_opens_ten_seconds_only_after_every_connected_viewer():
    r = room()
    r.playlist[0]["duration"] = 30
    r.connections = {"a": "u1", "b": "u2"}
    r.start(100)
    for key in ("u1", "u2"):
        r.signal(key, "ready", 0, r.game_id, 101)
    r.signal("u1", "ended", 0, r.game_id, 102)
    assert r.phase == "watching" and r.closes == 0
    r.signal("u1", "ended", 0, r.game_id, 106)
    assert r.phase == "watching"
    r.signal("u2", "ended", 0, r.game_id, 107)
    assert r.phase == "judge" and r.scoring_starts == 107 and r.closes == 117


def test_no_players_own_shadow_on_panel():
    r = room()
    r.ghosts = [dict(id="shadow", name="Maxime", emoji="🌑", points=0)] + [
        dict(id=k, name=n, emoji=e, points=0) for k, n, e, _ in GHOSTS
    ]
    assert "shadow" not in [p["id"] for p in r.panel()]
    del r.players["u1"]
    assert "shadow" in [p["id"] for p in r.panel()]


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
    assert r.mole is None or r.mole in [p["id"] for p in r.panel()]
    assert r.snapshot("u1", 100)["mole"] is None
    # Independent server-side randomness: the public code alone cannot predict
    # the mole, so repeated assignments vary while staying valid.
    outcomes = set()
    for _ in range(100):
        r.assign_mole()
        assert r.mole is None or r.mole in [p["id"] for p in r.panel()]
        outcomes.add(r.mole)
    assert None in outcomes and len(outcomes) > 1


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
    r.connections = {"a": "u1", "b": "u2"}
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
    room.begin_video(100)
    room.begin_scoring(105)
    monkeypatch.setattr("app.api.v1.judge_rooms.time.time", lambda: 106)
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
    r.begin_video(100)
    r.begin_scoring(105)
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
    r.begin_video(100)
    r.begin_scoring(105)
    monkeypatch.setattr("app.api.v1.judge_rooms.time.time", lambda: 106)
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


def test_native_end_corrects_metadata_drift_without_resetting_answer_speed():
    r = room("code")
    r.connections = {"a": "u1", "b": "u2"}
    r.start(100)
    r.begin_video(101)
    r.begin_scoring(106)
    r.answer_times = {"u1": 1}
    r.signal("u1", "ended", 0, r.game_id, 107)
    r.signal("u2", "ended", 0, r.game_id, 107.2)
    assert r.scoring_starts == 107.2 and r.closes == 117.2
    assert r.answer_times["u1"] == 0
    r.signal("u2", "ended", 0, r.game_id, 109)
    assert r.closes == 117.2


def test_playback_duration_prefers_verified_file_duration(tmp_path, monkeypatch):
    from app.services import judge_room

    path = tmp_path / "clip.mp4"
    path.write_bytes(b"fake")
    monkeypatch.setattr(
        judge_room.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout="10.928")
    )
    assert judge_room.playback_duration(path, 3) == 10.928


@pytest.mark.parametrize("mode", ["classic", "code"])
def test_last_connected_human_reveals_immediately_without_waiting_for_ghosts(mode):
    r = room(mode)
    r.connections = {"a": "u1", "b": "u2"}
    if mode == "code":
        r.playlist[0]["dive_code"] = "101B"
    r.start(100)
    r.begin_video(101)
    r.begin_scoring(106)
    r.votes["u1"] = "101B" if mode == "code" else 12
    r.answer_times["u1"] = 1
    r.advance(107)
    assert r.phase == "judge"
    r.votes["u2"] = "101B" if mode == "code" else 13
    r.answer_times["u2"] = 2
    r.advance(108)
    assert r.phase == "reveal" and r.closes == 117
    if mode == "classic":
        assert len(r.results[0]["scores"]) == 5


def test_disconnected_players_do_not_hold_score_or_mole_countdown():
    r = room()
    r.connections = {"a": "u1", "other-tab": "u1"}
    r.start(100)
    r.begin_video(101)
    r.begin_scoring(106)
    r.votes = {"u1": 12}
    r.advance(107)
    assert r.phase == "reveal"
    r.phase = "mole"
    r.closes = 200
    r.ballots = {"u1": None}
    r.advance(110)
    assert r.phase == "results"


def test_room_media_unlocks_before_sql_files_or_signing(workspace, monkeypatch):
    from app.api.v1 import judge_rooms

    db, login, dives, _, _ = workspace
    client = login("alice")
    state = client.post("/api/v1/rooms", json={}).json()
    code = state["code"]

    def sign(path, checksum, *, ttl_seconds):
        assert not judge_rooms.lock._is_owned()
        assert ttl_seconds == 120
        return "/media/cache/signed/" + "b" * 64 + "/test.mp4?expires=123&sig=test"

    original_entries = judge_rooms.media_entries

    def entries(*args):
        assert not judge_rooms.lock._is_owned()
        return original_entries(*args)

    monkeypatch.setattr(judge_rooms, "signed_url", sign)
    monkeypatch.setattr(judge_rooms, "media_entries", entries)
    path = f'/api/v1/rooms/{code}/media/{dives["alice-public"]}/video'
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 302 and response.headers["location"].startswith(
        "/media/cache/signed/"
    )
    client.cookies.clear()
    assert client.get(path, follow_redirects=False).status_code == 403
    rooms.pop(code)


def test_room_signatures_expire_soon_without_changing_library_ttl(
    tmp_path, monkeypatch
):
    from app.services.signed_media import signed_url
    from app.config import get_settings

    monkeypatch.setenv("MEDIA_SIGNED_URLS_ENABLED", "true")
    monkeypatch.setenv("MEDIA_SIGNING_SECRET", "a" * 64)
    monkeypatch.setattr(get_settings(), "media_cache_root", str(tmp_path))
    from urllib.parse import urlparse, parse_qs

    issued = 1000
    expires = int(
        parse_qs(
            urlparse(
                signed_url(tmp_path / "clip.mp4", "b" * 64, now=issued, ttl_seconds=120)
            ).query
        )["expires"][0]
    )
    assert 120 <= expires - issued <= 150
    library = int(
        parse_qs(
            urlparse(signed_url(tmp_path / "clip.mp4", "b" * 64, now=issued)).query
        )["expires"][0]
    )
    assert library - issued >= 3600


def test_ghosts_earn_points_and_rank_with_humans():
    r = room()
    r.connections = {"a": "u1", "b": "u2"}
    r.start(100)
    r.begin_video(101)
    r.begin_scoring(106)
    r.votes = {"u1": 12, "u2": 12}
    r.advance(107)
    assert r.phase == "reveal"
    ghosts = r.ghost_seats()
    assert ghosts and all(g["id"] in r.results[-1]["gains"] for g in ghosts)
    assert any(g["points"] > 0 for g in ghosts)
    assert {p["id"] for p in r.panel()} >= {g["id"] for g in ghosts}
    r.reset_scores()
    assert all(j["points"] == 0 for j in r.panel())


def test_ghosts_answer_guess_the_code():
    r = room("code")
    r.connections = {"a": "u1"}
    r.playlist[0].update(dive_code="101B", choices=["101B", "103B", "201B", "301B"])
    r.start(100)
    r.begin_video(101)
    r.begin_scoring(106)
    r.votes = {"u1": "101B"}
    r.answer_times = {"u1": 1}
    r.advance(107)
    answers = r.results[-1]["answers"]
    assert {g["id"] for g in r.ghost_seats()} <= answers.keys()
    assert all(a in r.playlist[0]["choices"] for a in answers.values())


def test_reveal_ends_when_every_connected_human_skips():
    r = room()
    r.connections = {"a": "u1", "b": "u2"}
    r.start(100)
    r.begin_video(101)
    r.begin_scoring(106)
    r.votes = {"u1": 12, "u2": 12}
    r.advance(107)
    r.skips = {"u1"}
    r.advance(108)
    assert r.phase == "reveal"
    r.skips.add("u2")
    r.advance(108)
    assert r.phase in ("loading", "results", "mole")
    assert r.skips == set() or r.phase != "loading"


def test_shadow_playlist_offset_uses_grouped_peer_average(workspace):
    from app.models.judge_room import JudgeShadowPreference
    from app.models.matchmaking import AutomaticRating

    db, login, dives, users, _ = workspace
    db.add(JudgeShadowPreference(user_id=users["alice"].id, enabled=1))
    rated = dives["alice-public"]
    peers = {"bob": 10, "viewer": 12}
    db.add(
        AutomaticRating(
            dive_id=rated,
            evaluator_user_id=users["alice"].id,
            score_half_steps=14,
            dive_code="101B",
            height="3m",
            dive_name="n",
            video_uuid="v",
        )
    )
    for name, score in peers.items():
        db.add(
            AutomaticRating(
                dive_id=rated,
                evaluator_user_id=users[name].id,
                score_half_steps=score,
                dive_code="101B",
                height="3m",
                dive_name="n",
                video_uuid="v",
            )
        )
    db.commit()
    # The shadow stands in for an absent user 1, so another member hosts.
    state = login("bob").post("/api/v1/rooms", json={}).json()
    assert state["code"] and "shadow" in [p["id"] for p in state["players"]]
    # Shadow fields stay server-side (snapshots strip them); check the room.
    from app.services.judge_room import rooms as live_rooms

    room = live_rooms[state["code"]]
    try:
        entries = {d["id"]: d for d in room.playlist}
        assert entries[rated]["shadow_score"] == 14
        assert entries[rated]["shadow_offset"] == pytest.approx(14 - (10 + 12) / 2)
    finally:
        live_rooms.pop(state["code"], None)


def test_code_mode_distractors_share_group_height_platform(workspace):
    from app.models.dd_lookup import DDLookup
    from app.models.fina_dive_code import FINADiveCode
    from app.services.judge_room import rooms as live_rooms

    db, login, _, _, _ = workspace
    codes = ["101B", "102B", "103B", "104B"]
    for c in codes:
        db.add(
            FINADiveCode(
                dive_code=c, group=1, direction=1, rotations=2, position="B"
            )
        )
        db.add(
            DDLookup(
                dive_code=c,
                height="3m",
                platform_type="springboard",
                dd_value=2.0,
            )
        )
    db.commit()
    client = login("alice")
    room_code = client.post("/api/v1/rooms", json={}).json()["code"]
    try:
        state = client.post(
            f"/api/v1/rooms/{room_code}/actions",
            json={"action": "configure", "mode": "code", "source": "community"},
        ).json()
        assert state["playlist"], "expected playable code-mode dives"
        for d in state["playlist"]:
            assert len(d["choices"]) == 4 and len(set(d["choices"])) == 4
            assert set(d["choices"]) <= set(codes)
        server = {d["id"]: d for d in live_rooms[room_code].playlist}
        for d in state["playlist"]:
            assert server[d["id"]]["dive_code"] in d["choices"]
    finally:
        live_rooms.pop(room_code, None)
