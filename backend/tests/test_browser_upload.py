from tests.upload_helpers import publish_upload
import pytest

from tests.test_member_dive_visibility import workspace


@pytest.mark.parametrize(('code', 'direction', 'height'), [
    ('103B', 1, '3m'), ('5231D', 2, '10m'), ('603B', None, '10m'),
])
def test_browser_upload_ownership_privacy_and_retry(workspace, monkeypatch, tmp_path, code, direction, height):
    from app.services import browser_upload
    db, login, _, users, _ = workspace
    from app.services.dive_access import owned_diver_ids
    owner = owned_diver_ids(db, users['bob'].id)[0]
    folder = tmp_path / 'prepared'
    folder.mkdir()
    for name in ('source', 'original.mp4', 'poster.jpg'):
        (folder / name).write_bytes(b'full' if name == 'original.mp4' else b'test')
    import boto3
    from app.config import get_settings
    settings = get_settings()
    for key, value in [('b2_upload_key_id', 'test'), ('b2_upload_key_secret', 'test'), ('b2_upload_region', 'test')]:
        monkeypatch.setattr(settings, key, value)
    class Stream:
        def iter_chunks(self, chunk_size):
            yield b'test'
        def close(self):
            pass
    class Client:
        def upload_file(self, path, *args, **kwargs):
            from pathlib import Path
            self.content = Path(path).read_bytes()
        def get_object(self, **kwargs):
            import io
            class Body(io.BytesIO):
                def iter_chunks(self, chunk_size):
                    yield self.read()
            return {'Body': Body(self.content)}
    monkeypatch.setattr(boto3, 'client', lambda *a, **kw: Client())
    calls = []
    def prepare(file):
        calls.append(file.filename)
        return folder, 4
    monkeypatch.setattr(browser_upload, 'prepare_video', prepare)
    fields = dict(dive_code=code, height=height, performance='G', dive_datetime='2026-10-05T12:00:00', diver_id=str(owner), upload_id='12345678-1234-1234-1234-123456789012')
    client = login('bob')
    response = publish_upload(db, client, data=fields, files={'file': ('clip.mov', b'video', 'video/quicktime')})
    assert response.status_code == 200, response.text
    record = response.json()
    assert record['diver_id'] == owner
    assert record['person_name'] == 'bob'
    assert record['visibility'] == 'private'
    assert record['direction'] == direction
    assert record['dive_code'] == code
    assert record['platform_type'] == ('platform' if height == '10m' else 'springboard')
    from app.models.media_backbone import MediaRevision, MediaBlobLocation
    assert {r.rendition_semantics for r in db.query(MediaRevision).filter_by(video_uuid=record['video_uuid']).all()} == {'browser_original', 'browser_playback'}
    assert all(row.verified for row in db.query(MediaBlobLocation).all())
    retry = publish_upload(db, client, data=fields, files={'file': ('clip.mov', b'video')})
    assert retry.status_code == 200 and retry.json()['id'] == record['id']
    assert len(calls) == 1
    status = client.get(f"/api/v1/media/{record['video_uuid']}/status")
    assert status.status_code == 200, status.text
    assert status.json()['status'] == 'ready'
    assert status.json()['poster_url']
    from app.models.media import MediaJob
    jobs_before = db.query(MediaJob).count()
    for rendition in ('poster', 'original'):
        request = client.post(f"/api/v1/media/{record['video_uuid']}/request", json={'rendition': rendition})
        assert request.status_code == 200, request.text
        assert request.json()['cache_hit'] is True
        assert request.json()['created_job'] is False
    assert db.query(MediaJob).count() == jobs_before
    assert login('alice').get(f"/api/v1/dives/{record['id']}").status_code == 404
    fields['diver_id'] = str(owned_diver_ids(db, users['alice'].id)[0])
    assert publish_upload(db, login('bob'), data=fields, files={'file': ('clip.mp4', b'video')}).status_code == 403
    assert len(calls) == 1


def test_browser_upload_validates_before_processing(workspace):
    db, login, _, _, _ = workspace
    response = publish_upload(db, login('viewer'), data=dict(dive_code='bad', height='3m', performance='G', dive_datetime='2026-10-05T12:00:00', diver_id='1', upload_id='12345678-1234-1234-1234-123456789012'), files={'file': ('clip.mp4', b'video')})
    assert response.status_code == 422


def test_b2_failure_does_not_publish_clip(workspace, monkeypatch, tmp_path):
    from app.services import browser_upload
    from fastapi import HTTPException
    from app.models.dive import Dive
    from app.services.dive_access import owned_diver_ids
    db, login, _, users, _ = workspace
    folder = tmp_path / 'failed-upload'
    folder.mkdir()
    for name in ('source', 'original.mp4', 'poster.jpg'):
        (folder / name).write_bytes(b'video')
    monkeypatch.setattr(browser_upload, 'prepare_video', lambda file: (folder, 5))
    def fail(*args, **kwargs):
        raise HTTPException(503, 'Video storage unavailable; please retry')
    monkeypatch.setattr(browser_upload, 'persist_original', fail)
    before = db.query(Dive).count()
    response = publish_upload(db, login('bob'), data=dict(dive_code='103B', height='3m', performance='G', dive_datetime='2026-10-05T12:00:00', diver_id=str(owned_diver_ids(db, users['bob'].id)[0]), upload_id='12345678-1234-1234-1234-123456789012'), files={'file': ('clip.mp4', b'video')})
    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert db.query(Dive).count() == before
    assert not folder.exists()


def test_b2_original_is_roundtrip_verified_before_registration(monkeypatch, tmp_path):
    import io
    import boto3
    from app.config import get_settings
    from app.services import browser_upload, media_backbone
    import pytest
    from fastapi import HTTPException
    settings = get_settings()
    for key, value in [('b2_upload_key_id', 'test'), ('b2_upload_key_secret', 'test'), ('b2_upload_region', 'test')]:
        monkeypatch.setattr(settings, key, value)
    (tmp_path / 'source').write_bytes(b'original video bytes')
    calls = []
    class Stream(io.BytesIO):
        def iter_chunks(self, chunk_size):
            yield self.read()
    class Client:
        def upload_file(self, *args, **kwargs):
            calls.append('upload')
        def get_object(self, **kwargs):
            return {'Body': Stream(b'original video bytes')}
    monkeypatch.setattr(boto3, 'client', lambda *a, **kw: Client())
    monkeypatch.setattr(media_backbone, 'commit_verified_ingest', lambda *a, **kw: calls.append(kw))
    browser_upload.persist_original(None, 'video-id', tmp_path)
    assert calls[0] == 'upload'
    assert calls[1]['rendition_semantics'] == 'browser_original'
    assert calls[1]['commit'] is False
    monkeypatch.setattr(Client, 'get_object', lambda *a, **kw: {'Body': Stream(b'corrupt')})
    with pytest.raises(HTTPException) as error:
        browser_upload.persist_original(None, 'video-id', tmp_path)
    assert error.value.status_code == 502
    assert len(calls) == 3  # second upload, no second registration


def test_upload_rejects_empty_and_non_video_inputs_before_processing(monkeypatch, tmp_path):
    import io
    import pytest
    from fastapi import HTTPException, UploadFile
    from app.config import get_settings
    from app.services.browser_upload import prepare_video
    monkeypatch.setattr(get_settings(), 'media_cache_root', str(tmp_path))
    for filename, content in [('empty.mp4', b''), ('playlist.m3u8', b'#EXTM3U')]:
        with pytest.raises(HTTPException) as error:
            prepare_video(UploadFile(file=io.BytesIO(content), filename=filename))
        assert error.value.status_code == 422
    assert not list((tmp_path / 'browser-uploads').iterdir())


@pytest.mark.parametrize('code', ['5501D', '6031B'])
def test_invalid_structural_code_is_rejected_before_video_processing(workspace, monkeypatch, code):
    from app.services import browser_upload
    from app.services.dive_access import owned_diver_ids
    db, login, _, users, _ = workspace
    def unexpected_prepare(file):
        raise AssertionError('Invalid codes must not process video')
    monkeypatch.setattr(browser_upload, 'prepare_video', unexpected_prepare)
    response = publish_upload(db, login('bob'), data=dict(dive_code=code, height='3m', performance='G', dive_datetime='2026-10-05T12:00:00', diver_id=str(owned_diver_ids(db, users['bob'].id)[0]), upload_id='12345678-1234-1234-1234-123456789012'), files={'file': ('clip.mp4', b'video')})
    assert response.status_code == 422
    if code == '5501D':
        assert 'direction' in response.json()['detail']


@pytest.mark.parametrize('transfer', [None, 'smpte2084', 'arib-std-b67'])
def test_ten_bit_video_becomes_browser_compatible_sdr(tmp_path, monkeypatch, transfer):
    import json
    import shutil
    import subprocess
    from fastapi import UploadFile
    from app.config import get_settings
    from app.services.browser_upload import prepare_video, cleanup_upload
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        pytest.skip('Real video regression requires ffmpeg and ffprobe')
    source = tmp_path / 'ten-bit.mp4'
    colors = ['-color_primaries', 'bt2020', '-color_trc', transfer, '-colorspace', 'bt2020nc'] if transfer else []
    source_filter = 'format=yuv420p10le'
    if transfer:
        source_filter += f',setparams=color_primaries=bt2020:color_trc={transfer}:colorspace=bt2020nc'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=64x64:d=0.2', '-vf', source_filter, '-c:v', 'libx265', '-threads', '1', '-x265-params', 'pools=1:frame-threads=1:log-level=error', '-tag:v', 'hvc1', *colors, str(source)], check=True, capture_output=True, timeout=30)
    input_stream = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(source)]))['streams'][0]
    assert input_stream['pix_fmt'] == 'yuv420p10le'
    if transfer:
        assert input_stream['color_transfer'] == transfer
    monkeypatch.setattr(get_settings(), 'media_cache_root', str(tmp_path / 'cache'))
    with source.open('rb') as file:
        folder, _ = prepare_video(UploadFile(file=file, filename=source.name))
    try:
        stream = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(folder / 'original.mp4')]))['streams'][0]
        assert stream['codec_name'] == 'h264'
        assert stream['profile'] == 'Main'
        assert stream['pix_fmt'] == 'yuv420p'
        if transfer:
            assert stream['color_transfer'] == 'bt709'
            assert stream['color_primaries'] == 'bt709'
            assert stream['color_space'] == 'bt709'
        assert (folder / 'poster.jpg').stat().st_size > 0
        assert (folder / 'source').read_bytes() == source.read_bytes()
    finally:
        cleanup_upload(folder)


def test_full_resolution_and_frame_rate_are_preserved(tmp_path, monkeypatch):
    import json
    import shutil
    import subprocess
    from fastapi import UploadFile
    from app.config import get_settings
    from app.services.browser_upload import prepare_video, cleanup_upload
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        pytest.skip('Real video regression requires ffmpeg and ffprobe')
    source = tmp_path / 'full.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=1920x1080:r=60:d=0.15', '-c:v', 'libx264', '-threads', '1', str(source)], check=True, timeout=30)
    monkeypatch.setattr(get_settings(), 'media_cache_root', str(tmp_path / 'cache'))
    with source.open('rb') as file:
        folder, _ = prepare_video(UploadFile(file=file, filename=source.name))
    try:
        stream = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(folder / 'original.mp4')]))['streams'][0]
        assert (stream['width'], stream['height'], stream['r_frame_rate']) == (1920, 1080, '60/1')
        assert (folder / 'source').read_bytes() == source.read_bytes()
    finally:
        cleanup_upload(folder)


def test_cleanup_preserves_browser_playback_when_remote_path_is_disabled(workspace, monkeypatch, tmp_path):
    from datetime import datetime, timedelta
    from app.config import get_settings
    from app.models.media import MediaCacheEntry
    from app.models.photos_asset import PhotosAsset
    from app.services.media_cache import cleanup_cache
    db, _, _, _, _ = workspace
    monkeypatch.setattr(get_settings(), 'b2_playback_canary_enabled', False)
    folder = tmp_path / 'browser-uploads' / 'retained'
    folder.mkdir(parents=True)
    video = folder / 'original.mp4'
    video.write_bytes(b'only accessible playback')
    asset = db.query(PhotosAsset).first()
    entry = MediaCacheEntry(photos_asset_id=asset.id, media_key='retention-safety', rendition='original', storage_path=str(video), size_bytes=video.stat().st_size, content_type='video/mp4', status='ready', pinned=False, expires_at=datetime.utcnow() - timedelta(days=1))
    db.add(entry); db.commit()
    cleanup_cache(db, max_bytes=1)
    db.commit()
    assert video.exists()
    assert entry.pinned is True
