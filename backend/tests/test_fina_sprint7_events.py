"""Sprint 7: Event Management Tests"""

import pytest
from sqlalchemy.orm import Session

from app.services.event_manager import EventManager


class TestEventManager:
    """Test event manager service"""

    @pytest.fixture
    def event_mgr(self, test_db):
        return EventManager(test_db)

    def test_create_event(self, event_mgr):
        """Test creating an event"""
        result = event_mgr.create_event({"name": "State Championships 2026"})
        assert "event_id" in result
        assert result["name"] == "State Championships 2026"

    def test_create_round(self, event_mgr):
        """Test creating a round"""
        result = event_mgr.create_round(1, {"name": "Preliminaries"})
        assert "round_id" in result
        assert result["event_id"] == 1

    def test_create_heat(self, event_mgr):
        """Test creating a heat"""
        result = event_mgr.create_heat(1, {"name": "Heat 1"})
        assert "heat_id" in result
        assert result["round_id"] == 1

    def test_add_competitor(self, event_mgr):
        """Test adding competitor"""
        result = event_mgr.add_competitor(1, {"name": "John Doe"})
        assert "competitor_id" in result
        assert result["name"] == "John Doe"

    def test_get_event_standings(self, event_mgr):
        """Test getting event standings"""
        standings = event_mgr.get_event_standings(1)
        assert isinstance(standings, list)

    def test_finalize_event(self, event_mgr):
        """Test finalizing event"""
        result = event_mgr.finalize_event(1)
        assert result is True
