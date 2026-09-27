"""Read-only acquisition for the metadata-frozen FAX V2 raw-clip screen."""
import hashlib
import json
import os
from pathlib import Path

import boto3

rows = json.loads(Path('/tmp/fax_v2_shortlist.json').read_text())
out = Path('/tmp/fax_v2_sources')
out.mkdir(exist_ok=True)
client = boto3.client('s3', endpoint_url=os.environ['B2_PLAYBACK_ENDPOINT_URL'],
    aws_access_key_id=os.environ['B2_PLAYBACK_KEY_ID'],
    aws_secret_access_key=os.environ['B2_PLAYBACK_KEY_SECRET'],
    region_name=os.environ['B2_PLAYBACK_REGION'])
for r in rows:
    d = r['dive_id']
    path = out / f"{d}{Path(r['object_key']).suffix}"
    if not path.exists():
        obj = client.get_object(Bucket='diveanalyzer-prod-media', Key=r['object_key'])
        with path.open('wb') as f:
            for block in iter(lambda: obj['Body'].read(1 << 20), b''):
                f.write(block)
    h = hashlib.sha256(path.read_bytes()).hexdigest()
    assert h == r['sha256'], d
    print(d, path.stat().st_size, h[:12], flush=True)
