"""Backblaze B2 adapter over the S3-compatible API.

No credentials in source; credentials come from the environment
(B2_APPLICATION_KEY_ID / B2_APPLICATION_KEY) or are injected explicitly by the
operator config layer. Private bucket assumed and enforced. boto3 is imported
lazily so unit tests never require it.
"""

import os
import time
from pathlib import Path

from ..content_addr import validate_sha256
from ..errors import ConfigValidationError, ObjectStoreUnavailable
from .base import ObjectHead, PutResult

MAX_TTL_SECONDS = 7 * 24 * 3600
DEFAULT_MAX_RETRIES = 3

DEV_BUCKET_TOKEN = "dev"
PROD_BUCKET_TOKEN = "prod"


class B2Config:
    """Validated B2 configuration. Construction performs the firewall checks."""

    def __init__(
        self,
        environment: str,
        bucket: str,
        *,
        region: str | None = None,
        endpoint_url: str | None = None,
        prefix: str = "blobs/sha256",
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        presign_ttl_seconds: int = 3600,
    ):
        if environment not in ("dev", "prod"):
            raise ConfigValidationError(f"environment must be 'dev' or 'prod', got {environment!r}")
        if not bucket or not bucket.strip():
            raise ConfigValidationError("bucket must be a non-empty string")
        bucket = bucket.strip().lower()
        has_dev = DEV_BUCKET_TOKEN in bucket
        has_prod = PROD_BUCKET_TOKEN in bucket
        if has_dev and has_prod:
            raise ConfigValidationError(f"bucket name {bucket!r} references both environments")
        if has_prod and environment != "prod":
            raise ConfigValidationError(
                f"DEV environment configured with PROD bucket {bucket!r}"
            )
        if has_dev and environment != "dev":
            raise ConfigValidationError(
                f"PROD environment configured with DEV bucket {bucket!r}"
            )
        if not has_dev and not has_prod:
            raise ConfigValidationError(
                f"bucket {bucket!r} does not declare its environment (expected "
                f"'{environment}' token in name)"
            )
        if not endpoint_url and not region:
            raise ConfigValidationError("either region or endpoint_url is required")
        prefix = (prefix or "").strip("/")
        if prefix and (".." in prefix or not prefix.replace("/", "").replace("-", "").replace("_", "").replace(".", "").isalnum()):
            raise ConfigValidationError(f"unexpected object prefix: {prefix!r}")
        ttl = int(presign_ttl_seconds)
        if ttl <= 0 or ttl > MAX_TTL_SECONDS:
            raise ConfigValidationError(f"presign ttl out of range: {ttl}")
        if max_retries < 0 or max_retries > 10:
            raise ConfigValidationError(f"max_retries out of range: {max_retries}")

        self.environment = environment
        self.bucket = bucket
        self.region = region
        self.endpoint_url = endpoint_url or f"https://s3.{region}.backblazeb2.com"
        self.prefix = prefix
        self.max_retries = max_retries
        self.presign_ttl_seconds = ttl
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key

    def resolve_credentials(self) -> tuple[str, str]:
        key_id = self._access_key_id or os.environ.get("B2_APPLICATION_KEY_ID")
        secret = self._secret_access_key or os.environ.get("B2_APPLICATION_KEY")
        if not key_id or not secret:
            raise ConfigValidationError(
                "missing credentials: set B2_APPLICATION_KEY_ID and B2_APPLICATION_KEY"
            )
        return key_id, secret

    def key_for_sha(self, sha: str, ext: str | None = None) -> str:
        validate_sha256(sha)
        key = f"{self.prefix}/{sha[:2]}/{sha}" if self.prefix else f"{sha[:2]}/{sha}"
        if ext:
            key = f"{key}.{ext.lower().lstrip('.')}"
        return key


class BackblazeB2Store:
    """S3-compatible B2 store. Full GET is used for canary verification.

    `delete_object_explicit_operator_action` is intentionally verbose and is NOT
    part of the ingest synchronization path; no automatic deletion participates
    in ingest.
    """

    def __init__(self, config: B2Config, client=None, client_factory=None):
        self.config = config
        if client is not None:
            self._client = client
        else:
            if client_factory is None:
                try:
                    import boto3
                except ImportError as exc:
                    raise ConfigValidationError(
                        "boto3 is not installed; install it to use the B2 adapter"
                    ) from exc

                def client_factory():
                    key_id, secret = config.resolve_credentials()
                    return boto3.client(
                        "s3",
                        endpoint_url=config.endpoint_url,
                        aws_access_key_id=key_id,
                        aws_secret_access_key=secret,
                        region_name=config.region or "us-east-1",
                    )

            self._client = client_factory()

    def _with_retries(self, fn):
        last_error: Exception | None = None
        for attempt in range(self.config.max_retries + 1):
            try:
                return fn()
            except ConfigValidationError:
                raise
            except Exception as exc:
                last_error = exc
                if attempt < self.config.max_retries:
                    time.sleep(min(2 ** attempt, 8))
        raise ObjectStoreUnavailable(f"object store unavailable after retries: {last_error}") from last_error

    def put(self, key: str, source: bytes | Path, content_type: str | None = None) -> PutResult:
        from hashlib import sha256 as _sha

        if isinstance(source, (bytes, bytearray)):
            data = bytes(source)
            kwargs = {"Bucket": self.config.bucket, "Key": key, "Body": data}
            if content_type:
                kwargs["ContentType"] = content_type
            self._with_retries(lambda: self._client.put_object(**kwargs))
            return PutResult(key=key, sha256=_sha(data).hexdigest(), byte_size=len(data))
        path = Path(source)
        digest = _sha()
        size = 0
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
        upload_kwargs = {"ContentType": content_type} if content_type else None
        self._with_retries(
            lambda: self._client.upload_fileobj(
                open(path, "rb"),
                self.config.bucket,
                key,
                ExtraArgs=upload_kwargs,
            )
        )
        return PutResult(key=key, sha256=digest.hexdigest(), byte_size=size)

    def head(self, key: str) -> ObjectHead | None:
        last_error: Exception | None = None
        for attempt in range(self.config.max_retries + 1):
            try:
                resp = self._client.head_object(Bucket=self.config.bucket, Key=key)
                return ObjectHead(
                    key=key,
                    byte_size=int(resp.get("ContentLength", 0)),
                    etag=resp.get("ETag"),
                )
            except Exception as exc:
                code = ""
                response = getattr(exc, "response", None)
                if isinstance(response, dict):
                    code = response.get("Error", {}).get("Code", "")
                if code in ("404", "NoSuchKey", "NotFound"):
                    return None
                if code in ("403", "AccessDenied"):
                    # P4.2 repair (verified live 2026-09-09): Backblaze B2's
                    # S3 API returns 403 Forbidden — NOT 404 — for HeadObject
                    # on a MISSING object when the application key holds
                    # least-privilege capabilities. Disambiguate with a
                    # prefix LIST probe (listFiles is an authorized
                    # capability): absent -> None (idempotent ingest path
                    # proceeds to PUT); still present -> real auth problem,
                    # fail closed below. If the LIST probe itself fails, the
                    # error is treated as real (fail closed).
                    if self._absent_by_prefix_list(key):
                        return None
                last_error = exc
                if attempt < self.config.max_retries:
                    time.sleep(min(2 ** attempt, 8))
        raise ObjectStoreUnavailable(f"head failed after retries: {last_error}") from last_error

    def _absent_by_prefix_list(self, key: str) -> bool:
        """True ONLY when a successful prefix LIST proves the key absent.
        Any list failure returns False (fail closed: the caller raises)."""
        try:
            resp = self._client.list_objects_v2(
                Bucket=self.config.bucket, Prefix=key, MaxKeys=1
            )
        except Exception:
            return False
        contents = resp.get("Contents") or []
        return not any(obj.get("Key") == key for obj in contents)

    def get(self, key: str) -> bytes:
        resp = self._with_retries(
            lambda: self._client.get_object(Bucket=self.config.bucket, Key=key)
        )
        return resp["Body"].read()

    def get_streaming_sha(self, key: str, chunk_size: int = 1024 * 1024):
        """Full GET streamed through a hash sink; bytes are never buffered
        whole in RAM and never written to disk (P10 §28/§29/§31).

        Returns (sha256_hex, byte_size). Raises ObjectStoreUnavailable on
        transport failure after bounded retries."""
        from hashlib import sha256 as _sha

        resp = self._with_retries(
            lambda: self._client.get_object(Bucket=self.config.bucket, Key=key)
        )
        digest = _sha()
        size = 0
        body = resp["Body"]
        try:
            for chunk in iter(lambda: body.read(chunk_size), b""):
                digest.update(chunk)
                size += len(chunk)
        finally:
            try:
                body.close()
            except Exception:
                pass
        return digest.hexdigest(), size

    def presign_get(self, key: str, ttl_seconds: int) -> str:
        if ttl_seconds <= 0 or ttl_seconds > MAX_TTL_SECONDS:
            raise ConfigValidationError(f"presign ttl out of range: {ttl_seconds}")
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.config.bucket, "Key": key},
            ExpiresIn=ttl_seconds,
        )

    def delete_object_explicit_operator_action(self, key: str) -> None:
        self._client.delete_object(Bucket=self.config.bucket, Key=key)
