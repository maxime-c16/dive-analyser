"""Metric registry loader.

Loads and validates the authoritative metric definitions from
backend/app/data/metric_registry.yaml (Git-versioned).

Usage:
    from app.services.metric_registry import get_registry, get_metric

    metric = get_metric("flight_duration_seconds", "v1")
    print(metric["label"], metric["unit"])
"""

import functools
import os
from pathlib import Path
from typing import Optional

import yaml

_REGISTRY_PATH = Path(__file__).parent.parent / "data" / "metric_registry.yaml"


@functools.lru_cache(maxsize=1)
def _load_registry() -> list[dict]:
    """Load and cache metric definitions from YAML."""
    with open(_REGISTRY_PATH, "r") as f:
        data = yaml.safe_load(f)
    return data.get("metrics", [])


def get_registry() -> list[dict]:
    """Return all metric definitions."""
    return _load_registry()


def get_metric(key: str, version: str = "v1") -> Optional[dict]:
    """Return a metric definition by key and version, or None if not found."""
    for m in get_registry():
        if m["key"] == key and m["version"] == version:
            return m
    return None


def validate_metric_value(key: str, version: str, value: float) -> tuple[bool, str]:
    """Check whether a numeric value is within the metric's valid_range.

    Returns (ok, reason).
    """
    metric = get_metric(key, version)
    if not metric:
        return False, f"Unknown metric: {key}/{version}"
    vr = metric.get("valid_range")
    if not vr or metric.get("value_type") != "numeric":
        return True, "no_range_constraint"
    lo, hi = vr
    if lo is not None and value < lo:
        return False, f"value {value} below minimum {lo}"
    if hi is not None and value > hi:
        return False, f"value {value} above maximum {hi}"
    return True, "ok"
