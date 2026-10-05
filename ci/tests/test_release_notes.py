import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('release_notes', Path(__file__).resolve().parents[1] / 'release-notes.py')
notes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notes)


class ReleaseNotesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git('init', '-q')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('config', 'user.name', 'test')
        (self.root / 'base').write_text('base')
        self.base = self.commit()
        (self.root / notes.NOTE_DIR).mkdir(parents=True)
        self.note = dict(id='first', date='2026-10-05', title='New feature', body='Available now.', audience='all', components=['frontend', 'backend'])
        self.write(self.note)
        self.first = self.commit()

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], text=True).strip()

    def commit(self):
        self.git('add', '.')
        self.git('commit', '-qm', 'test')
        return self.git('rev-parse', 'HEAD')

    def write(self, note):
        (self.root / notes.NOTE_DIR / (note['id'] + '.json')).write_text(json.dumps(note))

    def build(self, frontend, backend):
        return notes.build(self.root, dict(frontend=frontend, backend=backend))

    def test_partial_delivery_does_not_announce_full_feature(self):
        self.assertEqual(self.build(self.first, self.base)['notes'], [])
        self.assertEqual(self.build(self.base, self.first)['notes'], [])
        self.assertEqual(self.build(self.first, self.first)['notes'], [self.note])

    def test_multiple_updates_are_deduplicated_and_rollback_removes_future_notes(self):
        second = {**self.note, 'id': 'second', 'components': ['backend']}
        self.write(second)
        current = self.commit()
        self.assertEqual(len(self.build(current, current)['notes']), 2)
        self.assertEqual(self.build(current, self.first)['notes'], [self.note])
        self.assertEqual(self.build(self.first, self.first), self.build(self.first, self.first))

    def test_immutable_notes_reject_edits(self):
        self.write({**self.note, 'title': 'Changed'})
        with self.assertRaises(ValueError):
            notes.check_tree(self.root)
        self.commit()
        with self.assertRaises(ValueError):
            self.build(self.first, 'HEAD')

    def test_note_schema_rejects_invalid_dependencies_and_ids(self):
        for bad in [dict(components=[]), dict(components=['mac']), dict(audience='secret'), dict(title=''), dict(id='../first'), dict(date='20261005')]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                notes.validate({**self.note, **bad}, 'first.json')

    def test_published_note_cannot_be_deleted(self):
        (self.root / notes.NOTE_DIR / 'first.json').unlink()
        with self.assertRaises(ValueError):
            notes.check_tree(self.root)

    def test_legacy_unlabeled_services_do_not_block_partial_deployment(self):
        frontend_note = {**self.note, 'id': 'frontend-only', 'components': ['frontend']}
        self.write(frontend_note)
        current = self.commit()
        for unknown in ['', '<no value>', 'unreachable-sha']:
            with self.subTest(unknown=unknown):
                self.assertEqual(self.build(current, unknown)['notes'], [frontend_note])
                self.assertEqual(self.build(unknown, current)['notes'], [])
                command = ['python3', str(Path(notes.__file__)), 'build', '--root', str(self.root),
                           '--frontend', current, '--backend', unknown]
                self.assertEqual(json.loads(subprocess.check_output(command, text=True))['notes'], [frontend_note])
