#!/usr/bin/env bash
# Bounded worker run in the deployed backend; installation is explicit.
set -euo pipefail
cd "$(dirname "$0")/.."
if docker compose version >/dev/null 2>&1; then
    compose=(docker compose)
else
    compose=(docker-compose)
fi
# One process per minute: run, then readiness (exit 2 if not ready). Prints a
# single line while healthy, the full status report otherwise.
"${compose[@]}" exec -T backend python scripts/calendar_alerts_worker.py tick
