"""API key authentication and security utilities."""

import hmac
from typing import Optional

from fastapi import Header, HTTPException, status

from app.config import get_settings


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
