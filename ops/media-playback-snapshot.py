"""Read-only PostgreSQL snapshot. Run on backend stdin; emits aggregate JSON only.

ssh diveanalyzer-server 'docker exec -i dive-analyser-backend-1 python -' \
    < ops/media-playback-snapshot.py > snapshot.json
"""
import json
from datetime import datetime, timezone

from sqlalchemy import text
from app.database import engine


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
        FROM media_jobs WHERE status='ready' AND completed_at >= now() AT TIME ZONE 'UTC' - interval '24 hours'
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
    snapshot = {"captured_at": datetime.now(timezone.utc).isoformat(), "window_hours": 24}
    for name, query in QUERIES.items():
        snapshot[name] = [dict(row) for row in connection.execute(text(query)).mappings()]
    connection.rollback()

print(json.dumps(snapshot, indent=2, default=float))
