"""Slow synchronous snapshots must not stall unrelated HTTP requests."""
import asyncio
import threading

import httpx
from fastapi import FastAPI

from app.api.v1 import health
from app.database import get_db


def test_operations_snapshot_does_not_block_health(monkeypatch):
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def slow_snapshot(_db):
        started.set()
        release.wait(timeout=2)
        finished.set()
        return {"read_only": True}

    monkeypatch.setattr(health, "build_operations_status", slow_snapshot)
    app = FastAPI()
    app.include_router(health.router)
    app.dependency_overrides[get_db] = lambda: None

    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            snapshot = asyncio.create_task(client.get("/operations/status"))
            try:
                assert await asyncio.to_thread(started.wait, 1)
                response = await client.get("/health")
                assert response.status_code == 200
                assert not finished.is_set(), "Health waited for the blocking snapshot"
            finally:
                release.set()
                response = await snapshot
            assert response.status_code == 200
            assert response.json() == {"read_only": True}

    asyncio.run(check())
