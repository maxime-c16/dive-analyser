"""Best-effort Web Push fan-out for inbox notifications (PR3).

Every push mirrors an inbox row created by notification_service (create /
notify_owners_for_diver), so only types the recipient left enabled can ever
produce a push — a disabled type returns None / no row, and fan-out additionally
re-checks the preference per recipient before sending (anti-spam).

Delivery is best-effort and never breaks the caller:
- push is skipped entirely when VAPID is not fully configured (empty keys =
  gracefully disabled; inbox + prefs keep working);
- dead endpoints (push service 404/410) are pruned;
- every failure path rolls back before returning and never raises.

Privacy: endpoint URLs, p256dh/auth keys and payload bodies are secrets —
they are never written to logs. Log lines carry user ids and counts only.
Exception details (including SQLAlchemy statements that embed bound
parameters) are never logged — only the exception type name and counts.

Execution: fan-out is blocking (pywebpush uses requests). Request-path
callers must NOT call fanout_for_rows inline from async endpoints — they
create inbox rows synchronously via notification_service (defer_push=True)
then schedule notification_service.fanout_in_background via FastAPI
BackgroundTasks (sync tasks run in Starlette's threadpool) with a fresh
SessionLocal. All eligible recipients/devices are handled in bounded
chunks (MAX_PUSH_SENDS_PER_CHUNK sends, _PUSH_SEND_TIMEOUT_SECONDS per
send) — never an inline total cap that would starve later rows.
"""
import json
import logging
from typing import List, Sequence
from urllib.parse import urlparse

import requests
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.notification import Notification, PushSubscription

logger = logging.getLogger(__name__)

# Exact allowlist of public browser push services that may receive Web Push
# traffic from this server (SSRF protection: `endpoint` is otherwise an
# arbitrary URL that pywebpush would POST to from the backend network).
# Chrome/Edge/Android → fcm.googleapis.com, Firefox →
# updates.push.services.mozilla.com, Safari (macOS + iOS 16.4+) →
# web.push.apple.com. Any new browser push service must be added here
# explicitly after review — everything else is rejected at registration
# (422) and skipped silently at fan-out.
ALLOWED_PUSH_ENDPOINT_HOSTS = frozenset(
    {
        "fcm.googleapis.com",
        "updates.push.services.mozilla.com",
        "web.push.apple.com",
    }
)
MAX_PUSH_ENDPOINT_LENGTH = 2048

# Bound stored devices per user (oldest evicted on overflow at upsert time).
MAX_SUBSCRIPTIONS_PER_USER = 20
# Bound one DB/send chunk: subs are fetched per recipient with
# offset/limit pages of this size (each with _PUSH_SEND_TIMEOUT_SECONDS
# per send) until every eligible recipient/device has been handled.
# Previously MAX_PUSH_SENDS_PER_FANOUT capped the TOTAL sends per call,
# starving later inbox rows after the first recipients' devices — now it
# is a per-chunk bound, not a total cap (background threadpool work).
MAX_PUSH_SENDS_PER_CHUNK = 20
# Deprecated alias: the old total-cap name now means the per-chunk bound.
MAX_PUSH_SENDS_PER_FANOUT = MAX_PUSH_SENDS_PER_CHUNK
_PUSH_TTL_SECONDS = 86400

# Bound each outbound push POST so one slow push service cannot wedge the
# single uvicorn worker (requests takes seconds). Exceeding it skips the
# device without pruning — the next fan-out retries.
_PUSH_SEND_TIMEOUT_SECONDS = 10


class _NoRedirectSession(requests.Session):
    """requests session that never follows redirects.

    The fan-out allowlist validates the initial endpoint, but requests
    follows redirects by default — an allowlisted endpoint answering 3xx
    could bounce the POST to a private/local URL, bypassing the SSRF
    guard. pywebpush's webpush() exposes `timeout` and `requests_session`
    but no allow_redirects flag, so the session forces it off. A 3xx then
    surfaces as a plain failure (no prune, retried on the next fan-out).
    """

    def post(self, url, *args, **kwargs):
        kwargs["allow_redirects"] = False
        return super().post(url, *args, **kwargs)


try:
    from pywebpush import WebPushException
    from pywebpush import webpush as _pywebpush
except ImportError:  # pragma: no cover - deployed images always pin pywebpush
    WebPushException = None  # type: ignore[assignment]
    _pywebpush = None  # type: ignore[assignment]


class PushGone(Exception):
    """The push service reports the endpoint as dead (404/410): prune it."""


def is_allowed_push_endpoint(endpoint: str) -> bool:
    """True iff `endpoint` is a public browser push URL we may POST to.

    SSRF guard shared by registration (422) and fan-out (silent skip):
    https only, exact host allowlist, no userinfo, no non-443 port,
    max 2048 chars. Anything else (http, localhost, literal IPs,
    attacker domains, explicit ports) is rejected.
    """
    try:
        if not isinstance(endpoint, str):
            return False
        if not endpoint or len(endpoint) > MAX_PUSH_ENDPOINT_LENGTH:
            return False
        parsed = urlparse(endpoint)
        if parsed.scheme != "https":
            return False
        if parsed.username or parsed.password:
            return False
        host = (parsed.hostname or "").lower()
        if host not in ALLOWED_PUSH_ENDPOINT_HOSTS:
            return False
        try:
            port = parsed.port
        except ValueError:
            return False
        if port is not None and port != 443:
            return False
        return True
    except Exception:
        return False


def is_push_configured() -> bool:
    """True only when all three VAPID settings are present.

    Partial configuration (keys without subject, or vice versa) reads as
    disabled so the frontend never offers a broken opt-in.
    """
    settings = get_settings()
    return bool(
        settings.vapid_public_key.strip()
        and settings.vapid_private_key.strip()
        and settings.vapid_subject.strip()
    )


def push_url(dive_id) -> str:
    """Deep link carried in the push payload (mirrors Notifications.tsx)."""
    if dive_id is None:
        return "/notifications"
    try:
        return f"/dives?clip={int(dive_id)}"
    except (TypeError, ValueError):
        return "/notifications"


def _payload_for(row: Notification) -> str:
    # Task05 calendar alerts attach a prepared payload (generic preview for
    # private events, authorized calendar deep link); other rows unchanged.
    prepared = getattr(row, "_push_payload", None)
    if isinstance(prepared, dict):
        return json.dumps(prepared)
    return json.dumps(
        {
            "title": row.title or "Dive Analyser",
            "body": row.body or "",
            "url": f"/messages/{row.conversation_id}" if row.conversation_id else push_url(row.dive_id),
        }
    )


def _send_one(*, endpoint: str, p256dh: str, auth: str, payload: str) -> None:
    """Send one push; raises PushGone when the endpoint is dead.

    Transport failures other than gone-away are swallowed (best-effort).
    Never logs endpoint, keys or payload contents.
    Defense in depth: re-validates the allowlist so a row written before
    validation (or by hand) can never turn the server into an SSRF proxy,
    sends with redirects disabled (an allowlisted endpoint must not bounce
    the POST to a private URL), and bounds each send with a timeout so a
    slow push service cannot wedge the single uvicorn worker.
    """
    if not is_allowed_push_endpoint(endpoint):
        return
    if _pywebpush is None:
        return
    settings = get_settings()
    try:
        _pywebpush(
            subscription_info={
                "endpoint": endpoint,
                "keys": {"p256dh": p256dh, "auth": auth},
            },
            data=payload,
            vapid_private_key=settings.vapid_private_key,
            vapid_claims={"sub": settings.vapid_subject},
            ttl=_PUSH_TTL_SECONDS,
            timeout=_PUSH_SEND_TIMEOUT_SECONDS,
            requests_session=_NoRedirectSession(),
        )
    except requests.exceptions.Timeout:
        # Slow push service: skip this device (no prune, no send count).
        logger.warning("push send timed out")
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in (404, 410):
            raise PushGone(f"push endpoint gone (status {status})")
        # Anything else — WebPushException without a response (bad receipt,
        # VAPID rejection, network error) or a refused 3xx redirect from the
        # no-redirect session above: best-effort, keep the subscription.
        logger.warning("push send failed (status %s)", status)


def fanout_for_rows(db: Session, rows: Sequence[Notification]) -> int:
    """Push every row to its recipient's devices. Returns sends attempted.

    Never raises: any failure (including our own queries) rolls back and
    returns the count so far. Callers invoke this only after their own
    commit, so our rollback can never poison their session.

    Full fan-out in bounded chunks: every eligible recipient/device is
    handled (no total cap starving later rows); subs are fetched per
    recipient with offset/limit pages of MAX_PUSH_SENDS_PER_CHUNK ordered
    by id (deterministic), each send with _PUSH_SEND_TIMEOUT_SECONDS.
    Must run off the request event loop — via
    notification_service.fanout_in_background scheduled on FastAPI
    BackgroundTasks (Starlette runs sync background tasks in its
    threadpool) with a fresh SessionLocal.

    Logging: user ids and counts only. Never logs endpoints, keys,
    payloads, statements, parameters, or exception messages — only the
    exception type name (logger.error, never logger.exception, so no
    traceback with SQLAlchemy bound parameters reaches the logs).
    """
    if not rows:
        return 0
    if not is_push_configured():
        return 0
    # Late import: notification_service calls us after its commits, and we
    # re-check prefs here — a module-level import would be circular.
    from app.services.notification_service import is_enabled

    sent = 0
    dead_endpoints: List[str] = []
    try:
        for row in rows:
            try:
                # Belt and suspenders: rows only exist because the type was
                # enabled at creation, but a concurrent opt-out between the
                # inbox commit and this send must not push anyway.
                if not is_enabled(db, row.user_id, row.type):
                    continue
            except Exception as exc:
                # Type name only: the message could embed the SQL statement
                # plus bound parameters (i.e. endpoint URLs treated here
                # as secrets). No exc_info, no exception interpolation.
                logger.error(
                    "push pref re-check failed for user %s (%s)",
                    row.user_id,
                    type(exc).__name__,
                )
                try:
                    db.rollback()
                except Exception:
                    pass
                continue
            payload = _payload_for(row)
            offset = 0
            while True:
                try:
                    subs = (
                        db.query(PushSubscription)
                        .filter(PushSubscription.user_id == row.user_id)
                        .order_by(PushSubscription.id)
                        .offset(offset)
                        .limit(MAX_PUSH_SENDS_PER_CHUNK)
                        .all()
                    )
                except Exception as exc:
                    logger.error(
                        "push subscription fetch failed for user %s (%s)",
                        row.user_id,
                        type(exc).__name__,
                    )
                    try:
                        db.rollback()
                    except Exception:
                        pass
                    break
                if not subs:
                    break
                for sub in subs:
                    # Defense in depth: never POST to a non-allowlisted URL,
                    # even if a legacy/hand-written row slipped past registration
                    # validation. Silent skip (no log of the URL, no send count).
                    if not is_allowed_push_endpoint(sub.endpoint):
                        continue
                    try:
                        _send_one(
                            endpoint=sub.endpoint,
                            p256dh=sub.p256dh,
                            auth=sub.auth,
                            payload=payload,
                        )
                        sent += 1
                    except PushGone:
                        dead_endpoints.append(sub.endpoint)
                    except Exception:
                        # _send_one already swallows; this guards mocks/futures.
                        # User id only — never the endpoint or the error itself.
                        logger.warning("push send failed for user %s", row.user_id)
                if len(subs) < MAX_PUSH_SENDS_PER_CHUNK:
                    break
                offset += MAX_PUSH_SENDS_PER_CHUNK
        if dead_endpoints:
            try:
                db.query(PushSubscription).filter(
                    PushSubscription.endpoint.in_(dead_endpoints)
                ).delete(synchronize_session=False)
                db.commit()
            except Exception as exc:
                # Count + type only: the bound parameters of a failed
                # DELETE are the endpoint URLs themselves.
                logger.error(
                    "push prune failed (%d endpoints, %s)",
                    len(dead_endpoints),
                    type(exc).__name__,
                )
                try:
                    db.rollback()
                except Exception:
                    pass
    except Exception as exc:
        logger.error("push fan-out failed (%s)", type(exc).__name__)
        try:
            db.rollback()
        except Exception:
            pass
    return sent
