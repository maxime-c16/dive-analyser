import json
from fastapi.testclient import TestClient

from app.api.v1.updates import read_updates
from app.main import app
from tests.test_member_dive_visibility import workspace


def test_authenticated_updates_filter_admin_and_do_not_cache(workspace, monkeypatch, tmp_path):
    monkeypatch.setenv('MEDIA_CACHE_ROOT', str(tmp_path))
    notes = [dict(id='public', date='2026-10-05', title='Public', body='Public note', audience='all'),
             dict(id='operator', date='2026-10-05', title='Operator', body='Private note', audience='admin')]
    (tmp_path / 'release-notes.json').write_text(json.dumps(dict(schema=1, version='v1.2.3', frontend_sha='a' * 40, notes=notes)))
    _, login, _, _, _ = workspace
    with TestClient(app, base_url='https://testserver') as guest:
        assert guest.get('/api/v1/updates').status_code == 401
    response = login('alice').get('/api/v1/updates')
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'private, no-store'
    assert response.json()['version'] == 'v1.2.3'
    assert [note['id'] for note in response.json()['notes']] == ['public']
    assert len(read_updates(True)['notes']) == 2
    assert 'audience' not in response.json()['notes'][0]


def test_missing_corrupt_and_oversized_manifests_are_quiet(monkeypatch, tmp_path):
    monkeypatch.setenv('MEDIA_CACHE_ROOT', str(tmp_path))
    assert read_updates(False)['notes'] == []
    for raw in ['invalid', '[]', '{}', 'x' * 200_001]:
        (tmp_path / 'release-notes.json').write_text(raw)
        assert read_updates(True)['notes'] == []
