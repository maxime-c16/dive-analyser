"""Versioned World Aquatics degree-of-difficulty calculation.

The legacy ``dd_lookups`` table contains a small, manually assembled set of
values.  It is useful as historical data, but it is not a sufficiently
complete or auditable source for assigning an official DD.  This module
implements the component tables published in the FFN French edition of the
World Aquatics Diving Rules, Appendices 1-3 (2022-2025 edition).  The formula is deliberately kept
separate from the database so every result can report its rulebook edition.

The current edition must be re-audited before replacing this reference.  A
calculation that is not defined by the table returns a structured error; it
must never fall back to a heuristic.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re
from typing import Mapping


REFERENCE_ID = "ffn_world_aquatics_diving_2022_2025_appendix_1_3"
REFERENCE_LABEL = "FFN World Aquatics Diving Rules 2022-2025, Appendices 1-3"

_D = Decimal
_CODE = re.compile(r"^(\d{3,4})([ABCD])$")
_HEIGHTS = {"1m", "3m", "5m", "7.5m", "10m"}
_HEIGHT_ALIASES = {"7m": "7.5m", "3mp": "3m"}


@dataclass(frozen=True)
class DDResult:
    dive_code: str
    height: str
    platform_type: str
    dd: Decimal
    components: Mapping[str, Decimal]
    reference_id: str = REFERENCE_ID
    reference_label: str = REFERENCE_LABEL

    def as_dict(self) -> dict:
        return {
            "dive_code": self.dive_code,
            "height": self.height,
            "platform_type": self.platform_type,
            "dd_value": float(self.dd),
            "components": {key: float(value) for key, value in self.components.items()},
            "reference_id": self.reference_id,
            "reference_label": self.reference_label,
        }


class OfficialDDUndefined(ValueError):
    """The reference formula does not define the requested dive."""


def normalize_height(value: str) -> str:
    height = (value or "").strip().lower()
    height = _HEIGHT_ALIASES.get(height, height)
    if height not in _HEIGHTS:
        raise OfficialDDUndefined(f"Unsupported official board height: {value!r}")
    return height


def _band(units: int) -> str:
    if units <= 2:
        return "0_1"
    if units <= 4:
        return "1_5_2"
    if units == 5:
        return "2_5"
    if units <= 7:
        return "3_3_5"
    if units <= 9:
        return "4_4_5"
    if units == 11:
        return "5_5"
    raise OfficialDDUndefined("Somersault count is not defined by the reference")


def _decimal(value: str | float | int) -> Decimal:
    return _D(str(value))


# Position components (B in the official formula).  Keys are body position,
# somersault band, and direction group: 1 Forward, 2 Back, 3 Reverse,
# 4 Inward, 6F Armstand Forward, 6B Armstand Back/Reverse.
_SPRING_POSITION = {
    "C": {
        "0_1": [0.1, 0.1, 0.1, -0.3], "1_5_2": [0, 0, 0, 0.1],
        "2_5": [0, 0.1, 0, 0.2], "3_3_5": [0, 0, 0, 0.3],
        "4_4_5": [0, 0.1, 0.2, 0.4],
    },
    "B": {
        "0_1": [0.2, 0.2, 0.2, -0.2], "1_5_2": [0.1, 0.3, 0.3, 0.3],
        "2_5": [0.2, 0.3, 0.2, 0.5], "3_3_5": [0.3, 0.3, 0.3, 0.6],
        "4_4_5": [0.4, 0.4, 0.5, 0.8],
    },
    "A": {
        "0_1": [0.3, 0.3, 0.3, 0.1], "1_5_2": [0.4, 0.5, 0.6, 0.8],
        "2_5": [0.6, 0.7, 0.6, None], "3_3_5": [None, None, None, None],
        "4_4_5": [None, None, None, None],
    },
    "D": {
        "0_1": [0.1, 0.1, 0.1, -0.1], "1_5_2": [0, -0.1, -0.1, 0.2],
        "2_5": [0, -0.1, -0.2, 0.4], "3_3_5": [0, 0, 0, None],
        "4_4_5": [None, None, None, None],
    },
}
_PLATFORM_POSITION = {
    "C": {
        "0_1": [0.1, 0.1, 0.1, -0.3, 0.1], "1_5_2": [0, 0, 0, 0.1, 0],
        "2_5": [0, 0.1, 0, 0.2, 0.1], "3_3_5": [0, 0, 0, 0.3, 0.2],
        "4_4_5": [0, 0.1, 0.3, 0.4, 0.3], "5_5": [0],
    },
    "B": {
        "0_1": [0.2, 0.2, 0.2, -0.2, 0.3], "1_5_2": [0.1, 0.3, 0.3, 0.3, 0.3],
        "2_5": [0.2, 0.3, 0.2, 0.5, 0], "3_3_5": [0.3, 0.3, 0.3, 0.6, 0.4],
        "4_4_5": [0.4, 0.4, 0.6, 0.7, 0.5], "5_5": [None],
    },
    "A": {
        "0_1": [0.3, 0.3, 0.3, 0.1, 0.4], "1_5_2": [0.4, 0.5, 0.6, 0.8, 0.5],
        "2_5": [0.6, 0.7, 0.6, None, None], "3_3_5": [None, None, None, None, None],
        "4_4_5": [None, None, None, None, None], "5_5": [None],
    },
    "D": {
        "0_1": [0.1, 0.1, 0.1, -0.1, 0], "1_5_2": [0, -0.1, -0.1, 0.2, 0],
        "2_5": [0, -0.1, -0.2, 0.4, 0], "3_3_5": [0, 0, 0, None, None],
        "4_4_5": [None, None, None, None, None], "5_5": [None],
    },
}
_FLY_SPRING = {
    "0_1": [0.2, 0.1, 0.1, 0.4], "1_5_2": [0.2, 0.2, 0.2, 0.5],
    "2_5": [0.3, 0.3, 0.3, 0.7], "3_3_5": [0.4, None, None, None],
}
_FLY_PLATFORM = {
    "0_1": [0.2, 0.1, 0.1, 0.4], "1_5_2": [0.2, 0.2, 0.2, 0.5],
    "2_5": [0.3, 0.3, 0.3, 0.7], "3_3_5": [0.4, None, None, None],
}

_SOMERSAULTS = {
    "1m": {0: 0.9, 1: 1.1, 2: 1.2, 3: 1.6, 4: 2.0, 5: 2.4, 6: 2.7, 7: 3.0, 8: 3.3, 9: 3.8},
    "3m": {0: 1.0, 1: 1.3, 2: 1.3, 3: 1.5, 4: 1.8, 5: 2.2, 6: 2.3, 7: 2.8, 8: 2.9, 9: 3.5},
    "5m": {0: 0.9, 1: 1.1, 2: 1.2, 3: 1.6, 4: 2.0, 5: 2.4, 6: 2.7, 7: 3.0},
    "7.5m": {0: 1.0, 1: 1.3, 2: 1.3, 3: 1.5, 4: 1.8, 5: 2.2, 6: 2.3, 7: 2.8, 8: 3.5, 9: 3.5},
    "10m": {0: 1.0, 1: 1.3, 2: 1.4, 3: 1.5, 4: 1.9, 5: 2.1, 6: 2.5, 7: 2.7, 8: 3.5, 9: 3.5, 11: 4.5},
}


def _value(values: list[float | None], index: int, name: str) -> Decimal:
    try:
        value = values[index]
    except IndexError as exc:
        raise OfficialDDUndefined(f"{name} is not defined by the reference") from exc
    if value is None:
        raise OfficialDDUndefined(f"{name} is not defined by the reference")
    return _decimal(value)


def _direction_index(direction: int, *, platform: bool, armstand: bool) -> int:
    if armstand:
        if direction == 1:
            return 4 if platform else 0
        if direction in (2, 3):
            return 4 if platform else 0
        raise OfficialDDUndefined("Unsupported armstand direction")
    if direction not in (1, 2, 3, 4):
        raise OfficialDDUndefined("Unsupported dive direction")
    return direction - 1


def _position_component(position: str, units: int, direction: int, *, platform: bool, armstand: bool) -> Decimal:
    table = _PLATFORM_POSITION if platform else _SPRING_POSITION
    band = _band(units)
    values = table.get(position, {}).get(band)
    if not values:
        raise OfficialDDUndefined("Position is not defined for this dive")
    if armstand and platform:
        # Platform position tables list armstand forward then armstand back/reverse.
        index = 4 if direction == 1 else 4
        # The reference's armstand values live in the fifth column only for
        # forward; back/reverse values are the same band in a separate formula
        # path below and are intentionally not guessed here.
        if direction in (2, 3):
            arm_values = {
                "C": {"0_1": 0.1, "1_5_2": 0, "2_5": 0.1, "3_3_5": 0.2, "4_4_5": 0.3},
                "B": {"0_1": 0.3, "1_5_2": 0.3, "2_5": 0, "3_3_5": 0.4, "4_4_5": 0.5},
                "A": {"0_1": 0.4, "1_5_2": 0.5},
                "D": {"0_1": 0, "1_5_2": 0, "2_5": 0, "3_3_5": None},
            }
            value = arm_values.get(position, {}).get(band)
            if value is None:
                raise OfficialDDUndefined("Armstand position is not defined for this dive")
            return _decimal(value)
        return _value(values, index, "Armstand position")
    return _value(values, _direction_index(direction, platform=platform, armstand=False), "Position")


def _approach_component(height: str, direction: int, units: int, *, armstand: bool, twists: int) -> Decimal:
    if armstand:
        if twists:
            return _D("0")
        if direction == 1:
            return _D("0.2") if units <= 4 else _D("0.4")
        if direction == 2:
            return _D("0.2") if units <= 1 else _D("0.4")
        if direction == 3:
            return _D("0.3") if units <= 1 else _D("0.5")
        raise OfficialDDUndefined("Unsupported armstand direction")
    if height in ("1m", "3m"):
        table = {
            "1m": {1: (0, 0.5), 2: (0.2, 0.6), 3: (0.3, 0.5), 4: (0.6, 0.5)},
            "3m": {1: (0, 0.3), 2: (0.2, 0.4), 3: (0.3, 0.3), 4: (0.3, 0.3)},
        }
        split = {1: 7, 2: 6, 3: 6, 4: 2}[direction]
        return _decimal(table[height][direction][0 if units <= split else 1])
    table = {
        "5m": {1: (0, 0.5), 2: (0.2, 0.5), 3: (0.3, 0.4, 0.6), 4: (0.6, 0.5)},
        "7.5m": {1: (0, 0.3), 2: (0.2, 0.3), 3: (0.3, 0.4, 0.4), 4: (0.3, 0.3)},
        "10m": {1: (0, 0.2), 2: (0.2, 0.2), 3: (0.3, 0.4, 0.3), 4: (0.3, 0.2)},
    }
    values = table[height][direction]
    if direction == 3:
        index = 0 if units <= 4 else 1 if units <= 6 else 2
    else:
        split = {1: 7, 2: 6, 4: 2}[direction]
        index = 0 if units <= split else 1
    return _decimal(values[index])


def _unnatural_entry(direction: int, units: int, *, armstand: bool, twists: int) -> Decimal:
    if twists:
        return _D("0")
    if armstand:
        if direction == 1:
            return _decimal({1: 0.1, 3: 0.2, 5: 0.3, 7: 0.4, 9: 0.4, 11: 0}.get(units, 0))
        if direction in (2, 3):
            return _decimal({2: 0.1, 4: 0.2, 6: 0.2, 8: 0.3}.get(units, 0))
        return _D("0")
    if direction in (1, 4):
        return _decimal({2: 0.1, 4: 0.2, 6: 0.2, 8: 0.2}.get(units, 0))
    return _decimal({1: 0.1, 3: 0.2, 5: 0.3, 7: 0.4, 9: 0.4, 11: 0}.get(units, 0))


def _fly_component(direction: int, units: int, *, platform: bool) -> Decimal:
    values = (_FLY_PLATFORM if platform else _FLY_SPRING).get(_band(units))
    if not values:
        raise OfficialDDUndefined("Flying position is not defined for this dive")
    return _value(values, direction - 1, "Flying position")


def _twist_component(direction: int, units: int, twists: int, *, armstand: bool, platform: bool) -> Decimal:
    band = "short" if units <= 4 else "long"
    # Half-twist values vary over four somersault ranges.  Other entries
    # follow the columns in the official C. Twists component table.
    half = {
        1: [0.4, 0.4, 0.4, 0.4], 2: [0.2, 0.4, 0, 0],
        3: [0.2, 0.4, 0, 0], 4: [0.2, 0.4, 0.2, 0.4],
        6: [0.4, 0.5, 0.5, 0.4],
    }
    if armstand:
        direction_key = 6 if direction == 1 else 7
        # Use the armstand forward/back values, represented below.
        data = {
            6: {1: [0.4, 0.5, 0.5, 0.4], 2: 1.2, 3: [1.3, 1.3], 4: 1.5, 5: [1.7, 1.7], 6: 1.9, 7: 2.1, 8: 2.3, 9: 2.5},
            7: {1: [0.4, 0.5, 0.5, 0.5], 2: 1.2, 3: [1.3, 1.3], 4: 1.3, 5: [1.7, 1.7], 6: 1.9, 7: 2.1, 8: 2.3, 9: 2.5},
        }[direction_key]
    else:
        data = {
            1: {1: half[1], 2: 0.6, 3: [0.8, 0.8], 4: 1.0, 5: [1.2, 1.2], 6: 1.5, 7: 1.6, 8: 1.9, 9: 2.0},
            2: {1: half[2], 2: 0.4, 3: [0.8, 0.7 if not platform else 0.6], 4: 0.8, 5: [1.2, 1.1 if not platform else 1.0], 6: 1.4, 7: 1.7, 8: 1.8, 9: 2.1},
            3: {1: half[3], 2: 0.4, 3: [0.8, 0.6], 4: 0.8, 5: [1.2, 1.0], 6: 1.4, 7: 1.8, 8: 1.8, 9: 2.1},
            4: {1: half[4], 2: 0.4, 3: [0.8, 0.8], 4: 0.8, 5: [1.2, 1.2], 6: 1.5, 7: 1.6, 8: 1.9, 9: 2.0},
        }[direction]
    value = data.get(twists)
    if isinstance(value, list):
        if twists == 1:
            index = 0 if units <= 2 else 1 if units <= 4 else 2 if units == 5 else 3
        else:
            index = 0 if band == "short" else 1
        return _decimal(value[index])
    if value is None:
        raise OfficialDDUndefined("Twist count is not defined by the reference")
    return _decimal(value)


def calculate_official_dd(dive_code: str, height: str) -> DDResult:
    """Calculate a DD from the versioned official component formula.

    The dive number encodes half-somersault and half-twist units.  A 100-series
    straight jump is deliberately rejected: it is not an analytics dive and
    has no competition DD in this product.
    """
    match = _CODE.fullmatch((dive_code or "").strip().upper())
    if not match:
        raise OfficialDDUndefined("Dive code must be a canonical code such as 103B")
    numeric, position = match.groups()
    group = int(numeric[0])
    if group not in range(1, 7) or numeric.startswith(("0", "100", "200", "300", "400")):
        raise OfficialDDUndefined("Straight jumps and unsupported dive codes have no official DD here")
    official_height = normalize_height(height)
    platform = official_height in {"5m", "7.5m", "10m"}
    if group in (1, 2, 3, 4):
        direction, units, twists, flying, armstand = group, int(numeric[2:]), 0, numeric[1] == "1", False
        if position == "D":
            raise OfficialDDUndefined("Free position is only defined for twisting dives")
    elif group == 5:
        if len(numeric) != 4:
            raise OfficialDDUndefined("Twisting dive codes require four digits")
        direction, units, twists, flying, armstand = int(numeric[1]), int(numeric[2]), int(numeric[3]), False, False
    else:
        if not platform:
            raise OfficialDDUndefined("Armstand dives are only defined on platform")
        direction, units = int(numeric[1]), int(numeric[2])
        twists = int(numeric[3]) if len(numeric) == 4 else 0
        flying, armstand = False, True
    if units not in _SOMERSAULTS[official_height]:
        raise OfficialDDUndefined("Somersault count is not defined for this board height")
    if group == 5:
        if units == 1 and position not in {"A", "B", "C"}:
            raise OfficialDDUndefined("Half-somersault twisting dives require A, B, or C position")
        if units in {2, 3} and position != "D":
            raise OfficialDDUndefined("One and one-and-a-half somersault twisting dives require Free position")
        if units >= 4 and position not in {"B", "C"}:
            raise OfficialDDUndefined("Twisting dives with two or more somersaults require Pike or Tuck")
    if armstand and twists:
        if units <= 4 and position != "D":
            raise OfficialDDUndefined("Armstand twisting dives through two somersaults require Free position")
        if units >= 5 and position not in {"B", "C"}:
            raise OfficialDDUndefined("Armstand twisting dives over two somersaults require Pike or Tuck")
    components = {
        "somersaults": _decimal(_SOMERSAULTS[official_height][units]),
        "position": _position_component(position, units, direction, platform=platform, armstand=armstand),
        "twists": _twist_component(direction, units, twists, armstand=armstand, platform=platform) if twists else _D("0"),
        "approach": _approach_component(official_height, direction, units, armstand=armstand, twists=twists),
        "unnatural_entry": _unnatural_entry(direction, units, armstand=armstand, twists=twists),
    }
    if flying:
        components["flying_position"] = _fly_component(direction, units, platform=platform)
    dd = sum(components.values(), _D("0")).quantize(_D("0.1"))
    return DDResult(dive_code=f"{numeric}{position}", height=official_height, platform_type="platform" if platform else "springboard", dd=dd, components=components)
