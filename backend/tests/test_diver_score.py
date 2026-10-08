from tests.test_member_dive_visibility import workspace  # noqa: F401
from app.models.dive_social import DiveLike
from app.models.evaluation import EvaluationRating, EvaluationRequest
from app.models.matchmaking import AutomaticRating


def test_diver_score_composite(workspace):
    db, login, dives, users, _ = workspace
    alice_public = dives['alice-public']
    bob_public = dives['bob-public']
    # Bob rates Alice's public dive (automatic, 14 half-steps = 7.0).
    db.add(AutomaticRating(dive_id=alice_public, evaluator_user_id=users['bob'].id,
        score_half_steps=14, dive_code='101B', height='3m', dive_name='alice', video_uuid='alice-public-video'))
    # Manual jury vote received on Alice's dive (16 half-steps = 8.0).
    req = EvaluationRequest(dive_id=alice_public, active=True, created_by_user_id=users['alice'].id)
    db.add(req)
    db.flush()
    db.add(EvaluationRating(request_id=req.id, evaluator_user_id=users['bob'].id,
        score_half_steps=16, dive_code='101B', height='3m', dive_name='alice'))
    # Alice judges Bob's dive (counts toward judging).
    db.add(AutomaticRating(dive_id=bob_public, evaluator_user_id=users['alice'].id,
        score_half_steps=12, dive_code='101B', height='3m', dive_name='bob', video_uuid='bob-public-video'))
    # Same dive judged manually too still counts once (SQL UNION dedupes).
    bob_req = EvaluationRequest(dive_id=bob_public, active=True, created_by_user_id=users['bob'].id)
    db.add(bob_req)
    db.flush()
    db.add(EvaluationRating(request_id=bob_req.id, evaluator_user_id=users['alice'].id,
        score_half_steps=10, dive_code='101B', height='3m', dive_name='bob'))
    # Community interaction: Bob likes Alice's dive.
    db.add(DiveLike(dive_id=alice_public, user_id=users['bob'].id))
    db.commit()

    body = login('alice').get('/api/v1/users/me/diver-score').json()
    # Received: (14 + 16) / 2 / 2 = 7.5 mean over 2 votes.
    assert body['performance']['mean_score'] == 7.5
    assert body['performance']['rating_count'] == 2
    # confidence 2/5 → 7.5 * 6 * 0.4 = 18.0
    assert body['performance']['points'] == 18.0
    assert body['judging']['evaluated_dives'] == 1
    assert body['judging']['points'] == 2.5
    assert body['community']['interactions'] == 1
    assert body['score'] == 21
    assert body['provisional'] is True

    # Self-votes never inflate the score.
    db.add(AutomaticRating(dive_id=alice_public, evaluator_user_id=users['alice'].id,
        score_half_steps=20, dive_code='101B', height='3m', dive_name='alice', video_uuid='alice-public-video'))
    db.commit()
    again = login('alice').get('/api/v1/users/me/diver-score').json()
    assert again['performance']['rating_count'] == 2


def test_diver_score_empty_account(workspace):
    db, login, dives, users, _ = workspace
    body = login('viewer').get('/api/v1/users/me/diver-score').json()
    assert body['score'] == 0
    assert body['provisional'] is True
    assert body['performance']['mean_score'] is None
