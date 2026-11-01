"""Library filters run before pagination and never search another owner's notes."""
import base64
import json
import re
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import and_, case, func, or_

from app.models.dive import Dive

# Figure-name search (see the Library UI) derives exact candidate codes from
# the dive-naming catalog before the request, so the API only needs to verify
# a bounded set. The cap matches the largest single-word family the catalog
# can produce; bigger requests are refused rather than silently truncated so
# answers never appear complete when they are not.
CODE_FILTER_MAX = 1024
CODE_FILTER_PATTERN = re.compile(r'^[1-6][0-9]{2,3}[A-D]$')


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


def sanitize_code_filter(value: str) -> list[str]:
    """Bounded, exact dive-code set for figure-name search (never free text)."""
    if not value:
        return []
    if len(value) > (CODE_FILTER_MAX * 7) or len(value) < 4:
        # Length bound first: a huge string fails fast before splitting.
        raise HTTPException(422, 'Invalid library code filter')
    codes: list[str] = []
    for part in value.split(','):
        code = part.strip().upper()
        if CODE_FILTER_PATTERN.fullmatch(code) is None or code in codes:
            raise HTTPException(422, 'Invalid library code filter')
        codes.append(code)
        if len(codes) > CODE_FILTER_MAX:
            raise HTTPException(422, 'Invalid library code filter')
    return codes


def _searchable_context(db):
    """Match the serializer's owner/admin/depositor permissions without N+1."""
    context = db.info.get('member_access')
    return True if context is None else or_(
        Dive.diver_id.in_(context['diver_ids']),
        and_(Dive.diver_id.is_(None), bool(context.get('is_admin'))),
        and_(Dive.accepted_at.is_(None), Dive.batch_id.is_not(None),
             or_(Dive.deposited_by_user_id == context['user_id'], bool(context.get('is_admin')))),
    )


def _text_filters(db, text, manageable):
    """Code-prefix OR caption/notes phrase, never probing another owner's notes."""
    searchable = func.upper(func.coalesce(Dive.raw_caption, '') + ' ' + func.coalesce(Dive.notes, ''))
    return [
        func.upper(Dive.dive_code).contains(text.upper(), autoescape=True),
        and_(manageable, searchable.contains(text.upper(), autoescape=True)),
    ]


def apply_library_filters(query, db, code, text, position, sync, modifiers, code_filter=""):
    if code:
        query = query.filter(func.upper(Dive.dive_code).startswith(code.upper(), autoescape=True))
    # Match the serializer's owner/admin/depositor permissions without N+1:
    # notes and captions stay private, codes are public catalog data.
    manageable = _searchable_context(db)
    filter_codes = sanitize_code_filter(code_filter)
    text_filters = _text_filters(db, text, manageable) if text else []
    if filter_codes:
        # Figure-name matching and the caption/notes phrase are alternatives
        # (the catalog derivation cannot see private captions and the phrase
        # cannot see empty ones); the client mirrors this OR-composition so
        # every page agrees with the aggregates.
        name_match = func.upper(Dive.dive_code).in_(filter_codes)
        if text_filters:
            query = query.filter(or_(name_match, *text_filters))
        else:
            query = query.filter(name_match)
    elif text_filters:
        query = query.filter(or_(*text_filters))
    if position:
        query = query.filter(case((func.upper(Dive.dive_code).regexp_match('^[0-9]{3,4}[ABCD]$'), func.upper(func.substr(Dive.dive_code, -1))),
                                 else_=func.upper(Dive.position)) == position.upper())
    if sync is not None:
        query = query.filter(Dive.is_sync == sync)
    for modifier in filter(None, modifiers.split(',')):
        if modifier not in ('DB', 'SD', 'HU'):
            raise HTTPException(422, 'Invalid library modifier')
        query = query.filter(manageable, func.upper(func.coalesce(Dive.raw_caption, '')).regexp_match(
            f'(^|[^A-Z0-9_]){modifier}([^A-Z0-9_]|$)'))
    return query
