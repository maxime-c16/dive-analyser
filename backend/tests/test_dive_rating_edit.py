"""Owners edit a dive's rating as one note or as two phases."""
from tests.test_member_dive_visibility import workspace  # noqa: F401  (fixture)


def test_owner_sets_two_phases_and_composite_follows(workspace):
    db, as_user, dives, _users, _ = workspace
    response = as_user('alice').put(f"/api/v1/dives/{dives['alice-public']}", json={
        'phase1_performance': 'G', 'phase2_performance': 'M', 'performance': 'P', 'performance_numeric': 4,
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body['phase1_performance'], body['phase2_performance']) == ('G', 'M')
    # Composite is derived (min of the phases), never the client's value.
    assert (body['performance'], body['performance_numeric']) == ('M', 2)
    assert (body['phase1_numeric'], body['phase2_numeric']) == (3, 2)


def test_owner_returns_to_single_rating(workspace):
    _db, as_user, dives, _users, _ = workspace
    client = as_user('alice')
    url = f"/api/v1/dives/{dives['alice-public']}"
    assert client.put(url, json={'phase1_performance': 'G', 'phase2_performance': 'P'}).status_code == 200
    response = client.put(url, json={'phase1_performance': None, 'phase2_performance': None, 'performance': 'B'})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['phase1_performance'] is None and body['phase2_performance'] is None
    assert (body['performance'], body['performance_numeric']) == ('B', 1)


def test_rating_edits_are_validated(workspace):
    _db, as_user, dives, _users, _ = workspace
    client = as_user('alice')
    url = f"/api/v1/dives/{dives['alice-public']}"
    assert client.put(url, json={'phase1_performance': 'G'}).status_code == 422
    assert client.put(url, json={'phase1_performance': None, 'phase2_performance': None}).status_code == 422
    assert client.put(url, json={'performance': 'X'}).status_code == 422
    assert client.put(url, json={'performance': None}).status_code == 422
    # A stale client ordinal is corrected server-side.
    assert client.put(url, json={'performance': 'G', 'performance_numeric': 0}).json()['performance_numeric'] == 3


def test_other_members_cannot_edit_rating(workspace):
    _db, as_user, dives, _users, _ = workspace
    response = as_user('bob').put(f"/api/v1/dives/{dives['alice-public']}", json={'performance': 'F'})
    assert response.status_code in (403, 404)


def test_client_ordinal_alone_is_ignored(workspace):
    _db, as_user, dives, _users, _ = workspace
    response = as_user('alice').put(f"/api/v1/dives/{dives['alice-public']}", json={'performance_numeric': 99})
    assert response.status_code == 200, response.text
    # Fixture dive is rated G; its ordinal stays derived from the letter.
    assert (response.json()['performance'], response.json()['performance_numeric']) == ('G', 3)


def test_single_letter_cannot_override_a_two_phase_rating(workspace):
    _db, as_user, dives, _users, _ = workspace
    client = as_user('alice')
    url = f"/api/v1/dives/{dives['alice-public']}"
    assert client.put(url, json={'phase1_performance': 'G', 'phase2_performance': 'M'}).status_code == 200
    assert client.put(url, json={'performance': 'F'}).status_code == 422
    body = client.get(url).json()
    assert (body['performance'], body['phase1_performance'], body['phase2_performance']) == ('M', 'G', 'M')
