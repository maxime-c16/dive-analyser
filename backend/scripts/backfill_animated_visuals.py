"""Server-only: PYTHONPATH=backend nice -n 15 python backend/scripts/backfill_animated_visuals.py --limit 4
One bounded batch of stop-motion tiles for proxies still missing one; run until generated=0.
The per-minute media tick (scripts/media_migration.py tick) already does this automatically.
"""
import argparse
import json
import os
from app.database import SessionLocal
from app.services.animated_visuals import backfill

if __name__ == '__main__':
    os.nice(10)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=4, choices=range(1, 17))
    args = parser.parse_args()
    with SessionLocal() as db:
        print(json.dumps(backfill(db, args.limit)))
