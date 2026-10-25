#!/usr/bin/env python
"""Historical web-package migration CLI (docs/design/media-global-migration.md).

Run inside the backend container (uses its DATABASE_URL):

    inventory [--json]                 read-only exact classification, no writes
    start --budget-gib N [--queue-depth 2] [--priority 70] [--admission-cap N]
    tick                               one bounded controller pass (timer, every minute),
                                       then copy up to 40 durable posters into the grid cache
    status [--json]                    run, items, gates, budget, throughput, failures
    pause --reason TEXT                stop admitting; withdraw not-yet-leased jobs
    resume                             admit again (gates still apply)
    set [--budget-gib N] [--queue-depth N] [--admission-cap N | --no-admission-cap]
    retry-item --video-uuid U --reason TEXT    explicit retry of ONE failed item
    cancel --reason TEXT               close the run (history kept)

Output carries counts, ids and reasons only: no URLs, credentials or tokens.
Exit codes: 0 ok, 1 failure, 2 refused (operator error / no run).
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.models  # noqa: E402,F401  (register every mapped table)
from app.services import media_migration as mm  # noqa: E402

GIB = 1024**3


def _materialize_posters(factory):
    """Durable posters -> local grid cache (bounded; never fails the tick)."""
    from app.services.durable_poster_cache import materialize_durable_posters

    with factory() as db:
        try:
            return materialize_durable_posters(db)
        except Exception as exc:  # noqa: BLE001 - type only, never bound values
            db.rollback()
            return {"status": "failed", "error": type(exc).__name__}


def _factory(url):
    if url:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        return sessionmaker(bind=create_engine(url, pool_pre_ping=True), expire_on_commit=False)
    from app.database import SessionLocal

    return SessionLocal


def _gib(value):
    return None if value is None else int(float(value) * GIB)


def _print_status(report):
    run = report.get("run")
    if run is None:
        print(f"no open run (last={report.get('last_run_id')} {report.get('last_run_status')})")
        return
    print(f"run={run['id']} status={run['status']} pause_reason={run['pause_reason'] or '-'} "
          f"transform={run['transform_version']} priority={run['priority']} "
          f"depth={run['queue_depth']} max_attempts={run['max_attempts']} "
          f"admitted={run['admitted_jobs']} cap={run['admission_cap']}")
    print("items: " + " ".join(f"{k}={v}" for k, v in report["items"].items())
          + f" total={report['items_total']} remaining={report['remaining']} done={report['done']}")
    pub, bud, thr = report["published"], report["budget"], report["throughput"]
    print(f"published objects={pub['objects']} bytes={pub['bytes']} | accounted={bud['accounted_bytes']} "
          f"budget={bud['budget_bytes']} remaining={bud['remaining_bytes']}")
    print(f"throughput 1h={thr['completed_last_hour']} 24h={thr['completed_last_day']} eta_h={thr['eta_hours']}")
    print(f"admitting={report['admitting']} last_tick_at={run['last_tick_at']}")
    for gate in report["gates"]:
        detail = {k: v for k, v in gate.items() if k not in ("gate", "ok")}
        print(f"  gate {gate['gate']}: {'ok' if gate['ok'] else 'BLOCKED'} {json.dumps(detail, default=str)}")
    for job in report["active_jobs"]:
        print(f"  job {job['job_id']} {job['status']} {job['progress']}% attempts={job['attempts']}/"
              f"{job['max_attempts']} p={job['priority']} by={job['claimed_by']}")
    for row in report["blocked_or_failed_by_reason"]:
        print(f"  {row['status']} reason={row['reason']} count={row['count']}")
    for row in report["recent_failures"]:
        print(f"  failed {row['video_uuid']} job={row['job_id']} reason={row['reason']} error={row['error']}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database-url", default=None)
    sub = parser.add_subparsers(dest="cmd", required=True)
    inv = sub.add_parser("inventory")
    inv.add_argument("--json", action="store_true")
    inv.add_argument("--limit", type=int, default=None, help="classify only the first N clips (sample)")
    start = sub.add_parser("start")
    start.add_argument("--budget-gib", type=float, required=True)
    start.add_argument("--queue-depth", type=int, default=mm.DEFAULT_QUEUE_DEPTH)
    start.add_argument("--priority", type=int, default=mm.DEFAULT_PRIORITY)
    start.add_argument("--admission-cap", type=int, default=None)
    start.add_argument("--created-by", default="operator")
    sub.add_parser("tick")
    status = sub.add_parser("status")
    status.add_argument("--json", action="store_true")
    pause = sub.add_parser("pause")
    pause.add_argument("--reason", required=True)
    sub.add_parser("resume")
    cancel = sub.add_parser("cancel")
    cancel.add_argument("--reason", required=True)
    setp = sub.add_parser("set")
    setp.add_argument("--budget-gib", type=float, default=None)
    setp.add_argument("--queue-depth", type=int, default=None)
    cap = setp.add_mutually_exclusive_group()
    cap.add_argument("--admission-cap", type=int, default=None)
    cap.add_argument("--no-admission-cap", action="store_true")
    retry = sub.add_parser("retry-item")
    retry.add_argument("--video-uuid", required=True)
    retry.add_argument("--reason", required=True)
    args = parser.parse_args(argv)

    factory = _factory(args.database_url)
    with factory() as db:
        try:
            if args.cmd == "inventory":
                report = mm.inventory(db, limit=args.limit)
                db.rollback()
                if args.json:
                    print(json.dumps(report, indent=2, sort_keys=True))
                else:
                    print(f"clips={report['clips']} transform={report['transform_version']}")
                    for name, count in report["classes"].items():
                        print(f"  {name}: {count}")
                    print(f"source_bytes_to_convert={report['source_bytes_to_convert']} "
                          f"estimated_worst_case_bytes={report['estimated_worst_case_bytes']}")
                return 0
            if args.cmd == "status":
                report = mm.status_report(db)
                db.rollback()
                if args.json:
                    print(json.dumps(report, indent=2, sort_keys=True, default=str))
                else:
                    _print_status(report)
                return 0 if report.get("run") else 2
            if args.cmd == "tick":
                result = mm.tick(db)
                db.commit()
                result["posters"] = _materialize_posters(factory)
                print(json.dumps(result, sort_keys=True, default=str))
                return 0
            if args.cmd == "start":
                run = mm.start_run(db, budget_bytes=_gib(args.budget_gib), queue_depth=args.queue_depth,
                                   priority=args.priority, admission_cap=args.admission_cap,
                                   created_by=args.created_by)
                db.commit()
                print(json.dumps({"run_id": run.id, "status": run.status,
                                  "transform_version": run.transform_version}))
                return 0
            if args.cmd == "pause":
                result = mm.pause_run(db, args.reason)
            elif args.cmd == "resume":
                result = mm.resume_run(db)
            elif args.cmd == "cancel":
                result = mm.cancel_run(db, args.reason)
            elif args.cmd == "set":
                result = mm.update_run(db, budget_bytes=_gib(args.budget_gib), queue_depth=args.queue_depth,
                                       admission_cap=args.admission_cap,
                                       clear_admission_cap=args.no_admission_cap)
            else:
                result = mm.retry_item(db, args.video_uuid, args.reason)
            db.commit()
            print(json.dumps(result, sort_keys=True, default=str))
            return 0
        except mm.MigrationError as exc:
            db.rollback()
            print(json.dumps({"status": "refused", "error": str(exc)}))
            return 2
        except Exception as exc:  # noqa: BLE001 - type only, never bound values
            db.rollback()
            print(json.dumps({"status": "failed", "error": type(exc).__name__}))
            return 1


if __name__ == "__main__":
    sys.exit(main())
