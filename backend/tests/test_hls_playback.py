"""Byte-range HLS over durable fragmented packages: parser, playlists, routes.

Fixtures are the header bytes of synthetic ffmpeg test-pattern encodes (no
user media): ``fmp4_head.bin`` uses the v4 recipe's movflags with AAC audio,
``faststart_head.bin`` is a classic faststart MP4.
"""

from pathlib import Path

import pytest

from app.config import get_settings
from app.models.media_backbone import MediaRevision
from app.models.user_auth import MediaPlaybackGrant
from app.services import hls_index

# Shared world: owner user-a, stranger user-b, a full clip with HQ/Light/poster.
from tests.test_derivative_read_d5 import (  # noqa: F401  (pytest fixtures)
    PRESIGN_MARKER,
    UUID_FULL,
    UUID_SMALL,
    _seed_world,
    client,
    db,
    fake_presign,
    flags,
)

FIXTURES = Path(__file__).parent / "fixtures" / "hls"
FMP4_HEAD = (FIXTURES / "fmp4_head.bin").read_bytes()
FMP4_SIZE = 4_351_785
FASTSTART_HEAD = (FIXTURES / "faststart_head.bin").read_bytes()


def _reader(data: bytes, total: int):
    calls = []

    def read(length):
        calls.append(length)
        return data[:length], total

    return read, calls


# ----------------------------------------------------------------- parser


def test_fragmented_header_indexes_every_fragment():
    index = hls_index.load_index(_reader(FMP4_HEAD, FMP4_SIZE)[0])
    assert index is not None
    assert index.init_length == 1276  # ftyp + moov
    assert len(index.segments) == 13
    assert index.segments[0].offset == 1668  # after both per-track sidx boxes
    assert all(a.offset + a.length == b.offset for a, b in zip(index.segments, index.segments[1:]))
    assert index.segments[-1].offset + index.segments[-1].length <= FMP4_SIZE
    assert index.duration == pytest.approx(12.5)
    assert index.codecs == "avc1.640020,mp4a.40.2"
    assert (index.width, index.height) == (720, 1280)
    assert index.peak_bandwidth >= index.average_bandwidth > 0


def test_classic_mp4_is_not_indexed():
    assert hls_index.load_index(_reader(FASTSTART_HEAD, 228_511)[0]) is None


def test_short_first_read_fetches_more_then_parses():
    read, calls = _reader(FMP4_HEAD, FMP4_SIZE)
    hls_index.HEAD_FETCH_BYTES, saved = 600, hls_index.HEAD_FETCH_BYTES
    try:
        assert hls_index.load_index(read) is not None
    finally:
        hls_index.HEAD_FETCH_BYTES = saved
    assert len(calls) >= 2 and calls[-1] <= hls_index.MAX_HEAD_BYTES


def test_garbage_and_truncated_files_are_not_indexed():
    assert hls_index.load_index(_reader(b"\x00" * 64, 64)[0]) is None
    assert hls_index.load_index(_reader(FMP4_HEAD[:900], 900)[0]) is None


def test_media_playlist_addresses_the_file_by_byte_range():
    index = hls_index.load_index(_reader(FMP4_HEAD, FMP4_SIZE)[0])
    body = hls_index.media_playlist(index, "https://b2.example/obj?sig=1")
    lines = body.splitlines()
    assert lines[0] == "#EXTM3U" and lines[-1] == "#EXT-X-ENDLIST"
    assert "#EXT-X-PLAYLIST-TYPE:VOD" in lines
    assert '#EXT-X-MAP:URI="https://b2.example/obj?sig=1",BYTERANGE="1276@0"' in lines
    assert lines.count("https://b2.example/obj?sig=1") == 13
    assert "#EXT-X-BYTERANGE:%d@1668" % index.segments[0].length in lines
    target = int(next(line for line in lines if line.startswith("#EXT-X-TARGETDURATION:")).split(":")[1])
    assert all(round(segment.duration) <= target for segment in index.segments)
    with pytest.raises(ValueError):
        hls_index.media_playlist(index, 'https://x/"\n#EXT-X-ENDLIST')


# ----------------------------------------------------------------- routes


@pytest.fixture()
def hls(monkeypatch, flags):
    """Serve the seeded transform version as HLS; B2 header reads faked."""
    settings = get_settings()
    monkeypatch.setattr(settings, "media_hls_transform_versions", settings.media_derivative_transform_version)
    hls_index.reset_cache()
    import app.api.v1.media_playback as playback_module

    state = {"reads": [], "fail": False, "data": FMP4_HEAD, "size": FMP4_SIZE}

    def read_head(bucket, object_key, length):
        state["reads"].append(object_key)
        if state["fail"]:
            raise playback_module.b2_presign.PresignUnavailable("injected")
        return state["data"][:length], state["size"]

    monkeypatch.setattr(playback_module.b2_presign, "read_object_head", read_head)
    yield state
    hls_index.reset_cache()


def _master(client, uuid=UUID_FULL, **params):
    return client.get(f"/api/v1/media/{uuid}/hls.m3u8", params=params)


def test_master_lists_light_then_hq_without_signed_urls(client, hls, fake_presign):
    response = _master(client)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/vnd.apple.mpegurl")
    assert response.headers["cache-control"] == "private, no-store"
    uris = [line for line in response.text.splitlines() if line and not line.startswith("#")]
    assert len(uris) == 2 and all(uri.endswith("/hls.m3u8") for uri in uris)
    assert 'CODECS="avc1.640020,mp4a.40.2"' in response.text
    assert PRESIGN_MARKER not in response.text and fake_presign[1] == []
    light_first = uris
    hq_first = [line for line in _master(client, start="hq").text.splitlines() if line and not line.startswith("#")]
    assert hq_first == list(reversed(light_first))
    # Headers are content addressed: the second master reads nothing.
    assert len(hls["reads"]) == 2


def test_media_playlist_signs_through_the_grant_path(client, db, hls, fake_presign):
    uri = next(line for line in _master(client).text.splitlines() if line and not line.startswith("#"))
    response = client.get(uri)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert response.text.count(PRESIGN_MARKER) == 14  # init map + 13 segments
    assert "#EXT-X-BYTERANGE:" in response.text
    assert "index" in response.headers["server-timing"]
    assert PRESIGN_MARKER not in response.headers["server-timing"]
    assert db.query(MediaPlaybackGrant).filter_by(outcome="ALLOWED").count() == 1


def test_stranger_gets_uniform_404_and_no_provider_io(client, db, hls, fake_presign):
    uri = next(line for line in _master(client).text.splitlines() if line and not line.startswith("#"))
    reads = len(hls["reads"])
    client.post("/api/v1/auth/logout")
    client.post("/api/v1/auth/login", json={"email": "user-b@example.test", "password": "correct-horse-battery"})
    assert _master(client).status_code == 404
    assert client.get(uri).status_code == 404
    assert len(hls["reads"]) == reads
    assert fake_presign[1] == []


def test_unauthenticated_playlists_rejected(client, hls):
    client.post("/api/v1/auth/logout")
    assert _master(client).status_code in (401, 404)


def test_classic_packages_are_not_served_as_hls(client, hls):
    hls["data"], hls["size"] = FASTSTART_HEAD, 228_511
    assert _master(client).status_code == 404


def test_hls_off_when_no_version_is_fragmented(client, hls, monkeypatch):
    monkeypatch.setattr(get_settings(), "media_hls_transform_versions", "")
    assert _master(client).status_code == 404
    status = client.get(f"/api/v1/media/{UUID_FULL}/status").json()
    assert status["derivatives"]["hls"] is None
    assert status["derivatives"]["light"]["hls_url"] is None
    batch = client.post("/api/v1/media/status/batch", json={"video_uuids": [UUID_FULL]}).json()
    assert "start_hls" not in batch[UUID_FULL]
    assert hls["reads"] == []


def test_status_and_batch_hint_hls_mode(client, hls, monkeypatch):
    status = client.get(f"/api/v1/media/{UUID_FULL}/status").json()
    assert status["derivatives"]["hls"] == "apple"
    for role in ("light", "hq"):
        entry = status["derivatives"][role]
        assert entry["hls_url"] == f"/api/v1/media/revisions/{entry['revision_id']}/hls.m3u8"
        assert client.get(entry["hls_url"]).status_code == 200
    assert status["derivatives"]["poster"]["hls_url"] is None
    batch = client.post("/api/v1/media/status/batch", json={"video_uuids": [UUID_FULL]}).json()
    assert batch[UUID_FULL]["start_hls"] == "apple"
    # Other players (Chrome's native HLS, hls.js) only once the bucket answers CORS.
    monkeypatch.setattr(get_settings(), "media_hls_cors_ready", True)
    assert client.get(f"/api/v1/media/{UUID_FULL}/status").json()["derivatives"]["hls"] == "all"
    batch = client.post("/api/v1/media/status/batch", json={"video_uuids": [UUID_FULL]}).json()
    assert batch[UUID_FULL]["start_hls"] == "all"


def test_provider_failure_is_503_and_not_cached(client, hls):
    hls["fail"] = True
    assert _master(client).status_code == 503
    hls["fail"] = False
    assert _master(client).status_code == 200


def test_small_clip_aliased_hq_has_a_single_variant(client, hls):
    response = _master(client, UUID_SMALL)
    assert response.status_code == 200, response.text
    assert response.text.count("#EXT-X-STREAM-INF") == 1
    derivatives = client.get(f"/api/v1/media/{UUID_SMALL}/status").json()["derivatives"]
    assert derivatives["hq"]["aliased_to"] == "light"
    assert derivatives["hq"]["hls_url"] == derivatives["light"]["hls_url"] is not None


def test_source_revision_has_no_media_playlist(client, db, hls):
    source = db.query(MediaRevision).filter_by(video_uuid=UUID_FULL).order_by(MediaRevision.id).first()
    assert client.get(f"/api/v1/media/revisions/{source.id}/hls.m3u8").status_code == 404
    assert hls["reads"] == []


def test_media_playlist_honors_the_kill_switch(client, hls, monkeypatch):
    uri = next(line for line in _master(client).text.splitlines() if line and not line.startswith("#"))
    monkeypatch.setattr(get_settings(), "media_hls_transform_versions", "")
    assert client.get(uri).status_code == 404
    monkeypatch.setattr(get_settings(), "media_hls_transform_versions", "some-other-version")
    assert client.get(uri).status_code == 404


def test_media_playlist_reads_the_package_with_no_open_transaction(client, db, hls, monkeypatch):
    import app.api.v1.media_playback as playback_module

    uri = next(line for line in _master(client).text.splitlines() if line and not line.startswith("#"))
    hls_index.reset_cache()
    seen = []

    def read_head(bucket, object_key, length):
        seen.append(db.in_transaction())
        return FMP4_HEAD[:length], FMP4_SIZE

    monkeypatch.setattr(playback_module.b2_presign, "read_object_head", read_head)
    assert client.get(uri).status_code == 200
    assert seen == [False]


def test_index_cache_has_a_segment_budget(monkeypatch):
    hls_index.reset_cache()
    monkeypatch.setattr(hls_index, "_CACHE_MAX_SEGMENTS", 30)  # two 13-segment indexes
    read = _reader(FMP4_HEAD, FMP4_SIZE)[0]
    for blob in ("a", "b", "c"):
        assert hls_index.cached_index(blob, read) is not None
    assert list(hls_index._cache) == ["b", "c"]
    assert hls_index._cached_segments == 26
    monkeypatch.setattr(hls_index, "_CACHE_MAX_SEGMENTS", 10)
    assert hls_index.cached_index("d", read) is not None  # served, too big to keep
    assert "d" not in hls_index._cache
    hls_index.reset_cache()


def test_batch_hints_hls_even_beside_an_older_uncapped_light(client, db, hls, monkeypatch):
    from tests.test_derivative_read_d5 import _derivative, _sha
    from app.models.media_backbone import MediaDerivative

    settings = get_settings()
    current = settings.media_derivative_transform_version
    monkeypatch.setattr(settings, "media_derivative_served_transform_versions", f"ffmpeg-h264-web-v4,{current}")
    monkeypatch.setattr(settings, "media_hls_transform_versions", "ffmpeg-h264-web-v4")
    src = db.query(MediaDerivative).filter_by(video_uuid=UUID_FULL, role="light").first().source_blob_sha256
    _derivative(db, UUID_FULL, src, "light", _sha("hls-v4-light"), transform="ffmpeg-h264-web-v4")
    db.commit()
    body = client.post("/api/v1/media/status/batch", json={"video_uuids": [UUID_FULL]}).json()
    assert body[UUID_FULL]["start_light_version"] == current  # cautious bitrate hint unchanged
    assert body[UUID_FULL]["start_hls"] == "apple"
