#!/usr/bin/env python3
"""Select checks from changed paths; unknown inputs fail closed to all tiers."""
import argparse
import json
import os
import subprocess
import sys

ALL = ('fast', 'frontend', 'backend', 'agent', 'postgres', 'images')


def select(paths):
    tiers = {'fast'}
    for path in paths:
        if (path.startswith('backend/release-notes/') and path.endswith('.json')) or path.startswith(('docs/', 'design/', 'memory/', 'tools/')) or path.endswith('.md'):
            continue
        if path.startswith(('ci/', '.github/workflows/')):
            tiers.update(ALL)
        elif path.startswith('frontend/'):
            tiers.add('frontend')
            if path.startswith('frontend/Dockerfile') or path in ('frontend/package.json', 'frontend/package-lock.json'):
                tiers.add('images')
        elif path.startswith(('backend/', 'layer2/', 'docker/')):
            tiers.update(('backend', 'postgres'))
            if path in ('backend/requirements.txt', 'backend/Dockerfile'):
                tiers.add('images')
        elif path.startswith('mac-agent/'):
            tiers.add('agent')
        elif path == 'docker-compose.yml' or path.startswith('nginx/'):
            tiers.update(('frontend', 'backend', 'postgres', 'images'))
        elif path.startswith('ops/'):
            # Shell syntax is checked by fast; deployment behavior still needs review.
            if path.startswith('ops/tailscale/'):
                tiers.add('images')
        elif path in ('.gitignore', '.gitattributes', '.github/pull_request_template.md', 'LICENSE'):
            continue
        else:
            tiers.update(ALL)
    return [tier for tier in ALL if tier in tiers]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base')
    parser.add_argument('--head')
    parser.add_argument('--github-output', action='store_true')
    parser.add_argument('paths', nargs='*')
    args = parser.parse_args()
    if bool(args.base) != bool(args.head):
        parser.error('--base and --head must be supplied together')
    if args.base:
        try:
            paths = subprocess.check_output(['git', 'diff', '--name-only', '-z', args.base, args.head, '--']).decode().split('\0')
            tiers = select(p for p in paths if p)
        except (subprocess.CalledProcessError, UnicodeError):
            tiers = list(ALL)
    else:
        tiers = select(args.paths)
    if args.github_output:
        workers = [t for t in tiers if t not in ('fast', 'postgres')]
        with open(os.environ['GITHUB_OUTPUT'], 'a') as out:
            out.write(f'matrix={json.dumps({"tier": workers or ["fast"]})}\n')
            out.write(f'postgres={str("postgres" in tiers).lower()}\n')
            out.write(f'checks={str(bool(workers)).lower()}\n')
        print('Selected tiers: ' + ' '.join(tiers))
    else:
        print(' '.join(tiers))


if __name__ == '__main__':
    main()
