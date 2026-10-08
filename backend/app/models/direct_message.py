"""Participant-based conversations; direct creation today, groups later."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON, UniqueConstraint, CheckConstraint, Index
from app.database import Base


class Conversation(Base):
    __tablename__ = 'conversations'
    id = Column(Integer, primary_key=True)
    kind = Column(String(16), nullable=False, default='direct')
    direct_key = Column(String(64), nullable=True, unique=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (CheckConstraint("kind IN ('direct', 'group')", name='ck_conversation_kind'),)


class ConversationParticipant(Base):
    __tablename__ = 'conversation_participants'
    conversation_id = Column(Integer, ForeignKey('conversations.id', ondelete='CASCADE'), primary_key=True)
    user_id = Column(Integer, ForeignKey('app_users.id', ondelete='CASCADE'), primary_key=True)
    joined_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    left_at = Column(DateTime, nullable=True)
    __table_args__ = (Index('ix_conversation_participants_user', 'user_id', 'conversation_id'),)


class DirectMessage(Base):
    __tablename__ = 'direct_messages'
    id = Column(Integer, primary_key=True)
    conversation_id = Column(Integer, ForeignKey('conversations.id', ondelete='CASCADE'), nullable=False)
    sender_id = Column(Integer, ForeignKey('app_users.id', ondelete='SET NULL'), nullable=True)
    client_id = Column(String(36), nullable=False)
    body = Column(String(2000), nullable=False, default='')
    mentions = Column(JSON, nullable=False, default=list, server_default='[]')
    dive_id = Column(Integer, ForeignKey('dives.id', ondelete='SET NULL'), nullable=True)
    has_dive = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint('sender_id', 'client_id', name='uq_message_retry'), Index('ix_messages_conversation_id', 'conversation_id', 'id'))


class MessageReceipt(Base):
    __tablename__ = 'message_receipts'
    message_id = Column(Integer, ForeignKey('direct_messages.id', ondelete='CASCADE'), primary_key=True)
    user_id = Column(Integer, ForeignKey('app_users.id', ondelete='CASCADE'), primary_key=True)
    delivered_at = Column(DateTime, nullable=True)
    read_at = Column(DateTime, nullable=True)


class MessageReaction(Base):
    __tablename__ = 'message_reactions'
    message_id = Column(Integer, ForeignKey('direct_messages.id', ondelete='CASCADE'), primary_key=True)
    user_id = Column(Integer, ForeignKey('app_users.id', ondelete='CASCADE'), primary_key=True)
    emoji = Column(String(16), nullable=False, default='❤️')
