"""Batch email delivery ("Récupérer mes plongeons").

Free-tier transport: a Gmail SMTP maintainer account (2FA + app password).
Secrets live in the runtime env only (SMTP_HOST/PORT/USER/PASSWORD,
EMAIL_FROM); an empty SMTP_HOST disables sending — outbox rows stay
pending while inbox + push keep working, so mail is never load-bearing.

Content: one email per diver per batch with a card-stack of up to 4 poster
thumbnails (attached as CID parts — email clients fetch nothing, so no auth
is needed), the maintainer's evaluator note, and a magic-link button that
signs the recipient straight into their review page.
"""

import html
import logging
import smtplib
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.dive import Dive
from app.models.media import MediaCacheEntry
from app.models.notification import NotificationPref

logger = logging.getLogger(__name__)

EMAIL_BATCH_PREF = "email_batch"
MAX_THUMBNAILS = 4
MAX_THUMBNAIL_BYTES = 500 * 1024


def _sender_address(email_from: str) -> str:
    """Bare address of the configured From header ("Name <a@b>" -> "a@b")."""
    return parseaddr(email_from or "")[1].strip()


def is_email_configured() -> bool:
    settings = get_settings()
    return bool(
        settings.smtp_host.strip()
        and settings.smtp_user.strip()
        and settings.smtp_password
        and settings.email_from.strip()
    )


def email_enabled(db: Session, user_id: int) -> bool:
    """Batch-email opt-out (notification_prefs row, default ON).

    Deliberately outside notification_service NOTIF_TYPES: email is a
    transport for new_video events, not a new inbox type.
    """
    row = (
        db.query(NotificationPref)
        .filter_by(user_id=user_id, notif_type=EMAIL_BATCH_PREF)
        .first()
    )
    if row is None:
        return True
    return bool(row.enabled)


def set_email_enabled(db: Session, user_id: int, enabled: bool) -> bool:
    row = (
        db.query(NotificationPref)
        .filter_by(user_id=user_id, notif_type=EMAIL_BATCH_PREF)
        .first()
    )
    if row is None:
        row = NotificationPref(user_id=user_id, notif_type=EMAIL_BATCH_PREF, enabled=bool(enabled))
        db.add(row)
    else:
        row.enabled = bool(enabled)
    db.commit()
    db.refresh(row)
    return bool(row.enabled)


def posters_for_dives(db: Session, dives: list[Dive], limit: int = MAX_THUMBNAILS) -> list[tuple[str, bytes, str]]:
    """Poster bytes for the thumbnail stack, newest dive first.

    Reads media-cache poster files (already small JPEGs); oversized or
    missing files are skipped so one bad rendition never kills the email.
    """
    asset_ids = [d.photos_asset_id for d in dives if d.photos_asset_id]
    if not asset_ids:
        return []
    entries = (
        db.query(MediaCacheEntry)
        .filter(
            MediaCacheEntry.photos_asset_id.in_(asset_ids),
            MediaCacheEntry.rendition == "poster",
        )
        .all()
    )
    by_asset: dict[int, MediaCacheEntry] = {}
    for entry in entries:
        by_asset.setdefault(entry.photos_asset_id, entry)
    posters: list[tuple[str, bytes, str]] = []
    for dive in dives:
        if len(posters) >= limit:
            break
        entry = by_asset.get(dive.photos_asset_id or -1)
        if entry is None or not entry.storage_path:
            continue
        try:
            data = Path(entry.storage_path).read_bytes()
        except OSError:
            continue
        if not data or len(data) > MAX_THUMBNAIL_BYTES:
            continue
        ctype = (entry.content_type or "image/jpeg").strip() or "image/jpeg"
        maintype, _, subtype = ctype.partition("/")
        if maintype != "image" or not subtype:
            continue
        posters.append((f"poster-{dive.id}", data, subtype))
    return posters


def _clip_line(dive: dict) -> str:
    when = (dive.get("dive_datetime") or "")[:10]
    parts = [dive.get("dive_code") or "?", dive.get("height") or "?"]
    if when:
        parts.append(when)
    return " · ".join(parts)


def render_batch_email(
    *,
    recipient_name: str,
    diver_name: str,
    depositor_name: Optional[str],
    dives: list[dict],
    evaluator_note: Optional[str],
    claim_url: str,
    review_url: str,
    posters: list[tuple[str, bytes, str]],
) -> EmailMessage:
    """Build the multipart (text + HTML + CID thumbnails) batch email."""
    count = len(dives)
    title = (
        "Un nouveau plongeon à récupérer"
        if count == 1
        else f"{count} nouveaux plongeons à récupérer"
    )
    clip_lines = "\n".join(f"- {_clip_line(d)}" for d in dives)
    note_block = f'\nNote de {depositor_name or "ton club"} :\n{evaluator_note.strip()}\n' if evaluator_note else ""
    text = (
        f"Salut {recipient_name},\n\n"
        f"{depositor_name or 'Ton club'} t'a déposé {count} plongeon{'s' if count > 1 else ''} "
        f"pour {diver_name} :\n{clip_lines}\n"
        f"{note_block}\n"
        f"Récupère-les ici (connexion automatique) :\n{claim_url}\n\n"
        f"Tu pourras les accepter un par un — ou tout accepter — et corriger "
        f"le code, la hauteur ou ta note perso au passage.\n"
        f"Lien direct vers la revue : {review_url}\n"
    )

    cards = ""
    for cid, _data, _subtype in posters:
        cards += (
            '<td style="padding:0 6px 0 0;">'
            f'<img src="cid:{cid}" width="140" alt="" '
            'style="display:block;width:140px;height:auto;border:0;border-radius:10px;" />'
            "</td>"
        )
    if not cards:
        initials = "".join(w[0] for w in (diver_name or "?").split() if w)[:2].upper() or "?"
        cards = (
            '<td style="padding:0;">'
            '<div style="width:140px;height:140px;line-height:140px;text-align:center;'
            "font-size:44px;font-weight:700;color:#ffffff;background:#0e7490;"
            'border-radius:10px;">' + html.escape(initials) + "</div></td>"
        )
    items = ""
    for d in dives:
        items += (
            '<li style="margin:0 0 6px 0;">'
            f"<strong>{html.escape(d.get('dive_code') or '?')}</strong>"
            f" · {html.escape(d.get('height') or '?')}"
            + (f" · {html.escape((d.get('dive_datetime') or '')[:10])}" if d.get("dive_datetime") else "")
            + "</li>"
        )
    note_html = ""
    if evaluator_note:
        note_html = (
            '<p style="margin:16px 0 0 0;padding:12px 14px;background:#f1f5f9;'
            'border-left:4px solid #0e7490;border-radius:0 8px 8px 0;'
            'font-style:italic;color:#334155;">'
            f"« {html.escape(evaluator_note.strip())} »"
            f"<br /><span style=\"font-style:normal;font-size:12px;\">— {html.escape(depositor_name or 'ton club')}</span>"
            "</p>"
        )
    greeting = html.escape(recipient_name)
    diver = html.escape(diver_name)
    plural = "s" if count > 1 else ""
    html_body = (
        '<div style="margin:0;padding:0;background:#f8fafc;">'
        '<div style="max-width:560px;margin:0 auto;padding:24px 16px;'
        'font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#0f172a;">'
        '<div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:14px;'
        'padding:28px 24px;">'
        '<p style="margin:0 0 4px 0;font-size:12px;letter-spacing:2px;color:#0e7490;'
        'font-weight:700;">DIVE ANALYSER</p>'
        f'<h1 style="margin:0 0 8px 0;font-size:22px;">{html.escape(title)}</h1>'
        f"<p style=\"margin:0 0 16px 0;color:#475569;\">Salut {greeting}, "
        f"{html.escape(depositor_name or 'Ton club')} t'a déposé "
        f"{count} plongeon{plural} pour <strong>{diver}</strong>&nbsp;:</p>"
        '<table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 0 8px 0;">'
        f"<tr>{cards}</tr></table>"
        f'<ul style="margin:8px 0 0 0;padding-left:20px;color:#334155;">{items}</ul>'
        f"{note_html}"
        '<p style="margin:22px 0 0 0;">'
        f'<a href="{html.escape(claim_url)}" '
        'style="display:inline-block;background:#0e7490;color:#ffffff;text-decoration:none;'
        'font-weight:700;padding:13px 26px;border-radius:999px;">'
        "Récupérer mes plongeons</a></p>"
        '<p style="margin:14px 0 0 0;font-size:13px;color:#64748b;">'
        "Le bouton te connecte automatiquement. Tu pourras accepter les clips "
        "un par un — ou tout accepter — et corriger le code, la hauteur ou ta "
        "note perso au passage.</p>"
        "</div>"
        '<p style="margin:14px 4px 0 4px;font-size:12px;color:#94a3b8;">'
        "Tu reçois cet email car tu suis ce plongeur. "
        f'Gérer les emails : <a href="{html.escape(review_url)}" '
        'style="color:#64748b;">mes réglages</a>.</p>'
        "</div></div>"
    )

    msg = EmailMessage()
    settings = get_settings()
    msg["Subject"] = f"[Dive Analyser] {title} — {diver_name}"
    msg["From"] = settings.email_from.strip()
    sender = _sender_address(settings.email_from)
    if sender:
        # Replies reach the real mailbox instead of a no-reply black hole.
        msg["Reply-To"] = sender
    msg["To"] = ""  # filled by the sender (per-recipient envelope)
    msg["Date"] = formatdate(localtime=True)
    msg.set_content(text)
    msg.add_alternative(html_body, subtype="html")
    for cid, data, subtype in posters:
        msg.get_payload()[1].add_related(data, maintype="image", subtype=subtype, cid=cid)
    # Stable References anchor for threading follow-ups per batch. The domain
    # must be a real, dotted one (the sender's): a dot-less Message-ID domain
    # is a classic spam-filter signal.
    msg["Message-ID"] = make_msgid(domain=sender.rpartition("@")[2] if "@" in sender else None)
    return msg


def send_message(msg: EmailMessage, to_address: str) -> tuple[bool, str]:
    """Send one message over SMTP STARTTLS. Never raises: (ok, error)."""
    settings = get_settings()
    if not is_email_configured():
        return False, "email not configured"
    try:
        with smtplib.SMTP(settings.smtp_host.strip(), int(settings.smtp_port), timeout=20) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(settings.smtp_user.strip(), settings.smtp_password)
            del msg["To"]
            msg["To"] = to_address
            smtp.send_message(msg)
        return True, ""
    except Exception as exc:
        logger.warning("batch email send failed (%s)", type(exc).__name__)
        return False, type(exc).__name__
