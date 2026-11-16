"""JSON import (`POST /api/v1/import/sync`) derives the stored letter of a
two-phase dive from its phases, exactly like the Photos sync and the clip
editor do (docs/SCORING.md §1). A payload written under the old
min(phase1, phase2) rule must not survive the import.
"""
import json

import pytest
from sqlalchemy.orm import Session

from app.models.dive import Dive
from app.services.import_service import ImportService


def _import(test_db: Session, tmp_path, dives: list[dict]) -> dict:
    payload = {"valid_dive_videos": dives}
    json_path = tmp_path / "dives.json"
    json_path.write_text(json.dumps(payload))
    return ImportService(test_db).import_from_json(str(json_path))


@pytest.mark.unit
def test_import_derives_two_phase_letter_from_phases(test_db: Session, tmp_path):
    """A stale payload letter (G, the old min rule) is replaced by the band (P)."""
    stats = _import(test_db, tmp_path, [
        {
            "uuid": "import-two-phase-stale-letter",
            "date": "2026-02-01T12:00:00",
            "dive_code": "101B",
            "performance": "G",
            "phase1_performance": "G",
            "phase2_performance": "P",
        }
    ])
    assert stats["dives_created"] == 1

    dive = test_db.query(Dive).filter(
        Dive.video_uuid == "import-two-phase-stale-letter"
    ).first()
    assert dive is not None
    # 0.45*7 + 0.55*10 = 8.65 -> P, ordinal 4 (docs/SCORING.md).
    assert dive.performance == "P"
    assert dive.performance_numeric == 4


@pytest.mark.unit
def test_import_keeps_single_rating_letter(test_db: Session, tmp_path):
    """A legacy dive without phases keeps its payload letter."""
    stats = _import(test_db, tmp_path, [
        {
            "uuid": "import-single-rating",
            "date": "2026-02-01T12:00:00",
            "dive_code": "101B",
            "performance": "M",
        }
    ])
    assert stats["dives_created"] == 1

    dive = test_db.query(Dive).filter(
        Dive.video_uuid == "import-single-rating"
    ).first()
    assert dive is not None
    assert dive.performance == "M"
    assert dive.performance_numeric == 2
