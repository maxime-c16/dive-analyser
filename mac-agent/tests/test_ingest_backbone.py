"""Media backbone P1 tests: content addressing, object stores, B2 firewall,
caption revisions, ingestion state machine crash recovery (A-G), and
feature-flag legacy compatibility."""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import Config
from src.ingest import (
    PHOTOKIT_CAPTION_SHADOW_STATUS,
    BackblazeB2Store,
    B2Config,
    CaptionResult,
    CurrentStableCaptionProvider,
    FakeObjectStore,
    IngestState,
    IngestStateStore,
    ObjectStoreIngestCoordinator,
    PhotosDbCaptionProviderShadow,
    compare_caption_providers,
    caption_sha256,
    legacy_caption_transform,
    object_key_for_sha,
    sha256_bytes,
    sha256_file,
    validate_sha256,
)
from src.ingest.coordinator import InjectedCrash
from src.ingest.errors import (
    ConfigValidationError,
    ObjectStoreError,
    ObjectStoreUnavailable,
)
from src.ingest.objectstore.b2 import MAX_TTL_SECONDS

FAKE_SHA = "ab" * 32


def make_sha(seed: bytes) -> str:
    return sha256_bytes(seed)


class TestContentAddressing:
    def test_sha256_bytes_identity(self):
        assert sha256_bytes(b"hello") == (
            "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
        )

    def test_sha256_file_identity(self, tmp_path):
        p = tmp_path / "clip.mov"
        p.write_bytes(b"0123456789" * 1000)
        assert sha256_file(p) == sha256_bytes(b"0123456789" * 1000)

    def test_validate_sha256_rejects_malformed(self):
        assert validate_sha256(FAKE_SHA) == FAKE_SHA
        with pytest.raises(ValueError):
            validate_sha256(FAKE_SHA.upper())
        with pytest.raises(ValueError):
            validate_sha256("xyz")
        with pytest.raises(ValueError):
            validate_sha256(FAKE_SHA[:-1] + "g")

    def test_object_key_format(self):
        sha = "abcdef01" + "0" * 56
        assert object_key_for_sha(sha) == f"blobs/sha256/ab/{sha}"
        assert object_key_for_sha(sha, ext="MOV") == f"blobs/sha256/ab/{sha}.mov"

    def test_object_key_no_pii_possible(self):
        sha = "ab" * 32
        key = object_key_for_sha(sha)
        assert key.startswith("blobs/sha256/")
        assert key.count("/") == 3

    def test_object_key_rejects_unsafe_prefix(self):
        sha = "ab" * 32
        for bad in ["../escape", "/absolute", "Athlete Name", "a../b"]:
            with pytest.raises(ValueError):
                object_key_for_sha(sha, prefix=bad)

    def test_object_key_rejects_bad_ext(self):
        sha = "ab" * 32
        with pytest.raises(ValueError):
            object_key_for_sha(sha, ext="../../etc")
        with pytest.raises(ValueError):
            object_key_for_sha(sha, ext="toolongext")


class TestFakeObjectStore:
    def test_put_head_get_roundtrip(self):
        store = FakeObjectStore()
        data = b"video-bytes-here"
        result = store.put("k1", data)
        assert result.sha256 == sha256_bytes(data)
        assert store.head("k1").byte_size == len(data)
        assert store.get("k1") == data

    def test_put_from_path(self, tmp_path):
        store = FakeObjectStore()
        p = tmp_path / "f.bin"
        p.write_bytes(b"file-bytes")
        result = store.put("k", p)
        assert result.byte_size == 10
        assert store.get("k") == b"file-bytes"

    def test_duplicate_same_hash_put_is_idempotent_content(self):
        store = FakeObjectStore()
        data = b"same-content"
        store.put("blobs/sha256/aa/x", data)
        store.put("blobs/sha256/aa/x", data)
        assert store.put_counts["blobs/sha256/aa/x"] == 2
        assert store.get("blobs/sha256/aa/x") == data

    def test_head_missing_returns_none(self):
        assert FakeObjectStore().head("nope") is None

    def test_get_missing_raises(self):
        with pytest.raises(ObjectStoreError):
            FakeObjectStore().get("nope")

    def test_corruption_injection_fails_roundtrip(self):
        store = FakeObjectStore()
        key = "blobs/sha256/cc/" + make_sha(b"orig")
        store.corrupt_keys.add(key)
        store.put(key, b"orig")
        remote = store.get(key)
        assert sha256_bytes(remote) != make_sha(b"orig")

    def test_interrupted_upload(self):
        store = FakeObjectStore()
        store.fail_after_bytes = 4
        with pytest.raises(ObjectStoreUnavailable):
            store.put("k", b"more-than-four-bytes")
        assert store.head("k") is None

    def test_head_and_get_errors(self):
        store = FakeObjectStore()
        store.put("k", b"data")
        store.error_keys.add("k")
        with pytest.raises(ObjectStoreUnavailable):
            store.head("k")
        with pytest.raises(ObjectStoreUnavailable):
            store.get("k")

    def test_presign_records_request(self):
        store = FakeObjectStore()
        url = store.presign_get("k", 600)
        assert "ttl=600" in url
        assert store.presigned == [("k", 600)]


class TestB2ConfigFirewall:
    def test_dev_using_prod_bucket_rejected(self):
        with pytest.raises(ConfigValidationError):
            B2Config("dev", "diveanalyzer-prod-media", region="eu-central-003")

    def test_prod_using_dev_bucket_rejected(self):
        with pytest.raises(ConfigValidationError):
            B2Config("prod", "diveanalyzer-dev-media", region="eu-central-003")

    def test_empty_bucket_rejected(self):
        with pytest.raises(ConfigValidationError):
            B2Config("dev", "  ", region="eu-central-003")

    def test_bucket_without_env_token_rejected(self):
        with pytest.raises(ConfigValidationError):
            B2Config("dev", "diveanalyzer-media", region="eu-central-003")

    def test_missing_region_and_endpoint_rejected(self):
        with pytest.raises(ConfigValidationError):
            B2Config("dev", "diveanalyzer-dev-media")

    def test_unexpected_prefix_rejected(self):
        with pytest.raises(ConfigValidationError):
            B2Config(
                "dev",
                "diveanalyzer-dev-media",
                region="eu-central-003",
                prefix="Oh No/..",
            )

    def test_bad_ttl_rejected(self):
        with pytest.raises(ConfigValidationError):
            B2Config(
                "dev",
                "diveanalyzer-dev-media",
                region="eu-central-003",
                presign_ttl_seconds=0,
            )
        with pytest.raises(ConfigValidationError):
            B2Config(
                "dev",
                "diveanalyzer-dev-media",
                region="eu-central-003",
                presign_ttl_seconds=MAX_TTL_SECONDS + 1,
            )

    def test_missing_credentials_rejected(self, monkeypatch):
        monkeypatch.delenv("B2_APPLICATION_KEY_ID", raising=False)
        monkeypatch.delenv("B2_APPLICATION_KEY", raising=False)
        config = B2Config("dev", "diveanalyzer-dev-media", region="eu-central-003")
        with pytest.raises(ConfigValidationError):
            config.resolve_credentials()

    def test_valid_dev_config_and_endpoint(self):
        config = B2Config("dev", "diveanalyzer-dev-media", region="eu-central-003")
        assert config.endpoint_url == "https://s3.eu-central-003.backblazeb2.com"
        assert config.key_for_sha(FAKE_SHA) == f"blobs/sha256/ab/{FAKE_SHA}"
        with pytest.raises(ValueError):
            config.key_for_sha("NOTASHA")


class StubB2Client:
    def __init__(self, fail_times=0):
        self.objects = {}
        self.fail_times = fail_times
        self.calls = 0

    def put_object(self, Bucket, Key, Body):
        self.calls += 1
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("transient 503")
        self.objects[Key] = bytes(Body)
        return {}

    def head_object(self, Bucket, Key):
        self.calls += 1
        if Key not in self.objects:
            error = RuntimeError("missing")
            error.response = {"Error": {"Code": "404"}}
            raise error
        return {"ContentLength": len(self.objects[Key]), "ETag": '"etag"'}

    def get_object(self, Bucket, Key):
        self.calls += 1
        return {"Body": _Body(self.objects[Key])}

    def generate_presigned_url(self, method, Params, ExpiresIn):
        return f"https://s3.example/presigned/{Params['Key']}?ttl={ExpiresIn}"


class _Body:
    def __init__(self, data):
        self.data = data

    def read(self):
        return self.data


class TestBackblazeB2Store:
    def _store(self, client):
        config = B2Config("dev", "diveanalyzer-dev-media", region="eu-central-003")
        return BackblazeB2Store(config, client=client), config

    def test_put_head_get_roundtrip(self):
        client = StubB2Client()
        store, config = self._store(client)
        key = config.key_for_sha(make_sha(b"data123"))
        result = store.put(key, b"data123")
        assert result.sha256 == make_sha(b"data123")
        assert store.head(key).byte_size == 7
        assert store.get(key) == b"data123"
        assert make_sha(b"data123") != "etag-none"

    def test_bounded_retries_then_unavailable(self):
        client = StubB2Client(fail_times=10)
        store, _ = self._store(client)
        with pytest.raises(ObjectStoreUnavailable):
            store.put("k", b"data")
        assert client.calls == store.config.max_retries + 1

    def test_retry_then_success(self):
        client = StubB2Client(fail_times=1)
        store, _ = self._store(client)
        result = store.put("k", b"data")
        assert result.byte_size == 4

    def test_head_404_returns_none(self):
        client = StubB2Client()
        store, _ = self._store(client)
        assert store.head("missing") is None

    def test_presign_ttl_bounds(self):
        client = StubB2Client()
        store, _ = self._store(client)
        assert "ttl=600" in store.presign_get("k", 600)
        with pytest.raises(ConfigValidationError):
            store.presign_get("k", 0)

    def test_multipart_etag_is_not_source_sha(self):
        client = StubB2Client()
        store, config = self._store(client)
        key = config.key_for_sha(make_sha(b"body"))
        result = store.put(key, b"body")
        head = store.head(key)
        assert head.etag != result.sha256
        assert result.sha256 == make_sha(b"body")


CAPTIONS = [
    "107B | 7.5 | H:3 | drill:no-arms | note:à revoir",
    "101A F 3m SYNC",
    "emoji 🤿 Dive 🌊 103B",
    "pipes | and | more | pipes",
    "colon: inside caption",
    "punctuation! really? yes.",
    "multiple   internal    spaces",
    "line one\nline two\nline three",
    "accent éèàç çàéè",
]


EXACTNESS_STRINGS = [
    "abc",
    " abc",
    "abc ",
    "  abc  ",
    "",
    " ",
    "  ",
    "a  b",
    "a\nb",
    "\na\n",
    "éèàç",
    "🤿",
    "107B | 7.5 | H:3",
]


class TestCaptionRawExactness:
    """R1: caption_raw = exact provider output, BEFORE any app-level strip."""

    def test_provider_returns_exact_string_for_every_case(self):
        for caption in EXACTNESS_STRINGS:
            provider = CurrentStableCaptionProvider(lambda uuid, c=caption: c)
            result = provider.get_caption("u")
            assert result.available, caption
            assert result.raw == caption
            assert result.sha256 == caption_sha256(caption)
            assert bytes(result.raw, "utf-8") == caption.encode("utf-8")

    def test_no_strip_applied_by_backbone_provider(self):
        provider = CurrentStableCaptionProvider(lambda uuid: "  abc  ")
        result = provider.get_caption("u")
        assert result.raw == "  abc  "
        assert result.sha256 == caption_sha256("  abc  ")
        assert result.raw != "abc"

    def test_whitespace_variants_have_distinct_hashes(self):
        provider = CurrentStableCaptionProvider(lambda uuid: None)
        variants = {}
        for caption in ["abc", " abc", "abc ", "  abc  ", "\na\n", "a"]:
            provider = CurrentStableCaptionProvider(lambda uuid, c=caption: c)
            variants[caption] = provider.get_caption("u").sha256
        assert len(set(variants.values())) == len(variants)
        assert variants[" abc"] != variants["abc"]
        assert variants["abc "] != variants["abc"]
        assert variants["\na\n"] != variants["a"]

    def test_effectively_empty_is_derived_gate_only(self):
        for caption in ["", " ", "  "]:
            provider = CurrentStableCaptionProvider(lambda uuid, c=caption: c)
            result = provider.get_caption("u")
            assert result.available
            assert result.raw == caption
            assert result.sha256 == caption_sha256(caption)
            assert result.effectively_empty is True

    def test_effectively_empty_false_for_whitespace_bearing_caption(self):
        provider = CurrentStableCaptionProvider(lambda uuid: " 107B ")
        result = provider.get_caption("u")
        assert result.effectively_empty is False
        assert result.raw == " 107B "

    def test_legacy_transform_is_separate_and_unapplied(self):
        assert legacy_caption_transform(" abc") == "abc"
        assert legacy_caption_transform("abc ") == "abc"
        assert legacy_caption_transform("\na\n") == "a"
        provider = CurrentStableCaptionProvider(lambda uuid: " abc ")
        result = provider.get_caption("u")
        assert result.raw != legacy_caption_transform(result.raw)

    def test_unicode_and_emoji_exact_bytes(self):
        for caption in ["éèàç", "🤿", "107B | 7.5 | H:3"]:
            provider = CurrentStableCaptionProvider(lambda uuid, c=caption: c)
            result = provider.get_caption("u")
            assert result.raw.encode("utf-8") == caption.encode("utf-8")

    def test_provider_failure_does_not_raise(self):
        def boom(uuid):
            raise RuntimeError("photos locked")

        provider = CurrentStableCaptionProvider(boom)
        result = provider.get_caption("u")
        assert not result.available
        assert result.error_family == "stable_provider_error"

    def test_shadow_provider_missing_library(self, tmp_path):
        shadow = PhotosDbCaptionProviderShadow(tmp_path / "NotALibrary")
        result = shadow.get_caption("uuid")
        assert not result.available
        assert result.error

    def test_shadow_provider_returns_exact_db_value(self, tmp_path):
        import sqlite3 as _sqlite3
        lib = tmp_path / "Lib"
        (lib / "database").mkdir(parents=True)
        db = lib / "database" / "Photos.sqlite"
        con = _sqlite3.connect(db)
        con.execute("CREATE TABLE ZASSET (ZUUID TEXT, ZUNMANAGEDCAPTION TEXT)")
        con.execute("INSERT INTO ZASSET VALUES ('u1', '  kept-exact  ')")
        con.commit()
        con.close()
        shadow = PhotosDbCaptionProviderShadow(lib)
        result = shadow.get_caption("u1")
        assert result.available
        assert result.raw == "  kept-exact  "
        assert result.sha256 == caption_sha256("  kept-exact  ")

    def test_shadow_provider_modern_schema_join(self, tmp_path):
        """macOS 13+ schema: caption lives in ZASSETDESCRIPTION.ZLONGDESCRIPTION,
        reached through ZADDITIONALASSETATTRIBUTES — all introspected, never
        hardcoded into the query text by the caller."""
        import sqlite3 as _sqlite3
        lib = tmp_path / "Lib"
        (lib / "database").mkdir(parents=True)
        db = lib / "database" / "Photos.sqlite"
        con = _sqlite3.connect(db)
        con.execute("CREATE TABLE ZASSET (Z_PK INTEGER PRIMARY KEY, ZUUID TEXT)")
        con.execute(
            "CREATE TABLE ZADDITIONALASSETATTRIBUTES "
            "(Z_PK INTEGER PRIMARY KEY, ZASSET INTEGER, ZASSETDESCRIPTION INTEGER)"
        )
        con.execute(
            "CREATE TABLE ZASSETDESCRIPTION "
            "(Z_PK INTEGER PRIMARY KEY, ZLONGDESCRIPTION TEXT)"
        )
        con.execute("INSERT INTO ZASSET VALUES (1, 'u2')")
        con.execute("INSERT INTO ZADDITIONALASSETATTRIBUTES VALUES (1, 1, 7)")
        con.execute("INSERT INTO ZASSETDESCRIPTION VALUES (7, '  modern exact  ')")
        con.commit()
        con.close()
        shadow = PhotosDbCaptionProviderShadow(lib)
        result = shadow.get_caption("u2")
        assert result.available
        assert result.raw == "  modern exact  "
        assert result.sha256 == caption_sha256("  modern exact  ")

    def test_shadow_provider_modern_schema_missing_row(self, tmp_path):
        import sqlite3 as _sqlite3
        lib = tmp_path / "Lib"
        (lib / "database").mkdir(parents=True)
        db = lib / "database" / "Photos.sqlite"
        con = _sqlite3.connect(db)
        con.execute("CREATE TABLE ZASSET (Z_PK INTEGER PRIMARY KEY, ZUUID TEXT)")
        con.execute(
            "CREATE TABLE ZADDITIONALASSETATTRIBUTES "
            "(Z_PK INTEGER PRIMARY KEY, ZASSET INTEGER, ZASSETDESCRIPTION INTEGER)"
        )
        con.execute(
            "CREATE TABLE ZASSETDESCRIPTION "
            "(Z_PK INTEGER PRIMARY KEY, ZLONGDESCRIPTION TEXT)"
        )
        con.execute("INSERT INTO ZASSET VALUES (1, 'u3')")
        con.commit()
        con.close()
        shadow = PhotosDbCaptionProviderShadow(lib)
        result = shadow.get_caption("u3")
        assert not result.available
        assert result.error_family == "shadow_no_row"

    def test_photokit_shadow_status_constant(self):
        assert PHOTOKIT_CAPTION_SHADOW_STATUS == "NOT_IMPLEMENTED_CURRENT_RUNTIME"
        shadow = PhotosDbCaptionProviderShadow("unused")
        assert shadow.provider_kind == "photos_db_sqlite"
        assert "photokit" not in shadow.name


class TestParityHarnessMetadata:
    def test_report_includes_provider_identity_and_redaction(self):
        stable = CaptionResult(
            "osxphotos_description_stable", True, "caption text",
            caption_sha256("caption text"),
            provider_kind="osxphotos_description", provider_version="1.0",
        )
        shadow_same = CaptionResult(
            "photos_db_sqlite_shadow", True, "caption text",
            caption_sha256("caption text"),
            provider_kind="photos_db_sqlite", provider_version="1.0",
        )
        shadow_diff = CaptionResult(
            "photos_db_sqlite_shadow", True, "caption!",
            caption_sha256("caption!"), provider_kind="photos_db_sqlite",
        )
        shadow_down = CaptionResult(
            "photos_db_sqlite_shadow", False, None, None,
            "shadow_unavailable: locked", provider_kind="photos_db_sqlite",
        )
        report = compare_caption_providers(
            [("u1", stable, shadow_same), ("u2", stable, shadow_diff), ("u3", stable, shadow_down)]
        )
        assert report["sample_count"] == 3
        assert report["exact_equal_count"] == 1
        assert report["exact_equal_rate"] == pytest.approx(1 / 3)
        assert report["provider_failures"] == {"stable": 0, "shadow": 1}
        assert len(report["samples"]) == 3
        sample = report["samples"][1]
        assert sample["exact_equal"] is False
        assert sample["stable"]["provider_kind"] == "osxphotos_description"
        assert sample["shadow"]["provider_kind"] == "photos_db_sqlite"
        assert sample["shadow"]["caption_sha256"] == caption_sha256("caption!")
        assert sample["shadow"]["caption_length"] == len("caption!")
        assert sample["shadow"]["error_family"] is None
        down = report["samples"][2]["shadow"]
        assert down["available"] is False
        assert down["error_family"] == "shadow_unavailable"
        serialized = json.dumps(report)
        assert "raw" not in serialized
        assert "caption text" not in serialized


_FAKE_STORES: dict[str, FakeObjectStore] = {}


def make_coordinator(tmp_path, *, failpoints=None, store=None, free_bytes=None,
                     materialize_fn=None, commit_fn=None, min_free_disk_bytes=0,
                     object_store=None):
    video_uuid = "A1B2C3D4E5F60718293A4B5C6D7E8F90"
    blob_path = tmp_path / "source" / "clip.mov"
    blob_path.parent.mkdir(parents=True, exist_ok=True)
    if not blob_path.exists():
        blob_path.write_bytes(os.urandom(2048))
    content = blob_path.read_bytes()
    state_store = store or IngestStateStore(tmp_path / "state" / "ingest.json")
    if object_store is None:
        object_store = _FAKE_STORES.setdefault(str(tmp_path), FakeObjectStore())

    def default_materialize(uuid, workdir):
        target = Path(workdir) / "clip.mov"
        target.write_bytes(content)
        return target

    committed = []

    def default_commit(payload):
        committed.append(payload)
        return {"ok": True}

    coordinator = ObjectStoreIngestCoordinator(
        video_uuid,
        state_store,
        object_store,
        materialize_fn=materialize_fn or default_materialize,
        commit_db_fn=commit_fn or default_commit,
        temp_root=tmp_path / "ingest_tmp",
        caption_provider=CurrentStableCaptionProvider(
            lambda uuid: "107B | 7.5 | H:3 | drill:no-arms | note:à revoir"
        ),
        min_free_disk_bytes=min_free_disk_bytes,
        free_disk_bytes_fn=free_bytes,
        failpoints=failpoints or {},
        bucket="diveanalyzer-dev-media",
    )
    return coordinator, object_store, committed, content


class TestIngestionStateMachine:
    def test_happy_path_converges(self, tmp_path):
        coordinator, store, committed, content = make_coordinator(tmp_path)
        final = coordinator.run_once()
        assert final is IngestState.CACHE_CLEANED
        assert len(committed) == 1
        payload = committed[0]
        assert payload["rendition_semantics"] == "photos_edited_rendition"
        assert payload["caption"]["raw"] == "107B | 7.5 | H:3 | drill:no-arms | note:à revoir"
        assert payload["blob"]["sha256"] == sha256_bytes(content)
        key = payload["blob"]["object_key"]
        assert key == object_key_for_sha(sha256_bytes(content), ext="mov")
        assert store.store_sha256(key) == sha256_bytes(content)
        assert not coordinator.workdir.exists()

    def test_a_crash_before_materialization(self, tmp_path):
        coordinator, store, committed, _ = make_coordinator(
            tmp_path, failpoints={"MEDIA_REQUESTED:before_effect": "raise"}
        )
        with pytest.raises(InjectedCrash):
            coordinator.run_once()
        restarted, store2, committed2, _ = make_coordinator(
            tmp_path, store=IngestStateStore(tmp_path / "state" / "ingest.json")
        )
        assert restarted.run_once() is IngestState.CACHE_CLEANED
        assert len(committed2) == 1

    def test_b_crash_after_materialization_before_hash(self, tmp_path):
        coordinator, _, _, _ = make_coordinator(
            tmp_path, failpoints={"MEDIA_MATERIALIZED:after_effect": "raise"}
        )
        with pytest.raises(InjectedCrash):
            coordinator.run_once()
        restarted, store, committed, content = make_coordinator(
            tmp_path, store=IngestStateStore(tmp_path / "state" / "ingest.json")
        )
        assert restarted.run_once() is IngestState.CACHE_CLEANED
        assert len(committed) == 1
        assert committed[0]["blob"]["sha256"] == sha256_bytes(content)

    def test_c_crash_after_local_sha_before_upload(self, tmp_path):
        coordinator, _, _, _ = make_coordinator(
            tmp_path, failpoints={"REMOTE_UPLOAD_STARTED:before_effect": "raise"}
        )
        with pytest.raises(InjectedCrash):
            coordinator.run_once()
        restarted, store, committed, content = make_coordinator(
            tmp_path, store=IngestStateStore(tmp_path / "state" / "ingest.json")
        )
        assert restarted.run_once() is IngestState.CACHE_CLEANED
        assert len(committed) == 1
        assert len(store.objects) == 1

    def test_d_interrupted_mid_upload_retries(self, tmp_path):
        coordinator, store, committed, content = make_coordinator(tmp_path)
        store.fail_after_bytes = 64
        state = coordinator.run_once()
        assert state is IngestState.REMOTE_UPLOAD_STARTED
        assert store.objects == {}
        assert coordinator.store.doc["attempts"] >= 1
        assert coordinator.store.doc["last_error"]["family"] == "object_store_unavailable"
        assert coordinator.run_once() is IngestState.CACHE_CLEANED
        assert len(committed) == 1
        key = coordinator.store.doc["media"]["object_key"]
        assert store.store_sha256(key) == sha256_bytes(content)

    def test_e_upload_complete_crash_before_verification(self, tmp_path):
        coordinator, _, _, _ = make_coordinator(
            tmp_path, failpoints={"REMOTE_UPLOADED:before_effect": "raise"}
        )
        with pytest.raises(InjectedCrash):
            coordinator.run_once()
        restarted, store, committed, _ = make_coordinator(
            tmp_path, store=IngestStateStore(tmp_path / "state" / "ingest.json")
        )
        puts_before = sum(store.put_counts.values())
        assert restarted.run_once() is IngestState.CACHE_CLEANED
        assert sum(store.put_counts.values()) == puts_before
        assert len(committed) == 1

    def test_f_verified_db_commit_absent_retries_commit_once(self, tmp_path):
        coordinator, _, _, _ = make_coordinator(
            tmp_path, failpoints={"REMOTE_VERIFIED:before_effect": "raise"}
        )
        with pytest.raises(InjectedCrash):
            coordinator.run_once()
        restarted, store, committed, _ = make_coordinator(
            tmp_path, store=IngestStateStore(tmp_path / "state" / "ingest.json")
        )
        assert restarted.run_once() is IngestState.CACHE_CLEANED
        assert len(committed) == 1

    def test_g_db_commit_complete_cleanup_absent(self, tmp_path):
        coordinator, _, committed_first, _ = make_coordinator(
            tmp_path, failpoints={"DB_COMMITTED:before_effect": "raise"}
        )
        with pytest.raises(InjectedCrash):
            coordinator.run_once()
        assert len(committed_first) == 1
        state_file = tmp_path / "state" / "ingest.json"
        assert json.loads(state_file.read_text())["db_commit"]["committed"] is True
        workdir = tmp_path / "ingest_tmp" / "A1B2C3D4E5F60718293A4B5C6D7E8F90"
        assert workdir.exists()
        restarted, _, committed_second, _ = make_coordinator(
            tmp_path, store=IngestStateStore(state_file)
        )
        assert restarted.run_once() is IngestState.CACHE_CLEANED
        assert not workdir.exists()
        assert committed_second == []

    def test_corrupt_remote_fails_closed_quarantine(self, tmp_path):
        def corrupt_materialize(uuid, workdir):
            target = Path(workdir) / "clip.mov"
            target.write_bytes(b"local-original-bytes")
            return target

        fresh_store = FakeObjectStore()
        coordinator, store, committed, _ = make_coordinator(
            tmp_path, materialize_fn=corrupt_materialize, object_store=fresh_store
        )
        real_put = store.put

        def put_then_corrupt(key, source):
            result = real_put(key, source)
            store.objects[key] = b"tampered!"
            return result

        store.put = put_then_corrupt
        assert coordinator.run_once() is IngestState.QUARANTINED
        assert committed == []
        assert coordinator.store.doc["last_error"]["family"] == "verification_failed"

    def test_missing_temp_file_reconciles_and_rematerializes(self, tmp_path):
        coordinator, store, committed, content = make_coordinator(
            tmp_path, failpoints={"MEDIA_MATERIALIZED:before_effect": "raise"}
        )
        with pytest.raises(InjectedCrash):
            coordinator.run_once()
        state_file = tmp_path / "state" / "ingest.json"
        doc = json.loads(state_file.read_text())
        Path(doc["media"]["temp_path"]).unlink()
        restarted, _, committed2, _ = make_coordinator(
            tmp_path, store=IngestStateStore(state_file)
        )
        assert restarted.run_once() is IngestState.CACHE_CLEANED
        assert len(committed2) == 1
        assert committed2[0]["blob"]["sha256"] == sha256_bytes(content)

    def test_min_free_disk_guard_blocks_materialization(self, tmp_path):
        coordinator, _, committed, _ = make_coordinator(
            tmp_path, min_free_disk_bytes=10**9, free_bytes=lambda: 5
        )
        state = coordinator.run_once()
        assert state is IngestState.MEDIA_REQUESTED
        assert coordinator.store.doc["last_error"]["family"] == "insufficient_disk"
        assert committed == []

    def test_db_commit_unavailable_is_retryable(self, tmp_path):
        calls = []

        def flaky_commit(payload):
            if len(calls) == 0:
                calls.append("fail")
                raise ObjectStoreUnavailable("db down")
            calls.append("ok")
            return {"ok": True}

        coordinator, _, _, _ = make_coordinator(tmp_path, commit_fn=flaky_commit)
        assert coordinator.run_once() is IngestState.REMOTE_VERIFIED
        assert coordinator.run_once() is IngestState.CACHE_CLEANED
        assert calls == ["fail", "ok"]

    def test_caption_unavailable_quarantines(self, tmp_path):
        coordinator, _, committed, _ = make_coordinator(tmp_path)
        coordinator.caption_provider = CurrentStableCaptionProvider(lambda uuid: None)
        assert coordinator.run_once() is IngestState.QUARANTINED
        assert committed == []


class TestPersistenceRestart:
    def test_state_file_survives_process_recreation(self, tmp_path):
        coordinator, _, _, _ = make_coordinator(
            tmp_path, failpoints={"LOCAL_HASHED:before_effect": "raise"}
        )
        with pytest.raises(InjectedCrash):
            coordinator.run_once()
        state_file = tmp_path / "state" / "ingest.json"
        doc = json.loads(state_file.read_text(encoding="utf-8"))
        assert doc["video_uuid"] == "A1B2C3D4E5F60718293A4B5C6D7E8F90"
        assert doc["state"] == IngestState.LOCAL_HASHED.value
        assert doc["media"]["sha256"]
        assert doc["caption"]["raw"]
        fresh_store = IngestStateStore(state_file)
        fresh_store.load("A1B2C3D4E5F60718293A4B5C6D7E8F90")
        assert fresh_store.state is IngestState.LOCAL_HASHED

    def test_corrupt_state_file_starts_fresh(self, tmp_path):
        state_file = tmp_path / "state" / "ingest.json"
        state_file.parent.mkdir(parents=True)
        state_file.write_text("{not json")
        coordinator, _, committed, _ = make_coordinator(
            tmp_path, store=IngestStateStore(state_file)
        )
        assert coordinator.run_once() is IngestState.CACHE_CLEANED
        assert len(committed) == 1

    def test_no_duplicate_objects_on_full_replay(self, tmp_path):
        coordinator, store, committed, _ = make_coordinator(tmp_path)
        assert coordinator.run_once() is IngestState.CACHE_CLEANED
        assert sum(store.put_counts.values()) == 1
        assert len(store.objects) == 1
        assert len(committed) == 1


class TestStateAuthority:
    """R3: ONE coherent state model.

    - Local per-clip JSON journal = authority for pre-commit/restart mechanics.
    - Server DB (blob/revision/caption-revision + ingest_object_state commit
      ledger) = authority for the durable committed logical result.
    - The agent never reads server state; the ledger is written once at commit.
    """

    def _dedupe_commit_fn(self):
        committed: list[tuple] = []
        seen: set[tuple] = set()

        def commit(payload):
            key = (payload["video_uuid"], payload["blob"]["sha256"], payload["caption"]["sha256"])
            committed.append(key)
            if key in seen:
                return {"ok": True, "deduped": True}
            seen.add(key)
            return {"ok": True}

        return commit, committed

    def test_local_journal_is_the_only_agent_side_orchestration_store(self, tmp_path):
        coordinator_src = (
            Path(__file__).resolve().parents[1] / "src" / "ingest" / "coordinator.py"
        ).read_text()
        assert "ingest_object_state" not in coordinator_src
        assert "app.models" not in coordinator_src
        assert "commit_verified_ingest" not in coordinator_src

    def test_reconciliation_local_journal_exists_db_absent(self, tmp_path):
        """Journal reached REMOTE_VERIFIED; DB commit never happened.
        Deterministic outcome: restart commits exactly once, converges."""
        coordinator, _, _, _ = make_coordinator(
            tmp_path, failpoints={"REMOTE_VERIFIED:before_effect": "raise"}
        )
        with pytest.raises(InjectedCrash):
            coordinator.run_once()
        commit_fn, committed = self._dedupe_commit_fn()
        restarted, store, _, _ = make_coordinator(
            tmp_path,
            store=IngestStateStore(tmp_path / "state" / "ingest.json"),
            commit_fn=commit_fn,
        )
        assert restarted.run_once() is IngestState.CACHE_CLEANED
        assert len(committed) == 1
        assert len(set(committed)) == 1

    def test_reconciliation_journal_lost_committed_db_rows_exist(self, tmp_path):
        """Journal lost after a full successful ingest. Deterministic outcome:
        full re-ingest converges to the SAME content-addressed result; server
        dedupe by content SHA collapses to one logical result, no duplicates."""
        coordinator, store, _, content = make_coordinator(tmp_path)
        assert coordinator.run_once() is IngestState.CACHE_CLEANED
        first_sha = coordinator.store.doc["media"]["sha256"]
        commit_fn, committed = self._dedupe_commit_fn()
        fresh_state = IngestStateStore(tmp_path / "state2" / "ingest.json")
        restarted, store2, _, _ = make_coordinator(
            tmp_path, store=fresh_state, commit_fn=commit_fn,
            object_store=store,
        )
        assert restarted.run_once() is IngestState.CACHE_CLEANED
        assert restarted.store.doc["media"]["sha256"] == first_sha
        assert len(store.objects) == 1
        keys = {(c[0], c[1]) for c in committed}
        assert len(keys) == 1

    def test_reconciliation_remote_exists_journal_says_pre_upload(self, tmp_path):
        """Journal at REMOTE_UPLOAD_STARTED (pre-upload) but object already
        exists remotely. Deterministic outcome: idempotent re-put of identical
        bytes, converges, no duplicate objects."""
        coordinator, store, _, content = make_coordinator(
            tmp_path, failpoints={"REMOTE_UPLOAD_STARTED:before_effect": "raise"}
        )
        with pytest.raises(InjectedCrash):
            coordinator.run_once()
        key = object_key_for_sha(sha256_bytes(content), ext="mov")
        store.objects[key] = content
        commit_fn, committed = self._dedupe_commit_fn()
        restarted, _, _, _ = make_coordinator(
            tmp_path,
            store=IngestStateStore(tmp_path / "state" / "ingest.json"),
            commit_fn=commit_fn,
            object_store=store,
        )
        assert restarted.run_once() is IngestState.CACHE_CLEANED
        assert store.store_sha256(key) == sha256_bytes(content)
        assert len(committed) == 1

    def test_reconciliation_db_committed_journal_says_pre_commit(self, tmp_path):
        """DB commit actually succeeded but the journal was not persisted
        (crash after effect). Deterministic outcome: restart re-commits;
        server dedupe collapses to one logical result."""
        coordinator, _, _, _ = make_coordinator(
            tmp_path, failpoints={"REMOTE_VERIFIED:after_effect": "raise"}
        )
        commit_fn_first, committed_first = self._dedupe_commit_fn()
        coordinator.commit_db_fn = commit_fn_first
        with pytest.raises(InjectedCrash):
            coordinator.run_once()
        assert len(committed_first) == 1
        state_file = tmp_path / "state" / "ingest.json"
        assert json.loads(state_file.read_text())["state"] == "REMOTE_VERIFIED"
        commit_fn, committed = self._dedupe_commit_fn()
        restarted, _, _, _ = make_coordinator(
            tmp_path, store=IngestStateStore(state_file), commit_fn=commit_fn
        )
        assert restarted.run_once() is IngestState.CACHE_CLEANED
        all_keys = {(c[0], c[1]) for c in committed_first + committed}
        assert len(all_keys) == 1


class TestFeatureFlagLegacyCompatibility:
    def _base_yaml(self, tmp_path, object_store: dict | None):
        server_block = (
            "server:\n"
            "  url: https://192.168.1.57:8000\n"
            f"  api_key: {'a' * 44}\n"
        )
        media_block = (
            "media:\n"
            "  enabled: true\n"
            "  allow_single_asset_materialization: true\n"
        )
        os_block = ""
        if object_store is not None:
            os_block = "object_store:\n" + "".join(
                f"  {k}: {json.dumps(v)}\n" for k, v in object_store.items()
            )
        return server_block + media_block + os_block

    def _write_config(self, tmp_path, object_store=None):
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(self._base_yaml(tmp_path, object_store))
        return cfg_path

    @staticmethod
    def _make_library(tmp_path):
        (tmp_path / "Pictures" / "Photos Library.photoslibrary").mkdir(
            parents=True, exist_ok=True
        )

    def test_default_config_object_store_disabled(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        self._make_library(tmp_path)
        cfg = Config.from_file(str(self._write_config(tmp_path)))
        assert cfg.validate() is True
        assert cfg.object_store.enabled is False

    def test_enabled_dev_with_prod_bucket_fails_validation(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        self._make_library(tmp_path)
        cfg_path = self._write_config(
            tmp_path,
            {
                "enabled": True,
                "environment": "dev",
                "bucket": "diveanalyzer-prod-media",
                "region": "eu-central-003",
            },
        )
        cfg = Config.from_file(str(cfg_path))
        from src.config import ConfigValidationError

        with pytest.raises(ConfigValidationError) as excinfo:
            cfg.validate()
        assert "object_store" in str(excinfo.value)

    def test_enabled_valid_dev_config_passes(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        self._make_library(tmp_path)
        cfg_path = self._write_config(
            tmp_path,
            {
                "enabled": True,
                "environment": "dev",
                "bucket": "diveanalyzer-dev-media",
                "region": "eu-central-003",
                "min_free_disk_bytes": 10**9,
            },
        )
        cfg = Config.from_file(str(cfg_path))
        assert cfg.validate() is True
        assert cfg.object_store.enabled is True
        assert cfg.object_store.bucket == "diveanalyzer-dev-media"

    def test_disabled_never_constructs_object_store(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        self._make_library(tmp_path)
        cfg = Config.from_file(str(self._write_config(tmp_path)))
        assert cfg.object_store.enabled is False
        imported = [
            name
            for name in list(sys.modules)
            if "botocore" in name or name == "boto3"
        ]
        assert imported == []
