"""P9 §29 B2 inventory reconciliation (read-only; runs on the ingest Mac).

Reconciles the PROD bucket (read-only LIST with the bucket-scoped ingest
key) against the server's DB-driven media inventory (agent-key endpoint
GET /api/v1/media/backbone/migration/inventory — storage facts only):

  - every verified PROD object_key in the DB must exist in the bucket
  - every bucket object key must be content-addressed
    (blobs/sha256/<2>/<sha>.<ext>)
  - orphan objects (in bucket, not referenced by a verified DB location)
    are REPORTED ONLY — never deleted, never hidden

The store adapter exposes delete only as an explicit-operator-action
method; this module never calls it.
"""

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from .objectstore.b2 import B2Config, BackblazeB2Store

CONTENT_KEY_RE = re.compile(r"^blobs/sha256/[0-9a-f]{2}/[0-9a-f]{64}\.[a-z0-9]{1,8}$")


@dataclass
class InventoryReport:
    object_count: int
    total_bytes: int
    malformed_keys: list[str]
    missing_verified_keys: list[str]
    orphans: list[str]

    def as_dict(self) -> dict:
        return {
            "object_count": self.object_count,
            "total_bytes": self.total_bytes,
            "malformed_keys": self.malformed_keys,
            "missing_verified_keys": self.missing_verified_keys,
            "orphans": self.orphans,
            "orphans_note": "REPORTED ONLY — no delete, no hide",
        }


def list_bucket(store: BackblazeB2Store) -> list[dict]:
    """Read-only full LIST of the configured bucket (paginated)."""
    client = store._client  # the S3-compatible client bound to the bucket
    bucket = store.config.bucket
    objects: list[dict] = []
    token = None
    while True:
        kwargs = {"Bucket": bucket}
        if token:
            kwargs["ContinuationToken"] = token
        resp = client.list_objects_v2(**kwargs)
        for item in resp.get("Contents") or []:
            objects.append({"key": item["Key"], "size": item["Size"]})
        if not resp.get("IsTruncated"):
            break
        token = resp.get("NextContinuationToken")
    return objects


def fetch_db_verified_prod_keys(inventory_items: list[dict]) -> set[str]:
    keys = set()
    for item in inventory_items:
        if item.get("verified_prod") and item.get("prod_object_key"):
            keys.add(item["prod_object_key"])
    return keys


def reconcile(objects: list[dict], verified_keys: set[str]) -> InventoryReport:
    bucket_keys = {o["key"] for o in objects}
    malformed = sorted(k for k in bucket_keys if not CONTENT_KEY_RE.match(k))
    missing = sorted(verified_keys - bucket_keys)
    orphans = sorted(bucket_keys - verified_keys)
    return InventoryReport(
        object_count=len(objects),
        total_bytes=sum(o["size"] for o in objects),
        malformed_keys=malformed,
        missing_verified_keys=missing,
        orphans=orphans,
    )


def main(argv=None) -> int:
    import argparse

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-url", required=True)
    parser.add_argument("--api-key-env", required=True,
                        help="env var NAME holding the mac-agent X-API-Key")
    parser.add_argument("--ca-cert", default=None)
    args = parser.parse_args(argv)

    import os
    from ..sync_client import _curl_get
    api_key = os.environ[args.api_key_env]
    status, body = _curl_get(
        args.server_url.rstrip("/") + "/api/v1/media/backbone/migration/inventory",
        api_key,
        60.0,
        args.ca_cert,
    )
    if status != 200:
        print(json.dumps({"error": f"inventory endpoint returned {status}"}))
        return 2
    items = json.loads(body)

    from ..config import Config
    # credentials come from the production env file (mac-agent convention)
    env_path = os.environ.get("B2_PROD_ENV_FILE")
    if not env_path:
        print(json.dumps({"error": "B2_PROD_ENV_FILE not set"}))
        return 2
    env = {}
    for line in Path(env_path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    os.environ.setdefault("B2_APPLICATION_KEY_ID", env["B2_APPLICATION_KEY_ID"])
    os.environ.setdefault("B2_APPLICATION_KEY", env["B2_APPLICATION_KEY"])
    config = B2Config(
        environment="prod",
        bucket=os.environ.get("B2_INVENTORY_BUCKET") or "diveanalyzer-prod-media",
        region=os.environ.get("B2_INVENTORY_REGION") or "eu-central-003",
        endpoint_url=os.environ.get("B2_INVENTORY_ENDPOINT_URL")
        or "https://s3.eu-central-003.backblazeb2.com",
    )
    store = BackblazeB2Store(config)
    objects = list_bucket(store)
    report = reconcile(objects, fetch_db_verified_prod_keys(items))
    ok = not (report.malformed_keys or report.missing_verified_keys)
    print(json.dumps(report.as_dict(), indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
