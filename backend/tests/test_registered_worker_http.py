"""Registered package keys must traverse both HTTP guards without admin access."""
import hashlib

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.models.media import MediaAgent
from app.security import verify_api_key, verify_media_worker_key
from app.services.media_agents import authenticate_media_agent
from app.services.write_guard import require_owner_for_mutation


def test_registered_key_http_scope_and_revocation(test_db, monkeypatch):
    import app.security as security
    import app.services.write_guard as guard
    from types import SimpleNamespace
    settings = SimpleNamespace(user_auth_enabled=True, configured_api_keys=['legacy-key'], auth_cookie_name='session')
    monkeypatch.setattr(security, 'get_settings', lambda: settings)
    monkeypatch.setattr(guard, 'get_settings', lambda: settings)
    monkeypatch.setattr(guard.sessions, 'resolve_session', lambda *a: None)
    key = 'private-package-worker-key'
    agent = MediaAgent(id='worker', hostname='test', api_key_sha256=hashlib.sha256(key.encode()).hexdigest(), active=True, leasing_enabled=True, capabilities=['web_package'])
    test_db.add(agent)
    test_db.commit()
    app = FastAPI(dependencies=[Depends(require_owner_for_mutation)])
    app.dependency_overrides[get_db] = lambda: test_db

    @app.post('/api/v1/media/jobs/lease')
    def lease(payload: dict, auth=Depends(verify_media_worker_key)):
        try:
            authenticate_media_agent(test_db, payload['agent_id'], auth['key'])
        except PermissionError:
            from fastapi import HTTPException
            raise HTTPException(403)
        return {'ok': True}

    @app.post('/api/v1/media/cache/cleanup')
    def admin(auth=Depends(verify_api_key)):
        return {'ok': True}

    with TestClient(app) as client:
        headers = {'X-API-Key': key}
        assert client.post('/api/v1/media/jobs/lease', headers=headers, json={'agent_id':'worker'}).status_code == 200
        assert client.post('/api/v1/media/jobs/lease', headers=headers, json={'agent_id':'other'}).status_code == 403
        assert client.post('/api/v1/media/cache/cleanup', headers=headers).status_code == 401
        assert client.post('/api/v1/media/jobs/lease', headers={'X-API-Key':'wrong'}, json={'agent_id':'worker'}).status_code == 401
        agent.active = False
        test_db.commit()
        assert client.post('/api/v1/media/jobs/lease', headers=headers, json={'agent_id':'worker'}).status_code == 401


def test_real_heartbeat_accepts_registered_key(api_client, test_db, monkeypatch):
    from types import SimpleNamespace
    import app.security as security
    import app.services.write_guard as guard
    import app.api.v1.media as media
    settings = SimpleNamespace(user_auth_enabled=True, configured_api_keys=['legacy-key'], auth_cookie_name='session')
    monkeypatch.setattr(security, 'get_settings', lambda: settings)
    monkeypatch.setattr(guard, 'get_settings', lambda: settings)
    monkeypatch.setattr(guard.sessions, 'resolve_session', lambda *a: None)
    monkeypatch.setattr(media, '_advance_background_media_work', lambda db: db.commit())
    key = 'registered-http-worker'
    test_db.add(MediaAgent(id='worker', hostname='old', api_key_sha256=hashlib.sha256(key.encode()).hexdigest(), active=True, leasing_enabled=True, capabilities=['web_package']))
    test_db.commit()
    response = api_client.post('/api/v1/media/agents/heartbeat', headers={'X-API-Key':key}, json={'agent_id':'worker', 'hostname':'new', 'capabilities':['web_package'], 'photos_access_status':'library_unavailable'})
    assert response.status_code == 200, response.text
    test_db.expire_all()
    assert test_db.get(MediaAgent, 'worker').hostname == 'new'
    assert test_db.get(MediaAgent, 'worker').last_seen_at is not None
