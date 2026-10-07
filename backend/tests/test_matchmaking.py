import uuid
from datetime import datetime, timedelta
from tests.test_member_dive_visibility import workspace
from app.models.dive import Dive
from app.models.user_auth import AppUser
from app.models.matchmaking import AutomaticRating, ReviewStackItem


def stack(client, daily=True, key=None):
    r = client.post('/api/v1/evaluations/automatic/stacks', json={'daily': daily, 'client_session_id': key or str(uuid.uuid4())})
    assert r.status_code == 200, r.text
    sid = r.json()['session_id']
    q = client.get(f'/api/v1/evaluations/automatic/stacks/{sid}/queue')
    assert q.status_code == 200, q.text
    return sid, q.json()['items']


def test_public_only_daily_resume_and_isolation(workspace):
    db, login, dives, users, _ = workspace
    sid, items = stack(login('bob'))
    assert [i['dive_id'] for i in items] == [dives['alice-public']]
    assert stack(login('bob'))[0] == sid
    assert stack(login('bob'), daily=False)[1] == []  # outstanding daily stack
    assert login('alice').get(f'/api/v1/evaluations/automatic/stacks/{sid}/queue').status_code == 404
    assert items[0]['media']['playback_url'].startswith('/api/v1/evaluations/automatic/')
    assert login('bob').get(items[0]['media']['playback_url']).status_code == 200
    for key in ('alice-private', 'bob-public'):
        assert login('bob').get(f'/api/v1/evaluations/automatic/{dives[key]}/media/status').status_code == 404


def test_immutable_votes_separate_from_manual(workspace):
    db, login, dives, _, _ = workspace
    sid, items = stack(login('bob'))
    did = items[0]['dive_id']
    endpoint = f'/api/v1/evaluations/automatic/{did}/ratings'
    client = login('bob')
    result = client.post(endpoint, json={'video_uuid': 'alice-public-video', 'score_half_steps': 13, 'comment': ' good '})
    assert result.status_code == 200, result.text
    assert result.json()['results']['mean_score'] == 6.5
    assert client.post(endpoint, json={'video_uuid': 'alice-public-video', 'score_half_steps': 13, 'comment': 'good'}).json()['rating']['id'] == result.json()['rating']['id']
    assert client.post(endpoint, json={'video_uuid': 'alice-public-video', 'score_half_steps': 14}).status_code == 409
    assert client.post(endpoint, json={'video_uuid': 'alice-public-video', 'score_half_steps': 21}).status_code == 422
    assert client.get(f'/api/v1/evaluations/automatic/stacks/{sid}/queue').json()['items'] == []
    assert stack(client, daily=False)[1] == []
    from app.models.evaluation import EvaluationRating
    assert db.query(EvaluationRating).count() == 0
    summary = login('alice').get('/api/v1/evaluations/automatic/mine').json()['items'][0]
    assert summary['mean_score'] == 6.5 and summary['rating_count'] == 1 and summary['provisional']


def test_revocation_exclusion_and_disabled_owner(workspace):
    db, login, dives, users, _ = workspace
    sid, items = stack(login('bob'))
    did = dives['alice-public']
    endpoint = f'/api/v1/dives/{did}/automatic-review'
    assert login('bob').put(endpoint, json={'excluded': True}).status_code == 403
    assert login('alice').put(endpoint, json={'excluded': True}).status_code == 200
    client = login('bob')
    assert client.get(f'/api/v1/evaluations/automatic/{did}/media/status').status_code == 404
    assert client.post(f'/api/v1/evaluations/automatic/{did}/ratings', json={'video_uuid': 'alice-public-video', 'score_half_steps': 12}).status_code == 404
    assert client.get(f'/api/v1/evaluations/automatic/stacks/{sid}/queue').json()['items'] == []
    assert login('alice').put(endpoint, json={'excluded': False}).status_code == 200
    assert login('alice').put(f'/api/v1/dives/{did}', json={'visibility': 'private'}).status_code == 200
    assert login('bob').get(items[0]['media']['playback_url']).status_code == 404
    login('alice').put(f'/api/v1/dives/{did}', json={'visibility': 'public'})
    owner = db.get(AppUser, users['alice'].id); owner.is_active = False; db.commit()
    assert login('bob').get(items[0]['media']['playback_url']).status_code == 404


def test_skip_cooldown_and_explicit_retry(workspace):
    db, login, dives, _, _ = workspace
    client = login('bob')
    sid, items = stack(client)
    did = items[0]['dive_id']
    assert client.post(f'/api/v1/evaluations/automatic/stacks/{sid}/skip', json={'request_id': did}).status_code == 200
    key = str(uuid.uuid4())
    extra, empty = stack(client, daily=False, key=key)
    assert empty == [] and stack(client, daily=False, key=key)[0] == extra
    row = db.query(ReviewStackItem).filter_by(stack_id=sid).one()
    row.skipped_at = datetime.utcnow() - timedelta(days=8); db.commit()
    assert len(stack(client, daily=False)[1]) == 1


def test_unassigned_and_anonymous_votes_fail(workspace):
    _, login, dives, _, _ = workspace
    client = login('viewer')
    path = f'/api/v1/evaluations/automatic/{dives["alice-public"]}/ratings'
    assert client.post(path, json={'video_uuid': 'alice-public-video', 'score_half_steps': 10}).status_code == 404
    client.cookies.clear()
    assert client.post(path, json={'video_uuid': 'alice-public-video', 'score_half_steps': 10}).status_code == 401


def test_fair_by_owner_and_partial_stack(workspace):
    db, login, dives, users, session_id = workspace
    from app.models.photos_asset import PhotosAsset
    from app.models.media import MediaCacheEntry
    alice_dive = db.get(Dive, dives['alice-public'])
    for n in range(6):
        dive = Dive(session_id=session_id, diver_id=alice_dive.diver_id, dive_code='103B', performance='G',
            performance_numeric=3, height='3m', dive_datetime=datetime.utcnow() + timedelta(seconds=n),
            visibility='public', video_uuid=f'alice-extra-{n}')
        db.add(dive); db.flush()
        asset = PhotosAsset(video_uuid=dive.video_uuid); db.add(asset); db.flush()
        db.add(MediaCacheEntry(photos_asset_id=asset.id, media_key=f'fair-{n}', rendition='proxy_360p', storage_path='/test', size_bytes=1))
    db.commit()
    _, items = stack(login('viewer'))
    assert len(items) == 3
    assert dives['bob-public'] in [i['dive_id'] for i in items[:2]]
    _, small = stack(login('alice'))
    assert len(small) == 1 and small[0]['dive_id'] == dives['bob-public']


def test_video_replacement_invalidates_assignment(workspace):
    db, login, dives, _, _ = workspace
    sid, items = stack(login('bob'))
    did = dives['alice-public']
    dive = db.get(Dive, did); dive.video_uuid = 'replacement'; db.commit()
    client = login('bob')
    assert client.get(f'/api/v1/evaluations/automatic/stacks/{sid}/queue').json()['items'] == []
    assert client.post(f'/api/v1/evaluations/automatic/{did}/ratings', json={'video_uuid': 'alice-public-video', 'score_half_steps': 10}).status_code == 404
    assert db.query(AutomaticRating).count() == 0


def test_missing_migration_fails_closed(workspace):
    db, login, _, _, _ = workspace
    from sqlalchemy import text
    db.execute(text('DROP TABLE review_exclusions')); db.commit()
    assert login('bob').get('/api/v1/evaluations/automatic/mine').status_code == 503
    assert login('bob').get('/api/v1/evaluations/mine').status_code == 200


def test_unbound_diver_votes_survive_binding_but_self_votes_leave_score(workspace):
    from app.models.user_auth import UserDiverAccess
    db, login, dives, users, _ = workspace
    did = dives['alice-public']
    diver_id = db.get(Dive, did).diver_id
    db.query(UserDiverAccess).filter_by(diver_id=diver_id).delete(); db.commit()
    sid, items = stack(login('bob'))
    assert [i['dive_id'] for i in items] == [did]
    result = login('bob').post(f'/api/v1/evaluations/automatic/{did}/ratings', json={'video_uuid': 'alice-public-video', 'score_half_steps': 14})
    assert result.status_code == 200, result.text
    viewer_sid, _ = stack(login('viewer'))
    db.add(UserDiverAccess(user_id=users['bob'].id, diver_id=diver_id, access_kind='OWNER')); db.commit()
    assert db.query(AutomaticRating).filter_by(dive_id=did).count() == 1
    summary = login('bob').get('/api/v1/evaluations/automatic/mine').json()['items']
    row = next(i for i in summary if i['dive_id'] == did)
    assert row['rating_count'] == 0 and row['mean_score'] is None
    assert login('bob').get(f'/api/v1/evaluations/automatic/{did}/media/status').status_code == 404
    # Another reviewer's existing assignment remains valid after binding.
    assert did in [i['dive_id'] for i in login('viewer').get(f'/api/v1/evaluations/automatic/stacks/{viewer_sid}/queue').json()['items']]


def test_binding_removes_pending_own_dive_and_unattributed_never_matches(workspace):
    from app.models.user_auth import UserDiverAccess
    db, login, dives, users, _ = workspace
    did = dives['alice-public']; diver_id = db.get(Dive, did).diver_id
    db.query(UserDiverAccess).filter_by(diver_id=diver_id).delete(); db.commit()
    sid, items = stack(login('bob'))
    assert items
    db.add(UserDiverAccess(user_id=users['bob'].id, diver_id=diver_id, access_kind='OWNER')); db.commit()
    assert login('bob').get(f'/api/v1/evaluations/automatic/stacks/{sid}/queue').json()['items'] == []
    assert login('bob').post(f'/api/v1/evaluations/automatic/{did}/ratings', json={'video_uuid': 'alice-public-video', 'score_half_steps': 14}).status_code == 404
    db.get(Dive, did).diver_id = None; db.commit()
    assert did not in [i['dive_id'] for i in stack(login('viewer'))[1]]


def test_original_transport_stays_scoped_and_rechecks_binding(workspace, monkeypatch):
    from app.api.v1 import media_playback
    from app.services import matchmaking
    from fastapi.responses import Response
    db, login, dives, users, _ = workspace
    did = dives['alice-public']
    monkeypatch.setattr(matchmaking, 'original_revision_id', lambda db, video: 42)
    calls = []
    async def play(revision_id, request, response, db, user):
        calls.append((revision_id, user.id))
        return Response(b'original video', media_type='video/mp4')
    monkeypatch.setattr(media_playback, 'play_media_revision', play)
    client = login('bob')
    status = client.get(f'/api/v1/evaluations/automatic/{did}/media/status').json()
    assert status['rendition'] == 'original'
    assert '/automatic/' in status['playback_url']
    assert 'original' in status['available_renditions']
    assert client.get(status['playback_url'] + '?rendition=original').content == b'original video'
    assert calls == [(42, users['bob'].id)]
    login('alice').put(f'/api/v1/dives/{did}/automatic-review', json={'excluded': True})
    assert login('bob').get(status['playback_url'] + '?rendition=original').status_code == 404
    assert len(calls) == 1


def test_unbound_divers_have_separate_fairness_buckets(workspace):
    from app.models.user_auth import UserDiverAccess
    from app.models.photos_asset import PhotosAsset
    from app.models.media import MediaCacheEntry
    db, login, dives, _, session_id = workspace
    alice = db.get(Dive, dives['alice-public'])
    alice_diver = alice.diver_id
    db.query(UserDiverAccess).delete()
    for n in range(4):
        dive = Dive(session_id=session_id, diver_id=alice_diver, dive_code='103B', performance='G',
            performance_numeric=3, height='3m', dive_datetime=datetime.utcnow() + timedelta(seconds=n),
            visibility='public', video_uuid=f'unbound-extra-{n}')
        db.add(dive); db.flush()
        asset = PhotosAsset(video_uuid=dive.video_uuid); db.add(asset); db.flush()
        db.add(MediaCacheEntry(photos_asset_id=asset.id, media_key=f'unbound-{n}', rendition='proxy_360p', storage_path='/test', size_bytes=1))
    db.commit()
    _, items = stack(login('viewer'))
    assert len(items) == 3
    assert dives['bob-public'] in [i['dive_id'] for i in items[:2]]


def test_original_readiness_rejects_wrong_bucket_and_ambiguous_storage(workspace):
    from app.config import get_settings
    from app.models.media_backbone import MediaBlobLocation
    from app.models.media import MediaCacheEntry
    from app.services import matchmaking
    db, login, dives, _, _ = workspace
    settings = get_settings(); previous = settings.b2_playback_canary_enabled
    settings.b2_playback_canary_enabled = True
    try:
        db.query(MediaCacheEntry).delete()
        location = MediaBlobLocation(blob_sha256='a' * 64, environment='prod', storage_backend='b2',
            verified=True, bucket='wrong-bucket', object_key='original.mp4')
        db.add(location); db.commit()
        assert matchmaking.original_revision_id(db, 'alice-public-video') is None
        assert stack(login('bob'))[1] == []
        location = db.get(MediaBlobLocation, location.id)
        location.bucket = settings.media_backbone_prod_bucket; db.commit()
        assert matchmaking.original_revision_id(db, 'alice-public-video') is not None
        _, items = stack(login('bob'), daily=False)
        assert [i['dive_id'] for i in items] == [dives['alice-public']]
        assert items[0]['media']['rendition'] == 'original'
        db.add(MediaBlobLocation(blob_sha256='a' * 64, environment='prod', storage_backend='b2',
            verified=True, bucket=settings.media_backbone_prod_bucket, object_key='duplicate.mp4')); db.commit()
        assert matchmaking.original_revision_id(db, 'alice-public-video') is None
        assert login('bob').get(f'/api/v1/evaluations/automatic/{dives["alice-public"]}/media/status').json()['status'] != 'ready'
    finally:
        settings.b2_playback_canary_enabled = previous
