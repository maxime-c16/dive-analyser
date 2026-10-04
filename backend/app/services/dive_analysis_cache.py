"""Short-lived database cache for media-independent analytics calculations."""

import hashlib
import json
import logging
from datetime import datetime, timedelta

from fastapi.encoders import jsonable_encoder
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.cache import AnalyticsCache

logger = logging.getLogger(__name__)
ANALYTICS_VERSION = "2.1"


def analysis_cache_key(dive_code: str, filters: dict, weighting: str) -> str:
    payload = json.dumps(jsonable_encoder({"dive_code": dive_code, "filters": filters, "weighting": weighting, "analytics_version": ANALYTICS_VERSION}), sort_keys=True, separators=(",", ":"))
    return f"dive-analysis:v2.1:{hashlib.sha256(payload.encode()).hexdigest()}"


def get_cached_analysis(db: Session, cache_key: str) -> dict | None:
    now = datetime.utcnow()
    entry = db.execute(select(AnalyticsCache).where(AnalyticsCache.cache_key == cache_key, AnalyticsCache.expires_at > now)).scalar_one_or_none()
    if entry:
        logger.info("dive_analysis_cache hit key=%s", cache_key[-12:])
        return entry.cache_data
    db.execute(delete(AnalyticsCache).where(AnalyticsCache.cache_key == cache_key, AnalyticsCache.expires_at <= now))
    logger.info("dive_analysis_cache miss key=%s", cache_key[-12:])
    return None


def set_cached_analysis(db: Session, cache_key: str, filters: dict, payload: dict) -> None:
    now = datetime.utcnow()
    entry = db.execute(select(AnalyticsCache).where(AnalyticsCache.cache_key == cache_key)).scalar_one_or_none()
    if not entry:
        entry = AnalyticsCache(cache_key=cache_key, cache_data={})
        db.add(entry)
    entry.cache_data = jsonable_encoder(payload)
    entry.filters = jsonable_encoder(filters)
    entry.computed_at = now
    entry.expires_at = now + timedelta(seconds=get_settings().dive_analysis_cache_ttl_seconds)
    db.flush()
