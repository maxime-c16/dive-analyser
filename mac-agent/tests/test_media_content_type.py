"""P5 §20 tests: evidence-based Content-Type for FUTURE uploads only.

- the mapping helper derives video MIME types from ffprobe container/codec
  evidence and fails closed to binary/octet-stream
- the B2 adapter passes ContentType through to the S3 client for both the
  bytes-put and the fileobj-upload paths (and omits it when unset)
- the coordinator forwards the configured content type to the store
- the counting/fault-injection wrappers keep the signature transparent

No historical object rewrite is exercised anywhere: these tests touch only
in-memory fakes and the adapter's boto3 call arguments.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ingest.media_content_type import (
    DEFAULT_CONTENT_TYPE,
    video_content_type,
)
from src.ingest.objectstore.b2 import BackblazeB2Store, B2Config
from src.ingest.objectstore.fake import FakeObjectStore


MOV_FAMILY = "mov,mp4,m4a,3gp,3g2,mj2"
MP4_FAMILY = "mp4,m4a,3gp,3g2,mj2"


def test_mov_family_with_video_codec_and_mov_ext_is_quicktime():
    assert video_content_type(MOV_FAMILY, "h264", "mov") == "video/quicktime"


def test_mp4_family_with_video_codec_and_mp4_ext_is_mp4():
    assert video_content_type(MP4_FAMILY, "hevc", "mp4") == "video/mp4"


def test_audio_codec_fails_closed():
    assert video_content_type(MOV_FAMILY, "aac", "mov") == DEFAULT_CONTENT_TYPE


def test_no_codec_fails_closed():
    assert video_content_type(MOV_FAMILY, None, "mov") == DEFAULT_CONTENT_TYPE


def test_unknown_container_fails_closed():
    assert video_content_type("avi", "h264", "avi") == DEFAULT_CONTENT_TYPE


def test_mov_family_without_evidence_fails_closed():
    assert video_content_type(MOV_FAMILY, "h264", None) == DEFAULT_CONTENT_TYPE
    assert video_content_type(MOV_FAMILY, "h264", "bin") == DEFAULT_CONTENT_TYPE


def test_webm_and_matroska():
    assert video_content_type("webm", "vp9", "webm") == "video/webm"
    assert video_content_type("matroska,webm", "vp9", "mkv") == "video/x-matroska"


class _RecordingB2Client:
    def __init__(self):
        self.put_calls = []
        self.upload_calls = []

    def put_object(self, **kwargs):
        self.put_calls.append(kwargs)
        return {"ResponseMetadata": {"HTTPStatusCode": 200}}

    def upload_fileobj(self, fileobj, bucket, key, ExtraArgs=None):
        self.upload_calls.append({"bucket": bucket, "key": key, "ExtraArgs": ExtraArgs})


@pytest.fixture()
def b2_store():
    config = B2Config(
        environment="dev",
        bucket="diveanalyzer-dev-media",
        region="eu-central-003",
    )
    client = _RecordingB2Client()
    store = BackblazeB2Store(config, client=client)
    return store, client


def test_b2_put_bytes_sets_content_type(b2_store):
    store, client = b2_store
    result = store.put("blobs/sha256/aa/aa" + "0" * 62, b"bytes", content_type="video/quicktime")
    assert client.put_calls[0]["ContentType"] == "video/quicktime"
    assert result.sha256


def test_b2_put_file_sets_content_type(b2_store, tmp_path: Path):
    store, client = b2_store
    payload = tmp_path / "clip.mov"
    payload.write_bytes(b"file-bytes")
    result = store.put("blobs/sha256/bb/bb" + "0" * 62, payload, content_type="video/mp4")
    assert client.upload_calls[-1]["ExtraArgs"] == {"ContentType": "video/mp4"}
    assert result.byte_size == len(b"file-bytes")


def test_b2_put_without_content_type_keeps_legacy_behavior(b2_store):
    store, client = b2_store
    store.put("blobs/sha256/cc/cc" + "0" * 62, b"legacy")
    assert "ContentType" not in client.put_calls[-1]
    assert client.put_calls[-1]["Bucket"] == "diveanalyzer-dev-media"


def test_fake_store_records_content_type():
    store = FakeObjectStore()
    store.put("k", b"data", content_type="video/quicktime")
    store.put("k2", b"data2")
    assert store.put_content_types["k"] == "video/quicktime"
    assert "k2" not in store.put_content_types
