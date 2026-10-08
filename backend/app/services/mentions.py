"""Stable identity spans, in Unicode code points (never UTF-16 offsets)."""
from fastapi import HTTPException
from pydantic import BaseModel, Field
from app.models.user_auth import AppUser


class MentionInput(BaseModel):
    user_id: int = Field(gt=0)
    start: int = Field(ge=0)
    end: int = Field(gt=0)


def validate_mentions(db, body, mentions):
    result = []
    end = 0
    users = {u.id: u for u in db.query(AppUser).filter(
        AppUser.id.in_({m.user_id for m in mentions}), AppUser.is_active.is_(True)).all()} if mentions else {}
    for mention in sorted(mentions, key=lambda m: m.start):
        user = users.get(mention.user_id)
        if (user is None or mention.start < end or mention.end <= mention.start
                or mention.end > len(body)
                or body[mention.start:mention.end] not in
                {f'@{user.display_name}', f'@{user.handle}' if user.handle else None}):
            raise HTTPException(422, 'Invalid mention; select a member again')
        result.append(mention.model_dump())
        end = mention.end
    return result
