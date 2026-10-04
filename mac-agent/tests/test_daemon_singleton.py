"""P4.3 daemon singleton guard tests (packet §19/§20).

A duplicate full `src.main` daemon instance was observed live during P4.2.
The guard is a pid/lock file with stale-owner verification; these tests
prove: acquire, refuse-live-owner, stale takeover (dead pid, recycled pid,
corrupt file), safe release, and that only full-daemon mode takes the lock.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.daemon_lock import (  # noqa: E402
    DaemonAlreadyRunning,
    acquire_daemon_lock,
    release_daemon_lock,
    _owner_is_live,
)


@pytest.fixture()
def lock_path(tmp_path):
    return tmp_path / "state" / "daemon.lock"


@pytest.fixture()
def live_daemon_record(monkeypatch):
    """Simulate a verified-live src.main owner without spawning a process.

    The ps-based verifier helpers are monkeypatched so the recorded owner
    resolves as alive, start-time-matched, and command-matched.
    """
    record = {
        "pid": 4242424242 % (2 ** 62) + 1,
        "start_time": "Mon 9 sep 2026 00:00:00",
        "command": "python -m src.main --config /x/config.yaml",
    }
    monkeypatch.setattr("src.daemon_lock._process_start_time", lambda pid: record["start_time"])
    monkeypatch.setattr("src.daemon_lock._process_command", lambda pid: record["command"])
    monkeypatch.setattr("src.daemon_lock._pid_alive", lambda pid: True)
    return record


def _write(path: Path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(content, indent=2) if isinstance(content, dict) else content,
        encoding="utf-8",
    )


def test_acquire_creates_lock_with_owner_identity(lock_path):
    holder = acquire_daemon_lock(lock_path)
    assert holder["pid"] > 0
    assert holder["command"]  # non-empty process command recorded
    assert holder["start_time"]  # real ps-derived start time recorded
    record = json.loads(lock_path.read_text())
    assert record["pid"] == holder["pid"]


def test_second_daemon_refuses_safely(lock_path, live_daemon_record):
    _write(lock_path, live_daemon_record)
    with pytest.raises(DaemonAlreadyRunning) as excinfo:
        acquire_daemon_lock(lock_path)
    assert excinfo.value.holder["pid"] == live_daemon_record["pid"]
    # The live owner's lock is untouched.
    assert json.loads(lock_path.read_text())["pid"] == live_daemon_record["pid"]


def test_dead_owner_lock_is_taken_over(monkeypatch, lock_path):
    monkeypatch.setattr("src.daemon_lock._pid_alive", lambda pid: False)
    stale = {"pid": 999999, "start_time": "never", "command": "x"}
    _write(lock_path, stale)
    holder = acquire_daemon_lock(lock_path)
    assert json.loads(lock_path.read_text())["pid"] == holder["pid"]


def test_recycled_pid_lock_is_taken_over(lock_path):
    # Alive pid but recorded start time does not match the process's actual
    # start time (we never wrote a matching one) → stale by definition.
    import os

    stale = {"pid": os.getpid(), "start_time": "impossible-start-time", "command": "x"}
    _write(lock_path, stale)
    holder = acquire_daemon_lock(lock_path)
    assert json.loads(lock_path.read_text())["pid"] == holder["pid"]


def test_corrupt_lock_file_is_taken_over(lock_path):
    _write(lock_path, "{not-json")
    holder = acquire_daemon_lock(lock_path)
    assert json.loads(lock_path.read_text())["pid"] == holder["pid"]


def test_owner_is_live_requires_command_marker(live_daemon_record, monkeypatch):
    # A live-looking pid whose LIVE command is not a src.main daemon is not a
    # verified daemon owner (stale-owner verification includes the command).
    monkeypatch.setattr(
        "src.daemon_lock._process_command", lambda pid: "zsh -c something-else"
    )
    assert _owner_is_live(live_daemon_record) is False
    monkeypatch.setattr(
        "src.daemon_lock._process_command", lambda pid: "python -m src.main --config x"
    )
    assert _owner_is_live(live_daemon_record) is True


def test_release_removes_own_lock_but_not_another_daemons(lock_path):
    mine = acquire_daemon_lock(lock_path)
    release_daemon_lock(lock_path, mine)
    assert not lock_path.exists()

    other = {"pid": 424242, "start_time": "x", "command": "y"}
    _write(lock_path, other)
    release_daemon_lock(lock_path, mine)
    assert lock_path.exists()  # foreign lock untouched


def test_full_daemon_mode_refuses_when_lock_held(lock_path, live_daemon_record, monkeypatch, caplog):
    """A second full src.main instance refuses safely (§20 test contract)."""
    _write(lock_path, live_daemon_record)

    import asyncio

    from src import main as main_module

    called = {"sync_loop": 0}

    async def fake_run_sync_loop(config):
        called["sync_loop"] += 1

    fake_config = type(
        "Cfg",
        (),
        {
            "validate": lambda self: None,
            "logging": property(lambda self: None),
            "server": property(lambda self: type("S", (), {"url": "https://x"})()),
            "photos": property(
                lambda self: type("P", (), {"library_path": "/x"})()
            ),
        },
    )()
    monkeypatch.setattr(main_module, "run_sync_loop", fake_run_sync_loop)
    monkeypatch.setattr(
        main_module,
        "Config",
        type("C", (), {"from_file": staticmethod(lambda p: fake_config)}),
    )
    monkeypatch.setattr(main_module, "create_example_config", lambda: None)
    monkeypatch.setattr(main_module, "setup_logging", lambda cfg: None)
    with caplog.at_level("ERROR"):
        asyncio.run(main_module.main(["--config", str(lock_path.parent / "config.yaml")]))
    assert called["sync_loop"] == 0
    assert "DAEMON_SINGLETON_REFUSE" in caplog.text


def test_ps_field_without_header_returns_value(monkeypatch):
    """Live-deploy regression: `ps -o lstart=` emits value only, no header.

    The first P4.3 implementation assumed a header row and returned None for
    every live owner, letting a second instance steal the lock and race the
    canonical daemon (observed in the live deploy and repaired same-night).
    """
    from src import daemon_lock

    class R:
        returncode = 0
        stdout = "Jeu 10 sep 00:14:22 2026\n"
        stderr = ""

    monkeypatch.setattr(
        daemon_lock.subprocess, "run", lambda *a, **k: R()
    )
    assert daemon_lock._ps_field(123, "lstart=") == "Jeu 10 sep 00:14:22 2026"

    class RH:
        returncode = 0
        stdout = " STARTED\nJeu 10 sep 00:14:22 2026\n"
        stderr = ""

    monkeypatch.setattr(daemon_lock.subprocess, "run", lambda *a, **k: RH())
    assert daemon_lock._ps_field(123, "lstart") == "Jeu 10 sep 00:14:22 2026"


def test_real_ps_lstart_matches_recorded_self(tmp_path, monkeypatch):
    """End-to-end with the REAL ps output on this host: a process must verify
    its own lock as live (not stale), under ANY locale.

    The live deploy found `ps -o lstart=` output is locale-dependent ("Thu
    Sep 10" under the daemon's C locale vs "Jeu 10 sep" under fr_FR), which
    made cross-context verification steal the lock; the verifier forces
    LC_ALL=C. This test runs with a French locale to prove the fix.
    """
    import os

    from src import daemon_lock

    monkeypatch.setenv("LC_ALL", "fr_FR.UTF-8")
    monkeypatch.setenv("LANG", "fr_FR.UTF-8")

    # This test process is pytest, not src.main; relax the command marker so
    # the real ps start-time/alive verification is what is under test.
    monkeypatch.setattr(daemon_lock, "_COMMAND_MARKER", "")
    holder = acquire_daemon_lock(tmp_path / "daemon.lock")
    assert _owner_is_live(holder) is True
    release_daemon_lock(tmp_path / "daemon.lock", holder)


def test_ps_start_time_is_locale_stable(monkeypatch):
    """The verifier must force LC_ALL=C into the ps subprocess env."""
    import os
    import subprocess as sp

    from src import daemon_lock

    captured = {}

    def fake_run(cmd, capture_output=True, text=True, timeout=None, env=None):
        captured["env"] = env
        result = type("R", (), {"returncode": 0, "stdout": "Thu Sep 10 00:18:41 2026\n", "stderr": ""})()
        return result

    monkeypatch.setenv("LC_ALL", "fr_FR.UTF-8")
    monkeypatch.setattr(daemon_lock.subprocess, "run", fake_run)
    value = daemon_lock._process_start_time(123)
    assert captured["env"]["LC_ALL"] == "C"
    assert value == "Thu Sep 10 00:18:41 2026"
