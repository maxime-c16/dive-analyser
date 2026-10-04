#!/bin/bash
# Install the versioned pre-push gate in Git's hooks directory (all worktrees).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOKS_DIR="$(git rev-parse --git-path hooks)"
HOOK="$HOOKS_DIR/pre-push"
case "${1:-}" in
    ''|--uninstall) ;;
    *) echo "usage: ci/install-hooks.sh [--uninstall]" >&2; exit 1 ;;
esac
if [ -s "$HOOK" ] && ! grep -q 'dive-analyser CI gate' "$HOOK"; then
    echo "error: $HOOK is not managed by this installer; preserve and merge it manually" >&2
    exit 1
fi
if [ "${1:-}" = --uninstall ]; then
    [ ! -f "$HOOK" ] || mv "$HOOK" "$HOOK.disabled.$(date +%s).$$"
    echo "hook disabled (existing contents preserved)"
    exit 0
fi
mkdir -p "$HOOKS_DIR"
bash -n "$SCRIPT_DIR/pre-push"
HOOK_TMP=$(mktemp "$HOOKS_DIR/pre-push.tmp.XXXXXX")
trap 'unlink "$HOOK_TMP" 2>/dev/null || true' EXIT
cp "$SCRIPT_DIR/pre-push" "$HOOK_TMP"
chmod +x "$HOOK_TMP"
mv "$HOOK_TMP" "$HOOK"
trap - EXIT
echo "installed $HOOK (shared by worktrees; each needs ci/ in its checkout)"
