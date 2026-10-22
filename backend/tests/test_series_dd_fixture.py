"""Keep the no-backend series preview on the real DD engine, across heights."""
import json
from pathlib import Path

from scripts.generate_series_dd_fixture import OUTPUT, generate


def test_preview_catalog_is_generated_from_current_engine():
    assert json.loads(OUTPUT.read_text()) == generate()


def test_preview_covers_real_dives_beyond_the_old_sample_and_respects_height():
    data = json.loads(OUTPUT.read_text())["by_height"]
    # Published springboard examples (FFN 2022–2025, Appendix 2).
    assert data["1m"]["101B"] == 1.3
    assert data["3m"]["101B"] == 1.5
    assert data["1m"]["105B"] == 2.6
    assert data["3m"]["105B"] == 2.4
    assert data["3m"]["5152B"] == 3.0
    # This forward 5½ is defined at 10m, not springboard.
    assert data["10m"]["1011C"] == 4.7
    assert "1011C" not in data["3m"]
    # A made-up Free position must not acquire a fallback DD.
    assert "101D" not in data["3m"]
