"""Background playback-credential probe (see b2_presign.credential_proven).

Every ``media_playback_credential_probe_seconds`` the probe HEADs the most
recently verified PROD replica. Object-level problems (a deleted or corrupt
object) surface to the player as a playback error, which it recovers from or
reports; credential problems (revoked key, provider outage) are caught here
within one interval and send every grant back to the per-object HEAD path.
"""
import logging
import threading

from app.config import get_settings
from app.services import b2_presign

logger = logging.getLogger(__name__)


def probe_once(session_factory) -> bool:
    from app.models.media_backbone import MediaBlobLocation

    settings = get_settings()
    db = session_factory()
    try:
        location = (
            db.query(MediaBlobLocation)
            .filter(
                MediaBlobLocation.environment == "prod",
                MediaBlobLocation.bucket == settings.media_backbone_prod_bucket,
                MediaBlobLocation.verified.is_(True),
            )
            .order_by(MediaBlobLocation.id.desc())
            .first()
        )
        target = (location.bucket, location.object_key) if location else None
    finally:
        db.close()
    if target is None:
        b2_presign.record_credential_probe(False)
        return False
    return b2_presign.probe_credential(*target)


def start_probe(session_factory) -> threading.Event | None:
    """Run the probe on a daemon thread; returns its stop event (or None)."""
    settings = get_settings()
    interval = settings.media_playback_credential_probe_seconds
    if interval <= 0 or not (settings.user_auth_enabled and settings.b2_playback_canary_enabled):
        return None
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            try:
                ok = probe_once(session_factory)
                if not ok:
                    logger.warning("playback credential probe failed; grants use per-object HEAD")
            except Exception as exc:  # never kill the loop
                b2_presign.record_credential_probe(False)
                logger.warning("playback credential probe error: %s", type(exc).__name__)
            stop.wait(interval)

    threading.Thread(target=loop, name="b2-credential-probe", daemon=True).start()
    return stop
