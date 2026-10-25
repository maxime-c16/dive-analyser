"""Server-only: PYTHONPATH=backend nice -n 15 python backend/scripts/backfill_animated_visuals.py --limit 4 --after-id 0
One bounded batch; persist after_id, stop when scanned=0. Retry from 0 after disk recovery.
No startup hook, event loop, Mac job or remote fetch.
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
    parser.add_argument('--after-id', type=int, default=0)
    args = parser.parse_args()
    with SessionLocal() as db:
        print(json.dumps(backfill(db, args.limit, max(0, args.after_id))))
