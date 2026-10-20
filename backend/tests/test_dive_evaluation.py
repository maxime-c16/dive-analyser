"""Player evaluation tab: one vote per member and dive, routed to one circuit."""
from tests.test_member_dive_visibility import workspace  # noqa: F401
from app.models.evaluation import EvaluationRating
from app.models.matchmaking import AutomaticRating


def tab(client, dive_id):
    return client.get(f'/api/v1/dives/{dive_id}/evaluation')


def vote(client, dive_id, score, comment=None):
    return client.post(f'/api/v1/dives/{dive_id}/evaluation/ratings',
                       json={'score_half_steps': score, **({'comment': comment} if comment else {})})


def test_public_dive_is_rateable_without_daily_selection(workspace):
    db, login, dives, _, _ = workspace
    did = dives['alice-public']
    bob = login('bob')
    state = tab(bob, did).json()
    assert state['state'] == 'open' and state['circuit'] == 'automatic'
    assert state['results'] is None and state['my_rating'] is None
    result = vote(bob, did, 13, ' clean entry ')
    assert result.status_code == 200, result.text
    assert result.json()['circuit'] == 'automatic'
    assert result.json()['results']['mean_score'] == 6.5
    assert db.query(AutomaticRating).count() == 1 and db.query(EvaluationRating).count() == 0
    rated = tab(bob, did).json()
    assert rated['state'] == 'rated' and rated['my_rating']['score_half_steps'] == 13
    assert vote(bob, did, 13, 'clean entry').status_code == 200  # idempotent retry
    assert vote(bob, did, 14).status_code == 409


def test_active_request_wins_and_carries_the_prompt(workspace):
    db, login, dives, _, _ = workspace
    did = dives['alice-public']
    assert login('alice').put(f'/api/v1/dives/{did}/evaluation-request',
                              json={'active': True, 'prompt': 'Watch the entry'}).status_code == 200
    bob = login('bob')
    state = tab(bob, did).json()
    assert state == {**state, 'state': 'open', 'circuit': 'request', 'prompt': 'Watch the entry'}
    result = vote(bob, did, 15)
    assert result.status_code == 200 and result.json()['circuit'] == 'request'
    assert db.query(EvaluationRating).count() == 1 and db.query(AutomaticRating).count() == 0
    assert tab(bob, did).json()['circuit'] == 'request'


def test_existing_vote_is_never_counted_twice(workspace):
    db, login, dives, _, _ = workspace
    did = dives['alice-public']
    bob = login('bob')
    assert vote(bob, did, 12).status_code == 200
    login('alice').put(f'/api/v1/dives/{did}/evaluation-request', json={'active': True})
    state = tab(login('bob'), did).json()
    assert state['state'] == 'rated' and state['circuit'] == 'automatic'
    assert vote(login('bob'), did, 16).status_code == 409
    assert db.query(EvaluationRating).count() == 0


def test_owner_sees_results_but_cannot_vote(workspace):
    _, login, dives, _, _ = workspace
    did = dives['alice-public']
    vote(login('bob'), did, 12)
    alice = login('alice')
    state = tab(alice, did).json()
    assert state['state'] == 'owner' and state['circuit'] == 'automatic'
    assert state['results']['rating_count'] == 1 and state['automatic_excluded'] is False
    assert vote(alice, did, 20).status_code == 403
    private = tab(alice, dives['alice-private']).json()
    assert private['state'] == 'owner' and private['circuit'] is None


def test_viewing_rights_bound_rating_rights(workspace):
    _, login, dives, _, _ = workspace
    bob = login('bob')
    # Private dive of another member: invisible, so no tab and no vote.
    assert tab(bob, dives['alice-private']).status_code == 404
    assert vote(bob, dives['alice-private'], 10).status_code == 404
    # Owner exclusion closes the public circuit; the dive stays watchable.
    did = dives['alice-public']
    assert login('alice').put(f'/api/v1/dives/{did}/automatic-review', json={'excluded': True}).status_code == 200
    bob = login('bob')
    assert tab(bob, did).json()['state'] == 'closed'
    assert vote(bob, did, 10).status_code == 409
    bob.cookies.clear()
    assert tab(bob, did).status_code == 401


def test_daily_selection_path_still_requires_assignment(workspace):
    _, login, dives, _, _ = workspace
    path = f'/api/v1/evaluations/automatic/{dives["alice-public"]}/ratings'
    assert login('viewer').post(path, json={'video_uuid': 'alice-public-video', 'score_half_steps': 10}).status_code == 404
