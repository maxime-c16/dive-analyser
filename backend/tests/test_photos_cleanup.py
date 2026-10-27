import hashlib
from types import SimpleNamespace

import pytest

from app.api.v1.media_backbone import PhotosCleanupCheck
from app.models.diver import Diver, DiverAlias
from app.models.photos_asset import PhotosAsset, PhotosAssetAgentIdentity
from app.models.media_backbone import MediaBlob, MediaBlobLocation, MediaRevision, CaptionRevision, IngestObjectState
from app.services.photos_cleanup import check_cleanup

VIDEO = "11111111-1111-1111-1111-111111111111"
LOCAL = "22222222-2222-2222-2222-222222222222"
SHA = "a" * 64
EDIT = "c" * 64


@pytest.fixture
def eligible(test_db, sample_dive):
    db, dive = test_db, sample_dive
    keeper = Diver(display_name="Keeper", canonical_name="keeper", is_primary_user=True)
    friend = Diver(display_name="Friend", canonical_name="friend")
    asset = PhotosAsset(video_uuid=VIDEO)
    db.add_all([keeper, friend, asset])
    db.flush()
    dive.video_uuid, dive.photos_asset_id, dive.diver_id = VIDEO, asset.id, friend.id
    dive.person_name, dive.raw_caption, dive.is_sync, dive.is_lineup = "Friend", "101B | Friend | note", False, False
    cap = hashlib.sha256(dive.raw_caption.encode()).hexdigest()
    identity = PhotosAssetAgentIdentity(photos_asset_id=asset.id, agent_id="mac-media-01", local_uuid=LOCAL)
    blob = MediaBlob(sha256=SHA, byte_size=100)
    loc = MediaBlobLocation(blob_sha256=SHA, environment="prod", storage_backend="b2", bucket="prod", object_key="blobs/test.mov", verified=True)
    rev = MediaRevision(video_uuid=VIDEO, blob_sha256=SHA, photos_edit_fingerprint=EDIT,
                        rendition_semantics="photos_edited_rendition", source_provenance={"photos_asset_uuid": LOCAL})
    caption = CaptionRevision(video_uuid=VIDEO, caption_raw=dive.raw_caption, caption_sha256=cap, caption_provider="test")
    ledger = IngestObjectState(video_uuid=VIDEO, blob_sha256=SHA, caption_sha256=cap, environment="prod", state="DB_COMMITTED", verified=True, object_key=loc.object_key)
    db.add_all([identity, blob, loc, rev, caption, ledger])
    db.flush()
    request = PhotosCleanupCheck(video_uuid=VIDEO, photos_uuid=LOCAL, agent_id="mac-media-01", keeper_diver_id=keeper.id,
                                 blob_sha256=SHA, byte_size=100, caption_sha256=cap, edit_fingerprint=EDIT, bucket="prod", object_key=loc.object_key)
    return SimpleNamespace(db=db, dive=dive, keeper=keeper, friend=friend, asset=asset, loc=loc,
                           rev=rev, caption=caption, ledger=ledger, request=request)


def test_only_verified_other_diver_is_eligible(eligible):
    e = eligible
    result = check_cleanup(e.db, e.request, "prod")
    assert result["eligible"] and result["diver_id"] == e.friend.id and result["photos_uuid"] == LOCAL


def test_cleanup_route_requires_machine_auth_and_validates_identity(eligible, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.database import get_db
    from app.config import get_settings
    e = eligible
    saved = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = lambda: e.db
    monkeypatch.setattr(get_settings(), "media_backbone_prod_bucket", "prod")
    try:
        client = TestClient(app)
        route = "/api/v1/media/backbone/photos-cleanup/check"
        body = e.request.model_dump()
        assert client.post(route, json=body).status_code in (401, 403)
        headers = {"X-API-Key": "test-api-key-1234567890abcdef"}
        response = client.post(route, json=body, headers=headers)
        assert response.status_code == 200 and response.json()["eligible"]
        body["photos_uuid"] = "../bad-identity"
        assert client.post(route, json=body, headers=headers).status_code == 422
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved)


@pytest.mark.parametrize("case", ["self", "primary", "inactive", "unknown", "blank", "ambiguous", "sync", "lineup",
    "changed_caption", "new_caption", "changed_edit", "wrong_blob", "wrong_local", "wrong_agent", "unverified",
    "dev", "bucket", "missing_ledger", "size", "location", "bad_keeper", "wrong_provenance", "ambiguous_dive"])
def test_refuses_uncertain_or_kept_assets(eligible, case):
    e = eligible
    if case == "self": e.dive.diver_id = e.keeper.id
    if case == "primary": e.friend.is_primary_user = True
    if case == "inactive": e.friend.active = False
    if case == "unknown": e.dive.diver_id = None
    if case == "blank": e.dive.person_name = None
    if case == "ambiguous": e.dive.person_name = "Someone else"
    if case == "sync": e.dive.is_sync = True
    if case == "lineup": e.dive.is_lineup = True
    if case == "changed_caption": e.dive.raw_caption += " changed"
    if case == "new_caption": e.caption.caption_sha256 = "d" * 64
    if case == "changed_edit": e.rev.photos_edit_fingerprint = "d" * 64
    if case == "wrong_blob": e.rev.blob_sha256 = "d" * 64
    if case == "wrong_local": e.request.photos_uuid = VIDEO
    if case == "wrong_agent": e.request.agent_id = "other-agent"
    if case == "unverified": e.loc.verified = False
    if case == "dev": e.loc.environment = "dev"
    if case == "bucket": e.loc.bucket = "wrong-bucket"
    if case == "missing_ledger": e.db.delete(e.ledger)
    if case == "size": e.request.byte_size += 1
    if case == "location": e.request.object_key = "another-object"
    if case == "bad_keeper": e.request.keeper_diver_id = e.friend.id
    if case == "wrong_provenance": e.rev.source_provenance = {"photos_asset_uuid": VIDEO}
    if case == "ambiguous_dive":
        from app.models.dive import Dive
        e.db.add(Dive(session_id=e.dive.session_id, photos_asset_id=e.asset.id, dive_code="101B", performance="G", performance_numeric=3, height="1m", dive_datetime=e.dive.dive_datetime))
    e.db.flush()
    assert check_cleanup(e.db, e.request, "prod")["eligible"] is False


def test_alias_rows_cannot_hide_a_second_matching_primary_diver(eligible):
    e = eligible
    # Friend sorts before this keeper; its canonical-name match joins both
    # aliases and used to consume the two-row limit before ORM deduplication.
    keeper = Diver(display_name="Another Keeper", canonical_name="another keeper", is_primary_user=True)
    e.db.add(keeper)
    e.db.flush()
    e.request.keeper_diver_id = keeper.id
    e.db.add_all([
        DiverAlias(diver_id=e.friend.id, alias="Friend One", canonical_alias="friend one"),
        DiverAlias(diver_id=e.friend.id, alias="Friend Two", canonical_alias="friend two"),
        DiverAlias(diver_id=keeper.id, alias="Friend", canonical_alias="friend"),
    ])
    e.db.flush()
    result = check_cleanup(e.db, e.request, "prod")
    assert result == {"eligible": False, "reason": "ambiguous_person"}


def test_multiple_aliases_for_one_resolved_diver_remain_eligible(eligible):
    e = eligible
    e.db.add_all([
        DiverAlias(diver_id=e.friend.id, alias="Friend One", canonical_alias="friend one"),
        DiverAlias(diver_id=e.friend.id, alias="Friend Two", canonical_alias="friend two"),
    ])
    e.db.flush()
    assert check_cleanup(e.db, e.request, "prod")["eligible"] is True
