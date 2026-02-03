"""Analytics cache model"""

from datetime import datetime
from typing import Optional, Any, Dict
from sqlalchemy import Column, Integer, String, DateTime, Index, JSON

from app.database import Base


class AnalyticsCache(Base):
    """Cached analytics results for fast queries"""

    __tablename__ = "analytics_cache"

    id = Column(Integer, primary_key=True, index=True)
    cache_key = Column(String(255), unique=True, nullable=False, index=True)
    cache_data = Column(JSON, nullable=False)
    filters = Column(JSON, nullable=True)

    computed_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<AnalyticsCache(key={self.cache_key}, expires={self.expires_at})>"
