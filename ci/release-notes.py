#!/usr/bin/env python3
"""Validate immutable PR notes and build a catalog for actually running services."""
import argparse
import datetime
import json
import os
import re
import subprocess
from pathlib import Path

NOTE_DIR = 'backend/release-notes'
FIELDS = {'id', 'date', 'title', 'body', 'audience', 'components'}

def _git_env() -> dict:
    """Drop hook-exported GIT_* plumbing vars for -C based child calls.

    When release-notes.py runs from a pre-push hook, git exports GIT_DIR /
    GIT_INDEX_FILE which override the explicit `-C <path>` targets and make
    plumbing calls (rev-parse, add, commit in fixture repos) hit the real
    repository instead.
    """
    return {k: v for k, v in os.environ.items()
            if not k.startswith('GIT_') and not k.startswith('DIVE_CI_')}


def validate(note, filename):
    if not isinstance(note, dict) or set(note) != FIELDS:
        raise ValueError(f'{filename}: expected {sorted(FIELDS)}')
    if not isinstance(note['id'], str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', note['id']) or filename != note['id'] + '.json':
        raise ValueError(f'{filename}: id must match filename')
    if not isinstance(note['date'], str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', note['date']):
        raise ValueError(f'{filename}: date must use YYYY-MM-DD')
    datetime.date.fromisoformat(note['date'])
    for field, maximum in [('title', 100), ('body', 600)]:
        if not isinstance(note[field], str) or not 1 <= len(note[field].strip()) <= maximum:
            raise ValueError(f'{filename}: invalid {field}')
    if note['audience'] not in ('all', 'admin'):
        raise ValueError(f'{filename}: invalid audience')
    components = note['components']
    if not isinstance(components, list) or not components or any(c not in ('frontend', 'backend') for c in components) or len(set(components)) != len(components):
        raise ValueError(f'{filename}: components must list required server services')
    return note


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], env=_git_env(), text=True).strip()


def check_tree(root):
    baseline = 'origin/master'
    if subprocess.run(['git', '-C', str(root), 'rev-parse', '--verify', baseline], env=_git_env(),
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        baseline = 'HEAD'
    for filename in git(root, 'ls-tree', '-r', '--name-only', baseline, '--', NOTE_DIR).splitlines():
        if filename.endswith('.json') and not (root / filename).is_file():
            raise ValueError(f'{filename}: published notes cannot be deleted')
    for path in sorted((root / NOTE_DIR).glob('*.json')):
        validate(json.loads(path.read_text()), path.name)
        # Existing notes are immutable: corrections receive a new ID.
        additions = git(root, 'log', '--diff-filter=A', '--format=%H', 'HEAD', '--', str(path.relative_to(root))).splitlines()
        if additions:
            original = json.loads(git(root, 'show', f'{additions[-1]}:{path.relative_to(root)}'))
            if original != json.loads(path.read_text()):
                raise ValueError(f'{path.name}: published notes are immutable; create a new note')


def resolve_version(root, ref):
    """Version tag shown in the app. Prefer the tag pinned to the running
    frontend SHA; fall back to the newest reachable tag; else empty (quiet)."""
    if not ref:
        return ''
    for args in (('describe', '--tags', '--exact-match', '--match', 'v*', ref),
                 ('describe', '--tags', '--abbrev=0', '--match', 'v*', ref)):
        try:
            return subprocess.check_output(['git', '-C', str(root), *args], env=_git_env(),
                                           text=True, stderr=subprocess.DEVNULL).strip()
        except subprocess.CalledProcessError:
            continue
    return ''


def build(root, refs):
    resolved = {}
    for service, ref in refs.items():
        # Legacy images may be unlabeled, and an unreachable SHA cannot prove
        # feature availability. Omit their notes without blocking the rollout.
        try:
            resolved[service] = subprocess.check_output(
                ['git', '-C', str(root), 'rev-parse', '--verify', f'{ref}^{{commit}}'],
                env=_git_env(), text=True, stderr=subprocess.DEVNULL).strip()
        except subprocess.CalledProcessError:
            resolved[service] = ''
    refs = resolved
    candidates = {}
    for ref in set(refs.values()):
        if not ref:
            continue
        paths = git(root, 'ls-tree', '-r', '--name-only', ref, '--', NOTE_DIR).splitlines()
        for path in paths:
            if not path.endswith('.json'):
                continue
            note = validate(json.loads(git(root, 'show', f'{ref}:{path}')), Path(path).name)
            added = git(root, 'log', '--diff-filter=A', '--format=%H', ref, '--', path).splitlines()[-1]
            original = json.loads(git(root, 'show', f'{added}:{path}'))
            if original != note:
                raise ValueError(f'{path}: immutable note was modified')
            previous = candidates.get(note['id'])
            if previous and previous[0] != note:
                raise ValueError(f'{path}: conflicting note IDs')
            candidates[note['id']] = (note, added)
    notes = []
    for note, introduced in candidates.values():
        if all(refs.get(component) and subprocess.run(
            ['git', '-C', str(root), 'merge-base', '--is-ancestor', introduced, refs[component]],
            env=_git_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
               for component in note['components']):
            notes.append(note)
    notes.sort(key=lambda note: (note['date'], note['id']), reverse=True)
    if not refs.get('frontend'):
        notes = []  # No reliable frontend identity for the client version guard.
    version = resolve_version(root, refs['frontend'])
    return {'schema': 1, 'version': version, 'frontend_sha': refs['frontend'], 'notes': notes[:100]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['validate', 'build'])
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--frontend')
    parser.add_argument('--backend')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.command == 'validate':
        check_tree(args.root)
        return
    if args.frontend is None or args.backend is None:
        parser.error('build requires --frontend and --backend')
    manifest = build(args.root, {'frontend': args.frontend, 'backend': args.backend})
    rendered = json.dumps(manifest, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.write_text(rendered)
    else:
        print(rendered, end='')


if __name__ == '__main__':
    main()
