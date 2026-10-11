"""Library filters run before pagination and never search another owner's notes."""
import base64
import json
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import and_, case, func, or_

from app.models.dive import Dive


def encode_cursor(row):
    value = json.dumps([row['dive_datetime'].isoformat(), row['id']]).encode()
    return base64.urlsafe_b64encode(value).decode().rstrip('=')


def decode_cursor(value):
    try:
        if len(value) > 200:
            raise ValueError()
        date, identity = json.loads(base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True))
        parsed = datetime.fromisoformat(date)
        if parsed.tzinfo is not None or type(identity) is not int or identity < 1:
            raise ValueError()
        return parsed, identity
    except (ValueError, TypeError, UnicodeError):
        raise HTTPException(422, 'Invalid library cursor')


def apply_library_filters(query, db, code, text, position, sync, modifiers):
    if code:
        query = query.filter(func.upper(Dive.dive_code).startswith(code.upper(), autoescape=True))
    if position:
        query = query.filter(case((func.upper(Dive.dive_code).regexp_match('^[0-9]{3,4}[ABCD]$'), func.upper(func.substr(Dive.dive_code, -1))),
                                 else_=func.upper(Dive.position)) == position.upper())
    if sync is not None:
        query = query.filter(Dive.is_sync == sync)
    context = db.info.get('member_access')
    # Match the serializer's owner/admin/depositor permissions without N+1.
    manageable = True if context is None else or_(
        Dive.diver_id.in_(context['diver_ids']),
        and_(Dive.diver_id.is_(None), bool(context.get('is_admin'))),
        and_(Dive.accepted_at.is_(None), Dive.batch_id.is_not(None),
             or_(Dive.deposited_by_user_id == context['user_id'], bool(context.get('is_admin')))),
    )
    if text:
        searchable = func.upper(func.coalesce(Dive.raw_caption, '') + ' ' + func.coalesce(Dive.notes, ''))
        query = query.filter(or_(func.upper(Dive.dive_code).contains(text.upper(), autoescape=True),
                                and_(manageable, searchable.contains(text.upper(), autoescape=True))))
    for modifier in filter(None, modifiers.split(',')):
        if modifier not in ('DB', 'SD', 'HU'):
            raise HTTPException(422, 'Invalid library modifier')
        query = query.filter(manageable, func.upper(func.coalesce(Dive.raw_caption, '')).regexp_match(
            f'(^|[^A-Z0-9_]){modifier}([^A-Z0-9_]|$)'))
    return query
