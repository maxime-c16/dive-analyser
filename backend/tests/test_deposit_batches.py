from tests.upload_helpers import publish_upload
"""Deposit batches: pending acceptance, depositor access, claim links, email."""
import sys
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
    # Machine ingest waits for an admin to confirm before any friend is emailed.
    assert rows[0].status == "held"


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


def test_one_email_per_diver_when_owner_has_two_divers(workspace):
    from app.models.deposit_batch import BatchEmailOutbox
    from app.services import deposit_batches

    db, login, machine, users, divers = workspace
    second = Diver(display_name="Alice B", canonical_name="alice b")
    db.add(second)
    db.flush()
    db.add(UserDiverAccess(user_id=users["alice"].id, diver_id=second.id, access_kind="OWNER"))
    db.commit()
    alice_id, second_id, alice_user_id = divers["alice"].id, second.id, users["alice"].id
    _sync_batch(machine, [_video("alice1", "alice"), _video("aliceb1", "Alice B")])
    rows = db.query(BatchEmailOutbox).order_by(BatchEmailOutbox.diver_id).all()
    assert {(r.diver_id, r.user_id) for r in rows} == {
        (alice_id, alice_user_id),
        (second_id, alice_user_id),
    }


def test_agent_day_batch_id_fits_varchar36():
    from app.services import deposit_batches

    batch_id = deposit_batches.agent_day_batch_id("x" * 100, datetime.now().date())
    assert len(batch_id) <= 36
    assert deposit_batches.agent_day_batch_id("mac-1", datetime.now().date()) == \
        deposit_batches.agent_day_batch_id("mac-1", datetime.now())


def test_preconsumed_token_redeem_misses(workspace):
    db, login, machine, users, divers = workspace
    raw = claim_tokens.mint_claim_token(
        db, user_id=users["alice"].id, batch_id="batch-taken",
        created_by_user_id=None, ttl_seconds=3600)
    row = db.query(ClaimToken).filter_by(user_id=users["alice"].id).one()
    row.used_at = datetime.utcnow()
    db.commit()
    assert claim_tokens.redeem_claim_token(db, raw) is None


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


def _stub_browser_upload(monkeypatch, tmp_path):
    from app.services import browser_upload
    folder = tmp_path / "prepared"
    folder.mkdir(exist_ok=True)
    for name in ("source", "original.mp4", "poster.jpg"):
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


def test_admin_browser_upload_on_behalf_pends(workspace, monkeypatch, tmp_path):
    db, login, machine, users, divers = workspace
    _stub_browser_upload(monkeypatch, tmp_path)
    fields = dict(
        dive_code="403B", height="3m", performance="G",
        dive_datetime="2026-10-06T12:00:00", diver_id=str(divers["alice"].id),
        upload_id="12345678-1234-1234-1234-123456789012", notes="serre les genoux")
    response = publish_upload(db, login("maxime"), data=fields, files={"file": ("clip.mp4", b"video")})
    assert response.status_code == 200, response.text
    dive = db.query(Dive).filter(Dive.diver_id == divers["alice"].id).one()
    assert dive.visibility == "private" and dive.accepted_at is None
    assert dive.notes is None  # owner's field stays theirs
    assert db.query(EvaluatorNote).filter_by(dive_id=dive.id).one().comment == "serre les genoux"
    assert db.query(BatchEmailOutbox).filter_by(user_id=users["alice"].id).count() == 1
    # A non-admin still cannot deposit for someone else.
    fields["upload_id"] = "22345678-1234-1234-1234-123456789012"
    assert publish_upload(db, login("bob"), data=fields, files={"file": ("clip.mp4", b"video")}).status_code == 403


def test_captionless_admin_deposit_still_queues_the_email(workspace, monkeypatch, tmp_path):
    db, login, machine, users, divers = workspace
    _stub_browser_upload(monkeypatch, tmp_path)
    fields = dict(
        dive_code="403B", height="3m", performance="G",
        dive_datetime="2026-10-06T12:00:00", diver_id=str(divers["alice"].id),
        upload_id="32345678-1234-1234-1234-123456789012")
    response = publish_upload(db, login("maxime"), data=fields, files={"file": ("clip.mp4", b"video")})
    assert response.status_code == 200, response.text
    dive = db.query(Dive).filter(Dive.diver_id == divers["alice"].id).one()
    assert dive.accepted_at is None
    assert db.query(EvaluatorNote).filter_by(dive_id=dive.id).count() == 0
    assert db.query(BatchEmailOutbox).filter_by(user_id=users["alice"].id).count() == 1


def test_pending_deposit_cannot_be_published_before_acceptance(workspace):
    db, login, machine, users, divers = workspace
    _sync_batch(machine, [_video("alice1", "alice")])
    dive = db.query(Dive).filter(Dive.diver_id == divers["alice"].id).one()
    dive_id, batch_id = dive.id, dive.batch_id
    # Depositor and owner alike: pending clips stay private on the regular route.
    for name in ("maxime", "alice"):
        response = login(name).put(f"/api/v1/dives/{dive_id}", json={"visibility": "public"})
        assert response.status_code in (403, 404, 409), (name, response.text)
        if name == "alice":
            assert response.status_code == 409, response.text
        assert db.get(Dive, dive_id).visibility == "private"
    assert login("alice").post(f"/api/v1/deposits/batches/{batch_id}/accept", json={}).status_code == 200
    published = login("alice").put(f"/api/v1/dives/{dive_id}", json={"visibility": "public"})
    assert published.status_code == 200, published.text
    assert db.get(Dive, dive_id).visibility == "public"


def test_batch_review_is_scoped_to_one_diver(workspace):
    db, login, machine, users, divers = workspace
    second = Diver(display_name="Alice B", canonical_name="alice b")
    db.add(second)
    db.flush()
    db.add(UserDiverAccess(user_id=users["alice"].id, diver_id=second.id, access_kind="OWNER"))
    db.commit()
    alice_id, second_id, alice_user_id = divers["alice"].id, second.id, users["alice"].id
    _sync_batch(machine, [_video("alice1", "alice"), _video("aliceb1", "Alice B", code="305C")])
    first = db.query(Dive).filter(Dive.diver_id == alice_id).one()
    other = db.query(Dive).filter(Dive.diver_id == second_id).one()
    first_id, other_id = first.id, other.id
    # Force the shared agent-day batch id the mac-agent produces.
    other.batch_id = first.batch_id
    batch_id = first.batch_id
    db.commit()

    ambiguous = login("alice").get(f"/api/v1/deposits/batches/{batch_id}")
    assert ambiguous.status_code == 400, ambiguous.text

    detail = login("alice").get(f"/api/v1/deposits/batches/{batch_id}?diver_id={second_id}")
    assert detail.status_code == 200
    assert detail.json()["diver_id"] == second_id
    assert [d["id"] for d in detail.json()["dives"]] == [other_id]

    accepted = login("alice").post(
        f"/api/v1/deposits/batches/{batch_id}/accept?diver_id={second_id}", json={})
    assert accepted.status_code == 200 and accepted.json()["accepted"] == [other_id]
    assert db.get(Dive, other_id).accepted_at is not None
    assert db.get(Dive, first_id).accepted_at is None

    # The claim link is bound to the diver it was emailed for.
    raw = claim_tokens.mint_claim_token(
        db, user_id=alice_user_id, batch_id=batch_id, diver_id=alice_id,
        created_by_user_id=users["maxime"].id, ttl_seconds=3600)
    anon = TestClient(app)
    peek = anon.post("/api/v1/deposits/claim/peek", json={"token": raw})
    assert peek.status_code == 200
    assert peek.json()["diver_id"] == alice_id and peek.json()["pending"] == 1
    redeem = anon.post("/api/v1/deposits/claim/redeem", json={"token": raw})
    assert redeem.status_code == 200 and redeem.json()["diver_id"] == alice_id
    anon.close()


def test_pending_list_filters_visibility_before_paging(workspace):
    db, login, machine, users, divers = workspace
    _sync_batch(machine, [_video("alice1", "alice", code="403B")])
    _sync_batch(machine, [_video("bob1", "bob", code="305C")])
    alice_dive = db.query(Dive).filter(Dive.diver_id == divers["alice"].id).one()
    bob_dive = db.query(Dive).filter(Dive.diver_id == divers["bob"].id).one()
    alice_dive.created_at = datetime.utcnow() - timedelta(days=2)
    bob_dive.created_at = datetime.utcnow()  # newer: wins the global order
    db.commit()
    # Alice's older batch is not pushed out of her own page by bob's newer one.
    mine = login("alice").get("/api/v1/deposits/pending", params={"limit": 1})
    assert mine.status_code == 200
    assert [b["diver_id"] for b in mine.json()["batches"]] == [divers["alice"].id]
    # Admin triage pages through every pending batch.
    first = login("maxime").get("/api/v1/deposits/pending", params={"limit": 1}).json()["batches"]
    second = login("maxime").get("/api/v1/deposits/pending", params={"limit": 1, "offset": 1}).json()["batches"]
    assert [b["diver_id"] for b in first] == [divers["bob"].id]
    assert [b["diver_id"] for b in second] == [divers["alice"].id]
    assert {b["diver_id"] for b in login("maxime").get("/api/v1/deposits/pending").json()["batches"]} == {
        divers["alice"].id, divers["bob"].id}


def test_held_emails_need_admin_confirmation_and_cron_ignores_them(workspace):
    db, login, machine, users, divers = workspace
    _sync_batch(machine, [_video("alice1", "alice"), _video("alice2", "alice", code="201C")])
    row = db.query(BatchEmailOutbox).one()
    row_id = row.id
    assert row.status == "held"
    # Only admins see or act on the held list.
    assert login("alice").get("/api/v1/deposits/outbox/held").status_code == 403
    assert login("alice").post("/api/v1/deposits/outbox/release", json={}).status_code == 403
    held = login("maxime").get("/api/v1/deposits/outbox/held")
    assert held.status_code == 200, held.text
    emails = held.json()["emails"]
    assert [(e["diver_name"], e["recipient_email"], e["clips"]) for e in emails] == [
        ("alice", "alice@example.test", 2)]
    # The sender only picks 'pending' rows: nothing is due while held.
    due = db.query(BatchEmailOutbox).filter(
        BatchEmailOutbox.status == BatchEmailOutbox.STATUS_PENDING).count()
    assert due == 0
    released = login("maxime").post("/api/v1/deposits/outbox/release", json={"ids": [row_id]})
    assert released.status_code == 200 and released.json() == {"released": 1}
    db.expire_all()
    fresh = db.get(BatchEmailOutbox, row_id)
    assert fresh.status == "pending" and fresh.scheduled_for <= datetime.utcnow()
    assert login("maxime").get("/api/v1/deposits/outbox/held").json()["emails"] == []


def test_discarding_a_held_email_is_terminal(workspace):
    db, login, machine, users, divers = workspace
    _sync_batch(machine, [_video("alice1", "alice")])
    row_id = db.query(BatchEmailOutbox).one().id
    discarded = login("maxime").post("/api/v1/deposits/outbox/discard", json={})
    assert discarded.status_code == 200 and discarded.json() == {"discarded": 1}
    db.expire_all()
    row = db.get(BatchEmailOutbox, row_id)
    assert row.status == "sent" and "discarded" in (row.error or "")
    # Releasing afterwards finds nothing held.
    assert login("maxime").post("/api/v1/deposits/outbox/release", json={}).json() == {"released": 0}


def test_admin_browser_deposit_is_not_held(workspace, monkeypatch, tmp_path):
    db, login, machine, users, divers = workspace
    _stub_browser_upload(monkeypatch, tmp_path)
    fields = dict(
        dive_code="403B", height="3m", performance="G",
        dive_datetime="2026-10-06T12:00:00", diver_id=str(divers["alice"].id),
        upload_id="42345678-1234-1234-1234-123456789012")
    assert publish_upload(db, login("maxime"), data=fields, files={"file": ("clip.mp4", b"video")}).status_code == 200
    assert db.query(BatchEmailOutbox).one().status == "pending"


def test_claim_peek_names_the_diver(workspace):
    db, login, machine, users, divers = workspace
    raw = claim_tokens.mint_claim_token(
        db, user_id=users["alice"].id, batch_id="batch-x", diver_id=divers["alice"].id,
        created_by_user_id=None, ttl_seconds=3600)
    peek = TestClient(app).post("/api/v1/deposits/claim/peek", json={"token": raw})
    assert peek.status_code == 200 and peek.json()["diver_name"] == "alice"


def test_email_headers_are_spam_filter_friendly(workspace):
    settings = get_settings()
    prev = settings.email_from
    settings.email_from = "Dive Analyser <notifs@example.test>"
    try:
        msg = email_service.render_batch_email(
            recipient_name="Alice", diver_name="Alice", depositor_name="Maxime",
            dives=[{"dive_code": "403B", "height": "3m", "dive_datetime": ""}],
            evaluator_note=None, claim_url="https://app.test/claim#t=abc",
            review_url="https://app.test/deposits/b?diver=1", posters=[])
    finally:
        settings.email_from = prev
    assert msg["Reply-To"] == "notifs@example.test"
    assert msg["Message-ID"].rstrip(">").endswith("@example.test")


def test_machine_ingest_re_holds_a_still_pending_row_for_the_same_batch(workspace):
    from app.services import deposit_batches

    db, login, machine, users, divers = workspace
    _sync_batch(machine, [_video("alice1", "alice")])
    row = db.query(BatchEmailOutbox).one()
    row_id, batch_id = row.id, row.batch_id
    # A row queued before the hold existed (or already scheduled) is pending.
    row.status = BatchEmailOutbox.STATUS_PENDING
    db.commit()
    deposit_batches.queue_batch_email(
        db, batch_id=batch_id, diver_id=divers["alice"].id,
        exclude_user_id=users["maxime"].id, hold=True)
    db.commit()
    db.expire_all()
    assert db.get(BatchEmailOutbox, row_id).status == "held"
    # Terminal rows are never reopened.
    row = db.get(BatchEmailOutbox, row_id)
    row.status = BatchEmailOutbox.STATUS_SENT
    db.commit()
    deposit_batches.queue_batch_email(
        db, batch_id=batch_id, diver_id=divers["alice"].id,
        exclude_user_id=users["maxime"].id, hold=True)
    db.commit()
    db.expire_all()
    assert db.get(BatchEmailOutbox, row_id).status == "sent"


def test_sender_only_sends_pending_rows_and_rechecks_before_sending(workspace, monkeypatch):
    import importlib.util
    import pathlib

    db, login, machine, users, divers = workspace
    now = datetime.utcnow() - timedelta(minutes=1)
    db.add_all([
        BatchEmailOutbox(batch_id="b-held", diver_id=divers["alice"].id, user_id=users["alice"].id,
                         status="held", scheduled_for=now),
        BatchEmailOutbox(batch_id="b-due", diver_id=divers["alice"].id, user_id=users["alice"].id,
                         status="pending", scheduled_for=now),
    ])
    db.commit()
    path = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "send_batch_emails.py"
    spec = importlib.util.spec_from_file_location("send_batch_emails_under_test", path)
    sender = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sender)
    sent = []
    monkeypatch.setattr(sender, "SessionLocal", lambda: db)
    monkeypatch.setattr(sender.email_service, "is_email_configured", lambda: True)
    monkeypatch.setattr(sender, "_send_one", lambda _db, row, _dry: sent.append(row.batch_id) or "sent to a@b (1 clips)")
    monkeypatch.setattr(sys, "argv", ["send_batch_emails.py"])
    assert sender.main() == 0
    assert sent == ["b-due"]
    statuses = {r.batch_id: r.status for r in db.query(BatchEmailOutbox).all()}
    assert statuses == {"b-held": "held", "b-due": "sent"}


def test_save_download_accepts_only_owner_diver_and_retries_include_accepted(workspace):
    db, login, machine, users, divers = workspace
    _sync_batch(machine, [_video('download-a1', 'alice'), _video('download-a2', 'alice'), _video('download-b1', 'bob')])
    from app.services.dive_access import unscoped_reads
    with unscoped_reads(db):
        alice = db.query(Dive).filter(Dive.diver_id == divers['alice'].id).all()
        bob = db.query(Dive).filter(Dive.diver_id == divers['bob'].id).one()
        batch_id = alice[0].batch_id
        alice_ids = {d.id for d in alice}
        bob_id = bob.id
    path = f'/api/v1/deposits/batches/{batch_id}/save-download?diver_id={divers["alice"].id}'
    assert login('maxime').post(path).status_code == 404
    assert login('bob').post(path).status_code == 404
    response = login('alice').post(path)
    assert response.status_code == 200, response.text
    clips = response.json()['clips']
    assert {d['id'] for d in clips} == alice_ids
    assert all(d['url'] == f'/api/v1/dives/{d["id"]}/download' for d in clips)
    assert login('alice').post(path).json() == response.json()
    with unscoped_reads(db):
        db.expire_all()
        assert all(db.get(Dive, dive_id).accepted_at for dive_id in alice_ids)
        assert db.get(Dive, bob_id).accepted_at is None
        assert all(db.get(Dive, dive_id).visibility == 'private' for dive_id in alice_ids)


def test_save_download_accepts_entire_batch_and_pages_manifest(workspace):
    db, login, machine, users, divers = workspace
    _sync_batch(machine, [_video('page-seed', 'alice')])
    seed = db.query(Dive).filter(Dive.diver_id == divers['alice'].id).one()
    batch_id = seed.batch_id
    for number in range(500):
        db.add(Dive(session_id=seed.session_id, diver_id=seed.diver_id, batch_id=batch_id,
                    dive_code='101B', height='3m', performance='G', performance_numeric=3, dive_datetime=seed.dive_datetime,
                    visibility='private', video_uuid=f'page-video-{number}'))
    db.commit()
    path = f'/api/v1/deposits/batches/{batch_id}/save-download?diver_id={divers["alice"].id}'
    first = login('alice').post(path).json()
    assert len(first['clips']) == 500 and first['next_offset'] == 500
    assert db.query(Dive).filter(Dive.batch_id == batch_id, Dive.accepted_at.is_(None)).count() == 0
    second = login('alice').post(path + '&offset=500').json()
    assert len(second['clips']) == 1 and second['next_offset'] is None
    assert second['clips'][0]['id'] not in {d['id'] for d in first['clips']}
