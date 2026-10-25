#!/bin/bash
# Parse both real front-door configurations with ephemeral certificates/DNS.
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
scratch=$(mktemp -d)
trap 'rm -f "$scratch/server.key" "$scratch/server.crt"; rmdir "$scratch"' EXIT
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj /CN=ci.invalid \
    -keyout "$scratch/server.key" -out "$scratch/server.crt" >/dev/null 2>&1
# Disposable container only: no published ports, app data or real credentials.
check_proxy() {
    docker run --rm --network none \
        --add-host backend:127.0.0.1 --add-host frontend:127.0.0.1 --add-host adminer:127.0.0.1 \
        -e MEDIA_SIGNING_SECRET= -e 'NGINX_ENVSUBST_FILTER=^MEDIA_SIGNING_SECRET$' \
        -v "$ROOT/$1:/etc/nginx/nginx.conf:ro" \
        -v "$ROOT/$2:/etc/nginx/conf.d/default.conf:ro" \
        -v "$ROOT/nginx/njs:/etc/nginx/njs:ro" \
        -v "$ROOT/nginx/media-signing.conf.template:/etc/nginx/templates/media-signing.conf.template:ro" \
        -v "$ROOT/nginx/signing-entrypoint.sh:/docker-entrypoint.d/19-media-signing.sh:ro" \
        -v "$scratch:/etc/nginx/ssl:ro" nginx:1.29.4-alpine nginx -t
}
check_proxy nginx/nginx.conf nginx/conf.d/default.conf
check_proxy ops/tailscale/main.conf ops/tailscale/nginx.conf
