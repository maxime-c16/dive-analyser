import pytest
from fastapi import HTTPException

from app.config import get_settings
from app.security import verify_api_key


@pytest.mark.asyncio
async def test_verify_api_key_accepts_configured_key():
    result = await verify_api_key("test-api-key-1234567890abcdef")

    assert result["key"] == "test-api-key-1234567890abcdef"
    assert result["is_active"] is True


@pytest.mark.asyncio
async def test_verify_api_key_rejects_missing_key():
    with pytest.raises(HTTPException) as exc:
        await verify_api_key(None)

    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_verify_api_key_rejects_invalid_key():
    with pytest.raises(HTTPException) as exc:
        await verify_api_key("test-api-key-not-configured")

    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_verify_api_key_fails_closed_without_runtime_config(monkeypatch):
    monkeypatch.setenv("MAC_AGENT_API_KEYS", "")
    get_settings.cache_clear()
    try:
        with pytest.raises(HTTPException) as exc:
            await verify_api_key("test-api-key-1234567890abcdef")
        assert exc.value.status_code == 401
    finally:
        monkeypatch.setenv(
            "MAC_AGENT_API_KEYS",
            ",".join([
                "test-api-key-1234567890abcdef",
                "test-api-key-perf-testing",
                "personal-value-test-key",
                "test-api-key-long-enough",
                "test-api-key-integration-testing",
                "k" * 48,
            ]),
        )
        get_settings.cache_clear()
