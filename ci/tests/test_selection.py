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

    def test_complete_diff_keeps_earlier_commits_and_deleted_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
            def git(*args):
                return subprocess.check_output(['git', *args], cwd=root, env=env, text=True).strip()
            git('init', '-q')
            git('config', 'user.name', 'CI test')
            git('config', 'user.email', 'ci@example.invalid')
            (root / 'backend').mkdir()
            path = root / 'backend/name with spaces.py'
            path.write_text('legacy')
            git('add', '.')
            git('commit', '-qm', 'base')
            base = git('rev-parse', 'HEAD')
            path.unlink()
            git('add', '-A')
            git('commit', '-qm', 'delete backend module')
            (root / 'README.md').write_text('docs tip')
            git('add', '.')
            git('commit', '-qm', 'docs')
            output = root / 'outputs'
            subprocess.run(['python3', str(CI / 'select-tiers.py'), '--base', base,
                            '--head', git('rev-parse', 'HEAD'), '--github-output'], cwd=root,
                           env=dict(env, GITHUB_OUTPUT=str(output)), check=True, capture_output=True)
            data = dict(line.split('=', 1) for line in output.read_text().splitlines())
            self.assertEqual(data['postgres'], 'true')
            self.assertEqual(json.loads(data['matrix']), {'tier': ['backend']})

    def test_empty_diff_still_has_a_runnable_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'outputs'
            subprocess.run(['python3', str(CI / 'select-tiers.py'), '--github-output'],
                           env=dict(os.environ, GITHUB_OUTPUT=str(output)), check=True, capture_output=True)
            data = dict(line.split('=', 1) for line in output.read_text().splitlines())
            self.assertEqual(json.loads(data['matrix']), {'tier': ['fast']})
            self.assertEqual(data['postgres'], 'false')
            self.assertEqual(data['checks'], 'false')


class AggregateTests(unittest.TestCase):
    def test_postgres_major_version_matches_deployment(self):
        import yaml
        workflow = yaml.safe_load((CI.parent / '.github/workflows/ci.yml').read_text())
        compose = yaml.safe_load((CI.parent / 'docker-compose.yml').read_text())
        self.assertEqual(workflow['jobs']['postgres']['services']['postgres']['image'],
                         compose['services']['postgres']['image'])

    def test_actual_gate_shell_rejects_failed_cancelled_or_missing_checks(self):
        # Exercise the shell shipped in the workflow, including skipped-job handling.
        import yaml
        workflow = yaml.safe_load((CI.parent / '.github/workflows/ci.yml').read_text())
        job = workflow['jobs']['gate']
        self.assertEqual(job['if'], 'always()')
        self.assertEqual(set(job['needs']), {'plan', 'checks', 'postgres'})
        script = job['steps'][0]['run']
        for plan, checks, postgres in itertools.product(['success', 'failure', 'cancelled', 'skipped'], repeat=3):
            for required, checks_required in itertools.product(['true', 'false', ''], repeat=2):
                env = dict(os.environ, PLAN=plan, CHECKS=checks, POSTGRES=postgres,
                           POSTGRES_REQUIRED=required, CHECKS_REQUIRED=checks_required)
                run = subprocess.run(['bash', '-e', '-c', script], env=env, capture_output=True)
                expected = (required in ('true', 'false') and checks_required in ('true', 'false')
                            and plan == 'success'
                            and checks == ('success' if checks_required == 'true' else 'skipped')
                            and postgres == ('success' if required == 'true' else 'skipped'))
                self.assertEqual(run.returncode == 0, expected, (plan, checks, postgres, required, checks_required))


class TierInvocationTests(unittest.TestCase):
    def test_hosted_tier_omits_fast_and_local_command_keeps_it(self):
        # Execute the real argument dispatcher with stubbed expensive tiers.
        # This exercises the CLI boundary without installing application packages.
        source = (CI / 'gate.sh').read_text()
        main = source[source.index('main() {'):source.rindex('\nmain "$@"')]
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, DIVE_CI_CACHE=tmp)
            script = '''
source "$1/lib.sh"
flock() { return 0; }
nproc() { echo 2; }
tier_fast() { echo FAST_SENTINEL; }
tier_backend() { echo BACKEND_SENTINEL; }
''' + main + '\nmain "${@:2}"\n'
            for args, expected in [(['--tier', 'backend'], ['BACKEND_SENTINEL']),
                                   (['backend'], ['FAST_SENTINEL', 'BACKEND_SENTINEL'])]:
                run = subprocess.run(['bash', '-c', script, '_', str(CI), *args],
                                     env=env, capture_output=True, text=True)
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertEqual([l for l in run.stdout.splitlines() if l.endswith('_SENTINEL')], expected)
            for args in [['--tier'], ['--tier', 'all'], ['--tier', 'backend', 'agent']]:
                run = subprocess.run(['bash', '-c', script, '_', str(CI), *args],
                                     env=env, capture_output=True, text=True)
                self.assertNotEqual(run.returncode, 0)
