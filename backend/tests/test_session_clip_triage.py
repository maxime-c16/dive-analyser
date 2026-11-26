"""Tests for session clip auto-detection runs, fast triage, GT export, B2 persistence, and Mac cut leases."""
from __future__ import annotations

from datetime import date, datetime, timedelta
import hashlib
from pathlib import Path
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import session_clips as session_clips_api
from app.config import get_settings
from app.main import app
from app.models.deposit_batch import BatchEmailOutbox, EvaluatorNote
from app.models.dive import Dive
from app.models.diver import Diver
from app.models.media import MediaAgent, MediaCacheEntry
from app.models.media_backbone import MediaBlobLocation, MediaRevision
from app.models.session import Session as TrainingSession
from app.models.session_clip_triage import SessionClipCandidate
from app.models.session_video import SessionVideo
from app.models.user_auth import AppUser
from app.services import browser_upload, session_videos as sv_service
from tests.test_member_dive_visibility import workspace  # noqa: F401

API_KEY = "test-api-key-1234567890abcdef"
WORKER_KEY = "test-media-worker-key-abcdef123456"
OTHER_WORKER_KEY = "test-other-worker-key-9876543210"
ORIGIN = {"Origin": "http://testserver"}


def _make_real_mp4_bytes(tmp_path: Path, duration_s: float = 2.0, name: str = "tiny_real.mp4") -> bytes:
    """Generate a tiny real H.264 MP4 via ffmpeg so server ffprobe + poster extraction are truly exercised."""
    out = tmp_path / name
    res = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-nostdin",
            "-v", "error",
            "-f", "lavfi",
            "-i", f"color=c=teal:s=160x120:d={duration_s:.1f}:r=15",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(out),
        ],
        capture_output=True,
        timeout=20,
    )
    assert res.returncode == 0, f"ffmpeg failed: {res.stderr.decode('utf-8', 'replace')}"
    return out.read_bytes()


@pytest.fixture
def clip_env(workspace, monkeypatch, tmp_path):
    db, as_user, _, users, training_id = workspace
    settings = get_settings()
    monkeypatch.setattr(settings, "shared_sessions_enabled", True)
    monkeypatch.setattr(settings, "media_cache_root", str(tmp_path))

    presign_calls: list[dict] = []

    def _fake_presign(bucket, key, ttl, **kw):
        presign_calls.append({"bucket": bucket, "key": key, "ttl": ttl, **kw})
        return f"https://b2.example/{bucket}/{key}?ttl={ttl}"

    monkeypatch.setattr(sv_service, "presign_get", _fake_presign)

    persisted_uploads: list[dict] = []

    def _fake_persist_original(_db, video_uuid, folder, *, register=True, source_name="original.mp4"):
        src = Path(folder) / source_name
        raw = src.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        manifest = {
            "video_uuid": video_uuid,
            "blob_sha256": sha,
            "byte_size": len(raw),
            "object_key": f"media/{sha[:2]}/{sha}",
            "storage_backend": "b2",
            "bucket": "diveanalyzer-dev-media",
            "environment": "dev",
            "media_only": True,
            "media_only_reason": "Session clip cut stored on dive record",
            "rendition_semantics": "session_clip_cut",
            "source_provenance": {"source": "session_clip_cut"},
            "ingest_impl_version": "session_clip_cut_v1",
            "codec": "h264",
            "width": 160,
            "height": 120,
        }
        persisted_uploads.append(manifest)
        return manifest

    monkeypatch.setattr(browser_upload, "persist_original", _fake_persist_original)

    agent_ok = MediaAgent(
        id="mac-media-01",
        hostname="mac-mini.local",
        api_key_sha256=hashlib.sha256(WORKER_KEY.encode()).hexdigest(),
        capabilities=["original", "poster"],
        active=True,
        leasing_enabled=True,
    )
    agent_paused = MediaAgent(
        id="mac-media-paused",
        hostname="mac-paused.local",
        api_key_sha256=hashlib.sha256(OTHER_WORKER_KEY.encode()).hexdigest(),
        capabilities=["original"],
        active=True,
        leasing_enabled=False,
    )
    db.add_all([agent_ok, agent_paused])

    admin = db.get(AppUser, users["alice"].id)
    admin.is_admin = True
    bob_user = db.get(AppUser, users["bob"].id)
    bob_user.is_admin = False
    db.flush()

    alice_diver = db.query(Diver).filter_by(canonical_name="alice").one()
    bob_diver = db.query(Diver).filter_by(canonical_name="bob").one()
    session = db.get(TrainingSession, training_id)

    video = SessionVideo(
        session_id=session.id,
        owner_user_id=admin.id,
        bucket="diveanalyzer-sessions",
        object_key="inbox/IMG_2651.MOV",
        etag="etag-v1",
        status="ready",
        recorded_at=datetime(2026, 11, 25, 17, 5, 0),
        recorded_date=date(2026, 11, 25),
        duration_seconds=1800.0,
        size_bytes=3_300_000_000,
        codec_string="hvc1.2.4.L123.B0",
        color_transfer="arib-std-b67",
        video_codec="hevc",
        width=1920,
        height=1080,
        fps=60.0,
    )
    db.add(video)
    db.commit()
    db.refresh(video)
    return {
        "db": db,
        "as_user": as_user,
        "tmp_path": tmp_path,
        "admin_id": admin.id,
        "bob_user_id": bob_user.id,
        "alice_diver_id": alice_diver.id,
        "bob_diver_id": bob_diver.id,
        "session_id": session.id,
        "video_id": video.id,
        "persisted_uploads": persisted_uploads,
        "presign_calls": presign_calls,
    }


def test_submit_dedup_after_aggressive_trim_and_gt_pagination(clip_env):
    video_id = clip_env["video_id"]
    api_client = TestClient(app)
    as_user = clip_env["as_user"]

    res = api_client.get(
        "/api/v1/clip-triage/resolve-video",
        params={"filename": "IMG_2651.MOV"},
        headers={"X-API-Key": API_KEY},
    )
    assert res.status_code == 200
    assert res.json()["items"][0]["id"] == video_id

    # Push run v1.0 with intra-run overlap + out-of-range detection
    r1 = api_client.post(
        f"/api/v1/session-videos/{video_id}/clip-runs",
        headers={"X-API-Key": API_KEY},
        json={
            "detector_name": "core_detection",
            "detector_version": "v1.0",
            "candidates": [
                {"start_s": 100.0, "end_s": 110.0, "confidence": 0.91},
                {"start_s": 100.4, "end_s": 110.2, "confidence": 0.95},  # intra-run overlap
                {"start_s": 250.0, "end_s": 261.0, "confidence": 0.55},
                {"start_s": 1850.0, "end_s": 1860.0, "confidence": 0.80},  # out of range -> dropped
            ],
        },
    )
    assert r1.status_code == 201
    assert r1.json()["created_count"] == 2
    assert r1.json()["deduped_count"] == 1

    # Aggressively trim [100,110] -> [108,110] and reject #2
    admin_client = as_user("alice")
    items = admin_client.get("/api/v1/clip-triage/candidates", params={"tab": "pending"}).json()["items"]
    c1, c2 = items[0], items[1]

    keep_res = admin_client.patch(
        f"/api/v1/clip-triage/candidates/{c1['id']}",
        headers=ORIGIN,
        json={
            "diver_id": clip_env["bob_diver_id"],
            "trimmed_start_s": 108.0,
            "trimmed_end_s": 110.0,
            "triage_status": "kept",
        },
    )
    assert keep_res.status_code == 200
    admin_client.patch(
        f"/api/v1/clip-triage/candidates/{c2['id']}",
        headers=ORIGIN,
        json={"triage_status": "rejected", "reject_reason": "false_positive"},
    )

    # Identical detector rerun [100,110] MUST STILL dedup against original bounds (never recreate a duplicate!)
    r2 = api_client.post(
        f"/api/v1/session-videos/{video_id}/clip-runs",
        headers={"X-API-Key": API_KEY},
        json={
            "detector_name": "core_detection",
            "detector_version": "v1.1",
            "candidates": [
                {"start_s": 100.0, "end_s": 110.0, "confidence": 0.96},
                {"start_s": 249.5, "end_s": 261.5, "confidence": 0.50},
                {"start_s": 420.0, "end_s": 433.0, "confidence": 0.88},
            ],
        },
    )
    assert r2.status_code == 201
    assert r2.json()["created_count"] == 1
    assert r2.json()["deduped_count"] == 2
    assert r2.json()["preserved_triaged_count"] == 2

    # Paginated GT export preserves full-scope counts
    gt_p1 = api_client.get(
        f"/api/v1/session-videos/{video_id}/clip-gt",
        params={"limit": 1, "offset": 0},
        headers={"X-API-Key": API_KEY},
    ).json()
    assert gt_p1["counts"] == {"positives": 1, "negatives": 1, "trimmed": 1}
    assert gt_p1["has_more"] is True
    assert gt_p1["next_offset"] == 1


def test_shrinking_pending_queue_with_exclude_ids_never_skips(clip_env):
    video_id = clip_env["video_id"]
    api_client = TestClient(app)
    as_user = clip_env["as_user"]

    # Push 80 distinct non-overlapping candidates (spaced 20s apart)
    cands = [{"start_s": float(i * 20), "end_s": float(i * 20 + 5)} for i in range(80)]
    r = api_client.post(
        f"/api/v1/session-videos/{video_id}/clip-runs",
        headers={"X-API-Key": API_KEY},
        json={"detector_name": "core", "detector_version": "v1", "candidates": cands},
    )
    assert r.status_code == 201
    assert r.json()["created_count"] == 80

    admin = as_user("alice")
    page1 = admin.get("/api/v1/clip-triage/candidates", params={"tab": "pending", "limit": 50, "offset": 0}).json()
    assert len(page1["items"]) == 50
    assert page1["has_more"] is True

    # Reject 45 items from page 1, leaving 5 locally hosted
    for item in page1["items"][:45]:
        res = admin.patch(
            f"/api/v1/clip-triage/candidates/{item['id']}",
            headers=ORIGIN,
            json={"triage_status": "rejected"},
        )
        assert res.status_code == 200

    remaining_local = [item["id"] for item in page1["items"][45:]]
    # Refetch at offset=0 with exclude_ids of the 5 locally hosted items -> gets ALL 30 remaining!
    page2 = admin.get(
        "/api/v1/clip-triage/candidates",
        params={
            "tab": "pending",
            "limit": 50,
            "offset": 0,
            "exclude_ids": ",".join(str(i) for i in remaining_local),
        },
    ).json()
    assert len(page2["items"]) == 30
    assert page2["has_more"] is False
    assert set(remaining_local).isdisjoint({i["id"] for i in page2["items"]})


def test_access_control_anti_oracle_and_non_admin_diver_masking(clip_env):
    db = clip_env["db"]
    video_id = clip_env["video_id"]
    api_client = TestClient(app)
    as_user = clip_env["as_user"]

    api_client.post(
        f"/api/v1/session-videos/{video_id}/clip-runs",
        headers={"X-API-Key": API_KEY},
        json={
            "detector_name": "core_detection",
            "detector_version": "v1.2",
            "candidates": [{"start_s": 30.0, "end_s": 42.0, "confidence": 0.9}],
        },
    )
    admin_cand = as_user("alice").get("/api/v1/clip-triage/candidates").json()["items"][0]

    # Non-manager Bob gets empty list, divers=[], and uniform 404 on direct candidate & video endpoints
    bob_q = as_user("bob").get("/api/v1/clip-triage/candidates").json()
    assert bob_q["items"] == []
    assert bob_q["divers"] == []
    assert as_user("bob").get(f"/api/v1/clip-triage/candidates/{admin_cand['id']}").status_code == 404
    assert as_user("bob").get("/api/v1/clip-triage/candidates/999999").status_code == 404
    assert as_user("bob").get(f"/api/v1/session-videos/{video_id}/clip-runs").status_code == 404
    assert as_user("bob").get(f"/api/v1/session-videos/{video_id}/clip-gt").status_code == 404

    # Bob owns his own video; admin assigns Alice to a clip on Bob's video -> Bob MUST NOT see Alice's name!
    bob_video = SessionVideo(
        session_id=clip_env["session_id"],
        owner_user_id=clip_env["bob_user_id"],
        bucket="diveanalyzer-sessions",
        object_key="inbox/BOB_OWN.MOV",
        status="ready",
        recorded_date=date(2026, 11, 25),
        duration_seconds=600.0,
        size_bytes=100_000,
    )
    db.add(bob_video)
    db.commit()
    db.refresh(bob_video)
    bob_video_id = bob_video.id

    as_user("bob").post(
        f"/api/v1/session-videos/{bob_video_id}/clip-runs",
        headers=ORIGIN,
        json={"detector_name": "core", "detector_version": "v1", "candidates": [{"start_s": 10.0, "end_s": 20.0}]},
    )
    bob_list = as_user("bob").get("/api/v1/clip-triage/candidates").json()
    cand_id = bob_list["items"][0]["id"]
    assert [d["id"] for d in bob_list["divers"]] == [clip_env["bob_diver_id"]]

    # Bob cannot assign Alice (403)
    assert as_user("bob").patch(
        f"/api/v1/clip-triage/candidates/{cand_id}",
        headers=ORIGIN,
        json={"diver_id": clip_env["alice_diver_id"], "triage_status": "kept"},
    ).status_code == 403

    # Admin assigns Alice on Bob's video -> Bob's list, direct GET, and GT export mask Alice's diver_id & diver_name!
    assert as_user("alice").patch(
        f"/api/v1/clip-triage/candidates/{cand_id}",
        headers=ORIGIN,
        json={"diver_id": clip_env["alice_diver_id"], "triage_status": "kept"},
    ).status_code == 200

    bob_recent = as_user("bob").get("/api/v1/clip-triage/candidates", params={"tab": "recent"}).json()["items"][0]
    assert bob_recent["diver_id"] is None
    assert bob_recent["diver_name"] is None
    bob_direct = as_user("bob").get(f"/api/v1/clip-triage/candidates/{cand_id}").json()
    assert bob_direct["diver_id"] is None
    assert bob_direct["diver_name"] is None
    bob_gt = as_user("bob").get(f"/api/v1/session-videos/{bob_video_id}/clip-gt").json()
    assert bob_gt["positives"][0]["diver_id"] is None
    assert bob_gt["positives"][0]["diver_name"] is None

    # Bob CANNOT confirm_publish on a clip assigned to Alice (403, cannot piggyback on admin's keep!)
    confirm_forbid = as_user("bob").patch(
        f"/api/v1/clip-triage/candidates/{cand_id}",
        headers=ORIGIN,
        json={"dive_code": "103B", "height": "3m", "performance": "G", "confirm_publish": True},
    )
    assert confirm_forbid.status_code == 403


def test_worker_auth_fencing_confirm_invalidation_recut_and_guardrails(clip_env, monkeypatch):
    db = clip_env["db"]
    video_id = clip_env["video_id"]
    api_client = TestClient(app)
    as_user = clip_env["as_user"]
    mp4_2s = _make_real_mp4_bytes(clip_env["tmp_path"], duration_s=2.0, name="cut_2s.mp4")
    mp4_3s = _make_real_mp4_bytes(clip_env["tmp_path"], duration_s=3.0, name="cut_3s.mp4")

    # Candidate window is 2.5s ([500.0, 502.5]) so 2.0s and 3.0s cuts are within duration tolerance!
    api_client.post(
        f"/api/v1/session-videos/{video_id}/clip-runs",
        headers={"X-API-Key": API_KEY},
        json={
            "detector_name": "core_detection",
            "detector_version": "v1.4",
            "candidates": [{"start_s": 500.0, "end_s": 502.5, "confidence": 0.95}],
        },
    )
    admin_client = as_user("alice")
    cand = admin_client.get("/api/v1/clip-triage/candidates").json()["items"][0]

    # Confirm at 3m, then edit height to None -> prior confirmation MUST be cleared!
    kept = admin_client.patch(
        f"/api/v1/clip-triage/candidates/{cand['id']}",
        headers=ORIGIN,
        json={
            "diver_id": clip_env["bob_diver_id"],
            "dive_code": "103B",
            "height": "3m",
            "performance": "G",
            "notes": "Super appel",
            "visibility": "public",
            "triage_status": "kept",
            "confirm_publish": True,
        },
    )
    assert kept.status_code == 200
    assert kept.json()["publish_requested"] is True

    # Editing height clears publish_requested!
    cleared = admin_client.patch(
        f"/api/v1/clip-triage/candidates/{cand['id']}",
        headers=ORIGIN,
        json={"height": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["publish_requested"] is False

    # Worker auth binding checks: wrong key -> 403, leasing-disabled -> 403
    assert api_client.post(
        "/api/v1/media/clip-cuts/lease",
        headers={"X-API-Key": OTHER_WORKER_KEY},
        json={"agent_id": "mac-media-01", "limit": 1},
    ).status_code == 403
    assert api_client.post(
        "/api/v1/media/clip-cuts/lease",
        headers={"X-API-Key": OTHER_WORKER_KEY},
        json={"agent_id": "mac-media-paused", "limit": 1},
    ).status_code == 403

    # Valid lease includes source_etag and passes if_match to presign_get!
    lease = api_client.post(
        "/api/v1/media/clip-cuts/lease",
        headers={"X-API-Key": WORKER_KEY},
        json={"agent_id": "mac-media-01", "limit": 1},
    )
    assert lease.status_code == 200
    job1 = lease.json()["jobs"][0]
    assert job1["source_etag"] == "etag-v1"
    assert clip_env["presign_calls"][-1]["if_match"] == "etag-v1"

    # Upload guardrails: 413 oversized Content-Length, 429 busy semaphore, 507 disk full, 422 garbage
    oversized = api_client.post(
        f"/api/v1/media/clip-cuts/{cand['id']}/complete",
        headers={
            "X-API-Key": WORKER_KEY,
            "X-Media-Agent-Id": "mac-media-01",
            "X-Lease-Token": job1["lease_token"],
            "X-Cut-Revision": str(job1["cut_revision"]),
            "Content-Length": str(session_clips_api.MAX_CUT_UPLOAD_BYTES + 1),
        },
        content=b"",
    )
    assert oversized.status_code == 413

    assert session_clips_api._COMPLETE_SLOTS.acquire(blocking=False) is True
    try:
        busy = api_client.post(
            f"/api/v1/media/clip-cuts/{cand['id']}/complete",
            headers={
                "X-API-Key": WORKER_KEY,
                "X-Media-Agent-Id": "mac-media-01",
                "X-Lease-Token": job1["lease_token"],
                "X-Cut-Revision": str(job1["cut_revision"]),
            },
            content=mp4_2s,
        )
        assert busy.status_code == 429
    finally:
        session_clips_api._COMPLETE_SLOTS.release()

    orig_disk = shutil.disk_usage
    monkeypatch.setattr(shutil, "disk_usage", lambda _p: shutil._ntuple_diskusage(1000, 999, 1))
    disk_full = api_client.post(
        f"/api/v1/media/clip-cuts/{cand['id']}/complete",
        headers={
            "X-API-Key": WORKER_KEY,
            "X-Media-Agent-Id": "mac-media-01",
            "X-Lease-Token": job1["lease_token"],
            "X-Cut-Revision": str(job1["cut_revision"]),
        },
        content=mp4_2s,
    )
    assert disk_full.status_code == 507
    monkeypatch.setattr(shutil, "disk_usage", orig_disk)

    # Confirm semaphore was NOT leaked by 507!
    assert session_clips_api._COMPLETE_SLOTS.acquire(blocking=False) is True
    session_clips_api._COMPLETE_SLOTS.release()

    # Garbage bytes -> 422
    assert api_client.post(
        f"/api/v1/media/clip-cuts/{cand['id']}/complete",
        headers={
            "X-API-Key": WORKER_KEY,
            "X-Media-Agent-Id": "mac-media-01",
            "X-Lease-Token": job1["lease_token"],
            "X-Cut-Revision": str(job1["cut_revision"]),
        },
        content=b"not-a-valid-mp4",
    ).status_code == 422

    # Valid upload succeeds -> stays 'ready' because publish_requested was cleared by height edit!
    comp1 = api_client.post(
        f"/api/v1/media/clip-cuts/{cand['id']}/complete",
        headers={
            "X-API-Key": WORKER_KEY,
            "X-Media-Agent-Id": "mac-media-01",
            "X-Lease-Token": job1["lease_token"],
            "X-Cut-Revision": str(job1["cut_revision"]),
        },
        content=mp4_2s,
    )
    assert comp1.status_code == 200
    assert comp1.json()["extraction_status"] == "ready"
    assert comp1.json()["dive_id"] is None

    # Autosaving height=5m WITHOUT confirm_publish MUST NOT publish!
    autosaved = admin_client.patch(
        f"/api/v1/clip-triage/candidates/{cand['id']}",
        headers=ORIGIN,
        json={"height": "5m"},
    )
    assert autosaved.status_code == 200
    assert autosaved.json()["dive_id"] is None
    assert autosaved.json()["publish_requested"] is False

    # Verify old staging folder exists, then trim to trigger re-cut -> replaces cache & removes old dir!
    db.expire_all()
    cand_row = db.get(SessionClipCandidate, cand["id"])
    old_entry = db.query(MediaCacheEntry).filter_by(rendition="original").one()
    old_dir = Path(old_entry.storage_path).parent
    assert old_dir.is_dir()
    assert not (old_dir / "metadata.json").exists()

    # Trim [500.0, 502.5] -> [500.0, 503.0] -> rotates clip_video_uuid, cleans old folder, re-queues extraction
    trimmed = admin_client.patch(
        f"/api/v1/clip-triage/candidates/{cand['id']}",
        headers=ORIGIN,
        json={"trimmed_start_s": 500.0, "trimmed_end_s": 503.0},
    )
    assert trimmed.status_code == 200
    assert trimmed.json()["cut_revision"] == 2
    assert trimmed.json()["extraction_status"] == "queued"
    assert not old_dir.exists()

    # Lease revision 2 and complete with matching 3.0s cut
    job2 = api_client.post(
        "/api/v1/media/clip-cuts/lease",
        headers={"X-API-Key": WORKER_KEY},
        json={"agent_id": "mac-media-01", "limit": 1},
    ).json()["jobs"][0]
    assert job2["cut_revision"] == 2
    clip_uuid = job2["clip_video_uuid"]

    # Confirm publish, then test confirm_publish=False revokes it cleanly!
    assert admin_client.patch(
        f"/api/v1/clip-triage/candidates/{cand['id']}",
        headers=ORIGIN,
        json={"confirm_publish": True},
    ).json()["publish_requested"] is True
    assert admin_client.patch(
        f"/api/v1/clip-triage/candidates/{cand['id']}",
        headers=ORIGIN,
        json={"confirm_publish": False},
    ).json()["publish_requested"] is False

    # Re-cut completes under rotated clip_video_uuid
    comp2 = api_client.post(
        f"/api/v1/media/clip-cuts/{cand['id']}/complete",
        headers={
            "X-API-Key": WORKER_KEY,
            "X-Media-Agent-Id": "mac-media-01",
            "X-Lease-Token": job2["lease_token"],
            "X-Cut-Revision": str(job2["cut_revision"]),
        },
        content=mp4_3s,
    )
    assert comp2.status_code == 200
    assert comp2.json()["extraction_status"] == "ready"

    # Verify MediaRevision + verified MediaBlobLocation
    db.expire_all()
    assert db.query(MediaRevision).filter_by(video_uuid=clip_uuid).count() >= 1
    assert db.query(MediaBlobLocation).filter_by(
        blob_sha256=clip_env["persisted_uploads"][-1]["blob_sha256"],
        verified=True,
    ).count() == 1

    # Simulate prior sent batch -> publish allocates fresh batch suffix, then second clip reuses that held batch!
    db.add(
        BatchEmailOutbox(
            batch_id=f"clip-sv-{video_id}",
            diver_id=clip_env["bob_diver_id"],
            user_id=clip_env["bob_user_id"],
            scheduled_for=datetime.utcnow(),
            status=BatchEmailOutbox.STATUS_SENT,
        )
    )
    db.commit()

    pub = admin_client.patch(
        f"/api/v1/clip-triage/candidates/{cand['id']}",
        headers=ORIGIN,
        json={"confirm_publish": True},
    )
    assert pub.status_code == 200
    pdata = pub.json()
    assert pdata["extraction_status"] == "published"
    db.expire_all()
    dive = db.get(Dive, pdata["dive_id"])
    assert dive.batch_id != f"clip-sv-{video_id}"
    assert dive.batch_id.startswith(f"clip-sv-{video_id}-")
    assert dive.visibility == "private"
    assert dive.accepted_at is None
    assert db.query(EvaluatorNote).filter_by(dive_id=dive.id).one().comment == "Super appel"
    assert db.query(BatchEmailOutbox).filter_by(batch_id=dive.batch_id, diver_id=dive.diver_id).one().status == BatchEmailOutbox.STATUS_HELD


def test_duration_mismatch_422_and_trim_mid_upload_409(clip_env, monkeypatch):
    video_id = clip_env["video_id"]
    api_client = TestClient(app)
    as_user = clip_env["as_user"]
    mp4_1s = _make_real_mp4_bytes(clip_env["tmp_path"], duration_s=1.0, name="short_1s.mp4")

    # 12-second candidate
    api_client.post(
        f"/api/v1/session-videos/{video_id}/clip-runs",
        headers={"X-API-Key": API_KEY},
        json={
            "detector_name": "core",
            "detector_version": "v1",
            "candidates": [{"start_s": 20.0, "end_s": 32.0}],
        },
    )
    admin = as_user("alice")
    cand = admin.get("/api/v1/clip-triage/candidates").json()["items"][0]
    admin.patch(
        f"/api/v1/clip-triage/candidates/{cand['id']}",
        headers=ORIGIN,
        json={"diver_id": clip_env["alice_diver_id"], "triage_status": "kept"},
    )
    job = api_client.post(
        "/api/v1/media/clip-cuts/lease",
        headers={"X-API-Key": WORKER_KEY},
        json={"agent_id": "mac-media-01", "limit": 1},
    ).json()["jobs"][0]

    # Uploading a 1.0s clip for a 12.0s leased window MUST be rejected with 422!
    mismatch = api_client.post(
        f"/api/v1/media/clip-cuts/{cand['id']}/complete",
        headers={
            "X-API-Key": WORKER_KEY,
            "X-Media-Agent-Id": "mac-media-01",
            "X-Lease-Token": job["lease_token"],
            "X-Cut-Revision": str(job["cut_revision"]),
        },
        content=mp4_1s,
    )
    assert mismatch.status_code == 422

    # Trim during upload (simulated inside persist_original) -> final commit MUST return 409 & clean staging!
    mp4_12s = _make_real_mp4_bytes(clip_env["tmp_path"], duration_s=11.5, name="full_11_5s.mp4")
    orig_persist = browser_upload.persist_original

    def _persist_with_mid_trim(_db, video_uuid, folder, *, register=True, source_name="original.mp4"):
        manifest = orig_persist(_db, video_uuid, folder, register=register, source_name=source_name)
        # Simulate user trimming the clip while B2 upload was in flight!
        res = admin.patch(
            f"/api/v1/clip-triage/candidates/{cand['id']}",
            headers=ORIGIN,
            json={"trimmed_start_s": 21.0, "trimmed_end_s": 31.0},
        )
        assert res.status_code == 200
        return manifest

    monkeypatch.setattr(browser_upload, "persist_original", _persist_with_mid_trim)
    raced = api_client.post(
        f"/api/v1/media/clip-cuts/{cand['id']}/complete",
        headers={
            "X-API-Key": WORKER_KEY,
            "X-Media-Agent-Id": "mac-media-01",
            "X-Lease-Token": job["lease_token"],
            "X-Cut-Revision": str(job["cut_revision"]),
        },
        content=mp4_12s,
    )
    assert raced.status_code == 409
    staging_root = clip_env["tmp_path"] / "session-clips"
    assert list(staging_root.glob("cand-*")) == []


def test_exhausted_expired_lease_transitions_to_failed(clip_env):
    db = clip_env["db"]
    video_id = clip_env["video_id"]
    api_client = TestClient(app)
    as_user = clip_env["as_user"]

    api_client.post(
        f"/api/v1/session-videos/{video_id}/clip-runs",
        headers={"X-API-Key": API_KEY},
        json={
            "detector_name": "core_detection",
            "detector_version": "v1.5",
            "candidates": [{"start_s": 10.0, "end_s": 22.0}],
        },
    )
    admin_client = as_user("alice")
    cand = admin_client.get("/api/v1/clip-triage/candidates").json()["items"][0]
    admin_client.patch(
        f"/api/v1/clip-triage/candidates/{cand['id']}",
        headers=ORIGIN,
        json={"diver_id": clip_env["alice_diver_id"], "triage_status": "kept"},
    )

    row = db.get(SessionClipCandidate, cand["id"])
    row.extraction_status = "extracting"
    row.extraction_attempts = 5
    row.claimed_until = datetime.utcnow() - timedelta(minutes=10)
    db.commit()

    lease = api_client.post(
        "/api/v1/media/clip-cuts/lease",
        headers={"X-API-Key": WORKER_KEY},
        json={"agent_id": "mac-media-01", "limit": 1},
    )
    assert lease.status_code == 200
    assert lease.json()["jobs"] == []

    db.expire_all()
    refreshed = db.get(SessionClipCandidate, cand["id"])
    assert refreshed.extraction_status == "failed"
    assert refreshed.lease_token is None


def test_trim_a_b_a_rotates_revision_and_inactive_confirmer_blocks_deferred_publish(clip_env):
    from app.services.media_backbone import resolve_media_revision_location

    db = clip_env["db"]
    video_id = clip_env["video_id"]
    api_client = TestClient(app)
    as_user = clip_env["as_user"]
    mp4_a = _make_real_mp4_bytes(clip_env["tmp_path"], duration_s=2.0, name="aba_a.mp4")
    mp4_b = _make_real_mp4_bytes(clip_env["tmp_path"], duration_s=3.0, name="aba_b.mp4")
    sha_a = hashlib.sha256(mp4_a).hexdigest()

    # 1. Start at trim A [10, 12], cut A
    api_client.post(
        f"/api/v1/session-videos/{video_id}/clip-runs",
        headers={"X-API-Key": API_KEY},
        json={"detector_name": "core", "detector_version": "v1", "candidates": [{"start_s": 10.0, "end_s": 12.0}]},
    )
    admin = as_user("alice")
    cand = admin.get("/api/v1/clip-triage/candidates").json()["items"][0]
    admin.patch(
        f"/api/v1/clip-triage/candidates/{cand['id']}",
        headers=ORIGIN,
        json={"diver_id": clip_env["bob_diver_id"], "dive_code": "103B", "height": "3m", "performance": "G", "triage_status": "kept"},
    )
    j1 = api_client.post("/api/v1/media/clip-cuts/lease", headers={"X-API-Key": WORKER_KEY}, json={"agent_id": "mac-media-01"}).json()["jobs"][0]
    assert api_client.post(
        f"/api/v1/media/clip-cuts/{cand['id']}/complete",
        headers={"X-API-Key": WORKER_KEY, "X-Media-Agent-Id": "mac-media-01", "X-Lease-Token": j1["lease_token"], "X-Cut-Revision": str(j1["cut_revision"])},
        content=mp4_a,
    ).status_code == 200

    # 2. Trim to B [10, 13], cut B
    admin.patch(f"/api/v1/clip-triage/candidates/{cand['id']}", headers=ORIGIN, json={"trimmed_start_s": 10.0, "trimmed_end_s": 13.0})
    j2 = api_client.post("/api/v1/media/clip-cuts/lease", headers={"X-API-Key": WORKER_KEY}, json={"agent_id": "mac-media-01"}).json()["jobs"][0]
    assert api_client.post(
        f"/api/v1/media/clip-cuts/{cand['id']}/complete",
        headers={"X-API-Key": WORKER_KEY, "X-Media-Agent-Id": "mac-media-01", "X-Lease-Token": j2["lease_token"], "X-Cut-Revision": str(j2["cut_revision"])},
        content=mp4_b,
    ).status_code == 200

    # 3. Return to trim A [10, 12], confirm publish as Alice, then deactivate Alice before cut A completes!
    admin.patch(
        f"/api/v1/clip-triage/candidates/{cand['id']}",
        headers=ORIGIN,
        json={"trimmed_start_s": 10.0, "trimmed_end_s": 12.0, "confirm_publish": True},
    )
    j3 = api_client.post("/api/v1/media/clip-cuts/lease", headers={"X-API-Key": WORKER_KEY}, json={"agent_id": "mac-media-01"}).json()["jobs"][0]
    assert j3["clip_video_uuid"] != j1["clip_video_uuid"]
    assert j3["clip_video_uuid"] != j2["clip_video_uuid"]

    # Deactivate Alice before cut completes -> deferred publication MUST refuse (stays 'ready', no Dive!)
    alice = db.get(AppUser, clip_env["admin_id"])
    alice.is_active = False
    db.commit()

    c3 = api_client.post(
        f"/api/v1/media/clip-cuts/{cand['id']}/complete",
        headers={"X-API-Key": WORKER_KEY, "X-Media-Agent-Id": "mac-media-01", "X-Lease-Token": j3["lease_token"], "X-Cut-Revision": str(j3["cut_revision"])},
        content=mp4_a,
    )
    assert c3.status_code == 200
    assert c3.json()["extraction_status"] == "ready"
    assert c3.json()["dive_id"] is None

    # Latest revision for j3's clip_video_uuid resolves strictly to byte-identical A (never B!)
    db.expire_all()
    loc = resolve_media_revision_location(db, j3["clip_video_uuid"], "dev")
    assert loc is not None
    assert loc.blob_sha256 == sha_a

    # Invalidated confirmation MUST clear publish_requested & claimed_by so clip re-enters 'incomplete'!
    refreshed = db.get(SessionClipCandidate, cand["id"])
    assert refreshed.publish_requested_at is None
    assert refreshed.publish_requested_by_user_id is None
    assert refreshed.claimed_by is None

    # Reactivate Alice -> clip is visible in To Complete with publish_requested=False and can be reconfirmed!
    alice = db.get(AppUser, clip_env["admin_id"])
    alice.is_active = True
    db.commit()
    admin = as_user("alice")
    inc_items = admin.get("/api/v1/clip-triage/candidates", params={"tab": "incomplete"}).json()["items"]
    matching = [it for it in inc_items if it["id"] == cand["id"]]
    assert len(matching) == 1
    assert matching[0]["publish_requested"] is False
    assert matching[0]["extraction_status"] == "ready"
    repub = admin.patch(
        f"/api/v1/clip-triage/candidates/{cand['id']}",
        headers=ORIGIN,
        json={"confirm_publish": True},
    )
    assert repub.status_code == 200
    assert repub.json()["extraction_status"] == "published"
    assert repub.json()["dive_id"] is not None


def test_short_lease_rejects_4s_upload_with_422(clip_env):
    video_id = clip_env["video_id"]
    api_client = TestClient(app)
    as_user = clip_env["as_user"]
    mp4_4s = _make_real_mp4_bytes(clip_env["tmp_path"], duration_s=4.0, name="too_long_4s.mp4")

    api_client.post(
        f"/api/v1/session-videos/{video_id}/clip-runs",
        headers={"X-API-Key": API_KEY},
        json={"detector_name": "core", "detector_version": "v1", "candidates": [{"start_s": 40.0, "end_s": 41.0}]},
    )
    admin = as_user("alice")
    cand = admin.get("/api/v1/clip-triage/candidates").json()["items"][0]
    admin.patch(
        f"/api/v1/clip-triage/candidates/{cand['id']}",
        headers=ORIGIN,
        json={"diver_id": clip_env["alice_diver_id"], "triage_status": "kept"},
    )
    job = api_client.post("/api/v1/media/clip-cuts/lease", headers={"X-API-Key": WORKER_KEY}, json={"agent_id": "mac-media-01"}).json()["jobs"][0]
    res = api_client.post(
        f"/api/v1/media/clip-cuts/{cand['id']}/complete",
        headers={"X-API-Key": WORKER_KEY, "X-Media-Agent-Id": "mac-media-01", "X-Lease-Token": job["lease_token"], "X-Cut-Revision": str(job["cut_revision"])},
        content=mp4_4s,
    )
    assert res.status_code == 422


def test_dedup_beyond_2000_historical_rows_preserves_rejected_clip(clip_env):
    """Detector reruns on a video with >2,000 historical candidates never recreate rejected clips."""
    db = clip_env["db"]
    video_id = clip_env["video_id"]
    video = db.get(SessionVideo, video_id)
    video.duration_seconds = 100_000.0
    db.flush()

    now = datetime.utcnow()
    # Seed 2,001 non-overlapping historical candidates spanning [0, 80040s], with #2001 rejected!
    rows = [
        SessionClipCandidate(
            session_video_id=video_id,
            start_s=float(i * 40),
            end_s=float(i * 40 + 10),
            triage_status="rejected" if i == 2000 else "pending",
            reject_reason="false_positive" if i == 2000 else None,
            extraction_status="none",
            visibility="private",
            created_at=now,
            updated_at=now,
        )
        for i in range(2001)
    ]
    db.bulk_save_objects(rows)
    db.commit()

    api_client = TestClient(app)
    rerun = api_client.post(
        f"/api/v1/session-videos/{video_id}/clip-runs",
        headers={"X-API-Key": API_KEY},
        json={
            "detector_name": "core_detection",
            "detector_version": "v2",
            "candidates": [
                {"start_s": 0.0, "end_s": 10.0},
                {"start_s": 80000.0, "end_s": 80010.0},
            ],
        },
    )
    assert rerun.status_code == 201
    body = rerun.json()
    assert body["created_count"] == 0
    assert body["deduped_count"] == 2
    assert body["preserved_triaged_count"] == 1
    assert db.query(SessionClipCandidate).filter_by(session_video_id=video_id).count() == 2001


def test_keyset_cursor_pagination_reaches_all_151_incomplete_and_shrinking_pending(clip_env):
    """Keyset cursor pagination traverses >150 incomplete clips and shrinking pending queues with zero skips."""
    db = clip_env["db"]
    video_id = clip_env["video_id"]
    video = db.get(SessionVideo, video_id)
    video.duration_seconds = 20_000.0
    db.flush()

    base = datetime(2026, 11, 25, 12, 0, 0)
    # 151 kept incomplete clips (same & distinct timestamps)
    inc_rows = [
        SessionClipCandidate(
            session_video_id=video_id,
            start_s=float(i * 20),
            end_s=float(i * 20 + 8),
            diver_id=clip_env["alice_diver_id"],
            triage_status="kept",
            extraction_status="queued",
            visibility="private",
            created_at=base,
            updated_at=base + timedelta(seconds=i // 3),
        )
        for i in range(151)
    ]
    db.bulk_save_objects(inc_rows)
    db.commit()

    admin = clip_env["as_user"]("alice")
    seen_ids: list[int] = []
    cursor = None
    pages = 0
    while True:
        params = {"tab": "incomplete", "limit": 50}
        if cursor:
            params["cursor"] = cursor
        resp = admin.get("/api/v1/clip-triage/candidates", params=params)
        assert resp.status_code == 200
        data = resp.json()
        pages += 1
        seen_ids.extend(it["id"] for it in data["items"])
        if not data["has_more"]:
            assert data["next_cursor"] is None
            break
        assert data["next_cursor"]
        cursor = data["next_cursor"]
        assert pages <= 5

    assert pages == 4
    assert len(seen_ids) == 151
    assert len(set(seen_ids)) == 151

    # Shrinking pending queue: 65 pending clips -> reject first 45 -> cursor from page 1 yields remaining 15!
    pend_rows = [
        SessionClipCandidate(
            session_video_id=video_id,
            start_s=float(5000 + i * 20),
            end_s=float(5000 + i * 20 + 8),
            triage_status="pending",
            extraction_status="none",
            visibility="private",
            created_at=base,
            updated_at=base,
        )
        for i in range(65)
    ]
    db.bulk_save_objects(pend_rows)
    db.commit()

    p1 = admin.get("/api/v1/clip-triage/candidates", params={"tab": "pending", "limit": 50}).json()
    assert len(p1["items"]) == 50
    assert p1["has_more"] is True
    cur1 = p1["next_cursor"]
    assert cur1

    # Reject 45 of the first 50 clips while holding cur1
    for it in p1["items"][:45]:
        r = admin.patch(
            f"/api/v1/clip-triage/candidates/{it['id']}",
            headers=ORIGIN,
            json={"triage_status": "rejected", "reject_reason": "false_positive"},
        )
        assert r.status_code == 200

    p2 = admin.get("/api/v1/clip-triage/candidates", params={"tab": "pending", "limit": 50, "cursor": cur1}).json()
    assert len(p2["items"]) == 15
    assert p2["has_more"] is False
    p1_ids = {it["id"] for it in p1["items"]}
    assert all(it["id"] not in p1_ids for it in p2["items"])


def test_non_finite_json_run_params_return_422_never_500(clip_env):
    """Raw JSON overflow literals like 1e400 return clean HTTP 422 instead of 500."""
    video_id = clip_env["video_id"]
    api_client = TestClient(app)
    headers = {"X-API-Key": API_KEY, "Content-Type": "application/json"}

    r1 = api_client.post(
        f"/api/v1/session-videos/{video_id}/clip-runs",
        headers=headers,
        content='{"detector_name":"core","detector_version":"v1","params_json":{"x":1e400},"candidates":[]}',
    )
    assert r1.status_code == 422

    r2 = api_client.post(
        f"/api/v1/session-videos/{video_id}/clip-runs",
        headers=headers,
        content='{"detector_name":"core","detector_version":"v1","candidates":[{"start_s":1e400,"end_s":12.0}]}',
    )
    assert r2.status_code == 422

    r3 = api_client.post(
        f"/api/v1/session-videos/{video_id}/clip-runs",
        headers=headers,
        content='{"detector_name":"core","detector_version":"v1","candidates":[{"start_s":1.0,"end_s":12.0,"meta":{"bad":1e400}}]}',
    )
    assert r3.status_code == 422

    # Malformed cursors with non-finite integers/floats or booleans MUST return 422, never 500!
    import base64

    admin = clip_env["as_user"]("alice")
    for raw_cursor_json in (
        '{"t":"incomplete","u":"2026-11-25T12:00:00","id":1e400}',
        '{"t":"incomplete","u":"2026-11-25T12:00:00","id":true}',
        '{"t":"pending","sk":0,"rn":0,"ra":"2026-11-25T12:00:00","vid":1,"s":1e400,"id":1}',
    ):
        tok = base64.urlsafe_b64encode(raw_cursor_json.encode()).decode().rstrip("=")
        tab = "pending" if '"pending"' in raw_cursor_json else "incomplete"
        resp = admin.get("/api/v1/clip-triage/candidates", params={"tab": tab, "cursor": tok})
        assert resp.status_code == 422


def test_revoked_source_access_and_deleted_confirmer_block_publish_and_clear_confirmation(clip_env):
    """Deferred publish revalidates BOTH source-video permission and confirmer existence, clearing stale confirmation."""
    db = clip_env["db"]
    api_client = TestClient(app)
    as_user = clip_env["as_user"]
    mp4_2s = _make_real_mp4_bytes(clip_env["tmp_path"], duration_s=2.0, name="revoked_2s.mp4")

    # Bob owns this recording; admin Alice confirms a clip for Alice's OWN diver, then loses admin role!
    bob_video = SessionVideo(
        session_id=clip_env["session_id"],
        owner_user_id=clip_env["bob_user_id"],
        bucket="diveanalyzer-sessions",
        object_key="inbox/BOB_ONLY.MOV",
        etag="etag-bob-v1",
        status="ready",
        recorded_at=datetime(2026, 11, 25, 18, 0, 0),
        recorded_date=datetime(2026, 11, 25).date(),
        duration_seconds=300.0,
    )
    db.add(bob_video)
    db.commit()
    bob_video_id = bob_video.id

    api_client.post(
        f"/api/v1/session-videos/{bob_video_id}/clip-runs",
        headers={"X-API-Key": API_KEY},
        json={
            "detector_name": "core",
            "detector_version": "v1",
            "candidates": [
                {"start_s": 10.0, "end_s": 12.0},
                {"start_s": 30.0, "end_s": 32.0},
            ],
        },
    )
    admin = as_user("alice")
    items = admin.get(
        "/api/v1/clip-triage/candidates", params={"session_video_id": bob_video_id}
    ).json()["items"]
    cand1_id, cand2_id = items[0]["id"], items[1]["id"]

    # Case 1: Admin Alice confirms publish for her OWN diver on Bob's video, then loses admin rights!
    r_confirm = admin.patch(
        f"/api/v1/clip-triage/candidates/{cand1_id}",
        headers=ORIGIN,
        json={
            "diver_id": clip_env["alice_diver_id"],
            "dive_code": "103B",
            "height": "3m",
            "performance": "G",
            "triage_status": "kept",
            "confirm_publish": True,
        },
    )
    assert r_confirm.status_code == 200

    # Case 2: Confirm cand2, then simulate confirmer deleted (ON DELETE SET NULL -> user_id=None, at!=None)
    assert admin.patch(
        f"/api/v1/clip-triage/candidates/{cand2_id}",
        headers=ORIGIN,
        json={
            "diver_id": clip_env["bob_diver_id"],
            "dive_code": "105B",
            "height": "3m",
            "performance": "G",
            "triage_status": "kept",
            "confirm_publish": True,
        },
    ).status_code == 200

    jobs = api_client.post(
        "/api/v1/media/clip-cuts/lease",
        headers={"X-API-Key": WORKER_KEY},
        json={"agent_id": "mac-media-01", "limit": 2},
    ).json()["jobs"]
    jobs_by_id = {j["candidate_id"]: j for j in jobs}

    # Demote Alice (loses access to Bob's recording even though she still owns alice_diver_id!)
    alice = db.get(AppUser, clip_env["admin_id"])
    alice.is_admin = False
    # Simulate deleted confirmer on cand2 (ON DELETE SET NULL)
    c2_row = db.get(SessionClipCandidate, cand2_id)
    c2_row.publish_requested_by_user_id = None
    db.commit()

    # Before complete, API already reports cand2 as publish_requested=False (not falsely confirmed!)
    bob_client = as_user("bob")
    c2_before = bob_client.get(f"/api/v1/clip-triage/candidates/{cand2_id}").json()
    assert c2_before["publish_requested"] is False

    # Complete both cuts: NEITHER may publish, and BOTH must clear publish_requested_at & claimed_at!
    for cid in (cand1_id, cand2_id):
        job = jobs_by_id[cid]
        res = api_client.post(
            f"/api/v1/media/clip-cuts/{cid}/complete",
            headers={
                "X-API-Key": WORKER_KEY,
                "X-Media-Agent-Id": "mac-media-01",
                "X-Lease-Token": job["lease_token"],
                "X-Cut-Revision": str(job["cut_revision"]),
            },
            content=mp4_2s,
        )
        assert res.status_code == 200
        assert res.json()["extraction_status"] == "ready"
        assert res.json()["dive_id"] is None

    db.expire_all()
    for cid in (cand1_id, cand2_id):
        row = db.get(SessionClipCandidate, cid)
        assert row.dive_id is None
        assert row.publish_requested_at is None
        assert row.publish_requested_by_user_id is None
        assert row.claimed_at is None
        assert row.claimed_by is None

    # Restore Alice admin status for fixture hygiene
    alice = db.get(AppUser, clip_env["admin_id"])
    alice.is_admin = True
    db.commit()


def test_dedup_keyset_pagination_loops_past_500_overlapping_rows_in_one_window(clip_env):
    """More than 500 historical rows inside a single merged time window still deduplicate cleanly."""
    db = clip_env["db"]
    video_id = clip_env["video_id"]
    now = datetime.utcnow()
    # Seed 520 rows inside [10.0, 22.0] with the 520th row rejected at exact [15.0, 20.0]
    rows = [
        SessionClipCandidate(
            session_video_id=video_id,
            start_s=10.0 if i < 519 else 15.0,
            end_s=11.0 if i < 519 else 20.0,
            triage_status="rejected" if i == 519 else "pending",
            reject_reason="false_positive" if i == 519 else None,
            extraction_status="none",
            visibility="private",
            created_at=now,
            updated_at=now,
        )
        for i in range(520)
    ]
    db.bulk_save_objects(rows)
    db.commit()

    api_client = TestClient(app)
    rerun = api_client.post(
        f"/api/v1/session-videos/{video_id}/clip-runs",
        headers={"X-API-Key": API_KEY},
        json={
            "detector_name": "core",
            "detector_version": "v2",
            "candidates": [{"start_s": 15.0, "end_s": 20.0}],
        },
    )
    assert rerun.status_code == 201
    assert rerun.json()["created_count"] == 0
    assert rerun.json()["deduped_count"] == 1
    assert rerun.json()["preserved_triaged_count"] == 1
