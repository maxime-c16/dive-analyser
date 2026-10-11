"""Durable, account-private browser ingestion jobs (no bearer tokens)."""
from datetime import datetime
from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from app.database import Base


class BrowserUploadJob(Base):
    __tablename__ = 'browser_upload_jobs'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('app_users.id'), nullable=False, index=True)
    upload_id = Column(String(36), nullable=False)
    payload = Column(JSON, nullable=False)
    filename = Column(String(255), nullable=False)
    storage_path = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default='receiving', index=True)
    attempts = Column(Integer, nullable=False, default=0)
    result_id = Column(Integer, nullable=True)
    last_error = Column(String(200), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (UniqueConstraint('user_id', 'upload_id', name='uq_browser_upload_identity'),)
