"""P6 playback metrics (privacy-safe observability).

Counters record playback traffic shape and outcomes ONLY: request counts,
authorize outcomes, source selection (B2 vs legacy fallback), latencies,
provider failures, and Range/streaming outcomes. Session tokens, cookies,
presigned URLs, signatures, passwords, and raw identifiers are NEVER
recorded here (see SECURITY_V1 §27).

The registry is in-process (per uvicorn worker); the /metrics endpoint
sums nothing across workers — it reports this worker's live view. It is
sufficient for the owner-cohort observation window and introduces no new
scrape infrastructure.
"""

import threading
import time


class _Counter:
    __slots__ = ("_value", "_lock")

    def __init__(self) -> None:
        self._value = 0
        self._lock = threading.Lock()

    def inc(self, amount: int = 1) -> None:
        with self._lock:
            self._value += amount

    @property
    def value(self) -> int:
        with self._lock:
            return self._value


class _LatencyMs:
    __slots__ = ("_count", "_total_ms", "_max_ms", "_lock")

    def __init__(self) -> None:
        self._count = 0
        self._total_ms = 0.0
        self._max_ms = 0.0
        self._lock = threading.Lock()

    def observe(self, ms: float) -> None:
        with self._lock:
            self._count += 1
            self._total_ms += ms
            self._max_ms = max(self._max_ms, ms)

    def snapshot(self) -> dict:
        with self._lock:
            count = self._count
            avg = (self._total_ms / count) if count else 0.0
            return {"count": count, "avg_ms": round(avg, 1), "max_ms": round(self._max_ms, 1)}


class PlaybackMetrics:
    def __init__(self) -> None:
        self.requests_total = _Counter()
        self.authorized = _Counter()
        self.denied = _Counter()
        self.b2_selected = _Counter()
        self.legacy_fallback_selected = _Counter()
        self.provider_failures = _Counter()
        self.legacy_fallback_failures = _Counter()
        self.range_successes = _Counter()
        self.grant_refreshes = _Counter()
        self.storage_lookup_latency = _LatencyMs()
        self.presign_latency = _LatencyMs()

    def snapshot(self) -> dict:
        return {
            "playback_requests_total": self.requests_total.value,
            "authorized": self.authorized.value,
            "denied": self.denied.value,
            "b2_selected": self.b2_selected.value,
            "legacy_fallback_selected": self.legacy_fallback_selected.value,
            "provider_failures": self.provider_failures.value,
            "legacy_fallback_failures": self.legacy_fallback_failures.value,
            "range_successes": self.range_successes.value,
            "grant_refreshes": self.grant_refreshes.value,
            "storage_lookup_latency_ms": self.storage_lookup_latency.snapshot(),
            "presign_latency_ms": self.presign_latency.snapshot(),
        }


_METRICS = PlaybackMetrics()


def get_playback_metrics() -> PlaybackMetrics:
    return _METRICS


def now_ms() -> float:
    return time.perf_counter() * 1000.0
