#!/usr/bin/env python3
"""Read-only Mac GUI/VNC state for isolated Photos confirmation experiments.

Run with the media node's venv Python (PyObjC Quartz is required). This does
not wake, unlock, authenticate, or change any session or security settings.
"""
import json
import subprocess
from datetime import datetime, timezone


def session_state():
    import Quartz
    session = dict(Quartz.CGSessionCopyCurrentDictionary() or {})
    result = subprocess.run(["/usr/sbin/netstat", "-an", "-p", "tcp"],
                            capture_output=True, text=True, check=True, timeout=10)
    connections = 0
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 6 and parts[3].endswith(".5900") and parts[5] == "ESTABLISHED":
            connections += 1
    login_done = session.get("kCGSessionLoginDoneKey")
    # Quartz omits the locked flag in an unlocked session. Missing session
    # data is unknown, never evidence of an unlocked desktop.
    locked = bool(session.get("CGSSessionScreenIsLocked", False)) if login_done is True else None
    return {"checked_at": datetime.now(timezone.utc).isoformat(),
            "login_done": login_done, "screen_locked": locked,
            "screen_sharing_connections": connections}


if __name__ == "__main__":
    print(json.dumps(session_state()))
