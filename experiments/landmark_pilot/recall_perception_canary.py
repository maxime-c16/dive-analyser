#!/usr/bin/env python3
"""Sequential, exact-UUID, read-only Photos exports for the authorized six assets."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

CANARIES = {
    2661: "D73DB757-0A6F-40BD-A167-D3A3753B617F",
    2169: "B6AC3A80-752B-439F-A927-01550A6F52C1",
    192: "ADB6FB70-6CE7-4AD3-B8E3-3F05928AC7DF",
    311: "D0C33293-F4B7-4A57-9368-9C53BFC32033",
    2555: "1FBF7764-0257-4AC1-8634-B99C0FA80949",
    2387: "51BDE272-B56F-411A-997C-5B2277127CA5",
}
ROOT = Path("/Users/Shared/services/data/perception-decomposition-v1/originals")
CLI = "/Users/Shared/services/data/diveanalyzer/venv/bin/osxphotos"
PROBE = "/Users/Shared/services/data/diveanalyzer/bin/ffprobe"


def checksum(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, LC_ALL="en_US.UTF-8")
    results = []
    for did, uuid in CANARIES.items():
        dest = ROOT / str(did)
        dest.mkdir(exist_ok=True)
        argv = [CLI, "export", str(dest), "--uuid", uuid, "--only-movies",
                "--download-missing", "--use-photokit", "--skip-edited", "--update", "--no-progress"]
        started = time.monotonic()
        try:
            process = subprocess.run(argv, capture_output=True, text=True, env=env, timeout=600)
            status = "export_command_completed" if process.returncode == 0 else "export_failed"
            log = (process.stdout + process.stderr)[-6000:]
        except subprocess.TimeoutExpired:
            status, log = "timeout", "Exact-UUID export exceeded 600 seconds"
        (dest / "export.log").write_text(log)
        files = []
        for path in dest.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in (".mov", ".mp4", ".m4v"):
                continue
            if path.stat().st_size == 0:
                continue
            probe = json.loads(subprocess.check_output([PROBE, "-v", "error", "-show_streams",
                                                       "-show_format", "-of", "json", str(path)], timeout=60))
            files.append({"path": str(path), "size_bytes": path.stat().st_size,
                          "sha256": checksum(path), "probe": probe})
        result = {"dive_id": did, "agent_local_uuid": uuid, "status": status,
                  "seconds": round(time.monotonic() - started, 2), "argv": argv, "files": files,
                  "split": "INTERNAL_EVAL" if did == 192 else "DEVELOPMENT_DESIGN"}
        results.append(result)
        (ROOT / "provenance.json").write_text(json.dumps(results, indent=2) + "\n")
        print(json.dumps({"dive_id": did, "status": status, "files": len(files),
                          "bytes": sum(f["size_bytes"] for f in files)}), flush=True)


if __name__ == "__main__":
    main()
