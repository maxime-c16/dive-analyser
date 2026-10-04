"""Competition results, ranking and exports through the current DB service."""
import csv
import io
import json
from decimal import Decimal

import pytest

from app.models.competition_event import CompetitionDiveEntry
from app.models.judge_score import JudgePanel
from app.services.results_aggregator import ResultsAggregator
from tests.competition_fixtures import competition, event_mgr


@pytest.fixture
def standings(test_db, competition, event_mgr):
    round_obj = event_mgr.create_round(competition.id, 1, "FINAL")
    alice = event_mgr.register_competitor(competition.id, "Alice", "FRA")
    bob = event_mgr.register_competitor(competition.id, "Bob", "GBR")
    # The current service estimates execution at 8/10, using formula DD.
    for competitor, code in [(alice, "101B"), (bob, "103B")]:
        test_db.add(CompetitionDiveEntry(round_id=round_obj.id, competitor_id=competitor.id,
                                       dive_order=1, dive_code=code, planned_dd=130, status="PENDING"))
    test_db.commit()
    return ResultsAggregator(test_db), competition, round_obj, alice, bob


def test_calculate_dive_score(test_db, sample_dive):
    panel = JudgePanel(dive_id=sample_dive.id, judge_count=7, panel_average=Decimal("8.5"))
    test_db.add(panel)
    test_db.commit()
    aggregator = ResultsAggregator(test_db)
    assert aggregator.calculate_dive_score(panel.id, sample_dive.id) == pytest.approx(1.105)
    assert aggregator.calculate_dive_score(panel.id + 100, sample_dive.id) is None


def test_round_standings_rank_formula_scores(standings):
    aggregator, _, round_obj, alice, bob = standings
    result = aggregator.calculate_round_standings(round_obj.id)
    assert [row["competitor_id"] for row in result] == [bob.id, alice.id]
    assert [row["rank"] for row in result] == [1, 2]
    assert result[0]["total_score"] == pytest.approx(1.36)
    assert result[1]["total_score"] == pytest.approx(1.04)
    assert result[0]["dives_completed"] == 1


def test_event_standings_accumulate_rounds(standings, event_mgr, test_db):
    aggregator, event, _, alice, bob = standings
    second = event_mgr.create_round(event.id, 2, "FINAL")
    test_db.add(CompetitionDiveEntry(round_id=second.id, competitor_id=alice.id,
                                   dive_order=1, dive_code="103B", planned_dd=170, status="PENDING"))
    test_db.commit()
    result = aggregator.calculate_event_standings(event.id)
    assert [row["competitor_id"] for row in result] == [alice.id, bob.id]
    assert result[0]["total_score"] == pytest.approx(2.4)
    assert len(result[0]["round_breakdown"]) == 2


def test_missing_event_and_round_return_empty(test_db):
    aggregator = ResultsAggregator(test_db)
    assert aggregator.calculate_event_standings(999) == []
    assert aggregator.calculate_round_standings(999) == []


def test_export_json(standings):
    aggregator, event, *_ = standings
    exported = json.loads(aggregator.export_results(event.id, "json"))
    assert [row["competitor_name"] for row in exported] == ["Bob", "Alice"]
    assert exported[0]["rank"] == 1


def test_export_csv(standings):
    aggregator, event, *_ = standings
    rows = list(csv.DictReader(io.StringIO(aggregator.export_results(event.id, "csv"))))
    assert rows[0] == {"rank": "1", "competitor_name": "Bob", "country": "GBR", "total_score": "1.36"}
    assert rows[1]["competitor_name"] == "Alice"
