#!/usr/bin/env python3
"""Require a complete pytest run with zero failures; never accept stale results."""
import json
import sys
from pathlib import Path


def check(result_path, process_status):
    result = json.loads(Path(result_path).read_text())
    if process_status not in (0, 1) or result["exitstatus"] != process_status:
        raise ValueError(f"pytest infrastructure error (exit {process_status})")
    outcomes = result["outcomes"]
    if not result["collected"] or len(outcomes) != result["collected"]:
        raise ValueError("pytest did not finish every collected test")
    failed = {name for name, state in outcomes.items() if state["failed"]}
    passed = {name for name, state in outcomes.items()
              if state["passed"] and not state["failed"] and not state["skipped"]}
    if bool(failed) != bool(process_status):
        raise ValueError("pytest exit code disagrees with test outcomes")
    for name in sorted(failed):
        print(f"FAILURE: {name}", file=sys.stderr)
    print(f"{len(passed)} passed, {len(failed)} failed, "
          f"{sum(s['skipped'] for s in outcomes.values())} skipped")
    return bool(failed)


if __name__ == "__main__":
    try:
        sys.exit(check(sys.argv[1], int(sys.argv[2])))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"CI result rejected: {exc}", file=sys.stderr)
        sys.exit(1)
