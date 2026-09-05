from datetime import datetime, timedelta

from app.models.dive import Dive
from app.models.media import MediaCacheEntry, MediaJob, RepresentativeMediaSelection
from app.models.photos_asset import PhotosAsset
from app.models.session import Session as SessionModel
from app.services.representative_media import (
    build_representative_media_manifest,
    replacement_candidates,
    representative_coverage,
    replace_representative,
    representative_gallery,
    plan_ready_representative_remap,
    remap_representatives_to_ready_media,
)


def _asset(test_db, uuid: str) -> PhotosAsset:
    asset = PhotosAsset(video_uuid=uuid, filename=f"{uuid}.mov")
    test_db.add(asset)
    test_db.flush()
    return asset


def _dive(test_db, session: SessionModel, *, code: str, performance: str, uuid: str, days: int = 0, sync: bool = False):
    asset = _asset(test_db, uuid)
    dive = Dive(
        session_id=session.id,
        dive_code=code,
        position=code[-1],
        performance=performance,
        performance_numeric={"F": 0, "B": 1, "M": 2, "G": 3, "P": 4}[performance],
        height="1m",
        platform_type="springboard",
        is_lineup=False,
        is_sync=sync,
        video_uuid=uuid,
        photos_asset_id=asset.id,
        raw_caption=f"{code} {performance}",
        dive_datetime=datetime(2026, 1, 1) + timedelta(days=days),
    )
    test_db.add(dive)
    test_db.flush()
    return dive


def test_manifest_selects_low_median_high_by_exact_canonical_code(test_db):
    session = SessionModel(date=datetime(2026, 1, 1).date())
    test_db.add(session)
    test_db.flush()
    low = _dive(test_db, session, code="103B", performance="B", uuid="manifest-103b-low", days=1)
    median = _dive(test_db, session, code="103B", performance="M", uuid="manifest-103b-median", days=2)
    high = _dive(test_db, session, code="103B", performance="P", uuid="manifest-103b-high", days=3)
    tuck = _dive(test_db, session, code="103C", performance="B", uuid="manifest-103c-low", days=4)
    straight = _dive(test_db, session, code="100B", performance="G", uuid="manifest-straight", days=5)
    test_db.add(
        MediaCacheEntry(
            photos_asset_id=high.photos_asset_id,
            media_key="a" * 64,
            rendition="poster",
            storage_path="/tmp/high-poster.jpg",
            content_type="image/jpeg",
            size_bytes=10,
            status="ready",
        )
    )
    test_db.add(
        MediaCacheEntry(
            photos_asset_id=high.photos_asset_id,
            media_key="b" * 64,
            rendition="proxy_360p",
            storage_path="/tmp/high-proxy.mp4",
            content_type="video/mp4",
            size_bytes=100,
            status="ready",
        )
    )
    test_db.add(
        MediaJob(
            photos_asset_id=low.photos_asset_id,
            media_key="c" * 64,
            rendition="poster",
            status="unavailable",
            last_error="materialization_unavailable",
        )
    )
    test_db.commit()

    manifest = build_representative_media_manifest(test_db)

    codes = {entry["dive_code"]: entry for entry in manifest["codes"]}
    assert "100B" not in codes
    assert "103B" in codes
    assert "103C" in codes
    assert [item["band"] for item in codes["103B"]["representatives"]] == ["low", "median", "high"]
    assert [item["attempt_id"] for item in codes["103B"]["representatives"]] == [low.id, median.id, high.id]
    assert codes["103B"]["representatives"][0]["performance"] == "B"
    assert codes["103B"]["representatives"][2]["cache"]["poster"]["ready"] is True
    assert codes["103B"]["representatives"][2]["cache"]["proxy_360p"]["ready"] is True
    assert "poster_previously_unavailable" in codes["103B"]["representatives"][0]["warnings"]
    assert codes["103C"]["representatives"][0]["attempt_id"] == tuck.id
    assert manifest["selection_policy"]["jobs_created"] is False
    assert test_db.query(MediaJob).count() == 1


def test_representative_gallery_is_read_only_and_reports_states(test_db):
    session = SessionModel(date=datetime(2026, 1, 1).date())
    test_db.add(session)
    test_db.flush()
    low = _dive(test_db, session, code="103B", performance="B", uuid="gallery-low", days=1)
    _dive(test_db, session, code="103B", performance="M", uuid="gallery-mid", days=2)
    high = _dive(test_db, session, code="103B", performance="P", uuid="gallery-high", days=3)
    test_db.add(MediaCacheEntry(
        photos_asset_id=high.photos_asset_id,
        media_key="e" * 64,
        rendition="poster",
        storage_path="/tmp/high.jpg",
        content_type="image/jpeg",
        size_bytes=10,
        status="ready",
    ))
    test_db.add(MediaJob(
        photos_asset_id=low.photos_asset_id,
        media_key="f" * 64,
        rendition="proxy_360p",
        status="unavailable",
        last_error="materialized_video_not_found",
    ))
    test_db.commit()

    before = test_db.query(MediaJob).count()
    gallery = representative_gallery(test_db, dive_code="103B")

    assert test_db.query(MediaJob).count() == before
    assert gallery["summary"]["canonical_dive_codes"] == 1
    reps = gallery["dives"][0]["representatives"]
    assert [rep["role"] for rep in reps] == ["low", "median", "high"]
    assert any(rep["media"]["state"].startswith("replacement_") for rep in reps)
    assert gallery["dives"][0]["coverage"]["poster_ready"] == 1


def test_replacement_candidates_are_bounded_same_code_and_exclude_selected(test_db):
    session = SessionModel(date=datetime(2026, 1, 1).date())
    test_db.add(session)
    test_db.flush()
    selected = _dive(test_db, session, code="103B", performance="M", uuid="replace-selected", days=1)
    _dive(test_db, session, code="103B", performance="M", uuid="replace-candidate", days=2)
    _dive(test_db, session, code="103C", performance="M", uuid="replace-other-code", days=3)
    for idx in range(10):
        _dive(test_db, session, code="103B", performance="M", uuid=f"replace-extra-{idx}", days=4 + idx)
    test_db.commit()

    candidates = replacement_candidates(test_db, "103B", "median", limit=5, current_dive_id=selected.id)

    assert len(candidates) == 5
    ids = {item["candidate"]["id"] for item in candidates}
    assert selected.id not in ids
    assert {item["candidate"]["dive_code"] for item in candidates} == {"103B"}


def test_replacement_candidates_prefer_untested_over_known_placeholder_failure(test_db):
    session = SessionModel(date=datetime(2026, 1, 1).date())
    test_db.add(session)
    test_db.flush()
    selected = _dive(test_db, session, code="103B", performance="M", uuid="viability-selected", days=1)
    placeholder = _dive(test_db, session, code="103B", performance="M", uuid="viability-placeholder", days=2)
    untested = _dive(test_db, session, code="103B", performance="M", uuid="viability-untested", days=3)
    test_db.add(MediaJob(
        photos_asset_id=placeholder.photos_asset_id,
        media_key="p" * 64,
        rendition="poster",
        status="unavailable",
        last_error="materialized_video_not_found",
    ))
    test_db.commit()

    candidates = replacement_candidates(test_db, "103B", "median", limit=5, current_dive_id=selected.id)

    assert candidates[0]["candidate"]["id"] == untested.id
    assert candidates[0]["media_viability"] == "untested"
    assert all(candidate["media_viability"] != "known_placeholder_failure" for candidate in candidates)


def test_replacement_candidates_include_placeholder_only_when_no_viable_alternative(test_db):
    session = SessionModel(date=datetime(2026, 1, 1).date())
    test_db.add(session)
    test_db.flush()
    selected = _dive(test_db, session, code="103B", performance="M", uuid="only-placeholder-selected", days=1)
    placeholder = _dive(test_db, session, code="103B", performance="M", uuid="only-placeholder-candidate", days=2)
    test_db.add(MediaJob(
        photos_asset_id=placeholder.photos_asset_id,
        media_key="q" * 64,
        rendition="poster",
        status="unavailable",
        last_error="materialized_video_not_found",
    ))
    test_db.commit()

    candidates = replacement_candidates(test_db, "103B", "median", limit=5, current_dive_id=selected.id)

    assert candidates
    assert candidates[0]["media_viability"] == "known_placeholder_failure"
    assert candidates[0]["materialization_history"]["last_error_code"] == "materialization_only_placeholders"


def test_representative_coverage_is_read_only_and_classifies_zero_ready(test_db):
    session = SessionModel(date=datetime(2026, 1, 1).date())
    test_db.add(session)
    test_db.flush()
    _dive(test_db, session, code="103B", performance="B", uuid="coverage-low", days=1)
    selected = _dive(test_db, session, code="103B", performance="M", uuid="coverage-selected", days=2)
    _dive(test_db, session, code="103B", performance="P", uuid="coverage-high", days=3)
    _dive(test_db, session, code="103B", performance="M", uuid="coverage-candidate", days=4)
    test_db.add(MediaJob(
        photos_asset_id=selected.photos_asset_id,
        media_key="r" * 64,
        rendition="poster",
        status="unavailable",
        last_error="materialized_video_not_found",
    ))
    test_db.commit()

    before = test_db.query(MediaJob).count()
    coverage = representative_coverage(test_db)

    assert test_db.query(MediaJob).count() == before
    assert coverage["read_only"] is True
    assert coverage["summary"]["codes"]["zero_ready"] == 1
    assert coverage["summary"]["zero_ready_categories"]["A"] == 1
    assert coverage["zero_ready_codes"][0]["viable_replacement_candidates"] > 0


def test_replace_preserves_history_and_prepare_false_creates_zero_jobs(test_db):
    session = SessionModel(date=datetime(2026, 1, 1).date())
    test_db.add(session)
    test_db.flush()
    original = _dive(test_db, session, code="103B", performance="M", uuid="history-original", days=1)
    replacement = _dive(test_db, session, code="103B", performance="M", uuid="history-replacement", days=2)
    _dive(test_db, session, code="103B", performance="B", uuid="history-low", days=3)
    _dive(test_db, session, code="103B", performance="P", uuid="history-high", days=4)
    test_db.add(RepresentativeMediaSelection(
        dive_code="103B",
        selection_role="median",
        dive_id=original.id,
        active=True,
        selection_reason="initial_manifest",
    ))
    test_db.commit()

    result = replace_representative(
        test_db,
        dive_code="103B",
        role="median",
        replacement_dive_id=replacement.id,
        prepare=False,
        renditions=["poster", "proxy_360p"],
    )
    test_db.commit()

    assert result["replacement_dive_id"] == replacement.id
    assert result["jobs"] == []
    assert test_db.query(MediaJob).count() == 0
    active = test_db.query(RepresentativeMediaSelection).filter_by(active=True, dive_code="103B", selection_role="median").one()
    inactive = test_db.query(RepresentativeMediaSelection).filter_by(active=False, dive_code="103B", selection_role="median").one()
    assert active.dive_id == replacement.id
    assert active.replaced_selection_id == inactive.id


def test_ready_media_remap_only_promotes_fully_cached_same_code_candidates(test_db):
    session = SessionModel(date=datetime(2026, 1, 1).date())
    test_db.add(session)
    test_db.flush()
    low = _dive(test_db, session, code="103B", performance="B", uuid="remap-low", days=1)
    original = _dive(test_db, session, code="103B", performance="M", uuid="remap-original", days=2)
    ready = _dive(test_db, session, code="103B", performance="M", uuid="remap-ready", days=3)
    _dive(test_db, session, code="103B", performance="P", uuid="remap-high", days=4)
    other_code = _dive(test_db, session, code="103C", performance="M", uuid="remap-other-code", days=5)
    test_db.add_all([
        MediaJob(photos_asset_id=original.photos_asset_id, media_key="s" * 64, rendition="poster", status="unavailable", last_error="materialized_video_not_found"),
        MediaCacheEntry(photos_asset_id=ready.photos_asset_id, media_key="t" * 64, rendition="poster", storage_path="/tmp/ready.jpg", content_type="image/jpeg", size_bytes=10, status="ready"),
        MediaCacheEntry(photos_asset_id=ready.photos_asset_id, media_key="u" * 64, rendition="proxy_360p", storage_path="/tmp/ready.mp4", content_type="video/mp4", size_bytes=100, status="ready"),
        RepresentativeMediaSelection(dive_code="103B", selection_role="median", dive_id=original.id, active=True, selection_reason="initial_manifest"),
    ])
    test_db.commit()

    jobs_before = test_db.query(MediaJob).count()
    plan = plan_ready_representative_remap(test_db)
    assert len(plan) == 1
    assert plan[0]["dive_code"] == "103B"
    assert plan[0]["role"] == "median"
    assert plan[0]["replacement"]["candidate"]["id"] == ready.id
    assert plan[0]["replacement"]["candidate"]["id"] != other_code.id

    result = remap_representatives_to_ready_media(test_db)
    test_db.commit()
    assert result["jobs_created"] == 0
    assert test_db.query(MediaJob).count() == jobs_before
    active = test_db.query(RepresentativeMediaSelection).filter_by(active=True, dive_code="103B", selection_role="median").one()
    assert active.dive_id == ready.id
    assert active.selection_reason == "auto_ready_media_remap"
