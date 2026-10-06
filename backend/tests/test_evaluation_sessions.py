"""Real multi-account tests for evaluation ratings, sessions and history
(issue #67, ticket 2). Shares the workspace fixture with the #66 tests so
both tickets cover the same contracts.
"""
import re
import uuid
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import text

from pathlib import Path

from tests.test_member_dive_visibility import workspace


def _session(client):
    response = client.post('/api/v1/evaluations/sessions', json={'client_session_id': str(uuid.uuid4())})
    assert response.status_code == 200, response.text
    return response.json()['session_id']


def _first_client_id(db, session_id: int) -> str:
    from app.models.evaluation import EvaluationSession

    return db.query(EvaluationSession.client_session_id).filter(EvaluationSession.id == session_id).scalar()


def _queue(db, client, session_id: int, limit: int, batch_id: str | None = None):
    used = batch_id or str(uuid.uuid4())
    response = client.get(
        f'/api/v1/evaluations/sessions/{session_id}/queue',
        params={'limit': limit, 'batch_id': used},
    )
    response.used_batch_id = used
    return response


def _rate(client, request_id: int, half: int, comment=None):
    body = {'score_half_steps': half}
    if comment is not None:
        body['comment'] = comment
    return client.post(f'/api/v1/evaluations/{request_id}/ratings', json=body)


def _activate(alice, dive_id: int, prompt=None):
    body = {'active': True}
    if prompt is not None:
        body['prompt'] = prompt
    response = alice.put(f'/api/v1/dives/{dive_id}/evaluation-request', json=body)
    assert response.status_code == 200, response.text
    return response.json()['id']


def test_sessions_idempotent_expired_and_foreign(workspace):
    db, login, dives, users, _ = workspace
    from app.models.evaluation import EvaluationSession

    bob = login('bob')
    session_id = _session(bob)
    # Retrying the SAME client_session_id returns the same session.
    retry = login('bob').post('/api/v1/evaluations/sessions', json={'client_session_id': _first_client_id(db, session_id)})
    assert retry.status_code == 200 and retry.json()['session_id'] == session_id
    # A different client id is a deliberate NEW session (fresh queue, no carry-over).
    fresh = bob.post('/api/v1/evaluations/sessions', json={'client_session_id': str(uuid.uuid4())})
    assert fresh.status_code == 200 and fresh.json()['session_id'] != session_id
    # Foreign session: uniform 404 (decoyed with bob's own session id).
    assert login('alice').get(
        f'/api/v1/evaluations/sessions/{session_id}/queue', params={'batch_id': str(uuid.uuid4())}
    ).status_code == 404
    assert login('alice').post(
        f'/api/v1/evaluations/sessions/{session_id}/skip', json={'request_id': 1}
    ).status_code == 404
    # Guest.
    guest = login('bob')
    guest.cookies.clear()
    assert guest.post('/api/v1/evaluations/sessions', json={'client_session_id': str(uuid.uuid4())}).status_code == 401
    # Expiry: the owner hitting his expired session collapses with 410.
    row = db.query(EvaluationSession).filter_by(id=session_id).one()
    row.expires_at = datetime.utcnow() - timedelta(minutes=5)
    db.commit()
    bob2 = login('bob')
    assert _queue(db, bob2, session_id, 5).status_code == 410
    assert _queue(db, bob2, session_id, 5).json()['detail'] == 'SESSION_EXPIRED'


from datetime import timedelta  # noqa: E402


def _third_ready_request(db, client):
    """Third eligible request for alice with a ready 360p cache entry."""
    from app.config import get_settings
    from app.models.dive import Dive
    from app.models.diver import Diver
    from app.models.media import MediaCacheEntry
    from app.models.photos_asset import PhotosAsset
    from app.models.session import Session as TrainingSession

    diver_id = db.query(Diver.id).filter_by(display_name='alice').scalar()
    session_id_t = db.query(TrainingSession.id).order_by(TrainingSession.id).first()[0]
    dive = Dive(
        session_id=session_id_t, diver_id=diver_id, person_name='alice', dive_code='107C', performance='G',
        performance_numeric=3, height='3m', platform_type='springboard', dive_datetime=datetime.now(),
        visibility='private', video_uuid='alice-third-video',
    )
    db.add(dive)
    db.flush()
    asset = PhotosAsset(video_uuid='alice-third-video')
    db.add(asset)
    db.flush()
    dive.photos_asset_id = asset.id
    storage = get_settings().media_cache_root
    media_path = Path(storage) / 'alice-third-proxy.mp4'
    media_path.write_bytes(b'cached third video')
    db.add(MediaCacheEntry(
        photos_asset_id=asset.id, media_key='alice-third', rendition='proxy_360p',
        storage_path=str(media_path), size_bytes=17, content_type='video/mp4',
    ))
    db.commit()
    response = client.put(f'/api/v1/dives/{dive.id}/evaluation-request', json={'active': True})
    assert response.status_code == 200, response.text
    return response.json()['id']


def test_queue_basics_exclusions_order_and_batches(workspace):
    db, login, dives, users, _ = workspace
    from app.models.evaluation import EvaluationSessionRequest

    # One shared TestClient: re-login before every block that acts as a user.
    alice = login('alice')
    r_private = _activate(alice, dives['alice-private'])
    r_public = _activate(alice, dives['alice-public'])
    r_third = _third_ready_request(db, alice)
    bob = login('bob')
    assert _activate(bob, dives['bob-private'])  # own dive: never proposed to bob
    bob = login('bob')
    session_id = _session(bob)

    bob = login('bob')
    batch = _queue(db, bob, session_id, limit=2)
    assert batch.status_code == 200, batch.text
    payload = batch.json()
    ids = [item['request_id'] for item in payload['items']]
    assert len(ids) == 2
    assert r_private in ids and r_public in ids
    first = payload['items'][0]
    # Frozen media contract + no personal payload.
    assert set(first.keys()) == {'request_id', 'dive_id', 'prompt', 'dive', 'media'}
    assert set(first['dive'].keys()) == {'id', 'video_uuid', 'dive_code', 'height', 'platform_type', 'owner_display_name'}
    assert set(first['media'].keys()) == {'status', 'poster_url', 'playback_url'}
    assert 'notes' not in first['dive'] and 'performance' not in first['dive']
    assert first['dive']['owner_display_name'] == 'alice'
    assert isinstance(payload['has_more'], bool)
    assert payload['batch_id'] == batch.used_batch_id

    # Vote on the first item: the next batch excludes it and the queue stays ordered.
    bob = login('bob')
    first_request = ids[0]
    assert _rate(bob, first_request, 15).status_code == 200
    bob = login('bob')
    second = _queue(db, bob, session_id, limit=5)
    second_ids = [item['request_id'] for item in second.json()['items']]
    assert first_request not in second_ids  # voted: only leaves via its own batch retry
    # The not-voted items of batch 1 stay in their batch (not duplicated here);
    # the third request becomes the single new proposal.
    assert second_ids == [r_third]

    # Deterministic batch retry: reuse the exact first batch id.
    bob = login('bob')
    rows = db.query(EvaluationSessionRequest).filter_by(session_id=session_id, batch_id=payload['batch_id']).all()
    retried = _queue(db, bob, session_id, limit=2, batch_id=payload['batch_id'])
    assert retried.status_code == 200
    per_request = {item['request_id']: item for item in retried.json()['items']}
    # The voted request is flagged unavailable without any media URL.
    voted = per_request.get(first_request)
    assert voted is not None and voted['unavailable'] is True
    assert 'media' not in voted and 'dive' not in voted
    # The still-eligible one keeps its URLs in the retry.
    other = per_request.get(list({r_private, r_public} - {first_request})[0])
    assert other is not None and other.get('unavailable') is False and other['media']['playback_url']


def test_queue_never_presents_unready_media_and_bounds(workspace):
    db, login, dives, users, _ = workspace
    from app.config import get_settings
    from app.models.dive import Dive
    from app.models.diver import Diver
    from app.models.photos_asset import PhotosAsset
    from app.models.session import Session as TrainingSession
    from sqlalchemy.orm import sessionmaker

    settings = get_settings()
    diver_id = db.query(Diver.id).filter_by(display_name='alice').scalar()
    session_id_t = db.query(TrainingSession.id).order_by(TrainingSession.id).first()[0]
    dive = Dive(
        session_id=session_id_t, diver_id=diver_id, person_name='alice', dive_code='105B', performance='G',
        performance_numeric=3, height='3m', platform_type='springboard', dive_datetime=datetime.now(),
        visibility='private', video_uuid='alice-norender-video',
    )
    db.add(dive)
    db.flush()
    asset = PhotosAsset(video_uuid='alice-norender-video')
    db.add(asset)
    db.flush()
    dive.photos_asset_id = asset.id
    db.commit()
    client = login('alice')
    wait_request_id = client.put(f'/api/v1/dives/{dive.id}/evaluation-request', json={'active': True}).json()['id']
    session_id = _session(login('bob'))
    for _ in range(2):
        batch = _queue(db, login('bob'), session_id, limit=5)
        assert all(item['request_id'] != wait_request_id for item in batch.json()['items'])
    assert _queue(db, login('bob'), session_id, limit=0).status_code == 422
    assert _queue(db, login('bob'), session_id, limit=21).status_code == 422


def test_ratings_validation_and_immutable_votes(workspace):
    db, login, dives, users, _ = workspace
    from app.models.evaluation import EvaluationRating

    alice = login('alice')
    request_id = _activate(alice, dives['alice-private'], prompt='Judge the entry')
    bob = login('bob')
    bob.post('/api/v1/evaluations/sessions', json={'client_session_id': str(uuid.uuid4())})
    bob = login('bob')
    assert _rate(bob, request_id, -1).status_code == 422
    assert _rate(bob, request_id, 21).status_code == 422
    assert _rate(bob, request_id, 5, 'x' * 2001).status_code == 422
    # 0, 0.5 (=1) and 10 (=20) are legal.
    ok = _rate(bob, request_id, 0)
    assert ok.status_code == 200, ok.text
    assert ok.json()['rating']['score_half_steps'] == 0
    results = ok.json()['results']
    assert results['rating_count'] == 1 and results['mean_score'] == 0.0
    assert results['my_rating']['score_half_steps'] == 0
    assert results['ratings'][0]['author'] == 'bob'
    # Same-content retry: idempotent, no second row.
    retry = _rate(bob, request_id, 0)
    assert retry.status_code == 200 and retry.json()['rating']['id'] == ok.json()['rating']['id']
    # Different content after confirmation: stable rejection code.
    conflict = _rate(bob, request_id, 10)
    assert conflict.status_code == 409
    assert 'immutable' in conflict.json()['detail']
    assert db.query(EvaluationRating).filter_by(request_id=request_id).count() == 1
    # One final row with the stored content.
    vote = db.query(EvaluationRating).filter_by(request_id=request_id).one()
    assert vote.comment is None and vote.created_at is not None


def test_results_visibility_countries_scores_untouched(workspace):
    db, login, dives, users, _ = workspace
    alice, bob, viewer = login('alice'), login('bob'), login('viewer')
    from app.models.evaluation import EvaluationRating
    from app.models.judge_score import JudgeScore
    from app.models.user_auth import AppUser
    from app.services.sessions import create_session
    from app.config import get_settings

    request_id = _activate(login('alice'), dives['alice-private'])
    before = login('alice').get(f"/api/v1/dives/{dives['alice-private']}").json()
    assert login('bob').post(f'/api/v1/evaluations/{request_id}/ratings', json={'score_half_steps': 9, 'comment': 'Great entry'}).status_code == 200
    assert login('viewer').post(f'/api/v1/evaluations/{request_id}/ratings', json={'score_half_steps': 19, 'comment': 'So close'}).status_code == 200
    payload = login('alice').get(f'/api/v1/evaluations/{request_id}/results').json()
    assert payload['rating_count'] == 2
    assert payload['mean_score'] == round((9 + 19) / 2 / 2, 1)
    assert payload['my_rating'] is None
    assert {row['author'] for row in payload['ratings']} == {'bob', 'viewer'}
    # An evaluator with their own vote sees the panel afterwards.
    voter = login('bob').get(f'/api/v1/evaluations/{request_id}/results')
    assert voter.status_code == 200
    assert voter.json()['my_rating']['comment'] == 'Great entry'
    # A member without a vote gets a uniform 404.
    db.add(AppUser(email='carol@example.test', display_name='carol', role='friend'))
    db.commit()
    carol_user_id = db.query(AppUser.id).filter_by(email='carol@example.test').scalar()
    carol = login('bob')
    carol.cookies.clear()
    carol.cookies.set(get_settings().auth_cookie_name, create_session(db, user_id=carol_user_id, ttl_seconds=3600)[0])
    assert carol.get(f'/api/v1/evaluations/{request_id}/results').status_code == 404
    # Guests.
    guest = login('bob')
    guest.cookies.clear()
    assert guest.get(f'/api/v1/evaluations/{request_id}/results').status_code == 401
    assert guest.post(f'/api/v1/evaluations/{request_id}/ratings', json={'score_half_steps': 10}).status_code == 401
    # Votes never modify the dive's personal fields or official panels.
    after = login('alice').get(f"/api/v1/dives/{dives['alice-private']}").json()
    assert after['performance'] == before['performance']
    assert after['performance_numeric'] == before['performance_numeric']
    assert after['notes'] == before['notes']
    assert db.query(JudgeScore).count() == 0
    # Vote on the dive of another USER who owns it directly (self-eval).
    from app.models.evaluation import EvaluationRequest
    request_row = db.query(EvaluationRequest).filter_by(id=request_id).one()
    assert request_row is not None
    alice = login('alice')
    own = alice.put(
        f'/api/v1/dives/{dives["alice-public"]}/evaluation-request', json={'active': True}
    )
    assert own.status_code == 200
    own_request_id = own.json()['id']
    self_vote = _rate(alice, own_request_id, 10)
    assert self_vote.status_code == 403
    assert 'own dive' in self_vote.json()['detail']


def test_vote_after_deactivation_retry_and_closure(workspace):
    db, login, dives, users, _ = workspace
    from app.models.evaluation import EvaluationRequest, EvaluationRating
    from sqlalchemy.orm import sessionmaker

    alice = login('alice')
    request_id = _activate(alice, dives['alice-private'], prompt='Entry focus')
    submitted = login('bob').post(f'/api/v1/evaluations/{request_id}/ratings', json={'score_half_steps': 8, 'comment': 'Solid'})
    assert submitted.status_code == 200
    stored = submitted.json()['rating']
    # Deactivate AFTER the vote: identical retry succeeds; new-vote 409.
    assert login('alice').put(f'/api/v1/dives/{dives["alice-private"]}/evaluation-request', json={'active': False}).status_code == 200
    bob = login('bob')
    retry = bob.post(f'/api/v1/evaluations/{request_id}/ratings', json={'score_half_steps': 8, 'comment': 'Solid'})
    assert retry.status_code == 200, retry.text
    assert retry.json()['rating']['id'] == stored['id']
    assert retry.json()['rating']['created_at'] == stored['created_at']
    closed = login('bob').post(f'/api/v1/evaluations/{request_id}/ratings', json={'score_half_steps': 12})
    assert closed.status_code == 409
    # Results remain readable for owner and voter while suspended.
    assert login('alice').get(f'/api/v1/evaluations/{request_id}/results').status_code == 200
    assert login('bob').get(f'/api/v1/evaluations/{request_id}/results').status_code == 200
    # Deletion cascades the request and votes away; direct calls hit 404.
    alice = login('alice')
    second_id = _activate(alice, dives['alice-public'])
    assert login('bob').post(f'/api/v1/evaluations/{second_id}/ratings', json={'score_half_steps': 10}).status_code == 200
    request_row = db.query(EvaluationRequest).filter_by(id=second_id).one()
    dive_id = request_row.dive_id
    db.execute(text('PRAGMA foreign_keys=ON'))
    login('alice').delete(f'/api/v1/dives/{dive_id}')
    assert db.query(EvaluationRequest).filter_by(id=second_id).first() is None
    assert db.query(EvaluationRating).filter_by(request_id=second_id).count() == 0


def test_history_endpoints_and_aggregates(workspace):
    db, login, dives, users, _ = workspace
    alice = login('alice')
    r1 = _activate(alice, dives['alice-private'], prompt='Case A')
    r2 = _activate(alice, dives['alice-public'])
    assert login('bob').post(f'/api/v1/evaluations/{r1}/ratings', json={'score_half_steps': 5, 'comment': 'Solid'}).status_code == 200
    assert login('bob').post(f'/api/v1/evaluations/{r2}/ratings', json={'score_half_steps': 15}).status_code == 200
    assert login('alice').put(f'/api/v1/dives/{dives["alice-public"]}/evaluation-request', json={'active': False}).status_code == 200
    mine = login('alice').get('/api/v1/evaluations/mine')
    assert mine.status_code == 200, mine.text
    items = {row['request_id']: row for row in mine.json()['items']}
    assert set(items) == {r1, r2}
    assert items[r1]['active'] is True and items[r1]['rating_count'] == 1 and items[r1]['mean_score'] == 2.5
    assert items[r2]['active'] is False and items[r2]['rating_count'] == 1 and items[r2]['mean_score'] == 7.5
    assert items[r1]['dive']['dive_code'] == '101B'
    assert 'notes' not in items[r1]['dive']  # owner history carries no personal dive notes
    assert items[r1]['prompt'] == 'Case A'
    # Evaluator history: own votes frozen + aggregates, no media URL leaked.
    ratings = login('bob').get('/api/v1/evaluations/my-ratings')
    assert ratings.status_code == 200
    rated = {row['request_id']: row for row in ratings.json()['items']}
    assert set(rated) == {r1, r2}
    assert rated[r1]['score_half_steps'] == 5 and rated[r1]['comment'] == 'Solid'
    assert rated[r2]['rating_count'] == 1
    assert 'playback_url' not in ratings.text and 'poster_url' not in ratings.text


def test_queue_pagination_exhaustion_and_skip(workspace):
    db, login, dives, users, _ = workspace
    from app.models.evaluation import EvaluationSessionRequest

    bob = login('bob')
    assert _activate(bob, dives['bob-private'])  # own dive excluded
    login('alice').put(f'/api/v1/dives/{dives["alice-private"]}/evaluation-request', json={'active': True})
    login('alice').put(f'/api/v1/dives/{dives["alice-public"]}/evaluation-request', json={'active': True})
    bob = login('bob')
    session_id = _session(bob)
    first = _queue(db, bob, session_id, limit=1)
    items = first.json()['items']
    assert len(items) == 1
    target = items[0]['request_id']
    skipped = login('bob').post(f'/api/v1/evaluations/sessions/{session_id}/skip', json={'request_id': target})
    assert skipped.status_code == 200 and skipped.json()['state'] == 'skipped'
    repeat = bob.post(f'/api/v1/evaluations/sessions/{session_id}/skip', json={'request_id': target})
    assert repeat.status_code == 200 and repeat.json() == {'request_id': target, 'state': 'skipped'}
    assert bob.post(f'/api/v1/evaluations/sessions/{session_id}/skip', json={'request_id': 999999}).status_code == 404
    second = _queue(db, bob, session_id, limit=5)
    ids = [item['request_id'] for item in second.json()['items']]
    assert target not in ids
    # A fresh session re-includes the skipped request while it stays unrated.
    fresh = _session(login('bob'))
    rebatch = _queue(db, login('bob'), fresh, limit=5)
    assert target in [item['request_id'] for item in rebatch.json()['items']]
    rows = db.query(EvaluationSessionRequest).filter_by(session_id=session_id).all()
    assert {row.request_id for row in rows if row.state == 'skipped'} == {target}


def test_vote_scoping_and_media_after_golden_path(workspace):
    db, login, dives, users, _ = workspace
    alice = login('alice')
    request_id = _activate(alice, dives['alice-private'], prompt='Steady')
    bob = login('bob')
    session_id = _session(bob)
    batch = _queue(db, login('bob'), session_id, limit=1)
    item = batch.json()['items'][0]
    assert item['request_id'] == request_id and item['media']['status'] == 'ready'
    assert item['media']['playback_url'].startswith(f'/api/v1/evaluations/requests/{request_id}/media/')
    play = login('bob').get(item['media']['playback_url'])
    assert play.status_code == 200
    assert login('bob').post(f'/api/v1/evaluations/{request_id}/ratings', json={'score_half_steps': 6}).status_code == 200
    # The private dive never enters the evaluator's Library.
    library = login('bob').get('/api/v1/dives', params={'diver_scope': 'all'}).json()
    assert all(row['id'] != item['dive_id'] for row in library)
    # Active request → media transport still works for the evaluator.
    assert login('bob').get(item['media']['playback_url']).status_code == 200
    # Deactivation revokes it instantly.
    login('alice').put(f'/api/v1/dives/{item["dive_id"]}/evaluation-request', json={'active': False})
    assert login('bob').get(item['media']['playback_url']).status_code == 404


class TestEvaluationSessionsMigrationFile:
    """Static guard: additive, idempotent, and reversible SQL."""

    def test_migration_file(self):
        migration = Path(__file__).resolve().parents[1] / 'migrations' / 'add_evaluation_sessions.sql'
        assert migration.is_file()
        sql = migration.read_text()
        joined = '\n'.join(line.strip() for line in sql.splitlines() if line.strip() and not line.strip().startswith('--'))
        for forbidden in re.finditer(
            r'^\s*(ALTER\s+TABLE|DROP\s+COLUMN|UPDATE\s+|DELETE\s+FROM|INSERT\s+INTO|TRUNCATE)',
            joined, re.MULTILINE | re.IGNORECASE,
        ):
            raise AssertionError(f'non-additive statement found: {forbidden.group(0)!r}')
        assert joined.count('CREATE TABLE IF NOT EXISTS') == 3
        assert 'UNIQUE (request_id, evaluator_user_id)' in joined
        assert 'CREATE INDEX IF NOT EXISTS' in sql
        assert 'DROP TABLE IF EXISTS evaluation_ratings' in sql
