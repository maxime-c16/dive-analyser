from datetime import date


API_KEY = {"X-API-Key": "test-api-key-long-enough"}


def test_training_period_crud_requires_key_and_preserves_overlap(api_client):
    payload = {"name": "Summer block", "period_type": "training_block", "start_date": "2026-06-01", "end_date": "2026-08-31", "description": "Summer", "active": True}
    assert api_client.post("/api/v1/training-periods", json=payload).status_code == 401
    first = api_client.post("/api/v1/training-periods", json=payload, headers=API_KEY)
    assert first.status_code == 201
    second = api_client.post("/api/v1/training-periods", json={**payload, "name": "Competition prep", "period_type": "competition_preparation", "start_date": "2026-07-01"}, headers=API_KEY)
    assert second.status_code == 201
    periods = api_client.get("/api/v1/training-periods").json()
    assert {period["name"] for period in periods} == {"Summer block", "Competition prep"}
    updated = api_client.put(f"/api/v1/training-periods/{first.json()['id']}", json={**payload, "name": "Summer training"}, headers=API_KEY)
    assert updated.json()["name"] == "Summer training"


def test_training_period_rejects_inverted_dates(api_client):
    response = api_client.post("/api/v1/training-periods", json={"name": "Invalid", "period_type": "custom", "start_date": "2026-08-01", "end_date": "2026-07-01"}, headers=API_KEY)
    assert response.status_code == 422
