"""Regression checks for skipped coverage and a falsely green aggregate gate."""
import importlib.util
import itertools
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

CI = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('select_tiers', CI / 'select-tiers.py')
selection = importlib.util.module_from_spec(spec)
spec.loader.exec_module(selection)


class SelectionTests(unittest.TestCase):
    def test_frontend_and_release_note_do_not_run_backend_or_agent(self):
        self.assertEqual(selection.select(['frontend/src/pages/Library.tsx',
                                          'backend/release-notes/search.json']), ['fast', 'frontend'])
        self.assertEqual(selection.select(['backend/release-notes/search.json']), ['fast'])
        # Only JSON catalog entries are documentation; executable files are code.
        self.assertIn('backend', selection.select(['backend/release-notes/script.py']))

    def test_unknown_and_ci_changes_run_every_check(self):
        for path in ['new-component/main.py', 'ci/gate.sh', '.github/workflows/ci.yml']:
            self.assertEqual(selection.select([path]), list(selection.ALL))

    def test_dependencies_and_proxies_build_images(self):
        for path in ['backend/requirements.txt', 'frontend/package-lock.json',
                     'frontend/package.json', 'docker-compose.yml', 'nginx/conf.d/default.conf',
                     'ops/tailscale/nginx.conf']:
            self.assertIn('images', selection.select([path]), path)
        self.assertIn('postgres', selection.select(['backend/app/api/v1/users.py']))
        self.assertEqual(selection.select(['mac-agent/src/agent.py']), ['fast', 'agent'])

    def test_bad_diff_fails_closed_and_outputs_are_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'outputs'
            env = dict(os.environ, GITHUB_OUTPUT=str(output))
            run = subprocess.run(['python3', str(CI / 'select-tiers.py'), '--base', 'invalid-base',
                                  '--head', 'invalid-head', '--github-output'], env=env, capture_output=True)
            self.assertEqual(run.returncode, 0)
            data = dict(line.split('=', 1) for line in output.read_text().splitlines())
            self.assertEqual(data['postgres'], 'true')
            self.assertEqual(set(json.loads(data['matrix'])['tier']), {'frontend', 'backend', 'agent', 'images'})

    def test_empty_diff_still_has_a_runnable_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'outputs'
            subprocess.run(['python3', str(CI / 'select-tiers.py'), '--github-output'],
                           env=dict(os.environ, GITHUB_OUTPUT=str(output)), check=True, capture_output=True)
            data = dict(line.split('=', 1) for line in output.read_text().splitlines())
            self.assertEqual(json.loads(data['matrix']), {'tier': ['fast']})
            self.assertEqual(data['postgres'], 'false')


class AggregateTests(unittest.TestCase):
    def test_actual_gate_shell_rejects_failed_cancelled_or_missing_checks(self):
        # Exercise the shell shipped in the workflow, including skipped-job handling.
        import yaml
        workflow = yaml.safe_load((CI.parent / '.github/workflows/ci.yml').read_text())
        job = workflow['jobs']['gate']
        self.assertEqual(job['if'], 'always()')
        self.assertEqual(set(job['needs']), {'plan', 'checks', 'postgres'})
        script = job['steps'][0]['run']
        for plan, checks, postgres in itertools.product(['success', 'failure', 'cancelled', 'skipped'], repeat=3):
            for required in ['true', 'false', '']:
                env = dict(os.environ, PLAN=plan, CHECKS=checks, POSTGRES=postgres, POSTGRES_REQUIRED=required)
                run = subprocess.run(['bash', '-e', '-c', script], env=env, capture_output=True)
                expected = plan == checks == 'success' and postgres == ('success' if required == 'true' else 'skipped')
                self.assertEqual(run.returncode == 0, expected, (plan, checks, postgres, required))
