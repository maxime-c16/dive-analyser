"""Video label model for non-dive Photos captions."""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, UniqueConstraint, Index

from app.database import Base


class VideoLabel(Base):
    """Metadata labels attached to videos that are not necessarily dives."""

    __tablename__ = "video_labels"

    id = Column(Integer, primary_key=True, index=True)
    video_uuid = Column(String(100), nullable=False, index=True)
    label_type = Column(String(50), nullable=False, index=True)
    label_value = Column(String(100), nullable=False, index=True)
    source = Column(String(50), nullable=False, default="photos_caption", index=True)
    raw_caption = Column(Text, nullable=True)
    video_filename = Column(String(255), nullable=True)
    label_datetime = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "video_uuid",
            "label_type",
            "source",
            name="uq_video_labels_uuid_type_source",
        ),
        Index("idx_video_labels_type_value", "label_type", "label_value"),
    )
