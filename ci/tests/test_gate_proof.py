"""A deploy may skip the server gate only on an identical tree with a green GitHub gate."""
import importlib.util
from pathlib import Path
import unittest

CI = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('gate_proof', CI / 'gate-proof.py')
gate_proof = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate_proof)

MERGE, HEAD, TREE = 'm' * 40, 'h' * 40, 't' * 40


def run(sha, conclusion='success', name='gate', app='github-actions', status='completed'):
    return {'head_sha': sha, 'name': name, 'status': status, 'conclusion': conclusion, 'app': {'slug': app}}


def fake_github(head_tree=TREE, head_runs=(), merge_runs=(), merged=True):
    def fetch(path):
        if path == f'commits/{MERGE}/pulls':
            return [{'number': 7, 'merged_at': '2026-10-21T00:00:00Z' if merged else None, 'head': {'sha': HEAD}}]
        if path == f'git/commits/{HEAD}':
            return {'tree': {'sha': head_tree}}
        if path.startswith(f'commits/{HEAD}/check-runs'):
            return {'check_runs': list(head_runs)}
        if path.startswith(f'commits/{MERGE}/check-runs'):
            return {'check_runs': list(merge_runs)}
        raise gate_proof.NoProof(f'unexpected {path}')
    return fetch


class GateProofTests(unittest.TestCase):
    def test_green_pr_head_with_identical_tree_is_proof(self):
        proof = gate_proof.find_proof(fake_github(head_runs=[run(HEAD)]), MERGE, TREE)
        self.assertIn('PR #7 head hhhhhhh', proof)

    def test_green_gate_on_the_commit_itself_is_proof(self):
        self.assertIn('commit', gate_proof.find_proof(fake_github(merge_runs=[run(MERGE)]), MERGE, TREE))

    def test_different_tree_is_not_proof(self):
        # A PR merged without being up to date with master: master's tree was never tested.
        with self.assertRaises(gate_proof.NoProof):
            gate_proof.find_proof(fake_github(head_tree='x' * 40, head_runs=[run(HEAD)]), MERGE, TREE)

    def test_failed_pending_foreign_or_other_checks_are_not_proof(self):
        for runs in ([run(HEAD, 'failure')], [run(HEAD, None, status='in_progress')],
                     [run(HEAD, app='some-other-app')], [run(HEAD, name='checks (frontend)')], [run(HEAD, 'skipped')],
                     [run('o' * 40)], []):
            with self.subTest(runs=runs), self.assertRaises(gate_proof.NoProof):
                gate_proof.find_proof(fake_github(head_runs=runs), MERGE, TREE)

    def test_unmerged_pr_head_is_ignored(self):
        with self.assertRaises(gate_proof.NoProof):
            gate_proof.find_proof(fake_github(head_runs=[run(HEAD)], merged=False), MERGE, TREE)

    def test_api_failure_is_not_proof(self):
        def down(path):
            raise gate_proof.NoProof('GitHub API down')
        with self.assertRaises(gate_proof.NoProof):
            gate_proof.find_proof(down, MERGE, TREE)


if __name__ == '__main__':
    unittest.main()
