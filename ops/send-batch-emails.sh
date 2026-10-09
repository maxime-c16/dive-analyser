#!/usr/bin/env bash
# send-batch-emails.sh — flush due deposit-batch emails ("Récupérer mes plongeons").
#
# Cron runs this from ~/dive-analyser (server deploy keeps it current):
#   */15 * * * * /home/mcauchy/dive-analyser/ops/send-batch-emails.sh >> ~/.cache/dive-ci/batch-emails.log 2>&1
#
# Secrets (SMTP_* maintainer app password, DATABASE_URL) live in the
# environment / email env file (mode 600), never in Git, never on argv.
# The script never prints secrets; the sender only logs counts and outcomes.

set -eu

LIVE="${DIVE_LIVE_DIR:-$HOME/dive-analyser}"
EMAIL_ENV="$HOME/.config/diveanalyzer/email.env"
if [ -f "$EMAIL_ENV" ]; then
  # shellcheck disable=SC1090
  set -a
  . "$EMAIL_ENV"
  set +a
fi

# Inside the backend container when available, else any host with DATABASE_URL.
if docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^dive-analyser-backend-1$'; then
  docker exec -i dive-analyser-backend-1 python scripts/send_batch_emails.py --limit 20
else
  cd "$LIVE/backend"
  python3 scripts/send_batch_emails.py --limit 20
fi
