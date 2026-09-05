"""
Pytest configuration and fixtures for backend tests.

Provides:
- db_session: Clean test database per test
- api_client: FastAPI test client
- sample_dive: Test dive record
- sample_session: Test session record
"""

import pytest
import os
from datetime import datetime, timedelta
from typing import Generator
from sqlalchemy import create_engine, event, Engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

# Override environment to use test database
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["AUTO_IMPORT"] = "false"

from app.main import app
from app.database import Base, get_db
from app.models.session import Session as SessionModel
from app.models.dive import Dive
from app.models import DDLookup
from decimal import Decimal
from tests.mock_server import MockHTTPClient, MockSyncServer
from tests.fixtures import seed_test_database, clear_test_database, seed_fina_dive_codes


# Helper function to seed DD lookups for tests
def _seed_test_dd_lookups(db: Session) -> int:
    """Seed test DD lookups for common test dives"""
    test_dives = [
        ("101B", ["1m", "3m", "5m", "7.5m", "10m"], [1.3, 1.5, 1.7, 2.0, 2.3]),
        ("101C", ["1m", "3m", "5m", "7.5m", "10m"], [1.4, 1.6, 1.8, 2.1, 2.4]),
        ("201B", ["1m", "3m", "5m", "7.5m", "10m"], [1.4, 1.6, 1.8, 2.1, 2.4]),
        ("201C", ["1m", "3m", "5m", "7.5m", "10m"], [1.5, 1.7, 1.9, 2.2, 2.5]),
        ("301B", ["1m", "3m", "5m", "7.5m", "10m"], [1.6, 1.8, 2.0, 2.3, 2.6]),
        ("301C", ["1m", "3m", "5m", "7.5m", "10m"], [1.7, 1.9, 2.1, 2.4, 2.7]),
        ("401B", ["1m", "3m", "5m", "7.5m", "10m"], [1.7, 1.9, 2.1, 2.4, 2.7]),
        ("401C", ["1m", "3m", "5m", "7.5m", "10m"], [1.8, 2.0, 2.2, 2.5, 2.8]),
        ("5231D", ["1m", "3m", "5m", "7.5m", "10m"], [1.9, 2.1, 2.3, 2.6, 2.9]),
        ("5233D", ["1m", "3m", "5m", "7.5m", "10m"], [2.0, 2.2, 2.4, 2.7, 3.0]),
    ]

    count = 0
    for dive_code, heights, dd_values in test_dives:
        for height, dd_val in zip(heights, dd_values):
            # Check if exists
            existing = db.query(DDLookup).filter_by(dive_code=dive_code, height=height).first()
            if existing:
                continue

            dd = DDLookup(
                dive_code=dive_code,
                height=height,
                platform_type="springboard" if height in ["1m", "3m"] else "platform",
                dd_value=Decimal(str(dd_val)),
            )
            db.add(dd)
            count += 1

    if count > 0:
        db.commit()
    return count


# Test database setup
@pytest.fixture(scope="function")
def test_db() -> Generator[Session, None, None]:
    """
    Fixture that provides a clean test database for each test.
    Uses in-memory SQLite for speed.
    """
    # Create test engine (in-memory SQLite)
    # Note: check_same_thread=False allows SQLite to be used across threads,
    # which is needed for FastAPI's async dependency injection
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False, "timeout": 30},
        poolclass=StaticPool,
        echo=False,
    )

    # Create all tables
    Base.metadata.create_all(bind=engine)

    # Create session factory
    TestingSessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
        expire_on_commit=False,  # Don't expire objects after commit
    )

    # Create session instance
    db = TestingSessionLocal()

    # Seed FINA dive codes
    try:
        seed_fina_dive_codes(db)
    except Exception:
        # If seeding fails (e.g., JSON file not found), continue anyway
        # Tests that don't need FINA codes will pass, others will fail appropriately
        pass

    # Seed DD lookups for common test dives
    try:
        _seed_test_dd_lookups(db)
    except Exception:
        # If seeding fails, continue anyway
        pass

    # Override dependency in FastAPI app
    def override_get_db():
        # Yield a new session for each request to avoid cross-thread issues
        # This is safer than sharing the same session
        try:
            yield db
        finally:
            # Don't close the session here, let the fixture cleanup handle it
            pass

    app.dependency_overrides[get_db] = override_get_db

    yield db

    # Cleanup
    try:
        db.close()
    except Exception:
        pass
    try:
        Base.metadata.drop_all(bind=engine)
    except Exception:
        pass
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def api_client(test_db: Session) -> TestClient:
    """
    Fixture that provides a FastAPI test client with injected test database.
    """
    return TestClient(app)


@pytest.fixture(scope="function")
def sample_session(test_db: Session) -> SessionModel:
    """
    Fixture that provides a sample session record in the test database.
    """
    session = SessionModel(
        date=datetime.now().date(),
        location="Pool",
        notes="Test session",
        total_dives=10,
        total_personal_dives=8,
        avg_performance=3.0,
        success_rate=80.0,
    )
    test_db.add(session)
    test_db.commit()
    test_db.refresh(session)
    return session


@pytest.fixture(scope="function")
def sample_dive(test_db: Session, sample_session: SessionModel) -> Dive:
    """
    Fixture that provides a sample two-phase dive record.
    """
    dive = Dive(
        session_id=sample_session.id,
        dive_code="101B",
        performance="G",  # Legacy score
        performance_numeric=3,
        height="5m",
        is_sync=False,
        is_smack=False,
        person_name=None,
        dive_datetime=datetime.now(),
        is_lineup=False,
        video_uuid="sample-dive-uuid-1234567890abcdefghij",
        # Two-phase format
        phase1_performance="G",  # Hurdle + Flight
        phase1_numeric=3,
        phase2_performance="P",  # Opening + Entry
        phase2_numeric=4,
    )
    test_db.add(dive)
    test_db.commit()
    test_db.refresh(dive)
    return dive


@pytest.fixture(scope="function")
def legacy_dive(test_db: Session, sample_session: SessionModel) -> Dive:
    """
    Fixture that provides a legacy (single-score) dive record.
    """
    dive = Dive(
        session_id=sample_session.id,
        dive_code="5231D",
        performance="M",  # Legacy score only
        performance_numeric=2,
        height="10m",
        is_sync=False,
        is_smack=True,
        person_name=None,
        dive_datetime=datetime.now() - timedelta(days=1),
        is_lineup=False,
        # No phase data (legacy)
        phase1_performance=None,
        phase1_numeric=None,
        phase2_performance=None,
        phase2_numeric=None,
    )
    test_db.add(dive)
    test_db.commit()
    test_db.refresh(dive)
    return dive


@pytest.fixture(scope="function")
def multiple_dives(test_db: Session, sample_session: SessionModel) -> list[Dive]:
    """
    Fixture that provides multiple dives (both legacy and two-phase format).
    """
    dives = []

    # Create 10 two-phase dives
    for i in range(10):
        dive = Dive(
            session_id=sample_session.id,
            dive_code="101B",
            performance="G",
            performance_numeric=3,
            height="5m",
            is_sync=False,
            is_smack=False,
            person_name=None,
            dive_datetime=datetime.now() - timedelta(hours=i),
            is_lineup=False,
            phase1_performance="G",
            phase1_numeric=3,
            phase2_performance="P",
            phase2_numeric=4,
        )
        dives.append(dive)

    # Create 10 legacy dives
    codes = ["201C", "301B", "401B", "5231D", "101B"]
    for i in range(10):
        dive = Dive(
            session_id=sample_session.id,
            dive_code=codes[i % len(codes)],
            performance="M",
            performance_numeric=2,
            height="3m",
            is_sync=False,
            is_smack=False,
            person_name=None,
            dive_datetime=datetime.now() - timedelta(hours=10+i),
            is_lineup=False,
            # No phase data
            phase1_performance=None,
            phase1_numeric=None,
            phase2_performance=None,
            phase2_numeric=None,
        )
        dives.append(dive)

    # Add all to database
    for dive in dives:
        test_db.add(dive)
    test_db.commit()

    # Refresh all
    for dive in dives:
        test_db.refresh(dive)

    return dives


@pytest.fixture(scope="function")
def auth_headers() -> dict[str, str]:
    """
    Fixture that provides standard auth headers (X-API-Key).
    Note: Real API key validation happens on server side.
    """
    return {
        "X-API-Key": "test-api-key-1234567890abcdef",
    }


@pytest.fixture(scope="function")
def mock_server() -> MockSyncServer:
    """
    Fixture that provides a configured mock server.
    """
    return MockSyncServer()


@pytest.fixture(scope="function")
def mock_http_client(mock_server: MockSyncServer) -> MockHTTPClient:
    """
    Fixture that provides a mock HTTP client for testing sync client.
    """
    return MockHTTPClient(mock_server)


@pytest.fixture(scope="function")
def seeded_database(test_db: Session) -> tuple[Session, dict]:
    """
    Fixture that provides a seeded test database with sample data.

    Returns:
        Tuple of (db_session, seed_stats) where seed_stats contains counts
    """
    stats = seed_test_database(test_db, num_sessions=5, dives_per_session=10)
    return test_db, stats


# Markers for test categorization
def pytest_configure(config):
    """Register custom pytest markers"""
    config.addinivalue_line(
        "markers", "unit: mark test as a unit test"
    )
    config.addinivalue_line(
        "markers", "integration: mark test as an integration test"
    )
    config.addinivalue_line(
        "markers", "e2e: mark test as an end-to-end test"
    )
    config.addinivalue_line(
        "markers", "performance: mark test as a performance test"
    )
    config.addinivalue_line(
        "markers", "mock: mark test as using mock server"
    )
