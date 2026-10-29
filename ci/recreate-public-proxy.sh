#!/bin/bash
# Runtime-only operation. Keep secrets outside the live checkout and stdout.
set -euo pipefail
live="${DIVE_DEPLOY_ROOT:-$HOME/dive-analyser}"
dry_run=0
locked=0
for arg in "$@"; do
    case "$arg" in
        --dry-run) dry_run=1 ;;
        --locked) locked=1 ;;
        *) echo "Unknown proxy option" >&2; exit 2 ;;
    esac
done
cd "$live"
if [ -n "$(git status --porcelain)" ]; then
    echo "Public proxy: live checkout must be clean" >&2
    exit 1
fi
if [ "$dry_run" = 0 ] && [ "$locked" = 0 ]; then
    mkdir -p "$HOME/.cache/dive-ci"
    mkdir "$HOME/.cache/dive-ci/deploy.lock"
    trap 'rmdir "$HOME/.cache/dive-ci/deploy.lock"' EXIT
fi
# This is also the backend's managed media-signing configuration.
if [ -f "$HOME/.config/diveanalyzer/browser-upload.env" ]; then
    set -a
    . "$HOME/.config/diveanalyzer/browser-upload.env"
    set +a
fi
if ! [[ "${MEDIA_SIGNING_SECRET:-}" =~ ^[0-9a-f]{64}$ ]]; then
    echo "Public proxy: missing or invalid MEDIA_SIGNING_SECRET in protected configuration" >&2
    exit 1
fi
compose() { docker-compose -f ops/tailscale/docker-compose.yml -p dive-funnel "$@"; }
# Never print `compose config`: its expanded output contains credentials.
compose config -q
if [ "$dry_run" = 1 ]; then
    echo "Public proxy: configuration valid; would recreate with the backend signing key"
    exit 0
fi
compose up -d --no-deps --force-recreate funnel-proxy
docker exec dive-funnel-funnel-proxy-1 nginx -t
echo "Public proxy recreated with protected signing configuration"
# Server deployment verifies after the backend/frontend swap. A standalone
# recreation verifies immediately, using the helper from the deployed commit.
if [ "$locked" = 0 ]; then
    python3 "$live/ci/check-media-delivery.py" --base http://127.0.0.1:6091 \
        --base https://dive-analyser.tail32dd14.ts.net
fi
