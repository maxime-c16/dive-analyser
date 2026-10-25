"""Bounded browser ingestion into the existing, access-controlled media cache."""
import hashlib
import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException

from app.config import get_settings
from app.models.media import MediaCacheEntry
from app.services.media_keys import build_media_key

MAX_BYTES = 1024 * 1024 * 1024


def prepare_video(file):
    # Force a video demuxer; uploaded playlists must not fetch URLs/files.
    formats = {'.mp4': 'mov', '.mov': 'mov', '.m4v': 'mov', '.webm': 'matroska', '.mkv': 'matroska', '.avi': 'avi', '.mts': 'mpegts', '.m2ts': 'mpegts', '.mpeg': 'mpeg', '.mpg': 'mpeg'}
    demuxer = formats.get(Path(file.filename or '').suffix.lower())
    if not demuxer:
        raise HTTPException(422, 'Use MP4, MOV, M4V, WebM, MKV, AVI or MPEG video')
    root = Path(get_settings().media_cache_root).resolve() / 'browser-uploads'
    root.mkdir(parents=True, exist_ok=True)
    folder = root / uuid4().hex
    folder.mkdir()
    source = folder / 'source'
    try:
        size = 0
        with source.open('wb') as target:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise HTTPException(413, 'Video exceeds 1 GB')
                target.write(chunk)
        if not size:
            raise HTTPException(422, 'Empty video')
        probe = subprocess.run(['ffprobe', '-v', 'error', '-protocol_whitelist', 'file,pipe', '-f', demuxer, '-show_streams', '-show_format', '-of', 'json', str(source)], capture_output=True, timeout=30)
        metadata = json.loads(probe.stdout) if probe.returncode == 0 else {}
        video_stream = next((stream for stream in metadata.get('streams', []) if stream.get('codec_type') == 'video'), None)
        if video_stream is None:
            raise HTTPException(422, 'The file is not a readable video')
        try:
            duration = float(metadata.get('format', {}).get('duration', 0))
            width, height = int(video_stream.get('width', 0)), int(video_stream.get('height', 0))
        except (TypeError, ValueError):
            raise HTTPException(422, 'Unable to read video dimensions or duration') from None
        if duration <= 0 or duration > 180 or width <= 0 or height <= 0 or width * height > 4096 * 2160:
            raise HTTPException(422, 'Use a video up to 3 minutes and 4K resolution')
        filters = []
        color_args = []
        if video_stream.get('color_transfer') in ('smpte2084', 'arib-std-b67'):
            # Convert PQ/HLG HDR to SDR for web playback. The B2 original
            # retains all source bytes and color metadata.
            filters.extend(['zscale=t=linear:npl=100', 'format=gbrpf32le',
                            'zscale=p=bt709', 'tonemap=tonemap=hable:desat=0',
                            'zscale=t=bt709:m=bt709:r=tv'])
            color_args = ['-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709']
        # Preserve source resolution and frame rate. Archive bytes remain untouched.
        filters.extend(['scale=trunc(iw/2)*2:trunc(ih/2)*2', 'format=yuv420p'])
        proxy = folder / 'original.mp4'
        result = subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-protocol_whitelist', 'file,pipe', '-f', demuxer, '-i', str(source), '-map', '0:v:0', '-map', '0:a:0?', '-vf', ','.join(filters), '-fps_mode', 'passthrough', '-c:v', 'libx264', '-profile:v', 'main', '-pix_fmt', 'yuv420p', '-threads', '1', '-preset', 'veryfast', '-crf', '18', '-c:a', 'aac', '-movflags', '+faststart', '-fs', str(2 * MAX_BYTES), *color_args, str(proxy)], capture_output=True, timeout=600)
        if result.returncode:
            raise HTTPException(422, 'Unable to prepare this video')
        if proxy.stat().st_size >= 2 * MAX_BYTES:
            raise HTTPException(413, 'Prepared video exceeds the processing limit')
        poster = folder / 'poster.jpg'
        result = subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-i', str(proxy), '-frames:v', '1', str(poster)], capture_output=True, timeout=30)
        if result.returncode:
            raise HTTPException(422, 'Unable to prepare video preview')
        (folder / 'metadata.json').write_text(json.dumps(video_stream))
        return folder, size
    except (FileNotFoundError, subprocess.TimeoutExpired):
        cleanup_upload(folder)
        raise HTTPException(503, 'Video processing unavailable; please try again')
    except BaseException:
        cleanup_upload(folder)
        raise


def cleanup_upload(folder):
    for path in folder.iterdir():
        path.unlink(missing_ok=True)
    folder.rmdir()


def remote_playback_configured():
    settings = get_settings()
    return bool(settings.user_auth_enabled and settings.b2_playback_canary_enabled
        and settings.b2_upload_environment == 'prod' and settings.b2_playback_key_id
        and settings.b2_playback_key_secret and settings.b2_playback_region)


def cache_upload(db, asset, folder):
    posters = []
    for name, rendition, content_type in [('source', 'browser_source', 'application/octet-stream'), ('original.mp4', 'original', 'video/mp4'), ('poster.jpg', 'poster', 'image/jpeg')]:
        path = folder / name
        if rendition == 'poster':
            # Posters have no durable replica anywhere (B2 holds originals
            # only): the local file is the sole copy, unconditionally.
            pinned = True
            expires_at = None
        elif rendition == 'browser_source':
            # Raw upload bytes are roundtrip-verified into B2 before the dive
            # is published (persist_original): the local copy stays a
            # disposable 1-day staging file and must remain evictable.
            pinned = False
            expires_at = datetime.utcnow() + timedelta(days=1)
        else:
            # Playback MP4 bytes are roundtrip-verified into B2 as well, but
            # the app can only serve them remotely when the playback
            # credential is configured; otherwise local is the sole readable
            # copy.
            pinned = not remote_playback_configured()
            expires_at = datetime.utcnow() + timedelta(days=30)
        entry = MediaCacheEntry(photos_asset_id=asset.id, media_key=build_media_key(asset.video_uuid, rendition), rendition=rendition, storage_path=str(path), content_type=content_type, size_bytes=path.stat().st_size, status='ready', pinned=pinned, expires_at=expires_at)
        db.add(entry)
        if rendition == 'poster':
            posters.append(entry)
    return posters


def persist_original(db, video_uuid, folder, *, register=True, source_name='source'):
    """Upload and roundtrip-verify original bytes before publishing a clip."""
    import boto3
    from botocore.config import Config
    from app.services.media_backbone import commit_verified_ingest, environment_bucket
    from app.services.media_cache import sha256_file
    settings = get_settings()
    if not settings.b2_upload_key_id or not settings.b2_upload_key_secret or not settings.b2_upload_region:
        raise HTTPException(503, 'Video storage is not configured yet')
    environment = settings.b2_upload_environment
    if environment not in ("dev", "prod"):
        raise HTTPException(503, "Video storage environment is not configured correctly")
    bucket = environment_bucket(environment)
    source = folder / source_name
    content_type = 'video/mp4' if source_name == 'original.mp4' else 'application/octet-stream'
    sha = sha256_file(source)
    key = f'{settings.media_backbone_object_prefix}/{sha[:2]}/{sha}'
    client = boto3.client('s3', region_name=settings.b2_upload_region, endpoint_url=settings.b2_upload_endpoint_url or f'https://s3.{settings.b2_upload_region}.backblazeb2.com', aws_access_key_id=settings.b2_upload_key_id, aws_secret_access_key=settings.b2_upload_key_secret, config=Config(connect_timeout=10, read_timeout=120, retries={'total_max_attempts': 2}))
    try:
        client.upload_file(str(source), bucket, key, ExtraArgs={'ContentType': content_type, 'Metadata': {'sha256': sha}})
        response = client.get_object(Bucket=bucket, Key=key)
        digest = hashlib.sha256()
        size = 0
        stream = response['Body']
        try:
            for chunk in stream.iter_chunks(chunk_size=1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
        finally:
            stream.close()
        if digest.hexdigest() != sha or size != source.stat().st_size:
            raise HTTPException(502, 'Video storage verification failed; please retry')
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, 'Video storage unavailable; please retry') from None
    manifest = dict(video_uuid=video_uuid, blob_sha256=sha, byte_size=size, object_key=key, storage_backend='b2', bucket=bucket, environment=environment, media_only=True, media_only_reason='Browser upload metadata stored on dive record', rendition_semantics='browser_playback' if source_name == 'original.mp4' else 'browser_original', source_provenance={'source': 'browser_upload'}, ingest_impl_version='browser_upload_v2')
    metadata_path = folder / 'metadata.json'
    metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
    manifest.update(width=metadata.get('width'), height=metadata.get('height'), codec='h264' if source_name == 'original.mp4' else metadata.get('codec_name'))
    if register:
        commit_verified_ingest(db, **manifest, commit=False)
    return manifest
