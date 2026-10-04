"""Daemon singleton guard (P4.3, packet §19/§20).

The P4.2 cohort observed a second full `src.main` daemon instance beside the
canonical LaunchAgent (spawned inadvertently by an SSH diagnostic that invoked
the runtime app binary — a daemon launcher, not a generic interpreter). Both
instances shared one config and one journal, so they could race production
work.

Mechanism: a deterministic pid/lock file with stale-owner verification.

- Lock identity records pid + process start time + command marker.
- If the recorded owner is dead (ESRCH) or the pid was recycled (recorded
  start time no longer matches), the lock is STALE and is taken over.
- If the recorded owner is alive with matching start time and command, a
  second full daemon instance REFUSES SAFELY (caller decides how to exit).
- One-shot diagnostic tooling never runs through the daemon entry point, so
  it is unaffected by design (the guard is wired ONLY into src.main's
  full-daemon mode, not into --extract-only/--library-stats or the
  ingest/dual_write + ingest/canary one-shot CLIs).
"""

import json
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

LOCK_FILENAME = "daemon.lock"
_COMMAND_MARKER = "src.main"


class DaemonAlreadyRunning(RuntimeError):
    """A live, verified daemon instance already owns the lock."""

    def __init__(self, holder: dict):
        self.holder = holder
        super().__init__(
            f"another production daemon instance is running: {holder!r}"
        )


def _owner_identity() -> dict:
    return {
        "pid": _current_pid(),
        "start_time": _process_start_time(_current_pid()),
        "command": _current_command(),
    }


def _current_pid() -> int:
    import os

    return os.getpid()


def _current_command() -> str:
    pid = _current_pid()
    return _process_command(pid) or _COMMAND_MARKER


def _ps_field(pid: int, fmt: str) -> str | None:
    """One ps output field, header-safe and locale-stable.

    Two live-deploy P4.3 findings are fixed here:
    1. `ps -p PID -o lstart=` (header-suppressed `=` form) emits ONLY the
       value line on macOS — a header-row assumption returned None for every
       live owner, letting a second instance steal the lock.
    2. `lstart=` output is LOCALE-dependent ("Thu Sep 10" under the launchd
       daemon's C locale vs "Jeu 10 sep" under a fr_FR SSH session). The
       verifier forces LC_ALL=C so recorded and re-read start times compare
       equal regardless of which process verifies the lock.
    """
    try:
        import os

        env = dict(os.environ)
        env["LC_ALL"] = "C"
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", fmt],
            capture_output=True,
            text=True,
            timeout=5,
            env=env,
        )
        if result.returncode != 0:
            return None
        lines = [ln.strip() for ln in result.stdout.strip().splitlines() if ln.strip()]
        if not lines:
            return None
        first = lines[0]
        # Header-form output: a bare header token followed by the value.
        if len(lines) > 1 and first.upper() in {"STARTED", "COMMAND", "LSTART"}:
            return lines[1]
        return first
    except Exception:
        return None


def _process_start_time(pid: int) -> str | None:
    return _ps_field(pid, "lstart=")


def _process_command(pid: int) -> str | None:
    return _ps_field(pid, "command=")


def _pid_alive(pid: int) -> bool:
    import os

    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _owner_is_live(record: dict) -> bool:
    """Stale-owner verification.

    A recorded owner is considered live ONLY if:
    - the pid exists, AND
    - the recorded process start time still matches (the pid was not
      recycled by an unrelated process), AND
    - the process command still identifies it as a src.main daemon.

    Anything else is a stale lock from a dead or mutated owner.
    """
    pid = record.get("pid")
    if not isinstance(pid, int) or not _pid_alive(pid):
        return False
    if record.get("start_time") != _process_start_time(pid):
        return False
    command = _process_command(pid) or ""
    return _COMMAND_MARKER in command


def acquire_daemon_lock(lock_path: str | Path) -> dict:
    """Acquire the daemon singleton lock; raise DaemonAlreadyRunning if live.

    Returns the recorded holder identity on success.
    """
    import os

    path = Path(lock_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    holder = _owner_identity()

    while True:
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(holder, fh, indent=2)
            return holder
        except FileExistsError:
            pass
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            record = None
        if isinstance(record, dict) and _owner_is_live(record):
            raise DaemonAlreadyRunning(record)
        # Stale lock (dead owner, recycled pid, or corrupt file): take over.
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        logger.warning(
            "stale daemon lock taken over (previous record: %r)", record
        )


def release_daemon_lock(lock_path: str | Path, holder: dict) -> None:
    """Release the lock if we still own it (never drop someone else's lock)."""
    path = Path(lock_path).expanduser()
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    if isinstance(record, dict) and record.get("pid") == holder.get("pid"):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
