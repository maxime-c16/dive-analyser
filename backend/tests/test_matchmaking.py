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
    result = client.post(endpoint, json={'score_half_steps': 13, 'comment': ' good '})
    assert result.status_code == 200, result.text
    assert result.json()['results']['mean_score'] == 6.5
    assert client.post(endpoint, json={'score_half_steps': 13, 'comment': 'good'}).json()['rating']['id'] == result.json()['rating']['id']
    assert client.post(endpoint, json={'score_half_steps': 14}).status_code == 409
    assert client.post(endpoint, json={'score_half_steps': 21}).status_code == 422
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
    assert client.post(f'/api/v1/evaluations/automatic/{did}/ratings', json={'score_half_steps': 12}).status_code == 404
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
    assert client.post(path, json={'score_half_steps': 10}).status_code == 404
    client.cookies.clear()
    assert client.post(path, json={'score_half_steps': 10}).status_code == 401
