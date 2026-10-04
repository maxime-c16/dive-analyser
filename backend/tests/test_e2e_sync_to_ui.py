"""Metadata sync through the real API to the analytics consumed by the UI.

Native Photos extraction and browser rendering are covered separately. This
flow uses the actual sync, persistence and analytics services with SQLite.
"""
from app.models.dive import Dive


def test_synced_attempt_is_visible_to_ui_analytics_and_retry_is_idempotent(api_client, test_db, auth_headers):
    payload = {
        "video_uuid": "C1000000-0000-4000-8000-000000000001",
        "dive_code": "103B", "height": "1m", "performance": "G",
        "date": "2026-01-15T12:00:00", "is_sync": False, "is_smack": False,
    }
    created = api_client.post("/api/v1/videos/sync", json=payload, headers=auth_headers)
    assert created.status_code == 201, created.json()
    dive_id = created.json()["dive_id"]
    retry = api_client.post("/api/v1/videos/sync", json=payload, headers=auth_headers)
    assert retry.status_code in (200, 201)
    assert retry.json()["created"] is False
    assert retry.json()["dive_id"] == dive_id
    assert test_db.query(Dive).filter_by(video_uuid=payload["video_uuid"]).count() == 1

    response = api_client.get("/api/v1/dive-analysis/103B?diver_scope=all")
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["attempt_count"] == 1
    assert body["summary"]["average"] == 7.0
    assert body["summary"]["average_dd"] == 1.7
    assert body["attempts"][0]["id"] == dive_id
