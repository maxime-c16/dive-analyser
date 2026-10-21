"""D1 durable-derivative pure unit tests (no PostgreSQL required).

Runs in the normal backend CI tier (SQLite/isolated env): deterministic
derivative keys + fail-closed validation (delimiter/whitespace/length/SHA
contract) + legacy key byte-stability + shared original-selector policy.
Real-PostgreSQL migration/selector proof lives in
`tests/test_postgres_media_derivatives_d1.py` (CI `postgres` tier).
"""

import hashlib

import pytest
from sqlalchemy import Column, String, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


def _sha(tag):
    return hashlib.sha256(f"d1-{tag}".encode()).hexdigest()


def test_derivative_key_determinism_and_identity_axes():
    from app.services.media_keys import build_derivative_media_key

    video_uuid = "clip-123"
    source_sha = _sha("source")
    version = "ffmpeg-h264-web-v1"

    first = build_derivative_media_key(video_uuid, "hq", source_sha, version)
    assert first == build_derivative_media_key(video_uuid, "hq", source_sha, version)
    assert len(first) == 64 and all(c in "0123456789abcdef" for c in first)
    # Identity is (clip, role, source, version): each axis separates keys.
    assert build_derivative_media_key(video_uuid, "light", source_sha, version) != first
    assert build_derivative_media_key(video_uuid, "hq", _sha("other-source"), version) != first
    assert build_derivative_media_key(video_uuid, "hq", source_sha, "ffmpeg-h264-web-v2") != first
    assert build_derivative_media_key("clip-456", "hq", source_sha, version) != first


def test_derivative_key_default_version_and_legacy_byte_stability():
    from app.config import get_settings
    from app.services.media_keys import build_derivative_media_key, build_media_key

    settings = get_settings()
    video_uuid = "clip-123"
    source_sha = _sha("source")
    # Default version resolves from settings, pinned to the web chain.
    assert settings.media_derivative_transform_version == "ffmpeg-h264-web-v1"
    assert build_derivative_media_key(video_uuid, "hq", source_sha) == build_derivative_media_key(
        video_uuid, "hq", source_sha, "ffmpeg-h264-web-v1"
    )
    # Legacy keys are byte-stable: the legacy transform default is untouched
    # and derivative versioning never leaks into legacy inputs.
    assert settings.media_transform_version == "ffmpeg-h264-v1"
    legacy = build_media_key(video_uuid, "proxy_720p")
    assert legacy == hashlib.sha256(
        f"{video_uuid}:proxy_720p:{settings.media_transform_version}:"
        f"{settings.media_export_policy_version}".encode()
    ).hexdigest()


def test_derivative_key_fail_closed_validation():
    from app.services.media_keys import build_derivative_media_key

    video_uuid = "clip-123"
    source_sha = _sha("source")
    version = "ffmpeg-h264-web-v1"

    bad_cases = [
        # Empty / blank video UUID.
        dict(video_uuid="", role="hq", source_sha256=source_sha, transform_version=version),
        dict(video_uuid="   ", role="hq", source_sha256=source_sha, transform_version=version),
        dict(video_uuid=None, role="hq", source_sha256=source_sha, transform_version=version),
        # Unknown role.
        dict(video_uuid=video_uuid, role="proxy_720p", source_sha256=source_sha, transform_version=version),
        dict(video_uuid=video_uuid, role="HQ", source_sha256=source_sha, transform_version=version),
        # Malformed SHAs: short, non-hex, uppercase, padded.
        dict(video_uuid=video_uuid, role="hq", source_sha256="short", transform_version=version),
        dict(video_uuid=video_uuid, role="hq", source_sha256="X" * 64, transform_version=version),
        dict(video_uuid=video_uuid, role="hq", source_sha256=_sha("s").upper(), transform_version=version),
        dict(video_uuid=video_uuid, role="hq", source_sha256=f" {source_sha}", transform_version=version),
        # Bad versions: empty, blank, over 40 chars.
        dict(video_uuid=video_uuid, role="hq", source_sha256=source_sha, transform_version=""),
        dict(video_uuid=video_uuid, role="hq", source_sha256=source_sha, transform_version="   "),
        dict(video_uuid=video_uuid, role="hq", source_sha256=source_sha, transform_version="x" * 41),
        # Delimiter / whitespace ambiguity: '|' would collide with the
        # derivative-v1 join; surrounding whitespace would mint distinct keys
        # for the same logical identity.
        dict(video_uuid="clip|123", role="hq", source_sha256=source_sha, transform_version=version),
        dict(video_uuid=" clip-123", role="hq", source_sha256=source_sha, transform_version=version),
        dict(video_uuid="clip-123 ", role="hq", source_sha256=source_sha, transform_version=version),
        dict(video_uuid=video_uuid, role="hq", source_sha256=source_sha, transform_version="v|1"),
        dict(video_uuid=video_uuid, role="hq", source_sha256=source_sha, transform_version=" v1"),
        dict(video_uuid=video_uuid, role="hq", source_sha256=source_sha, transform_version="v1 "),
        # DB contract: video_uuid capped at 100 chars (ledger VARCHAR(100)).
        dict(video_uuid="v" * 101, role="hq", source_sha256=source_sha, transform_version=version),
    ]
    for bad in bad_cases:
        with pytest.raises(ValueError):
            build_derivative_media_key(**bad)

    # Boundary lengths are accepted and keep derivative-v1 compatibility.
    ok_100 = build_derivative_media_key("v" * 100, "hq", source_sha, version)
    assert len(ok_100) == 64
    ok_40 = build_derivative_media_key(video_uuid, "hq", source_sha, "t" * 40)
    assert len(ok_40) == 64
    assert ok_40 == hashlib.sha256(
        f"derivative-v1|{video_uuid}|hq|{source_sha}|{'t' * 40}".encode()
    ).hexdigest()


def test_is_derived_semantics_python_check():
    from app.services.media_backbone import is_derived_rendition_semantics

    assert is_derived_rendition_semantics("derived_hq") is True
    assert is_derived_rendition_semantics("derived_light") is True
    assert is_derived_rendition_semantics("derived_poster") is True
    assert is_derived_rendition_semantics("derived_future_role") is True
    assert is_derived_rendition_semantics("photos_edited_rendition") is False
    assert is_derived_rendition_semantics("browser_original") is False
    assert is_derived_rendition_semantics("browser_playback") is False
    assert is_derived_rendition_semantics("") is False
    assert is_derived_rendition_semantics(None) is False


def test_derived_exclusion_clause_sqlite_semantics():
    """The shared exclusion clause is a strict no-op without derived rows."""
    from app.services.media_backbone import derived_semantics_exclusion_clause

    Base = declarative_base()

    class Rev(Base):
        __tablename__ = "rev"
        id = Column(String(64), primary_key=True)
        rendition_semantics = Column(String(60), nullable=False)

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        session.add_all([
            Rev(id="a", rendition_semantics="photos_edited_rendition"),
            Rev(id="b", rendition_semantics="browser_original"),
            Rev(id="c", rendition_semantics="browser_playback"),
        ])
        session.commit()
        # Without derived rows: all three legitimate semantics survive.
        got = sorted(
            r.id
            for r in session.query(Rev)
            .filter(derived_semantics_exclusion_clause(Rev.rendition_semantics))
            .all()
        )
        assert got == ["a", "b", "c"]
        # With derived rows: only the future rows are excluded (prefix, so a
        # future role under the same convention is excluded automatically).
        session.add_all([
            Rev(id="d", rendition_semantics="derived_hq"),
            Rev(id="e", rendition_semantics="derived_future"),
        ])
        session.commit()
        got = sorted(
            r.id
            for r in session.query(Rev)
            .filter(derived_semantics_exclusion_clause(Rev.rendition_semantics))
            .all()
        )
        assert got == ["a", "b", "c"]
        # LIKE escaping: 'derivedXhq' (no underscore) is NOT excluded.
        session.add(Rev(id="f", rendition_semantics="derivedXhq"))
        session.commit()
        got = sorted(
            r.id
            for r in session.query(Rev)
            .filter(derived_semantics_exclusion_clause(Rev.rendition_semantics))
            .all()
        )
        assert got == ["a", "b", "c", "f"]
    finally:
        session.close()
        engine.dispose()
