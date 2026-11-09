#!/bin/bash
# dive-analyser host preflight: what can this machine actually run?
#
# Gate and ship steps used to fail late with tool-native errors ("Cannot
# connect to the Docker daemon", ~10s ssh timeouts, "command not found"
# mid-gate). This script turns those surprises into one fast, readable report.
#
#   ci/checkhost.sh                    # full report (default scope); exit 1 on FAIL
#   ci/checkhost.sh --scope ship       # the subset ship.sh needs on this host
#   ci/checkhost.sh --scope images     # the subset the images tier needs (strict)
#   ci/checkhost.sh --brief            # one summary line per scope
#   ci/checkhost.sh --quiet            # nothing printed, exit code only
#   ci/checkhost.sh --warn-only        # report everything, always exit 0
#
# Scopes:
#   laptop (default): everything a dev checkout uses, incl. optional tools.
#   ship:             git/ssh/python3 + ssh aliases; docker is advisory
#                     (images and proxy checks belong on the server).
#   images:           strict subset used by `ci/gate.sh images` — a dead Docker
#                     daemon FAILs, because builds cannot run anywhere else.
#
# Wired in: ci/gate.sh images tier (strict) and the ci/ship.sh entry for
# server/mac/all/proxy (advisory; enforce with DIVE_CHECKHOST_STRICT=1 so the
# deb-serv auto-deploy cron keeps working unattended).
#
# Notes:
#   - Missing MySQL/YaQ/Go/DuckDB/wrangler and similar are NOT checked: grep -
#     shows ci/ and ops/ never call them. Adding an unused tool here would
#     just recreate the "tools unavailable on macOS" confusion.
#   - The script itself only uses commands present on stock macOS (no GNU
#     coreutils), because it also runs before those are proven present.

set -u

brief=0 quiet=0 warn_only=0 scope="laptop"
while [ $# -gt 0 ]; do
    case "$1" in
        --scope) [ $# -ge 2 ] || { echo "usage error: --scope needs laptop|ship|images" >&2; exit 2; }
                 scope="$2"; shift ;;
        --brief)     brief=1 ;;
        --quiet)     quiet=1 ;;
        --warn-only) warn_only=1 ;;
        -h|--help) sed -n '3,31p' "$0"; exit 0 ;;
        *) echo "unknown option: $1 (see ci/checkhost.sh --help)" >&2; exit 2 ;;
    esac
    shift
done

ok_out()  { [ "$quiet" -eq 1 ] || [ "$brief" -eq 1 ] || printf '  ok   %s\n' "$1"; }
fail_out(){ [ "$quiet" -eq 1 ] || printf '  FAIL %s\n' "$1" >&2; FAILS=$((FAILS+1)); }
warn_out(){ [ "$quiet" -eq 1 ] || [ "$brief" -eq 1 ] || printf '  NOTE %s\n' "$1" >&2; WARNS=$((WARNS+1)); }

FAILS=0
WARNS=0

# -- present? sets a list of found/missing tool names ------------------------

present_in_list() {
    local found="" missing=""
    for t in "$@"; do
        command -v "$t" >/dev/null 2>&1 && found="$found $t" || missing="$missing $t"
    done
    printf '%s|%s\n' "${found# }" "${missing# }"
}

report_tools() {
    # $1=advice for missing ones; every arg after that names a tool.
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

report_alias() {
    # $1=alias $2=factor hint $3=severity: warn (default) or strict.
    local alias="$1" ip_hint="$2" sev="${3:-warn}"
    if alias_resolves "$alias"; then
        ok_out "ssh alias '$alias' resolves (${ip_hint})"
    elif [ "$sev" = strict ]; then
        fail_out "ssh alias '$alias' not in ~/.ssh/config — ship/status to that host will fail (override: DIVE_SERVER_SSH/DIVE_MAC_SSH)"
    else
        warn_out "ssh alias '$alias' not in ~/.ssh/config — ship/status to that host will fail (override: DIVE_SERVER_SSH/DIVE_MAC_SSH)"
    fi
}

alias_reachable() {
    ssh -o BatchMode=yes -o ConnectTimeout=3 "$1" true >/dev/null 2>&1
}

# ---------------------------------------------------------------- scope: laptop

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
    report_alias diveanalyzer-server "mcauchy@192.168.1.57 (deb-serv)"
    report_alias diveanalyzer-mac "divesensei@192.168.1.19 (mac worker)"
    if alias_reachable diveanalyzer-server; then ok_out "deb-serv reachable"; else warn_out "deb-serv not answering ssh right now (machine off/asleep?)"; fi
    if alias_reachable diveanalyzer-mac; then ok_out "mac worker reachable"; else warn_out "mac worker not answering ssh right now"; fi
fi

# --------------------------------------- docker (both laptop and ship scopes)

if [ "$scope" = laptop ] || [ "$scope" = ship ] || [ "$scope" = images ]; then
    if command -v docker >/dev/null 2>&1; then
        if docker info --format '{{.ServerVersion}}' >/dev/null 2>&1; then
            ok_out "docker daemon running"
        elif [ "$scope" = images ]; then
            fail_out "docker client here but daemon is DOWN — builds must run on deb-serv, or start Docker on this host"
        else
            warn_out "docker daemon DOWN on this laptop — 'images' tier and proxy checks are SERVER-ONLY (run on deb-serv)"
        fi
        if docker compose version >/dev/null 2>&1 || command -v docker-compose >/dev/null 2>&1; then
            ok_out "docker compose available (plugin and/or standalone)"
        elif [ "$scope" = images ]; then
            fail_out "neither 'docker compose' plugin nor standalone 'docker-compose' found"
        else
            warn_out "docker compose not found on this host"
        fi
    elif [ "$scope" = images ]; then
        fail_out "docker client missing — image builds cannot run here (use deb-serv via ci/ship.sh)"
    else
        warn_out "docker client not installed here — server-only steps will run on deb-serv"
    fi
fi

# ---------------------------------------------------------------- scope: ship

if [ "$scope" = ship ]; then
    report_tools "core of ship.sh on the invoking host" git ssh python3
    # Strict aliases: shipping is about reaching these two hosts, so an
    # unresolved alias fails even with --warn-only absent AND makes
    # DIVE_CHECKHOST_STRICT=1 meaningful. Unreachable (machine off) stays a
    # note: a deploy attempt produces the real ssh error.
    report_alias diveanalyzer-server "mcauchy@192.168.1.57 (deb-serv)" strict
    report_alias diveanalyzer-mac "divesensei@192.168.1.19 (mac worker)" strict
    if alias_reachable diveanalyzer-server; then ok_out "deb-serv reachable"; else warn_out "deb-serv not answering ssh right now (machine off/asleep?)"; fi
    if alias_reachable diveanalyzer-mac; then ok_out "mac worker reachable"; else warn_out "mac worker not answering ssh right now (deploy would fail if down)"; fi
elif [ "$scope" = images ]; then
    report_tools "core of the images tier" git python3
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
