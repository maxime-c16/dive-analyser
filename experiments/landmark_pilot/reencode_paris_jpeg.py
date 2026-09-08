#!/usr/bin/env python3
import json, hashlib
from pathlib import Path
from PIL import Image

OUT_DIR = Path("/home/mcauchy/dive-analyser/media/perception_decomposition_v1/localization/PARIS")
manifest_path = OUT_DIR / "manifest.json"
rows = json.loads(manifest_path.read_text())


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


for row in rows:
    rid = row["id"]
    png_path = OUT_DIR / f"{rid}.png"
    jpg_path = OUT_DIR / f"{rid}.jpg"
    im = Image.open(png_path)
    assert im.size == (row["width"], row["height"]), (im.size, row["width"], row["height"])
    im.convert("RGB").save(jpg_path, format="JPEG", quality=92, optimize=True)
    row["image_ext"] = "jpg"
    row["image_sha256"] = sha256_file(jpg_path)
    png_kb = png_path.stat().st_size / 1024
    jpg_kb = jpg_path.stat().st_size / 1024
    print(f"{rid}: png={png_kb:.0f}KB jpg={jpg_kb:.0f}KB")

manifest_path.write_text(json.dumps(rows, indent=2) + "\n")
print("manifest updated")
