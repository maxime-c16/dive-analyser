"""Authenticated, optional deployment announcements. Missing state is quiet."""
import json
import os
import re
from pathlib import Path

from fastapi import APIRouter, Depends, Response
from app.api.v1.auth import get_current_user

router = APIRouter()


def read_updates(is_admin: bool):
    empty = {'schema': 1, 'version': '', 'frontend_sha': '', 'notes': []}
    path = Path(os.environ.get('MEDIA_CACHE_ROOT', '/app/media-cache')) / 'release-notes.json'
    try:
        if path.stat().st_size > 200_000:
            return empty
        manifest = json.loads(path.read_text())
        if manifest.get('schema') != 1 or not re.fullmatch(r'[0-9a-f]{40}', manifest.get('frontend_sha', '')):
            return empty
        notes = manifest['notes']
        if not isinstance(notes, list) or len(notes) > 100:
            return empty
        visible = []
        ids = set()
        for note in notes:
            if (not isinstance(note, dict) or not all(isinstance(note.get(k), str) for k in ('id', 'date', 'title', 'body', 'audience'))
                    or note['audience'] not in ('all', 'admin') or note['id'] in ids):
                return empty
            ids.add(note['id'])
            if note['audience'] == 'all' or is_admin:
                visible.append({k: note[k] for k in ('id', 'date', 'title', 'body')})
        version = manifest.get('version', '')
        if not isinstance(version, str):
            version = ''
        return {**empty, 'version': version, 'frontend_sha': manifest['frontend_sha'], 'notes': visible}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return empty


@router.get('/updates')
def updates(response: Response, user=Depends(get_current_user)):
    response.headers['Cache-Control'] = 'private, no-store'
    return read_updates(bool(user.is_admin))
