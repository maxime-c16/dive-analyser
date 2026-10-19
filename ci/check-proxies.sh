#!/bin/bash
# Parse both real front-door configurations with ephemeral certificates/DNS.
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
scratch=$(mktemp -d)
trap 'rm -f "$scratch/server.key" "$scratch/server.crt"; rmdir "$scratch"' EXIT
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj /CN=ci.invalid \
    -keyout "$scratch/server.key" -out "$scratch/server.crt" >/dev/null 2>&1
# Disposable container only: no published ports, app data or real credentials.
docker run --rm --network none \
    --add-host backend:127.0.0.1 --add-host frontend:127.0.0.1 --add-host adminer:127.0.0.1 \
    -v "$ROOT/nginx/nginx.conf:/etc/nginx/nginx.conf:ro" \
    -v "$ROOT/nginx/conf.d:/etc/nginx/conf.d:ro" \
    -v "$scratch:/etc/nginx/ssl:ro" nginx:alpine nginx -t
docker run --rm --network none \
    --add-host backend:127.0.0.1 --add-host frontend:127.0.0.1 \
    -v "$ROOT/ops/tailscale/nginx.conf:/etc/nginx/conf.d/default.conf:ro" \
    nginx:alpine nginx -t
