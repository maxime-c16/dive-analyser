"""Regression coverage for the verified cache, query and workspace audit bugs."""

from collections import Counter
from datetime import datetime, timedelta

import pytest
from sqlalchemy import event, func
from sqlalchemy.orm import sessionmaker

from app.api.v1 import media
from app.api.v1.dive_analysis import _build_analysis
from app.config import get_settings
from app.models.cache import AnalyticsCache
from app.models.dive import Dive
from app.models.media_backbone import MediaBlobLocation, MediaRevision
from app.models.session import Session as TrainingSession
from app.models.user_auth import AppUser
from app.services.diver_identity import get_primary_diver, invalidate_analysis_cache
from app.services.personal_dive_value import PersonalDiveValueService
from app.services.sessions import create_session, revoke_session_by_raw_token


FILTERS = {"diver_scope": "all", "weighting": "attempts", "success_threshold": "G"}


def seed_dives(db, count):
    primary = get_primary_diver(db)
    training = TrainingSession(date=datetime(2026, 1, 1).date())
    db.add(training)
    db.flush()
    dives = [Dive(
        session_id=training.id, diver_id=primary.id, dive_code="103B",
        performance="G", performance_numeric=3, height="1m", position="B",
        is_lineup=False, dive_datetime=datetime(2026, 1, 1) + timedelta(minutes=i),
        updated_at=datetime(2026, 1, 1) + timedelta(seconds=i),
    ) for i in range(count)]
    db.add_all(dives)
    db.commit()
    return dives


def test_invalidation_removes_all_analysis_versions_and_preserves_other_caches(test_db):
    for key in ("dive-analysis:v2:old", "dive-analysis:v2.1:current", "dive-analysis:v3:future", "other:cache"):
        test_db.add(AnalyticsCache(cache_key=key, cache_data={}))
    test_db.commit()
    invalidate_analysis_cache(test_db)
    test_db.commit()
    assert [entry.cache_key for entry in test_db.query(AnalyticsCache)] == ["other:cache"]


def test_analytics_edit_and_delete_refresh_cached_summary(api_client, test_db):
    dive = seed_dives(test_db, 1)[0]
    url = "/api/v1/dive-analysis/103B?diver_scope=all"
    assert api_client.get(url).json()["summary"]["average"] == 7.0
    assert api_client.get(url).json()["observability"]["cache"] == "hit"
    assert api_client.put(f"/api/v1/dives/{dive.id}", json={"performance": "P", "performance_numeric": 4}).status_code == 200
    refreshed = api_client.get(url).json()
    assert refreshed["observability"]["cache"] == "miss"
    assert refreshed["summary"]["average"] == 10.0
    assert api_client.delete(f"/api/v1/dives/{dive.id}").status_code == 204
    assert api_client.get(url).json()["summary"]["attempt_count"] == 0


@pytest.mark.parametrize("count", [5, 20])
def test_cache_miss_does_not_reload_each_attempt_after_commit(test_db, count):
    seed_dives(test_db, count)
    engine = test_db.get_bind()
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(" ".join(statement.split()))

    event.listen(engine, "before_cursor_execute", capture)
    try:
        # Production defaults to expire_on_commit=True, unlike test_db.
        with sessionmaker(bind=engine)() as db:
            assert db.expire_on_commit is True
            response = _build_analysis(db, "103B", FILTERS)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(response["attempts"]) == count
    tables = Counter(s.split(" FROM ")[1].split()[0] for s in statements if s.startswith("SELECT") and " FROM " in s)
    assert tables["dives"] == 1
    assert tables["dive_modifiers"] == 1
    assert tables["sessions"] == 1
    assert tables["divers"] == 1
    assert tables["training_periods"] == 2


def test_cached_detail_free_endpoints_skip_attempt_queries(api_client, test_db, monkeypatch):
    seed_dives(test_db, 5)
    base = api_client.get("/api/v1/dive-analysis/103B").json()

    def unexpected(*args, **kwargs):
        pytest.fail("A detail-free cache hit must not load or serialize attempts")

    from app.services.dive_analysis_service import DiveAnalysisService
    monkeypatch.setattr(DiveAnalysisService, "query_dives", unexpected)
    monkeypatch.setattr(DiveAnalysisService, "serialize_attempts", unexpected)
    for suffix in ("phases", "insights", "breakdown?dimension=height", "compare?dimension=height"):
        response = api_client.get(f"/api/v1/dive-analysis/103B/{suffix}")
        assert response.status_code == 200
        body = response.json()
        assert body["observability"]["cache"] == "hit"
        assert body["observability"]["result_attempts"] == base["sample"]["attempt_count"]
        assert "attempts" not in body


def test_recent_values_detect_deletion_without_newest_timestamp_changing(test_db):
    dives = seed_dives(test_db, 5)
    service = PersonalDiveValueService(test_db)
    before = service.recent_values(5)
    deleted_id = dives[0].id
    newest = test_db.query(func.max(Dive.updated_at)).scalar()
    test_db.delete(dives[0])
    test_db.commit()
    assert test_db.query(func.max(Dive.updated_at)).scalar() == newest
    after = service.recent_values(5)
    assert len(before) == 5 and len(after) == 4
    assert deleted_id not in {item["attempt_id"] for item in after}


@pytest.fixture
def backbone_clock(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "user_auth_enabled", True)
    monkeypatch.setattr(settings, "b2_playback_canary_enabled", True)
    monkeypatch.setattr(settings, "media_backbone_lookup_cache_ttl_seconds", 30)
    clock = [100.0]
    monkeypatch.setattr(media, "monotonic", lambda: clock[0])
    media._backbone_id_cache.clear()
    yield clock
    media._backbone_id_cache.clear()


def add_revision(db, uuid, sha):
    revision = MediaRevision(video_uuid=uuid, blob_sha256=sha)
    db.add_all([revision, MediaBlobLocation(blob_sha256=sha, environment="prod", bucket="test", object_key=sha, verified=True)])
    db.commit()
    return revision.id


def test_backbone_negative_and_positive_cache_expire(test_db, backbone_clock):
    assert media._backbone_playback_url(test_db, "clip") is None
    first = add_revision(test_db, "clip", "a" * 64)
    assert media._backbone_playback_url(test_db, "clip") is None
    backbone_clock[0] += 30
    assert media._backbone_playback_url(test_db, "clip") == f"/api/v1/media/revisions/{first}/play"
    second = add_revision(test_db, "clip", "b" * 64)
    assert media._backbone_playback_url(test_db, "clip") == f"/api/v1/media/revisions/{first}/play"
    backbone_clock[0] += 30
    assert media._backbone_playback_url(test_db, "clip") == f"/api/v1/media/revisions/{second}/play"


def test_backbone_cache_is_bounded_and_can_be_disabled(test_db, backbone_clock, monkeypatch):
    monkeypatch.setattr(media, "_BACKBONE_CACHE_MAX_ENTRIES", 2)
    for uuid in ("one", "two", "three"):
        assert media._backbone_playback_url(test_db, uuid) is None
    assert len(media._backbone_id_cache) == 2
    assert (test_db.get_bind(), "one") not in media._backbone_id_cache
    monkeypatch.setattr(get_settings(), "media_backbone_lookup_cache_ttl_seconds", 0)
    # Disabling caching must also bypass an already cached negative lookup.
    revision = add_revision(test_db, "three", "c" * 64)
    assert media._backbone_playback_url(test_db, "three") == f"/api/v1/media/revisions/{revision}/play"
    assert media._backbone_playback_url(test_db, "disabled") is None
    assert (test_db.get_bind(), "disabled") not in media._backbone_id_cache


@pytest.mark.parametrize("path", [
    "/api/v1/dives", "/api/v1/dive-analysis/103B", "/api/v1/dive-analysis/103B/phases",
    "/api/v1/analytics/overall", "/api/v1/personal-dive-value/recent",
])
def test_workspace_requires_live_login_only_when_enabled(api_client, test_db, monkeypatch, path):
    seed_dives(test_db, 1)
    settings = get_settings()
    monkeypatch.setattr(settings, "personal_dive_value_enabled", True)
    monkeypatch.setattr(settings, "user_auth_enabled", False)
    assert api_client.get(path).status_code == 200
    monkeypatch.setattr(settings, "user_auth_enabled", True)
    assert api_client.get(path).status_code == 401
    user = AppUser(email="workspace@example.test", display_name="Workspace user")
    test_db.add(user)
    test_db.commit()
    token, _ = create_session(test_db, user_id=user.id, ttl_seconds=3600)
    # No UserDiverAccess grant: authenticated users share the workspace.
    headers = {"Cookie": f"{settings.auth_cookie_name}={token}"}
    assert api_client.get(path, headers=headers).status_code == 200
    revoke_session_by_raw_token(test_db, token)
    assert api_client.get(path, headers=headers).status_code == 401


def test_workspace_rejects_unauthenticated_writes(api_client, monkeypatch):
    monkeypatch.setattr(get_settings(), "user_auth_enabled", True)
    assert api_client.put("/api/v1/dives/1", json={"notes": "anonymous"}).status_code == 401
    assert api_client.delete("/api/v1/dives/1").status_code == 401
