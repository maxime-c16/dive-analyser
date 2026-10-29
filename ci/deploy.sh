#!/bin/bash
# dive-analyser CD: build, swap, verify, roll back on failure.
#
# Safety model
# ------------
#   1. Refuse to deploy a dirty tree. Deploying uncommitted files is how you
#      end up unable to explain what is running.
#   2. Refuse to run without a green gate (skip with --skip-gate for hotfixes,
#      which is then reported loudly). ci/ship.sh skips it quietly only when
#      GitHub's required gate already passed on this exact tree, and says so
#      through DIVE_GATE_PROOF.
#   3. Tag the incoming image with the git SHA, remember the *currently running*
#      image id, and only then swap. If health checks fail, put the old image
#      back and re-verify before reporting failure.
#   4. Wait for real HTTP 200s from the backend and from nginx, not merely for
#      the container to exist.
#
# Note the live stack serves through nginx on 6443 with a 301 from :80, so the
# existing ./health-check.sh reports a false failure against port 6090. This
# script checks the real TLS endpoints instead.
#
# Usage:
#   ci/deploy.sh [--skip-gate] [--frontend-only|--backend-only] [--dry-run]

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=ci/lib.sh
. "$SCRIPT_DIR/lib.sh"

# Two distinct roots, deliberately not conflated:
#   ROOT        the source tree we build from and check for cleanliness
#   COMPOSE_DIR the deployment directory holding docker-compose.yml
# In normal use (via ci/ship.sh) both are the live checkout. COMPOSE_DIR
# defaults to the live dir rather than ROOT so that running this from a
# worktree can never bring up a second compose project named after it. Note
# the backend bind-mounts ./backend from COMPOSE_DIR, so deploy through
# ci/ship.sh, which checks out the commit there first.
ROOT="${DIVE_SOURCE_ROOT:-$(ci_repo_root)}"
COMPOSE_DIR="${DIVE_DEPLOY_ROOT:-/home/mcauchy/dive-analyser}"
COMPOSE="${DIVE_COMPOSE_CMD:-docker-compose}"
PROJECT="${DIVE_COMPOSE_PROJECT:-dive-analyser}"
FRONTEND_IMAGE="${DIVE_FRONTEND_IMAGE:-dive-analyser-frontend}"
BACKEND_IMAGE="${DIVE_BACKEND_IMAGE:-dive-analyser-backend}"

# Overridable so the pipeline can be rehearsed against a sandbox stack instead
# of the live one.
BACKEND_HEALTH="${DIVE_BACKEND_HEALTH:-http://127.0.0.1:6002/api/v1/health}"
FRONTEND_HEALTH="${DIVE_FRONTEND_HEALTH:-https://127.0.0.1:6443/health}"
PROXY_API_HEALTH="${DIVE_PROXY_API_HEALTH:-https://127.0.0.1:6443/api/v1/health}"
HEALTH_RETRIES="${DIVE_HEALTH_RETRIES:-90}"
FUNNEL_PROXY="${DIVE_FUNNEL_PROXY:-dive-funnel-funnel-proxy-1}"
FUNNEL_LOGIN="${DIVE_FUNNEL_LOGIN:-http://127.0.0.1:6091/login}"
FUNNEL_API_PROBE="${DIVE_FUNNEL_API_PROBE:-http://127.0.0.1:6091/api/v1/auth/me}"

SKIP_GATE=0
ONLY=""
DRY_RUN=0

for arg in "$@"; do
    case "$arg" in
        --skip-gate)    SKIP_GATE=1 ;;
        --frontend-only) ONLY="frontend" ;;
        --backend-only)  ONLY="backend" ;;
        --dry-run)       DRY_RUN=1 ;;
        -h|--help)       sed -n '2,20p' "$0"; exit 0 ;;
        *) ci_die "unknown option: $arg" ;;
    esac
done

sha="$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)"
cd "$ROOT" || ci_die "cannot cd to $ROOT"

printf '%sdive-analyser deploy%s  sha=%s branch=%s\n' \
    "$C_BLU" "$C_OFF" "$sha" "$(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null)"

# ------------------------------------------------------------ 1. safety

if [ -n "$(git -C "$ROOT" status --porcelain 2>/dev/null)" ]; then
    ci_die "working tree is dirty — commit or stash before deploying
    (an uncommitted deploy cannot be rolled back to a known state)"
fi

if [ ! -f "$COMPOSE_DIR/docker-compose.yml" ]; then
    ci_die "compose file not found at $COMPOSE_DIR/docker-compose.yml
    set DIVE_DEPLOY_ROOT to the deployment directory"
fi

if [ "$DRY_RUN" -eq 1 ]; then
    ci_warn "DRY RUN — no changes will be made"
fi

# ------------------------------------------------------------ 2. gate

# A backend-only deploy ships no frontend code, so it skips the frontend tier.
gate_tiers="fast frontend"
[ "$ONLY" = "backend" ] && gate_tiers="fast"

if [ "$SKIP_GATE" -eq 0 ]; then
    ci_step "gate ($gate_tiers)"
    # shellcheck disable=SC2086
    if ! ci_run gate "$ROOT/ci/gate.sh" $gate_tiers; then
        ci_die "gate failed — not deploying"
    fi
    ci_ok "gate green"
elif [ -n "${DIVE_GATE_PROOF:-}" ]; then
    ci_step "gate"
    ci_ok "already verified on GitHub: $DIVE_GATE_PROOF"
else
    ci_warn "skipping gate (--skip-gate): deploying WITHOUT CI verification"
fi

# ------------------------------------------------- 3. capture rollback state

compose() { ( cd "$COMPOSE_DIR" && $COMPOSE "$@" ); }

prev_frontend_id="$(docker image inspect "$FRONTEND_IMAGE:latest" \
    --format '{{.Id}}' 2>/dev/null || true)"
prev_backend_id="$(docker image inspect "$BACKEND_IMAGE:latest" \
    --format '{{.Id}}' 2>/dev/null || true)"

[ -n "$prev_frontend_id" ] && ci_log "current frontend image: ${prev_frontend_id:7:12}"
[ -n "$prev_backend_id" ]  && ci_log "current backend image:  ${prev_backend_id:7:12}"

# Both nginx front doors (LAN :6443 and the Tailscale Funnel proxy) resolve
# upstream container addresses at startup, so they must be reloaded whenever
# backend/frontend are recreated or they keep proxying to stale IPs.
# Returns non-zero if a running proxy could not be reloaded.
reload_proxies() {
    local c rc=0
    for c in dive-analyser-nginx-1 "$FUNNEL_PROXY"; do
        [ "$(docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null)" = "true" ] || continue
        if docker exec "$c" nginx -t >/dev/null 2>&1 && docker exec "$c" nginx -s reload >/dev/null 2>&1; then
            ci_ok "reloaded $c"
        else
            ci_err "could not reload $c — check: docker exec $c nginx -t"
            rc=1
        fi
    done
    return "$rc"
}

funnel_running() {
    [ "$(docker inspect -f '{{.State.Running}}' "$FUNNEL_PROXY" 2>/dev/null)" = "true" ]
}

# The public proxy gates /api behind a session, so an anonymous probe should
# get 401 from the backend; 502/504 means nginx still targets a stale address.
wait_funnel_api() {
    local code deadline=$(( $(date +%s) + HEALTH_RETRIES ))
    while [ "$(date +%s)" -lt "$deadline" ]; do
        code="$(curl -s -o /dev/null -w '%{http_code}' -m 5 "$FUNNEL_API_PROBE" 2>/dev/null)"
        case "$code" in
            200|401) ci_ok "public proxy -> backend answered $code ($FUNNEL_API_PROBE)"; return 0 ;;
        esac
        sleep 3
    done
    ci_err "public proxy -> backend never answered 200/401 (last: ${code:-none})"
    return 1
}

# Restores the previous images and EXITS non-zero: a deploy that needed a
# rollback is a failed deploy, whether or not the rollback itself succeeded.
rollback() {
    local why="$1"
    ci_err "deploy verification FAILED ($why) — rolling back"
    if [ -n "$prev_frontend_id" ] && [ "$ONLY" != "backend" ]; then
        docker tag "$prev_frontend_id" "$FRONTEND_IMAGE:latest" 2>/dev/null
        compose up -d --no-deps --force-recreate frontend >/dev/null 2>&1
        ci_log "rolled frontend back to ${prev_frontend_id:7:12}"
    fi
    if [ -n "$prev_backend_id" ] && [ "$ONLY" != "frontend" ]; then
        docker tag "$prev_backend_id" "$BACKEND_IMAGE:latest" 2>/dev/null
        compose up -d --no-deps --force-recreate backend >/dev/null 2>&1
        ci_log "rolled backend back to ${prev_backend_id:7:12}"
    fi
    local recovered=1
    reload_proxies || recovered=0
    # Confirm recovery on whatever this deploy actually touched, rather than
    # always on the backend.
    if [ "$ONLY" != "frontend" ]; then
        ci_wait_http "$BACKEND_HEALTH" "backend(rollback)" "$HEALTH_RETRIES" \
            || { ci_err "rollback did NOT restore a healthy backend — manual intervention needed"; recovered=0; }
    fi
    if [ "$ONLY" != "backend" ]; then
        ci_wait_http "$FRONTEND_HEALTH" "frontend(rollback)" "$HEALTH_RETRIES" \
            || { ci_err "rollback did NOT restore a serving frontend — manual intervention needed"; recovered=0; }
    fi
    if [ "$recovered" -eq 1 ]; then
        ci_warn "rollback complete — the previous version is serving again"
    else
        ci_err "rollback incomplete — manual intervention needed"
    fi
    exit 1
}

# ------------------------------------------------------------ 4. build

if [ "$ONLY" != "backend" ]; then
    ci_step "build: frontend production image"
    if [ "$DRY_RUN" -eq 1 ]; then
        ci_warn "would run: docker build -f frontend/Dockerfile.deploy -t $FRONTEND_IMAGE:sha-$sha frontend"
    else
        # The daemon's layer cache once shipped a stale frontend bundle
        # (COPY/npm-run-build cache-hit on changed sources), so /register +
        # /account 404'd into the login redirect while the deploy reported
        # success. Health checks cannot catch content staleness. The
        # Dockerfile therefore fences the cache with APP_SHA: `npm ci` is
        # reused while the lockfile is unchanged, but sources and the bundle
        # are rebuilt for every commit. APP_SHA must stay the full commit SHA.
        ci_run build-frontend docker build \
            -f "$ROOT/frontend/Dockerfile.deploy" \
            -t "$FRONTEND_IMAGE:sha-$sha" \
            --label "dive.analyser/sha=$sha" \
            --build-arg "APP_SHA=$(git -C "$ROOT" rev-parse HEAD)" \
            "$ROOT/frontend" \
            || ci_die "frontend image build failed — previous images untouched"
        ci_ok "frontend image built ($FRONTEND_IMAGE:sha-$sha)"
    fi
fi

if [ "$ONLY" != "frontend" ]; then
    ci_step "build: backend image"
    if [ "$DRY_RUN" -eq 1 ]; then
        ci_warn "would run: docker build -f backend/Dockerfile -t $BACKEND_IMAGE:sha-$sha backend"
    else
        ci_run build-backend docker build \
            -f "$ROOT/backend/Dockerfile" \
            -t "$BACKEND_IMAGE:sha-$sha" \
            --label "dive.analyser/sha=$sha" \
            "$ROOT/backend" \
            || ci_die "backend image build failed — previous images untouched"
        ci_ok "backend image built ($BACKEND_IMAGE:sha-$sha)"
    fi
fi

if [ "$DRY_RUN" -eq 1 ]; then
    ci_step "dry run complete — nothing was deployed"
    exit 0
fi

# Move :latest only once every requested build succeeded, so a failed build
# can never leave a half-new :latest behind as the next rollback target.
[ "$ONLY" != "backend" ]  && docker tag "$FRONTEND_IMAGE:sha-$sha" "$FRONTEND_IMAGE:latest"
[ "$ONLY" != "frontend" ] && docker tag "$BACKEND_IMAGE:sha-$sha" "$BACKEND_IMAGE:latest"

# ------------------------------------------------------------ 5. swap

# Load the same protected signing configuration as the backend before any
# public-proxy recreation; missing credentials must stop deployment visibly.
if funnel_running; then
    bash "$ROOT/ci/recreate-public-proxy.sh" --locked \
        || rollback "public proxy configuration/recreation failed"
fi

ci_step "deploy: recreate containers"
svc_list=""
[ "$ONLY" != "backend" ]  && svc_list="$svc_list frontend"
[ "$ONLY" != "frontend" ] && svc_list="$svc_list backend"

compose up -d --no-deps --force-recreate $svc_list \
    || rollback "compose up failed"
ci_ok "containers recreated: $svc_list"
reload_proxies || rollback "nginx proxy reload failed"

# ------------------------------------------------------ 6. verify + rollback

ci_step "verify"
sleep 3   # let the services bind before the first probe

# Only assert on what this deploy actually changed: a --frontend-only deploy
# must not fail because the backend happens to be down, and vice versa.
if [ "$ONLY" != "frontend" ]; then
    ci_wait_http "$BACKEND_HEALTH" "backend direct" "$HEALTH_RETRIES" \
        || rollback "backend health never returned 200"

    ci_wait_http "$PROXY_API_HEALTH" "nginx -> backend API" "$HEALTH_RETRIES" \
        || rollback "API not reachable through nginx"
fi

if [ "$ONLY" != "backend" ]; then
    ci_wait_http "$FRONTEND_HEALTH" "frontend serving" "$HEALTH_RETRIES" \
        || rollback "frontend not serving"
fi

# Public Tailscale Funnel path (only when that proxy is deployed on this host).
if funnel_running; then
    if [ "$ONLY" != "frontend" ]; then
        wait_funnel_api || rollback "API not reachable through the public proxy"
    fi
    if [ "$ONLY" != "backend" ]; then
        ci_wait_http "$FUNNEL_LOGIN" "public proxy -> frontend" "$HEALTH_RETRIES" \
            || rollback "frontend not reachable through the public proxy"
    fi
fi

# Verify bytes, not just an API 200. Only LAN loopback permits its
# self-signed certificate; the public probe validates external TLS/routing.
media_bases=(--base "https://127.0.0.1:6443")
if funnel_running; then
    media_bases+=(--base "http://127.0.0.1:6091" --base "https://dive-analyser.tail32dd14.ts.net")
fi
python3 "$ROOT/ci/check-media-delivery.py" "${media_bases[@]}" \
    || rollback "signed media delivery failed"

compose ps 2>/dev/null | sed 's/^/    /' || true

# Publish only after every health check succeeded. The API reads this file
# from its existing persistent media-cache volume, never from source files.
# Rollbacks leave the previous manifest intact; successful explicit rollbacks
# rebuild the catalog from the SHA labels of the services actually running.
ci_step "publish: what's new"
updates_tmp="$(mktemp "$(ci_cache_dir)/release-notes.XXXXXX")" || rollback "cannot stage update manifest"
frontend_sha="$(docker inspect dive-analyser-frontend-1 --format '{{index .Config.Labels "dive.analyser/sha"}}')"
backend_sha="$(docker inspect dive-analyser-backend-1 --format '{{index .Config.Labels "dive.analyser/sha"}}')"
if ! python3 "$ROOT/ci/release-notes.py" build --root "$ROOT" \
    --frontend "$frontend_sha" --backend "$backend_sha" --output "$updates_tmp"; then
    unlink "$updates_tmp"
    rollback "cannot build update manifest"
fi
# docker cp owns the staged file as root; the API runs as diver and must read it.
chmod 644 "$updates_tmp" || rollback "cannot set update manifest permissions"
if ! docker cp "$updates_tmp" dive-analyser-backend-1:/app/media-cache/release-notes.pending.json; then
    unlink "$updates_tmp"
    rollback "cannot stage update manifest in backend"
fi
unlink "$updates_tmp"
docker exec dive-analyser-backend-1 python -c \
    'import os; os.replace("/app/media-cache/release-notes.pending.json", "/app/media-cache/release-notes.json")' \
    || rollback "cannot publish update manifest"
ci_ok "update catalog published"

# ------------------------------------------------------------ 7. tidy up

# Keep the previous image as a rollback target, drop older build tags so the
# 172 GB free disk does not creep away under us.
if [ "$DRY_RUN" -eq 0 ]; then
    stale="$(docker images -q "$FRONTEND_IMAGE" -f 'label=dive.analyser/sha' 2>/dev/null | head -n -2 || true)"
    for img in $stale; do docker image rm -f "$img" >/dev/null 2>&1 || true; done
fi

printf '\n%s✓ deployed sha=%s%s\n' "$C_GRN" "$sha" "$C_OFF"
ci_log "verify with: cd $COMPOSE_DIR && docker-compose ps"
exit 0
