#!/usr/bin/env bash
# One historical media-migration tick in the deployed backend container.
# Scheduled by ops/systemd/dive-media-migration.timer (installation is an
# explicit operational step: docs/design/media-global-migration.md).
# A tick is bounded and idempotent; all state lives in Postgres, so a missed
# or failed tick (deploy, reboot, container restart) is simply retried by the
# next one. flock prevents overlapping ticks on this host; the DB advisory
# lock prevents overlap from anywhere else.
set -euo pipefail
cd "$(dirname "$0")/.."
if docker compose version >/dev/null 2>&1; then
    compose=(docker compose)
else
    compose=(docker-compose)
fi
exec flock -n -E 0 /tmp/dive-media-migration.lock \
    "${compose[@]}" exec -T backend python scripts/media_migration.py tick
