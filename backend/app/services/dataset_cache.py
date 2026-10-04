"""Dataset revision + revision-keyed in-process result caches.

Analytics/Journey/milestone computations scan the whole dive history.
Their results only change when the dataset changes, so they cache against
a dataset revision instead of a wall-clock TTL alone:

    revision = (count, max(id), max(updated_at)) over all dives

- an APPENDED dive bumps count and max(id),
- an EDITED dive bumps max(updated_at) (ORM onupdate),
- a DELETED dive changes the count even when the newest row is untouched.

A small TTL stays in the key contract so writes that bypass ORM row
events (bulk scripts) cannot leave a result stale for long. Cache keys
always embed the revision, matching the audit rule that cache keys must
handle edits and deletions — never just "newest dive id".
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any, Callable, Hashable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.dive import Dive
from app.models.diver import Diver

_CACHE_MAX_ENTRIES = 256
_store: OrderedDict = OrderedDict()
_lock = threading.Lock()


def dive_dataset_revision(db: Session) -> tuple[int, int | None, Any]:
    """Cheap dataset revision stamp over the dives table."""
    row = db.execute(
        select(func.count(Dive.id), func.max(Dive.id), func.max(Dive.updated_at))
    ).one()
    return (int(row[0]), row[1], row[2])


def diver_dataset_revision(db: Session) -> tuple[int, int | None, Any]:
    """Revision stamp over the divers table.

    Self-scoped analytics depend on diver identity (the resolved primary
    diver), which lives in divers rows: switching the primary diver changes
    the result without touching dives. Keyed with the dives revision, this
    busts caches on diver edits/deletes too.
    """
    row = db.execute(
        select(func.count(Diver.id), func.max(Diver.id), func.max(Diver.updated_at))
    ).one()
    return (int(row[0]), row[1], row[2])


def revision_cached(
    key: tuple,
    compute: Callable[[], Any],
    *,
    db: Session,
    ttl_seconds: float,
) -> Any:
    """compute() once per (key, dataset revision), otherwise serve cached.

    Storage is bounded (LRU of _CACHE_MAX_ENTRIES) and process-local; a
    restart computes again, which is always safe.
    """
    revision = dive_dataset_revision(db)
    cache_key = (key, revision)
    now_monotonic = _monotonic()
    with _lock:
        cached = _store.get(cache_key)
        if cached is not None and now_monotonic < cached[0]:
            _store.move_to_end(cache_key)
            return cached[1]
        _store.pop(cache_key, None)

    value = compute()

    with _lock:
        _store[cache_key] = (now_monotonic + ttl_seconds, value)
        _store.move_to_end(cache_key)
        while len(_store) > (_CACHE_MAX_ENTRIES + 64):
            _store.popitem(last=False)

    # Occasional sweep of dead entries without growing unbounded.
    with _lock:
        if len(_store) > _CACHE_MAX_ENTRIES:
            _prune_expired(now_monotonic)
    return value


def _prune_expired(now_monotonic: float) -> None:
    for cache_key in list(_store.keys()):
        expiry, value = _store[cache_key]
        if now_monotonic >= expiry:
            _store.pop(cache_key)
    while len(_store) > _CACHE_MAX_ENTRIES:
        try:
            _store.popitem(last=False)
        except KeyError:  # pragma: no cover - emptied concurrently
            break


def reset_cache() -> None:
    """Test/ops helper: drop every cached revision entry."""
    with _lock:
        _store.clear()


def _monotonic() -> float:
    from time import monotonic as _monotonic_time

    return _monotonic_time()


def cache_key(*parts: Hashable) -> tuple:
    """Freeze heterogeneous endpoint inputs into one hashable key."""
    return tuple(parts)
