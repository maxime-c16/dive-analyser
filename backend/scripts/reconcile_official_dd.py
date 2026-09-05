"""Reconcile stored official DD values with the versioned WA formula.

This script is intentionally explicit. Run without ``--execute`` to audit
production first; it never guesses a value for undefined/invalid codes.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from decimal import Decimal
from collections import Counter

from app.database import SessionLocal
from app.models.dive import Dive
from app.services.world_aquatics_dd import OfficialDDUndefined, REFERENCE_ID, calculate_official_dd


def reconcile(*, execute: bool, batch_size: int) -> dict:
    db = SessionLocal()
    changed = unchanged = cleared = undefined = 0
    reasons: Counter[str] = Counter()
    try:
        offset = 0
        while True:
            dives = db.query(Dive).order_by(Dive.id).offset(offset).limit(batch_size).all()
            if not dives:
                break
            for dive in dives:
                try:
                    result = calculate_official_dd(dive.dive_code, dive.height)
                except OfficialDDUndefined as error:
                    undefined += 1
                    reasons[str(error)] += 1
                    if dive.official_dd is not None:
                        cleared += 1
                        if execute:
                            dive.official_dd = None
                            dive.official_dd_assigned_at = datetime.utcnow()
                            dive.official_dd_verification_status = "not_defined"
                            dive.official_dd_source = REFERENCE_ID
                    continue
                if dive.official_dd == result.dd and dive.official_dd_source == REFERENCE_ID:
                    unchanged += 1
                    continue
                changed += 1
                if execute:
                    dive.official_dd = result.dd
                    dive.official_dd_assigned_at = datetime.utcnow()
                    dive.official_dd_verification_status = "official_formula"
                    dive.official_dd_source = REFERENCE_ID
            if execute:
                db.commit()
            offset += len(dives)
        return {
            "execute": execute,
            "changed": changed,
            "unchanged": unchanged,
            "cleared": cleared,
            "undefined": undefined,
            "undefined_reasons": dict(reasons),
            "reference": REFERENCE_ID,
        }
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Commit changes after the audit")
    parser.add_argument("--batch-size", type=int, default=200)
    arguments = parser.parse_args()
    print(reconcile(execute=arguments.execute, batch_size=arguments.batch_size))
