"""ObjectStore port: put / head / get / presign_get (delete is guarded)."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class PutResult:
    key: str
    sha256: str
    byte_size: int
    etag: str | None = None


@dataclass(frozen=True)
class ObjectHead:
    key: str
    byte_size: int
    etag: str | None = None


@runtime_checkable
class ObjectStore(Protocol):
    def put(self, key: str, source: bytes | Path, content_type: str | None = None) -> PutResult: ...

    def head(self, key: str) -> ObjectHead | None: ...

    def get(self, key: str) -> bytes: ...

    def presign_get(self, key: str, ttl_seconds: int) -> str: ...
