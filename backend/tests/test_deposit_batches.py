"""Deposit batches: pending acceptance, depositor access, claim links, email."""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.database import Base, get_db
from app.main import app
from app.models.deposit_batch import BatchEmailOutbox, ClaimToken, EvaluatorNote
from app.models.dive import Dive
from app.models.diver import Diver
from app.models.session import Session as TrainingSession
from app.models.user_auth import AppUser, UserDiverAccess
from app.services import claim_tokens, email_service
from app.services.sessions import create_session

MACHINE_KEY = "test-api-key-1234567890abcdef"


def _video(uuid_suffix, person, code="403B", height="3m", perf="G", caption="403B G 3m belle hauteur"):
    return {
        "dive_code": code,
        "height": height,
        "performance": perf,
        "video_uuid": f"deposit-batch-{uuid_suffix}-1234567890abcdef",
        "date": "2026-10-06T12:00:00",
        "is_sync": False,
        "is_smack": False,
        "person_name": person,
        "raw_caption": caption,
    }


@pytest.fixture()
def workspace(tmp_path):
    settings = get_settings()
    prev_auth = settings.user_auth_enabled
    prev_depositor = settings.ingest_depositor_email
    prev_delay = settings.batch_email_delay_minutes
    prev_cache = settings.media_cache_root
    settings.media_cache_root = str(tmp_path)
    settings.user_auth_enabled = True
    settings.ingest_depositor_email = "maxime@example.test"
    settings.batch_email_delay_minutes = 45
    prev_secure = settings.auth_cookie_secure
    settings.auth_cookie_secure = False
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    training = TrainingSession(date=datetime.now().date(), notes="operator notes")
    db.add(training)
    db.flush()
    users, tokens, divers = {}, {}, {}
    for name, admin in (("maxime", True), ("alice", False), ("bob", False)):
        user = AppUser(email=f"{name}@example.test", display_name=name, role="owner" if admin else "friend", is_admin=admin)
        db.add(user)
        db.flush()
        users[name] = user
        diver = Diver(display_name=name, canonical_name=name)
        db.add(diver)
        db.flush()
        divers[name] = diver
        db.add(UserDiverAccess(user_id=user.id, diver_id=diver.id, access_kind="OWNER"))
    db.commit()
    for name in users:
        tokens[name] = create_session(db, user_id=users[name].id, ttl_seconds=3600, revoke_existing=False)[0]
    db.expunge_all()

    def override():
        try:
            yield db
        finally:
            db.rollback()
            db.expunge_all()

    app.dependency_overrides[get_db] = override
    member = TestClient(app)
    machine = TestClient(app, headers={"X-API-Key": MACHINE_KEY})

    def as_user(name):
        member.cookies.clear()
        member.cookies.set(settings.auth_cookie_name, tokens[name])
        return member

    yield db, as_user, machine, users, divers
    member.close()
    machine.close()
    app.dependency_overrides.clear()
    db.close()
    engine.dispose()
    settings.user_auth_enabled = prev_auth
    settings.ingest_depositor_email = prev_depositor
    settings.batch_email_delay_minutes = prev_delay
    settings.auth_cookie_secure = prev_secure
    settings.media_cache_root = prev_cache


def _sync_batch(machine, videos):
    response = machine.post("/api/v1/videos/batch", json={"videos": videos})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["failed"] == 0, data
    return data


def test_third_party_deposit_pends_private_with_note_and_outbox(workspace):
    db, login, machine, users, divers = workspace
    _sync_batch(machine, [
        _video("alice1", "alice"),
        _video("alice2", "alice", code="201C"),
        _video("mine1", "maxime"),
    ])
    alice_dives = db.query(Dive).filter(Dive.diver_id == divers["alice"].id).order_by(Dive.id).all()
    assert len(alice_dives) == 2
    for dive in alice_dives:
        assert dive.visibility == "private"
        assert dive.accepted_at is None
        assert dive.batch_id is not None
        assert dive.deposited_by_user_id == users["maxime"].id
    mine = db.query(Dive).filter(Dive.diver_id == divers["maxime"].id).one()
    assert mine.accepted_at is not None
    assert mine.deposited_by_user_id == users["maxime"].id
    # Maintainer caption stored as a note-only evaluation.
    note = db.query(EvaluatorNote).filter_by(dive_id=alice_dives[0].id).one()
    assert note.author_user_id == users["maxime"].id
    assert "belle hauteur" in (note.comment or "")
    assert note.score_half_steps is None
    # One email queued for alice, none for the depositor's own clips.
    rows = db.query(BatchEmailOutbox).all()
    assert len(rows) == 1
    assert rows[0].user_id == users["alice"].id
    assert rows[0].diver_id == divers["alice"].id
    assert rows[0].status == "pending"


def test_depositor_keeps_access_outsiders_see_nothing(workspace):
    db, login, machine, users, divers = workspace
    _sync_batch(machine, [_video("alice1", "alice")])
    dive_id = db.query(Dive.id).filter(Dive.diver_id == divers["alice"].id).limit(1).scalar()
    assert login("maxime").get(f"/api/v1/dives/{dive_id}").status_code == 200
    assert login("bob").get(f"/api/v1/dives/{dive_id}").status_code == 404
    assert login("bob").get("/api/v1/deposits/pending").json() == {"batches": []}
    pending = login("alice").get("/api/v1/deposits/pending").json()["batches"]
    assert len(pending) == 1 and pending[0]["pending"] == 1


def test_owner_reviews_accepts_and_edits(workspace):
    db, login, machine, users, divers = workspace
    _sync_batch(machine, [_video("alice1", "alice"), _video("alice2", "alice", code="201C")])
    batch_id = db.query(Dive.batch_id).filter(Dive.diver_id == divers["alice"].id).limit(1).scalar()
    detail = login("alice").get(f"/api/v1/deposits/batches/{batch_id}")
    assert detail.status_code == 200, detail.text
    assert len(detail.json()["dives"]) == 2
    assert detail.json()["dives"][0]["evaluator_note"] is not None
    first_id = detail.json()["dives"][0]["id"]
    # Depositor and admin cannot accept for the owner.
    assert login("maxime").post(f"/api/v1/deposits/batches/{batch_id}/accept", json={}).status_code == 403
    # Owner edits then accepts one clip, then the rest.
    edit = login("alice").patch(f"/api/v1/deposits/dives/{first_id}", json={"dive_code": "403C", "notes": "mes notes"})
    assert edit.status_code == 200, edit.text
    assert edit.json()["dive_code"] == "403C"
    one = login("alice").post(f"/api/v1/deposits/batches/{batch_id}/accept", json={"dive_ids": [first_id]})
    assert one.status_code == 200 and one.json()["accepted"] == [first_id]
    rest = login("alice").post(f"/api/v1/deposits/batches/{batch_id}/accept", json={})
    assert rest.status_code == 200 and len(rest.json()["accepted"]) == 1
    assert login("alice").get("/api/v1/deposits/pending").json() == {"batches": []}
    # Accepted clips are plain library rows again.
    assert db.query(Dive).filter(Dive.batch_id == batch_id, Dive.accepted_at.is_(None)).count() == 0


def test_outsider_cannot_review_or_edit(workspace):
    db, login, machine, users, divers = workspace
    _sync_batch(machine, [_video("alice1", "alice")])
    batch_id = db.query(Dive.batch_id).filter(Dive.diver_id == divers["alice"].id).limit(1).scalar()
    dive_id = db.query(Dive.id).filter(Dive.diver_id == divers["alice"].id).limit(1).scalar()
    assert login("bob").get(f"/api/v1/deposits/batches/{batch_id}").status_code == 404
    assert login("bob").post(f"/api/v1/deposits/batches/{batch_id}/accept", json={}).status_code == 404
    assert login("bob").patch(f"/api/v1/deposits/dives/{dive_id}", json={"notes": "hijack"}).status_code == 404


def test_claim_link_signs_in_once(workspace):
    db, login, machine, users, divers = workspace
    _sync_batch(machine, [_video("alice1", "alice")])
    batch_id = db.query(Dive.batch_id).filter(Dive.diver_id == divers["alice"].id).limit(1).scalar()
    raw = claim_tokens.mint_claim_token(
        db, user_id=users["alice"].id, batch_id=batch_id,
        created_by_user_id=users["maxime"].id, ttl_seconds=3600)
    anon = TestClient(app)
    peek = anon.post("/api/v1/deposits/claim/peek", json={"token": raw})
    assert peek.status_code == 200 and peek.json()["batch_id"] == batch_id
    redeem = anon.post("/api/v1/deposits/claim/redeem", json={"token": raw})
    assert redeem.status_code == 200, redeem.text
    assert redeem.json()["batch_id"] == batch_id
    # The redeemed session works like a normal login.
    assert anon.get("/api/v1/deposits/pending").status_code == 200
    # Single-use: second redeem and unknown tokens read as missing.
    assert anon.post("/api/v1/deposits/claim/redeem", json={"token": raw}).status_code == 404
    assert anon.post("/api/v1/deposits/claim/redeem", json={"token": "nope-nope-nope-nope"}).status_code == 404
    anon.close()


def test_claim_token_expiry(workspace):
    db, login, machine, users, divers = workspace
    raw = claim_tokens.mint_claim_token(
        db, user_id=users["alice"].id, batch_id="batch-gone",
        created_by_user_id=None, ttl_seconds=3600)
    row = db.query(ClaimToken).filter_by(user_id=users["alice"].id).one()
    row.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.commit()
    anon = TestClient(app)
    assert anon.post("/api/v1/deposits/claim/peek", json={"token": raw}).status_code == 404
    assert anon.post("/api/v1/deposits/claim/redeem", json={"token": raw}).status_code == 404
    anon.close()


def test_claim_disabled_without_auth(workspace):
    from app.config import get_settings as _settings

    db, login, machine, users, divers = workspace
    raw = claim_tokens.mint_claim_token(
        db, user_id=users["alice"].id, batch_id="batch-x",
        created_by_user_id=None, ttl_seconds=3600)
    settings = _settings()
    previous = settings.user_auth_enabled
    settings.user_auth_enabled = False
    try:
        anon = TestClient(app)
        assert anon.post("/api/v1/deposits/claim/peek", json={"token": raw}).status_code == 404
        assert anon.post("/api/v1/deposits/claim/redeem", json={"token": raw}).status_code == 404
        anon.close()
    finally:
        settings.user_auth_enabled = previous
    # Token unconsumed: still redeemable with auth back on.
    anon = TestClient(app)
    assert anon.post("/api/v1/deposits/claim/peek", json={"token": raw}).status_code == 200
    anon.close()


def test_visibility_locked_until_acceptance_and_depositor_cut_off(workspace):
    db, login, machine, users, divers = workspace
    _sync_batch(machine, [_video("alice1", "alice")])
    dive = db.query(Dive).filter(Dive.diver_id == divers["alice"].id).one()
    dive_id, video_uuid, batch_id = dive.id, dive.video_uuid, dive.batch_id
    # Visibility is not a pending-edit field: rejected, stays private.
    edited = login("alice").patch(f"/api/v1/deposits/dives/{dive_id}", json={"visibility": "public"})
    assert edited.status_code == 422, edited.text
    assert db.get(Dive, dive_id).visibility == "private"
    # Depositor watches their pending deposit, then loses it on acceptance.
    from app.services.user_access import can_user_access_video

    assert can_user_access_video(db, users["maxime"], video_uuid).allowed is True
    login("alice").post(
        f"/api/v1/deposits/batches/{batch_id}/accept", json={})
    assert login("maxime").get(f"/api/v1/dives/{dive_id}").status_code == 404
    assert can_user_access_video(db, users["maxime"], video_uuid).allowed is False


def test_migration_backfill_never_accepts_live_batches():
    import pathlib

    sql = pathlib.Path(__file__).parent.parent.joinpath("migrations", "add_deposit_batches.sql").read_text()
    assert "WHERE accepted_at IS NULL AND batch_id IS NULL" in sql


def test_email_pref_and_render_without_smtp(workspace):
    db, login, machine, users, divers = workspace
    assert not email_service.is_email_configured()
    assert email_service.email_enabled(db, users["alice"].id) is True
    assert login("alice").get("/api/v1/deposits/email-pref").json() == {"enabled": True}
    put = login("alice").put("/api/v1/deposits/email-pref", json={"enabled": False})
    assert put.status_code == 200 and put.json() == {"enabled": False}
    assert email_service.email_enabled(db, users["alice"].id) is False
    msg = email_service.render_batch_email(
        recipient_name="Alice", diver_name="Alice", depositor_name="Maxime",
        dives=[{"dive_code": "403B", "height": "3m", "dive_datetime": "2026-10-06T12:00:00"}],
        evaluator_note="belle hauteur", claim_url="https://app.test/claim/abc",
        review_url="https://app.test/deposits/batch-1", posters=[])
    assert "Récupérer mes plongeons" in msg.get_body(("html",)).get_content()
    assert "https://app.test/claim/abc" in msg.get_body(("plain",)).get_content()
    ok, _error = email_service.send_message(msg, "alice@example.test")
    assert ok is False


def test_admin_browser_upload_on_behalf_pends(workspace, monkeypatch, tmp_path):
    db, login, machine, users, divers = workspace
    from app.services import browser_upload
    folder = tmp_path / "prepared"
    folder.mkdir(exist_ok=True)
    for name in ("source", "video.mp4", "poster.jpg"):
        (folder / name).write_bytes(b"test")
    monkeypatch.setattr(browser_upload, "prepare_video", lambda file: (folder, 4))
    import boto3

    from app.config import get_settings as _get_settings

    _settings = _get_settings()
    for key, value in [("b2_upload_key_id", "test"), ("b2_upload_key_secret", "test"), ("b2_upload_region", "test")]:
        monkeypatch.setattr(_settings, key, value)

    class _Stream:
        def iter_chunks(self, chunk_size):
            yield b"test"

        def close(self):
            pass

    class _Client:
        def upload_file(self, *args, **kwargs):
            pass

        def get_object(self, **kwargs):
            return {"Body": _Stream()}

    monkeypatch.setattr(boto3, "client", lambda *a, **kw: _Client())
    fields = dict(
        dive_code="403B", height="3m", performance="G",
        dive_datetime="2026-10-06T12:00:00", diver_id=str(divers["alice"].id),
        upload_id="12345678-1234-1234-1234-123456789012", notes="serre les genoux")
    response = login("maxime").post(
        "/api/v1/dives/upload", data=fields, files={"file": ("clip.mp4", b"video")})
    assert response.status_code == 201, response.text
    dive = db.query(Dive).filter(Dive.diver_id == divers["alice"].id).one()
    assert dive.visibility == "private" and dive.accepted_at is None
    assert dive.notes is None  # owner's field stays theirs
    assert db.query(EvaluatorNote).filter_by(dive_id=dive.id).one().comment == "serre les genoux"
    assert db.query(BatchEmailOutbox).filter_by(user_id=users["alice"].id).count() == 1
    # A non-admin still cannot deposit for someone else.
    fields["upload_id"] = "22345678-1234-1234-1234-123456789012"
    assert login("bob").post(
        "/api/v1/dives/upload", data=fields, files={"file": ("clip.mp4", b"video")}).status_code == 403
