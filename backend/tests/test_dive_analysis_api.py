from datetime import datetime, timedelta

from app.models.dive import Dive
from app.models.dive_modifier import DiveModifier
from app.models.session import Session as SessionModel
from app.models.training_period import TrainingPeriod
from app.services.diver_identity import resolve_diver


def seed_attempts(test_db):
    start = datetime(2026, 1, 1)
    primary = resolve_diver(test_db, None)
    paul = resolve_diver(test_db, "Paul")
    sessions = []
    for offset in (0, 30, 60):
        session = SessionModel(date=(start + timedelta(days=offset)).date())
        test_db.add(session)
        sessions.append(session)
    test_db.flush()
    attempts = []
    specs = [
        (sessions[0], "B", "1m", False, primary, ["DB", "HU"]),
        (sessions[0], "P", "1m", False, primary, []),
        (sessions[0], "P", "1m", False, primary, []),
        (sessions[1], "M", "3m", True, paul, ["DB"]),
        (sessions[2], "G", "3m", False, primary, ["SD"]),
    ]
    for index, (session, rating, height, sync, diver, modifiers) in enumerate(specs, 1):
        dive = Dive(session_id=session.id, dive_code="103B", performance=rating, performance_numeric={"B": 1, "M": 2, "G": 3, "P": 4}[rating], phase1_performance="G" if index != 2 else None, phase2_performance="M", height=height, position="B", platform_type="springboard", is_sync=sync, is_lineup=False, diver_id=diver.id, person_name=None if diver.is_primary_user else diver.display_name, dive_datetime=start + timedelta(days=(index - 1) * 15), video_uuid=f"test-analysis-{index:032d}")
        test_db.add(dive)
        test_db.flush()
        for modifier in modifiers:
            test_db.add(DiveModifier(dive_id=dive.id, modifier_code=modifier, modifier_type="drill"))
        attempts.append(dive)
    test_db.add(TrainingPeriod(name="Winter", period_type="season", start_date=datetime(2026, 1, 1).date(), end_date=datetime(2026, 2, 15).date()))
    test_db.commit()
    return primary, paul, attempts


def test_canonical_filters_modifier_modes_sync_and_traceability(api_client, test_db):
    primary, paul, attempts = seed_attempts(test_db)
    base = api_client.get("/api/v1/dive-analysis/103b").json()
    assert {item["diver"]["id"] for item in base["attempts"]} == {primary.id}
    all_scope = api_client.get("/api/v1/dive-analysis/103b?diver_scope=all").json()
    assert {item["diver"]["id"] for item in all_scope["attempts"]} == {primary.id, paul.id}
    any_db = api_client.get("/api/v1/dive-analysis/103B?modifiers=DB&modifier_mode=any").json()
    assert len(any_db["attempts"]) == 1
    all_db_hu = api_client.get("/api/v1/dive-analysis/103B?modifiers=DB&modifiers=HU&modifier_mode=all").json()
    assert [item["id"] for item in all_db_hu["attempts"]] == [attempts[0].id]
    none = api_client.get("/api/v1/dive-analysis/103B?modifier_mode=none").json()
    assert len(none["attempts"]) == 2
    sync = api_client.get("/api/v1/dive-analysis/103B?is_sync=true&diver_scope=all").json()
    assert len(sync["attempts"]) == 1 and sync["attempts"][0]["is_sync"] is True
    primary_only = api_client.get(f"/api/v1/dive-analysis/103B?diver_ids={primary.id}").json()
    assert all(item["diver"]["id"] == primary.id for item in primary_only["attempts"])
    assert all(item["video_uuid"] for item in primary_only["attempts"])


def test_weighting_period_phase_endpoints_and_cache(api_client, test_db):
    seed_attempts(test_db)
    attempt_response = api_client.get("/api/v1/dive-analysis/103B?weighting=attempts&date_from=2026-01-01&date_to=2026-03-31&diver_scope=all").json()
    session_response = api_client.get("/api/v1/dive-analysis/103B?weighting=sessions&date_from=2026-01-01&date_to=2026-03-31&diver_scope=all").json()
    assert attempt_response["summary"]["average"] != session_response["summary"]["average"]
    assert session_response["weighting_mode"] == "session_weighted"
    cached = api_client.get("/api/v1/dive-analysis/103B?weighting=sessions&date_from=2026-01-01&date_to=2026-03-31&diver_scope=all").json()
    assert cached["observability"]["cache"] == "hit"
    phases = api_client.get("/api/v1/dive-analysis/103B/phases?diver_scope=all").json()["phases"]
    assert phases["total_attempts"] == 5
    assert phases["phases"]["phase1"]["missing_count"] == 1
    periods = api_client.get("/api/v1/dive-analysis/103B/breakdown?dimension=training_period&diver_scope=all").json()["groups"]
    assert any(group["context"] == "Winter" for group in periods)


def test_attempt_and_summary_expose_formula_dd_adjusted_execution(api_client, test_db):
    seed_attempts(test_db)
    response = api_client.get("/api/v1/dive-analysis/103B?diver_scope=all").json()
    assert response["summary"]["dd_coverage_rate"] == 100.0
    first = response["attempts"][0]
    assert first["official_dd"] == 1.7
    assert first["dd_adjusted_execution"] == round(first["performance_numeric"] * first["official_dd"], 2)
    assert first["dd_reference"] == "ffn_world_aquatics_diving_2022_2025_appendix_1_3"


def test_structured_straight_jump_error_and_date_boundaries(api_client, test_db):
    seed_attempts(test_db)
    error = api_client.get("/api/v1/dive-analysis/100B")
    assert error.status_code == 422
    assert error.json()["detail"]["code"] == "straight_jump_not_supported"
    family = api_client.get("/api/v1/dive-analysis/103")
    assert family.status_code == 422
    assert family.json()["detail"]["code"] == "invalid_dive_code"
    one_day = api_client.get("/api/v1/dive-analysis/103B?date_from=2026-01-01&date_to=2026-01-01").json()
    assert one_day["sample"]["attempt_count"] == 1


def test_exact_dive_code_does_not_mix_pike_and_tuck(api_client, test_db):
    _, _, attempts = seed_attempts(test_db)
    session = attempts[0].session
    tuck = Dive(
        session_id=session.id,
        dive_code="103C",
        position="C",
        performance="B",
        performance_numeric=1,
        height="1m",
        platform_type="springboard",
        is_sync=False,
        is_lineup=False,
        dive_datetime=datetime(2026, 1, 8),
        video_uuid="test-analysis-103c-b-performance",
    )
    test_db.add(tuck)
    test_db.commit()

    pike = api_client.get("/api/v1/dive-analysis/103B?diver_scope=all").json()
    tuck_response = api_client.get("/api/v1/dive-analysis/103C").json()

    assert {attempt["dive_code"] for attempt in pike["attempts"]} == {"103B"}
    assert {attempt["position"] for attempt in pike["attempts"]} == {"B"}
    assert tuck_response["sample"]["attempt_count"] == 1
    assert tuck_response["attempts"][0]["dive_code"] == "103C"
    assert tuck_response["attempts"][0]["position"] == "C"
    assert tuck_response["attempts"][0]["performance"] == "B"


def test_comparison_returns_exact_sample_labels_and_constraints(api_client, test_db):
    seed_attempts(test_db)
    comparison = api_client.get("/api/v1/dive-analysis/103B/compare?dimension=modifier&e q uivalent_only=true".replace(" ", "")).json()
    db = next(group for group in comparison["groups"] if group["context"] == "DB")
    assert db["sample_label"] == "insufficient"
