"""
Validation service for two-phase dive scoring.

Validates phase1/phase2 combinations and converts to legacy single scores
for backwards compatibility with existing analytics.
"""

from typing import Tuple, Optional


class PhaseValidator:
    """Validates two-phase dive scores and handles conversions"""

    # Valid performance levels
    VALID_SCORES = {'F': 0, 'B': 1, 'M': 2, 'G': 3, 'P': 4}

    @staticmethod
    def validate_combination(
        phase1: Optional[str],
        phase2: Optional[str]
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate that phase1/phase2 combination is reasonable.

        Rules:
        - Both must be valid performance letters (F, B, M, G, P)
        - Can be identical (e.g., G/G, M/M)
        - Any combination of valid scores is allowed (coaching will handle it)

        Args:
            phase1: Phase 1 (Hurdle + Flight) score
            phase2: Phase 2 (Opening + Entry) score

        Returns:
            Tuple of (is_valid: bool, error_reason: Optional[str])

        Examples:
            >>> validate_combination("G", "P")
            (True, None)
            >>> validate_combination("F", "G")
            (True, None)
            >>> validate_combination("X", "G")
            (False, "Invalid phase1 score: X")
            >>> validate_combination("G", None)
            (False, "Both phase1 and phase2 must be provided together")
        """
        # Both must be provided or both must be None
        if (phase1 is None) != (phase2 is None):
            return False, "Both phase1 and phase2 must be provided together"

        # If both None, that's OK (legacy format)
        if phase1 is None and phase2 is None:
            return True, None

        # Validate each is a valid performance score
        if phase1 not in PhaseValidator.VALID_SCORES:
            return False, f"Invalid phase1 score: {phase1} (must be F/B/M/G/P)"

        if phase2 not in PhaseValidator.VALID_SCORES:
            return False, f"Invalid phase2 score: {phase2} (must be F/B/M/G/P)"

        # All combinations are valid (coaching will handle different patterns)
        return True, None

    @staticmethod
    def infer_legacy_score(phase1: str, phase2: str) -> str:
        """
        Convert two-phase scores to single legacy score.

        Strategy: Take the minimum score (pessimistic estimate)
        This ensures a dive is considered successful only if both phases
        were executed at a minimum level.

        Examples:
            >>> infer_legacy_score("G", "P")
            "G"  # min(3, 4) = 3 = "G"
            >>> infer_legacy_score("M", "P")
            "M"  # min(2, 4) = 2 = "M"
            >>> infer_legacy_score("P", "P")
            "P"  # min(4, 4) = 4 = "P"
            >>> infer_legacy_score("F", "G")
            "F"  # min(0, 3) = 0 = "F"

        Args:
            phase1: Phase 1 (Hurdle + Flight) score
            phase2: Phase 2 (Opening + Entry) score

        Returns:
            Single legacy performance score (F/B/M/G/P)
        """
        scores = PhaseValidator.VALID_SCORES
        if phase1 not in scores:
            raise ValueError(f"Invalid phase1 score: {phase1}")
        if phase2 not in scores:
            raise ValueError(f"Invalid phase2 score: {phase2}")

        # Take minimum (pessimistic)
        composite_numeric = min(scores[phase1], scores[phase2])

        # Convert back to letter
        reverse_map = {0: 'F', 1: 'B', 2: 'M', 3: 'G', 4: 'P'}
        return reverse_map[composite_numeric]

    @staticmethod
    def get_phase_insight(phase1: str, phase2: str) -> str:
        """
        Get coaching insight for a specific phase combination.

        Args:
            phase1: Phase 1 (Hurdle + Flight) score
            phase2: Phase 2 (Opening + Entry) score

        Returns:
            Coaching text describing the phase combination

        Examples:
            >>> get_phase_insight("P", "P")
            "Perfect execution: Both phases flawless..."
            >>> get_phase_insight("G", "M")
            "Good flight, solid entry..."
        """
        # Pattern-based coaching insights
        patterns = {
            # Perfect execution
            ("P", "P"): "Perfect execution: Both phases flawless. Competition-ready.",
            ("P", "G"): "Excellent flight, great entry. Minor refinements possible.",
            ("P", "M"): "Excellent flight, but entry needs work. Focus on landing control.",
            ("P", "B"): "Strong flight but weak entry. Major focus needed on entry phase.",
            ("P", "F"): "Perfect flight but failed entry. Complete landing mechanics review needed.",

            # Good flight
            ("G", "P"): "Good flight, excellent recovery. Outstanding adaptive control.",
            ("G", "G"): "Balanced execution: Both phases well-controlled. Continue technical work.",
            ("G", "M"): "Good flight, average entry. Focus on entry phase improvements.",
            ("G", "B"): "Good flight but weak entry. Entry control is the limiting factor.",
            ("G", "F"): "Good flight but failed entry. Major entry phase work needed.",

            # Medium performance
            ("M", "P"): "Solid flight, remarkable recovery. Excellent adaptation under pressure.",
            ("M", "G"): "Medium flight, good entry. Work on both phases for improvement.",
            ("M", "M"): "Consistent execution: Both phases equally developed. Continue progression.",
            ("M", "B"): "Adequate flight but weak entry. Entry phase needs focus.",
            ("M", "F"): "Decent flight but failed entry. Entry is critical weakness.",

            # Below average flight
            ("B", "P"): "Weak flight but exceptional recovery. Strong mental game evident.",
            ("B", "G"): "Below-average flight, good entry. Flight mechanics need work.",
            ("B", "M"): "Weak flight and entry. Work on takeoff phase fundamentals.",
            ("B", "B"): "Both phases below average. Systematic improvement needed.",
            ("B", "F"): "Weak flight and failed entry. Complete dive review recommended.",

            # Failed flight
            ("F", "P"): "Failed flight but recovered entry. Focus on takeoff mechanics.",
            ("F", "G"): "Failed flight, good entry. Impossible - re-check scoring.",
            ("F", "M"): "Failed flight, average entry. Takeoff is primary focus.",
            ("F", "B"): "Failed flight and weak entry. Comprehensive technique review.",
            ("F", "F"): "Complete failure. Review dive selection and fundamentals.",
        }

        return patterns.get(
            (phase1, phase2),
            f"Phase 1: {phase1}, Phase 2: {phase2} - Review technique for both phases."
        )

    @staticmethod
    def validate_with_dive_code(
        dive_code: str,
        phase1: Optional[str],
        phase2: Optional[str]
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate phase scores in context of specific dive code.

        Note: Currently all dive codes can have all phase combinations.
        This method is extensible for future rules like:
        - Some codes are easier/harder (no rules yet)
        - Certain combinations make less sense (no rules yet)

        Args:
            dive_code: FINA dive code (e.g., "101B")
            phase1: Phase 1 score
            phase2: Phase 2 score

        Returns:
            Tuple of (is_valid: bool, error_reason: Optional[str])
        """
        # First validate the basic combination
        valid, reason = PhaseValidator.validate_combination(phase1, phase2)
        if not valid:
            return False, reason

        # Future: Add dive-code-specific rules here
        # For now, all combinations are valid for all dives

        return True, None
