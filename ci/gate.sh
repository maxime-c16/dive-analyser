#!/bin/bash
# dive-analyser CI gate.
#
# Why this exists in this shape
# ----------------------------
# GitHub is the authoritative gate; the local pre-push hook defaults to fast.
# Each hosted runner runs one selected tier; local/deploy gates stay serial.
#
# The host is small (2 CPU, ~1.9 GB free RAM, production stack co-resident),
# so checks are ordered by cost and the cheap ones run first. A typo should
# fail in seconds, not after the three-minute backend suite.
#
# Usage:
#   ci/gate.sh                    # fast + frontend + backend + agent
#   ci/gate.sh fast               # static guards only (~1s)
#   ci/gate.sh frontend           # single-worker vitest + production build
#   ci/gate.sh backend            # isolated pytest, zero failures
#   ci/gate.sh agent              # portable Mac-agent tests
#   ci/gate.sh images             # docker build of the deployable images
#   ci/gate.sh all                # everything
#   ci/gate.sh tiers -- <paths>   # print the tiers needed for those changed paths
#
# Exit code is 0 only if every selected tier passed.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=ci/lib.sh
. "$SCRIPT_DIR/lib.sh"

ROOT="$(ci_repo_root)"
export CI=true NO_COLOR=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export NODE_OPTIONS="${NODE_OPTIONS:---max-old-space-size=768}"

# git exports GIT_DIR/GIT_INDEX_FILE (and friends) into hook environments.
# Child commands that run `git` with an explicit `-C <path>` (release-notes
# scoring against temp fixture repos, backend/git-spawning tests) inherit
# those vars, which override -C and silently redirect staging/commits into
# the real repository. Gate children always operate on explicit PATHs, so
# the hook's plumbing vars are dropped environment-wide here.
unset GIT_DIR GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES \
      GIT_WORK_TREE GIT_COMMON_DIR GIT_PREFIX GIT_QUARANTINE_PATH GIT_GRAFT_FILE \
      GIT_INDEX_VERSION GIT_SHARED_REPOSITORY 2>/dev/null || true

# Path selection is shared with GitHub through ci/select-tiers.py.

# ===========================================================================
# Tier: fast — static guards. No dependency installation, sub-second.
# ===========================================================================
tier_fast() {
    ci_step "fast: static guards"
    local failures=0 warns=0
    ci_run gate-self-tests python3 -m unittest discover -s "$ROOT/ci/tests" -q || failures=$((failures+1))
    ci_run release-notes python3 "$ROOT/ci/release-notes.py" validate || failures=$((failures+1))
    local note rc

    # -- shell syntax of every script the pipeline depends on --------------
    note="shell scripts parse"
    rc=0
    local s
    while IFS= read -r s; do
        bash -n "$ROOT/$s" 2>/dev/null || { rc=1; ci_err "syntax error: $s"; }
    done < <(git -C "$ROOT" ls-files '*.sh' | grep -vE '^(\.git|node_modules)/')
    if [ "$rc" -eq 0 ]; then
        ci_ok "$note"
    else
        ci_err "$note"; failures=$((failures+1))
    fi

    # -- compose file still resolves ---------------------------------------
    note="docker-compose.yml resolves"
    if ( cd "$ROOT" && ci_compose config -q ) >/dev/null 2>&1; then
        ci_ok "$note"
    else
        ci_err "$note — 'ci_compose config' failed"; failures=$((failures+1))
    fi

    # Compose's resolved build definitions must point at existing Dockerfiles.
    note="compose build contexts exist"
    local config_file
    config_file=$(mktemp)
    if ci_compose config >"$config_file" 2>/dev/null &&
       python3 - "$config_file" "$ROOT" <<'PYCODE'
import sys
from pathlib import Path
import yaml
with open(sys.argv[1]) as stream:
    doc = yaml.safe_load(stream)
for service in doc["services"].values():
    build = service.get("build")
    if build:
        context = build if isinstance(build, str) else build.get("context", ".")
        dockerfile = "Dockerfile" if isinstance(build, str) else build.get("dockerfile", "Dockerfile")
        path = Path(sys.argv[2]) / context / dockerfile
        if not path.is_file():
            raise SystemExit(f"missing compose Dockerfile: {path}")
PYCODE
    then
        ci_ok "$note"
    else
        ci_err "$note (requires Python PyYAML)"; failures=$((failures+1))
    fi
    unlink "$config_file"

    # -- no TLS private keys or real .env files tracked in git -------------
    # frontend/.env is intentionally tracked (VITE_* build-time constants,
    # no secrets) so it is allowlisted.
    note="no secrets tracked in git"
    rc=0
    local leaked
    leaked="$(git -C "$ROOT" ls-files \
        | grep -vE '(\.env\.example$|^frontend/\.env$)' \
        | grep -E '(^|/)\.env$|^nginx/ssl/' || true)"
    if [ -n "$leaked" ]; then
        while IFS= read -r leaked; do ci_err "tracked: $leaked"; done <<<"$leaked"
        rc=1
    fi
    if [ "$rc" -eq 0 ]; then
        ci_ok "$note"
    else
        ci_err "$note"; failures=$((failures+1))
    fi

    # -- known wart, reported but not blocking ----------------------------
    # The root Dockerfile COPYs package*.json but there is no package.json at
    # the repo root, so it cannot build. Nothing references it as a build
    # context; flagging rather than failing so the gate can go green today.
    note="root Dockerfile is buildable"
    if [ -f "$ROOT/Dockerfile" ] && [ ! -f "$ROOT/package.json" ] \
       && grep -qE '^\s*COPY\s+package\*?\.json' "$ROOT/Dockerfile"; then
        ci_warn "root Dockerfile cannot build (COPY package*.json with no package.json at repo root) — known issue, not blocking"
        warns=$((warns+1))
    else
        ci_ok "$note"
    fi

    if [ "$failures" -gt 0 ]; then
        ci_record fast FAIL "$failures check(s) failed"
        return 1
    fi
    ci_record fast PASS "static guards clean${warns:+ (${warns} known warning(s))}"
    return 0
}

# ===========================================================================
# Tier: frontend — vitest + tsc. ~1 min warm.
# ===========================================================================
tier_frontend() {
    ci_step "frontend: single-worker vitest + production build"
    local py rc

    if ! ci_have npm; then ci_record frontend FAIL "npm not installed"; return 1; fi

    ci_frontend_ready || ci_frontend_install

    rc=0
    # `npm test` is `vitest` in watch mode and would hang forever, so always
    # invoke the non-watch binary.
    #
    # This must run with CWD=frontend/: vitest resolves vite.config.ts,
    # setupFiles and the test glob relative to CWD, not to --prefix. Running
    # from the repo root silently collects the wrong files and skips
    # src/test/setup.ts.
    ci_run frontend-vitest \
        bash -c 'cd "$1" && CI=true NO_COLOR=1 npm run --silent test:ci' \
        _ "$ROOT/frontend" \
        || rc=1

    if [ "$rc" -ne 0 ]; then
        ci_record frontend FAIL "vitest failed"
        return 1
    fi

    ci_run frontend-build \
        bash -c 'cd "$1" && NO_COLOR=1 npm run --silent build' \
        _ "$ROOT/frontend" \
        || { ci_record frontend FAIL "production build failed"; return 1; }

    ci_record frontend PASS "unit tests + TypeScript + production bundle clean"
    return 0
}

# ===========================================================================
# Tier: backend — all portable API/service tests. No failure baseline.
# ===========================================================================

tier_backend() {
    ci_step "backend: isolated pytest (zero failures required)"
    ci_backend_python
    local result="$(ci_cache_dir)/logs/backend-results.json" rc=0
    mkdir -p "$(dirname "$result")"
    # Overwrite stale results before launching; a crashed run cannot reuse a pass.
    printf '{}' >"$result"
    ( cd "$ROOT/backend" &&
      export DATABASE_URL="sqlite:///:memory:" AUTO_IMPORT=false DB_TEST=0
      export PYTHONPATH="$ROOT:$ROOT/backend" DIVE_CI_RESULT_FILE="$result"
      ci_run backend-pytest "$CI_BACKEND_PYTHON" -m pytest tests/ \
        --junitxml="$(ci_cache_dir)/logs/backend-junit.xml" \
        -p ci.pytest_results -m "not performance" -q --tb=short \
        --strict-markers --asyncio-mode=auto \
        -W error::pytest.PytestUnhandledCoroutineWarning
    ) || rc=$?
    "$CI_BACKEND_PYTHON" "$ROOT/ci/check-results.py" "$result" "$rc" \
        || { ci_record backend FAIL "failures or incomplete run"; return 1; }
    ci_record backend PASS "zero failures; complete run"
}

# Portable agent logic: no Photos library, credentials, network or transcodes.
tier_agent() {
    ci_step "agent: caption parsing, sync, ingest and source-vault safety"
    ci_agent_python
    ( cd "$ROOT/mac-agent" &&
      ci_run agent-pytest "$CI_AGENT_PYTHON" -m pytest tests/ -q --tb=short \
        --junitxml="$(ci_cache_dir)/logs/agent-junit.xml" \
        --strict-markers --asyncio-mode=auto \
        -W error::pytest.PytestUnhandledCoroutineWarning
    ) || { ci_record agent FAIL "portable agent tests failed"; return 1; }
    ci_record agent PASS "agent tests clean with isolated native boundaries"
}

# ===========================================================================
# Tier: images — prove the deployable images actually build.
# ===========================================================================
tier_images() {
    ci_step "images: docker build"
    if ! ci_have docker; then ci_record images FAIL "docker not available"; return 1; fi
    local rc=0 tag="ci-build-$(git -C "$ROOT" rev-parse --short HEAD)-$$"
    ci_run proxy-config bash "$SCRIPT_DIR/check-proxies.sh" || return 1

    # Frontend production image. This is the artifact that actually gets
    # deployed (compose references it by tag and has no build section for it),
    # so it is the one whose breakage would actually bite.
    ci_run image-frontend \
        docker build -f "$ROOT/frontend/Dockerfile.deploy" \
        --build-arg "APP_SHA=$(git -C "$ROOT" rev-parse HEAD)" \
        -t "dive-analyser-frontend:$tag" "$ROOT/frontend" \
        || { rc=1; ci_err "frontend image build failed"; }

    ci_run image-backend \
        docker build -f "$ROOT/backend/Dockerfile" \
        -t "dive-analyser-backend:$tag" "$ROOT/backend" \
        || { rc=1; ci_err "backend image build failed"; }

    docker image rm "dive-analyser-frontend:$tag" "dive-analyser-backend:$tag" \
        >/dev/null 2>&1 || true

    if [ "$rc" -ne 0 ]; then
        ci_record images FAIL "docker build failed"
        return 1
    fi
    ci_record images PASS "frontend + backend images build"
    return 0
}

# ===========================================================================
# tiers subcommand — used by the pre-push hook to skip untouched components.
# ===========================================================================
cmd_tiers() {
    [ "${1:-}" = "--" ] && shift
    python3 "$SCRIPT_DIR/select-tiers.py" "$@"
}

# ===========================================================================

main() {
    # `tiers` is a subcommand that reports which tiers a set of paths needs.
    if [ "${1:-}" = "tiers" ]; then
        cmd_tiers "${@:2}"
        return 0
    fi

    # Join *all* arguments. The pre-push hook invokes this as
    # `gate.sh fast backend frontend`, so reading only $1 would silently drop
    # every tier after the first and let an ungated change through.
    local spec
    if [ "${1:-}" = --tier ]; then
        [ "$#" -eq 2 ] || ci_die "usage: ci/gate.sh --tier fast|frontend|backend|agent|postgres|images"
        # Hosted workers rely on the same checkout's successful plan/fast job.
        spec="$2"
    else
        spec="${*:-default}"
        case "$spec" in
            fast)     spec="fast" ;;
            frontend) spec="fast frontend" ;;
            backend)  spec="fast backend" ;;
            agent)    spec="fast agent" ;;
            images)   spec="fast images" ;;
            all)      spec="fast frontend backend agent images" ;;
            default)  spec="${DIVE_CI_TIERS:-fast frontend backend agent}" ;;
        esac
    fi

    # PostgreSQL is hosted separately; explicit local runs require a disposable DB.
    # Validate the whole spec before doing any work, so a typo costs a second
    # instead of failing three minutes in.
    local t
    for t in $spec; do
        case "$t" in
            fast|frontend|backend|agent|postgres|images) ;;
            *) ci_die "unknown tier: '$t' in '$spec' (use fast|frontend|backend|agent|postgres|images|all|tiers)" ;;
        esac
    done

    mkdir -p "$(ci_cache_dir)"
    exec 9>"$(ci_cache_dir)/gate.lock"
    flock -n 9 || ci_die "another CI gate is running; retry when it finishes"

    printf '%sdive-analyser CI%s  %s%d CIUs · %s\n' \
        "$C_BLU" "$C_OFF" "$C_DIM" "$(nproc)" "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

    local rc_any=0
    for t in $spec; do
        case "$t" in
            fast)     tier_fast     || rc_any=1 ;;
            frontend) tier_frontend || rc_any=1 ;;
            backend)  tier_backend  || rc_any=1 ;;
            agent)    tier_agent    || rc_any=1 ;;
            postgres) bash "$SCRIPT_DIR/postgres.sh" || rc_any=1 ;;
            images)   tier_images   || rc_any=1 ;;
            *) ci_die "unknown tier: $t" ;;
        esac
        # Fail fast: no point spending three minutes on the backend suite once
        # a syntax error has already sunk the build.
        if [ "$rc_any" -ne 0 ]; then
            ci_err "aborting remaining tiers — earlier tier already failed"
            CI_RESULTS+=("remaining|SKIP|skipped after failure")
            break
        fi
    done

    ci_summary || rc_any=1
    if [ "$rc_any" -ne 0 ]; then
        ci_err "CI FAILED"
        return 1
    fi
    ci_ok "CI passed"
    return 0
}

main "$@"
