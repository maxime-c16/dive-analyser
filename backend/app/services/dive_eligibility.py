"""Shared eligibility rules for performance-derived features."""

from app.models.dive import Dive


# These codes are recorded as drills/straight jumps, not scored dive attempts.
_STRAIGHT_JUMP_PREFIXES = ("100", "200", "300", "400")


def is_performance_attempt(dive: Dive) -> bool:
    """Return whether an attempt belongs in milestones and pattern analytics."""
    return not bool(dive.is_lineup) and not (dive.dive_code or "").startswith(_STRAIGHT_JUMP_PREFIXES)
