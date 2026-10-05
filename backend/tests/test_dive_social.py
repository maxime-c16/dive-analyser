"""Real sessions verify reactions/discussion cannot bypass dive privacy."""
from tests.test_member_dive_visibility import workspace


def test_likes_are_durable_idempotent_and_scoped(workspace):
    _, login, dives, _, _ = workspace
    url = f"/api/v1/dives/{dives['alice-public']}"
    client = login('bob')
    for _ in range(2):
        response = client.put(url + '/like', json={'liked': True})
        assert response.status_code == 200, response.text
        assert response.json()['like_count'] == 1
    assert login('alice').get(url + '/social').json()['liked'] is False
    assert login('bob').get(url + '/social').json()['liked'] is True
    assert client.put(url + '/like', json={'liked': False}).json()['like_count'] == 0
    private = f"/api/v1/dives/{dives['alice-private']}"
    for suffix in ('/social', '/comments'):
        assert client.get(private + suffix).status_code == 404
    assert client.put(private + '/like', json={'liked': True}).status_code == 404
    client.cookies.clear()
    assert client.get(url + '/social').status_code == 401


def test_comment_author_delete_validation_and_visibility_changes(workspace):
    _, login, dives, _, _ = workspace
    url = f"/api/v1/dives/{dives['alice-public']}"
    client = login('bob')
    for body in ('', '   ', 'x' * 2001):
        assert client.post(url + '/comments', json={'body': body}).status_code == 422
    response = client.post(url + '/comments', json={'body': '  Nice entry!  '})
    assert response.status_code == 201, response.text
    comment = response.json()
    assert comment['body'] == 'Nice entry!'
    assert comment['author'] == 'bob'
    assert login('alice').get(url + '/comments').json()['items'][0]['id'] == comment['id']
    assert client.delete(url + f"/comments/{comment['id']}").status_code == 403
    assert client.put(url, json={'visibility': 'private'}).status_code == 200
    assert login('bob').get(url + '/comments').status_code == 404
    assert client.delete(url + f"/comments/{comment['id']}").status_code == 404
    assert login('alice').put(url, json={'visibility': 'public'}).status_code == 200
    assert login('bob').delete(url + f"/comments/{comment['id']}").status_code == 204
    assert client.get(url + '/social').json()['comment_count'] == 0
    assert client.post(f"/api/v1/dives/{dives['alice-private']}/comments", json={'body': 'Hidden'}).status_code == 404


def test_comment_pagination_has_no_duplicates(workspace):
    from app.models.dive_social import DiveComment
    db, login, dives, users, _ = workspace
    dive_id = dives['alice-public']
    db.add_all([DiveComment(dive_id=dive_id, user_id=users['bob'].id, body=str(i)) for i in range(55)])
    db.commit()
    client = login('bob')
    first = client.get(f'/api/v1/dives/{dive_id}/comments').json()
    second = client.get(f'/api/v1/dives/{dive_id}/comments?before={first["next_before"]}').json()
    assert len(first['items']) == 50
    assert len(second['items']) == 5
    assert len({row['id'] for row in first['items'] + second['items']}) == 55
    assert second['next_before'] is None
