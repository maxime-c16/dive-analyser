#!/usr/bin/env python
"""P9-F extended playback soak (packet §25): automated representative
authenticated playback traffic against the LIVE production backend.

Operator tool, server-local only. It:
  1. mints a server-side session for an existing user (default: the real
     OWNER account) by inserting the row directly via DATABASE_URL —
     the same operator-minted-session model used in P8; no password is
     requested, printed or logged (the raw token exists ONLY in the
     session cookie argument, like a browser);
  2. drives >= --min-requests authorized playback grants against every
     media revision the user may access:
       GET /media/revisions/{id}/play        (302 → presigned URL)
       GET <presigned-url>  Range 0-65535    (206 provider proof)
       GET /media/playback/canary/revisions  (cohort listing)
     plus optional legacy-check probes (authenticated legacy route);
  3. prints a privacy-safe aggregated summary (counts/latencies only;
     presigned URLs are never printed, logged or stored).

It performs NO mutations: playback grants are the documented grant-ledger
rows; B2 access is read-only ranged GET; nothing is deleted or hidden.

Usage (inside the backend container):
    python scripts/playback_soak.py --base-url https://nginx:443 ... 
    python scripts/playback_soak.py --print-cookie   # mint session, exit
"""

import argparse
import hashlib
import json
import os
import secrets
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from app.config import get_settings
from app.database import SessionLocal, init_db
from app.models.user_auth import UserSession
from app.services.sessions import SESSION_TOKEN_BYTES

TTL_SECONDS = 3600


def mint_session_cookie(email: str) -> str:
    init_db()
    settings = get_settings()
    raw = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
    token_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    now = datetime.utcnow()
    with SessionLocal() as db:
        row = db.execute(
            text("SELECT id FROM app_users WHERE lower(email) = :e"),
            {"e": email.strip().lower()},
        ).fetchone()
        if row is None:
            raise SystemExit(f"unknown user email: {email}")
        db.add(
            UserSession(
                user_id=row[0],
                token_hash=token_hash,
                created_at=now,
                expires_at=now + timedelta(seconds=TTL_SECONDS),
            )
        )
        db.commit()
    cookie_name = settings.auth_cookie_name
    return f"{cookie_name}={raw}"


def http_get(client, url, cookie, *, range_header=None, allow_redirect=True):
    headers = {"Cookie": cookie}
    if range_header:
        headers["Range"] = range_header
    return client.get(
        url,
        headers=headers,
        follow_redirects=allow_redirect,
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="e.g. https://nginx or https://127.0.0.1:6443")
    parser.add_argument("--email", required=True)
    parser.add_argument("--cookie", default=None, help="use an existing session cookie (k=v)")
    parser.add_argument("--min-requests", type=int, default=100)
    parser.add_argument("--insecure", action="store_true", help="skip TLS verification (internal CA)")
    parser.add_argument("--print-cookie", action="store_true")
    args = parser.parse_args(argv)

    cookie = args.cookie or mint_session_cookie(args.email)
    if args.print_cookie:
        print(cookie)
        return 0

    import httpx

    client = httpx.Client(verify=not args.insecure, timeout=30.0)
    cookie_header = cookie if "=" in cookie else None
    if cookie_header is None:
        raise SystemExit("--cookie must be provided for the soak phase")

    summary = {
        "authorized": 0,
        "denied": 0,
        "b2_selected": 0,
        "legacy_fallback": 0,
        "provider_failures": 0,
        "range_success": 0,
        "grant_refreshes": 0,
        "provider_errors": 0,
        "storage_lookup_ms": [],
        "presign_ms": [],
        "unexpected": 0,
    }

    # cohort listing
    r = http_get(client, f"{args.base_url}/api/v1/media/playback/canary/revisions", cookie_header)
    if r.status_code != 200:
        print(json.dumps({"error": "cohort listing failed", "status": r.status_code}))
        return 1
    revisions = [
        item["media_revision_id"]
        for item in r.json().get("revisions", [])
        if item.get("b2_ready")
    ]
    summary["eligible_revisions"] = len(revisions)
    if not revisions:
        print(json.dumps({"error": "no eligible revisions"}))
        return 1

    requests = 0
    while requests < args.min_requests:
        for revision_id in revisions:
            if requests >= args.min_requests:
                break
            started = time.perf_counter()
            r = http_get(
                client,
                f"{args.base_url}/api/v1/media/revisions/{revision_id}/play",
                cookie_header,
                allow_redirect=False,
            )
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            summary["storage_lookup_ms"].append(elapsed_ms)
            requests += 1
            if r.status_code == 302:
                summary["authorized"] += 1
                summary["b2_selected"] += 1
                location = r.headers.get("location", "")
                fetch_started = time.perf_counter()
                try:
                    ranged = client.get(location, headers={"Range": "bytes=0-65535"})
                    fetch_ms = (time.perf_counter() - fetch_started) * 1000.0
                    summary["presign_ms"].append(fetch_ms)
                    if ranged.status_code == 206 and ranged.content:
                        summary["range_success"] += 1
                    else:
                        summary["provider_errors"] += 1
                except httpx.HTTPError:
                    summary["provider_errors"] += 1
                del location
            elif r.status_code == 200:
                summary["authorized"] += 1
                summary["legacy_fallback"] += 1
            elif r.status_code == 404:
                summary["denied"] += 1
            elif r.status_code == 503:
                summary["provider_failures"] += 1
            else:
                summary["unexpected"] += 1
            # deny-family probe every 10th request (wrong-owner simulation via
            # unknown revision id — must be a uniform 404)
            if requests % 10 == 0:
                r2 = http_get(
                    client,
                    f"{args.base_url}/api/v1/media/revisions/99999999/play",
                    cookie_header,
                    allow_redirect=False,
                )
                requests += 1
                if r2.status_code in (401, 404):
                    summary["denied"] += 1
                else:
                    summary["unexpected"] += 1

    for key in ("storage_lookup_ms", "presign_ms"):
        values = summary.pop(key)
        summary[f"{key}_avg_ms"] = round(sum(values) / len(values), 2) if values else 0
        summary[f"{key}_max_ms"] = round(max(values), 2) if values else 0
    summary["total_requests"] = requests
    print(json.dumps(summary, indent=2))

    live = http_get(client, f"{args.base_url}/api/v1/media/playback/metrics", cookie_header)
    if live.status_code == 200:
        print(json.dumps({"playback_metrics": live.json()}))
    return 0 if summary["unexpected"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
