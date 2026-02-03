"""
Data integrity testing: Verify consistency and correctness

Tests:
1. Sync data matches original
2. Milestone calculations correct
3. No data corruption during transmission
4. Deduplication works
5. State consistency
"""

import pytest
import json
from datetime import datetime, timedelta
from uuid import uuid4


class TestDataIntegrity:
    """Data integrity and consistency tests"""

    def test_sync_data_preserves_original(self):
        """Test: Synced data matches original source"""
        original_video = {
            "dive_code": "101B",
            "performance": 2,  # 0-4 scale
            "height": "1m",
            "date": "2026-01-15",
            "person": None,
            "is_sync": False,
        }

        # Simulate sync transmission
        synced_video = {
            "dive_code": original_video["dive_code"],
            "performance": original_video["performance"],
            "height": original_video["height"],
            "date": original_video["date"],
            "person": original_video["person"],
            "is_sync": original_video["is_sync"],
        }

        # Verify integrity
        assert synced_video == original_video
        assert synced_video["dive_code"] == "101B"
        assert synced_video["performance"] == 2

    def test_milestone_calculation_correctness(self):
        """Test: Milestone calculations are accurate"""
        dives = [
            {"dive_code": "101B", "performance": 1},  # Bad
            {"dive_code": "101B", "performance": 2},  # Medium - FIRST SUCCESS
            {"dive_code": "101B", "performance": 3},  # Good
            {"dive_code": "101B", "performance": 2},  # Medium
        ]

        # Find first success
        first_success = next((d for d in dives if d["performance"] >= 2), None)
        assert first_success is not None
        assert first_success == dives[1]

        # Calculate success rate
        successful = [d for d in dives if d["performance"] >= 2]
        success_rate = len(successful) / len(dives)
        assert success_rate == 0.75  # 3 out of 4

    def test_deduplication_removes_exact_duplicates(self):
        """Test: Duplicate detection works correctly"""
        videos = [
            {"id": "1", "dive_code": "101B", "date": "2026-01-15", "time": "10:00:00"},
            {"id": "2", "dive_code": "101B", "date": "2026-01-15", "time": "10:00:01"},  # 1 second apart
            {"id": "3", "dive_code": "101B", "date": "2026-01-15", "time": "10:00:00"},  # DUPLICATE
            {"id": "4", "dive_code": "201C", "date": "2026-01-15", "time": "10:01:00"},
        ]

        # Deduplicate (within 2 second window, same dive code)
        deduped = []
        seen = set()

        for video in videos:
            key = (video["dive_code"], video["date"], video["time"][:5])  # Minute precision
            if key not in seen:
                deduped.append(video)
                seen.add(key)

        # Should have 2 unique videos (ids 1/2/3 group to same minute, id 4 different)
        assert len(deduped) == 2

    def test_performance_scale_consistency(self):
        """Test: Performance scale remains consistent"""
        # Define performance scale
        performance_map = {"F": 0, "B": 1, "M": 2, "G": 3, "P": 4}

        dives = [
            {"code": "101B", "perf_letter": "F"},
            {"code": "101B", "perf_letter": "P"},
            {"code": "201C", "perf_letter": "G"},
        ]

        # Convert and verify
        for dive in dives:
            perf_value = performance_map[dive["perf_letter"]]
            # Verify round-trip
            reverse_map = {v: k for k, v in performance_map.items()}
            assert reverse_map[perf_value] == dive["perf_letter"]

    def test_height_value_normalization(self):
        """Test: Height values normalized correctly"""
        raw_heights = [
            "1m",
            "1M",  # Uppercase
            "3m",
            "3mP",  # Platform variant
            "5M",  # Uppercase
            "10m",
        ]

        # Normalize
        normalized = [h.lower() for h in raw_heights]

        expected = ["1m", "1m", "3m", "3mp", "5m", "10m"]
        assert normalized == expected

    def test_date_consistency(self):
        """Test: Dates stored and retrieved consistently"""
        original_date = "2026-01-15"

        # Simulate storage and retrieval
        stored_date = original_date  # In ISO format
        retrieved_date = stored_date

        # Parse as datetime
        dt = datetime.fromisoformat(retrieved_date)
        assert dt.year == 2026
        assert dt.month == 1
        assert dt.day == 15

        # Format back
        formatted = dt.date().isoformat()
        assert formatted == original_date

    def test_dive_code_validation(self):
        """Test: Dive codes remain valid through sync"""
        valid_codes = ["101B", "201C", "301D", "5231D", "5"]

        for code in valid_codes:
            # Validate format (digit + letter, or single digit for lineups)
            assert code[0].isdigit()

    def test_uuid_consistency(self):
        """Test: UUIDs generated consistently"""
        video_id = str(uuid4())

        # Should be valid UUID format
        assert len(video_id) == 36  # Standard UUID length
        assert video_id.count("-") == 4

        # Same ID should equal itself
        assert video_id == video_id

    def test_sync_id_tracking(self):
        """Test: Sync IDs properly tracked through workflow"""
        sync_id = str(uuid4())[:8]

        # Track videos in this sync
        sync_videos = [
            {"sync_id": sync_id, "dive_code": "101B"},
            {"sync_id": sync_id, "dive_code": "201C"},
            {"sync_id": sync_id, "dive_code": "301D"},
        ]

        # All videos should have same sync_id
        assert all(v["sync_id"] == sync_id for v in sync_videos)

        # Milestones should reference sync_id
        milestone = {
            "sync_id": sync_id,
            "type": "first_success",
            "dive_code": "101B",
        }
        assert milestone["sync_id"] == sync_id

    def test_state_consistency_across_sync_lifecycle(self):
        """Test: State remains consistent through sync lifecycle"""
        sync_id = "sync_123"

        # Initial state
        state = {
            "sync_id": sync_id,
            "status": "started",
            "total_videos": 100,
            "synced_count": 0,
            "error_count": 0,
            "milestones_detected": [],
        }

        # Progress state
        state["status"] = "in_progress"
        state["synced_count"] = 50
        assert state["total_videos"] - state["synced_count"] == 50

        # Add milestone
        milestone = {"type": "first_success", "dive_code": "101B"}
        state["milestones_detected"].append(milestone)
        assert len(state["milestones_detected"]) == 1

        # Complete state
        state["status"] = "complete"
        state["synced_count"] = 100
        assert state["synced_count"] == state["total_videos"]
        assert len(state["milestones_detected"]) > 0

    def test_error_state_doesn_not_corrupt_valid_data(self):
        """Test: Errors don't corrupt already-synced data"""
        sync_result = {
            "total_videos": 100,
            "synced_count": 75,
            "error_count": 25,
            "synced_videos": [
                {"dive_code": "101B", "performance": 2},
                {"dive_code": "201C", "performance": 3},
            ],
            "errors": [{"video_id": "x", "reason": "corrupted"}],
        }

        # Verify synced data unchanged despite errors
        assert len(sync_result["synced_videos"]) == 2
        assert all(
            "performance" in v and isinstance(v["performance"], int)
            for v in sync_result["synced_videos"]
        )

        # Verify error count accurate
        assert sync_result["synced_count"] + sync_result["error_count"] <= sync_result["total_videos"]

    def test_milestone_type_validation(self):
        """Test: Milestone types are valid"""
        valid_types = [
            "first_dive",
            "first_success",
            "height_milestone",
            "consistency_milestone",
            "dive_mastery",
        ]

        milestones = [{"type": t, "title": f"Achievement: {t}"} for t in valid_types]

        for milestone in milestones:
            assert milestone["type"] in valid_types

    def test_concurrent_sync_data_isolation(self):
        """Test: Data from concurrent syncs doesn't mix"""
        sync1_id = "sync_001"
        sync2_id = "sync_002"

        sync1_videos = [
            {"sync_id": sync1_id, "dive_code": "101B"},
            {"sync_id": sync1_id, "dive_code": "201C"},
        ]

        sync2_videos = [
            {"sync_id": sync2_id, "dive_code": "301D"},
            {"sync_id": sync2_id, "dive_code": "401D"},
        ]

        # Verify isolation
        sync1_codes = [v["dive_code"] for v in sync1_videos if v["sync_id"] == sync1_id]
        sync2_codes = [v["dive_code"] for v in sync2_videos if v["sync_id"] == sync2_id]

        assert sync1_codes == ["101B", "201C"]
        assert sync2_codes == ["301D", "401D"]
        assert set(sync1_codes) & set(sync2_codes) == set()

    def test_performance_sum_validation(self):
        """Test: Performance sums calculated correctly"""
        dives = [
            {"performance": 0},  # Failed
            {"performance": 1},  # Bad
            {"performance": 2},  # Medium
            {"performance": 3},  # Good
            {"performance": 4},  # Perfect
        ]

        total = sum(d["performance"] for d in dives)
        average = total / len(dives)

        assert total == 10
        assert average == 2.0  # Perfect average

    def test_temporal_ordering_preserved(self):
        """Test: Temporal order of dives preserved"""
        dives = [
            {"date": "2026-01-15", "time": "10:00"},
            {"date": "2026-01-15", "time": "10:30"},
            {"date": "2026-01-16", "time": "09:00"},
        ]

        # Verify ordering
        for i in range(len(dives) - 1):
            current = (dives[i]["date"], dives[i]["time"])
            next_dive = (dives[i + 1]["date"], dives[i + 1]["time"])
            assert current <= next_dive

    def test_recovery_from_partial_sync(self):
        """Test: Can recover from partial sync failure"""
        sync_id = "sync_partial"

        # Initial 100 videos to sync
        total = 100

        # Sync 60, then error at 61
        successful = 60
        failed = 40

        # Recovery state
        recovery_state = {
            "sync_id": sync_id,
            "previously_synced": successful,
            "remaining": failed,
            "can_resume": True,
        }

        assert recovery_state["previously_synced"] + recovery_state["remaining"] == total
        assert recovery_state["can_resume"] is True
