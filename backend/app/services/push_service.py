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
"""
import json
import logging
from typing import List, Sequence
from urllib.parse import urlparse

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

# Bound the per-send fan-out (one user cannot accumulate unbounded rows).
_PUSH_SUBSCRIPTION_LIMIT = 100
# Bound stored devices per user (oldest evicted on overflow at upsert time).
MAX_SUBSCRIPTIONS_PER_USER = 20
_PUSH_TTL_SECONDS = 86400

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
    return json.dumps(
        {
            "title": row.title or "Dive Analyser",
            "body": row.body or "",
            "url": push_url(row.dive_id),
        }
    )


def _send_one(*, endpoint: str, p256dh: str, auth: str, payload: str) -> None:
    """Send one push; raises PushGone when the endpoint is dead.

    Transport failures other than gone-away are swallowed (best-effort).
    Never logs endpoint, keys or payload contents.
    Defense in depth: re-validates the allowlist so a row written before
    validation (or by hand) can never turn the server into an SSRF proxy.
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
        )
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in (404, 410):
            raise PushGone(f"push endpoint gone (status {status})")
        # WebPushException without a response (bad receipt, VAPID rejection,
        # network error): best-effort, keep the subscription for next time.
        logger.warning("push send failed (status %s)", status)


def fanout_for_rows(db: Session, rows: Sequence[Notification]) -> int:
    """Push every row to its recipient's devices. Returns sends attempted.

    Never raises: any failure (including our own queries) rolls back and
    returns the count so far. Callers invoke this only after their own
    commit, so our rollback can never poison their session.
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
            except Exception:
                logger.exception(
                    "push pref re-check failed for user %s", row.user_id
                )
                try:
                    db.rollback()
                except Exception:
                    pass
                continue
            try:
                subs = (
                    db.query(PushSubscription)
                    .filter(PushSubscription.user_id == row.user_id)
                    .limit(_PUSH_SUBSCRIPTION_LIMIT)
                    .all()
                )
            except Exception:
                logger.exception(
                    "push subscription fetch failed for user %s", row.user_id
                )
                try:
                    db.rollback()
                except Exception:
                    pass
                continue
            payload = _payload_for(row)
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
                    logger.warning("push send failed for user %s", row.user_id)
        if dead_endpoints:
            try:
                db.query(PushSubscription).filter(
                    PushSubscription.endpoint.in_(dead_endpoints)
                ).delete(synchronize_session=False)
                db.commit()
            except Exception:
                logger.exception(
                    "push prune failed (%d endpoints)", len(dead_endpoints)
                )
                try:
                    db.rollback()
                except Exception:
                    pass
    except Exception:
        logger.exception("push fan-out failed")
        try:
            db.rollback()
        except Exception:
            pass
    return sent
