"""Backfill only missing official DD values defined by the live rulebook formula.

This is an audit-compatibility repair. Runtime APIs still calculate DD from the
versioned formula rather than trusting this persisted value.
"""

from __future__ import annotations

import argparse
from datetime import datetime

from app.database import SessionLocal
from app.models.dive import Dive
from app.services.difficulty_adjustment import formula_dd
from app.services.world_aquatics_dd import REFERENCE_ID


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Persist the proposed repair")
    parser.add_argument("--dive-code", help="Optional exact canonical code")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        query = db.query(Dive).filter(Dive.official_dd.is_(None))
        if args.dive_code:
            query = query.filter(Dive.dive_code == args.dive_code.upper())
        candidates = query.order_by(Dive.id).all()
        repaired = []
        undefined = 0
        for dive in candidates:
            value = formula_dd(dive)
            if value is None:
                undefined += 1
                continue
            repaired.append((dive, value))

        if args.apply:
            now = datetime.utcnow()
            for dive, value in repaired:
                dive.official_dd = value
                dive.official_dd_source = REFERENCE_ID
                dive.official_dd_verification_status = "official_formula"
                dive.official_dd_assigned_at = now
            db.commit()

        print({
            "mode": "apply" if args.apply else "dry_run",
            "candidates": len(candidates),
            "formula_defined": len(repaired),
            "undefined": undefined,
            "sample": [{"id": dive.id, "dive_code": dive.dive_code, "height": dive.height, "dd": value} for dive, value in repaired[:10]],
        })
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
