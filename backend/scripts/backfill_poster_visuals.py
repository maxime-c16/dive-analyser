"""Run with nice -n 15, one bounded batch per invocation; never on request/startup.

PYTHONPATH=backend nice -n 15 python backend/scripts/backfill_poster_visuals.py --limit 8 --after-id 0
Persist returned after_id; stop on scanned=0. Re-scan from 0 after disk recovery.
"""
import argparse
import json
import os
from app.database import SessionLocal
from app.services.poster_visuals import backfill

if __name__ == '__main__':
    os.nice(10)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=8, choices=range(1, 33))
    parser.add_argument('--after-id', type=int, default=0)
    args = parser.parse_args()
    with SessionLocal() as db:
        print(json.dumps(backfill(db, args.limit, max(0, args.after_id))))
