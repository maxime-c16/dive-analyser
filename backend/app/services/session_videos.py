"""Shared sessions: B2 inbox -> session video (docs/features/SHARED_SESSIONS.md).

Arrival comes from B2 Event Notifications and from a periodic reconciliation
of the inbox prefix. Both call `ingest_object`, which is idempotent: the
(bucket, key) unique row is the identity, a conditional UPDATE claims the
probe, and another conditional UPDATE sends the owner notification once.

Metadata comes from ffprobe reading a short-lived presigned GET (range reads,
nothing is copied to the server). No SQL transaction is open while ffprobe or
B2 run. GPS tags are never read or stored. Signed URLs are never logged.
"""
from __future__ import annotations

import json
import logging
import subprocess
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from fractions import Fraction
from pathlib import PurePosixPath
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.session import Session as TrainingSession
from app.models.session_video import SessionVideo
from app.models.user_auth import AppUser

logger = logging.getLogger(__name__)

LOCAL_TZ = ZoneInfo("Europe/Paris")
VIDEO_SUFFIXES = (".mov", ".mp4", ".m4v")
MAX_ATTEMPTS = 5
PROBE_STALE_AFTER = timedelta(minutes=15)
PROBE_TIMEOUT_SECONDS = 180
PROBE_URL_TTL_SECONDS = 600
# Bounds per reconciliation pass: listed keys and probes started.
RECONCILE_MAX_KEYS = 2000
RECONCILE_MAX_INGESTS = 20
_probe_slots = threading.BoundedSemaphore(2)


class SessionsStorageUnavailable(Exception):
    """The sessions bucket credential is missing or the provider failed."""


# --------------------------------------------------------------------- B2 ---

_client_lock = threading.Lock()
_client = None
_client_fingerprint = None


def _fingerprint():
    s = get_settings()
    key_id, secret = s.sessions_b2_key_id.strip(), s.sessions_b2_key_secret.strip()
    region = s.sessions_b2_region.strip()
    if not (key_id and secret and region and s.sessions_b2_bucket.strip()):
        return None
    endpoint = (s.sessions_b2_endpoint_url or f"https://s3.{region}.backblazeb2.com").strip()
    return key_id, secret, region, endpoint


def storage_client():
    """Cached S3 client for the sessions bucket (separate from media keys)."""
    global _client, _client_fingerprint
    fingerprint = _fingerprint()
    if fingerprint is None:
        raise SessionsStorageUnavailable("sessions bucket credential not configured")
    with _client_lock:
        if _client is None or _client_fingerprint != fingerprint:
            import boto3
            from botocore.config import Config

            key_id, secret, region, endpoint = fingerprint
            _client = boto3.client(
                "s3", endpoint_url=endpoint, region_name=region,
                aws_access_key_id=key_id, aws_secret_access_key=secret,
                config=Config(connect_timeout=5, read_timeout=30, retries={"total_max_attempts": 3},
                              signature_version="s3v4"),
            )
            _client_fingerprint = fingerprint
    return _client


def presign_get(bucket: str, key: str, ttl: int, *, content_type: str | None = None,
                download_name: str | None = None) -> str:
    params = {"Bucket": bucket, "Key": key}
    if content_type:
        params["ResponseContentType"] = content_type
    if download_name:
        params["ResponseContentDisposition"] = f'attachment; filename="{_safe_filename(download_name)}"'
    try:
        return storage_client().generate_presigned_url("get_object", Params=params, ExpiresIn=int(ttl))
    except SessionsStorageUnavailable:
        raise
    except Exception as exc:  # never include the URL or credential
        raise SessionsStorageUnavailable(type(exc).__name__) from None


def _safe_filename(name: str) -> str:
    cleaned = "".join(c for c in PurePosixPath(name).name if c.isalnum() or c in "._- ")
    return cleaned[:120] or "session.mov"


def is_session_video_key(key: str) -> bool:
    prefix = get_settings().sessions_b2_inbox_prefix
    return (
        bool(key)
        and key.startswith(prefix)
        and len(key) > len(prefix)
        and not key.endswith("/")
        and key.lower().endswith(VIDEO_SUFFIXES)
    )


# ------------------------------------------------------------------ probe ---

@dataclass
class ProbeResult:
    duration_seconds: Optional[float]
    recorded_at: Optional[datetime]  # aware
    video_codec: Optional[str]
    video_profile: Optional[str]
    codec_string: Optional[str]
    audio_codec_string: Optional[str]
    pix_fmt: Optional[str]
    color_transfer: Optional[str]
    width: Optional[int]
    height: Optional[int]
    fps: Optional[float]
    bit_rate: Optional[int]


def run_ffprobe(url: str) -> dict:
    """ffprobe over HTTP range reads. Errors never echo the signed URL."""
    with _probe_slots:
        try:
            completed = subprocess.run(
                ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", url],
                capture_output=True, text=True, timeout=PROBE_TIMEOUT_SECONDS, check=False,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("ffprobe timed out") from None
        except OSError:
            raise RuntimeError("ffprobe unavailable") from None
    if completed.returncode != 0:
        raise RuntimeError(f"ffprobe exited {completed.returncode}")
    try:
        return json.loads(completed.stdout or "{}")
    except ValueError:
        raise RuntimeError("ffprobe output unreadable") from None


def _int(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and number >= 0 else None


def _rate(value) -> Optional[float]:
    try:
        fraction = Fraction(str(value))
    except (ValueError, ZeroDivisionError):
        return None
    return round(float(fraction), 3) if fraction > 0 else None


def parse_recorded_at(tags: dict) -> Optional[datetime]:
    """Apple's local creation date first (carries the offset), then UTC."""
    apple = (tags or {}).get("com.apple.quicktime.creationdate")
    if apple:
        try:
            return datetime.strptime(apple, "%Y-%m-%dT%H:%M:%S%z")
        except ValueError:
            pass
    generic = (tags or {}).get("creation_time")
    if generic:
        try:
            parsed = datetime.fromisoformat(generic.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


_H264_PROFILES = {"Baseline": 66, "Constrained Baseline": 66, "Main": 77, "Extended": 88, "High": 100,
                  "High 10": 110, "High 4:2:2": 122, "High 4:4:4 Predictive": 244}
_HEVC_PROFILES = {"Main": (1, 6), "Main 10": (2, 4), "Main Still Picture": (3, 8), "Rext": (4, 16)}


def codec_string(stream: dict) -> Optional[str]:
    """RFC 6381 codecs value for MediaCapabilities/canPlayType."""
    name = stream.get("codec_name")
    profile = stream.get("profile") or ""
    level = _int(stream.get("level"))
    if name == "hevc":
        tag = stream.get("codec_tag_string") if stream.get("codec_tag_string") in ("hvc1", "hev1") else "hvc1"
        idc, compat = _HEVC_PROFILES.get(profile, (1, 6))
        return f"{tag}.{idc}.{compat}.L{level or 120}.B0"
    if name == "h264":
        idc = _H264_PROFILES.get(profile, 100)
        return f"avc1.{idc:02X}00{(level or 40):02X}"
    if name == "aac":
        return "mp4a.40.5" if profile == "HE-AAC" else "mp4a.40.2"
    if name == "av1":
        return "av01.0.08M.08"
    return None


def parse_probe(data: dict) -> ProbeResult:
    """Keep playback-relevant fields only; location tags are never read."""
    streams = data.get("streams") or []
    fmt = data.get("format") or {}
    video = next((s for s in streams if s.get("codec_type") == "video" and s.get("codec_name")), {})
    audio = next((s for s in streams if s.get("codec_type") == "audio" and s.get("codec_name")), {})
    duration = _float(fmt.get("duration")) or _float(video.get("duration"))
    return ProbeResult(
        duration_seconds=round(duration, 3) if duration else None,
        recorded_at=parse_recorded_at(fmt.get("tags") or {}) or parse_recorded_at(video.get("tags") or {}),
        video_codec=(video.get("codec_name") or None),
        video_profile=(video.get("profile") or None),
        codec_string=codec_string(video) if video else None,
        audio_codec_string=codec_string(audio) if audio else None,
        pix_fmt=video.get("pix_fmt") or None,
        color_transfer=video.get("color_transfer") or None,
        width=_int(video.get("width")),
        height=_int(video.get("height")),
        fps=_rate(video.get("avg_frame_rate")) or _rate(video.get("r_frame_rate")),
        bit_rate=_int(fmt.get("bit_rate")),
    )


def local_day(recorded_at: Optional[datetime], fallback: datetime) -> tuple[datetime, date]:
    """UTC naive timestamp + Europe/Paris training day."""
    aware = recorded_at or (fallback if fallback.tzinfo else fallback.replace(tzinfo=timezone.utc))
    return aware.astimezone(timezone.utc).replace(tzinfo=None), aware.astimezone(LOCAL_TZ).date()


# ------------------------------------------------------------- ingestion ---

def resolve_owner(db: Session) -> Optional[AppUser]:
    email = get_settings().shared_sessions_owner_email.strip().lower()
    if not email:
        return None
    user = db.query(AppUser).filter(AppUser.email == email).first()
    return user if user is not None and user.is_active else None


def _get_or_create_row(db: Session, bucket: str, key: str, owner_id: int, size: Optional[int]) -> SessionVideo:
    row = db.query(SessionVideo).filter_by(bucket=bucket, object_key=key).first()
    if row is not None:
        return row
    row = SessionVideo(bucket=bucket, object_key=key, owner_user_id=owner_id, size_bytes=size, status="pending")
    db.add(row)
    try:
        db.commit()
    except IntegrityError:  # concurrent event/reconciliation created it
        db.rollback()
        row = db.query(SessionVideo).filter_by(bucket=bucket, object_key=key).one()
    return row


def _claim(db: Session, video_id: int) -> bool:
    now = datetime.utcnow()
    result = db.execute(
        update(SessionVideo)
        .where(
            SessionVideo.id == video_id,
            or_(
                SessionVideo.status == "pending",
                and_(SessionVideo.status == "probing", SessionVideo.claimed_at < now - PROBE_STALE_AFTER),
                and_(SessionVideo.status == "failed", SessionVideo.attempts < MAX_ATTEMPTS),
            ),
        )
        .values(status="probing", claimed_at=now, attempts=SessionVideo.attempts + 1, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    db.expire_all()  # Core UPDATE: never trust identity-map copies afterwards
    return result.rowcount == 1


def training_session_for(db: Session, day: date) -> TrainingSession:
    existing = db.query(TrainingSession).filter_by(date=day).first()
    if existing is not None:
        return existing
    try:
        with db.begin_nested():
            created = TrainingSession(date=day, total_dives=0, total_personal_dives=0)
            db.add(created)
        return created
    except IntegrityError:
        return db.query(TrainingSession).filter_by(date=day).one()


def ingest_object(db: Session, key: str, *, size: Optional[int] = None,
                  event_time: Optional[datetime] = None) -> Optional[SessionVideo]:
    """Idempotently turn one inbox object into a ready session video.

    Returns the row (ready, failed or claimed by someone else), or None when
    the key is not a session video or no owner is configured.
    """
    settings = get_settings()
    bucket = settings.sessions_b2_bucket
    if not is_session_video_key(key):
        return None
    existing = db.query(SessionVideo).filter_by(bucket=bucket, object_key=key).first()
    if existing is not None and existing.status == "ready":
        _notify_once(db, existing.id)
        return existing
    owner = resolve_owner(db)
    if owner is None:
        logger.warning("shared sessions: owner account missing; ingestion skipped")
        return None
    row = existing or _get_or_create_row(db, bucket, key, owner.id, size)
    video_id = row.id
    if not _claim(db, video_id):
        db.refresh(row)
        return row
    try:
        client = storage_client()
        head = client.head_object(Bucket=bucket, Key=key)
        url = presign_get(bucket, key, PROBE_URL_TTL_SECONDS)
        probe = parse_probe(run_ffprobe(url))
        if not probe.video_codec:
            raise RuntimeError("no video stream")
    except Exception as exc:
        message = str(exc) if isinstance(exc, (RuntimeError, SessionsStorageUnavailable)) else type(exc).__name__
        db.rollback()
        db.execute(update(SessionVideo).where(SessionVideo.id == video_id)
                   .values(status="failed", last_error=message[:200], updated_at=datetime.utcnow())
                   .execution_options(synchronize_session=False))
        db.commit()
        db.expire_all()
        logger.warning("shared sessions: probe failed for video %s (%s)", video_id, message[:80])
        return db.get(SessionVideo, video_id)

    fallback = head.get("LastModified") or event_time or datetime.now(timezone.utc)
    recorded_at, day = local_day(probe.recorded_at, fallback)
    row = db.get(SessionVideo, video_id)
    training = training_session_for(db, day)
    db.flush()
    for field in ("duration_seconds", "video_codec", "video_profile", "codec_string", "audio_codec_string",
                  "pix_fmt", "color_transfer", "width", "height", "fps", "bit_rate"):
        setattr(row, field, getattr(probe, field))
    row.size_bytes = _int(head.get("ContentLength")) or size or row.size_bytes
    row.etag = (head.get("ETag") or "").strip('"')[:80] or None
    row.recorded_at, row.recorded_date = recorded_at, day
    row.session_id = training.id
    row.status, row.last_error, row.claimed_at = "ready", None, None
    db.commit()
    logger.info("shared sessions: video %s ready (session %s)", video_id, training.id)
    _notify_once(db, video_id)
    return db.get(SessionVideo, video_id)


def ingest_in_background(key: str, size: Optional[int] = None, event_time: Optional[datetime] = None) -> None:
    """Webhook/reconciliation entry: own DB session, never raises."""
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        ingest_object(db, key, size=size, event_time=event_time)
    except Exception as exc:
        logger.error("shared sessions: ingestion failed (%s)", type(exc).__name__)
        db.rollback()
    finally:
        db.close()


def reconcile(db: Session) -> int:
    """List the inbox and ingest objects that are not ready. Bounded."""
    settings = get_settings()
    bucket, prefix = settings.sessions_b2_bucket, settings.sessions_b2_inbox_prefix
    client = storage_client()
    candidates: list[tuple[str, int, datetime]] = []
    token, listed = None, 0
    while listed < RECONCILE_MAX_KEYS:
        kwargs = {"Bucket": bucket, "Prefix": prefix, "MaxKeys": 1000}
        if token:
            kwargs["ContinuationToken"] = token
        page = client.list_objects_v2(**kwargs)
        objects = page.get("Contents") or []
        listed += len(objects)
        keys = [o["Key"] for o in objects if is_session_video_key(o["Key"])]
        done = set()
        if keys:
            done = {k for (k,) in db.query(SessionVideo.object_key).filter(
                SessionVideo.bucket == bucket, SessionVideo.object_key.in_(keys),
                or_(SessionVideo.status == "ready",
                    and_(SessionVideo.status == "failed", SessionVideo.attempts >= MAX_ATTEMPTS)))}
        db.rollback()
        candidates += [(o["Key"], o.get("Size"), o.get("LastModified")) for o in objects
                       if is_session_video_key(o["Key"]) and o["Key"] not in done]
        token = page.get("NextContinuationToken")
        if not page.get("IsTruncated") or not token:
            break
    started = 0
    for key, size, modified in candidates[:RECONCILE_MAX_INGESTS]:
        row = ingest_object(db, key, size=size, event_time=modified)
        started += 1 if row is not None else 0
    return started


_worker_stop: Optional[threading.Event] = None


def start_reconciler() -> Optional[threading.Event]:
    """Every SESSIONS_RECONCILE_SECONDS while the feature is on."""
    settings = get_settings()
    if not settings.shared_sessions_enabled:
        return None
    stop = threading.Event()

    def loop():
        from app.database import SessionLocal

        if stop.wait(15):  # let startup finish first
            return
        while True:
            db = SessionLocal()
            try:
                count = reconcile(db)
                if count:
                    logger.info("shared sessions: reconciliation handled %s object(s)", count)
            except SessionsStorageUnavailable as exc:
                logger.warning("shared sessions: reconciliation skipped (%s)", str(exc)[:80])
            except Exception as exc:
                logger.error("shared sessions: reconciliation failed (%s)", type(exc).__name__)
            finally:
                db.rollback()
                db.close()
            if stop.wait(max(60, settings.sessions_reconcile_seconds)):
                return

    threading.Thread(target=loop, name="session-reconciler", daemon=True).start()
    return stop


# ---------------------------------------------------------- notification ---

def _format_size(size: Optional[int]) -> str:
    if not size:
        return ""
    gb = size / 1_000_000_000
    return f"{gb:.1f} Go".replace(".", ",") if gb >= 1 else f"{round(size / 1_000_000)} Mo"


def describe(video: SessionVideo) -> str:
    parts = [video.recorded_date.strftime("%d/%m/%Y") if video.recorded_date else ""]
    if video.duration_seconds:
        parts.append(f"{round(video.duration_seconds / 60)} min")
    parts.append(_format_size(video.size_bytes))
    return " · ".join(p for p in parts if p)


def _notify_once(db: Session, video_id: int) -> None:
    """Exactly one owner notification per video, whatever the event count."""
    result = db.execute(
        update(SessionVideo)
        .where(SessionVideo.id == video_id, SessionVideo.status == "ready", SessionVideo.notified_at.is_(None))
        .values(notified_at=datetime.utcnow())
        .execution_options(synchronize_session=False)
    )
    db.commit()
    db.expire_all()
    if result.rowcount != 1:
        return
    video = db.get(SessionVideo, video_id)
    try:
        notify_owner(db, video)
    except Exception as exc:
        logger.error("shared sessions: owner notification failed (%s)", type(exc).__name__)
        db.rollback()


def notify_owner(db: Session, video: SessionVideo) -> None:
    from app.services import notification_service, push_service, telegram

    settings = get_settings()
    base = settings.app_public_url.rstrip("/")
    member_path = f"/session-videos/{video.id}"
    summary = describe(video)
    row = notification_service.create(
        db, user_id=video.owner_user_id, type="session_video", title="Nouvelle séance en ligne",
        body=summary, defer_push=True,
    )
    if row is not None:
        row._push_payload = {"title": row.title, "body": row.body or "", "url": member_path}
        push_service.fanout_for_rows(db, [row])
    if telegram.configured():
        # The guest secret exists only in this message (only its hash is stored).
        from app.api.v1.session_videos import issue_share

        path = issue_share(db, video, video.owner_user_id)
        lines = [f"Nouvelle séance : {summary}", f"Lien invité : {base}{path}", f"Dans l'app : {base}{member_path}"]
        telegram.send("\n".join(lines))
