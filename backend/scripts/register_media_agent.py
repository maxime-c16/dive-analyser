#!/usr/bin/env python
"""Register an extra Mac media agent that only encodes web packages.

Run inside the backend container:

    register_media_agent.py add --agent-id mac-m2-joker --hostname mac-m2.local --key-file /tmp/agent.key
    register_media_agent.py disable --agent-id mac-m2-joker

``add`` generates a fresh 48-byte key, stores only its SHA-256 in
``media_agents`` and writes the key ONCE to ``--key-file`` (mode 0600, must
not exist). The key is never printed. Capabilities are ``web_package`` only,
so the agent never leases poster/proxy/Photos work. ``disable`` turns leasing
off and deactivates the agent (history kept).
"""
import argparse
import hashlib
import json
import os
import secrets
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.models  # noqa: E402,F401
from app.models.media import MediaAgent  # noqa: E402

PACKAGE_ONLY = ["web_package"]


def add_agent(db, agent_id: str, hostname: str, key_file: str) -> dict:
    if db.get(MediaAgent, agent_id) is not None:
        raise SystemExit(f"agent {agent_id!r} already exists")
    if os.path.exists(key_file):
        raise SystemExit(f"refusing to overwrite {key_file}")
    key = secrets.token_urlsafe(48)
    db.add(MediaAgent(
        id=agent_id,
        hostname=hostname,
        api_key_sha256=hashlib.sha256(key.encode("utf-8")).hexdigest(),
        active=True,
        leasing_enabled=True,
        capabilities=list(PACKAGE_ONLY),
    ))
    db.commit()
    fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(key)
    return {"agent_id": agent_id, "capabilities": PACKAGE_ONLY, "key_file": key_file}


def disable_agent(db, agent_id: str) -> dict:
    agent = db.get(MediaAgent, agent_id)
    if agent is None:
        raise SystemExit(f"agent {agent_id!r} not found")
    agent.leasing_enabled = False
    agent.active = False
    db.commit()
    return {"agent_id": agent_id, "active": False}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add")
    add.add_argument("--agent-id", required=True)
    add.add_argument("--hostname", required=True)
    add.add_argument("--key-file", required=True)
    disable = sub.add_parser("disable")
    disable.add_argument("--agent-id", required=True)
    args = parser.parse_args(argv)
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        result = add_agent(db, args.agent_id, args.hostname, args.key_file) if args.command == "add" else disable_agent(db, args.agent_id)
    finally:
        db.close()
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
