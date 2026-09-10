"""P8 auth operational metrics (packet §25), privacy-safe in-process counters.

Mirrors playback_metrics.py: counters record outcome shapes only — never a
password, raw session token, cookie, presigned URL or signature. The
approximate active-session count is computed live by the /auth/metrics
endpoint (DB query), not cached here.
"""

import threading


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


class AuthMetrics:
    def __init__(self) -> None:
        self.login_success = _Counter()
        self.login_failure = _Counter()
        self.login_rate_limited = _Counter()
        self.session_revocations = _Counter()

    def snapshot(self) -> dict:
        return {
            "login_success": self.login_success.value,
            "login_failure": self.login_failure.value,
            "login_rate_limited": self.login_rate_limited.value,
            "session_revocations": self.session_revocations.value,
        }


_METRICS = AuthMetrics()


def get_auth_metrics() -> AuthMetrics:
    return _METRICS
