"""DD Auto-Assignment Service - automatically assigns DD values based on dive code and height"""

from datetime import datetime
from typing import Optional, Dict, Tuple
from decimal import Decimal
from sqlalchemy.orm import Session

from app.models import Dive
from app.services.dd_calculator import DDCalculator
from app.services.world_aquatics_dd import REFERENCE_ID


class DDAssignmentError(Exception):
    """Raised when DD assignment fails"""
    pass


class DDAutoAssigner:
    """Automatically assigns DD values to dives"""

    def __init__(self, db: Session):
        """Initialize assigner"""
        self.db = db
        self.calculator = DDCalculator(db)

    def assign_dd_to_dive(self, dive_id: int) -> Tuple[bool, Optional[Dict]]:
        """
        Automatically assign DD to a dive.

        Args:
            dive_id: ID of the dive to assign DD to

        Returns:
            (success, result_dict)
        """
        try:
            # Get dive
            dive = self.db.query(Dive).filter_by(id=dive_id).first()
            if not dive:
                return False, {"error": f"Dive {dive_id} not found"}

            # Parse dive code to get height
            if not hasattr(dive, "height") or not dive.height:
                return False, {"error": f"Dive {dive_id} missing height"}

            # Look up DD
            dd_value = self.calculator.lookup_dd(dive.dive_code, dive.height)
            if not dd_value:
                return False, {
                    "error": f"No DD found for {dive.dive_code} at {dive.height}"
                }

            dive.official_dd = dd_value
            dive.official_dd_verification_status = "official_formula"
            dive.official_dd_source = REFERENCE_ID
            dive.official_dd_assigned_at = datetime.utcnow()
            self.db.commit()

            return True, {
                "dive_id": dive_id,
                "dive_code": dive.dive_code,
                "height": dive.height,
                "dd_value": float(dd_value),
            }

        except Exception as e:
            return False, {"error": str(e)}

    def assign_dd_to_dives_batch(self, dive_ids: list) -> Dict:
        """
        Assign DD to multiple dives.

        Returns:
            Dict with success_count, failed_count, errors
        """
        success_count = 0
        failed_count = 0
        errors = []

        for dive_id in dive_ids:
            success, result = self.assign_dd_to_dive(dive_id)
            if success:
                success_count += 1
            else:
                failed_count += 1
                if "error" in result:
                    errors.append(f"Dive {dive_id}: {result['error']}")

        return {
            "total": len(dive_ids),
            "success": success_count,
            "failed": failed_count,
            "errors": errors,
        }

    def assign_dd_to_session_dives(self, session_id: int) -> Dict:
        """
        Assign DD to all dives in a session.

        Returns:
            Dict with statistics
        """
        try:
            # Get all dives for session
            dives = self.db.query(Dive).filter_by(session_id=session_id).all()

            if not dives:
                return {
                    "session_id": session_id,
                    "total": 0,
                    "success": 0,
                    "failed": 0,
                }

            dive_ids = [dive.id for dive in dives]
            return self.assign_dd_to_dives_batch(dive_ids)

        except Exception as e:
            return {
                "session_id": session_id,
                "error": str(e),
            }

    def estimate_dd_for_dive(
        self,
        dive_code: str,
        height: str,
    ) -> Optional[Decimal]:
        """Return a formula-defined DD, never an estimated value."""
        # Normalize height
        height = height.lower().strip()
        normalization = {"7m": "7.5m"}
        height = normalization.get(height, height)

        # Try to look up from database
        dd_value = self.calculator.lookup_dd(dive_code, height)
        if dd_value:
            return dd_value

        # Official DD is a table/formula result, never a heuristic estimate.
        return None

    def get_assignment_statistics(self, session_id: int) -> Dict:
        """Get statistics about DD assignments in a session"""
        try:
            dives = self.db.query(Dive).filter_by(session_id=session_id).all()

            total = len(dives)
            with_dd = sum(1 for d in dives if d.official_dd is not None)
            without_dd = total - with_dd

            return {
                "session_id": session_id,
                "total_dives": total,
                "with_dd": with_dd,
                "without_dd": without_dd,
                "assignment_percentage": (with_dd / total * 100) if total > 0 else 0,
            }
        except Exception as e:
            return {
                "session_id": session_id,
                "error": str(e),
            }

    def validate_assignments(self, session_id: int) -> Dict:
        """Validate that all dives have appropriate DD values"""
        try:
            dives = self.db.query(Dive).filter_by(session_id=session_id).all()

            issues = []
            for dive in dives:
                # Check if dive has DD
                if not hasattr(dive, "dd_value") or not dive.dd_value:
                    issues.append({
                        "dive_id": dive.id,
                        "issue": "Missing DD value",
                    })
                    continue

                # Check if DD value is valid
                dd_float = float(dive.dd_value)
                if dd_float < 1.0 or dd_float > 5.0:
                    issues.append({
                        "dive_id": dive.id,
                        "issue": f"Invalid DD value: {dd_float}",
                    })

            return {
                "session_id": session_id,
                "total_dives": len(dives),
                "issues_found": len(issues),
                "issues": issues,
            }
        except Exception as e:
            return {
                "session_id": session_id,
                "error": str(e),
            }
