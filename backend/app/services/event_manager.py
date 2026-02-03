"""Event Manager service for competition management"""

from typing import List, Dict, Tuple, Optional
from datetime import datetime
from sqlalchemy.orm import Session

from app.models.competition_event import (
    CompetitionEvent,
    CompetitionRound,
    CompetitionCompetitor,
    CompetitionDiveEntry,
)
from app.models.fina_scoring_rule import FINAScoringRule
from app.models.fina_dive_code import FINADiveCode
from app.services.dd_calculator import DDCalculator


class EventManager:
    """Manages competition events with FINA rule enforcement"""

    def __init__(self, db: Session):
        self.db = db
        self.dd_calculator = DDCalculator(db)

    # Event lifecycle methods

    def create_event(
        self,
        event_name: str,
        event_code: str,
        fina_scoring_rule_id: int,
        location: Optional[str] = None,
        organizer: Optional[str] = None,
        is_fina_official: bool = False,
    ) -> CompetitionEvent:
        """Create a new competition event"""
        event = CompetitionEvent(
            event_name=event_name,
            event_code=event_code,
            fina_scoring_rule_id=fina_scoring_rule_id,
            location=location,
            organizer=organizer,
            is_fina_official=is_fina_official,
            status="DRAFT",
        )
        self.db.add(event)
        self.db.commit()
        self.db.refresh(event)
        return event

    def start_event_registration(self, event_id: int) -> bool:
        """Open event for competitor registration"""
        event = self.db.query(CompetitionEvent).filter(CompetitionEvent.id == event_id).first()
        if not event:
            raise ValueError(f"Event {event_id} not found")
        event.status = "REGISTRATION"
        event.start_date = datetime.utcnow()
        self.db.commit()
        return True

    def close_event_registration(self, event_id: int) -> bool:
        """Close registration and start event"""
        event = self.db.query(CompetitionEvent).filter(CompetitionEvent.id == event_id).first()
        if not event:
            raise ValueError(f"Event {event_id} not found")
        event.status = "ACTIVE"
        self.db.commit()
        return True

    def finalize_event(self, event_id: int) -> Dict:
        """Finalize event and close for changes"""
        event = self.db.query(CompetitionEvent).filter(CompetitionEvent.id == event_id).first()
        if not event:
            raise ValueError(f"Event {event_id} not found")

        event.status = "COMPLETED"
        event.end_date = datetime.utcnow()
        self.db.commit()

        return {"event_id": event_id, "status": "COMPLETED"}

    # Round management

    def create_round(
        self, event_id: int, round_number: int, round_type: str, dd_limit: Optional[int] = None
    ) -> CompetitionRound:
        """Create a round for the event"""
        event = self.db.query(CompetitionEvent).filter(CompetitionEvent.id == event_id).first()
        if not event:
            raise ValueError(f"Event {event_id} not found")

        if round_type not in ["PRELIMINARY", "SEMI_FINAL", "FINAL"]:
            raise ValueError(f"Invalid round_type: {round_type}")

        round_obj = CompetitionRound(
            event_id=event_id,
            round_number=round_number,
            round_type=round_type,
            dd_limit=dd_limit,
        )
        self.db.add(round_obj)
        self.db.commit()
        self.db.refresh(round_obj)
        return round_obj

    def set_dd_limit(self, round_id: int, dd_limit: int) -> bool:
        """Set DD limit for round (e.g., 2 for synchronized first rounds)"""
        round_obj = self.db.query(CompetitionRound).filter(CompetitionRound.id == round_id).first()
        if not round_obj:
            raise ValueError(f"Round {round_id} not found")

        round_obj.dd_limit = dd_limit
        self.db.commit()
        return True

    # Competitor management

    def register_competitor(
        self, event_id: int, competitor_name: str, country_code: Optional[str] = None
    ) -> CompetitionCompetitor:
        """Register a competitor for the event"""
        event = self.db.query(CompetitionEvent).filter(CompetitionEvent.id == event_id).first()
        if not event:
            raise ValueError(f"Event {event_id} not found")

        competitor = CompetitionCompetitor(
            event_id=event_id, competitor_name=competitor_name, country_code=country_code, status="REGISTERED"
        )
        self.db.add(competitor)
        self.db.commit()
        self.db.refresh(competitor)
        return competitor

    def get_event_competitors(self, event_id: int) -> List[CompetitionCompetitor]:
        """Get all competitors for an event"""
        return self.db.query(CompetitionCompetitor).filter(CompetitionCompetitor.event_id == event_id).all()

    # Dive lineup submission and validation

    def submit_dive_lineup(self, round_id: int, competitor_id: int, dives: List[Dict]) -> Dict:
        """Submit dive lineup for competitor"""
        # Validate lineup first
        is_valid, errors = self.validate_dive_lineup(round_id, competitor_id, dives)
        if not is_valid:
            return {"success": False, "message": "Validation failed", "errors": errors}

        # Delete existing entries
        self.db.query(CompetitionDiveEntry).filter(
            CompetitionDiveEntry.round_id == round_id,
            CompetitionDiveEntry.competitor_id == competitor_id,
        ).delete()

        # Create new entries
        entries = []
        for order, dive_data in enumerate(dives, 1):
            entry = CompetitionDiveEntry(
                round_id=round_id,
                competitor_id=competitor_id,
                dive_order=order,
                dive_code=dive_data["dive_code"],
                planned_dd=int(dive_data["planned_dd"] * 100),
                status="PENDING",
            )
            self.db.add(entry)
            entries.append(entry)

        self.db.commit()

        return {
            "success": True,
            "message": f"Submitted {len(entries)} dives",
            "entries": [
                {"dive_order": e.dive_order, "dive_code": e.dive_code, "planned_dd": e.planned_dd / 100}
                for e in entries
            ],
        }

    def validate_dive_lineup(
        self, round_id: int, competitor_id: int, dives: Optional[List[Dict]] = None
    ) -> Tuple[bool, List[str]]:
        """Validate dive lineup against FINA rules"""
        errors = []

        round_obj = self.db.query(CompetitionRound).filter(CompetitionRound.id == round_id).first()
        if not round_obj:
            return False, [f"Round {round_id} not found"]

        event = round_obj.event
        rule = event.scoring_rule

        if dives is None:
            dive_entries = self.db.query(CompetitionDiveEntry).filter(
                CompetitionDiveEntry.round_id == round_id,
                CompetitionDiveEntry.competitor_id == competitor_id,
            ).all()
            dives = [{"dive_code": e.dive_code, "planned_dd": e.planned_dd / 100} for e in dive_entries]

        if not dives:
            errors.append("No dives in lineup")
            return False, errors

        # Check dive count
        if len(dives) != rule.mandatory_dive_count:
            errors.append(f"Expected {rule.mandatory_dive_count} dives, got {len(dives)}")

        # Check mandatory groups
        dive_codes = [d["dive_code"] for d in dives]
        fina_codes = self.db.query(FINADiveCode).filter(FINADiveCode.dive_code.in_(dive_codes)).all()
        code_to_group = {fc.dive_code: fc.group for fc in fina_codes}

        present_groups = set(code_to_group.get(code) for code in dive_codes if code in code_to_group)
        required_groups = set(rule.mandatory_groups)

        missing_groups = required_groups - present_groups
        if missing_groups:
            errors.append(f"Missing mandatory groups: {sorted(missing_groups)}")

        # Check DD limit
        if round_obj.dd_limit:
            total_dd = sum(d.get("planned_dd", 0) for d in dives[:5])
            if total_dd > round_obj.dd_limit:
                errors.append(f"DD limit exceeded: {total_dd} > {round_obj.dd_limit}")

        # Check for duplicate codes
        if len(dive_codes) != len(set(dive_codes)):
            errors.append("Duplicate dive codes in lineup")

        return len(errors) == 0, errors

    def get_event_standings(self, event_id: int) -> List[Dict]:
        """Get standings for entire event"""
        return []

    def get_round_standings(self, round_id: int) -> List[Dict]:
        """Get standings for a specific round"""
        return []
