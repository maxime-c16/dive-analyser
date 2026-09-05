"""
Test fixtures and utilities for seeding test databases with sample data.

Provides functions to populate test databases with realistic test data
for integration and E2E testing.
"""

from datetime import datetime, timedelta
from typing import List
from sqlalchemy.orm import Session

from app.models.session import Session as SessionModel
from app.models.dive import Dive
from app.models.fina_dive_code import FINADiveCode
import json
import os


def seed_test_database(db: Session, num_sessions: int = 5, dives_per_session: int = 10) -> dict:
    """
    Populate test database with sample data.

    Args:
        db: SQLAlchemy session
        num_sessions: Number of training sessions to create
        dives_per_session: Average dives per session

    Returns:
        Dictionary with counts: {sessions: 5, dives: 50, legacy_dives: 25, two_phase_dives: 25}

    Performance: Should complete in <500ms for standard test size
    """
    sessions = []
    dives = []
    legacy_count = 0
    two_phase_count = 0

    # Dive codes for variety
    dive_codes = [
        "101B", "101C", "201B", "201C",
        "301B", "301C", "401B", "401C",
        "5231D", "5233D"
    ]

    # Heights for variety
    heights = ["1m", "3m", "5m", "7m", "10m"]

    # Create sessions
    for session_idx in range(num_sessions):
        session_date = datetime.now().date() - timedelta(days=num_sessions - session_idx - 1)

        session = SessionModel(
            date=session_date,
            location="Pool" if session_idx % 2 == 0 else "Springboard",
            notes=f"Test session {session_idx + 1}",
            total_dives=dives_per_session,
            total_personal_dives=int(dives_per_session * 0.75),
            avg_performance=3.0,
            success_rate=0.75,
        )
        sessions.append(session)
        db.add(session)

    db.commit()

    # Refresh to get IDs
    for session in sessions:
        db.refresh(session)

    # Create dives (mix of legacy and two-phase)
    for session_idx, session in enumerate(sessions):
        for dive_idx in range(dives_per_session):
            dive_time = datetime.now() - timedelta(days=num_sessions - session_idx - 1,
                                                   hours=dives_per_session - dive_idx)

            # Alternate between legacy and two-phase format
            is_two_phase = (session_idx + dive_idx) % 2 == 0

            if is_two_phase:
                # Two-phase dive
                dive = Dive(
                    session_id=session.id,
                    dive_code=dive_codes[(session_idx + dive_idx) % len(dive_codes)],
                    performance="G",
                    performance_numeric=3,
                    height=heights[dive_idx % len(heights)],
                    is_sync=False,
                    is_smack=False,
                    person_name=None,
                    dive_datetime=dive_time,
                    is_lineup=False,
                    phase1_performance="G",
                    phase1_numeric=3,
                    phase2_performance="P" if dive_idx % 3 == 0 else "M",
                    phase2_numeric=4 if dive_idx % 3 == 0 else 2,
                )
                two_phase_count += 1
            else:
                # Legacy dive (no phase data)
                dive = Dive(
                    session_id=session.id,
                    dive_code=dive_codes[(session_idx + dive_idx) % len(dive_codes)],
                    performance="M" if dive_idx % 2 == 0 else "G",
                    performance_numeric=2 if dive_idx % 2 == 0 else 3,
                    height=heights[dive_idx % len(heights)],
                    is_sync=False,
                    is_smack=dive_idx % 5 == 0,
                    person_name=None,
                    dive_datetime=dive_time,
                    is_lineup=False,
                    phase1_performance=None,
                    phase1_numeric=None,
                    phase2_performance=None,
                    phase2_numeric=None,
                )
                legacy_count += 1

            dives.append(dive)
            db.add(dive)

    db.commit()

    # Verify all committed
    for dive in dives:
        db.refresh(dive)

    return {
        "sessions": len(sessions),
        "dives": len(dives),
        "legacy_dives": legacy_count,
        "two_phase_dives": two_phase_count,
    }


def clear_test_database(db: Session) -> None:
    """
    Wipe all data from test database while keeping schema intact.

    Args:
        db: SQLAlchemy session
    """
    # Delete in correct order to respect foreign keys
    db.query(Dive).delete()
    db.query(SessionModel).delete()
    db.commit()


def get_test_dive_metadata(
    dive_code: str = "101B",
    performance: str = "G",
    phase1: str = None,
    phase2: str = None,
    height: str = "5m",
) -> dict:
    """
    Generate test dive metadata for API testing.

    Args:
        dive_code: FINA dive code (e.g., "101B")
        performance: Single performance score (F/B/M/G/P)
        phase1: Phase 1 performance (optional, for two-phase format)
        phase2: Phase 2 performance (optional, for two-phase format)
        height: Height (e.g., "5m", "10m")

    Returns:
        Dictionary with dive metadata ready for API POST
    """
    data = {
        "dive_code": dive_code,
        "height": height,
        "performance": performance if not phase1 else None,
        "date": datetime.now().isoformat(),
        "is_sync": False,
        "is_smack": False,
        "person_name": None,
    }

    # Add two-phase if provided
    if phase1:
        data["phase1_performance"] = phase1
    if phase2:
        data["phase2_performance"] = phase2

    return data


def seed_fina_dive_codes(db: Session) -> int:
    """
    Load official FINA dive codes from JSON and seed the database.

    Args:
        db: SQLAlchemy session

    Returns:
        Number of dive codes loaded
    """
    # Find the JSON file
    current_dir = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(current_dir, "..", "app", "data", "fina_official_dive_codes.json")

    if not os.path.exists(json_path):
        # Fallback to alternative path
        json_path = os.path.join(current_dir, "..", "app", "data", "fina_official_dive_codes.json")

    if not os.path.exists(json_path):
        raise FileNotFoundError(f"FINA dive codes JSON not found at {json_path}")

    with open(json_path, "r") as f:
        dives_data = json.load(f)

    count = 0
    for dive_data in dives_data:
        # Check if dive already exists
        existing = db.query(FINADiveCode).filter_by(dive_code=dive_data["dive_code"]).first()
        if existing:
            continue

        # Create new FINADiveCode record
        fina_dive = FINADiveCode(
            dive_code=dive_data["dive_code"],
            group=dive_data["group"],
            direction=dive_data["direction"],
            position=dive_data["position"],
            rotations=dive_data["rotations"],
            twists=dive_data["twists"],
            group_name=dive_data.get("group_name"),
            position_name=dive_data.get("position_name"),
            official_name=dive_data.get("official_name"),
            is_twisting=dive_data.get("is_twisting", False),
            is_flying=dive_data.get("is_flying", False),
            is_armstand=dive_data.get("is_armstand", False),
        )
        db.add(fina_dive)
        count += 1

    db.commit()
    return count
