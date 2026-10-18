#!/usr/bin/env bash
# Bounded worker run in the deployed backend; installation is explicit.
set -euo pipefail
cd "$(dirname "$0")/.."
if docker compose version >/dev/null 2>&1; then
    compose=(docker compose)
else
    compose=(docker-compose)
fi
"${compose[@]}" exec -T backend python scripts/calendar_alerts_worker.py run
"${compose[@]}" exec -T backend python scripts/calendar_alerts_worker.py status --json
