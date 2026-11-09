#!/bin/bash
# dive-analyser host preflight: what can this machine actually run?
#
# Gate and ship steps used to fail late with tool-native errors ("Cannot
# connect to the Docker daemon", ~10s ssh timeouts, "command not found"
# mid-gate). This script turns those surprises into one fast, readable report.
#
#   ci/checkhost.sh                       # full report (laptop scope); exit 1 on FAIL
#   ci/checkhost.sh --scope ship          # what ship.sh needs on the invoking host
#   ci/checkhost.sh --scope ship --target server
#   ci/checkhost.sh --scope images        # strict subset the images tier needs
#   ci/checkhost.sh --brief               # one summary line per scope
#   ci/checkhost.sh --quiet               # nothing printed, exit code only
#   ci/checkhost.sh --warn-only           # report everything, always exit 0
#
# Scopes:
#   laptop (default): everything a dev checkout uses, incl. optional tools.
#   ship:             git/ssh/python3 + the ssh aliases of the selected
#                     target (--target server|mac|all; default: both), plus
#                     ssh reachability. Docker is advisory here (image builds
#                     and proxy checks belong to the server).
#   images:           strict subset used by `ci/gate.sh images`: git,
#                     python3, the docker client, a live daemon. Compose is
#                     NOT required here — tier_images() is `docker build`
#                     and `docker run` only; compose belongs to the gate
#                     fast tier and ci/deploy.sh.
#
# Severity contract:
#   Ship-scope failures (missing required tool, unresolved alias, unreachable
#   target) exit 1. `ci/ship.sh` treats that as advisory unless
#   DIVE_CHECKHOST_STRICT=1 is set, in which case it aborts. The deb-serv
#   auto-deploy cron never sets the flag, so unattended deploys stay
#   unblocked; the report still tells an operator why the next step will
#   fail.
#
# Wired in: ci/gate.sh images tier (strict) and the ci/ship.sh entry for
# server/mac/all/proxy (advisory; enforce with DIVE_CHECKHOST_STRICT=1).
#
# Notes:
#   - Missing mysql/yq/go/duckdb/wrangler and similar are NOT checked: grep
#     shows ci/ and ops/ never call them. Listing unused tools would recreate
#     the "tools unavailable on macOS" confusion.
#   - ssh alias names honor DIVE_SERVER_SSH / DIVE_MAC_SSH (the same
#     overrides ship.sh accepts; docs/REPO_WORKFLOW.md).
#   - The script itself only uses commands present on stock macOS (no GNU
#     coreutils), because it also runs before those are proven present.

set -u

brief=0 quiet=0 warn_only=0 scope="laptop" target="both"
while [ $# -gt 0 ]; do
    case "$1" in
        --scope) [ $# -ge 2 ] || { echo "usage error: --scope needs laptop|ship|images" >&2; exit 2; }
                 scope="$2"; shift ;;
        --target) [ $# -ge 2 ] || { echo "usage error: --target needs server|mac|all" >&2; exit 2; }
                 target="$2"; shift ;;
        --brief)     brief=1 ;;
        --quiet)     quiet=1 ;;
        --warn-only) warn_only=1 ;;
        -h|--help) sed -n '3,45p' "$0"; exit 0 ;;
        *) echo "unknown option: $1 (see ci/checkhost.sh --help)" >&2; exit 2 ;;
    esac
    shift
done

case "$scope" in laptop|ship|images) ;; *) echo "unknown scope: $scope" >&2; exit 2 ;; esac
case "$target" in server|mac|all|both) ;; *) echo "unknown target: $target" >&2; exit 2 ;; esac

ok_out()  { [ "$quiet" -eq 1 ] || [ "$brief" -eq 1 ] || printf '  ok   %s\n' "$1"; }
fail_out(){ [ "$quiet" -eq 1 ] || printf '  FAIL %s\n' "$1" >&2; FAILS=$((FAILS+1)); }
warn_out(){ [ "$quiet" -eq 1 ] || [ "$brief" -eq 1 ] || printf '  NOTE %s\n' "$1" >&2; WARNS=$((WARNS+1)); }

FAILS=0
WARNS=0

# -- tool presence: prints one line for what is found / missing ---------------

present_in_list() {
    local found="" missing=""
    for t in "$@"; do
        command -v "$t" >/dev/null 2>&1 && found="$found $t" || missing="$missing $t"
    done
    printf '%s|%s\n' "${found# }" "${missing# }"
}

report_tools() {
    # $1=advice for missing ones; remaining args name tools.
    local advice="$1"; shift
    local res found missing
    res="$(present_in_list "$@")"
    found="${res%%|*}"; missing="${res##*|}"
    [ -n "$found" ] && ok_out "present:${found# }"
    if [ -n "$missing" ]; then
        fail_out "missing:${missing# }  ($advice)"
    fi
}

# -- ssh alias resolution (macOS OpenSSH must; `ssh -G` since 7.3) -----------

alias_resolves() {
    if ! ssh -G "$1" >/dev/null 2>&1; then return 1; fi
    local host
    host="$(ssh -G "$1" 2>/dev/null | awk '$1 == "hostname" {print $2; exit}')"
    # A missing config entry echoes the alias back as its own hostname.
    [ -n "$host" ] && [ "$host" != "$1" ]
}

alias_reachable() {
    ssh -o BatchMode=yes -o ConnectTimeout=3 "$1" true >/dev/null 2>&1
}

# Informational alias report for the laptop scope: never fails (the laptop
# may not even be a deploy station); unresolved aliases and offline hosts
# are notes with the fix attached.
report_alias_info() {
    # $1=alias (env-resolved), $2=human hint
    if alias_resolves "$1"; then
        ok_out "ssh alias '$1' resolves ($2)"
    else
        warn_out "ssh alias '$1' not in ~/.ssh/config — shipping from this host to that machine will fail (override: DIVE_SERVER_SSH / DIVE_MAC_SSH)"
    fi
    if alias_reachable "$1"; then
        ok_out "$1 reachable"
    else
        warn_out "$1 is not answering ssh right now (machine off/asleep?)"
    fi
}

# Ship-scope host check: every failure here blocks (strict) or advises ship.
check_ship_host() {
    # $1=alias (already env-resolved), $2=human hint
    local alias="$1" hint="$2"
    if alias_resolves "$alias"; then
        ok_out "ssh alias '$alias' resolves (${hint})"
        if alias_reachable "$alias"; then
            ok_out "$alias reachable"
        else
            fail_out "ssh alias '$alias' resolves but the host is not answering ssh right now — a deploy to it fails until it is up"
        fi
    else
        fail_out "ssh alias '$alias' not in ~/.ssh/config — shipping to that host will fail (override: DIVE_SERVER_SSH / DIVE_MAC_SSH; see docs/REPO_WORKFLOW.md)"
    fi
}

# ---------------------------------------------------------------- scope: laptop

SERVER_SSH="${DIVE_SERVER_SSH:-diveanalyzer-server}"
MAC_SSH="${DIVE_MAC_SSH:-diveanalyzer-mac}"

if [ "$scope" = laptop ]; then
    report_tools "core of gate + ship" git ssh python3 curl jq rsync
    report_tools "needed by ci/gate.sh frontend only (advisory)" node npm
    res="$(present_in_list timeout sha256sum nproc flock)"; found="${res%%|*}"; missing="${res##*|}"
    if [ -n "$missing" ]; then
        if command -v brew >/dev/null 2>&1; then
            fail_out "missing GNU tools:${missing# }  (brew install coreutils flock)"
        else
            fail_out "missing GNU tools:${missing# }  (Linux box? install coreutils+util-linux; macOS needs brew)"
        fi
    else ok_out "GNU tools present (timeout, sha256sum, nproc, flock)"; fi
    report_alias_info "$SERVER_SSH" "server (mcauchy@192.168.1.57, deb-serv)"
    report_alias_info "$MAC_SSH" "mac worker (divesensei@192.168.1.19, mac-server)"
fi

# --------------------------------------------------- docker (advisory level) --

if [ "$scope" = laptop ] || [ "$scope" = ship ]; then
    if command -v docker >/dev/null 2>&1; then
        if docker info --format '{{.ServerVersion}}' >/dev/null 2>&1; then
            ok_out "docker daemon running"
        else
            warn_out "docker daemon DOWN on this laptop — 'images' tier and proxy checks are SERVER-ONLY (run on deb-serv)"
        fi
        if docker compose version >/dev/null 2>&1 || command -v docker-compose >/dev/null 2>&1; then
            ok_out "docker compose available (plugin and/or standalone)"
        else
            warn_out "docker compose not found on this host (needed by ci/deploy.sh and the fast tier, not by image builds)"
        fi
    else
        warn_out "docker client not installed here — server-only steps will run on deb-serv"
    fi
fi

# ---------------------------------------------------------------- scope: ship

if [ "$scope" = ship ]; then
    report_tools "core of ship.sh on the invoking host" git ssh python3
    case "$target" in
        both|all)
            check_ship_host "$SERVER_SSH" "server"
            check_ship_host "$MAC_SSH" "mac worker"
            ;;
        server) check_ship_host "$SERVER_SSH" "server" ;;
        mac)    check_ship_host "$MAC_SSH" "mac worker" ;;
    esac
elif [ "$scope" = images ]; then
    report_tools "core of the images tier" git python3
    # tier_images() is `docker build` and `docker run` — no compose here.
    if command -v docker >/dev/null 2>&1; then
        if docker info --format '{{.ServerVersion}}' >/dev/null 2>&1; then
            ok_out "docker daemon running"
        else
            fail_out "docker client here but the daemon is DOWN — image builds must run on deb-serv (ci/ship.sh), or start Docker on this host"
        fi
    else
        fail_out "docker client missing — image builds cannot run here (use deb-serv via ci/ship.sh)"
    fi
fi

# ------------------------------------------------------------------- verdict

brief_line() {
    if [ "$FAILS" -eq 0 ] && [ "$WARNS" -eq 0 ]; then
        printf 'preflight: ok (%s scope clean)\n' "$scope"
    elif [ "$FAILS" -eq 0 ]; then
        printf 'preflight: ok (%s scope; %s advisory note(s) above)\n' "$scope" "$WARNS"
    else
        printf 'preflight: %s FAIL, %s note(s) in %s scope — see FAIL lines above\n' "$FAILS" "$WARNS" "$scope"
    fi
}

if [ "$brief" -eq 1 ]; then
    brief_line >&2
elif [ "$quiet" -eq 0 ] && [ "$WARNS" -gt 0 ] ; then
    printf 'preflight (%s): %d FAIL, %d note(s)\n' "$scope" "$FAILS" "$WARNS" >&2
fi

if [ "$warn_only" -eq 0 ] && [ "$FAILS" -gt 0 ]; then
    exit 1
fi
exit 0
