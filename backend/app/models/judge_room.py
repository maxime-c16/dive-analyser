from datetime import datetime
from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    ForeignKey,
    CheckConstraint,
    UniqueConstraint,
    Text,
)
from app.database import Base


class JudgeRoomResult(Base):
    __tablename__ = "judge_room_results"
    __table_args__ = {"info": {"sql_migration_only": True}}
    id = Column(String(32), primary_key=True)
    code = Column(String(4), nullable=False)
    mode = Column(String(16), nullable=False)
    result = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class JudgeRoomRating(Base):
    __tablename__ = "judge_room_ratings"
    id = Column(Integer, primary_key=True)
    room_id = Column(String(32), ForeignKey("judge_room_results.id"), nullable=False)
    dive_id = Column(
        Integer, ForeignKey("dives.id", ondelete="CASCADE"), nullable=False
    )
    player_id = Column(String(64), nullable=False)
    user_id = Column(Integer, ForeignKey("app_users.id"), nullable=True)
    nickname = Column(String(40), nullable=False)
    score_half_steps = Column(Integer, nullable=False)
    dive_code = Column(String(10), nullable=False)
    height = Column(String(5), nullable=False)
    __table_args__ = (
        CheckConstraint(
            "score_half_steps BETWEEN 0 AND 20", name="ck_judge_room_rating_score"
        ),
        UniqueConstraint("room_id", "dive_id", "player_id"),
        {"info": {"sql_migration_only": True}},
    )


class JudgeShadowPreference(Base):
    __tablename__ = "judge_shadow_preferences"
    __table_args__ = {"info": {"sql_migration_only": True}}
    user_id = Column(
        Integer, ForeignKey("app_users.id", ondelete="CASCADE"), primary_key=True
    )
    enabled = Column(Integer, nullable=False, default=0)
