#!/usr/bin/env python3
"""Check/request PhotoKit read-write authorization; never change library assets.

Run with the media-node venv interpreter in the logged-in user's Aqua session.
An SSH invocation is not proof of the production runtime's TCC authorization.
"""
import argparse
import json
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", action="store_true")
    args = parser.parse_args()

    import Photos
    from Foundation import NSDate, NSRunLoop

    names = {0: "not_determined", 1: "restricted", 2: "denied", 3: "authorized", 4: "limited"}
    level = Photos.PHAccessLevelReadWrite

    def report(stage, status):
        print(json.dumps({"stage": stage, "access_level": "read_write",
                          "status": names.get(int(status), str(status)),
                          "library_mutations": 0}), flush=True)

    before = Photos.PHPhotoLibrary.authorizationStatusForAccessLevel_(level)
    report("before", before)
    if before == 0 and args.request:
        completed = []
        Photos.PHPhotoLibrary.requestAuthorizationForAccessLevel_handler_(
            level, lambda status: completed.append(int(status)))
        deadline = time.monotonic() + 180
        while not completed and time.monotonic() < deadline:
            NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.2))
        if not completed:
            report("request_timeout", Photos.PHPhotoLibrary.authorizationStatusForAccessLevel_(level))
            return 2
    after = Photos.PHPhotoLibrary.authorizationStatusForAccessLevel_(level)
    report("after", after)
    return 0 if int(after) == 3 else 1


if __name__ == "__main__":
    raise SystemExit(main())
