#!/usr/bin/env python3
"""Read-only B2 acquisition of the pre-frozen FPSR2 edited sources.

Run inside the canonical backend container with its playback-scoped credentials.
Only GetObject is used. The split file supplies exact object keys and SHA256s.
"""
import hashlib
import json
import os
from pathlib import Path

import boto3

split = json.loads(Path('/tmp/fpsr2_split.json').read_text())
assert split['status'] == 'FROZEN_BEFORE_RECOVERY_FUSION_DESIGN'
out = Path('/tmp/fpsr2_hq')
out.mkdir(exist_ok=True)
client = boto3.client('s3', endpoint_url=os.environ['B2_PLAYBACK_ENDPOINT_URL'],
                      aws_access_key_id=os.environ['B2_PLAYBACK_KEY_ID'],
                      aws_secret_access_key=os.environ['B2_PLAYBACK_KEY_SECRET'],
                      region_name=os.environ['B2_PLAYBACK_REGION'])
manifest = {}
for r in split['dives']:
    d = str(r['dive_id'])
    key = r['object_key']
    path = out / f'{d}{Path(key).suffix}'
    if not path.exists():
        obj = client.get_object(Bucket='diveanalyzer-prod-media', Key=key)
        with path.open('wb') as f:
            for block in iter(lambda: obj['Body'].read(1 << 20), b''):
                f.write(block)
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    assert h.hexdigest() == r['edited_blob_sha256'], d
    manifest[d] = {'file': path.name, 'sha256': h.hexdigest(), 'bytes': path.stat().st_size,
                   'object_key': key, 'ok': True}
    print(d, path.stat().st_size, h.hexdigest()[:12], flush=True)
(out / 'b2_download_manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True))
