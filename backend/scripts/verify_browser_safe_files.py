"""Read-only file gate for the Lot A cutover.

Usage (from the live checkout on deb-serv, after the deploy barrier):

    docker compose exec backend python scripts/verify_browser_safe_files.py

Checks every sole-copy row (same scope as the stock migration) still has
its file on disk. Exit 0 when all files are present, 1 otherwise. SELECTs +
filesystem stats only: no row written, no file touched. Output is aggregates
+ entry ids (no paths, no per-clip detail).

See docs/runbooks/media-sole-copy-protection.md §3.
"""

import json
import sys


def main() -> int:
    from app.database import SessionLocal
    from app.services.media_cache import find_missing_sole_copy_files

    db = SessionLocal()
    try:
        result = find_missing_sole_copy_files(db)
    finally:
        db.close()
    checked = result["checked"]
    missing = result["missing"]
    print(json.dumps({
        "checked_sole_copy_rows": checked,
        "missing_files": len(missing),
        "missing": missing[:50],
        "truncated": len(missing) > 50,
    }))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
