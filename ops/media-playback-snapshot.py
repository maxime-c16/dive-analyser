"""Read-only PostgreSQL snapshot. Run on backend stdin; emits aggregate JSON only.

ssh diveanalyzer-server 'docker exec -i dive-analyser-backend-1 python -' \
    < ops/media-playback-snapshot.py > snapshot.json
"""
import argparse
import json
from datetime import datetime, timezone, timedelta

from sqlalchemy import text
from app.database import engine


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--since', help='ISO timestamp including timezone; filters job creation and completion')
parser.add_argument('--until', help='ISO timestamp including timezone; exclusive window end')
args = parser.parse_args()

def timestamp(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        parser.error('Window timestamps must include a timezone')
    return result.astimezone(timezone.utc).replace(tzinfo=None)

end = timestamp(args.until) if args.until else datetime.now(timezone.utc).replace(tzinfo=None)
start = timestamp(args.since) if args.since else end - timedelta(hours=24)
if end > datetime.now(timezone.utc).replace(tzinfo=None):
    parser.error('--until must not be in the future')
if start >= end:
    parser.error('--since must precede --until')

QUERIES = {
    "queue": """
        SELECT status, rendition, count(*) AS jobs,
          round(max(extract(epoch FROM (now() AT TIME ZONE 'UTC' - created_at)))::numeric, 1) AS oldest_age_seconds
        FROM media_jobs GROUP BY status, rendition ORDER BY status, rendition
    """,
    "completed_last_24h": """
        SELECT rendition, request_reason, count(*) AS jobs,
          percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM (claimed_at-created_at))) AS queue_p50_seconds,
          percentile_cont(0.95) WITHIN GROUP (ORDER BY extract(epoch FROM (claimed_at-created_at))) AS queue_p95_seconds,
          percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM (completed_at-claimed_at))) AS processing_p50_seconds,
          percentile_cont(0.95) WITHIN GROUP (ORDER BY extract(epoch FROM (completed_at-claimed_at))) AS processing_p95_seconds
        FROM media_jobs WHERE status='ready' AND completed_at >= :since AND completed_at < :until AND (:filter_creation = false OR (created_at >= :since AND created_at < :until))
        GROUP BY rendition, request_reason ORDER BY rendition, request_reason
    """,
    "cached_renditions": """
        SELECT rendition, status, count(*) AS entries, sum(size_bytes) AS bytes
        FROM media_cache_entries GROUP BY rendition, status ORDER BY rendition, status
    """,
    "workers": """
        SELECT active, leasing_enabled, photos_access_status, count(*) AS workers,
          min(extract(epoch FROM (now() AT TIME ZONE 'UTC' - last_seen_at))) AS freshest_heartbeat_age_seconds,
          min(internal_free_bytes) AS minimum_internal_free_bytes,
          min(vault_free_bytes) AS minimum_vault_free_bytes
        FROM media_agents GROUP BY active, leasing_enabled, photos_access_status
    """,
}

with engine.connect() as connection:
    connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
    connection.execute(text("SET LOCAL statement_timeout = '10s'"))
    snapshot = {"captured_at": datetime.now(timezone.utc).isoformat(),
                "window_start_utc": start.isoformat() + 'Z', "window_end_utc": end.isoformat() + 'Z',
                "filter_created_in_window": bool(args.since)}
    for name, query in QUERIES.items():
        snapshot['completed_in_window' if name == 'completed_last_24h' else name] = [dict(row) for row in connection.execute(text(query), {'since': start, 'until': end, 'filter_creation': bool(args.since)}).mappings()]
    connection.rollback()

print(json.dumps(snapshot, indent=2, default=float))
