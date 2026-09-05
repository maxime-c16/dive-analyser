from datetime import datetime

from app.models.dive import Dive
from app.models.session import Session as SessionModel
from app.services.diver_identity import resolve_diver


def _dive(session_id: int, diver_id: int, person_name: str | None, code: str, stamp: datetime) -> Dive:
    return Dive(
        session_id=session_id,
        dive_code=code,
        performance="G",
        performance_numeric=3,
        height="1m",
        platform_type="springboard",
        is_lineup=False,
        is_sync=False,
        diver_id=diver_id,
        person_name=person_name,
        dive_datetime=stamp,
    )


def test_sessions_and_session_dives_default_to_primary_diver(api_client, test_db):
    primary = resolve_diver(test_db, None)
    teammate = resolve_diver(test_db, "Teammate")
    shared = SessionModel(date=datetime(2026, 7, 1).date())
    teammate_only = SessionModel(date=datetime(2026, 7, 2).date())
    test_db.add_all([shared, teammate_only])
    test_db.flush()
    test_db.add_all([
        _dive(shared.id, primary.id, None, "103B", datetime(2026, 7, 1, 10)),
        _dive(shared.id, teammate.id, teammate.display_name, "103C", datetime(2026, 7, 1, 11)),
        _dive(teammate_only.id, teammate.id, teammate.display_name, "105C", datetime(2026, 7, 2, 10)),
    ])
    test_db.commit()

    mine = api_client.get("/api/v1/sessions").json()
    assert [item["id"] for item in mine] == [shared.id]
    assert mine[0]["total_dives"] == 1
    assert mine[0]["total_personal_dives"] == 1

    everyone = api_client.get("/api/v1/sessions?diver_scope=all").json()
    assert {item["id"] for item in everyone} == {shared.id, teammate_only.id}
    assert next(item for item in everyone if item["id"] == shared.id)["total_dives"] == 2

    session_dives = api_client.get(f"/api/v1/dives?session_id={shared.id}").json()
    assert [item["diver_id"] for item in session_dives] == [primary.id]
    all_session_dives = api_client.get(f"/api/v1/dives?session_id={shared.id}&diver_scope=all").json()
    assert {item["diver_id"] for item in all_session_dives} == {primary.id, teammate.id}
