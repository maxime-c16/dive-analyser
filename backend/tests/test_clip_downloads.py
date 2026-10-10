"""Download attachments preserve the existing member media boundary."""
from unittest.mock import Mock
from app.config import get_settings
from app.services import b2_presign
from tests.test_member_dive_visibility import workspace


def test_download_auth_attachment_range_and_private_isolation(workspace, monkeypatch):
    _, login, dives, _, _ = workspace
    monkeypatch.setattr(get_settings(), 'media_xaccel_enabled', False)
    response = login('alice').get(f"/api/v1/dives/{dives['alice-private']}/download")
    assert response.status_code == 200
    assert response.content == b'cached test video'
    assert response.headers['content-disposition'].startswith('attachment; filename="dive-')
    assert response.headers['cache-control'] == 'private, no-store'
    assert login('bob').get(f"/api/v1/dives/{dives['alice-private']}/download").status_code == 404
    response = login('alice').get(f"/api/v1/dives/{dives['alice-private']}/download", headers={'Range': 'bytes=0-5'})
    assert response.status_code == 206 and response.content == b'cached'
    client = login('alice')
    client.cookies.clear()
    assert client.get(f"/api/v1/dives/{dives['alice-private']}/download").status_code == 401


def test_attachment_is_signed_at_provider_without_affecting_playback(monkeypatch):
    client = Mock()
    client.generate_presigned_url.return_value = 'https://provider.test/signed'
    monkeypatch.setattr(b2_presign, '_b2_client', lambda: client)
    b2_presign.presign_get('bucket', 'video.mov', download_filename='dive-2026-10-10-1.mov')
    assert client.generate_presigned_url.call_args.kwargs['Params']['ResponseContentDisposition'] == 'attachment; filename="dive-2026-10-10-1.mov"'
    b2_presign.presign_get('bucket', 'video.mov')
    assert 'ResponseContentDisposition' not in client.generate_presigned_url.call_args.kwargs['Params']


def test_b2_download_redirects_and_share_stream_is_same_origin(workspace, monkeypatch):
    from types import SimpleNamespace
    from app.api.v1 import clip_downloads
    from fastapi.responses import Response
    _, login, dives, _, _ = workspace
    monkeypatch.setattr(get_settings(), 'b2_playback_canary_enabled', True)
    monkeypatch.setattr(clip_downloads, '_resolve_verified_prod_location', lambda *args: (SimpleNamespace(id=1, bucket='prod', object_key='original.mov'), None))
    monkeypatch.setattr(b2_presign, 'head_object', lambda **kwargs: True)
    signer = Mock(return_value=SimpleNamespace(url='https://provider.test/signed'))
    monkeypatch.setattr(b2_presign, 'presign_get', signer)
    stream_calls = []
    async def share_stream(bucket, key, filename):
        stream_calls.append((bucket, key, filename))
        return Response(b'video bytes', media_type='video/quicktime')
    monkeypatch.setattr(clip_downloads, '_share_file', share_stream)
    path = f"/api/v1/dives/{dives['alice-private']}/download"
    response = login('alice').get(path, follow_redirects=False)
    assert response.status_code == 302 and response.headers['location'] == 'https://provider.test/signed'
    assert signer.call_args.kwargs['download_filename'].endswith('.mov')
    assert not stream_calls
    response = login('alice').get(path + '?for_share=true')
    assert response.status_code == 200 and response.content == b'video bytes'
    assert stream_calls[0][:2] == ('prod', 'original.mov')
    assert signer.call_count == 1
    assert login('bob').get(path + '?for_share=true').status_code == 404
    assert len(stream_calls) == 1


def test_ambiguous_storage_never_downloads_or_falls_back(workspace, monkeypatch):
    from app.api.v1 import clip_downloads
    _, login, dives, _, _ = workspace
    monkeypatch.setattr(get_settings(), 'b2_playback_canary_enabled', True)
    monkeypatch.setattr(clip_downloads, '_resolve_verified_prod_location', lambda *args: (None, clip_downloads.DENY_STORAGE_AMBIGUOUS))
    signer = Mock()
    monkeypatch.setattr(b2_presign, 'presign_get', signer)
    response = login('alice').get(f"/api/v1/dives/{dives['alice-private']}/download")
    assert response.status_code == 404
    signer.assert_not_called()


async def test_share_proxy_streams_and_closes_connections(monkeypatch):
    from io import BytesIO
    from app.api.v1 import clip_downloads
    body = BytesIO(b'video')
    monkeypatch.setattr(b2_presign, 'open_get_stream', lambda bucket, key: (body, 5))
    response = await clip_downloads._share_file('prod', 'original.mov', 'dive-1.mov')
    assert response.headers['content-type'] == 'video/quicktime'
    assert response.headers['content-length'] == '5'
    assert b''.join([part async for part in response.body_iterator]) == b'video'
    assert body.closed


async def test_share_proxy_rejects_large_files_without_reading(monkeypatch):
    from io import BytesIO
    import pytest
    from fastapi import HTTPException
    from app.api.v1 import clip_downloads
    body = BytesIO()
    monkeypatch.setattr(b2_presign, 'open_get_stream', lambda bucket, key: (body, clip_downloads.MAX_SHARE_BYTES + 1))
    with pytest.raises(HTTPException) as error:
        await clip_downloads._share_file('prod', 'original.mp4', 'dive-1.mp4')
    assert error.value.status_code == 413
    assert body.closed


def test_browser_upload_uses_prepared_mp4_instead_of_extensionless_original(workspace, monkeypatch):
    from types import SimpleNamespace
    from app.models.media_backbone import MediaRevision
    from app.models.dive import Dive
    from app.api.v1 import clip_downloads
    db, login, dives, _, _ = workspace
    dive = db.get(Dive, dives['alice-private'])
    revision = db.query(MediaRevision).filter_by(video_uuid=dive.video_uuid).one()
    revision.rendition_semantics = 'browser_original'
    db.commit()
    monkeypatch.setattr(get_settings(), 'media_xaccel_enabled', False)
    monkeypatch.setattr(get_settings(), 'b2_playback_canary_enabled', True)
    storage = Mock(return_value=(SimpleNamespace(id=1, bucket='prod', object_key='blobs/sha256/abcd'), None))
    signer = Mock()
    monkeypatch.setattr(clip_downloads, '_resolve_verified_prod_location', storage)
    monkeypatch.setattr(b2_presign, 'presign_get', signer)
    response = login('alice').get(f'/api/v1/dives/{dive.id}/download?for_share=true')
    assert response.status_code == 200 and response.content == b'cached test video'
    assert response.headers['content-type'] == 'video/mp4'
    assert response.headers['content-disposition'].endswith('.mp4"')
    signer.assert_not_called()


async def test_share_proxy_closes_body_if_cancelled_while_opening(monkeypatch):
    import asyncio
    import threading
    from io import BytesIO
    import pytest
    from app.api.v1 import clip_downloads
    body = BytesIO(b'video')
    started, release = threading.Event(), threading.Event()
    def opening(bucket, key):
        started.set()
        release.wait(timeout=5)
        return body, 5
    monkeypatch.setattr(b2_presign, 'open_get_stream', opening)
    operation = asyncio.create_task(clip_downloads._share_file('prod', 'original.mov', 'dive-1.mov'))
    await asyncio.to_thread(started.wait, 5)
    operation.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await operation
    assert body.closed



def test_closed_b2_flag_uses_authorized_local_file_without_cloud_access(workspace, monkeypatch):
    from app.api.v1 import clip_downloads
    _, login, dives, _, _ = workspace
    monkeypatch.setattr(get_settings(), 'b2_playback_canary_enabled', False)
    monkeypatch.setattr(get_settings(), 'media_xaccel_enabled', False)
    cloud = Mock()
    signer = Mock()
    opener = Mock()
    monkeypatch.setattr(clip_downloads, '_resolve_verified_prod_location', cloud)
    monkeypatch.setattr(b2_presign, 'presign_get', signer)
    monkeypatch.setattr(b2_presign, 'open_get_stream', opener)
    path = f"/api/v1/dives/{dives['alice-private']}/download"
    for suffix in ('', '?for_share=true'):
        response = login('alice').get(path + suffix)
        assert response.status_code == 200 and response.content == b'cached test video'
    assert login('bob').get(path).status_code == 404
    cloud.assert_not_called()
    signer.assert_not_called()
    opener.assert_not_called()
