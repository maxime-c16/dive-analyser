"""Dive code metadata model (FINA codes reference)"""

from datetime import datetime
from typing import Optional
from sqlalchemy import Column, String, Text, Integer, Numeric, DateTime

from app.database import Base


class DiveCode(Base):
    """Dive code metadata and statistics"""

    __tablename__ = "dive_codes_metadata"

    dive_code = Column(String(10), primary_key=True, index=True)
    dive_number = Column(String(5), nullable=True)
    position = Column(String(1), nullable=True)
    direction = Column(Integer, nullable=True)
    description = Column(Text, nullable=True)
    group_name = Column(String(100), nullable=True)

    # User statistics for this dive code
    total_attempts = Column(Integer, default=0)
    avg_performance = Column(Numeric(3, 2), nullable=True)
    success_rate = Column(Numeric(5, 2), nullable=True)
    last_attempted = Column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<DiveCode(code={self.dive_code}, attempts={self.total_attempts})>"
