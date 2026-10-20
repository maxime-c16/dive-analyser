"""Read-only aggregate inventory of public playback packages (no IDs or URLs).

Run on backend stdin. Checks actual cache files, samples <=12 previews with
ffprobe, and reports a repair plan only; never queues jobs or changes readiness.
"""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import subprocess

from sqlalchemy import bindparam, text
from app.config import get_settings
from app.database import engine

root = Path(get_settings().media_cache_root).resolve()
counts = Counter()
owners = defaultdict(Counter)
sizes = defaultdict(list)
probe_results = Counter()
cutoff = datetime(2026, 10, 20, 20, 5, 18)
ASSET_QUERY = """SELECT p.id,p.video_uuid,coalesce(p.file_size_bytes,
        (SELECT min(b.byte_size) FROM media_revisions r JOIN media_blobs b ON b.sha256=r.blob_sha256
         JOIN media_blob_locations l ON l.blob_sha256=b.sha256
         WHERE r.video_uuid=p.video_uuid AND l.verified AND l.environment='prod')) file_size_bytes,
        (SELECT min(d.diver_id) FROM dives d WHERE d.photos_asset_id=p.id AND d.visibility='public') owner,
        EXISTS(SELECT 1 FROM media_revisions r JOIN media_blob_locations l ON l.blob_sha256=r.blob_sha256
               WHERE r.video_uuid=p.video_uuid AND l.verified AND l.environment='prod') remote_source,
        EXISTS(SELECT 1 FROM photos_asset_agent_identities i JOIN media_agents a ON a.id=i.agent_id
               WHERE i.photos_asset_id=p.id AND a.active AND a.leasing_enabled) photos_identity
        FROM photos_assets p WHERE EXISTS(SELECT 1 FROM dives d WHERE d.photos_asset_id=p.id
               AND d.visibility='public' AND d.video_uuid=p.video_uuid AND NOT d.is_lineup)
        AND p.id > :last_id ORDER BY p.id LIMIT :batch_size"""

ENTRY_QUERY = """SELECT photos_asset_id,rendition,storage_backend,storage_path,size_bytes,created_at
    FROM (SELECT photos_asset_id,rendition,storage_backend,storage_path,size_bytes,created_at,
          row_number() OVER(PARTITION BY photos_asset_id,rendition ORDER BY created_at DESC,id DESC) rank
          FROM media_cache_entries WHERE photos_asset_id IN :asset_ids AND status='ready'
          AND rendition IN ('proxy_720p','proxy_360p','poster')) latest
    WHERE rank=1 ORDER BY photos_asset_id,rendition"""
FAILURE_QUERY = """SELECT p.id,latest.last_error FROM photos_assets p
    JOIN LATERAL (SELECT j.last_error FROM media_jobs j WHERE j.photos_asset_id=p.id
        AND j.rendition IN ('proxy_720p','proxy_360p')
        ORDER BY j.created_at DESC,j.id DESC LIMIT 1) latest ON true
    WHERE p.id IN :asset_ids AND latest.last_error LIKE '%invalid_video_uuid%'"""

with engine.connect() as connection:
    connection.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
    connection.execute(text("SET LOCAL statement_timeout='10s'"))
    assets, entries, failures = [], [], {}
    last_id = 0
    batch_size = 250
    while True:
        batch = connection.execute(text(ASSET_QUERY),
                                   {'last_id': last_id, 'batch_size': batch_size}).mappings().all()
        if not batch:
            break
        asset_ids = [asset['id'] for asset in batch]
        assets.extend(batch)
        last_id = asset_ids[-1]
        # Both dependent queries are restricted to this canonical public batch.
        # Streaming also bounds driver-side buffers if an asset has many rows.
        for partition in connection.execution_options(stream_results=True).execute(
                text(ENTRY_QUERY).bindparams(bindparam('asset_ids', expanding=True)),
                {'asset_ids': asset_ids}).mappings().partitions(batch_size):
            entries.extend(partition)
        for partition in connection.execution_options(stream_results=True).execute(
                text(FAILURE_QUERY).bindparams(bindparam('asset_ids', expanding=True)),
                {'asset_ids': asset_ids}).partitions(batch_size):
            failures.update(dict(partition))
    connection.rollback()
by_asset = defaultdict(dict)
for row in entries:
    if row['storage_backend'] != 'local_fs':
        counts['unsupported_storage_rows'] += 1
        continue
    path = Path(row['storage_path']).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        counts['ready_rows_without_servable_file'] += 1
        continue
    if path.stat().st_size != row['size_bytes']:
        counts['ready_rows_size_mismatch'] += 1
        continue
    by_asset[row['photos_asset_id']][row['rendition']] = (path, row['created_at'])
    sizes[row['rendition']].append(row['size_bytes'])
for asset in assets:
    counts['public_assets'] += 1
    cache = by_asset[asset['id']]
    preview = cache.get('proxy_720p') or cache.get('proxy_360p')
    poster = cache.get('poster')
    missing = not preview or not poster
    counts['missing_preview'] += not bool(preview)
    counts['missing_poster'] += not bool(poster)
    counts['complete_local_package'] += bool(preview and poster)
    owners[asset['owner']]['total'] += 1
    owners[asset['owner']]['missing'] += missing
    if missing:
        counts['repair_assets'] += 1
        counts['repair_with_verified_prod_replica'] += bool(asset['remote_source'])
        counts['repair_with_active_photos_identity'] += bool(asset['photos_identity'])
        counts['repair_with_no_known_source'] += not (asset['remote_source'] or asset['photos_identity'])
        counts['repair_latest_invalid_identity_failure'] += asset['id'] in failures
        counts['repair_known_source_bytes'] += asset['file_size_bytes'] or 0
        counts['repair_unknown_source_size'] += not bool(asset['file_size_bytes'])
    if preview:
        counts['preview_predates_hdr_fix'] += preview[1] < cutoff
        if sum(probe_results.values()) < 12:
            try:
                result = subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=codec_name,pix_fmt,color_transfer,color_primaries,color_space','-of','json',str(preview[0])],capture_output=True,timeout=5,check=True)
                stream = json.loads(result.stdout)['streams'][0]
                if stream.get('color_transfer') in ('arib-std-b67','smpte2084'):
                    probe_results['hdr_tagged_preview'] += 1
                elif stream.get('codec_name') != 'h264' or stream.get('pix_fmt') != 'yuv420p':
                    probe_results['non_h264_8bit_preview'] += 1
                elif any(stream.get(k) != 'bt709' for k in ('color_transfer','color_primaries','color_space')):
                    probe_results['h264_8bit_incomplete_sdr_tags'] += 1
                else:
                    probe_results['h264_8bit_sdr_tagged'] += 1
            except (OSError,subprocess.SubprocessError,ValueError,KeyError,IndexError):
                probe_results['probe_failed'] += 1
median_preview = statistics.median(sizes['proxy_720p'] or sizes['proxy_360p'] or [0])
median_poster = statistics.median(sizes['poster'] or [0])
print(json.dumps({'captured_at':datetime.now(timezone.utc).isoformat(),'dry_run':True,
    'counts':dict(counts),'owner_coverage':{'owners':len(owners),'owners_with_missing_package':sum(v['missing']>0 for v in owners.values()),'owners_with_no_complete_package':sum(v['missing']==v['total'] for v in owners.values())},
    'sampled_preview_metadata':dict(probe_results),
    'estimated_output_bytes_at_catalog_median':counts['missing_preview']*median_preview+counts['missing_poster']*median_poster,
    'estimate_limit':'Catalog median estimate only; source recall peak, uploads and old-HDR repairs excluded. Missing tags do not prove incorrect pixels; old date does not prove HDR.'},indent=2))
