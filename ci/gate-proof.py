#!/usr/bin/env python3
"""Prove that GitHub's required `gate` check already passed on this exact tree.

A master commit is deployable without re-running the server gate when the
commit itself, or the head of the pull request that produced it, has a
successful `gate` check run from GitHub Actions *and* the same git tree. Same
tree means byte-identical sources, so the GitHub result covers what ships.

Prints one line describing the proof and exits 0, or prints why there is no
proof and exits 1. Any network or API error is "no proof": the caller then
runs the gate itself, so this can only ever skip work, never weaken it.

    ci/gate-proof.py <full-sha> [--repo owner/name] [--root <checkout>]
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.request

API = 'https://api.github.com'
GATE_CHECK = 'gate'
GITHUB_ACTIONS_APP = 'github-actions'
TIMEOUT = 10


class NoProof(Exception):
    pass


def token():
    if os.environ.get('GITHUB_TOKEN'):
        return os.environ['GITHUB_TOKEN']
    try:
        return subprocess.run(['gh', 'auth', 'token'], capture_output=True, text=True,
                              timeout=TIMEOUT).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def make_fetch(repo):
    auth = token()

    def fetch(path):
        req = urllib.request.Request(f'{API}/repos/{repo}/{path}', headers={
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
            **({'Authorization': f'Bearer {auth}'} if auth else {}),
        })
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return json.load(resp)
        except Exception as exc:  # network, HTTP or JSON: all mean "no proof"
            raise NoProof(f'GitHub API {path}: {exc}') from exc

    return fetch


def gate_passed(fetch, sha):
    runs = fetch(f'commits/{sha}/check-runs?check_name={GATE_CHECK}&per_page=100')
    return any(
        run.get('head_sha') == sha
        and run.get('name') == GATE_CHECK
        and run.get('status') == 'completed'
        and run.get('conclusion') == 'success'
        and (run.get('app') or {}).get('slug') == GITHUB_ACTIONS_APP
        for run in runs.get('check_runs', [])
    )


def find_proof(fetch, sha, tree):
    """Return a description of the proof, or raise NoProof."""
    candidates = [(sha, 'commit')]
    for pr in fetch(f'commits/{sha}/pulls'):
        if pr.get('merged_at') and pr.get('head', {}).get('sha'):
            candidates.append((pr['head']['sha'], f"PR #{pr['number']} head"))
    for cand, label in candidates:
        cand_tree = tree if cand == sha else fetch(f'git/commits/{cand}')['tree']['sha']
        if cand_tree != tree:
            continue
        if gate_passed(fetch, cand):
            return f'{label} {cand[:7]} passed the GitHub gate on an identical tree'
    raise NoProof('no commit with this exact tree has a green GitHub gate')


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('sha')
    parser.add_argument('--repo', default='maxime-c16/dive-analyser')
    parser.add_argument('--root', default='.')
    args = parser.parse_args()
    try:
        sha = subprocess.check_output(['git', '-C', args.root, 'rev-parse', '--verify', f'{args.sha}^{{commit}}'],
                                      text=True).strip()
        tree = subprocess.check_output(['git', '-C', args.root, 'rev-parse', f'{sha}^{{tree}}'], text=True).strip()
        print(find_proof(make_fetch(args.repo), sha, tree))
        return 0
    except subprocess.CalledProcessError:
        print(f'cannot resolve {args.sha} locally')
    except NoProof as exc:
        print(exc)
    return 1


if __name__ == '__main__':
    sys.exit(main())
