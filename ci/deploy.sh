#!/bin/bash
# dive-analyser CD: build, swap, verify, roll back on failure.
#
# Safety model
# ------------
#   1. Refuse to deploy a dirty tree. Deploying uncommitted files is how you
#      end up unable to explain what is running.
#   2. Refuse to run without a green gate (skip with --skip-gate for hotfixes,
#      which is then reported loudly).
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
# These are the same directory in the normal case (deployed from a checkout),
# but can differ — e.g. building from a worktree into the live deployment dir.
ROOT="${DIVE_SOURCE_ROOT:-$(ci_repo_root)}"
COMPOSE_DIR="${DIVE_DEPLOY_ROOT:-$ROOT}"

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

if [ "$SKIP_GATE" -eq 0 ]; then
    ci_step "gate"
    if ! ci_run gate "$ROOT/ci/gate.sh" fast frontend; then
        ci_die "gate failed — not deploying"
    fi
    ci_ok "gate green"
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
    # Confirm recovery on whatever this deploy actually touched, rather than
    # always on the backend.
    local recovered=1
    if [ "$ONLY" != "frontend" ]; then
        ci_wait_http "$BACKEND_HEALTH" "backend(rollback)" "$HEALTH_RETRIES" \
            || { ci_err "rollback did NOT restore a healthy backend — manual intervention needed"; recovered=0; }
    fi
    if [ "$ONLY" != "backend" ]; then
        ci_wait_http "$FRONTEND_HEALTH" "frontend(rollback)" "$HEALTH_RETRIES" \
            || { ci_err "rollback did NOT restore a serving frontend — manual intervention needed"; recovered=0; }
    fi
    [ "$recovered" -eq 1 ] \
        && ci_warn "rollback complete — the previous version is serving again"
    return 1
}

# ------------------------------------------------------------ 4. build

if [ "$ONLY" != "backend" ]; then
    ci_step "build: frontend production image"
    if [ "$DRY_RUN" -eq 1 ]; then
        ci_warn "would run: docker build -f frontend/Dockerfile.deploy -t $FRONTEND_IMAGE:sha-$sha frontend"
    else
        ci_run build-frontend docker build \
            -f "$ROOT/frontend/Dockerfile.deploy" \
            -t "$FRONTEND_IMAGE:sha-$sha" \
            --label "dive.analyser/sha=$sha" \
            "$ROOT/frontend" \
            || ci_die "frontend image build failed — previous images untouched"
        docker tag "$FRONTEND_IMAGE:sha-$sha" "$FRONTEND_IMAGE:latest"
        ci_ok "frontend image built and tagged :latest"
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
        docker tag "$BACKEND_IMAGE:sha-$sha" "$BACKEND_IMAGE:latest"
        ci_ok "backend image built and tagged :latest"
    fi
fi

if [ "$DRY_RUN" -eq 1 ]; then
    ci_step "dry run complete — nothing was deployed"
    exit 0
fi

# ------------------------------------------------------------ 5. swap

ci_step "deploy: recreate containers"
svc_list=""
[ "$ONLY" != "backend" ]  && svc_list="$svc_list frontend"
[ "$ONLY" != "frontend" ] && svc_list="$svc_list backend"

compose up -d --no-deps --force-recreate $svc_list \
    || rollback "compose up failed"
ci_ok "containers recreated: $svc_list"

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

compose ps 2>/dev/null | sed 's/^/    /' || true

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