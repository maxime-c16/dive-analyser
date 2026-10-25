"""Per-worker, identifier-free request timing and bounded event-loop samples."""
import asyncio
from collections import deque
from contextvars import ContextVar
from functools import wraps
import logging
from threading import Lock
from time import perf_counter

request_timing = ContextVar("request_timing", default=None)
logger = logging.getLogger(__name__)


def timed_auth(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        started = perf_counter()
        try:
            return fn(*args, **kwargs)
        finally:
            timing = request_timing.get()
            if timing is not None:
                timing["auth"] += (perf_counter() - started) * 1000
    return wrapped


class LoopLag:
    def __init__(self):
        self._lock = Lock()
        self.samples = deque(maxlen=600)
        self.samples_total = 0
        self.over_100ms_total = 0
        self.max_ms = 0.0

    def snapshot(self):
        with self._lock:
            recent = list(self.samples)
            total = self.samples_total
            over_100ms = self.over_100ms_total
            lifetime_max = self.max_ms
        cutoff = perf_counter() - 60
        samples = sorted(lag for timestamp, lag in recent if timestamp >= cutoff)
        def percentile(q):
            return round(samples[min(len(samples) - 1, int((len(samples) - 1) * q))], 2) if samples else 0
        return {"samples_total": total,
                "over_100ms_total": over_100ms,
                "window_samples": len(samples), "window_seconds": 60,
                "p50_ms": percentile(.5), "p99_ms": percentile(.99),
                "max_ms": round(max(samples, default=0), 2),
                "lifetime_max_ms": round(lifetime_max, 2)}

    async def run(self):
        next_log = perf_counter() + 60
        while True:
            started = perf_counter()
            await asyncio.sleep(.1)
            lag = max(0, (perf_counter() - started - .1) * 1000)
            with self._lock:
                self.samples.append((perf_counter(), lag))
                self.samples_total += 1
                self.over_100ms_total += int(lag >= 100)
                self.max_ms = max(self.max_ms, lag)
            if lag >= 100:
                logger.warning("Event loop lag: %.1fms", lag)
            if perf_counter() >= next_log:
                logger.info("Event loop lag summary: %s", self.snapshot())
                next_log = perf_counter() + 60


loop_lag = LoopLag()
