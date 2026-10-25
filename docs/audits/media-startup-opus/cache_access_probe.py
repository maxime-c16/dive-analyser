"""Compare the pre-lot1 cache reader at an explicit git ref with today's reader.

Uses synthetic bytes + disposable SQLite; counts commits, NOT production I/O.
Run from repo root: DATABASE_URL=sqlite:///:memory: python cache_access_probe.py
Requires --baseline-ref so the comparison remains reproducible after committing.
"""
import argparse
import ast
import json
from pathlib import Path
import subprocess
import tempfile

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.main import app  # register all model mappings; no app startup
from app.database import Base
from app.config import get_settings
from app.models.photos_asset import PhotosAsset
from app.models.media import MediaCacheEntry
from app.services import media_cache


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline-ref', required=True)
    args = parser.parse_args()
    source = subprocess.check_output(['git', 'show', args.baseline_ref + ':backend/app/services/media_cache.py'], text=True)
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == 'get_playable_entry')
    namespace = vars(media_cache).copy()
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<baseline-cache-reader>', 'exec'), namespace)
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine, tables=[PhotosAsset.__table__, MediaCacheEntry.__table__])
    out = {'baseline_ref': args.baseline_ref, 'backend': 'disposable SQLite', 'views_per_variant': 15}
    settings = get_settings()
    saved_root = settings.media_cache_root
    try:
        with tempfile.TemporaryDirectory(prefix='media-lot1-cache-') as root, Session(engine) as db:
            settings.media_cache_root = root
            path = Path(root) / 'poster.jpg'
            path.write_bytes(b'synthetic-poster')
            asset = PhotosAsset(video_uuid='synthetic-cache-probe')
            db.add(asset)
            db.flush()
            entry = MediaCacheEntry(photos_asset_id=asset.id, media_key='probe-poster', rendition='poster',
                storage_path=str(path), size_bytes=path.stat().st_size, status='ready')
            db.add(entry)
            db.commit()
            entry_id = entry.id
            for label, reader in [('before', namespace['get_playable_entry']), ('after', media_cache.get_playable_entry)]:
                entry.last_accessed_at = None
                db.commit()
                commits = []
                def committed(session):
                    commits.append(1)
                event.listen(db, 'after_commit', committed)
                try:
                    for _ in range(15):
                        reader(db, entry_id)
                finally:
                    event.remove(db, 'after_commit', committed)
                out[label + '_commits'] = len(commits)
    finally:
        settings.media_cache_root = saved_root
        engine.dispose()
    print(json.dumps(out, indent=2))


if __name__ == '__main__':
    main()
