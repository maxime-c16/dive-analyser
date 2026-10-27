#!/usr/bin/env python3
"""Create/remove ONLY a synthetic Photos video, through the cleanup adapter.

Run in the Mac GUI session with venv Python. Does not run production cleanup.
The manifest must be new for creation; removal uses only its recorded asset.
"""
import argparse
import json
import sys
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["create", "remove"])
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--agent-root", required=True)
    parser.add_argument("--video")
    args = parser.parse_args()
    sys.path.insert(0, args.agent_root)
    from src.photos_cleanup import PhotoKitLibrary, atomic_json
    library = PhotoKitLibrary()
    manifest = Path(args.manifest)
    if args.action == "create":
        if manifest.exists() or not args.video:
            raise RuntimeError("new_manifest_and_synthetic_video_required")
        import Photos
        from Foundation import NSDate, NSRunLoop, NSURL
        finished = []
        identifiers = []

        def changes():
            request = Photos.PHAssetChangeRequest.creationRequestForAssetFromVideoAtFileURL_(
                NSURL.fileURLWithPath_(str(Path(args.video).resolve())))
            identifiers.append(str(request.placeholderForCreatedAsset().localIdentifier()))

        Photos.PHPhotoLibrary.sharedPhotoLibrary().performChanges_completionHandler_(
            changes, lambda success, error: finished.append(bool(success) and error is None))
        deadline = time.monotonic() + 45
        while not finished and time.monotonic() < deadline:
            NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.1))
        # Preserve the placeholder even after a timeout so the synthetic asset
        # can be inspected/recovered without scanning anyone's library.
        if identifiers:
            uuid = identifiers[0].split("/")[0]
            atomic_json(manifest, {"synthetic_canary": True, "photos_uuid": uuid,
                                  "local_identifier": identifiers[0],
                                  "version": library.version(uuid)})
        if not finished or not finished[0] or not identifiers:
            raise RuntimeError("synthetic_creation_failed_or_pending")
        print(json.dumps({"created": True, "photos_uuid": uuid}), flush=True)
    else:
        item = json.loads(manifest.read_text())
        if item.get("synthetic_canary") is not True or item.get("version") is None:
            raise RuntimeError("invalid_synthetic_manifest")
        uuid = item["photos_uuid"]
        library.remove(uuid, item["version"])
        item["removed"] = library.version(uuid) is None
        atomic_json(manifest, item)
        print(json.dumps({"removed": item["removed"], "photos_uuid": uuid}), flush=True)


if __name__ == "__main__":
    main()
