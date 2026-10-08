"""HUD preferences and current photo identity across real session APIs."""
from io import BytesIO
from PIL import Image
from tests.test_member_dive_visibility import workspace


def _photo(color):
    output = BytesIO()
    Image.new('RGB', (320, 240), color).save(output, 'PNG')
    return output.getvalue()


def test_avatar_follows_identity_and_existing_interactions(workspace):
    _, login, dives, users, _ = workspace
    comment = login('alice').post(f"/api/v1/dives/{dives['bob-public']}/comments", json={'body': 'Nice entry'}).json()
    login('alice').put(f"/api/v1/dives/{dives['bob-public']}/like", json={'liked': True})
    photo = login('alice').put('/api/v1/users/me/avatar', content=_photo('teal')).json()
    assert login('alice').put('/api/v1/users/me/avatar-style', json={'avatar_hud': 'depth'}).status_code == 200

    def identities():
        return [
            login('alice').get('/api/v1/auth/me').json(),
            login('bob').get(f"/api/v1/users/{users['alice'].id}").json(),
            login('bob').get('/api/v1/users?q=alice').json()['items'][0],
            next(row for row in login('bob').get(f"/api/v1/dives/{dives['bob-public']}/comments").json()['items'] if row['id'] == comment['id']),
            next(row['actor'] for row in login('bob').get('/api/v1/users/me/activity?direction=received').json()['items'] if row['actor']['user_id'] == users['alice'].id),
        ]

    for identity in identities():
        assert identity['avatar_url'] == photo['avatar_url']
        assert identity['avatar_hud'] == 'depth'
        assert 'avatar' not in identity
    replacement = login('alice').put('/api/v1/users/me/avatar', content=_photo('blue')).json()
    assert replacement['avatar_url'] != photo['avatar_url']
    for identity in identities():
        assert identity['avatar_url'] == replacement['avatar_url']
    assert login('alice').delete('/api/v1/users/me/avatar').status_code == 204
    for identity in identities():
        assert identity['avatar_url'] is None
        assert identity['avatar_hud'] == 'depth'
    assert login('bob').get(photo['avatar_url']).status_code == 404


def test_style_is_self_only_validated_and_origin_protected(workspace):
    _, login, _, users, _ = workspace
    alice = login('alice')
    for style in ('orbit', 'reticle', 'depth'):
        result = alice.put('/api/v1/users/me/avatar-style', json={'avatar_hud': style})
        assert result.status_code == 200
        assert result.json()['avatar_hud'] == style
    assert login('bob').get(f"/api/v1/users/{users['bob'].id}").json()['avatar_hud'] == 'reticle'
    for body in ({'avatar_hud': 'unknown'}, {'avatar_hud': 'orbit', 'user_id': users['bob'].id}):
        assert alice.put('/api/v1/users/me/avatar-style', json=body).status_code == 422
    assert alice.put('/api/v1/users/me/avatar-style', json={'avatar_hud': 'orbit'}, headers={'Origin': 'https://evil.test'}).status_code == 403
    alice.cookies.clear()
    assert alice.put('/api/v1/users/me/avatar-style', json={'avatar_hud': 'orbit'}).status_code == 401
