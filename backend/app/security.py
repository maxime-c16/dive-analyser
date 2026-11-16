"""API key authentication and security utilities."""

import hashlib
import hmac
import re
from typing import Optional

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.database import get_db


async def verify_api_key(x_api_key: Optional[str] = Header(None)) -> dict:
    """Validate the machine API key from the X-API-Key header."""
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required in X-API-Key header",
        )

    configured_keys = get_settings().configured_api_keys
    if not configured_keys:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key authentication is not configured",
        )

    if not any(hmac.compare_digest(x_api_key, key) for key in configured_keys):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    return {
        "key": x_api_key,
        "agent_name": "configured-machine-client",
        "is_active": True,
    }


def create_test_api_key(db=None, agent_name: str = "test-agent") -> str:
    """Return a deterministic test key for older tests."""
    return "test-api-key-" + agent_name


_MEDIA_WORKER_PATH = re.compile(
    r"/api/v1/media/(?:agents/(?:heartbeat|sources/report)|jobs/(?:lease|[0-9]+/(?:heartbeat|fail|upload|finalize|package/slots))|catalog/runs/(?:lease|[0-9]+/(?:chunks|complete|fail)))"
)


def registered_media_key(db: Session, path: str, key: str) -> bool:
    """Registered worker keys grant only worker routes; handlers bind agent identity."""
    if not key or not _MEDIA_WORKER_PATH.fullmatch(path):
        return False
    from app.models.media import MediaAgent
    return db.query(MediaAgent.id).filter(
        MediaAgent.api_key_sha256 == hashlib.sha256(key.encode("utf-8")).hexdigest(),
        MediaAgent.active.is_(True),
    ).first() is not None


async def verify_media_worker_key(
    request: Request, x_api_key: Optional[str] = Header(None), db: Session = Depends(get_db),
) -> dict:
    # Called only by worker endpoints. Their agent/lease checks remain mandatory.
    if await run_in_threadpool(registered_media_key, db, request.scope.get("path", ""), x_api_key or ""):
        return {"key": x_api_key, "agent_name": "registered-media-worker", "is_active": True}
    return await verify_api_key(x_api_key)
