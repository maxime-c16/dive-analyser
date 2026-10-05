"""Bounded browser ingestion into the existing, access-controlled media cache."""
import hashlib
import json
import subprocess
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException

from app.config import get_settings
from app.models.media import MediaCacheEntry

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
        if not any(s.get('codec_type') == 'video' for s in metadata.get('streams', [])):
            raise HTTPException(422, 'The file is not a readable video')
        proxy = folder / 'video.mp4'
        result = subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-protocol_whitelist', 'file,pipe', '-f', demuxer, '-i', str(source), '-map', '0:v:0', '-map', '0:a:0?', '-vf', "scale=w='min(1280,iw)':h='min(720,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2", '-c:v', 'libx264', '-threads', '1', '-preset', 'veryfast', '-crf', '23', '-c:a', 'aac', '-movflags', '+faststart', str(proxy)], capture_output=True, timeout=600)
        if result.returncode:
            raise HTTPException(422, 'Unable to prepare this video')
        poster = folder / 'poster.jpg'
        result = subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-i', str(proxy), '-frames:v', '1', str(poster)], capture_output=True, timeout=30)
        if result.returncode:
            raise HTTPException(422, 'Unable to prepare video preview')
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


def cache_upload(db, asset, folder):
    for name, rendition, content_type in [('source', 'browser_source', 'application/octet-stream'), ('video.mp4', 'proxy_720p', 'video/mp4'), ('poster.jpg', 'poster', 'image/jpeg')]:
        path = folder / name
        db.add(MediaCacheEntry(photos_asset_id=asset.id, media_key=hashlib.sha256(f'{asset.video_uuid}:{rendition}'.encode()).hexdigest(), rendition=rendition, storage_path=str(path), content_type=content_type, size_bytes=path.stat().st_size, status='ready', pinned=True))


def persist_original(db, video_uuid, folder):
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
    source = folder / 'source'
    sha = sha256_file(source)
    key = f'{settings.media_backbone_object_prefix}/{sha[:2]}/{sha}'
    client = boto3.client('s3', region_name=settings.b2_upload_region, endpoint_url=settings.b2_upload_endpoint_url or f'https://s3.{settings.b2_upload_region}.backblazeb2.com', aws_access_key_id=settings.b2_upload_key_id, aws_secret_access_key=settings.b2_upload_key_secret, config=Config(connect_timeout=10, read_timeout=120, retries={'total_max_attempts': 2}))
    try:
        client.upload_file(str(source), bucket, key, ExtraArgs={'ContentType': 'application/octet-stream', 'Metadata': {'sha256': sha}})
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
    commit_verified_ingest(db, video_uuid=video_uuid, blob_sha256=sha, byte_size=size, object_key=key, storage_backend='b2', bucket=bucket, environment=environment, media_only=True, media_only_reason='Browser upload metadata stored on dive record', rendition_semantics='browser_original', source_provenance={'source': 'browser_upload'}, ingest_impl_version='browser_upload_v1', commit=False)
