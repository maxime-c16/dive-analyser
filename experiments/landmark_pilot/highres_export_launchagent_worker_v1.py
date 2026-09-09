#!/usr/bin/env python3
"""One-shot high-resolution Photos export worker.

This script is intended to run from a macOS Aqua LaunchAgent whose executable has
normal Photos Full Access. It exports one asset at a time and writes a durable
JSON manifest that can be copied back to the science repo.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any


OSXPHOTOS = "/Users/Shared/services/data/diveanalyzer/venv/bin/osxphotos"
FFPROBE = "/Users/Shared/services/data/diveanalyzer/bin/ffprobe"

CANARIES = [
    {"dive_id": 133, "uuid": "ABD32644-4536-416F-9572-86849FCF15B5"},
    {"dive_id": 311, "uuid": "D0C33293-F4B7-4A57-9368-9C53BFC32033"},
    {"dive_id": 676, "uuid": "AA890D9A-A8AE-44C4-B6A4-C82BDAD56F46"},
    {"dive_id": 2169, "uuid": "B6AC3A80-752B-439F-A927-01550A6F52C1"},
]

REPRESENTATIONS = [
    ("EDITED_HIGHRES_RENDITION", ["--skip-original-if-edited"]),
    ("ORIGINAL_MASTER", ["--skip-edited"]),
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ffprobe(path: Path) -> dict[str, Any]:
    proc = subprocess.run(
        [
            FFPROBE,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,width,height,avg_frame_rate,r_frame_rate,nb_frames,duration",
            "-show_entries",
            "format=duration,size,format_name",
            "-of",
            "json",
            str(path),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
        check=False,
    )
    return {
        "returncode": proc.returncode,
        "stdout": json.loads(proc.stdout or "{}") if proc.stdout else {},
        "stderr_tail": proc.stderr[-1000:],
    }


def export_one(root: Path, item: dict[str, Any], representation: str, flags: list[str]) -> dict[str, Any]:
    outdir = root / f"dive_{item['dive_id']}" / representation.lower()
    outdir.mkdir(parents=True, exist_ok=True)
    cmd = [
        OSXPHOTOS,
        "export",
        str(outdir),
        "--uuid",
        item["uuid"],
        "--only-movies",
        "--download-missing",
        "--use-photokit",
        "--update",
        "--verbose",
        *flags,
    ]
    started = time.time()
    try:
        proc = subprocess.run(
            cmd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=1200,
            check=False,
        )
        returncode = proc.returncode
        stdout_tail = proc.stdout[-5000:]
        stderr_tail = proc.stderr[-5000:]
    except Exception as exc:  # pragma: no cover - operational guard
        returncode = 99
        stdout_tail = ""
        stderr_tail = repr(exc)

    files = []
    for path in sorted(outdir.rglob("*")):
        if not path.is_file() or path.name == ".osxphotos_export.db":
            continue
        files.append(
            {
                "path": str(path),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
                "ffprobe": ffprobe(path),
            }
        )

    return {
        "dive_id": item["dive_id"],
        "uuid": item["uuid"],
        "representation": representation,
        "returncode": returncode,
        "elapsed_s": time.time() - started,
        "stdout_tail": stdout_tail,
        "stderr_tail": stderr_tail,
        "files": files,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--items-json", default="")
    parser.add_argument("--items-file", default="")
    parser.add_argument(
        "--representations",
        default="EDITED_HIGHRES_RENDITION,ORIGINAL_MASTER",
        help="Comma-separated subset of representation names to export.",
    )
    args = parser.parse_args()

    os.environ["LC_ALL"] = "C"
    os.environ["LANG"] = "C"

    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)
    if args.items_file:
        items = json.loads(Path(args.items_file).read_text(encoding="utf-8"))
    elif args.items_json:
        items = json.loads(args.items_json)
    else:
        items = CANARIES
    requested_representations = {name.strip() for name in args.representations.split(",") if name.strip()}
    representations = [
        (name, flags)
        for name, flags in REPRESENTATIONS
        if name in requested_representations
    ]
    if not representations:
        raise SystemExit("no valid representations requested")

    results = []
    for item in items:
        for representation, flags in representations:
            results.append(export_one(root, item, representation, flags))
            (root / "manifest.partial.json").write_text(
                json.dumps({"results": results}, indent=2),
                encoding="utf-8",
            )

    (root / "manifest.json").write_text(
        json.dumps(
            {
                "label": "HIGHRES_EXPORT_LAUNCHAGENT_WORKER_V1",
                "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "tooling": {
                    "worker": "experiments/landmark_pilot/highres_export_launchagent_worker_v1.py",
                    "osxphotos": OSXPHOTOS,
                    "ffprobe": FFPROBE,
                },
                "results": results,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
