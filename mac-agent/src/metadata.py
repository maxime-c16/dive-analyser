"""
Dive metadata extraction from Photos captions.

Parses dive metadata from photo captions in both legacy and two-phase formats:
- Legacy: "101B P 5m" (single performance score)
- Two-phase: "101B G/P 5m" (phase1/phase2 format, Jan 2026+)

Supports:
- Dive codes (FINA standard: 3-4 digits + A/B/C/D position)
- Open pike shorthand (BO), normalized to B for API compatibility
- Heights (1m, 3m, 5m, 7m, 10m, with optional P suffix for platform)
- Performance levels (F/B/M/G/P single or phase1/phase2)
- Keywords (SYNC, SMACK)
- Modifiers (DB, SD, HU)
- Training partner names
"""

import re
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from datetime import datetime


@dataclass
class DiveMetadata:
    """Extracted dive metadata from caption"""
    dive_code: str  # e.g., "101B"
    height: str  # e.g., "5m"
    performance: Optional[str] = None  # Legacy: F/B/M/G/P
    phase1_performance: Optional[str] = None  # Two-phase: Hurdle+Flight
    phase2_performance: Optional[str] = None  # Two-phase: Opening+Entry
    is_sync: bool = False
    is_smack: bool = False
    person_name: Optional[str] = None
    modifiers: List[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API submission"""
        return {
            "dive_code": self.dive_code,
            "height": self.height,
            "performance": self.performance,
            "phase1_performance": self.phase1_performance,
            "phase2_performance": self.phase2_performance,
            "is_sync": self.is_sync,
            "is_smack": self.is_smack,
            "person_name": self.person_name,
            "modifiers": self.modifiers or [],
        }


@dataclass
class VideoLabel:
    """Non-dive metadata label extracted from a Photos caption."""
    label_type: str
    label_value: str
    raw_caption: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API submission."""
        return {
            "label_type": self.label_type,
            "label_value": self.label_value,
            "raw_caption": self.raw_caption,
        }


def parse_dive_caption(caption: Optional[str]) -> Optional[DiveMetadata]:
    """
    Parse Photos caption for dive metadata.

    Supports both formats:
    - Old: "101B P 5m" (single performance)
    - New: "101B G/P 5m" (phase1/phase2)
    - Two-phase with numeric: "101B 3/4 5m"

    Args:
        caption: Text caption from Photos

    Returns:
        DiveMetadata if caption is valid, None if unparseable

    Examples:
        >>> parse_dive_caption("101B P 5m")
        DiveMetadata(dive_code='101B', height='5m', performance='P', ...)

        >>> parse_dive_caption("5231D G/P 10m SYNC")
        DiveMetadata(dive_code='5231D', height='10m', phase1='G', phase2='P',  is_sync=True, ...)

        >>> parse_dive_caption("invalid text")
        None

        >>> parse_dive_caption("")
        None
    """
    if not caption or not isinstance(caption, str):
        return None

    caption = caption.strip()
    if not caption:
        return None

    try:
        # Split caption into parts
        parts = caption.split()
        if len(parts) < 2:
            return None

        # Parse dive code (first part)
        dive_code = _normalize_dive_code(parts[0])
        if not dive_code:
            return None

        # Parse remaining tokens in flexible order. This supports both:
        # - "103B G/M 1m SD"
        # - "103B SD HU G/M 1m"
        performance = None
        phase1_performance = None
        phase2_performance = None
        height = None
        is_sync = False
        is_smack = False
        person_name = None
        modifiers = []

        for part in parts[1:]:
            part_upper = part.upper()
            part_lower = part.lower()

            if _is_valid_height(part_lower):
                height = part_lower
            elif part_upper in ("SYNC", "SYNCHRO"):
                is_sync = True
            elif part_upper in ("SMACK", "BELLY"):
                is_smack = True
            elif part_upper in _ANNOTATION_TOKENS:
                # Recognized diving annotation (e.g. rip entry): never a person.
                pass
            elif _is_drill_token(part_upper):
                if part_upper not in modifiers:
                    modifiers.append(part_upper)
            elif _is_performance_token(part_upper):
                if "/" in part_upper:
                    try:
                        phase1_str, phase2_str = part_upper.split("/")
                        phase1_performance = _normalize_performance(phase1_str)
                        phase2_performance = _normalize_performance(phase2_str)
                        if not phase1_performance or not phase2_performance:
                            return None
                        performance = None
                    except (ValueError, IndexError):
                        return None
                else:
                    performance = _normalize_performance(part_upper)
            elif _is_person_name(part):
                person_name = part

        if not performance and not (phase1_performance and phase2_performance):
            return None

        if not height:
            height = "1m"

        return DiveMetadata(
            dive_code=dive_code,
            height=height,
            performance=performance,
            phase1_performance=phase1_performance,
            phase2_performance=phase2_performance,
            is_sync=is_sync,
            is_smack=is_smack,
            person_name=person_name,
            modifiers=modifiers,
        )

    except Exception as e:
        # Log parsing error but don't crash
        # print(f"Error parsing caption '{caption}': {e}")
        return None


def parse_video_label(caption: Optional[str]) -> Optional[VideoLabel]:
    """Parse non-dive labels from Photos captions.

    Person-only captions become person labels, not fake dive records.
    """
    if not caption or not isinstance(caption, str):
        return None

    caption = caption.strip()
    if not caption:
        return None

    parts = caption.split()
    if len(parts) != 1:
        return None

    value = parts[0].strip()
    value_upper = value.upper()
    if _is_drill_token(value_upper):
        return VideoLabel(
            label_type="drill",
            label_value=value_upper,
            raw_caption=caption,
        )

    if _is_reserved_label_token(value_upper):
        return None

    if _is_person_name(value):
        return VideoLabel(
            label_type="person",
            label_value=value_upper,
            raw_caption=caption,
        )

    return None


def _normalize_dive_code(code: str) -> Optional[str]:
    """
    Normalize and validate dive code format.

    Open pike is written as BO in some captions, e.g. 201BO.
    This is still the B position, so it is normalized to 201B for the API.
    """
    code = code.upper().strip()

    open_pike_pattern = r"^(\d{3,4})BO$"
    open_pike_match = re.match(open_pike_pattern, code)
    if open_pike_match:
        return f"{open_pike_match.group(1)}B"

    if _is_valid_dive_code(code):
        return code

    return None


def _is_valid_dive_code(code: str) -> bool:
    """
    Validate FINA dive code format.

    Format: 3-4 digits followed by A/B/C/D position

    Examples:
        "101B" → True
        "201BO" → False here; normalized by _normalize_dive_code
        "5231D" → True
        "0101B" → False (4 leading digits, valid but unusual)
        "10B" → False (only 2 digits)
        "101E" → False (E not valid position)
        "101b" → True (after uppercase conversion)
    """
    pattern = r"^\d{3,4}[A-D]$"
    return bool(re.match(pattern, code))


def _is_valid_height(height: str) -> bool:
    """
    Validate height format.

    Format: 1-2 digit number + 'm' + optional 'p' suffix (for platform)

    Examples:
        "1m" → True
        "5m" → True
        "10m" → True
        "5mp" → True (platform)
        "5mP" → True (case-insensitive)
        "15m" → False (max is 10m)
        "0m" → False (must be positive)
        "5" → False (missing 'm')
    """
    pattern = r"^(1|3|5|7|10)m[p]?$"
    return bool(re.match(pattern, height.lower()))


def _normalize_performance(perf: str) -> Optional[str]:
    """
    Normalize performance score to letter format.

    Accepts:
    - Letter: F, B, M, G, P (case-insensitive)
    - Number: 0-4 maps to F, B, M, G, P

    Examples:
        "G" → "G"
        "g" → "G"
        "3" → "G" (numeric score)
        "4" → "P"
        "X" → None (invalid)
        "5" → None (out of range)
    """
    perf = perf.upper().strip()

    # Map numbers to letters
    number_map = {"0": "F", "1": "B", "2": "M", "3": "G", "4": "P"}
    if perf in number_map:
        return number_map[perf]

    # Accept letters directly
    if perf in ("F", "B", "M", "G", "P"):
        return perf

    # Invalid
    return None


def _is_performance_token(text: str) -> bool:
    """Return True if token looks like a single or two-phase score."""
    if "/" in text:
        try:
            phase1, phase2 = text.split("/")
        except ValueError:
            return False
        return bool(_normalize_performance(phase1) and _normalize_performance(phase2))
    return bool(_normalize_performance(text))


def _is_drill_token(text: str) -> bool:
    """Return True for shorthand drill markers that are not people."""
    return text in {"SD", "DB", "HU"}


# Entry-quality / one-token diving annotations that must never become a person
# (DIVER_ID_19_PHANTOM root cause: "RIP" parsed as a diver name and auto-created).
_ANNOTATION_TOKENS = {"RIP"}


def _is_reserved_label_token(text: str) -> bool:
    """Return True for one-token captions that should not become people."""
    return text in {"SD", "DB", "HU", "SYNC", "SYNCHRO", "SMACK", "BELLY", "RIP"}


def _is_person_name(text: str) -> bool:
    """
    Check if text looks like a person's name.

    Rules:
    - Starts with capital letter
    - 2-20 characters long
    - Contains only letters (hyphens/apostrophes allowed)

    Note: unlike the historical docstring, ALL-CAPS names are accepted
    ("TOM", "PAUL", "FANNY", ...) because production captions are typed in
    caps. Non-name diving annotations (RIP, SMACK, SYNC, ...) are excluded
    by the reserved/keyword token checks before this predicate is reached.

    Examples:
        "John" → True
        "Mary-Jane" → True
        "O'Connor" → True
        "TOM" → True (production captions are all caps)
        "JOHN" → True
        "john" → False (lowercase)
        "J" → False (too short)
        "A123" → False (contains number)
        "RIP" → False (reserved annotation token)
    """
    if not text or len(text) < 2 or len(text) > 20:
        return False

    # Must start with capital
    if not text[0].isupper():
        return False

    # Remaining must be letters, hyphens, or apostrophes
    for char in text[1:]:
        if not (char.isalpha() or char in ("-", "'")):
            return False

    return True


# Test cases demonstrating parser functionality
if __name__ == "__main__":
    test_cases = [
        # Legacy format
        ("101B M", "101B with medium performance (legacy)"),
        ("101B P 5m", "101B with perfect, 5m height"),
        ("5231D G", "5231D with good, default 1m"),

        # Two-phase format
        ("101B G/P 5m", "101B with good flight, perfect entry"),
        ("201C P/M 3m", "201C with perfect flight, medium entry"),
        ("5231D 3/4 10m", "5231D with numeric scores (G/P)"),

        # With keywords
        ("101B P 5m SYNC", "Synchronized dive"),
        ("101B M SMACK", "Belly flop"),
        ("101B G 5m SYNC SMACK", "Both keywords"),

        # With person name
        ("101B P John", "Training with John"),
        ("5231D G/M 5m Mary-Jane", "Two-phase with partner"),

        # Invalid/edge cases
        ("", "Empty caption"),
        ("invalid text", "Non-dive caption"),
        ("101E P 5m", "Invalid position (E)"),
        ("101B P 15m", "Invalid height (15m)"),
    ]

    print("Caption Parser Test Results:\n")
    for caption, description in test_cases:
        result = parse_dive_caption(caption)
        status = "✓" if result else "✗"
        print(f"{status} '{caption}' → {description}")
        if result:
            print(f"  Details: {result}\n")
