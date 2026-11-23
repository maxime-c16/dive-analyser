"""Regression checks for backend runtime packaging invariants."""

import zoneinfo
from pathlib import Path
from zoneinfo import ZoneInfo

import app.security

ROOT = Path(__file__).resolve().parents[2]


def test_zoneinfo_works_without_system_tzpath():
    """Python tzdata must stay installed so Alpine/minimal images resolve Europe/Paris."""
    original = zoneinfo.TZPATH
    try:
        zoneinfo.reset_tzpath(to=())
        tz = ZoneInfo.no_cache("Europe/Paris")
        assert tz.key == "Europe/Paris"
    finally:
        zoneinfo.reset_tzpath(to=original)


def test_security_module_not_shadowed_by_directory():
    """app.security resolves to security.py with no dead app/security/ folder."""
    assert Path(app.security.__file__).name == "security.py"
    assert not (ROOT / "backend" / "app" / "security").exists()


def test_backend_dockerfile_healthcheck_and_tzdata():
    """Alpine image installs tzdata and probes loopback directly without Python."""
    dockerfile = (ROOT / "backend" / "Dockerfile").read_text()
    assert "tzdata" in dockerfile
    assert "wget -q -Y off -T 2 -O /dev/null http://127.0.0.1:8000/health" in dockerfile
