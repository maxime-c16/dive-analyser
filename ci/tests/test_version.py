import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('version', Path(__file__).resolve().parents[1] / 'version.py')
version = importlib.util.module_from_spec(spec)
spec.loader.exec_module(version)


def sanitized_env():
    return {k: v for k, v in os.environ.items() if not k.startswith('GIT_') and not k.startswith('DIVE_CI_')}


class VersionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git('init', '-q')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('config', 'user.name', 'test')

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], env=sanitized_env(), text=True).strip()

    def commit(self, message):
        self.git('add', '.')
        self.git('commit', '-q', '-m', message)
        return self.git('rev-parse', 'HEAD')

    def tag(self, name):
        self.git('tag', '-a', name, '-m', name)

    def seed(self):
        (self.root / 'file').write_text('base')
        self.commit('chore: seed')

    def change(self, name):
        (self.root / name).write_text(name)

    def test_bump_levels(self):
        self.assertEqual(version.bump_level('feat(x): y', ''), 'minor')
        self.assertEqual(version.bump_level('fix: y', ''), 'patch')
        self.assertEqual(version.bump_level('chore: y', ''), 'patch')
        self.assertEqual(version.bump_level('feat!: breaking', ''), 'major')
        self.assertEqual(version.bump_level('feat: y', 'BREAKING CHANGE: dropped'), 'major')

    def test_first_release_is_v100(self):
        self.seed()
        self.assertEqual(version.next_version(self.root), 'v1.0.0')

    def test_feat_bumps_minor(self):
        self.seed()
        self.tag('v1.0.0')
        self.change('a')
        self.commit('feat: add things')
        self.assertEqual(version.next_version(self.root), 'v1.1.0')

    def test_fix_bumps_patch(self):
        self.seed()
        self.tag('v1.2.3')
        self.change('a')
        self.commit('fix: bug')
        self.assertEqual(version.next_version(self.root), 'v1.2.4')

    def test_breaking_bumps_major(self):
        self.seed()
        self.tag('v1.2.3')
        self.change('a')
        self.commit('feat!: rewrite')
        self.assertEqual(version.next_version(self.root), 'v2.0.0')

    def test_already_tagged_is_empty(self):
        self.seed()
        self.tag('v1.0.0')
        self.assertEqual(version.next_version(self.root), '')

    def test_release_body_lists_notes(self):
        self.seed()
        (self.root / version.NOTE_DIR).mkdir(parents=True)
        (self.root / version.NOTE_DIR / 'first.json').write_text(
            '{"id":"first","date":"2026-10-05","title":"New","body":"Available.","audience":"all","components":["frontend"]}')
        self.commit('feat: note')
        body = version.release_body(self.root)
        self.assertIn('New', body)
        self.assertIn('Available.', body)


if __name__ == '__main__':
    unittest.main()
