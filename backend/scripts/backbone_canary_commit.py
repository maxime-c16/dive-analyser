"""Backbone canary commit transport (server side, operator-tunneled).

Reads one JSON document on stdin:

    {
      "payload": { ...ObjectStoreIngestCoordinator._db_payload() ... },
      "extra": {
        "environment": "dev",
        "codec": ..., "width": ..., "height": ..., "duration_seconds": ...,
        "photos_edit_fingerprint": ..., "source_provenance": {...},
        "shadow_provider": ..., "shadow_raw": ..., "shadow_sha256": ...,
        "shadow_available": ..., "parser_version": ..., "parsed_json": {...}
      }
    }

Calls the accepted verified-ingest commit service
(`app.services.media_backbone.commit_verified_ingest`) and prints:

    {"input": <exact input document>, "result": <service return>}

The printed document is the receipt: the mac-side coordinator restart only
marks DB_COMMITTED when a receipt whose `input.payload` exactly matches the
staged coordinator payload is presented. Secrets never appear here; the
receipt contains hashes, sizes and keys only (plus the private caption/shadow
raw text which stays inside the server DB and the private state dir).
"""

import json
import sys

from app.database import SessionLocal
from app.services.media_backbone import commit_verified_ingest


def main() -> int:
    document = json.load(sys.stdin)
    payload = document["payload"]
    extra = document.get("extra") or {}
    caption = payload["caption"]
    blob = payload["blob"]

    db = SessionLocal()
    try:
        result = commit_verified_ingest(
            db,
            video_uuid=payload["video_uuid"],
            blob_sha256=blob["sha256"],
            byte_size=int(blob["byte_size"]),
            object_key=blob["object_key"],
            storage_backend=blob["storage_backend"],
            bucket=blob["bucket"],
            caption_raw=caption["raw"],
            caption_sha=caption["sha256"],
            caption_provider=caption["provider"],
            verified=bool(payload.get("remote_verified")),
            rendition_semantics=payload.get("rendition_semantics", "photos_edited_rendition"),
            codec=extra.get("codec"),
            width=extra.get("width"),
            height=extra.get("height"),
            duration_seconds=extra.get("duration_seconds"),
            photos_edit_fingerprint=extra.get("photos_edit_fingerprint"),
            source_provenance=extra.get("source_provenance"),
            shadow_provider=extra.get("shadow_provider"),
            shadow_raw=extra.get("shadow_raw"),
            shadow_sha256=extra.get("shadow_sha256"),
            shadow_available=extra.get("shadow_available"),
            parser_version=extra.get("parser_version"),
            parsed_json=extra.get("parsed_json"),
            ingest_impl_version=payload.get("ingest_impl_version", "media_backbone_v1"),
            environment=extra.get("environment", "dev"),
        )
    finally:
        db.close()

    print(json.dumps({"input": document, "result": result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
