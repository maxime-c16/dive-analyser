#!/usr/bin/env python
"""Calendar alerts worker CLI (Task05). See app/services/calendar_alerts.py.

    run [--batch N]                 one bounded run (schedule every minute)
    status [--json]                 readiness, queues, dead letters (exit 2 if not ready)
    requeue-dead --table outbox|delivery [--id N]   explicit operator retry

Uses the backend's DATABASE_URL (run it inside the backend container) unless
--database-url is given. Never provisions cron itself: scheduling it is an
explicit operational step (docs/design/calendar/TASK_05_RESULT.md).
Exit codes for run: 0 ok/busy/disabled, 1 failure, 2 schema missing.
Output carries counts only: no titles, recipients or endpoints.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

import app.models  # noqa: E402,F401  (register every mapped table)
from app.services import calendar_alerts  # noqa: E402


def factory_for(url):
    if url:
        return sessionmaker(bind=create_engine(url, pool_pre_ping=True), expire_on_commit=False)
    from app.database import SessionLocal
    return SessionLocal


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database-url", default=None)
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run")
    run.add_argument("--batch", type=int, default=calendar_alerts.DEFAULT_BATCH)
    status = sub.add_parser("status")
    status.add_argument("--json", action="store_true")
    requeue = sub.add_parser("requeue-dead")
    requeue.add_argument("--table", choices=("outbox", "delivery"), required=True)
    requeue.add_argument("--id", type=int, default=None)
    args = parser.parse_args(argv)
    factory = factory_for(args.database_url)

    if args.cmd == "run":
        try:
            result = calendar_alerts.run_once(factory, batch=args.batch, push_limit=1)
        except Exception as exc:  # noqa: BLE001 - type only (no bound parameters in logs)
            print(json.dumps({"status": "failed", "error": type(exc).__name__}))
            return 1
        print(json.dumps(result, sort_keys=True))
        return 2 if result["status"] == "schema_missing" else 0
    with factory() as db:
        if args.cmd == "status":
            report = calendar_alerts.health(db)
            if report["schema"]:
                report["dead_letters"] = calendar_alerts.dead_letters(db)
            if args.json:
                print(json.dumps(report, indent=2, sort_keys=True, default=str))
            else:
                print(f"ready={report['ready']} worker={report['worker']} problems={','.join(report['problems']) or '-'}")
                print(f"last_success_at={report.get('last_success_at')} last_error={report.get('last_error')}")
                for name, q in (report.get("queues") or {}).items():
                    print(f"{name}: " + " ".join(f"{k}={v}" for k, v in sorted(q.items())))
                for row in report.get("dead_letters", []):
                    print(f"dead {row['table']} id={row['id']} event={row['event_id']} attempts={row['attempts']} "
                          f"error={row['last_error']}")
            return 0 if report["ready"] else 2
        count = calendar_alerts.requeue_dead(db, args.table, args.id)
        print(json.dumps({"requeued": count}))
        return 0


if __name__ == "__main__":
    sys.exit(main())
