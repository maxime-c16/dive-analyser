from tests.test_member_dive_visibility import workspace
from app.models.user_auth import AppUser


def test_unicode_spans_trim_persist_and_survive_renaming(workspace):
    db, login, dives, users, _ = workspace
    url = f"/api/v1/dives/{dives['alice-public']}/comments"
    mention = dict(user_id=users['alice'].id, start=4, end=10)
    response = login('bob').post(url, json={'body': '  🌊 @alice well done!  ', 'mentions': [mention]})
    assert response.status_code == 201, response.text
    result = response.json()
    assert result['body'] == '🌊 @alice well done!'
    expected = [dict(mention, start=2, end=8)]
    assert result['mentions'] == expected
    db.query(AppUser).filter_by(id=users['alice'].id).update({'display_name': 'New name'})
    db.commit()
    assert login('bob').get(url).json()['items'][0]['mentions'] == expected
    liked = login('bob').put(url + f"/{result['id']}/like", json={'liked': True})
    assert liked.json()['mentions'] == expected


def test_mentions_reject_forged_inactive_overlapping_and_out_of_bounds(workspace):
    db, login, dives, users, _ = workspace
    url = f"/api/v1/dives/{dives['alice-public']}/comments"
    alice = users['alice'].id
    client = login('bob')
    for spans in ([dict(user_id=9999, start=0, end=6)],
                  [dict(user_id=alice, start=0, end=99)],
                  [dict(user_id=alice, start=0, end=5)],
                  [dict(user_id=alice, start=0, end=6)] * 2,
                  [dict(user_id=alice, start=0, end=6)] * 11):
        assert client.post(url, json={'body': '@alice', 'mentions': spans}).status_code == 422
    db.query(AppUser).filter_by(id=alice).update({'is_active': False})
    db.commit()
    assert client.post(url, json={'body': '@alice', 'mentions': [dict(user_id=alice, start=0, end=6)]}).status_code == 422
    assert client.get(url).json()['items'] == []


def test_handle_mentions_plain_text_and_visibility(workspace):
    db, login, dives, users, _ = workspace
    alice = users['alice'].id
    db.query(AppUser).filter_by(id=alice).update({'handle': 'alice_dives'})
    db.commit()
    url = f"/api/v1/dives/{dives['alice-public']}/comments"
    client = login('bob')
    response = client.post(url, json={'body': '@alice_dives', 'mentions': [dict(user_id=alice, start=0, end=12)]})
    assert response.status_code == 201
    plain = client.post(url, json={'body': '@alice_dives'})
    assert plain.json()['mentions'] == []
    private = f"/api/v1/dives/{dives['alice-private']}/comments"
    assert client.post(private, json={'body': '@alice', 'mentions': [dict(user_id=alice, start=0, end=6)]}).status_code == 404


def test_guest_can_comment_but_cannot_submit_structured_mentions(workspace):
    from fastapi.testclient import TestClient
    from app.main import app
    from tests.test_dive_sharing import issue, enter
    _, login, dives, users, _ = workspace
    base, token = issue(login, dives['alice-public'])
    with TestClient(app, base_url='https://testserver') as guest:
        enter(guest, base, token)
        rejected = guest.post(base + '/comments', json={
            'body': '@alice', 'mentions': [dict(user_id=users['alice'].id, start=0, end=6)]})
        assert rejected.status_code == 403
        plain = guest.post(base + '/comments', json={'body': '@alice nice dive'})
        assert plain.status_code == 201, plain.text
        assert plain.json()['mentions'] == []
        assert len(guest.get(base + '/comments').json()['items']) == 1
