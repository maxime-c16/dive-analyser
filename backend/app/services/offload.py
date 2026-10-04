"""Cancellation-safe offloading of blocking work.

Handlers offload blocking work (full-file hashing, provider HEAD calls,
promotion moves) to worker threads. When the awaiting handler is
cancelled (client disconnect, timeout), the worker must still finish its
work — and if it uses the request database session, the session teardown
behind get_db must not race it. `run_to_completion` wraps that contract:
the coroutine always completes before the awaiter observes cancellation.
Handlers therefore only return/raise AFTER the offloaded unit (including
any db.commit() inside it) has fully finished.
"""

from __future__ import annotations

import asyncio

__all__ = ["run_to_completion"]


async def run_to_completion(awaitable):
    """Await `awaitable`, never abandoning it on cancellation.

    Cancellation of the surrounding handler does not propagate "through"
    the wrapped awaitable: this helper waits for it to finish and then
    re-raises CancelledError, so task teardown (and, for handlers, the
    get_db dependency teardown) happens strictly after the work done.
    """
    task = asyncio.ensure_future(awaitable)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise
