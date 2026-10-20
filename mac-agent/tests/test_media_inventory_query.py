"""Run the inventory's actual cache query against duplicate/out-of-scope rows."""
import ast
from pathlib import Path
import sqlite3


def test_inventory_selects_latest_ready_per_rendition_in_requested_scope():
    source = Path(__file__).resolve().parents[2] / 'ops/media-cache-inventory.py'
    tree = ast.parse(source.read_text())
    query = next(ast.literal_eval(node.value) for node in tree.body
                 if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'ENTRY_QUERY' for target in node.targets))
    with sqlite3.connect(':memory:') as db:
        db.execute('CREATE TABLE media_cache_entries (id INTEGER, photos_asset_id INTEGER, rendition TEXT, storage_backend TEXT, storage_path TEXT, size_bytes INTEGER, created_at TEXT, status TEXT)')
        db.executemany('INSERT INTO media_cache_entries VALUES (?,?,?,?,?,?,?,?)', [
            (1, 10, 'proxy_720p', 'local_fs', '/older', 1, '2026-10-20', 'ready'),
            (2, 10, 'proxy_720p', 'local_fs', '/latest-missing', 1, '2026-10-20', 'ready'),
            (3, 10, 'poster', 'local_fs', '/poster', 1, '2026-10-19', 'ready'),
            (4, 20, 'proxy_720p', 'local_fs', '/outside-public-batch', 1, '2026-10-21', 'ready'),
            (5, 10, 'proxy_720p', 'local_fs', '/not-ready', 1, '2026-10-21', 'failed'),
            (6, 11, 'proxy_360p', 'local_fs', '/older-id-newer-date', 1, '2026-10-21', 'ready'),
            (7, 11, 'proxy_360p', 'local_fs', '/newer-id-older-date', 1, '2026-10-20', 'ready'),
        ])
        rows = db.execute(query.replace('IN :asset_ids', 'IN (?,?)'), (10, 11)).fetchall()
        assert {(row[0], row[1]): row[3] for row in rows} == {
            (10, 'proxy_720p'): '/latest-missing', (10, 'poster'): '/poster',
            (11, 'proxy_360p'): '/older-id-newer-date',
        }
