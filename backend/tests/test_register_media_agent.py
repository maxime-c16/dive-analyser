import hashlib
import importlib.util
import os
from pathlib import Path

import pytest

from app.models.media import MediaAgent
from app.services.media_agents import authenticate_media_agent

_SPEC = importlib.util.spec_from_file_location("register_media_agent", Path(__file__).resolve().parents[1] / "scripts" / "register_media_agent.py")
register = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(register)


def test_add_stores_only_a_hash_writes_the_key_once_and_is_package_only(test_db, tmp_path, capsys):
    key_file = tmp_path / "agent.key"
    result = register.add_agent(test_db, "mac-m2-joker", "mac-m2.local", str(key_file))
    key = key_file.read_text()
    assert len(key) >= 40 and oct(os.stat(key_file).st_mode & 0o777) == "0o600"
    agent = test_db.get(MediaAgent, "mac-m2-joker")
    assert agent.api_key_sha256 == hashlib.sha256(key.encode()).hexdigest()
    assert agent.capabilities == ["web_package"] and agent.leasing_enabled
    assert key not in str(result)
    assert authenticate_media_agent(test_db, "mac-m2-joker", key) is agent
    with pytest.raises(SystemExit):
        register.add_agent(test_db, "mac-m2-joker", "mac-m2.local", str(tmp_path / "other.key"))
    with pytest.raises(SystemExit):
        register.add_agent(test_db, "mac-m2-other", "mac-m2.local", str(key_file))  # never overwrite a key file


def test_disable_turns_the_agent_off(test_db, tmp_path):
    key_file = tmp_path / "agent.key"
    register.add_agent(test_db, "mac-m2-joker", "mac-m2.local", str(key_file))
    register.disable_agent(test_db, "mac-m2-joker")
    with pytest.raises(PermissionError):
        authenticate_media_agent(test_db, "mac-m2-joker", key_file.read_text())
