#!/usr/bin/env python3
"""Compute the next release version and its change list.

The GitHub release workflow (`.github/workflows/release.yml`) runs this after a
merge to `master`. It derives a semantic version from conventional-commit
prefixes (`feat`, `fix`, `BREAKING CHANGE`, `!`) since the last `v*` tag, and
renders the release notes introduced in that window. The server derives the
*displayed* version from the tag itself (`git describe --tags --exact-match`),
so this file only has to agree with that convention, not run on the server.

Commands:
    next    print the next version tag (vX.Y.Z), or nothing + exit 1 if HEAD is
            already tagged or there is no history to release.
    body    print markdown of the release notes added since the last v* tag.

No third-party dependencies; safe to run on any hosted runner.
"""
import argparse
import json
import os
import re
import subprocess
from pathlib import Path

NOTE_DIR = 'backend/release-notes'
BASE_VERSION = 'v1.0.0'


def _git_env() -> dict:
    return {k: v for k, v in os.environ.items()
            if not k.startswith('GIT_') and not k.startswith('DIVE_CI_')}


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], env=_git_env(), text=True).strip()


def _try_git(root, *args):
    try:
        return subprocess.check_output(['git', '-C', str(root), *args], env=_git_env(),
                                       text=True, stderr=subprocess.DEVNULL).strip()
    except subprocess.CalledProcessError:
        return ''


def root_arg(args):
    return Path(args.root or Path(__file__).resolve().parents[1])


def last_tag(root):
    return _try_git(root, 'describe', '--tags', '--abbrev=0', '--match', 'v*')


def commits_since(root, since):
    fmt = '%H%x00%s%x00%b%x00'
    if since:
        return git(root, 'log', f'{since}..HEAD', f'--format={fmt}')
    return git(root, 'log', f'--format={fmt}')


def bump_level(subject, body):
    text = f'{subject}\n{body}'
    if 'BREAKING CHANGE:' in text:
        return 'major'
    # "type(scope)!: ..." or "type!: ..." is a breaking change.
    if re.match(r'^[a-zA-Z]+(?:\([^)]*\))?!:', subject):
        return 'major'
    if re.match(r'^feat(?:\([^)]*\))?:', subject):
        return 'minor'
    return 'patch'


def parse_version(tag):
    match = re.fullmatch(r'v(\d+)\.(\d+)\.(\d+)', tag or '')
    if not match:
        return (0, 0, 0)
    return tuple(int(part) for part in match.groups())


def bump(version, level):
    major, minor, patch = version
    if level == 'major':
        return f'v{major + 1}.0.0'
    if level == 'minor':
        return f'v{major}.{minor + 1}.0'
    return f'v{major}.{minor}.{patch + 1}'


def next_version(root):
    if _try_git(root, 'describe', '--tags', '--exact-match', '--match', 'v*', 'HEAD'):
        return ''  # HEAD already carries a release tag.
    since = last_tag(root)
    raw = commits_since(root, since)
    if not raw.strip():
        return ''  # No commits to release.
    levels = {'patch'}
    fields = raw.split('\x00')
    for i in range(0, len(fields) - 2, 3):
        subject, body = fields[i + 1], fields[i + 2]
        levels.add(bump_level(subject, body))
    level = 'major' if 'major' in levels else 'minor' if 'minor' in levels else 'patch'
    if not since:
        return BASE_VERSION
    return bump(parse_version(since), level)


def release_body(root):
    since = last_tag(root)
    if since:
        added = _try_git(root, 'diff', '--name-only', '--diff-filter=A',
                         f'{since}..HEAD', '--', NOTE_DIR)
    else:
        added = _try_git(root, 'ls-tree', '-r', '--name-only', 'HEAD', '--', NOTE_DIR)
    lines = []
    for path in sorted(added.splitlines()):
        if not path.endswith('.json'):
            continue
        raw = _try_git(root, 'show', f'HEAD:{path}')
        if not raw:
            continue
        try:
            note = json.loads(raw)
            lines.append(f"- **{note['title']}** — {note['body']}")
        except (ValueError, KeyError):
            continue
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['next', 'body'])
    parser.add_argument('--root', default=None)
    args = parser.parse_args()
    root = root_arg(args)
    if args.command == 'next':
        version = next_version(root)
        if not version:
            raise SystemExit(1)
        print(version)
        return
    print(release_body(root))


if __name__ == '__main__':
    main()
