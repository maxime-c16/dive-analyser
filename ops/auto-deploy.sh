#!/bin/bash
# Pull-based CD: deploy origin/master to the live stack once it advances.
#
# Runs from cron on deb-serv (see docs/CD.md). Idempotent and quiet when there
# is nothing to do. Reuses ci/ship.sh's deploy lock, so it can never overlap a
# manual `ci/ship.sh server` or another tick of itself.
#
# A version is only deployed after the release workflow has tagged the commit
# (.github/workflows/release.yml), so the app's "what's new" version is always
# populated. A target without a tag waits for the next tick.

set -uo pipefail

LIVE="${DIVE_LIVE_DIR:-$HOME/dive-analyser}"
LOG="$HOME/.cache/dive-ci/auto-deploy.log"

mkdir -p "$HOME/.cache/dive-ci"

log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*" >>"$LOG"; }

cd "$LIVE" 2>/dev/null || { log "live dir $LIVE missing"; exit 0; }

git fetch --quiet --prune --tags origin 2>/dev/null \
    || { log "fetch failed - cannot reach GitHub"; exit 0; }

target="$(git rev-parse origin/master 2>/dev/null || true)"
current="$(git rev-parse HEAD 2>/dev/null || true)"
[ -n "$target" ] || { log "no origin/master ref"; exit 0; }

if [ "$target" = "$current" ]; then
    exit 0   # already deployed; keep cron logs small
fi

if ! git describe --tags --exact-match --match 'v*' "$target" >/dev/null 2>&1; then
    log "target ${target:0:7} has no release tag yet - waiting for the next tick"
    exit 0
fi

log "deploying ${current:0:7} -> ${target:0:7}"
# Pin the exact tagged SHA we just verified. Without --ref, ship.sh re-resolves
# origin/master and could ship a newer, untagged commit if master advances.
"$LIVE/ci/ship.sh" server --ref "$target"
rc=$?
log "deploy finished (rc=$rc)"
exit 0
