"""Nginx HMAC capability URLs, minted only by authorized payload producers."""
import hashlib
import hmac
import os
from pathlib import Path
import re
import time
from urllib.parse import quote
from app.config import get_settings


def signed_url(path, checksum, now=None):
    secret = os.environ.get("MEDIA_SIGNING_SECRET", "")
    if os.environ.get("MEDIA_SIGNED_URLS_ENABLED", "false").lower() != "true" or not re.fullmatch(r"[0-9a-f]{64}", secret):
        return None
    if not checksum or not re.fullmatch(r"[0-9a-fA-F]{64}", checksum):
        return None
    try:
        relative = Path(path).resolve().relative_to(Path(get_settings().media_cache_root).resolve()).as_posix()
    except (ValueError, OSError):
        return None
    # Restrict to predictable ASCII paths; reject symlinks/traversal at nginx too.
    if not re.fullmatch(r"[a-zA-Z0-9_./-]+", relative) or any(x in ("", ".", "..") for x in relative.split("/")):
        return None
    uri = f"/media/cache/signed/{checksum.lower()}/{quote(relative, safe='/')}"
    # 60–75 min validity, identical URL for requests in one 15-minute bucket.
    expires = (int(time.time() if now is None else now) // 900 + 5) * 900
    signature = hmac.new(secret.encode(), f"{expires}\n{uri}".encode(), hashlib.sha256).hexdigest()
    return f"{uri}?expires={expires}&sig={signature}"
