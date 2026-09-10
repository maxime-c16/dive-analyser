"""P9 §41 durable operational-metric aggregation (smallest viable).

The P6/P8 in-process counters (auth_metrics, playback_metrics) are
per-worker and lost on restart. The DURABLE sources of the same facts
already exist as append-only rows:

    login success/failure  -> login_attempts (success flag, per attempt)
    playback outcomes      -> media_playback_grants (outcome, denial_reason)
    security events        -> security_audit_log (event_type)

This module derives privacy-safe aggregates over a bounded window from
those tables ONLY — no new analytics system, no counters to maintain, no
raw identifiers, tokens, URLs or caption content.
"""

import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.security_audit_log import SecurityAuditEvent
from app.models.user_auth import LoginAttempt, MediaPlaybackGrant


def durable_ops_snapshot(db: Session, window_hours: int = 24) -> dict:
    window_start = datetime.datetime.utcnow() - datetime.timedelta(hours=window_hours)

    def _login_count(success: bool) -> int:
        return int(
            db.query(func.count(LoginAttempt.id))
            .filter(LoginAttempt.success.is_(success), LoginAttempt.created_at >= window_start)
            .scalar()
            or 0
        )

    grants = (
        db.query(MediaPlaybackGrant.outcome, func.count(MediaPlaybackGrant.id))
        .filter(MediaPlaybackGrant.created_at >= window_start)
        .group_by(MediaPlaybackGrant.outcome)
        .all()
    )
    grant_counts = {outcome: int(n) for outcome, n in grants}

    events = (
        db.query(SecurityAuditEvent.event_type, func.count(SecurityAuditEvent.id))
        .filter(SecurityAuditEvent.created_at >= window_start)
        .group_by(SecurityAuditEvent.event_type)
        .all()
    )
    event_counts = {event_type: int(n) for event_type, n in events}

    return {
        "window_hours": window_hours,
        "login_attempts": {
            "success": _login_count(True),
            "failure": _login_count(False),
        },
        "playback_grants": {
            "allowed": grant_counts.get("ALLOWED", 0),
            "legacy_fallback": grant_counts.get("LEGACY_FALLBACK", 0),
            "provider_failure": grant_counts.get("PROVIDER_FAILURE", 0),
            "denied": grant_counts.get("DENIED", 0),
        },
        "security_events": event_counts,
    }
