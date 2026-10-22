"""Generate preview DD values from the production engine, never sample values.

Run from any directory:
    python3 backend/scripts/generate_series_dd_fixture.py [--check]

Only the isolated dev fixture imports the result. The application continues to
call the backend formula. No database, credentials or installed app dependencies.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "backend/app/services/world_aquatics_dd.py"
OUTPUT = ROOT / "frontend/e2e/fixtures/series-dd.generated.json"


def engine():
    spec = importlib.util.spec_from_file_location("series_fixture_dd", SOURCE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def candidate_codes():
    codes = set()
    for group in range(1, 5):
        for flying in (0, 1):
            for units in range(12):
                codes.add(f"{group}{flying}{units}")
    for direction in range(1, 5):
        for units in range(10):
            for twists in range(1, 10):
                codes.add(f"5{direction}{units}{twists}")
    for direction in range(1, 4):
        for units in range(10):
            codes.add(f"6{direction}{units}")
            for twists in range(1, 10):
                codes.add(f"6{direction}{units}{twists}")
    return sorted(f"{code}{position}" for code in codes for position in "ABCD")


def generate():
    rules = engine()
    by_height = {}
    for height in ("1m", "3m", "5m", "7.5m", "10m"):
        table = {}
        for code in candidate_codes():
            try:
                table[code] = float(rules.calculate_official_dd(code, height).dd)
            except rules.OfficialDDUndefined:
                pass
        by_height[height] = table
    return {
        "_generated_by": "backend/scripts/generate_series_dd_fixture.py",
        "engine_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "reference_id": rules.REFERENCE_ID,
        "reference_label": rules.REFERENCE_LABEL,
        "by_height": by_height,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    content = json.dumps(generate(), indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text() != content:
            raise SystemExit("Preview DD catalog is stale. Run this script without --check.")
        print("Preview DD catalog matches the backend engine.")
    else:
        OUTPUT.write_text(content)
        print(f"Generated {OUTPUT.relative_to(ROOT)}")
    data = json.loads(content)
    print(", ".join(f"{height}: {len(values)} combinations" for height, values in data["by_height"].items()))


if __name__ == "__main__":
    main()
