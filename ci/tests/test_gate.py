"""Regression checks for false greens and pushed-range selection; stdlib only."""
import contextlib
import io
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

CI = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('check_results', CI / 'check-results.py')
results = importlib.util.module_from_spec(spec)
spec.loader.exec_module(results)


class ResultsTests(unittest.TestCase):
    def setUp(self):
        self.capture = contextlib.ExitStack()
        self.addCleanup(self.capture.close)
        self.capture.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.capture.enter_context(contextlib.redirect_stderr(io.StringIO()))
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.report = Path(self.temp.name) / 'report.json'

    def write(self, status=1, collected=1, failed=True):
        self.report.write_text(json.dumps({'exitstatus': status, 'collected': collected,
            'outcomes': {'test.py::known': {'passed': not failed, 'failed': failed, 'skipped': False}}}))

    def test_any_failure_blocks(self):
        self.write()
        self.assertTrue(results.check(self.report, 1))

    def test_crash_incomplete_and_stale_reports_block(self):
        for status, collected, process in [(2, 1, 2), (1, 2, 1), (0, 1, 1), (1, 0, 1)]:
            with self.subTest(status=status, collected=collected, process=process):
                self.write(status, collected)
                with self.assertRaises(ValueError):
                    results.check(self.report, process)

    def test_clean_complete_run_passes(self):
        self.write(0, failed=False)
        self.assertFalse(results.check(self.report, 0))

    def test_missing_or_malformed_report_blocks(self):
        with self.assertRaises(OSError):
            results.check(self.report, 0)
        self.report.write_text('{}')
        with self.assertRaises(KeyError):
            results.check(self.report, 0)


class HookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_') and not k.startswith('DIVE_CI_')}
        self.git('init', '-q')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('config', 'user.name', 'CI test')
        (self.root / 'ci').mkdir()
        self.gate = self.root / 'ci/gate.sh'
        self.gate.write_text('#!/bin/bash\nif [ "$1" = tiers ]; then printf "fast"; for p in "${@:3}"; do case "$p" in backend/*) printf " backend";; esac; done; echo; else printf "%s\\n" "$*"; fi\n')
        self.gate.chmod(0o755)
        self.commit('initial')

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.root, env=self.env, text=True).strip()

    def commit(self, message):
        self.git('add', '.')
        self.git('commit', '-qm', message)
        return self.git('rev-parse', 'HEAD')

    def run_hook(self, old=None, new=None, ref="refs/heads/test"):
        zero = '0' * 40
        line = f'{ref} {new or self.git("rev-parse", "HEAD")} {ref} {old or zero}\n'
        return subprocess.run(['bash', str(CI / 'pre-push'), 'origin'], input=line,
                              cwd=self.root, env=self.env, text=True, capture_output=True)

    def test_new_branch_checks_earlier_commit(self):
        (self.root / 'backend').mkdir()
        (self.root / 'backend/earlier.py').write_text('')
        self.commit('backend change')
        (self.root / 'docs').mkdir()
        (self.root / 'docs/tip.md').write_text('')
        self.commit('docs tip')
        run = self.run_hook()
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn('backend', run.stdout)

    def test_annotated_tag_at_head_is_tested(self):
        self.git('tag', '-a', 'v1', '-m', 'release')
        tag_sha = self.git('rev-parse', 'v1')
        self.assertNotEqual(tag_sha, self.git('rev-parse', 'HEAD'))
        run = self.run_hook(new=tag_sha, ref='refs/tags/v1')
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn('fast', run.stdout)

    def test_dirty_tree_and_other_ref_block(self):
        old = self.git('rev-parse', 'HEAD')
        (self.root / 'dirty').write_text('')
        self.assertNotEqual(self.run_hook().returncode, 0)
        self.commit('later')
        self.assertNotEqual(self.run_hook(new=old).returncode, 0)

    def test_unknown_range_runs_full_gate(self):
        run = self.run_hook(old='1' * 40)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn('all', run.stdout)

    def test_delete_does_not_need_gate(self):
        self.gate.unlink()
        self.assertEqual(self.run_hook(new='0' * 40).returncode, 0)

    def test_missing_gate_blocks(self):
        self.gate.unlink()
        self.commit('remove gate')
        self.assertNotEqual(self.run_hook().returncode, 0)

    def test_tier_mapping_covers_gate_and_agent_changes(self):
        def tiers(*paths):
            return set(subprocess.check_output([str(CI / 'gate.sh'), 'tiers', '--', *paths],
                                               cwd=self.root, env=self.env, text=True).split())
        self.assertEqual(tiers('docs/readme.md'), {'fast'})
        self.assertEqual(tiers('mac-agent/src/metadata.py'), {'fast', 'agent'})
        self.assertEqual(tiers('ci/lib.sh'), {'fast', 'frontend', 'backend', 'agent'})
        self.assertEqual(tiers('frontend/Dockerfile.deploy'), {'fast', 'frontend', 'images'})

    def test_installer_preserves_unrelated_hook(self):
        hook = self.root / '.git/hooks/pre-push'
        hook.write_text('#!/bin/bash\necho custom\n')
        result = subprocess.run([str(CI / 'install-hooks.sh')], cwd=self.root,
                                env=self.env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(hook.read_text(), '#!/bin/bash\necho custom\n')

    def test_install_and_uninstall_preserve_managed_hook(self):
        subprocess.check_call([str(CI / 'install-hooks.sh')], cwd=self.root, env=self.env,
                              stdout=subprocess.DEVNULL)
        hook = self.root / '.git/hooks/pre-push'
        self.assertEqual(hook.read_bytes(), (CI / 'pre-push').read_bytes())
        subprocess.check_call([str(CI / 'install-hooks.sh'), '--uninstall'], cwd=self.root,
                              env=self.env, stdout=subprocess.DEVNULL)
        self.assertFalse(hook.exists())
        self.assertEqual(len(list(hook.parent.glob('pre-push.disabled.*'))), 1)


class EnvironmentCacheTests(unittest.TestCase):
    def test_requirements_change_creates_a_clean_environment(self):
        """Use real empty venvs: no package downloads needed for this check."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'ci').mkdir()
            (root / 'backend').mkdir()
            for req in [root / 'ci/requirements-agent.txt', root / 'backend/requirements.txt']:
                req.write_text('# first dependency set\n')
            env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
            env['DIVE_CI_CACHE'] = str(root / 'cache')
            subprocess.run(['git', 'init', '-q'], cwd=root, env=env, check=True)
            script = r"""
source "$1/lib.sh"
# Real environments, without ensurepip overhead: installation is mocked below.
python3() {
    if [ "$1" = -m ] && [ "$2" = venv ]; then
        command python3 -m venv --without-pip "$3"
    else
        command python3 "$@"
    fi
}
# Dependency content is comments only; skip network to test cache isolation.
ci_run() { return 0; }
for label in agent backend; do
    "ci_${label}_python"
    if [ "$label" = agent ]; then first=$CI_AGENT_PYTHON; req=ci/requirements-agent.txt;
    else first=$CI_BACKEND_PYTHON; req=backend/requirements.txt; fi
    "$first" -c 'from pathlib import Path; import sysconfig; Path(sysconfig.get_paths()["purelib"], "removed_dependency.py").write_text("stale = True")'
    printf '# second dependency set\n' >"$req"
    "ci_${label}_python"
    if [ "$label" = agent ]; then second=$CI_AGENT_PYTHON; else second=$CI_BACKEND_PYTHON; fi
    [ "$first" != "$second" ] || exit 1
    "$second" -c 'import importlib.util; assert importlib.util.find_spec("removed_dependency") is None'
    printf '# first dependency set\n' >"$req"
    "ci_${label}_python"
    if [ "$label" = agent ]; then reused=$CI_AGENT_PYTHON; else reused=$CI_BACKEND_PYTHON; fi
    [ "$first" = "$reused" ] || exit 1
done
"""
            run = subprocess.run(['bash', '-c', script, '_', str(CI)], cwd=root, env=env,
                                 capture_output=True, text=True, timeout=60)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


if __name__ == '__main__':
    unittest.main()
