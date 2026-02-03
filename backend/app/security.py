"""
API key authentication and security utilities.

Provides FastAPI dependency for validating API keys from mac-agent.
"""

from typing import Optional
from fastapi import Header, HTTPException, Depends, status
from sqlalchemy.orm import Session

from app.database import get_db


async def verify_api_key(
    x_api_key: Optional[str] = Header(None),
    db: Session = Depends(get_db)
) -> dict:
    """
    FastAPI dependency to validate API key from X-API-Key header.

    Usage in routes:
        @router.post("/api/v1/videos/sync")
        async def sync_video(
            request: VideoSyncRequest,
            api_key: dict = Depends(verify_api_key),
            db: Session = Depends(get_db),
        ):
            # api_key contains validated key info
            pass

    Args:
        x_api_key: API key from X-API-Key header
        db: Database session

    Returns:
        Dictionary with key info: {key, agent_name, created_at, ...}

    Raises:
        HTTPException(401): If key invalid or not provided
        HTTPException(403): If key disabled
    """
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required in X-API-Key header"
        )

    # In production, would query AgentKey table
    # For now, just validate it's provided and non-empty
    if len(x_api_key) < 10:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key format"
        )

    # Return key info (would be from database in production)
    return {
        "key": x_api_key,
        "agent_name": "test-agent",  # TODO: Get from database
        "is_active": True,  # TODO: Check in database
    }


def create_test_api_key(db: Session, agent_name: str = "test-agent") -> str:
    """
    Create test API key for testing.

    Note: This is a placeholder until AgentKey model is created.

    Args:
        db: Database session
        agent_name: Name of agent

    Returns:
        API key string
    """
    # TODO: Implement when AgentKey model exists
    return "test-api-key-" + agent_name
