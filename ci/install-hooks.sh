#!/bin/bash
# Install the pre-push CI hook.
#
# Git hooks live in the *main* repository's .git directory, not in the worktree
# and not in version control — so a fresh clone starts with no gate at all.
# That is why this script exists and why it must be re-run after cloning.
#
#   ci/install-hooks.sh            install / update the pre-push hook
#   ci/install-hooks.sh --uninstall
#
# The hook only runs the tiers whose inputs actually changed, so a docs-only
# push costs a second rather than four minutes.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(git rev-parse --show-toplevel)"
HOOKS_DIR="$(git rev-parse --git-path hooks)"
HOOK="$HOOKS_DIR/pre-push"

mkdir -p "$HOOKS_DIR"

if [ "${1:-}" = "--uninstall" ]; then
    [ -f "$HOOK" ] && { rm -f "$HOOK"; echo "removed $HOOK"; } || echo "no hook installed"
    exit 0
fi

# Skip clobbering a hook someone wrote by hand. An empty hook is treated as
# ours: a previous interrupted install can leave a zero-byte file behind.
if [ -f "$HOOK" ] && [ -s "$HOOK" ] && ! grep -q 'dive-analyser CI gate' "$HOOK"; then
    echo "error: $HOOK exists and was not installed by this script." >&2
    echo "       Merge it by hand, or move it aside and re-run." >&2
    exit 1
fi

# Build the hook in a temp file and move it into place, so an error while
# writing never leaves a truncated (or empty) hook in the git directory.
HOOK_TMP="$HOOK.tmp.$$"
trap 'rm -f "$HOOK_TMP"' EXIT

cat >"$HOOK_TMP" <<HOOKEOF
#!/bin/bash
# dive-analyser CI gate (installed by ci/install-hooks.sh — do not edit here,
# edit ci/gate.sh and re-run the installer).
#
# Reads the ref updates git feeds on stdin and runs only the CI tiers whose
# source directories actually changed.
#
# This file lives in the shared main .git/hooks directory and is used by EVERY
# worktree of the repo, so the repo root must be resolved at runtime rather
# than baked in at install time.

set -uo pipefail

REPO="\$(git rev-parse --show-toplevel)"
GATE="\$REPO/ci/gate.sh"

if [ ! -x "\$GATE" ]; then
    echo "pre-push: \$GATE not found — skipping gate" >&2
    exit 0
fi

if [ "\${DIVE_CI_SKIP:-0}" = "1" ]; then
    echo "note: DIVE_CI_SKIP=1 — CI gate skipped"
    exit 0
fi

# Force the full suite:  DIVE_CI_TIERS="fast frontend backend images"
if [ -n "\${DIVE_CI_TIERS:-}" ]; then
    echo "note: DIVE_CI_TIERS set — running: \$DIVE_CI_TIERS"
    exec "\$GATE" "\$DIVE_CI_TIERS"
fi

# Collect the pushed range so we can pick tiers.
ZERO=0000000000000000000000000000000000000000
changed=""
while read -r _local_ref _local_sha _remote_ref _remote_sha; do
    if [ "\$_remote_sha" = "\$ZERO" ]; then
        # New branch: everything it contains is "changed".
        files="\$(git -C "\$REPO" diff-tree --no-commit-id --name-only -r "\$_local_sha" 2>/dev/null || true)"
    else
        # Note: quote both revisions and let the shell concatenate them. An embedded
        # backslash-quote would be a *literal* quote inside the double-quoted
        # string and produce an invalid revision, silently yielding no diff.
        files="\$(git -C "\$REPO" diff --name-only "\$_remote_sha...\$_local_sha" 2>/dev/null || true)"
    fi
    changed="\$changed \$files"
done

if [ -z "\${changed// /}" ]; then
    echo "note: could not determine changed files — running the default gate"
    exec "\$GATE"
fi

tiers="\$(printf '%s\n' \$changed | sort -u | xargs -r "\$GATE" tiers --)"
tiers="\${tiers:-fast}"

echo "note: changed paths map to tiers: \$tiers"
exec "\$GATE" \$tiers
HOOKEOF

chmod +x "$HOOK_TMP"
mv -f "$HOOK_TMP" "$HOOK"
trap - EXIT
echo "installed $HOOK"
echo
echo "The gate now runs on 'git push'. Escape hatches:"
echo "  DIVE_CI_SKIP=1 git push ...        # skip entirely"
echo "  DIVE_CI_TIERS='fast' git push ...  # force a specific tier set"
echo
echo "Remove with: ci/install-hooks.sh --uninstall"