"""Shared sessions: B2 inbox ingestion, member playback and guest links."""
import hashlib
import hmac
import json
from datetime import date, datetime, timezone
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.main import app
from app.models.notification import Notification
from app.models.session import Session as TrainingSession
from app.models.session_video import SessionVideo, SessionVideoPlaybackIssue, SessionVideoShare
from app.services import session_videos as service
from app.services import telegram
from tests.test_member_dive_visibility import workspace  # noqa: F401

SECRET = 'test-event-secret'
KEY = 'inbox/IMG_2651.MOV'
# Shape of the real iPhone 17 probe (trimmed), including the GPS tag that
# must never be stored or returned.
PROBE = {
    'format': {
        'duration': '1936.801667', 'size': '3338404955', 'bit_rate': '13789351',
        'tags': {'creation_time': '2026-10-17T11:05:10.000000Z',
                 'com.apple.quicktime.location.ISO6709': '+48.8561+002.4341+080.134/',
                 'com.apple.quicktime.creationdate': '2026-10-17T13:05:10+0200'},
    },
    'streams': [
        {'codec_type': 'video', 'codec_name': 'hevc', 'codec_tag_string': 'hvc1', 'profile': 'Main 10',
         'level': 123, 'pix_fmt': 'yuv420p10le', 'color_transfer': 'arib-std-b67', 'width': 1920,
         'height': 1080, 'r_frame_rate': '60/1', 'avg_frame_rate': '69691800/1162081'},
        {'codec_type': 'audio', 'codec_name': 'aac', 'profile': 'LC'},
        {'codec_type': 'audio', 'codec_tag_string': 'apac'},
        {'codec_type': 'data', 'codec_tag_string': 'mebx'},
    ],
}


class FakeB2:
    def __init__(self):
        self.objects = {'inbox/': 0, KEY: 3338404955, 'inbox/notes.txt': 4}
        self.presigned = []

    def head_object(self, Bucket, Key):
        return {'ContentLength': self.objects[Key], 'ETag': '"abc-637"',
                'LastModified': datetime(2026, 10, 28, 13, 50, tzinfo=timezone.utc)}

    def list_objects_v2(self, Bucket, Prefix, MaxKeys, ContinuationToken=None):
        return {'Contents': [{'Key': k, 'Size': s, 'LastModified': datetime(2026, 10, 28, tzinfo=timezone.utc)}
                             for k, s in self.objects.items() if k.startswith(Prefix)], 'IsTruncated': False}

    def generate_presigned_url(self, operation, Params, ExpiresIn):
        self.presigned.append((Params, ExpiresIn))
        return f"https://b2.example.test/{Params['Bucket']}/{Params['Key']}?sig=x"


@pytest.fixture
def sessions_env(workspace, monkeypatch):  # noqa: F811
    db, login, dives, users, training_id = workspace
    settings = get_settings()
    for name, value in dict(shared_sessions_enabled=True, shared_sessions_owner_email='alice@example.test',
                            sessions_b2_event_secret=SECRET, app_public_url='https://dive.example.test',
                            sessions_telegram_bot_token='', sessions_telegram_chat_id='').items():
        monkeypatch.setattr(settings, name, value)
    b2 = FakeB2()
    probes = []
    monkeypatch.setattr(service, 'storage_client', lambda: b2)
    monkeypatch.setattr(service, 'run_ffprobe', lambda url: probes.append(url) or json.loads(json.dumps(PROBE)))
    shared = db

    class Borrowed:
        """Background ingestion borrows the test session (StaticPool sqlite)."""
        def __getattr__(self, name):
            return getattr(shared, name)

        def close(self):
            pass
    monkeypatch.setattr('app.database.SessionLocal', lambda: Borrowed())
    return db, login, users, b2, probes


def signed(body: bytes) -> dict:
    return {'X-Bz-Event-Notification-Signature': 'v1=' + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest(),
            'Content-Type': 'application/json'}


def event_body(*events) -> bytes:
    return json.dumps({'events': list(events)}).encode()


def created(key=KEY, kind='b2:ObjectCreated:MultipartUpload', bucket='diveanalyzer-sessions'):
    return {'eventType': kind, 'bucketName': bucket, 'objectName': key, 'objectSize': 3338404955,
            'eventTimestamp': 1761659422601, 'eventId': 'e1'}


def test_probe_parsing_matches_real_iphone_shape():
    result = service.parse_probe(PROBE)
    assert result.codec_string == 'hvc1.2.4.L123.B0'
    assert result.audio_codec_string == 'mp4a.40.2'
    assert result.color_transfer == 'arib-std-b67'
    assert (result.width, result.height, round(result.fps)) == (1920, 1080, 60)
    utc, day = service.local_day(result.recorded_at, datetime.now(timezone.utc))
    assert utc == datetime(2026, 10, 17, 11, 5, 10) and day == date(2026, 10, 17)
    # Late-evening UTC recordings belong to the next Paris day.
    _, late = service.local_day(datetime(2026, 7, 1, 22, 30, tzinfo=timezone.utc), datetime.now(timezone.utc))
    assert late == date(2026, 7, 2)
    assert service.codec_string({'codec_name': 'h264', 'profile': 'High', 'level': 40}) == 'avc1.640028'


def test_feature_off_hides_every_route(sessions_env, monkeypatch):
    db, login, *_ = sessions_env
    monkeypatch.setattr(get_settings(), 'shared_sessions_enabled', False)
    body = event_body(created())
    assert login('alice').get('/api/v1/session-videos').status_code == 404
    assert login('alice').post('/api/v1/session-videos/b2-events', content=body, headers=signed(body)).status_code == 404
    assert login('alice').get('/api/v1/auth/me').json()['features']['shared_sessions'] is False
    assert service.start_reconciler() is None


def test_event_signature_is_required_and_duplicates_ingest_once(sessions_env):
    db, login, users, b2, probes = sessions_env
    client = login('viewer')
    client.cookies.clear()  # Backblaze has no session
    body = event_body(created())
    assert client.post('/api/v1/session-videos/b2-events', content=body).status_code == 401
    assert client.post('/api/v1/session-videos/b2-events', content=body,
                       headers={**signed(body), 'X-Bz-Event-Notification-Signature': 'v1=' + '0' * 64}).status_code == 401
    tampered = body.replace(b'IMG_2651', b'IMG_2652')
    assert client.post('/api/v1/session-videos/b2-events', content=tampered, headers=signed(body)).status_code == 401
    for _ in range(3):  # at-least-once delivery
        response = client.post('/api/v1/session-videos/b2-events', content=body, headers=signed(body))
        assert response.status_code == 200 and response.json() == {'accepted': 1}
    video = db.query(SessionVideo).one()
    assert video.status == 'ready' and len(probes) == 1
    assert video.recorded_date == date(2026, 10, 17) and video.size_bytes == 3338404955
    session = db.get(TrainingSession, video.session_id)
    assert session.date == date(2026, 10, 17)
    notes = db.query(Notification).filter_by(type='session_video').all()
    assert len(notes) == 1 and notes[0].user_id == users['alice'].id
    assert '17/10/2026' in notes[0].body and '32 min' in notes[0].body
    # Probe URL: short-lived presigned GET, never a copy.
    assert b2.presigned[0][1] == service.PROBE_URL_TTL_SECONDS


def test_events_outside_the_inbox_or_bucket_are_ignored(sessions_env):
    db, login, *_ = sessions_env
    body = event_body({'eventType': 'b2:TestEvent'}, created('lab/x.mov'), created('inbox/notes.txt'),
                      created(bucket='other-bucket'), created(kind='b2:ObjectDeleted:Delete'))
    client = login('viewer')
    client.cookies.clear()
    response = client.post('/api/v1/session-videos/b2-events', content=body, headers=signed(body))
    assert response.json() == {'accepted': 0}
    assert db.query(SessionVideo).count() == 0
    assert login('viewer').post('/api/v1/session-videos/b2-events', content=b'nope',
                                headers=signed(b'nope')).status_code == 400


def test_reconciliation_ingests_missed_objects_once_and_reuses_the_day(sessions_env):
    db, login, users, b2, probes = sessions_env
    existing = TrainingSession(date=date(2026, 10, 17), notes='coach day')
    db.add(existing)
    db.commit()
    assert service.reconcile(db) == 1
    assert service.reconcile(db) == 0
    video = db.query(SessionVideo).one()
    assert video.session_id == existing.id and len(probes) == 1
    assert db.query(TrainingSession).filter_by(date=date(2026, 10, 17)).count() == 1
    assert db.query(Notification).filter_by(type='session_video').count() == 1


def test_probe_failure_is_retried_without_notifying(sessions_env, monkeypatch):
    db, login, users, b2, probes = sessions_env

    def broken(url):
        raise RuntimeError('ffprobe exited 1')
    monkeypatch.setattr(service, 'run_ffprobe', broken)
    row = service.ingest_object(db, KEY)
    assert row.status == 'failed' and row.attempts == 1 and row.last_error == 'ffprobe exited 1'
    assert db.query(Notification).count() == 0
    monkeypatch.setattr(service, 'run_ffprobe', lambda url: PROBE)
    assert service.reconcile(db) == 1
    row = db.query(SessionVideo).one()
    assert row.status == 'ready' and row.attempts == 2 and row.last_error is None


def test_missing_owner_skips_ingestion(sessions_env, monkeypatch):
    db, *_ = sessions_env
    monkeypatch.setattr(get_settings(), 'shared_sessions_owner_email', 'nobody@example.test')
    assert service.ingest_object(db, KEY) is None
    assert db.query(SessionVideo).count() == 0


def test_members_watch_and_only_the_owner_shares(sessions_env):
    db, login, users, b2, _ = sessions_env
    video_id = service.ingest_object(db, KEY).id
    viewer = login('viewer')
    listing = viewer.get('/api/v1/session-videos').json()
    assert [item['id'] for item in listing['items']] == [video_id]
    detail = viewer.get(f'/api/v1/session-videos/{video_id}').json()
    assert detail['can_share'] is False and detail['codec_string'] == 'hvc1.2.4.L123.B0'
    assert 'ISO6709' not in json.dumps(detail) and 'object_key' not in detail and 'bucket' not in detail
    play = viewer.get(f'/api/v1/session-videos/{video_id}/play', follow_redirects=False)
    assert play.status_code == 302 and play.headers['location'].startswith('https://b2.example.test/')
    assert play.headers['cache-control'] == 'private, no-store'
    params, ttl = b2.presigned[-1]
    assert params['ResponseContentType'] == 'video/mp4' and ttl == get_settings().sessions_playback_ttl_seconds
    viewer.get(f'/api/v1/session-videos/{video_id}/download', follow_redirects=False)
    assert b2.presigned[-1][0]['ResponseContentDisposition'] == 'attachment; filename="IMG_2651.MOV"'
    assert viewer.post(f'/api/v1/session-videos/{video_id}/shares').status_code == 403
    assert login('alice').get(f'/api/v1/session-videos/{video_id}').json()['can_share'] is True
    viewer.cookies.clear()
    assert viewer.get(f'/api/v1/session-videos/{video_id}/play').status_code == 401


def test_guest_link_capability_identity_and_revocation(sessions_env):
    db, login, users, b2, _ = sessions_env
    video_id = service.ingest_object(db, KEY).id
    owner = login('alice')
    path = owner.post(f'/api/v1/session-videos/{video_id}/shares').json()['path']
    share_path, token = urlsplit(path).path, urlsplit(path).fragment
    assert share_path.startswith('/share/session/') and len(token) == 43
    assert token not in db.query(SessionVideoShare).one().token_hash
    base = '/api/v1/shared-dives/sessions/' + share_path.rsplit('/', 1)[-1]
    with TestClient(app, base_url='https://testserver') as guest:
        assert guest.get(base + '/video').status_code == 404
        assert guest.post(base + '/visit', headers={'X-Dive-Share': 'x' * 43}).status_code == 404
        identity = guest.post(base + '/visit', headers={'X-Dive-Share': token}).json()
        from app.api.v1.dive_sharing import CHARACTERS
        assert identity['guest_name'] in CHARACTERS and identity['id'] == video_id
        assert guest.post(base + '/visit', headers={'X-Dive-Share': token}).json()['guest_id'] == identity['guest_id']
        cookie = next(c for c in guest.cookies.jar if c.name == 'dive_guest')
        assert cookie.path == '/api/v1/shared-dives'  # same identity as dive links
        response = guest.get(identity['video_url'], follow_redirects=False)
        assert response.status_code == 302 and response.headers['referrer-policy'] == 'no-referrer'
        assert guest.get(identity['download_url'], follow_redirects=False).status_code == 302
        for _ in range(2):
            assert guest.post(base + '/playback-issues', json={'reason': 'no_frames'}).status_code == 204
        assert guest.post(base + '/playback-issues', json={'reason': 'bogus'}).status_code == 422
        issues = db.query(SessionVideoPlaybackIssue).all()
        assert len(issues) == 1 and issues[0].viewer_guest_id == identity['guest_id']
        for path in ('/api/v1/session-videos', f'/api/v1/session-videos/{video_id}/play', '/api/v1/auth/me'):
            assert guest.get(path).status_code == 401
        assert owner.get(f'/api/v1/session-videos/{video_id}/shares').json() == {'active_count': 1}
        assert owner.delete(f'/api/v1/session-videos/{video_id}/shares').status_code == 204
        assert guest.get(identity['video_url'], follow_redirects=False).status_code == 404
        assert guest.post(base + '/visit', headers={'X-Dive-Share': token}).status_code == 404


def test_member_playback_issue_is_counted_once_per_hour(sessions_env):
    db, login, *_ = sessions_env
    video_id = service.ingest_object(db, KEY).id
    client = login('viewer')
    for _ in range(3):
        assert client.post(f'/api/v1/session-videos/{video_id}/playback-issues',
                           json={'reason': 'unsupported'}).status_code == 204
    assert client.post(f'/api/v1/session-videos/{video_id}/playback-issues',
                       json={'reason': 'unsupported'}, headers={'Origin': 'https://evil.test'}).status_code == 403
    assert db.query(SessionVideoPlaybackIssue).count() == 1


def test_telegram_message_carries_a_working_guest_link_once(sessions_env, monkeypatch):
    db, login, users, b2, _ = sessions_env
    settings = get_settings()
    monkeypatch.setattr(settings, 'sessions_telegram_bot_token', 'bot-token')
    monkeypatch.setattr(settings, 'sessions_telegram_chat_id', '42')
    sent = []
    monkeypatch.setattr(telegram, 'send', lambda text: sent.append(text) or True)
    video_id = service.ingest_object(db, KEY).id
    service.ingest_object(db, KEY)
    assert len(sent) == 1 and db.query(SessionVideoShare).count() == 1
    link = next(line for line in sent[0].splitlines() if 'invité' in line).split(' : ', 1)[1]
    assert link.startswith('https://dive.example.test/share/session/')
    share_id, token = urlsplit(link).path.rsplit('/', 1)[-1], urlsplit(link).fragment
    with TestClient(app, base_url='https://testserver') as guest:
        visit = guest.post(f'/api/v1/shared-dives/sessions/{share_id}/visit', headers={'X-Dive-Share': token})
        assert visit.status_code == 200 and visit.json()['id'] == video_id
    assert f'/session-videos/{video_id}' in sent[0]


def test_telegram_never_leaks_the_token_in_logs(monkeypatch, caplog):
    import requests
    settings = get_settings()
    monkeypatch.setattr(settings, 'sessions_telegram_bot_token', 'SECRET-BOT-TOKEN')
    monkeypatch.setattr(settings, 'sessions_telegram_chat_id', '42')

    def boom(url, **kwargs):
        raise requests.ConnectionError(f'cannot reach {url}')
    monkeypatch.setattr(requests, 'post', boom)
    assert telegram.send('hello') is False
    assert 'SECRET-BOT-TOKEN' not in caplog.text
