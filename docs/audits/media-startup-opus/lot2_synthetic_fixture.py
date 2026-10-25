"""Generate deterministic local-only fixtures; no real media or credentials."""
import argparse
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from PIL import Image
from app.config import get_settings
from app.services.poster_visuals import enrich_poster

parser = argparse.ArgumentParser()
parser.add_argument('directory', type=Path)
args = parser.parse_args()
root = args.directory.resolve()
root.mkdir(parents=True, exist_ok=True)
get_settings().media_cache_root = str(root)
fixtures = {'items':[], 'batch':{}, 'files':{}}
for i in range(11):
    rng = np.random.default_rng(i)
    coarse = Image.fromarray(rng.integers(0,256,(120,68,3),dtype=np.uint8)).resize((1080,1920), Image.Resampling.BILINEAR)
    pixels = np.array(coarse).astype(float)
    pixels = np.clip(pixels + rng.normal(0,4,pixels.shape), 0,255).astype(np.uint8)
    path = root / f'{i}.jpg'
    image = Image.fromarray(pixels)
    # Approximate the audit's 156 KB median without changing dimensions.
    quality = 60
    for q in range(30,96):
        image.save(path, quality=q)
        quality = q
        if path.stat().st_size >= 156000: break
    entry = SimpleNamespace(id=i, storage_path=str(path))
    with patch('app.services.poster_visuals.shutil.disk_usage', return_value=SimpleNamespace(free=100*1024**3)):
        enrich_poster(entry)
    uuid = f'00000000-0000-4000-8000-{i:012d}'
    poster = f'/api/v1/media/cache/{i+1}/play'
    thumb = f'/api/v1/media/cache/{i+1}/thumb'
    fixtures['files'][poster] = {'path': str(path), 'type':'image/jpeg'}
    fixtures['files'][thumb] = {'path':entry.thumb_storage_path, 'type':'image/webp'}
    fixtures['items'].append(dict(id=i+1, dive_code=['103B','201C','301B'][i%3], diver_id=1,
        performance='G', performance_numeric=3, height='1m', dive_datetime=f'2026-10-{25-i:02d}T10:00:00',
        session_id=1, is_lineup=False, is_sync=False, platform_type='springboard', position='B',
        official_dd=1.5, raw_caption='Synthetic fixture', video_uuid=uuid,
        thumbhash=entry.thumbhash, thumb_url=thumb))
    fixtures['batch'][uuid] = dict(status='ready', poster_url=poster, playback_url=None, thumb_url=thumb, thumbhash=entry.thumbhash)
(root/'fixtures.json').write_text(json.dumps(fixtures))
print(json.dumps({'posters_bytes':sum(Path(f['path']).stat().st_size for p,f in fixtures['files'].items() if p.endswith('play')),
                  'thumb_bytes':sum(Path(f['path']).stat().st_size for p,f in fixtures['files'].items() if p.endswith('thumb'))}))
