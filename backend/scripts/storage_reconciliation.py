#!/usr/bin/env python
"""P9 §28/§29 storage reconciliation + B2 inventory (read-only).

STORAGE RECONCILIATION (§28): every eligible logical OWNER MediaRevision
must resolve to EXACTLY ONE verified PROD B2 location. Ambiguity, unverified
locations, DEV-only replicas and missing ownership chains are reported as
drift. Read-only; performs no writes.

B2 INVENTORY (§29): when --b2-env-file is given (the least-privilege ingest
key env file, mac-agent convention), lists the PROD bucket read-only and
reconciles:
  - every real media object key must be content-addressed
    (blobs/sha256/<2>/<sha>.<ext>)
  - every DB verified PROD location must exist in the bucket
  - unexplained orphans are reported (NEVER deleted or hidden)

Privacy-safe output: keys are content-addressed SHAs; nothing else.

Usage:
    python scripts/storage_reconciliation.py                 # DB-only
    python scripts/storage_reconciliation.py --b2-env-file E  # + bucket list
"""

import argparse
import json
import os
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select

from app.database import init_db
from app.database import SessionLocal
from app.models.dive import Dive
from app.models.media_backbone import MediaBlob, MediaBlobLocation, MediaRevision
from app.models.user_auth import UserDiverAccess

CONTENT_KEY_PREFIX = "blobs/sha256"


def load_b2_env(env_file: str) -> dict:
    creds = {}
    with open(env_file, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            creds[key.strip()] = value.strip()
    return creds


def b2_list_objects(env_file: str, prefix: str = CONTENT_KEY_PREFIX) -> list[dict]:
    """Read-only LIST of the PROD bucket with the bucket-scoped ingest key."""
    creds = load_b2_env(env_file)
    import boto3  # lazy import; only needed for the live inventory leg

    client = boto3.client(
        "s3",
        endpoint_url=os.environ.get(
            "B2_ENDPOINT_URL", "https://s3.eu-central-003.backblazeb2.com"
        ),
        aws_access_key_id=creds["B2_APPLICATION_KEY_ID"],
        aws_secret_access_key=creds["B2_APPLICATION_KEY"],
    )
    bucket = creds.get("B2_BUCKET_NAME") or creds.get("B2_BUCKET") or "diveanalyzer-prod-media"
    objects = []
    token: Optional[str] = None
    while True:
        kwargs = {"Bucket": bucket, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        resp = client.list_objects_v2(**kwargs)
        for item in resp.get("Contents", []):
            objects.append({"key": item["Key"], "size": item["Size"]})
        if not resp.get("IsTruncated"):
            break
        token = resp.get("NextContinuationToken")
    return objects


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--b2-env-file", default=None,
        help="least-privilege PROD ingest key env file (mac-agent format)",
    )
    args = parser.parse_args(argv)
    init_db()

    report: dict = {"storage_reconciliation": {}, "b2_inventory": None}

    with SessionLocal() as db:
        owner_diver_ids = {
            row[0]
            for row in db.execute(
                select(UserDiverAccess.diver_id).where(
                    UserDiverAccess.access_kind == "OWNER"
                )
            ).all()
        }
        dives_by_video_uuid = dict(db.query(Dive.video_uuid, Dive.diver_id).all())
        revisions = db.query(MediaRevision).order_by(MediaRevision.id).all()
        prod_locations = {}
        for loc in db.query(MediaBlobLocation).filter_by(environment="prod").all():
            prod_locations.setdefault(loc.blob_sha256, []).append(loc)

        eligible = 0
        reconciled = 0
        drift = []
        for revision in revisions:
            diver_id = dives_by_video_uuid.get(revision.video_uuid)
            if diver_id is None or diver_id not in owner_diver_ids:
                continue
            eligible += 1
            locs = [l for l in prod_locations.get(revision.blob_sha256, []) if l.verified]
            if len(locs) == 1 and (locs[0].storage_backend or "").lower() == "b2":
                reconciled += 1
            else:
                drift.append(
                    {
                        "media_revision_id": revision.id,
                        "video_uuid": revision.video_uuid,
                        "verified_prod_locations": len(locs),
                    }
                )
        total_revisions = len(revisions)
        report["storage_reconciliation"] = {
            "eligible_owner_revisions": eligible,
            "exactly_one_verified_prod": reconciled,
            "drift_count": len(drift),
            "drift": drift,
            "ratio": round(reconciled / eligible, 4) if eligible else 0.0,
            "non_owner_revisions": total_revisions - eligible,
        }

    if args.b2_env_file:
        objects = b2_list_objects(args.b2_env_file)
        with SessionLocal() as db:
            verified_keys = {
                loc.object_key
                for loc in db.query(MediaBlobLocation).filter_by(
                    environment="prod", verified=True
                ).all()
            }
        malformed = [o["key"] for o in objects if not o["key"].startswith(CONTENT_KEY_PREFIX)]
        missing = sorted(k for k in verified_keys if k not in {o["key"] for o in objects})
        orphans = sorted(o["key"] for o in objects if o["key"] not in verified_keys)
        report["b2_inventory"] = {
            "object_count": len(objects),
            "total_bytes": sum(o["size"] for o in objects),
            "malformed_keys": malformed,
            "missing_verified_keys": missing,
            "orphans": orphans,
            "note": "orphans are REPORTED ONLY — never deleted or hidden",
        }

    print(json.dumps(report, indent=2))
    storage = report["storage_reconciliation"]
    ok = storage["drift_count"] == 0 and storage["ratio"] == 1.0
    if report["b2_inventory"]:
        inv = report["b2_inventory"]
        ok = ok and not inv["missing_verified_keys"]
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
