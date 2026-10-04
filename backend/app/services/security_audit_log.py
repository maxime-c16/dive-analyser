"""P8 security audit trail service (packet §26).

record_event() is the single writer used by the operator CLI, the auth
routes and the login limiter. Events carry NO credentials: passwords,
session tokens, cookies, presigned URLs and credential material are never
passed to this module. Metadata is a small non-secret JSON object.

Failure policy: audit writes must not take down the request path — a
broken audit sink logs the failure and continues. (The operator CLI runs
synchronously so the operator sees a failure immediately.)
"""

import json
import logging
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.models.security_audit_log import SecurityAuditEvent

logger = logging.getLogger(__name__)

# Event vocabulary (packet §26 + user_enabled).
EVENT_USER_CREATED = "user_created"
EVENT_USER_DISABLED = "user_disabled"
EVENT_USER_ENABLED = "user_enabled"
EVENT_PASSWORD_RESET = "password_reset"
EVENT_SESSION_REVOKED = "session_revoked"
EVENT_OWNERSHIP_GRANTED = "ownership_granted"
EVENT_OWNERSHIP_REVOKED = "ownership_revoked"
EVENT_LOGIN_RATE_LIMITED = "login_rate_limited"

# actor_context values.
ACTOR_OPERATOR_CLI = "operator-cli"
ACTOR_SYSTEM = "system"


def record_event(
    db: Session,
    event_type: str,
    *,
    actor_context: str = ACTOR_SYSTEM,
    actor_note: Optional[str] = None,
    target_user_id: Optional[int] = None,
    target_diver_id: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Append one audit event. No secrets in, no secrets stored."""
    row = SecurityAuditEvent(
        event_type=event_type,
        actor_context=actor_context,
        actor_note=(actor_note or "")[:120] or None,
        target_user_id=target_user_id,
        target_diver_id=target_diver_id,
        metadata_json=(
            json.dumps(metadata, separators=(",", ":"), default=str)[:2000]
            if metadata
            else None
        ),
    )
    db.add(row)
    db.commit()
