"""Private preparation sheets; slot order and alternatives are one atomic document."""
from datetime import datetime
from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String
from app.database import Base


class DiveSeries(Base):
    __tablename__ = "dive_series"
    __table_args__ = {"info": {"sql_migration_only": True}}
    id = Column(Integer, primary_key=True)
    owner_user_id = Column(Integer, ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(160), nullable=False)
    clip_policy = Column(String(10), nullable=False, default="best", server_default="best")
    height = Column(String(5), nullable=False)
    # Calendar is optional/default-off. Authorization is checked when attaching;
    # no FK forces installation of the calendar schema for standalone series.
    event_id = Column(Integer, nullable=True, index=True)
    slots = Column(JSON, nullable=False, default=list)
    shared_with = Column(JSON, nullable=False, default=list)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
