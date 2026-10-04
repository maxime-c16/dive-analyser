#!/bin/bash
# Shared helpers for the dive-analyser CI/CD scripts.
#
# Design constraints this file encodes:
#   * The host is small (2 CPU, ~1.9 GB free RAM). Nothing here runs in
#     parallel, and long jobs are niced so the live dive-analyser stack
#     keeps serving traffic while CI runs.
#   * There is no CI provider. Everything runs from git hooks / the CLI.

set -euo pipefail

# ---------------------------------------------------------------- locations

# Repo root, resolved from wherever we were invoked so the scripts work from
# hooks, from any worktree, and from cron.
ci_repo_root() {
    git rev-parse --show-toplevel 2>/dev/null || {
        echo "fatal: not inside a git repository" >&2
        exit 2
    }
}

# Persistent scratch space. Deliberately outside the worktree so caches
# survive branch switches, worktree removal and `git clean`.
ci_cache_dir() {
    printf '%s' "${DIVE_CI_CACHE:-${XDG_CACHE_HOME:-$HOME/.cache}/dive-ci}"
}

# ------------------------------------------------------------------- output

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    C_RED=$'\033[0;31m'; C_GRN=$'\033[0;32m'; C_YEL=$'\033[1;33m'
    C_BLU=$'\033[1;34m'; C_DIM=$'\033[2m';    C_OFF=$'\033[0m'
else
    C_RED=''; C_GRN=''; C_YEL=''; C_BLU=''; C_DIM=''; C_OFF=''
fi

ci_log()  { printf '%s[ci]%s %s\n' "$C_DIM" "$C_OFF" "$*" >&2; }
ci_step() { printf '\n%s==>%s %s%s%s\n' "$C_BLU" "$C_OFF" "$C_BLU" "$*" "$C_OFF"; }
ci_ok()   { printf '  %s✓%s %s\n' "$C_GRN" "$C_OFF" "$*"; }
ci_warn() { printf '  %s!%s %s\n' "$C_YEL" "$C_OFF" "$*" >&2; }
ci_err()  { printf '  %s✗%s %s\n' "$C_RED" "$C_OFF" "$*" >&2; }
ci_die()  { ci_err "$*"; exit 1; }

# Niced + log-to-file wrapper. Long jobs write a full log under the cache dir
# so a failure can be inspected after the fact without re-running.
#
#   ci_run <slug> <command...>
ci_run() {
    local slug="$1"; shift
    local logdir; logdir="$(ci_cache_dir)/logs"
    mkdir -p "$logdir"
    local log="$logdir/${slug}.log"

    printf '%s  log:%s %s\n' "$C_DIM" "$C_OFF" "$log"
    local start elapsed rc
    start=$(date +%s)
    set +e
    if command nice -n 10 timeout --signal=TERM --kill-after=10s "${DIVE_CI_TIMEOUT:-900}" "$@" >"$log" 2>&1; then rc=0; else rc=$?; fi
    tail -20 "$log"
    set -e
    elapsed=$(( $(date +%s) - start ))

    printf '%s  took:%ss%s\n' "$C_DIM" "$elapsed" "$C_OFF"
    return "$rc"
}

# -------------------------------------------------------------- test result

# Accumulates per-tier outcomes so the caller can print one summary.
CI_RESULTS=()

ci_record() {
    # ci_record <tier> <PASS|FAIL|WARN|SKIP> <message>
    CI_RESULTS+=("$1|$2|$3")
}

ci_summary() {
    local tier rc msg bad=0
    printf '\n%s=== SUMMARY ===%s\n' "$C_BLU" "$C_OFF"
    for row in "${CI_RESULTS[@]:-}"; do
        [ -z "$row" ] && continue
        IFS='|' read -r tier rc msg <<<"$row"
        case "$rc" in
            PASS) printf '  %s✓%s %-10s %s\n' "$C_GRN" "$C_OFF" "$tier" "$msg" ;;
            WARN) printf '  %s!%s %-10s %s\n' "$C_YEL" "$C_OFF" "$tier" "$msg" ;;
            SKIP) printf '  %s·%s %-10s %s\n' "$C_DIM" "$C_OFF" "$tier" "$msg" ;;
            *)    printf '  %s✗%s %-10s %s\n' "$C_RED" "$C_OFF" "$tier" "$msg"
                 bad=1 ;;
        esac
    done
    printf '\n'
    return "$bad"
}

# ------------------------------------------------------- dependency caches

# Python venv for the backend, rebuilt only when requirements.txt changes.
# Result is returned in the global CI_BACKEND_PYTHON rather than on stdout:
# command substitution would swallow any diagnostics printed on the way.
CI_BACKEND_PYTHON=""
ci_backend_python() {
    local root cache venv stamp reqhash
    root="$(ci_repo_root)"
    cache="$(ci_cache_dir)"
    # A different requirements set gets a fresh environment, so pip cannot
    # retain packages removed by another branch. Include the interpreter in
    # the key and keep the old cache intact for worktrees using that set.
    reqhash="$(ci_python_env_hash "$root/backend/requirements.txt")"
    venv="$cache/venv-backend-$reqhash"
    stamp="$venv/.requirements.sha256"
    mkdir -p "$cache"
    if [ ! -x "$venv/bin/python" ]; then
        ci_log "creating backend venv (first run for this dependency set)"
        python3 -m venv "$venv" || ci_die "failed to create venv at $venv"
    fi

    if [ ! -f "$stamp" ] || [ "$(cat "$stamp")" != "$reqhash" ]; then
        ci_log "installing backend dependencies (requirements.txt changed)"
        ci_run backend-dependencies "$venv/bin/pip" install --quiet --disable-pip-version-check \
            -r "$root/backend/requirements.txt" \
            || ci_die "backend dependency install failed"
        printf '%s' "$reqhash" >"$stamp"
    fi

    [ -x "$venv/bin/python" ] || ci_die "backend venv has no interpreter at $venv/bin/python"
    CI_BACKEND_PYTHON="$venv/bin/python"
}

# Frontend node_modules. `npm ci` is the slow part of the frontend tier, so it
# is skipped entirely unless the lockfile moved.
ci_frontend_ready() {
    local root cache stamp lockhash
    root="$(ci_repo_root)"
    cache="$(ci_cache_dir)"
    stamp="$root/frontend/node_modules/.dive-ci.sha256"

    [ -d "$root/frontend/node_modules" ] || return 1
    [ -f "$stamp" ] || return 1

    lockhash="$(ci_frontend_hash "$root")"
    [ "$(cat "$stamp")" = "$lockhash" ] || return 1
    return 0
}

ci_frontend_install() {
    local root cache
    root="$(ci_repo_root)"
    cache="$(ci_cache_dir)"
    [ -d "$cache" ] || mkdir -p "$cache"

    ci_log "installing frontend dependencies (npm ci)"
    ( cd "$root/frontend" && command nice -n 10 npm ci --no-audit --no-fund ) \
        || ci_die "npm ci failed"
    ci_frontend_hash "$root" >"$root/frontend/node_modules/.dive-ci.sha256"
}

# --------------------------------------------------------------- utilities

ci_have() { command -v "$1" >/dev/null 2>&1; }

# Wait for an HTTP endpoint to answer 200.
#   ci_wait_http <url> <label> [timeout-seconds] [curl extra args...]
ci_wait_http() {
    local url="$1" label="$2" timeout="${3:-60}"; shift 3 || true
    local deadline
    deadline=$(( $(date +%s) + timeout ))
    while [ "$(date +%s)" -lt "$deadline" ]; do
        if curl -fsSk -m 5 "$@" "$url" >/dev/null 2>&1; then
            ci_ok "$label responded 200 ($url)"
            return 0
        fi
        sleep 3
    done
    ci_err "$label never returned 200 within ${timeout}s ($url)"
    return 1
}
CI_AGENT_PYTHON=""
ci_agent_python() {
    local root cache venv stamp reqhash
    root="$(ci_repo_root)"
    cache="$(ci_cache_dir)"
    reqhash="$(ci_python_env_hash "$root/ci/requirements-agent.txt")"
    venv="$cache/venv-agent-$reqhash"
    stamp="$venv/.requirements.sha256"
    mkdir -p "$cache"
    [ -x "$venv/bin/python" ] || python3 -m venv "$venv" || ci_die "agent venv creation failed"

    if [ ! -f "$stamp" ] || [ "$(cat "$stamp")" != "$reqhash" ]; then
        ci_run agent-dependencies "$venv/bin/pip" install --quiet --disable-pip-version-check \
            -r "$root/ci/requirements-agent.txt" || ci_die "agent dependencies failed"
        printf '%s' "$reqhash" >"$stamp"
    fi
    CI_AGENT_PYTHON="$venv/bin/python"
}

ci_frontend_hash() {
    { sha256sum "$1/frontend/package-lock.json" "$1/frontend/package.json"; node --version; } | sha256sum | cut -d' ' -f1
}

ci_compose() {
    if docker compose version >/dev/null 2>&1; then
        docker compose "$@"
    else
        docker-compose "$@"
    fi
}

# Version the cache scheme so existing in-place environments are not reused.
ci_python_env_hash() {
    { printf 'isolated-venv-v1\n'; cat "$1"; python3 -c 'import sys; print(sys.executable); print(sys.version)'; } | sha256sum | cut -d' ' -f1
}
