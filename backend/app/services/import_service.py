"""Import service for loading dive data from JSON files"""

import json
import os
import re
from datetime import datetime, date
from typing import Dict, List, Any, Optional
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.dive import Dive
from app.models.session import Session as SessionModel
from app.services.performance_scoring import ORDINAL_SCORE, dive_score_10, is_success
from app.services.diver_identity import invalidate_analysis_cache, resolve_diver

# Performance letter to numeric mapping
PERFORMANCE_MAP = ORDINAL_SCORE
CANONICAL_DIVE_CODE_RE = re.compile(r"^\d{3,4}[ABCD]$")


class ImportService:
    """Service for importing dive data from JSON files"""

    def __init__(self, db: Session):
        self.db = db
        self.stats = {
            'sessions_created': 0,
            'sessions_updated': 0,
            'dives_created': 0,
            'dives_skipped': 0,
            'errors': [],
        }

    def import_from_json(self, json_path: str) -> Dict[str, Any]:
        """
        Import dives from a JSON file into the database.

        Args:
            json_path: Path to the JSON file

        Returns:
            Dictionary with import statistics
        """
        self.stats = {
            'sessions_created': 0,
            'sessions_updated': 0,
            'dives_created': 0,
            'dives_skipped': 0,
            'errors': [],
        }

        # Read JSON file
        try:
            with open(json_path, 'r') as f:
                data = json.load(f)
        except FileNotFoundError:
            self.stats['errors'].append(f"File not found: {json_path}")
            return self.stats
        except json.JSONDecodeError as e:
            self.stats['errors'].append(f"Invalid JSON: {e}")
            return self.stats

        # Get valid dive videos
        valid_dives = data.get('valid_dive_videos', [])
        if not valid_dives:
            self.stats['errors'].append("No valid dive videos found in JSON")
            return self.stats

        # Group dives by date (for sessions)
        dives_by_date: Dict[date, List[Dict]] = {}
        for dive_data in valid_dives:
            try:
                dive_date = self._parse_date(dive_data.get('date'))
                if dive_date:
                    if dive_date not in dives_by_date:
                        dives_by_date[dive_date] = []
                    dives_by_date[dive_date].append(dive_data)
            except Exception as e:
                self.stats['errors'].append(f"Error parsing dive: {e}")

        # Process each date/session
        for session_date, dives in sorted(dives_by_date.items()):
            self._process_session(session_date, dives)

        # Update session statistics
        self._update_session_stats()

        return self.stats

    def _parse_date(self, date_str: Optional[str]) -> Optional[date]:
        """Parse date string to date object"""
        if not date_str:
            return None
        try:
            # Handle ISO format with timezone
            dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            return dt.date()
        except ValueError:
            try:
                # Try simple date format
                return datetime.strptime(date_str[:10], '%Y-%m-%d').date()
            except ValueError:
                return None

    def _parse_datetime(self, date_str: Optional[str]) -> Optional[datetime]:
        """Parse date string to datetime object"""
        if not date_str:
            return None
        try:
            return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        except ValueError:
            try:
                return datetime.strptime(date_str[:19], '%Y-%m-%dT%H:%M:%S')
            except ValueError:
                return None

    def _get_direction(self, dive_code: str) -> Optional[int]:
        """Extract direction (1-5) from dive code. Returns None for lineups (0xx)."""
        if dive_code and len(dive_code) >= 1:
            first_char = dive_code[0]
            if first_char.isdigit():
                direction = int(first_char)
                # Direction 0 means lineup - return None to satisfy DB constraint
                if direction == 0:
                    return None
                # Valid directions are 1-5
                if 1 <= direction <= 5:
                    return direction
        return None

    def _process_session(self, session_date: date, dives: List[Dict]) -> None:
        """Process a single session (date) with its dives"""
        # Find or create session
        session = self.db.query(SessionModel).filter(
            SessionModel.date == session_date
        ).first()

        if not session:
            session = SessionModel(
                date=session_date,
                location=None,
                notes=None,
                weather=None,
            )
            self.db.add(session)
            self.db.flush()  # Get the session ID
            self.stats['sessions_created'] += 1
        else:
            self.stats['sessions_updated'] += 1

        # Get existing dive UUIDs for this session to avoid duplicates
        existing_uuids = set(
            uuid for (uuid,) in self.db.query(Dive.video_uuid).filter(
                Dive.session_id == session.id,
                Dive.video_uuid.isnot(None)
            ).all()
        )

        # Process each dive
        for dive_data in dives:
            video_uuid = dive_data.get('uuid')

            # Skip if already imported (by UUID)
            if video_uuid and video_uuid in existing_uuids:
                self.stats['dives_skipped'] += 1
                continue

            try:
                self._create_dive(session.id, dive_data)
                self.stats['dives_created'] += 1
            except Exception as e:
                self.stats['errors'].append(f"Error creating dive: {e}")

        self.db.commit()

    def _create_dive(self, session_id: int, dive_data: Dict) -> Dive:
        """Create a dive record from JSON data"""
        performance = dive_data.get('performance', 'M')
        performance_numeric = PERFORMANCE_MAP.get(performance, 2)

        # Phase-specific scores (new two-phase format introduced Jan 2026)
        # Phase 1: Hurdle + Flight (takeoff quality)
        # Phase 2: Opening + Water Splash + Entry (landing quality)
        phase1_performance = dive_data.get('phase1_performance')
        phase1_numeric = dive_data.get('phase1_numeric')
        phase2_performance = dive_data.get('phase2_performance')
        phase2_numeric = dive_data.get('phase2_numeric')

        person_name = dive_data.get('person')
        diver = resolve_diver(self.db, person_name)
        dive_code = str(dive_data.get('dive_code', '')).upper()
        position = dive_data.get('position')
        if not position and CANONICAL_DIVE_CODE_RE.fullmatch(dive_code):
            position = dive_code[-1]
        dive = Dive(
            session_id=session_id,
            dive_code=dive_code,
            dive_number=dive_data.get('dive_number'),
            position=position,
            direction=self._get_direction(dive_code),
            performance=performance,
            performance_numeric=performance_numeric,
            phase1_performance=phase1_performance,
            phase1_numeric=phase1_numeric,
            phase2_performance=phase2_performance,
            phase2_numeric=phase2_numeric,
            height=dive_data.get('height', '1m').upper(),
            platform_type=dive_data.get('platform_type', 'springboard'),
            is_lineup=dive_data.get('is_lineup', False),
            is_sync=dive_data.get('sync', False),
            is_smack=dive_data.get('smack', False),
            raw_caption=dive_data.get('raw_caption'),
            person_name=person_name,
            diver_id=diver.id if diver else None,
            notes=None,
            video_uuid=dive_data.get('uuid'),
            video_filename=dive_data.get('filename'),
            video_path=dive_data.get('path'),
            dive_datetime=self._parse_datetime(dive_data.get('date')) or datetime.now(),
        )

        self.db.add(dive)
        invalidate_analysis_cache(self.db)
        return dive

    def _update_session_stats(self) -> None:
        """Update computed statistics for all sessions"""
        sessions = self.db.query(SessionModel).all()

        for session in sessions:
            # Get all dives for this session
            dives = self.db.query(Dive).filter(Dive.session_id == session.id).all()

            # Total dives
            session.total_dives = len(dives)

            # Personal dives (not lineup)
            personal_dives = [d for d in dives if not d.is_lineup]
            session.total_personal_dives = len(personal_dives)

            # Average performance (personal dives only)
            if personal_dives:
                avg_perf = sum(dive_score_10(d) for d in personal_dives) / len(personal_dives)
                session.avg_performance = round(avg_perf, 2)

                # Success rate is still categorical: M/G/P are successful.
                successful = sum(1 for d in personal_dives if is_success(d.performance))
                session.success_rate = round((successful / len(personal_dives)) * 100, 1)
            else:
                session.avg_performance = None
                session.success_rate = None

        self.db.commit()

    def clear_all_data(self) -> Dict[str, int]:
        """Clear all dives and sessions (for fresh import)"""
        dives_deleted = self.db.query(Dive).delete()
        sessions_deleted = self.db.query(SessionModel).delete()
        self.db.commit()

        return {
            'dives_deleted': dives_deleted,
            'sessions_deleted': sessions_deleted,
        }


def find_latest_json(base_path: str = '/app/reports') -> Optional[str]:
    """Find the latest dive metadata JSON file"""
    # First try the symlink
    symlink_path = os.path.join(base_path, 'dive_metadata_report_final.json')
    if os.path.exists(symlink_path):
        return symlink_path

    # Look for dive_metadata_*.json files
    reports_dir = Path(base_path)
    if not reports_dir.exists():
        return None

    json_files = list(reports_dir.glob('dive_metadata_*.json'))
    if not json_files:
        return None

    # Return the most recent one
    return str(max(json_files, key=lambda p: p.stat().st_mtime))
