"""Deterministic in-memory object store with fault injection for tests."""

import threading
from pathlib import Path

from ..content_addr import sha256_bytes
from ..errors import ObjectStoreError, ObjectStoreUnavailable
from .base import ObjectHead, PutResult


class FakeObjectStore:
    """In-memory backend. No network, no credentials.

    Fault injection:
      fail_after_bytes: raise ObjectStoreUnavailable mid-upload (interrupted put)
      corrupt_keys:     set of keys whose stored bytes are corrupted on put
      error_keys:       set of keys where head/get raise ObjectStoreUnavailable
    """

    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.etags: dict[str, str] = {}
        self.put_counts: dict[str, int] = {}
        self.presigned: list[tuple[str, int]] = []
        self.put_content_types: dict[str, str] = {}
        self.fail_after_bytes: int | None = None
        self.corrupt_keys: set[str] = set()
        self.error_keys: set[str] = set()
        self._lock = threading.Lock()

    def put(self, key: str, source: bytes | Path, content_type: str | None = None) -> PutResult:
        if content_type is not None:
            with self._lock:
                self.put_content_types[key] = content_type
        data = bytes(source) if isinstance(source, (bytes, bytearray)) else Path(source).read_bytes()
        with self._lock:
            self.put_counts[key] = self.put_counts.get(key, 0) + 1
            if self.fail_after_bytes is not None and len(data) > self.fail_after_bytes:
                limit = self.fail_after_bytes
                self.fail_after_bytes = None
                raise ObjectStoreUnavailable(
                    f"interrupted upload after {limit} bytes"
                )
            stored = data
            if key in self.corrupt_keys:
                stored = b"CORRUPTED" + data[1:]
            self.objects[key] = stored
            self.etags[key] = f"fake-etag-{len(stored)}-{self.put_counts[key]}"
        return PutResult(key=key, sha256=sha256_bytes(data), byte_size=len(data), etag=self.etags[key])

    def head(self, key: str) -> ObjectHead | None:
        with self._lock:
            if key in self.error_keys:
                raise ObjectStoreUnavailable(f"head error for {key}")
            if key not in self.objects:
                return None
            return ObjectHead(key=key, byte_size=len(self.objects[key]), etag=self.etags.get(key))

    def get(self, key: str) -> bytes:
        with self._lock:
            if key in self.error_keys:
                raise ObjectStoreUnavailable(f"get error for {key}")
            if key not in self.objects:
                raise ObjectStoreError(f"object not found: {key}")
            return self.objects[key]

    def presign_get(self, key: str, ttl_seconds: int) -> str:
        self.presigned.append((key, ttl_seconds))
        return f"https://fake.invalid/{key}?ttl={ttl_seconds}"

    def delete_object_explicit_operator_action(self, key: str) -> None:
        with self._lock:
            self.objects.pop(key, None)

    def store_sha256(self, key: str) -> str:
        return sha256_bytes(self.objects[key])
