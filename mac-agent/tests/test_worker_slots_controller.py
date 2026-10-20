"""Serialization and rollback safety of the operational slot controller."""
import importlib.util
from pathlib import Path
import stat
import subprocess
import sys
from types import SimpleNamespace

import pytest
import yaml


@pytest.fixture
def controller(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[2] / 'ops/media-worker-slots.py'
    spec = importlib.util.spec_from_file_location('worker_slots_controller', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    config = tmp_path / 'config.yaml'
    library = tmp_path / 'test.photoslibrary'
    library.mkdir()
    config.write_text(yaml.safe_dump({
        'server': {'url': 'https://example.invalid', 'api_key': 'test-placeholder'},
        'photos': {'library_path': str(library)},
        'media': {'max_jobs': 1},
    }))
    # A home with no default Photos library catches accidental host dependencies.
    monkeypatch.setenv('HOME', str(tmp_path / 'empty-home'))
    monkeypatch.setattr(module.shutil, 'disk_usage', lambda p: SimpleNamespace(free=50 * 1024**3))
    return module, config


def test_other_process_holding_lock_prevents_config_read_or_write(controller):
    module, config = controller
    original = config.read_bytes()
    code = "import fcntl,sys; f=open(sys.argv[1],'a'); fcntl.flock(f,fcntl.LOCK_EX); print('locked',flush=True); sys.stdin.read()"
    holder = subprocess.Popen([sys.executable, '-c', code, str(config.parent / '.media-config.lock')],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == 'locked'
        with pytest.raises(RuntimeError, match='Another managed'):
            module.update_slots(config, 2, apply=True)
        assert config.read_bytes() == original
        assert not list(config.parent.glob('config.pre-slots-*'))
    finally:
        holder.communicate('', timeout=5)
    assert module.update_slots(config, 2, apply=True)['changed']
    assert yaml.safe_load(config.read_text())['media']['max_jobs'] == 2
    backup, = config.parent.glob('config.pre-slots-*')
    assert backup.read_bytes() == original
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    assert stat.S_IMODE(config.stat().st_mode) == 0o600


def test_config_reloaded_after_lock_release_preserves_newer_edits(controller):
    module, config = controller
    module.update_slots(config, 2, apply=True)
    newer = yaml.safe_load(config.read_text())
    newer['server']['url'] = 'https://newer.example.invalid'
    config.write_text(yaml.safe_dump(newer))
    module.update_slots(config, 1, apply=True)
    result = yaml.safe_load(config.read_text())
    assert result['server']['url'] == 'https://newer.example.invalid'
    assert result['media']['max_jobs'] == 1


def test_low_disk_refuses_increase_but_allows_rollback(controller, monkeypatch):
    module, config = controller
    module.update_slots(config, 2, apply=True)
    monkeypatch.setattr(module.shutil, 'disk_usage', lambda p: SimpleNamespace(free=1024))
    module.update_slots(config, 1, apply=True)
    original = config.read_bytes()
    with pytest.raises(SystemExit) as error:
        module.update_slots(config, 2, apply=True)
    assert error.value.code == 2
    assert config.read_bytes() == original


def test_backup_is_created_with_private_permissions_atomically(controller, monkeypatch):
    module, config = controller
    original_open = module.os.open
    backups = []
    def inspect_open(path, flags, mode=0o777, **kwargs):
        if Path(path).name.startswith('config.pre-slots-'):
            backups.append((flags, mode))
        return original_open(path, flags, mode, **kwargs)
    monkeypatch.setattr(module.os, 'open', inspect_open)
    module.update_slots(config, 2, apply=True)
    flags, mode = backups[0]
    assert flags & module.os.O_CREAT and flags & module.os.O_EXCL
    assert mode == 0o600
