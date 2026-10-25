"""Discovery/profile writes and grids through real member sessions."""
from datetime import datetime
from io import BytesIO

from PIL import Image

from tests.test_member_dive_visibility import workspace
from app.models.dive import Dive
from app.models.diver import Diver
from app.models.user_auth import AppUser, UserDiverAccess


def test_search_linked_diver_name_respects_binding_visibility(workspace):
    db, login, dives, users, _ = workspace
    binding = db.query(UserDiverAccess).filter_by(user_id=users['alice'].id).one()
    db.get(Diver, binding.diver_id).display_name = 'Fanny'
    db.commit()
    assert login('viewer').get('/api/v1/users?q=fanny').json()['items'][0]['user_id'] == users['alice'].id
    db.get(Dive, dives['alice-public']).visibility = 'private'
    db.commit()
    assert login('viewer').get('/api/v1/users?q=fanny').json()['items'] == []
    assert login('alice').get('/api/v1/users?q=fanny').json()['items'][0]['user_id'] == users['alice'].id


def test_search_names_handles_literal_wildcards_and_inactive_accounts(workspace):
    db, login, _, users, _ = workspace
    client = login('alice')
    response = client.put('/api/v1/users/me/profile', json={'display_name': 'Fanny', 'handle': 'FANNY_DIVE', 'bio': 'Training together'})
    assert response.status_code == 200, response.text
    assert response.json()['handle'] == 'fanny_dive'
    for q in ('fAnNy', '@FANNY_DIVE'):
        rows = client.get('/api/v1/users', params={'q': q}).json()['items']
        assert [row['user_id'] for row in rows] == [users['alice'].id]
        assert 'email' not in rows[0] and 'avatar' not in rows[0]
    assert client.get('/api/v1/users?q=%25').json()['items'] == []
    assert client.get('/api/v1/users?q=_').json()['items'][0]['handle'] == 'fanny_dive'
    db.get(AppUser, users['bob'].id).is_active = False
    db.commit()
    assert client.get('/api/v1/users?q=bob').json()['items'] == []
    assert client.get(f"/api/v1/users/{users['bob'].id}/dives").status_code == 404


def test_discovery_pagination_is_bounded_and_nonoverlapping(workspace):
    _, login, _, _, _ = workspace
    client = login('viewer')
    first = client.get('/api/v1/users?limit=2').json()
    second = client.get('/api/v1/users', params={'limit': 2, 'after': first['next_after']}).json()
    ids = [row['user_id'] for row in first['items'] + second['items']]
    assert len(ids) == len(set(ids)) == 3
    assert second['next_after'] is None
    assert client.get('/api/v1/users?limit=1000').status_code == 422


def test_profile_edit_only_self_unique_handle_and_validation(workspace):
    _, login, _, users, _ = workspace
    body = {'display_name': ' Alice ', 'handle': 'alice_dive', 'bio': ' My bio '}
    assert login('alice').put('/api/v1/users/me/profile', json=body).status_code == 200
    profile = login('bob').get(f"/api/v1/users/{users['alice'].id}").json()
    assert profile['display_name'] == 'Alice' and profile['bio'] == 'My bio'
    assert login('bob').put('/api/v1/users/me/profile', json=body).status_code == 409
    assert login('bob').get(f"/api/v1/users/{users['bob'].id}").json()['display_name'] == 'bob'
    for bad in ({'handle': 'a b'}, {'display_name': '   '}, {'bio': 'x' * 501}, {'is_admin': True}, {'user_id': users['bob'].id}):
        assert login('alice').put('/api/v1/users/me/profile', json={**body, **bad}).status_code == 422
    assert login('alice').put('/api/v1/users/me/profile', json=body, headers={'Origin': 'https://evil.test'}).status_code == 403
    assert login('alice').put('/api/v1/users/me/profile', json={**body, 'handle': None}).status_code == 200


def test_avatar_decode_resize_access_and_remove(workspace):
    _, login, _, users, _ = workspace
    image = Image.new('RGB', (640, 480), 'blue')
    output = BytesIO()
    image.save(output, 'PNG')
    client = login('alice')
    upload = client.put('/api/v1/users/me/avatar', content=output.getvalue(), headers={'Content-Type': 'image/png'})
    assert upload.status_code == 200, upload.text
    avatar_url = upload.json()['avatar_url']
    assert avatar_url.startswith(f"/api/v1/users/{users['alice'].id}/avatar?v=")
    photo = login('bob').get(avatar_url)
    assert photo.status_code == 200 and photo.headers['content-type'] == 'image/jpeg'
    assert photo.headers['cache-control'] == 'private, no-store'
    with Image.open(BytesIO(photo.content)) as decoded:
        assert decoded.size == (256, 256) and not decoded.getexif()
    assert login('alice').delete('/api/v1/users/me/avatar').status_code == 204
    assert login('bob').get(avatar_url).status_code == 404
    assert login('bob').get(f"/api/v1/users/{users['alice'].id}").json()['avatar_url'] is None


def test_avatar_rejects_arbitrary_bytes_and_oversized_uploads(workspace):
    _, login, _, _, _ = workspace
    client = login('alice')
    for raw, status in ((b'<svg onload="alert(1)"></svg>', 422), (b'x' * (2 * 1024 * 1024 + 1), 413)):
        assert client.put('/api/v1/users/me/avatar', content=raw, headers={'Content-Type': 'image/jpeg'}).status_code == status


def test_grid_ownership_privacy_and_latest_first_cursor(workspace):
    db, login, dives, users, _ = workspace
    public, private = dives['alice-public'], dives['alice-private']
    # Same timestamp exercises the stable ID tie-breaker across pages.
    for dive_id in (public, private):
        db.get(Dive, dive_id).dive_datetime = datetime(2026, 10, 8, 12)
    db.commit()
    own = login('alice').get(f"/api/v1/users/{users['alice'].id}/dives?limit=1").json()
    assert [row['id'] for row in own['items']] == [private]
    next_page = login('alice').get(f"/api/v1/users/{users['alice'].id}/dives", params={'before': own['next_before'], 'limit': 1}).json()
    assert [row['id'] for row in next_page['items']] == [public] and next_page['next_before'] is None
    for viewer in ('bob', 'viewer'):
        rows = login(viewer).get(f"/api/v1/users/{users['alice'].id}/dives").json()['items']
        assert [row['id'] for row in rows] == [public]
        assert 'notes' not in rows[0] and 'video_uuid' not in rows[0]
    assert login('alice').get(f"/api/v1/users/{users['viewer'].id}/dives").json()['items'] == []
    assert login('alice').get(f"/api/v1/users/{users['alice'].id}/dives?before=bad").status_code == 422


def test_member_endpoints_require_browser_session(workspace):
    _, login, _, users, _ = workspace
    client = login('alice')
    client.cookies.clear()
    for path in ('/api/v1/users', f"/api/v1/users/{users['alice'].id}/dives", f"/api/v1/users/{users['alice'].id}/avatar"):
        assert client.get(path).status_code == 401
    assert client.put('/api/v1/users/me/profile', json={'display_name': 'No'}).status_code == 401


def test_profile_grid_never_serves_originals_without_a_local_preview(workspace, monkeypatch):
    from app.api.v1 import media as media_api
    from app.config import get_settings
    from app.models.media import MediaCacheEntry
    from app.models.media_backbone import MediaBlobLocation
    from app.models.photos_asset import PhotosAsset
    db, login, dives, users, _ = workspace
    monkeypatch.setattr(get_settings(), 'b2_playback_canary_enabled', True)
    db.query(MediaCacheEntry).delete()
    db.add(MediaBlobLocation(blob_sha256='a' * 64, environment='prod',
        storage_backend='b2', bucket=get_settings().media_backbone_prod_bucket,
        object_key='original.mov', verified=True))
    db.commit()

    client = login('viewer')
    rows = client.get(f"/api/v1/users/{users['alice'].id}/dives").json()['items']
    assert [row['id'] for row in rows] == [dives['alice-public']]
    # Bounded tile: placeholder, no B2 URL, no grant — even though a verified
    # original exists.
    assert rows[0]['poster_url'] is None
    assert rows[0]['playback_url'] is None
    # The full player status keeps the explicit original fallback behind auth.
    asset = db.query(PhotosAsset).filter_by(video_uuid='alice-public-video').one()
    assert media_api._status_for_asset(db, asset).playback_url.startswith('/api/v1/media/revisions/')
    # The URL remains authenticated and rechecks visibility on every grant.
    db.get(Dive, dives['alice-public']).visibility = 'private'
    db.commit()
    assert client.get(media_api._status_for_asset(db, asset).playback_url).status_code == 404
    assert client.get(f"/api/v1/users/{users['alice'].id}/dives").json()['items'] == []


def test_profile_grid_ignores_deleted_poster_and_uses_local_video(workspace):
    from app.models.media import MediaCacheEntry
    db, login, dives, users, _ = workspace
    dive = db.get(Dive, dives['alice-public'])
    db.add(MediaCacheEntry(photos_asset_id=dive.photos_asset_id, media_key='missing-poster',
        rendition='poster', storage_path='/nonexistent/poster.jpg', size_bytes=10, status='ready'))
    db.commit()
    row = login('viewer').get(f"/api/v1/users/{users['alice'].id}/dives").json()['items'][0]
    assert row['poster_url'] is None
    assert row['playback_url'].startswith('/api/v1/media/cache/')


def test_avatar_limit_precedes_image_decode_and_never_parses_multipart(workspace, monkeypatch):
    from starlette.formparsers import MultiPartParser
    _, login, _, _, _ = workspace
    def forbidden(*args, **kwargs):
        raise AssertionError('Body must be bounded before parsing/decoding')
    monkeypatch.setattr(MultiPartParser, 'parse', forbidden)
    monkeypatch.setattr(Image, 'open', forbidden)
    response = login('alice').put('/api/v1/users/me/avatar',
        content=b'x' * (2 * 1024 * 1024 + 1),
        headers={'Content-Type': 'multipart/form-data; boundary=avatar'})
    assert response.status_code == 413


def test_directory_dive_summary_matches_visible_grid(workspace):
    db, login, dives, users, _ = workspace
    db.get(Dive, dives['alice-private']).dive_datetime = datetime(2026, 10, 18, 12)
    db.get(Dive, dives['alice-public']).dive_datetime = datetime(2026, 1, 1, 12)
    db.commit()
    for viewer, count, latest in [('viewer', 1, '2026-01-01'), ('alice', 2, '2026-10-18')]:
        client = login(viewer)
        rows = client.get('/api/v1/users').json()['items']
        alice = next(row for row in rows if row['user_id'] == users['alice'].id)
        assert alice['accessible_dive_count'] == count
        assert alice['latest_dive_at'].startswith(latest)
        empty = next(row for row in rows if row['user_id'] == users['viewer'].id)
        assert empty['accessible_dive_count'] == 0
        assert empty['latest_dive_at'] is None


def test_linked_accounts_are_flagged_for_the_viewer_only(workspace):
    db, login, _, users, _ = workspace
    alice_diver = db.query(UserDiverAccess).filter_by(user_id=users['alice'].id).one().diver_id
    twin = AppUser(email='twin@example.test', display_name='twin', role='friend')
    db.add(twin)
    db.flush()
    twin_id = twin.id
    db.add(UserDiverAccess(user_id=twin_id, diver_id=alice_diver, access_kind='OWNER'))
    db.commit()
    flags = {item['user_id']: item['linked'] for item in login('alice').get('/api/v1/users').json()['items']}
    assert flags[twin_id] is True and flags[users['bob'].id] is False
    others = {item['user_id']: item['linked'] for item in login('bob').get('/api/v1/users').json()['items']}
    assert others[twin_id] is False and others[users['alice'].id] is False
    assert all(item['linked'] is False for item in login('viewer').get('/api/v1/users').json()['items'])


def test_member_codes_follow_dive_visibility(workspace):
    db, login, dives, users, session_id = workspace
    diver = db.query(UserDiverAccess).filter_by(user_id=users['bob'].id).one().diver_id
    db.add(Dive(session_id=session_id, diver_id=diver, dive_code='5122D', performance='P', performance_numeric=0, height='1m', dive_datetime=datetime(2026, 9, 1), visibility='public'))
    db.add(Dive(session_id=session_id, diver_id=diver, dive_code='5122D', performance='G', performance_numeric=0, height='1m', dive_datetime=datetime(2026, 9, 2), visibility='public', is_lineup=True))
    db.commit()
    url = f"/api/v1/users/{users['bob'].id}/codes"
    seen = login('viewer').get(url).json()
    codes = {item['dive_code']: item for item in seen['codes']}
    assert set(codes) == {'101B', '5122D'}
    assert codes['101B']['attempt_count'] == 1  # the private 101B stays hidden
    assert codes['5122D']['attempt_count'] == 1 and codes['5122D']['median'] == 10.0  # lineups excluded
    assert seen['totals']['attempt_count'] == 2
    own = login('bob').get(url).json()
    assert {item['dive_code']: item['attempt_count'] for item in own['codes']}['101B'] == 2
    assert own['totals']['attempt_count'] == 3
    grid = login('viewer').get(f"/api/v1/users/{users['bob'].id}/dives").json()['items']
    assert {'performance', 'phase1_performance', 'phase2_performance'} <= set(grid[0])
    assert login('viewer').get('/api/v1/users/999999/codes').status_code == 404


def test_leaderboard_counts_visible_dives_streaks_and_progress(workspace):
    from datetime import timedelta
    db, login, _, users, session_id = workspace
    bob = db.query(UserDiverAccess).filter_by(user_id=users['bob'].id).one().diver_id
    now = datetime.now()
    def add(diver, days_ago, performance, visibility='public', lineup=False):
        db.add(Dive(session_id=session_id, diver_id=diver, dive_code=f'10{days_ago % 3}C', performance=performance, performance_numeric=0, height='1m',
                    dive_datetime=now - timedelta(days=days_ago, hours=1), visibility=visibility, is_lineup=lineup))
    for day in range(1, 6):
        add(bob, day, 'G')          # this week-ish: median 7
    for day in range(8, 13):
        add(bob, day, 'M')          # previous week: median 4.5
    for weeks in (2, 3):
        add(bob, weeks * 7 + 1, 'B')
    add(bob, 1, 'P', visibility='private')
    add(bob, 1, 'P', lineup=True)
    db.commit()

    board = login('viewer').get('/api/v1/users/leaderboard', params={'period': 'week'}).json()
    entry = next(m for m in board['members'] if m['user_id'] == users['bob'].id)
    # The fixture's public 101B (today) counts too; private and lineup dives never do.
    assert entry['attempts'] == 6
    assert entry['codes'] == 4 and entry['median'] == 7.0 and entry['delta'] == 2.5
    assert entry['streak_weeks'] >= 3 and entry['avatar_hud']
    month = login('viewer').get('/api/v1/users/leaderboard', params={'period': 'month'}).json()
    assert next(m for m in month['members'] if m['user_id'] == users['bob'].id)['attempts'] == 13
    own = login('bob').get('/api/v1/users/leaderboard').json()
    assert next(m for m in own['members'] if m['user_id'] == users['bob'].id)['attempts'] == 8  # bob also sees his two private dives
    assert login('viewer').get('/api/v1/users/leaderboard', params={'period': 'year'}).status_code == 422
