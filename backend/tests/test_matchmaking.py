import uuid
import pytest
from datetime import datetime, timedelta
from tests.test_member_dive_visibility import workspace
from app.models.dive import Dive
from app.models.user_auth import AppUser
from app.models.matchmaking import AutomaticRating, ReviewStackItem


def stack(client, daily=True, key=None, size=None):
    r = client.post('/api/v1/evaluations/automatic/stacks', json={'daily': daily, 'client_session_id': key or str(uuid.uuid4()), **({'size': size} if size is not None else {})})
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
    assert len(items) == 5
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
    def play(revision_id, request, response, db, user):
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
    assert len(items) == 5
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
        # A verified cloud original is not an already prepared preview.
        assert items == []
        db.add(MediaBlobLocation(blob_sha256='a' * 64, environment='prod', storage_backend='b2',
            verified=True, bucket=settings.media_backbone_prod_bucket, object_key='duplicate.mp4')); db.commit()
        assert matchmaking.original_revision_id(db, 'alice-public-video') is None
        assert login('bob').get(f'/api/v1/evaluations/automatic/{dives["alice-public"]}/media/status').json()['status'] != 'ready'
    finally:
        settings.b2_playback_canary_enabled = previous


def test_results_require_owner_or_vote_and_page_full_aggregate(workspace):
    db, login, dives, users, _ = workspace
    did = dives['alice-public']
    path = f'/api/v1/evaluations/automatic/{did}/results'
    # Assignment does not reveal scores before this member confirms a vote.
    stack(login('bob'))
    assert login('bob').get(path).status_code == 404
    assert login('viewer').get(path).status_code == 404
    assert login('alice').get(path).status_code == 200
    client = login('bob')
    assert client.post(f'/api/v1/evaluations/automatic/{did}/ratings', json={
        'video_uuid': 'alice-public-video', 'score_half_steps': 14}).status_code == 200
    for i in range(59):
        user = AppUser(email=f'jury-{i}@example.test', display_name=f'Jury {i}', role='friend')
        db.add(user); db.flush()
        db.add(AutomaticRating(dive_id=did, evaluator_user_id=user.id, score_half_steps=14,
            dive_code='101B', height='3m', dive_name='Dive', video_uuid='alice-public-video'))
    db.commit()
    first = client.get(path).json()
    second = client.get(path, params={'offset': 50, 'limit': 50}).json()
    assert first['rating_count'] == second['rating_count'] == 60
    assert first['mean_score'] == second['mean_score'] == 7.0
    assert len(first['ratings']) == 50 and len(second['ratings']) == 10
    assert not {r['id'] for r in first['ratings']} & {r['id'] for r in second['ratings']}
    assert first['my_rating']['evaluator_user_id'] == users['bob'].id
    assert client.get(path, params={'limit': 101}).status_code == 422
    assert client.get(path, params={'offset': -1}).status_code == 422
    assert login('viewer').get(path).status_code == 404
    assert 'media' not in first and 'playback_url' not in first
    assert login('alice').get(path).json()['rating_count'] == 60
    client.cookies.clear()
    assert client.get(path).status_code == 401


def test_overview_reports_today_without_allocating(workspace):
    db, login, dives, _, _ = workspace
    from app.models.matchmaking import ReviewStack
    client = login('bob')
    empty = client.get('/api/v1/evaluations/overview')
    assert empty.status_code == 200, empty.text
    assert empty.json()['today']['daily'] is None and empty.json()['today']['resume'] is None
    assert db.query(ReviewStack).count() == 0  # a GET never allocates
    sid, items = stack(client)
    today = client.get('/api/v1/evaluations/overview').json()['today']
    assert today['daily'] == today['resume'] == {'stack_id': sid, 'daily': True, 'total': 1, 'judged': 0, 'skipped': 0, 'remaining': 1}
    did = items[0]['dive_id']
    assert client.post(f'/api/v1/evaluations/automatic/{did}/ratings', json={'video_uuid': 'alice-public-video', 'score_half_steps': 12}).status_code == 200
    body = client.get('/api/v1/evaluations/overview').json()
    assert body['today']['daily']['judged'] == 1 and body['today']['resume'] is None
    assert body['today']['judged_today'] == 1 and body['judged_total'] == 1
    history = client.get('/api/v1/evaluations/my-ratings').json()
    assert history['total'] == 1
    assert history['items'][0]['kind'] == 'automatic' and history['items'][0]['request_id'] == did
    assert history['items'][0]['rating_count'] == 1 and history['items'][0]['mean_score'] == 6.0


def test_overview_compares_my_votes_with_the_rest_of_the_panel(workspace):
    db, login, dives, _, _ = workspace
    did = dives['alice-public']
    for name, score in (('viewer', 8), ('bob', 12)):
        client = login(name)
        _, items = stack(client)
        assert did in [i['dive_id'] for i in items]
        assert client.post(f'/api/v1/evaluations/automatic/{did}/ratings', json={'video_uuid': 'alice-public-video', 'score_half_steps': score}).status_code == 200
    body = login('bob').get('/api/v1/evaluations/overview').json()
    vote = body['today']['votes'][0]
    assert vote['dive_id'] == did and vote['score_half_steps'] == 12
    assert vote['panel_count'] == 1 and vote['panel_mean'] == 4.0  # the others' mean, not including bob
    assert body['judge'] == {'compared': 1, 'bias': 2.0, 'streak': 1}
    # A vote yesterday keeps the streak going; a missed day breaks it.
    def age(days):
        db.query(AutomaticRating).filter(AutomaticRating.score_half_steps == 12).update(
            {'created_at': datetime.utcnow() - timedelta(days=days)}); db.commit()
        return login('bob').get('/api/v1/evaluations/overview').json()['judge']['streak']
    assert age(1) == 1
    assert age(2) == 0


def test_overview_resume_and_query_count_ignore_empty_stack_history(workspace):
    from sqlalchemy import event
    from app.models.matchmaking import ReviewStack
    from app.services import matchmaking
    db, login, _, users, _ = workspace
    sid, _ = stack(login('bob'))
    user = db.get(AppUser, users['bob'].id)

    def measure():
        statements = []
        def record(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)
        event.listen(db.bind, 'before_cursor_execute', record)
        try:
            body = matchmaking.today(db, user)
        finally:
            event.remove(db.bind, 'before_cursor_execute', record)
        assert body['daily']['stack_id'] == body['resume']['stack_id'] == sid
        return len(statements)

    measure()  # warm the session's expired objects
    baseline = measure()
    db.add_all([ReviewStack(user_id=user.id, key=f'empty-{n}') for n in range(200)])
    db.commit()
    measure()
    assert measure() == baseline


def test_overview_resumes_playable_stack_before_newer_revoked_or_finished_ones(workspace):
    from app.models.matchmaking import ReviewStack
    from app.services import matchmaking
    db, login, dives, users, _ = workspace
    sid, _ = stack(login('bob'))
    user = db.get(AppUser, users['bob'].id)
    # Model older unfinished on-demand work alongside a completed daily stack.
    daily = db.get(ReviewStack, sid)
    db.query(ReviewStackItem).filter_by(stack_id=sid).update({'skipped_at': datetime.utcnow()})
    def add_stack(key, did, video):
        row = ReviewStack(user_id=user.id, key=key)
        db.add(row); db.flush()
        db.add(ReviewStackItem(stack_id=row.id, dive_id=did, video_uuid=video, position=0))
        return row
    playable = add_stack('playable', dives['alice-public'], 'alice-public-video')
    add_stack('private', dives['alice-private'], 'alice-private-video')
    add_stack('replaced', dives['alice-public'], 'old-video')
    db.commit()
    body = matchmaking.today(db, user)
    assert body['daily']['stack_id'] == daily.id and body['daily']['skipped'] == 1
    assert body['resume']['stack_id'] == playable.id and body['resume']['remaining'] == 1


def test_overview_panel_stays_correct_when_voter_becomes_owner(workspace):
    from app.models.user_auth import UserDiverAccess
    db, login, dives, users, _ = workspace
    did = dives['alice-public']
    diver_id = db.get(Dive, did).diver_id
    db.query(UserDiverAccess).filter_by(diver_id=diver_id).delete(); db.commit()
    for name, score in (('viewer', 8), ('bob', 14)):
        client = login(name)
        stack(client)
        assert client.post(f'/api/v1/evaluations/automatic/{did}/ratings', json={
            'video_uuid': 'alice-public-video', 'score_half_steps': score}).status_code == 200
    db.add(UserDiverAccess(user_id=users['bob'].id, diver_id=diver_id, access_kind='OWNER'))
    db.commit()
    body = login('bob').get('/api/v1/evaluations/overview').json()
    vote = body['today']['votes'][0]
    assert vote['score_half_steps'] == 14
    assert vote['panel_count'] == 1 and vote['panel_mean'] == 4.0
    assert body['judge']['compared'] == 1 and body['judge']['bias'] == 3.0
    history = login('bob').get('/api/v1/evaluations/my-ratings').json()['items'][0]
    assert history['rating_count'] == 1 and history['mean_score'] == 4.0
    assert history['panel_count'] == 1 and history['panel_mean'] == 4.0
    # If no other vote is left, there is no panel or comparison sample.
    db.query(AutomaticRating).filter_by(evaluator_user_id=users['viewer'].id).delete(); db.commit()
    body = login('bob').get('/api/v1/evaluations/overview').json()
    assert body['today']['votes'][0]['panel_count'] == 0
    assert body['today']['votes'][0]['panel_mean'] is None
    assert body['judge']['compared'] == 0 and body['judge']['bias'] is None
    history = login('bob').get('/api/v1/evaluations/my-ratings').json()['items'][0]
    assert history['panel_count'] == 0 and history['panel_mean'] is None


def test_history_pages_both_vote_sources_in_sql_without_loading_skipped_rows(workspace):
    from types import SimpleNamespace
    from sqlalchemy import event
    from app.models.evaluation import EvaluationRating, EvaluationRequest
    from app.services import evaluation_ratings
    db, _, dives, users, _ = workspace
    user = SimpleNamespace(id=users['bob'].id)
    now = datetime.utcnow()
    for n, key in enumerate(('alice-public', 'alice-private')):
        request = EvaluationRequest(dive_id=dives[key], created_by_user_id=users['alice'].id)
        db.add(request); db.flush()
        snapshot = dict(evaluator_user_id=user.id, score_half_steps=12, dive_code='101B', height='3m', dive_name=key)
        db.add(EvaluationRating(request_id=request.id, created_at=now + timedelta(seconds=2*n), **snapshot))
        db.add(AutomaticRating(dive_id=dives[key], video_uuid=key + '-video', created_at=now + timedelta(seconds=2*n+1), **snapshot))
    db.commit()
    db.expunge_all()
    loaded = []
    def record(row, context):
        loaded.append(type(row))
    for model in (EvaluationRating, AutomaticRating):
        event.listen(model, 'load', record)
    try:
        page = evaluation_ratings.my_ratings(db, user, limit=2, offset=1)
        assert page['total'] == 4
        assert [(r['kind'], r['dive']['dive_name']) for r in page['items']] == [
            ('request', 'alice-private'), ('automatic', 'alice-public')]
        assert len(loaded) == 2  # only this page's vote objects are materialized
        loaded.clear()
        far_page = evaluation_ratings.my_ratings(db, user, limit=2, offset=1_000_000)
        assert far_page['items'] == [] and far_page['total'] == 4
        assert loaded == []
    finally:
        for model in (EvaluationRating, AutomaticRating):
            event.remove(model, 'load', record)


@pytest.mark.parametrize('size', [1, 8, 20])
@pytest.mark.parametrize('daily', [True, False])
def test_configured_draw_size_and_immutable_retry(workspace, size, daily):
    from app.models.photos_asset import PhotosAsset
    from app.models.media import MediaCacheEntry
    db, login, dives, _, session_id = workspace
    source = db.get(Dive, dives['alice-public'])
    for n in range(22):
        dive = Dive(session_id=session_id, diver_id=source.diver_id, dive_code='103B', performance='G',
            performance_numeric=3, height='3m', dive_datetime=datetime.utcnow(),
            visibility='public', video_uuid=f'draw-size-{n}')
        db.add(dive); db.flush()
        asset = PhotosAsset(video_uuid=dive.video_uuid); db.add(asset); db.flush()
        db.add(MediaCacheEntry(photos_asset_id=asset.id, media_key=f'draw-size-{n}', rendition='proxy_360p',
            storage_path='/test', size_bytes=1))
    db.commit()
    client = login('bob')
    key = str(uuid.uuid4())
    sid, items = stack(client, daily=daily, key=key, size=size)
    assert len(items) == size
    retry_sid, retry_items = stack(client, daily=daily, key=key, size=5)
    assert retry_sid == sid
    assert [item['dive_id'] for item in retry_items] == [item['dive_id'] for item in items]


@pytest.mark.parametrize('size', [0, -1, 21, 1.5, '5', True, None])
def test_draw_size_rejects_invalid_values(workspace, size):
    _, login, _, _, _ = workspace
    response = login('bob').post('/api/v1/evaluations/automatic/stacks', json={
        'client_session_id': str(uuid.uuid4()), 'size': size})
    assert response.status_code == 422


def test_selection_assigns_previews_and_prioritizes_explicit_preparation(workspace):
    from app.models.media import MediaCacheEntry, MediaJob
    from app.models.photos_asset import PhotosAsset
    from app.services import evaluation_access
    db, login, dives, _, _ = workspace
    original = db.query(MediaCacheEntry).join(PhotosAsset).filter(PhotosAsset.video_uuid == 'alice-public-video').one()
    original.rendition = 'original'
    db.commit()
    _, items = stack(login('bob'))
    assert items == []
    jobs = db.query(MediaJob).filter_by(photos_asset_id=original.photos_asset_id).all()
    assert any(job.rendition == 'proxy_720p' for job in jobs)
    assert all(job.priority == 100 for job in jobs)
    asset = db.get(PhotosAsset, original.photos_asset_id)
    evaluation_access.prepare_media(db, db.get(Dive, dives['alice-public']), asset, reason='automatic_review')
    proxy = db.query(MediaJob).filter_by(photos_asset_id=asset.id, rendition='proxy_720p').one()
    assert proxy.priority == 5
    assert db.query(MediaJob).filter_by(photos_asset_id=asset.id, rendition='proxy_720p').count() == 1


def test_background_warmup_does_not_retry_invalid_identity(workspace):
    from app.models.media import MediaJob
    from app.models.photos_asset import PhotosAsset
    from app.services import evaluation_access
    db, _, dives, _, _ = workspace
    dive = db.get(Dive, dives['alice-public'])
    asset = db.query(PhotosAsset).filter_by(video_uuid=dive.video_uuid).one()
    failed = MediaJob(photos_asset_id=asset.id, media_key='invalid-source', rendition='proxy_720p',
        status='failed', last_error='invalid_video_uuid')
    db.add(failed); db.commit()
    assert evaluation_access.prepare_media(db, dive, asset, reason='automatic_review_warmup') == ([], [])
    assert db.query(MediaJob).filter_by(photos_asset_id=asset.id).count() == 1


@pytest.mark.parametrize('media_state', ['original', 'preparing', 'missing'])
def test_existing_cold_selection_remains_resumable_without_get_side_effects(workspace, media_state):
    from app.models.media import MediaCacheEntry, MediaJob
    from app.models.photos_asset import PhotosAsset
    db, login, dives, _, _ = workspace
    client = login('bob')
    sid, assigned = stack(client, daily=False)
    assert len(assigned) == 1
    asset = db.query(PhotosAsset).filter_by(video_uuid='alice-public-video').one()
    entries = db.query(MediaCacheEntry).filter_by(photos_asset_id=asset.id)
    if media_state == 'original':
        entries.one().rendition = 'original'
    else:
        entries.delete()
        if media_state == 'preparing':
            db.add(MediaJob(photos_asset_id=asset.id, media_key='cold-resume-proxy',
                rendition='proxy_720p', status='queued'))
    db.commit()
    jobs_before = db.query(MediaJob).count()
    overview = client.get('/api/v1/evaluations/overview')
    assert overview.status_code == 200
    assert overview.json()['today']['resume']['stack_id'] == sid
    assert overview.json()['today']['resume']['remaining'] == 1
    resumed = client.get(f'/api/v1/evaluations/automatic/stacks/{sid}/queue')
    assert resumed.status_code == 200
    assert [item['dive_id'] for item in resumed.json()['items']] == [dives['alice-public']]
    assert resumed.json()['items'][0]['media']['status'] == ('ready' if media_state == 'original' else media_state)
    assert db.query(MediaJob).count() == jobs_before
    assert login('alice').get(f'/api/v1/evaluations/automatic/stacks/{sid}/queue').status_code == 404
