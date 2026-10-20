"""Queue draining must not impose an idle interval on waiting user media."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import src.media_jobs as jobs


@pytest.mark.parametrize("outcome", [0, RuntimeError("offline")])
def test_idle_or_failed_poll_waits_instead_of_spinning(monkeypatch, outcome):
    async def exercise():
        stop = asyncio.Event()
        calls = 0

        async def process():
            nonlocal calls
            calls += 1
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        monkeypatch.setattr(jobs, "MediaJobProcessor", lambda *_: SimpleNamespace(process_once=process))
        config = SimpleNamespace(media=SimpleNamespace(enabled=True, interval_seconds=60, max_jobs=1))
        task = asyncio.create_task(jobs.run_media_job_loop(config, None, stop))
        await asyncio.sleep(0.01)
        assert calls == 1
        stop.set()
        await asyncio.wait_for(task, 1)

    asyncio.run(exercise())


def test_available_batches_drain_before_idle_wait(monkeypatch):
    async def exercise():
        stop = asyncio.Event()
        process = AsyncMock(side_effect=[1, 2, 0])
        monkeypatch.setattr(jobs, "MediaJobProcessor", lambda *_: SimpleNamespace(process_once=process))
        config = SimpleNamespace(media=SimpleNamespace(enabled=True, interval_seconds=60, max_jobs=1))
        task = asyncio.create_task(jobs.run_media_job_loop(config, None, stop))
        await asyncio.sleep(0.01)
        assert process.await_count == 3
        stop.set()
        await asyncio.wait_for(task, 1)

    asyncio.run(exercise())
