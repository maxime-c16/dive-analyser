"""Private technique routes disappear when account authentication is disabled."""
import re
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import technique_adjustments, technique_history
from app.database import get_db


@pytest.fixture()
def client(monkeypatch):
    app = FastAPI()
    app.include_router(technique_history.router)
    app.include_router(technique_adjustments.router)

    def unexpected_database():
        raise AssertionError('Disabled technique routes must not access the database')

    app.dependency_overrides[get_db] = unexpected_database
    monkeypatch.setattr(technique_history, 'get_settings',
                        lambda: SimpleNamespace(user_auth_enabled=False))
    with TestClient(app) as c:
        yield c


ROUTES = [(method, re.sub(r'\{[^}]+\}', '1', route.path))
          for router in (technique_history.router, technique_adjustments.router)
          for route in router.routes for method in sorted(route.methods)]


@pytest.mark.parametrize('method,path', ROUTES)
def test_disabled_routes_return_404_before_database_or_body_validation(client, method, path):
    response = client.request(method, path, json={} if method == 'POST' else None)
    assert response.status_code == 404
    assert response.json() == {'detail': 'Not found'}


@pytest.mark.parametrize('path,status', [('/technique-history/preferences', 401),
                                        ('/technique-history/contexts?code=103', 401),
                                        ('/technique-history/1/tracks', 403)])
def test_enabled_routes_still_enforce_session_ownership(client, monkeypatch, path, status):
    monkeypatch.setattr(technique_history, 'get_settings',
                        lambda: SimpleNamespace(user_auth_enabled=True))
    monkeypatch.setattr(technique_history, 'optional_session_user', lambda *a: None)
    client.app.dependency_overrides[get_db] = lambda: None
    assert client.get(path).status_code == status
