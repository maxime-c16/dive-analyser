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
    monkeypatch.setattr(clip_downloads, '_resolve_verified_prod_location', lambda *args: (SimpleNamespace(id=1, bucket='prod', object_key='original.mov'), None))
    monkeypatch.setattr(b2_presign, 'head_object', lambda **kwargs: True)
    signer = Mock(return_value=SimpleNamespace(url='https://provider.test/signed'))
    monkeypatch.setattr(b2_presign, 'presign_get', signer)
    stream_calls = []
    async def share_stream(url, filename):
        stream_calls.append((url, filename))
        return Response(b'video bytes', media_type='video/quicktime')
    monkeypatch.setattr(clip_downloads, '_share_file', share_stream)
    path = f"/api/v1/dives/{dives['alice-private']}/download"
    response = login('alice').get(path, follow_redirects=False)
    assert response.status_code == 302 and response.headers['location'] == 'https://provider.test/signed'
    assert signer.call_args.kwargs['download_filename'].endswith('.mov')
    assert not stream_calls
    response = login('alice').get(path + '?for_share=true')
    assert response.status_code == 200 and response.content == b'video bytes'
    assert stream_calls[0][0] == 'https://provider.test/signed'
    assert login('bob').get(path + '?for_share=true').status_code == 404
    assert len(stream_calls) == 1


def test_ambiguous_storage_never_downloads_or_falls_back(workspace, monkeypatch):
    from app.api.v1 import clip_downloads
    _, login, dives, _, _ = workspace
    monkeypatch.setattr(clip_downloads, '_resolve_verified_prod_location', lambda *args: (None, clip_downloads.DENY_STORAGE_AMBIGUOUS))
    signer = Mock()
    monkeypatch.setattr(b2_presign, 'presign_get', signer)
    response = login('alice').get(f"/api/v1/dives/{dives['alice-private']}/download")
    assert response.status_code == 404
    signer.assert_not_called()


async def test_share_proxy_streams_and_closes_connections(monkeypatch):
    import httpx
    from app.api.v1 import clip_downloads
    real_client = httpx.AsyncClient
    clients = []
    def make_client(**kwargs):
        transport = httpx.MockTransport(lambda request: httpx.Response(200, headers={'content-length': '5'}, stream=httpx.ByteStream(b'video')))
        client = real_client(transport=transport, **kwargs)
        clients.append(client)
        return client
    monkeypatch.setattr(clip_downloads.httpx, 'AsyncClient', make_client)
    response = await clip_downloads._share_file('https://provider.test/signed', 'dive-1.mov')
    assert response.headers['content-type'] == 'video/quicktime'
    assert response.headers['content-length'] == '5'
    assert b''.join([part async for part in response.body_iterator]) == b'video'
    assert clients[0].is_closed


async def test_share_proxy_rejects_large_files_without_reading(monkeypatch):
    import httpx
    import pytest
    from fastapi import HTTPException
    from app.api.v1 import clip_downloads
    real_client = httpx.AsyncClient
    clients = []
    def make_client(**kwargs):
        transport = httpx.MockTransport(lambda request: httpx.Response(200, headers={'content-length': str(clip_downloads.MAX_SHARE_BYTES + 1)}))
        client = real_client(transport=transport, **kwargs)
        clients.append(client)
        return client
    monkeypatch.setattr(clip_downloads.httpx, 'AsyncClient', make_client)
    with pytest.raises(HTTPException) as error:
        await clip_downloads._share_file('https://provider.test/signed', 'dive-1.mp4')
    assert error.value.status_code == 413
    assert clients[0].is_closed


def test_browser_upload_uses_prepared_mp4_instead_of_extensionless_original(workspace, monkeypatch):
    from app.models.media_backbone import MediaRevision
    from app.models.dive import Dive
    from app.api.v1 import clip_downloads
    db, login, dives, _, _ = workspace
    dive = db.get(Dive, dives['alice-private'])
    revision = db.query(MediaRevision).filter_by(video_uuid=dive.video_uuid).one()
    revision.rendition_semantics = 'browser_original'
    db.commit()
    monkeypatch.setattr(get_settings(), 'media_xaccel_enabled', False)
    storage = Mock(return_value=(None, 'storage_not_found'))
    signer = Mock()
    monkeypatch.setattr(clip_downloads, '_resolve_verified_prod_location', storage)
    monkeypatch.setattr(b2_presign, 'presign_get', signer)
    response = login('alice').get(f'/api/v1/dives/{dive.id}/download?for_share=true')
    assert response.status_code == 200 and response.content == b'cached test video'
    assert response.headers['content-type'] == 'video/mp4'
    assert response.headers['content-disposition'].endswith('.mp4"')
    signer.assert_not_called()
