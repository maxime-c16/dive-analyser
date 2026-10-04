"""Content addressing: sha256 identity and deterministic privacy-safe object keys."""

import hashlib
import re
from pathlib import Path

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DEFAULT_PREFIX = "blobs/sha256"
_KEY_SAFE_RE = re.compile(r"^[a-z0-9][a-z0-9/._-]*$")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def validate_sha256(sha: str) -> str:
    if not isinstance(sha, str) or not SHA256_RE.match(sha):
        raise ValueError(f"malformed sha256: expected 64 lowercase hex chars, got {sha!r}")
    return sha


def object_key_for_sha(sha: str, ext: str | None = None, prefix: str = DEFAULT_PREFIX) -> str:
    validate_sha256(sha)
    if prefix and not _KEY_SAFE_RE.match(prefix):
        raise ValueError(f"unsafe object prefix: {prefix!r}")
    if ".." in prefix:
        raise ValueError(f"unsafe object prefix: {prefix!r}")
    key = f"{prefix}/{sha[:2]}/{sha}" if prefix else f"{sha[:2]}/{sha}"
    if ext is not None:
        ext = ext.lower().lstrip(".")
        if not re.match(r"^[a-z0-9]{1,8}$", ext):
            raise ValueError(f"unsafe object key extension: {ext!r}")
        key = f"{key}.{ext}"
    return key
