#!/usr/bin/env python
"""Send due deposit-batch emails ("Récupérer mes plongeons").

One email per (batch, recipient) outbox row whose scheduled_for has passed.
Run from cron on the app host (see ops/send-batch-emails.sh); safe to run
often — rows flip pending->sent/failed exactly once per process pass.

Skips (row stays pending for the next pass): email not configured
(SMTP_HOST empty), recipient opted out, APP_PUBLIC_URL missing, or no
pending clip left in the batch (marked sent: nothing to claim).

Usage (inside the backend container, or any host with DATABASE_URL):
    python scripts/send_batch_emails.py [--limit 20] [--dry-run]
"""

import argparse
import os
import sys
from datetime import datetime

# Allow direct script invocation from any CWD/container entrypoint.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import get_settings
from app.database import SessionLocal
from app.models.deposit_batch import BatchEmailOutbox
from app.models.dive import Dive
from app.models.diver import Diver
from app.models.user_auth import AppUser
from app.services import claim_tokens, email_service

CLAIM_TOKEN_TTL_SECONDS = 7 * 24 * 3600


def _send_one(db, row: BatchEmailOutbox, dry_run: bool) -> str:
    settings = get_settings()
    user = db.get(AppUser, row.user_id)
    diver = db.get(Diver, row.diver_id)
    if user is None or diver is None or not user.is_active:
        return "skipped: recipient gone"
    if not email_service.email_enabled(db, user.id):
        return "skipped: opted out"
    dives = (
        db.query(Dive)
        .filter(
            Dive.batch_id == row.batch_id,
            Dive.diver_id == row.diver_id,
            Dive.accepted_at.is_(None),
        )
        .order_by(Dive.dive_datetime.desc(), Dive.id.desc())
        .limit(50)
        .all()
    )
    if not dives:
        return "skipped: nothing pending"
    depositor_id = dives[0].deposited_by_user_id
    depositor = db.get(AppUser, depositor_id) if depositor_id else None
    note = None
    if dives:
        from app.models.deposit_batch import EvaluatorNote

        first_note = (
            db.query(EvaluatorNote)
            .filter(EvaluatorNote.dive_id.in_([d.id for d in dives]))
            .order_by(EvaluatorNote.id.asc())
            .first()
        )
        note = first_note.comment if first_note else None
    app_url = settings.app_public_url.strip().rstrip("/")
    if not app_url:
        return "skipped: APP_PUBLIC_URL missing"
    raw_token = claim_tokens.mint_claim_token(
        db,
        user_id=user.id,
        batch_id=row.batch_id,
        created_by_user_id=depositor_id,
        ttl_seconds=CLAIM_TOKEN_TTL_SECONDS,
    )
    dive_dicts = [
        {
            "dive_code": d.dive_code,
            "height": d.height,
            "dive_datetime": d.dive_datetime.isoformat() if d.dive_datetime else "",
        }
        for d in dives
    ]
    msg = email_service.render_batch_email(
        recipient_name=user.display_name or user.email.split("@")[0],
        diver_name=diver.display_name,
        depositor_name=depositor.display_name if depositor else None,
        dives=dive_dicts,
        evaluator_note=note,
        claim_url=f"{app_url}/claim/{raw_token}",
        review_url=f"{app_url}/deposits/{row.batch_id}",
        posters=email_service.posters_for_dives(db, dives),
    )
    if dry_run:
        print(f"DRY-RUN to={user.email} batch={row.batch_id} clips={len(dives)}")
        db.rollback()
        return "dry-run"
    ok, error = email_service.send_message(msg, user.email)
    if not ok:
        raise RuntimeError(f"smtp: {error}")
    return f"sent to {user.email} ({len(dives)} clips)"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not email_service.is_email_configured() and not args.dry_run:
        print("email not configured (SMTP_HOST empty); nothing to do")
        return 0
    db = SessionLocal()
    try:
        rows = (
            db.query(BatchEmailOutbox)
            .filter(
                BatchEmailOutbox.status == BatchEmailOutbox.STATUS_PENDING,
                BatchEmailOutbox.scheduled_for <= datetime.utcnow(),
            )
            .order_by(BatchEmailOutbox.scheduled_for.asc())
            .limit(max(1, args.limit))
            .all()
        )
        print(f"{len(rows)} due batch email(s)")
        for row in rows:
            try:
                outcome = _send_one(db, row, args.dry_run)
                if outcome == "dry-run":
                    continue
                if outcome.startswith("sent to"):
                    row.status = BatchEmailOutbox.STATUS_SENT
                    row.sent_at = datetime.utcnow()
                    row.error = None
                elif outcome.startswith("skipped: APP_PUBLIC_URL"):
                    # Configuration gap: retry on a later pass once fixed.
                    db.rollback()
                else:
                    # Terminal skips (opt-out, gone, nothing left to claim):
                    # not an error, and retrying would never help.
                    row.status = BatchEmailOutbox.STATUS_SENT
                    row.sent_at = datetime.utcnow()
                    row.error = outcome
                db.commit()
                print(f"batch={row.batch_id} user={row.user_id}: {outcome}")
            except Exception as exc:
                db.rollback()
                row.status = BatchEmailOutbox.STATUS_FAILED
                row.error = f"{type(exc).__name__}: {str(exc)[:300]}"
                db.commit()
                print(f"batch={row.batch_id} user={row.user_id}: FAILED {row.error}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
