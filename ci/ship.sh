#!/bin/bash
# dive-analyser fleet sync + deploy. GitHub is the single source of truth.
#
# Every deploy ships an exact commit that already exists on GitHub. Nothing is
# copied from a working tree, and no host pushes to another host directly.
#
#   ci/ship.sh status                     what is running where, vs GitHub master
#   ci/ship.sh server [options]           deploy the app stack on deb-serv
#   ci/ship.sh mac    [options]           deploy the media agent on mac-media-01
#   ci/ship.sh all    [options]           server, then mac
#
# Options:
#   --ref <ref>        commit to ship (default: origin/master)
#   --allow-unmerged   allow a ref that is not reachable from origin/master
#   --dry-run          show the plan, change nothing
#   --force            redeploy even if the host is already at that commit
#   --skip-gate | --frontend-only | --backend-only    passed to ci/deploy.sh
#
# Runs from any checkout that can fetch GitHub (the laptop, or deb-serv
# itself). Hosts are reached through the ssh aliases below; when the script is
# already running on the target host it runs locally instead.
#
# Full workflow and rationale: docs/REPO_WORKFLOW.md

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=ci/lib.sh
. "$SCRIPT_DIR/lib.sh"
set +e   # lib.sh enables errexit; this script checks every step explicitly

SERVER_SSH="${DIVE_SERVER_SSH:-diveanalyzer-server}"
SERVER_HOSTNAME="${DIVE_SERVER_HOSTNAME:-deb-serv}"
MAC_SSH="${DIVE_MAC_SSH:-diveanalyzer-mac}"
MAC_HOSTNAME="${DIVE_MAC_HOSTNAME:-mac-server}"
GITHUB_SLUG="maxime-c16/dive-analyser"

usage() { sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; }

cmd="${1:-}"; [ $# -gt 0 ] && shift
case "$cmd" in
    status|server|mac|all) ;;
    -h|--help|help|"") usage; exit 0 ;;
    *) ci_die "unknown command: $cmd (try: ci/ship.sh --help)" ;;
esac

REF="origin/master"
ALLOW_UNMERGED=0
DRY_RUN=0
FORCE=0
DEPLOY_FLAGS=()

while [ $# -gt 0 ]; do
    case "$1" in
        --ref) [ $# -ge 2 ] || ci_die "--ref needs a value"; REF="$2"; shift ;;
        --allow-unmerged) ALLOW_UNMERGED=1 ;;
        --dry-run) DRY_RUN=1 ;;
        --force) FORCE=1 ;;
        --skip-gate|--frontend-only|--backend-only) DEPLOY_FLAGS+=("$1") ;;
        *) ci_die "unknown option: $1" ;;
    esac
    shift
done

ROOT="$(ci_repo_root)"

# ------------------------------------------------------------------ helpers

# run_on <server|mac> <script> [args...]
# Runs a bash script on the target host, locally if we are already there.
run_on() {
    local target="$1" script="$2"; shift 2
    local ssh_alias host_name quoted=""
    case "$target" in
        server) ssh_alias="$SERVER_SSH"; host_name="$SERVER_HOSTNAME" ;;
        mac)    ssh_alias="$MAC_SSH";    host_name="$MAC_HOSTNAME" ;;
    esac
    if [ "$(hostname -s)" = "$host_name" ]; then
        bash -s -- "$@" <<<"$script"
    else
        [ $# -gt 0 ] && quoted="$(printf '%q ' "$@")"
        # ssh does not forward the environment; pass SHIP_FROM explicitly.
        ssh -o BatchMode=yes -o ConnectTimeout=10 "$ssh_alias" \
            "SHIP_FROM=$(printf '%q' "${SHIP_FROM:-}") bash -s -- $quoted" <<<"$script"
    fi
}

# Pipe stdin to a command on the target host.
pipe_to() {
    local target="$1" command="$2"
    local ssh_alias host_name
    case "$target" in
        server) ssh_alias="$SERVER_SSH"; host_name="$SERVER_HOSTNAME" ;;
        mac)    ssh_alias="$MAC_SSH";    host_name="$MAC_HOSTNAME" ;;
    esac
    if [ "$(hostname -s)" = "$host_name" ]; then
        bash -c "$command"
    else
        ssh -o BatchMode=yes -o ConnectTimeout=10 "$ssh_alias" "$command"
    fi
}

# Exact canonical URL forms only: a substring match would also accept
# look-alike hosts, forks with a suffix, or local paths.
is_canonical_url() {
    case "$1" in
        https://github.com/$GITHUB_SLUG|https://github.com/$GITHUB_SLUG.git) return 0 ;;
        git@github.com:$GITHUB_SLUG|git@github.com:$GITHUB_SLUG.git) return 0 ;;
        ssh://git@github.com/$GITHUB_SLUG|ssh://git@github.com/$GITHUB_SLUG.git) return 0 ;;
    esac
    return 1
}

origin_is_github() {
    is_canonical_url "$(git -C "$ROOT" remote get-url origin 2>/dev/null)"
}

# Resolve REF to a full sha that is on GitHub. Sets SHA and SHORT.
resolve_ref() {
    origin_is_github \
        || ci_die "this checkout's 'origin' is not GitHub ($GITHUB_SLUG) — see docs/REPO_WORKFLOW.md"
    git -C "$ROOT" fetch --quiet --prune origin \
        || ci_die "git fetch origin failed — this host cannot reach GitHub"
    SHA="$(git -C "$ROOT" rev-parse --verify --quiet "${REF}^{commit}")" \
        || ci_die "cannot resolve ref '$REF'"
    SHORT="${SHA:0:7}"
    if ! git -C "$ROOT" merge-base --is-ancestor "$SHA" origin/master; then
        if [ "$ALLOW_UNMERGED" -eq 1 ]; then
            [ -n "$(git -C "$ROOT" branch -r --contains "$SHA" --list 'origin/*' 2>/dev/null)" ] \
                || ci_die "$SHORT is not on GitHub at all — push it first"
            ci_warn "$SHORT is NOT on origin/master (--allow-unmerged)"
        else
            ci_die "$SHORT is not on origin/master — merge the PR first, or pass --allow-unmerged"
        fi
    fi
    ci_log "shipping $SHORT  $(git -C "$ROOT" log -1 --format=%s "$SHA")"
}

# ------------------------------------------------------------------- status

status_server_script='
LIVE="${DIVE_LIVE_DIR:-$HOME/dive-analyser}"
cd "$LIVE" 2>/dev/null || { echo "live dir $LIVE missing"; exit 0; }
git fetch --quiet origin 2>/dev/null || echo "  (fetch from GitHub failed)"
head="$(git rev-parse --short HEAD)"
branch="$(git symbolic-ref --short -q HEAD || echo detached)"
dirty="$(git status --porcelain | wc -l | tr -d " ")"
behind="$(git rev-list --count HEAD..origin/master 2>/dev/null || echo ?)"
ahead="$(git rev-list --count origin/master..HEAD 2>/dev/null || echo ?)"
echo "  live checkout   $LIVE @ $head ($branch)  behind master: $behind  ahead: $ahead  dirty files: $dirty"
echo "  origin          $(git remote get-url origin 2>/dev/null || echo "<none>")"
for c in dive-analyser-backend-1 dive-analyser-frontend-1; do
    label="$(docker inspect "$c" --format "{{index .Config.Labels \"dive.analyser/sha\"}}" 2>/dev/null)"
    state="$(docker inspect "$c" --format "{{.State.Status}}" 2>/dev/null || echo missing)"
    echo "  $c  image sha: ${label:-unlabeled (built before ci/deploy.sh)}  state: $state"
done
log="$HOME/.cache/dive-ci/deploys.log"
[ -f "$log" ] && { echo "  last deploys:"; tail -n 3 "$log" | sed "s/^/    /"; }
exit 0
'

status_mac_script='
BASE=/Users/Shared/services/data/diveanalyzer
sha="$(cat "$BASE/code/.deployed-sha" 2>/dev/null || echo "unknown (installed before ci/ship.sh)")"
echo "  agent code      $BASE/code @ $sha"
launchctl print "gui/$(id -u)/com.diveanalyzer.agent" 2>/dev/null \
    | awk "/^\tstate =|^\tpid =|^\tlast exit code =/ {sub(/^\t/, \"\"); printf \"  %s\n\", \$0}"
log="$BASE/releases/deploys.log"
[ -f "$log" ] && { echo "  last deploys:"; tail -n 3 "$log" | sed "s/^/    /"; }
exit 0
'

do_status() {
    origin_is_github || ci_warn "this checkout's origin is not GitHub"
    git -C "$ROOT" fetch --quiet --prune origin || ci_warn "git fetch origin failed"
    ci_step "GitHub (source of truth)"
    printf '  origin/master   %s\n' "$(git -C "$ROOT" log -1 --format='%h %s (%cr)' origin/master)"
    ci_step "this checkout ($(hostname -s))"
    printf '  %s @ %s (%s)\n' "$ROOT" "$(git -C "$ROOT" rev-parse --short HEAD)" \
        "$(git -C "$ROOT" symbolic-ref --short -q HEAD || echo detached)"
    ci_step "server ($SERVER_SSH)"
    run_on server "$status_server_script" || ci_warn "server unreachable"
    ci_step "mac worker ($MAC_SSH)"
    run_on mac "$status_mac_script" || ci_warn "mac unreachable"
}

# ------------------------------------------------------------------- server

# Args: sha dry_run force [deploy.sh flags...]
server_script='
set -uo pipefail
# Runtime upload secrets live outside the deployed checkout. Export them for
# Compose on deploy and rollback; never echo or trace their values.
UPLOAD_ENV="$HOME/.config/diveanalyzer/browser-upload.env"
if [ -f "$UPLOAD_ENV" ]; then
    set -a
    . "$UPLOAD_ENV"
    set +a
fi
sha="$1"; dry_run="$2"; force="$3"; shift 3
LIVE="${DIVE_LIVE_DIR:-$HOME/dive-analyser}"
STATE="$HOME/.cache/dive-ci"; mkdir -p "$STATE"
LOCK="$STATE/deploy.lock"
cd "$LIVE" || { echo "✗ live dir $LIVE missing"; exit 3; }

# Lock before reading any state, so a concurrent deploy cannot change HEAD or
# the images between our snapshot and our rollback.
if [ "$dry_run" != 1 ]; then
    mkdir "$LOCK" 2>/dev/null || { echo "✗ another deploy holds $LOCK (remove it if stale)"; exit 3; }
    trap "rmdir \"$LOCK\"" EXIT
fi

case "$(git remote get-url origin 2>/dev/null)" in
    https://github.com/maxime-c16/dive-analyser|https://github.com/maxime-c16/dive-analyser.git) ;;
    git@github.com:maxime-c16/dive-analyser|git@github.com:maxime-c16/dive-analyser.git) ;;
    ssh://git@github.com/maxime-c16/dive-analyser|ssh://git@github.com/maxime-c16/dive-analyser.git) ;;
    *) echo "✗ $LIVE origin is not GitHub — run the one-time migration in docs/REPO_WORKFLOW.md"; exit 3 ;;
esac
# A failing `git status` (e.g. core.bare flipped to true) must not read as clean.
if [ "$(git rev-parse --is-inside-work-tree 2>/dev/null)" != true ]; then
    echo "✗ $LIVE is not a usable work tree (git config core.bare = $(git config core.bare))."
    echo "  If core.bare is true, fix with: git -C $LIVE config core.bare false"
    exit 3
fi
porcelain="$(git status --porcelain)" || { echo "✗ git status failed in $LIVE"; exit 3; }
if [ -n "$porcelain" ]; then
    echo "✗ $LIVE has local changes. The live checkout is deploy-only; move this work"
    echo "  to a worktree (docs/REPO_WORKFLOW.md) and retry:"
    git status --short | head -20 | sed "s/^/    /"
    exit 3
fi

git fetch --quiet --prune origin || { echo "✗ server cannot fetch GitHub"; exit 3; }
git cat-file -e "$sha^{commit}" 2>/dev/null || { echo "✗ $sha not found after fetch"; exit 3; }
prev="$(git rev-parse HEAD)"
if [ -z "$(git branch -r --contains "$prev" --list "origin/*" 2>/dev/null)" ]; then
    echo "✗ live HEAD ${prev:0:7} is not on GitHub (someone committed in the live dir)."
    echo "  Push it from a worktree first so it is not lost, then retry."
    exit 3
fi
# HEAD alone is not deployment state (a --frontend-only deploy moves HEAD but
# leaves the backend image old), so also require every requested service to
# run an image labelled with this commit.
services="frontend backend"
case " $* " in
    *" --frontend-only "*) services="frontend" ;;
    *" --backend-only "*)  services="backend" ;;
esac
up_to_date=0
if [ "$prev" = "$sha" ]; then
    up_to_date=1
    for svc in $services; do
        label="$(docker inspect "dive-analyser-$svc-1" --format "{{index .Config.Labels \"dive.analyser/sha\"}}" 2>/dev/null)"
        case "$sha" in "$label"?*|"$label") [ -n "$label" ] || up_to_date=0 ;; *) up_to_date=0 ;; esac
    done
fi
if [ "$up_to_date" = 1 ] && [ "$force" != 1 ]; then
    echo "✓ server already at ${sha:0:7} ($services) — nothing to do (use --force to redeploy)"
    exit 0
fi

echo "  ${prev:0:7} -> ${sha:0:7}"
changed="$(git diff --name-only "$prev" "$sha")"
echo "$changed" | grep -q "^backend/migrations/" && \
    echo "! backend/migrations/ changed — SQL migrations are NOT applied automatically; apply them by hand"
echo "$changed" | grep -qE "^(docker-compose\.yml|nginx/)" && \
    echo "! docker-compose.yml or nginx/ changed — after deploy: docker-compose up -d nginx (or exec nginx nginx -s reload)"
echo "$changed" | grep -q "^ops/tailscale/" && \
    echo "! ops/tailscale/ changed — recreate the public proxy: docker-compose -f ops/tailscale/docker-compose.yml -p dive-funnel up -d --force-recreate"
echo "$changed" | grep -q "^mac-agent/" && \
    echo "! mac-agent/ changed — the worker needs its own deploy: ci/ship.sh mac"

if [ "$dry_run" = 1 ]; then
    echo "  dry run: would check out ${sha:0:7} (detached) in $LIVE and run ci/deploy.sh $*"
    exit 0
fi

backend_container() { docker inspect -f "{{.Id}}" dive-analyser-backend-1 2>/dev/null; }
backend_before="$(backend_container)"
git checkout --quiet --detach "$sha" || { echo "✗ checkout failed"; exit 3; }
DIVE_DEPLOY_ROOT="$LIVE" ./ci/deploy.sh "$@"
rc=$?
if [ "$rc" -ne 0 ]; then
    git checkout --quiet --detach "$prev"
    if [ "$(backend_container)" = "$backend_before" ]; then
        # Failed before the swap (gate/build): the running backend was never
        # touched, so restarting it would only cause downtime.
        echo "✗ deploy failed before the swap — nothing restarted; live checkout back at ${prev:0:7}"
    else
        # ci/deploy.sh restored the previous images; the backend also
        # bind-mounts ./backend from this checkout, so recreate it on the
        # restored source and point both proxies at the new container.
        docker-compose up -d --no-deps --force-recreate backend >/dev/null 2>&1
        for c in dive-analyser-nginx-1 dive-funnel-funnel-proxy-1; do
            docker exec "$c" nginx -s reload >/dev/null 2>&1
        done
        echo "✗ deploy failed — live checkout and backend restored to ${prev:0:7}"
    fi
    result="FAILED"
else
    result="ok"
fi
printf "%s server %s -> %s %s by %s\n" "$(date -u +%FT%TZ)" "${prev:0:7}" "${sha:0:7}" "$result" "${SHIP_FROM:-?}" >>"$STATE/deploys.log"
exit "$rc"
'

do_server() {
    ci_step "server: deploy $SHORT"
    run_on server "$server_script" "$SHA" "$DRY_RUN" "$FORCE" "${DEPLOY_FLAGS[@]+"${DEPLOY_FLAGS[@]}"}"
}

# ---------------------------------------------------------------------- mac

# The Mac has no GitHub credentials, so the exact commit is streamed to it
# with git archive into a per-invocation stage dir. Args: sha dry_run force stage
mac_script='
set -uo pipefail
sha="$1"; dry_run="$2"; force="$3"; STAGE="$4"
BASE=/Users/Shared/services/data/diveanalyzer
CODE="$BASE/code"
VENV="$BASE/venv"
REL="$BASE/releases"
LABEL=com.diveanalyzer.agent
SVC="gui/$(id -u)/$LABEL"
LOCK="$REL/deploy.lock"

# Lock before reading prev/need_pip so a concurrent deploy cannot invalidate
# them. The stage dir is unique to this invocation, so cleanup is always safe.
if [ "$dry_run" != 1 ]; then
    mkdir "$LOCK" 2>/dev/null || { echo "✗ another deploy holds $LOCK (remove it if stale)"; rm -rf "$STAGE"; exit 3; }
    trap "rm -rf \"$STAGE\"; rmdir \"$LOCK\"" EXIT
else
    trap "rm -rf \"$STAGE\"" EXIT
fi

prev="$(cat "$CODE/.deployed-sha" 2>/dev/null || echo unknown)"
if [ "$prev" = "$sha" ] && [ "$force" != 1 ]; then
    echo "✓ mac agent already at ${sha:0:7} — nothing to do (use --force to redeploy)"
    exit 0
fi
[ -d "$STAGE/mac-agent/src" ] || { echo "✗ staged code missing at $STAGE"; exit 3; }

echo "  ${prev:0:7} -> ${sha:0:7}"
cmp -s "$STAGE/mac-agent/requirements.txt" "$CODE/requirements.txt" && need_pip=0 || need_pip=1
[ "$need_pip" = 1 ] && echo "! requirements.txt differs — dependencies will be reinstalled"
diff -rq -x __pycache__ "$CODE/src" "$STAGE/mac-agent/src" 2>/dev/null | sed "s/^/    /" | head -20

if [ "$dry_run" = 1 ]; then
    echo "  dry run: would sync mac-agent/ into $CODE and restart $LABEL"
    exit 0
fi

backup="$REL/code-backup-$(date +%Y%m%dT%H%M%S)-${prev:0:7}.tgz"
tar -czf "$backup" -C "$BASE" --exclude "__pycache__" --exclude "code/logs" code \
    || { echo "✗ backup failed — nothing changed"; exit 3; }
echo "  backup: $backup"
# The LaunchAgent runs $VENV/bin/python, so a dependency change must roll back
# together with the code. APFS clone (cp -c) makes this snapshot near-free.
if [ "$need_pip" = 1 ]; then
    rm -rf "$VENV.rollback"
    cp -cR "$VENV" "$VENV.rollback" 2>/dev/null || cp -R "$VENV" "$VENV.rollback" \
        || { echo "✗ venv snapshot failed — nothing changed"; exit 3; }
fi

restore() {
    echo "✗ $1 — restoring previous code"
    rm -rf "$CODE.failed" && mv "$CODE" "$CODE.failed" && tar -xzf "$backup" -C "$BASE"
    [ -d "$CODE.failed/logs" ] && mv "$CODE.failed/logs" "$CODE/logs" 2>/dev/null
    rm -rf "$CODE.failed"
    if [ "$need_pip" = 1 ] && [ -d "$VENV.rollback" ]; then
        rm -rf "$VENV" && mv "$VENV.rollback" "$VENV"
    fi
    launchctl kickstart -k "$SVC"
    printf "%s mac %s -> %s FAILED (%s) by %s\n" "$(date -u +%FT%TZ)" "${prev:0:7}" "${sha:0:7}" "$1" "${SHIP_FROM:-?}" >>"$REL/deploys.log"
    exit 1
}

# src/ mirrors the repo exactly; top-level files are updated but local-only
# extras (logs, old backups) are left alone.
rsync -a --delete --exclude __pycache__ "$STAGE/mac-agent/src/" "$CODE/src/" || restore "rsync src failed"
rsync -a --exclude /src/ --exclude /logs/ --exclude __pycache__ "$STAGE/mac-agent/" "$CODE/" || restore "rsync failed"
if [ "$need_pip" = 1 ]; then
    "$BASE/venv/bin/pip" install --quiet --disable-pip-version-check -r "$CODE/requirements.txt" \
        || restore "pip install failed"
fi
echo "$sha" >"$CODE/.deployed-sha"

launchctl kickstart -k "$SVC" || restore "launchctl kickstart failed"
# KeepAlive relaunches a crashing agent with a new pid, so a pid that stays
# put across 20 s means it survived startup.
sleep 10
pid1="$(launchctl print "$SVC" | awk "/^\tpid =/ {print \$3}")"
sleep 20
pid2="$(launchctl print "$SVC" | awk "/^\tpid =/ {print \$3}")"
if [ -z "$pid1" ] || [ "$pid1" != "$pid2" ]; then
    tail -n 15 /Users/Shared/services/logs/diveanalyzer/agent.error.log 2>/dev/null | sed "s/^/    /"
    restore "agent not stable after restart (pid $pid1 -> $pid2)"
fi
echo "✓ agent running (pid $pid2) at ${sha:0:7}"

rm -rf "$VENV.rollback"
ls -1t "$REL"/code-backup-*.tgz 2>/dev/null | tail -n +6 | while read -r old; do rm -f "$old"; done
printf "%s mac %s -> %s ok by %s\n" "$(date -u +%FT%TZ)" "${prev:0:7}" "${sha:0:7}" "${SHIP_FROM:-?}" >>"$REL/deploys.log"
exit 0
'

do_mac() {
    ci_step "mac: deploy agent $SHORT"
    local stage="/Users/Shared/services/data/diveanalyzer/releases/incoming-$SHORT-$$-$RANDOM"
    git -C "$ROOT" archive --format=tar "$SHA" mac-agent \
        | pipe_to mac "mkdir -p '$stage' && LC_ALL=C tar -x -C '$stage'" \
        || ci_die "could not stage $SHORT on the mac"
    run_on mac "$mac_script" "$SHA" "$DRY_RUN" "$FORCE" "$stage"
}

# --------------------------------------------------------------------- main

SHIP_FROM="$(whoami)@$(hostname -s)"
export SHIP_FROM

case "$cmd" in
    status) do_status ;;
    server) resolve_ref; do_server ;;
    mac)    resolve_ref; do_mac ;;
    all)
        resolve_ref
        do_server || ci_die "server deploy failed — mac not touched"
        do_mac
        ;;
esac
