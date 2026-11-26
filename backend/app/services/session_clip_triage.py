"""Session clip auto-detection runs, fast triage, GT export, and Mac cut leases.

Bridges full-session videos (`session_videos`) to individual library dives
(`dives` + `deposit_batches`) without losing detector iterations or forcing
ffmpeg transcoding on false positives.
"""
from __future__ import annotations

import base64
import bisect
import json
import logging
import math
import re
import uuid
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import Float, String, and_, case, cast, exists, func, literal, or_, select, union_all
from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from app.models.dd_lookup import DDLookup
from app.models.deposit_batch import BatchEmailOutbox
from app.models.dive import Dive
from app.models.diver import Diver
from app.models.media import MediaCacheEntry
from app.models.media_backbone import MediaBlob, MediaBlobLocation, MediaRevision
from app.models.photos_asset import PhotosAsset
from app.models.session import Session as TrainingSession
from app.models.session_clip_triage import (
    SessionClipCandidate,
    SessionClipOrphanObject,
    SessionClipRun,
    SessionClipRunMatch,
)
from app.models.session_video import SessionVideo
from app.models.user_auth import AppUser, UserDiverAccess
from app.services import browser_upload, deposit_batches
from app.services import session_videos as sv_service
from app.services.dive_access import CONTEXT_KEY, owned_diver_ids, unscoped_reads
from app.services.dive_code_parser import DiveCodeParser
from app.services.diver_identity import invalidate_analysis_cache
from app.services.media_backbone import commit_verified_ingest
from app.services.media_keys import build_media_key
from app.services.performance_scoring import ORDINAL_SCORE
from app.services.phase_validator import PhaseValidator

logger = logging.getLogger(__name__)

MAX_CANDIDATES_PER_RUN = 500
MAX_PAGE_LIMIT = 100
DEFAULT_PAGE_LIMIT = 50
MAX_GT_PAGE_LIMIT = 500
DEDUP_IOU_MIN = 0.35
DEDUP_MIDPOINT_PAD_S = 1.5
DEDUP_WINDOW_PAD_S = 15.0
MAX_EXTRACTION_ATTEMPTS = 5
CUT_LEASE_TTL = timedelta(minutes=10)
CUT_SOURCE_URL_TTL_SECONDS = 900
MAX_CLIP_SPAN_S = 60.0
MIN_CLIP_SPAN_S = 0.5
TRIM_EPSILON_S = 0.01
VALID_HEIGHTS = {"1m", "3m", "5m", "7.5m", "10m"}
VALID_RATINGS = {"F", "B", "M", "G", "P"}
VALID_REJECT_REASONS = {"false_positive", "duplicate", "incomplete", "other"}

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_QUERY_SECRET_RE = re.compile(r"\?[^\s\"']+")


def sanitize_worker_error(message: str) -> str:
    """Strip any presigned URLs or query credentials before storing/returning errors."""
    cleaned = _URL_RE.sub("[redacted-url]", message or "")
    cleaned = _QUERY_SECRET_RE.sub("", cleaned)
    cleaned = " ".join(cleaned.split()).strip()
    return cleaned[:240] or "Extraction failed"


def interval_iou(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    inter = max(0.0, min(a_end, b_end) - max(a_start, b_start))
    if inter <= 0.0:
        return 0.0
    union = max(a_end, b_end) - min(a_start, b_start)
    return inter / union if union > 0.0 else 0.0


def _intervals_match(a_start: float, a_end: float, b_start: float, b_end: float) -> tuple[bool, float]:
    iou = interval_iou(a_start, a_end, b_start, b_end)
    if iou >= DEDUP_IOU_MIN:
        return True, iou
    a_mid = 0.5 * (a_start + a_end)
    b_mid = 0.5 * (b_start + b_end)
    if (b_start - DEDUP_MIDPOINT_PAD_S <= a_mid <= b_end + DEDUP_MIDPOINT_PAD_S) and (
        a_start - DEDUP_MIDPOINT_PAD_S <= b_mid <= a_end + DEDUP_MIDPOINT_PAD_S
    ):
        return True, iou
    return False, iou


def is_metadata_complete(candidate: SessionClipCandidate) -> bool:
    return bool(
        candidate.diver_id is not None
        and candidate.dive_code
        and candidate.height
        and candidate.performance
    )


def _incomplete_clause():
    """Single canonical SQL predicate for kept unpublished clips still needing metadata or publish confirmation."""
    return and_(
        SessionClipCandidate.triage_status == "kept",
        SessionClipCandidate.dive_id.is_(None),
        or_(
            SessionClipCandidate.diver_id.is_(None),
            SessionClipCandidate.dive_code.is_(None),
            SessionClipCandidate.height.is_(None),
            SessionClipCandidate.performance.is_(None),
            SessionClipCandidate.publish_requested_at.is_(None),
            SessionClipCandidate.publish_requested_by_user_id.is_(None),
            SessionClipCandidate.extraction_status == "ready",
        ),
    )


def can_manage_video(user: Optional[AppUser], video: SessionVideo) -> bool:
    return bool(user and user.is_active and (user.is_admin or user.id == video.owner_user_id))


def _manageable_video_filter(user: AppUser):
    base = [SessionVideo.status == "ready", SessionVideo.deleted_at.is_(None)]
    if not user.is_admin:
        base.append(SessionVideo.owner_user_id == user.id)
    return base


def _user_can_manage_any_video(db: Session, user: Optional[AppUser]) -> bool:
    if not user or not user.is_active:
        return False
    if user.is_admin:
        return True
    return db.query(SessionVideo.id).filter(*_manageable_video_filter(user)).limit(1).first() is not None


def _validated_span(start_raw: float, end_raw: float) -> tuple[float, float]:
    s_val = float(start_raw)
    e_val = float(end_raw)
    if not (math.isfinite(s_val) and math.isfinite(e_val)):
        raise HTTPException(422, "Clip bounds must be finite numbers")
    if s_val < 0.0 or e_val <= s_val:
        raise HTTPException(422, "Invalid clip bounds")
    span = e_val - s_val
    if span < MIN_CLIP_SPAN_S:
        raise HTTPException(422, f"Clip duration must be at least {MIN_CLIP_SPAN_S}s")
    if span > MAX_CLIP_SPAN_S:
        raise HTTPException(422, f"Clip duration cannot exceed {int(MAX_CLIP_SPAN_S)}s")
    return s_val, e_val


DEDUP_SQL_BATCH_SIZE = 100
# Every candidate satisfies end_s - start_s <= MAX_CLIP_SPAN_S (60s), so
# end_s >= sub_s - DEDUP_WINDOW_PAD_S implies start_s >= sub_s - DEDUP_START_LOOKBACK_S.
DEDUP_START_LOOKBACK_S = MAX_CLIP_SPAN_S + DEDUP_WINDOW_PAD_S
GT_STREAM_CHUNK_SIZE = 200
GT_STREAM_RUN_CHUNK_SIZE = 100
GT_EXPORT_MAX_BYTES = 2 * 1024 * 1024  # 2 MiB hard response-byte budget per export page
GT_EXPORT_MIN_BYTES = 4096
GT_EXPORT_MAX_CHUNKS = 25
ORPHAN_B2_GRACE_PERIOD = timedelta(hours=24)
ORPHAN_DELETE_CLAIM_TTL = timedelta(minutes=10)
ORPHAN_B2_RETRY_BACKOFF = timedelta(minutes=30)
MAX_ORPHAN_RECLAIM_BATCH = 20


def _sql_max2(a, b):
    return case((a >= b, a), else_=b)


def _sql_min2(a, b):
    return case((a <= b, a), else_=b)


def _sql_interval_match(sub_s, sub_e, cand_s, cand_e):
    """Exact SQL mirror of `_intervals_match` portable across SQLite and PostgreSQL."""
    inter = _sql_max2(literal(0.0), _sql_min2(sub_e, cand_e) - _sql_max2(sub_s, cand_s))
    union = _sql_max2(sub_e, cand_e) - _sql_min2(sub_s, cand_s)
    iou = case((and_(inter > 0.0, union > 0.0), inter / union), else_=literal(0.0))
    sub_mid = (sub_s + sub_e) * literal(0.5)
    cand_mid = (cand_s + cand_e) * literal(0.5)
    mid_ok = and_(
        sub_mid >= cand_s - DEDUP_MIDPOINT_PAD_S,
        sub_mid <= cand_e + DEDUP_MIDPOINT_PAD_S,
        cand_mid >= sub_s - DEDUP_MIDPOINT_PAD_S,
        cand_mid <= sub_e + DEDUP_MIDPOINT_PAD_S,
    )
    ok = or_(iou >= DEDUP_IOU_MIN, mid_ok)
    return ok, iou


DEDUP_SCAN_PAGE_ROWS = 500


def _find_best_db_matches(
    db: Session,
    video_id: int,
    valid_items: list[tuple[float, float, Optional[float], Optional[str], Optional[dict[str, Any]]]],
) -> tuple[dict[int, tuple[float, int]], dict[int, SessionClipCandidate]]:
    """Match submitted intervals against ALL historical candidates in bounded, resumable batches.

    Submitted items are sorted by start and processed in chunks of `DEDUP_SQL_BATCH_SIZE`.
    For each chunk and each bound family (original, trimmed), historical candidates in the
    chunk's time window are paged by keyset `(start, id)` at most `DEDUP_SCAN_PAGE_ROWS`
    at a time; each page is matched and ranked in SQL (`ROW_NUMBER` over at most
    chunk x page pairs) and the per-item best is carried across pages in Python with the
    same `(score DESC, id ASC)` order. No query ranks an unbounded history, and every
    historical row is still considered, so prior triage decisions are never missed.
    """
    if not valid_items:
        return {}, {}

    best_by_idx: dict[int, tuple[float, int]] = {}

    def _keep_best(idx: int, score: float, cid: int) -> None:
        current = best_by_idx.get(idx)
        if current is None or score > current[0] or (score == current[0] and cid < current[1]):
            best_by_idx[idx] = (score, cid)

    order = sorted(range(len(valid_items)), key=lambda i: (valid_items[i][0], valid_items[i][1]))
    bound_families = (
        (SessionClipCandidate.start_s, SessionClipCandidate.end_s),
        (SessionClipCandidate.trimmed_start_s, SessionClipCandidate.trimmed_end_s),
    )

    for batch_start in range(0, len(order), DEDUP_SQL_BATCH_SIZE):
        chunk_idx = order[batch_start : batch_start + DEDUP_SQL_BATCH_SIZE]
        sub_selects = [
            select(
                literal(i).label("idx"),
                cast(literal(float(valid_items[i][0])), Float).label("s"),
                cast(literal(float(valid_items[i][1])), Float).label("e"),
            )
            for i in chunk_idx
        ]
        submitted_cte = (
            sub_selects[0].cte("submitted_clips")
            if len(sub_selects) == 1
            else union_all(*sub_selects).cte("submitted_clips")
        )
        sub_s = submitted_cte.c.s
        sub_e = submitted_cte.c.e
        lo = min(valid_items[i][0] for i in chunk_idx) - DEDUP_START_LOOKBACK_S
        hi = max(valid_items[i][1] for i in chunk_idx) + DEDUP_WINDOW_PAD_S
        end_floor = min(valid_items[i][0] for i in chunk_idx) - DEDUP_WINDOW_PAD_S

        for start_col, end_col in bound_families:
            ok, iou = _sql_interval_match(sub_s, sub_e, start_col, end_col)
            last_key: Optional[tuple[float, int]] = None
            while True:
                page_q = db.query(SessionClipCandidate.id, start_col).filter(
                    SessionClipCandidate.session_video_id == video_id,
                    start_col.is_not(None),
                    start_col >= lo,
                    start_col <= hi,
                    end_col >= end_floor,
                )
                if last_key is not None:
                    page_q = page_q.filter(
                        or_(
                            start_col > last_key[0],
                            and_(start_col == last_key[0], SessionClipCandidate.id > last_key[1]),
                        )
                    )
                page = page_q.order_by(start_col, SessionClipCandidate.id).limit(DEDUP_SCAN_PAGE_ROWS).all()
                if not page:
                    break
                page_ids = [int(cid) for cid, _ in page]
                matches = (
                    select(
                        submitted_cte.c.idx.label("idx"),
                        SessionClipCandidate.id.label("cid"),
                        iou.label("score"),
                    )
                    .select_from(submitted_cte)
                    .join(
                        SessionClipCandidate,
                        and_(
                            SessionClipCandidate.id.in_(page_ids),
                            start_col >= sub_s - DEDUP_START_LOOKBACK_S,
                            start_col <= sub_e + DEDUP_WINDOW_PAD_S,
                            end_col >= sub_s - DEDUP_WINDOW_PAD_S,
                            ok,
                        ),
                    )
                    .subquery("dedup_matches")
                )
                ranked = (
                    select(
                        matches.c.idx,
                        matches.c.cid,
                        matches.c.score,
                        func.row_number()
                        .over(partition_by=matches.c.idx, order_by=(matches.c.score.desc(), matches.c.cid.asc()))
                        .label("rn"),
                    )
                    .subquery()
                )
                for orig_idx, score, cid in db.execute(
                    select(ranked.c.idx, ranked.c.score, ranked.c.cid).where(ranked.c.rn == 1)
                ).all():
                    _keep_best(int(orig_idx), float(score), int(cid))
                if len(page) < DEDUP_SCAN_PAGE_ROWS:
                    break
                last_key = (float(page[-1][1]), page_ids[-1])

    matched_ids = sorted({cid for _, cid in best_by_idx.values()})
    matched_rows: dict[int, SessionClipCandidate] = {}
    for pos in range(0, len(matched_ids), 200):
        chunk_ids = matched_ids[pos : pos + 200]
        for row in db.query(SessionClipCandidate).filter(SessionClipCandidate.id.in_(chunk_ids)).all():
            matched_rows[row.id] = row
    return best_by_idx, matched_rows


def submit_clip_run(
    db: Session,
    *,
    video_id: int,
    detector_name: str,
    detector_version: str,
    candidates: list[dict[str, Any]],
    params_json: Optional[dict[str, Any]] = None,
    submitted_by: Optional[AppUser] = None,
) -> dict[str, Any]:
    """Ingest a detection run with temporal deduplication (cross-run & intra-run).

    Locks the SessionVideo row so concurrent runs never double-insert the same
    interval. Existing triaged decisions (kept / rejected / trimmed bounds) are
    always preserved. Uniform 404 prevents video-existence oracles.
    """
    if len(candidates) > MAX_CANDIDATES_PER_RUN:
        raise HTTPException(422, f"At most {MAX_CANDIDATES_PER_RUN} candidates per run")

    video = (
        db.query(SessionVideo)
        .filter(
            SessionVideo.id == video_id,
            SessionVideo.status == "ready",
            SessionVideo.deleted_at.is_(None),
        )
        .with_for_update()
        .first()
    )
    if video is None or (submitted_by is not None and not can_manage_video(submitted_by, video)):
        raise HTTPException(404, "Session video not found")

    duration_cap = float(video.duration_seconds) if video.duration_seconds else None

    # Validate & filter submitted intervals before querying the temporal window.
    valid_items: list[tuple[float, float, Optional[float], Optional[str], Optional[dict[str, Any]]]] = []
    for item in candidates:
        s_val = float(item["start_s"])
        e_val = float(item["end_s"])
        if not (math.isfinite(s_val) and math.isfinite(e_val)):
            continue
        if duration_cap is not None:
            # Drop completely out-of-range detections instead of clamping fake EOF clips.
            if s_val >= duration_cap - MIN_CLIP_SPAN_S or e_val <= 0.0:
                continue
            s_val = max(0.0, s_val)
            e_val = min(duration_cap, e_val)
        if s_val < 0.0 or e_val - s_val < MIN_CLIP_SPAN_S:
            continue
        if e_val - s_val > MAX_CLIP_SPAN_S:
            e_val = s_val + MAX_CLIP_SPAN_S
        confidence = item.get("confidence")
        conf_val = (
            float(confidence)
            if confidence is not None and math.isfinite(float(confidence))
            else None
        )
        label = (str(item["label"]).strip()[:80] or None) if item.get("label") else None
        meta = item.get("meta") if isinstance(item.get("meta"), dict) else None
        valid_items.append((round(s_val, 3), round(e_val, 3), conf_val, label, meta))

    best_db_by_idx, matched_db_rows = _find_best_db_matches(db, video.id, valid_items)

    run = SessionClipRun(
        session_video_id=video.id,
        detector_name=detector_name.strip()[:80],
        detector_version=detector_version.strip()[:80],
        params_json=params_json,
        submitted_by_user_id=submitted_by.id if submitted_by else None,
        submitted_count=len(candidates),
        created_count=0,
        deduped_count=0,
    )
    db.add(run)
    db.flush()

    matched_in_run: dict[int, SessionClipRunMatch] = {}
    created_count = 0
    deduped_count = 0
    preserved_triaged_count = 0
    now = datetime.utcnow()

    # Maintain sorted index of newly created candidates in THIS run for intra-run dedup.
    newly_created: list[tuple[float, float, SessionClipCandidate]] = []
    newly_starts: list[float] = []
    max_new_span = MAX_CLIP_SPAN_S

    for idx, (start_s, end_s, conf_val, label, meta) in enumerate(valid_items):
        best_candidate: Optional[SessionClipCandidate] = None
        best_iou = -1.0

        db_hit = best_db_by_idx.get(idx)
        if db_hit is not None:
            best_iou, cid = db_hit
            best_candidate = matched_db_rows.get(cid)

        lo = bisect.bisect_left(newly_starts, start_s - max_new_span - DEDUP_WINDOW_PAD_S)
        hi = bisect.bisect_right(newly_starts, end_s + DEDUP_WINDOW_PAD_S)
        for _, cand_max_end, cand in newly_created[lo:hi]:
            if cand_max_end < start_s - DEDUP_WINDOW_PAD_S:
                continue
            ok_new, iou_new = _intervals_match(start_s, end_s, cand.start_s, cand.end_s)
            if ok_new and iou_new > best_iou:
                best_iou = iou_new
                best_candidate = cand

        if best_candidate is not None:
            deduped_count += 1
            if best_candidate.triage_status != "pending":
                if best_candidate.id not in matched_in_run:
                    preserved_triaged_count += 1
            else:
                best_candidate.latest_run_id = run.id
                if conf_val is not None and (
                    best_candidate.confidence is None or conf_val > best_candidate.confidence
                ):
                    best_candidate.confidence = conf_val
                best_candidate.updated_at = now

            prev_match = matched_in_run.get(best_candidate.id)
            if prev_match is None:
                match = SessionClipRunMatch(
                    run_id=run.id,
                    candidate_id=best_candidate.id,
                    raw_start_s=start_s,
                    raw_end_s=end_s,
                    confidence=conf_val,
                    was_new=False,
                    overlap_iou=round(max(0.0, best_iou), 4),
                )
                db.add(match)
                matched_in_run[best_candidate.id] = match
            elif conf_val is not None and (
                prev_match.confidence is None or conf_val > prev_match.confidence
            ):
                prev_match.confidence = conf_val
            continue

        new_cand = SessionClipCandidate(
            session_video_id=video.id,
            first_run_id=run.id,
            latest_run_id=run.id,
            start_s=start_s,
            end_s=end_s,
            confidence=conf_val,
            detector_label=label,
            detector_meta=meta,
            triage_status="pending",
            extraction_status="none",
            visibility="private",
            created_at=now,
            updated_at=now,
        )
        db.add(new_cand)
        db.flush()
        pos = bisect.bisect_left(newly_starts, new_cand.start_s)
        newly_starts.insert(pos, new_cand.start_s)
        newly_created.insert(pos, (new_cand.start_s, new_cand.end_s, new_cand))
        max_new_span = max(max_new_span, new_cand.end_s - new_cand.start_s)
        created_count += 1
        match = SessionClipRunMatch(
            run_id=run.id,
            candidate_id=new_cand.id,
            raw_start_s=start_s,
            raw_end_s=end_s,
            confidence=conf_val,
            was_new=True,
            overlap_iou=1.0,
        )
        db.add(match)
        matched_in_run[new_cand.id] = match

    run.created_count = created_count
    run.deduped_count = deduped_count
    db.commit()
    db.refresh(run)

    return {
        "run_id": run.id,
        "session_video_id": video.id,
        "session_id": video.session_id,
        "detector_name": run.detector_name,
        "detector_version": run.detector_version,
        "submitted_count": run.submitted_count,
        "created_count": created_count,
        "deduped_count": deduped_count,
        "preserved_triaged_count": preserved_triaged_count,
        "created_at": run.created_at.replace(tzinfo=timezone.utc).isoformat(),
    }


def _triage_counts_for_sessions(
    db: Session,
    session_ids: list[int],
    user: Optional[AppUser],
) -> dict[int, dict[str, Any]]:
    """Bulk per-session triage counts for managers (one SQL aggregate query)."""
    if not session_ids or not user or not user.is_active:
        return {}
    filters = [
        SessionVideo.session_id.in_(session_ids),
        SessionVideo.status == "ready",
        SessionVideo.deleted_at.is_(None),
    ]
    if not user.is_admin:
        filters.append(SessionVideo.owner_user_id == user.id)

    try:
        rows = (
            db.query(
                SessionVideo.session_id,
                func.sum(case((SessionClipCandidate.triage_status == "pending", 1), else_=0)),
                func.sum(case((SessionClipCandidate.triage_status == "kept", 1), else_=0)),
                func.sum(case((_incomplete_clause(), 1), else_=0)),
                func.sum(case((SessionClipCandidate.triage_status == "rejected", 1), else_=0)),
                func.count(SessionClipCandidate.id),
            )
            .join(SessionVideo, SessionVideo.id == SessionClipCandidate.session_video_id)
            .filter(*filters)
            .group_by(SessionVideo.session_id)
            .all()
        )
    except (OperationalError, ProgrammingError):
        # Migration not yet applied: fail open on optional badge metadata.
        db.rollback()
        return {}

    counts: dict[int, dict[str, Any]] = {}
    for session_id, pending, kept, incomplete, rejected, total in rows:
        if session_id is None:
            continue
        counts[int(session_id)] = {
            "pending": int(pending or 0),
            "kept": int(kept or 0),
            "incomplete": int(incomplete or 0),
            "rejected": int(rejected or 0),
            "total": int(total or 0),
            "latest_detector": None,
            "latest_version": None,
        }

    if not counts:
        return counts

    # Latest run per *selected session*, ranked in SQL: one row per session in
    # `counts` (already bounded by the caller's session page), never one row
    # per video nor an IN list that grows with recordings.
    session_table = TrainingSession.__table__
    latest_run_id_subq = (
        select(SessionClipRun.id)
        .join(SessionVideo, SessionVideo.id == SessionClipRun.session_video_id)
        .where(SessionVideo.session_id == session_table.c.id, *filters)
        .order_by(SessionClipRun.created_at.desc(), SessionClipRun.id.desc())
        .limit(1)
        .correlate(session_table)
        .scalar_subquery()
    )
    latest_rows = (
        db.query(
            session_table.c.id,
            SessionClipRun.detector_name,
            SessionClipRun.detector_version,
        )
        .select_from(session_table)
        .join(SessionClipRun, SessionClipRun.id == latest_run_id_subq)
        .filter(session_table.c.id.in_(list(counts.keys())))
        .all()
    )
    for sid, det_name, det_ver in latest_rows:
        entry = counts.get(int(sid))
        if entry is not None:
            entry["latest_detector"] = det_name
            entry["latest_version"] = det_ver
    return counts


MAX_SESSION_PAGE_LIMIT = 100
DEFAULT_SESSION_PAGE_LIMIT = 50


def list_triage_sessions(
    db: Session,
    user: AppUser,
    *,
    q: Optional[str] = None,
    limit: int = DEFAULT_SESSION_PAGE_LIMIT,
    offset: int = 0,
) -> dict[str, Any]:
    """Bounded, paginated, searchable session selector with full-scope count."""
    if not _user_can_manage_any_video(db, user):
        return {"items": [], "total": 0, "has_more": False, "next_offset": None}

    bounded_limit = max(1, min(limit, MAX_SESSION_PAGE_LIMIT))
    bounded_offset = max(0, offset)
    filters = _manageable_video_filter(user)
    table = TrainingSession.__table__
    search_term = (q or "").strip()

    extra_filters: list[Any] = [SessionVideo.session_id.is_not(None)]
    if search_term:
        escaped = search_term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        extra_filters.append(cast(table.c.date, String).ilike(f"%{escaped}%", escape="\\"))

    total = int(
        db.query(func.count(func.distinct(SessionVideo.session_id)))
        .select_from(SessionClipCandidate)
        .join(SessionVideo, SessionVideo.id == SessionClipCandidate.session_video_id)
        .join(table, table.c.id == SessionVideo.session_id)
        .filter(*filters, *extra_filters)
        .scalar()
        or 0
    )

    rows = (
        db.query(
            SessionVideo.session_id,
            table.c.date,
            table.c.calendar_occurrence_id,
            func.sum(case((SessionClipCandidate.triage_status == "pending", 1), else_=0)),
            func.sum(case((_incomplete_clause(), 1), else_=0)),
            func.sum(
                case(
                    (SessionClipCandidate.extraction_status.in_(("queued", "claimed", "extracting")), 1),
                    else_=0,
                )
            ),
            func.sum(case((SessionClipCandidate.extraction_status == "published", 1), else_=0)),
            func.sum(case((SessionClipCandidate.triage_status == "rejected", 1), else_=0)),
        )
        .join(SessionVideo, SessionVideo.id == SessionClipCandidate.session_video_id)
        .join(table, table.c.id == SessionVideo.session_id)
        .filter(*filters, *extra_filters)
        .group_by(SessionVideo.session_id, table.c.date, table.c.calendar_occurrence_id)
        .order_by(table.c.date.desc(), SessionVideo.session_id.desc())
        .offset(bounded_offset)
        .limit(bounded_limit + 1)
        .all()
    )
    has_more = len(rows) > bounded_limit
    page = rows[:bounded_limit]

    occ_ids = [r[2] for r in page if r[2] is not None]
    titles: dict[int, str] = {}
    if occ_ids:
        from app.services.session_calendar import session_titles

        titles = session_titles(db, occ_ids)

    items = [
        {
            "session_id": int(sid),
            "date": day_date.isoformat(),
            "title": titles.get(occ_id) if occ_id else None,
            "pending": int(p or 0),
            "incomplete": int(inc or 0),
            "extracting": int(ext or 0),
            "published": int(pub or 0),
            "rejected": int(rej or 0),
        }
        for sid, day_date, occ_id, p, inc, ext, pub, rej in page
    ]
    return {
        "items": items,
        "total": total,
        "has_more": has_more,
        "next_offset": (bounded_offset + bounded_limit) if has_more else None,
    }


def get_triage_summary(db: Session, user: AppUser) -> dict[str, Any]:
    """Bounded global counts + first paginated slice of manageable sessions."""
    if not _user_can_manage_any_video(db, user):
        return {
            "can_manage": False,
            "pending_count": 0,
            "incomplete_count": 0,
            "extracting_count": 0,
            "published_count": 0,
            "rejected_count": 0,
            "sessions": [],
            "sessions_total": 0,
            "sessions_has_more": False,
            "sessions_next_offset": None,
        }

    filters = _manageable_video_filter(user)

    # 1. Global totals in a single 1-row SQL aggregate (full scope accurate).
    totals = (
        db.query(
            func.sum(case((SessionClipCandidate.triage_status == "pending", 1), else_=0)),
            func.sum(case((_incomplete_clause(), 1), else_=0)),
            func.sum(
                case(
                    (SessionClipCandidate.extraction_status.in_(("queued", "claimed", "extracting")), 1),
                    else_=0,
                )
            ),
            func.sum(case((SessionClipCandidate.extraction_status == "published", 1), else_=0)),
            func.sum(case((SessionClipCandidate.triage_status == "rejected", 1), else_=0)),
        )
        .join(SessionVideo, SessionVideo.id == SessionClipCandidate.session_video_id)
        .filter(*filters)
        .one()
    )

    sessions_page = list_triage_sessions(db, user, limit=DEFAULT_SESSION_PAGE_LIMIT, offset=0)

    return {
        "can_manage": True,
        "pending_count": int(totals[0] or 0),
        "incomplete_count": int(totals[1] or 0),
        "extracting_count": int(totals[2] or 0),
        "published_count": int(totals[3] or 0),
        "rejected_count": int(totals[4] or 0),
        "sessions": sessions_page["items"],
        "sessions_total": sessions_page["total"],
        "sessions_has_more": sessions_page["has_more"],
        "sessions_next_offset": sessions_page["next_offset"],
    }


MAX_DIVER_PAGE_LIMIT = 100
DEFAULT_DIVER_PAGE_LIMIT = 50
MAX_RUNS_PAGE_LIMIT = 100
DEFAULT_RUNS_PAGE_LIMIT = 50
DIVER_SCOPED_UPDATE_FIELDS = frozenset(
    {
        "dive_code",
        "height",
        "performance",
        "phase1_performance",
        "phase2_performance",
        "notes",
        "visibility",
        "confirm_publish",
    }
)


def list_triage_divers(
    db: Session,
    user: AppUser,
    *,
    authorized_session_ids: Optional[list[int]] = None,
    q: Optional[str] = None,
    limit: int = DEFAULT_DIVER_PAGE_LIMIT,
    offset: int = 0,
) -> dict[str, Any]:
    """Bounded, searchable, paginated diver selector (admins: full roster; owners: own divers)."""
    if not _user_can_manage_any_video(db, user):
        return {"items": [], "total": 0, "has_more": False, "next_offset": None}

    bounded_limit = max(1, min(limit, MAX_DIVER_PAGE_LIMIT))
    bounded_offset = max(0, offset)
    search_term = (q or "").strip()
    own_ids = set(owned_diver_ids(db, user.id))

    def _search_filter(query):
        if not search_term:
            return query
        escaped = search_term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pat = f"%{escaped}%"
        return query.filter(
            or_(
                Diver.display_name.ilike(pat, escape="\\"),
                Diver.canonical_name.ilike(pat, escape="\\"),
            )
        )

    if not user.is_admin:
        if not own_ids:
            return {"items": [], "total": 0, "has_more": False, "next_offset": None}
        with unscoped_reads(db):
            base_q = _search_filter(db.query(Diver).filter(Diver.id.in_(own_ids)))
            total = int(base_q.count() or 0)
            rows = (
                base_q.order_by(Diver.display_name.asc(), Diver.id.asc())
                .offset(bounded_offset)
                .limit(bounded_limit + 1)
                .all()
            )
        has_more = len(rows) > bounded_limit
        page = rows[:bounded_limit]
        return {
            "items": [
                {
                    "id": d.id,
                    "display_name": d.display_name,
                    "is_own": True,
                    "has_account": True,
                    "suggested": True,
                }
                for d in page
            ],
            "total": total,
            "has_more": has_more,
            "next_offset": (bounded_offset + bounded_limit) if has_more else None,
        }

    suggested_ids: list[int] = []
    with unscoped_reads(db):
        sess_ids = list(authorized_session_ids or [])
        if sess_ids:
            table = TrainingSession.__table__
            occ_ids = [
                r[0]
                for r in db.execute(
                    select(table.c.calendar_occurrence_id).where(
                        table.c.id.in_(sess_ids),
                        table.c.calendar_occurrence_id.is_not(None),
                    )
                ).all()
                if r[0] is not None
            ]
            if occ_ids:
                try:
                    from app.models.calendar import (
                        CalendarEvent,
                        EventOccurrence,
                        TrainingGroupMembership,
                    )

                    group_ids = [
                        r[0]
                        for r in db.query(CalendarEvent.training_group_id)
                        .join(EventOccurrence, EventOccurrence.event_id == CalendarEvent.id)
                        .filter(
                            EventOccurrence.id.in_(occ_ids),
                            CalendarEvent.training_group_id.is_not(None),
                        )
                        .distinct()
                        .limit(50)
                        .all()
                    ]
                    if group_ids:
                        member_user_ids = [
                            r[0]
                            for r in db.query(TrainingGroupMembership.user_id)
                            .filter(
                                TrainingGroupMembership.group_id.in_(group_ids),
                                TrainingGroupMembership.ended_on.is_(None),
                            )
                            .distinct()
                            .limit(100)
                            .all()
                        ]
                        if member_user_ids:
                            group_divers = [
                                r[0]
                                for r in db.query(UserDiverAccess.diver_id)
                                .filter(
                                    UserDiverAccess.user_id.in_(member_user_ids),
                                    UserDiverAccess.access_kind == "OWNER",
                                )
                                .distinct()
                                .limit(100)
                                .all()
                            ]
                            suggested_ids.extend(group_divers)
                except (OperationalError, ProgrammingError):
                    pass

            recent_assigned = [
                r[0]
                for r in db.query(SessionClipCandidate.diver_id)
                .join(SessionVideo, SessionVideo.id == SessionClipCandidate.session_video_id)
                .filter(
                    SessionVideo.session_id.in_(sess_ids),
                    SessionClipCandidate.diver_id.is_not(None),
                )
                .distinct()
                .limit(50)
                .all()
            ]
            suggested_ids.extend(recent_assigned)

        for own_id in own_ids:
            if own_id not in suggested_ids:
                suggested_ids.insert(0, own_id)

        suggested_set = set(suggested_ids)
        base_q = _search_filter(db.query(Diver))
        total = int(base_q.count() or 0)
        own_rank = case((Diver.id.in_(own_ids), 0), else_=1) if own_ids else 1
        sugg_rank = case((Diver.id.in_(suggested_set), 0), else_=1) if suggested_set else 1
        rows = (
            base_q.order_by(
                own_rank,
                sugg_rank,
                func.lower(Diver.display_name).asc(),
                Diver.id.asc(),
            )
            .offset(bounded_offset)
            .limit(bounded_limit + 1)
            .all()
        )
        has_more = len(rows) > bounded_limit
        page = rows[:bounded_limit]
        page_diver_ids = [d.id for d in page]
        owner_links = (
            {
                r[0]
                for r in db.query(UserDiverAccess.diver_id)
                .filter(
                    UserDiverAccess.diver_id.in_(page_diver_ids),
                    UserDiverAccess.access_kind == "OWNER",
                )
                .distinct()
                .all()
            }
            if page_diver_ids
            else set()
        )

    return {
        "items": [
            {
                "id": d.id,
                "display_name": d.display_name,
                "is_own": d.id in own_ids,
                "has_account": d.id in owner_links,
                "suggested": d.id in suggested_set,
            }
            for d in page
        ],
        "total": total,
        "has_more": has_more,
        "next_offset": (bounded_offset + bounded_limit) if has_more else None,
    }


def _suggested_and_all_divers(
    db: Session,
    user: AppUser,
    authorized_session_ids: list[int],
) -> dict[str, Any]:
    return list_triage_divers(
        db,
        user,
        authorized_session_ids=authorized_session_ids,
        limit=DEFAULT_DIVER_PAGE_LIMIT,
        offset=0,
    )


def serialize_candidate(
    cand: SessionClipCandidate,
    *,
    video: SessionVideo,
    session_date: Optional[str],
    session_title: Optional[str],
    diver_name: Optional[str],
    run_info: Optional[tuple[str, str]],
    mask_diver: bool = False,
) -> dict[str, Any]:
    return {
        "id": cand.id,
        "session_video_id": cand.session_video_id,
        "session_id": video.session_id,
        "session_date": session_date,
        "session_title": session_title,
        "video_filename": PurePosixPath(video.object_key).name,
        "video_duration_seconds": video.duration_seconds,
        "video_codec_string": video.codec_string,
        "video_audio_codec_string": video.audio_codec_string,
        "video_color_transfer": video.color_transfer,
        "video_play_url": f"/api/v1/session-videos/{video.id}/play",
        "video_download_url": f"/api/v1/session-videos/{video.id}/download",
        "video_poster_url": f"/api/v1/session-videos/{video.id}/images/poster",
        "start_s": cand.start_s,
        "end_s": cand.end_s,
        "trimmed_start_s": cand.trimmed_start_s,
        "trimmed_end_s": cand.trimmed_end_s,
        "effective_start_s": cand.effective_start_s,
        "effective_end_s": cand.effective_end_s,
        "duration_s": round(max(0.0, cand.effective_end_s - cand.effective_start_s), 2),
        "confidence": cand.confidence,
        "detector_label": cand.detector_label,
        "detector_name": run_info[0] if run_info else None,
        "detector_version": run_info[1] if run_info else None,
        "triage_status": cand.triage_status,
        "reject_reason": cand.reject_reason,
        "skipped_at": cand.skipped_at.replace(tzinfo=timezone.utc).isoformat() if cand.skipped_at else None,
        "diver_id": None if mask_diver else cand.diver_id,
        "diver_name": None if mask_diver else diver_name,
        "dive_code": None if mask_diver else cand.dive_code,
        "height": None if mask_diver else cand.height,
        "performance": None if mask_diver else cand.performance,
        "phase1_performance": None if mask_diver else cand.phase1_performance,
        "phase2_performance": None if mask_diver else cand.phase2_performance,
        "notes": None if mask_diver else cand.notes,
        "visibility": "private" if mask_diver else cand.visibility,
        "metadata_complete": False if mask_diver else is_metadata_complete(cand),
        "publish_requested": False
        if mask_diver
        else bool(
            cand.publish_requested_at is not None and cand.publish_requested_by_user_id is not None
        ),
        "extraction_status": cand.extraction_status,
        "extraction_error": cand.extraction_error,
        "cut_revision": cand.cut_revision,
        "dive_id": None if mask_diver else cand.dive_id,
        "published_at": None
        if mask_diver
        else (cand.published_at.replace(tzinfo=timezone.utc).isoformat() if cand.published_at else None),
        "updated_at": cand.updated_at.replace(tzinfo=timezone.utc).isoformat() if cand.updated_at else None,
    }


def _encode_queue_cursor(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_queue_cursor(token: str, expected_tab: str) -> dict[str, Any]:
    def _reject_constant(_val: str):
        raise ValueError("non-finite JSON constant")

    try:
        padded = token + ("=" * ((4 - len(token) % 4) % 4))
        data = json.loads(
            base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"),
            parse_constant=_reject_constant,
        )
        if not isinstance(data, dict) or data.get("t") != expected_tab:
            raise ValueError("tab mismatch")
        return data
    except Exception as exc:
        raise HTTPException(422, "Invalid pagination cursor") from exc


def _parse_cursor_int(val: Any) -> int:
    if isinstance(val, bool) or not isinstance(val, int):
        raise HTTPException(422, "Invalid pagination cursor")
    return val


def _parse_cursor_float(val: Any) -> float:
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise HTTPException(422, "Invalid pagination cursor")
    fval = float(val)
    if not math.isfinite(fval):
        raise HTTPException(422, "Invalid pagination cursor")
    return fval


def _parse_cursor_dt(val: Any) -> datetime:
    if not isinstance(val, str):
        raise HTTPException(422, "Invalid pagination cursor")
    try:
        return datetime.fromisoformat(val).replace(tzinfo=None)
    except ValueError as exc:
        raise HTTPException(422, "Invalid pagination cursor") from exc


def _keyset_after_clause(terms: list[tuple[Any, str, Any]]):
    """Build exact lexicographic keyset WHERE clause for non-null sort terms.

    Each term is `(sql_expr, 'asc' | 'desc' | 'eq', cursor_value)`.
    `'eq'` pins an already-saturated component (e.g. null-sentinel == 1) without
    emitting an impossible comparison branch.
    """
    branches = []
    eq_prefix = []
    for expr, direction, val in terms:
        if direction != "eq":
            cmp_expr = (expr > val) if direction == "asc" else (expr < val)
            branches.append(and_(*eq_prefix, cmp_expr) if eq_prefix else cmp_expr)
        eq_prefix.append(expr == val)
    return or_(*branches)


def list_triage_candidates(
    db: Session,
    user: AppUser,
    *,
    tab: str = "pending",
    session_id: Optional[int] = None,
    session_video_id: Optional[int] = None,
    limit: int = DEFAULT_PAGE_LIMIT,
    offset: int = 0,
    exclude_ids: Optional[list[int]] = None,
    cursor: Optional[str] = None,
) -> dict[str, Any]:
    """Bounded triage queue with keyset cursor pagination and zero leakage to non-managers."""
    if not _user_can_manage_any_video(db, user):
        return {
            "items": [],
            "has_more": False,
            "next_offset": None,
            "next_cursor": None,
            "divers": [],
            "divers_total": 0,
            "divers_has_more": False,
        }

    bounded_limit = max(1, min(limit, MAX_PAGE_LIMIT))
    bounded_offset = max(0, offset)
    bounded_exclude = [int(i) for i in (exclude_ids or []) if int(i) > 0][:100]
    filters = _manageable_video_filter(user)
    if session_id is not None:
        filters.append(SessionVideo.session_id == session_id)
    if session_video_id is not None:
        filters.append(SessionVideo.id == session_video_id)
    if bounded_exclude:
        filters.append(SessionClipCandidate.id.notin_(bounded_exclude))

    query = (
        db.query(SessionClipCandidate)
        .join(SessionVideo, SessionVideo.id == SessionClipCandidate.session_video_id)
        .filter(*filters)
    )

    is_skipped_expr = case((SessionClipCandidate.skipped_at.is_(None), 0), else_=1)
    rec_is_null_expr = case((SessionVideo.recorded_at.is_(None), 1), else_=0)

    cursor_data = _decode_queue_cursor(cursor, tab) if cursor else None

    if tab == "pending":
        query = query.filter(SessionClipCandidate.triage_status == "pending")
        if cursor_data is not None:
            try:
                sk_flag = _parse_cursor_int(cursor_data["sk"])
                rn_flag = _parse_cursor_int(cursor_data["rn"])
                vid_val = _parse_cursor_int(cursor_data["vid"])
                start_val = _parse_cursor_float(cursor_data["s"])
                cid_val = _parse_cursor_int(cursor_data["id"])
                if sk_flag not in (0, 1) or rn_flag not in (0, 1):
                    raise ValueError("invalid bounds")
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                raise HTTPException(422, "Invalid pagination cursor") from exc
            terms: list[tuple[Any, str, Any]] = [(is_skipped_expr, "asc" if sk_flag == 0 else "eq", sk_flag)]
            if sk_flag == 1:
                terms.append((SessionClipCandidate.skipped_at, "asc", _parse_cursor_dt(cursor_data.get("ska"))))
            terms.append((rec_is_null_expr, "asc" if rn_flag == 0 else "eq", rn_flag))
            if rn_flag == 0:
                terms.append((SessionVideo.recorded_at, "desc", _parse_cursor_dt(cursor_data.get("ra"))))
            terms.extend(
                [
                    (SessionClipCandidate.session_video_id, "desc", vid_val),
                    (SessionClipCandidate.start_s, "asc", start_val),
                    (SessionClipCandidate.id, "asc", cid_val),
                ]
            )
            query = query.filter(_keyset_after_clause(terms))
        query = query.order_by(
            is_skipped_expr.asc(),
            SessionClipCandidate.skipped_at.asc(),
            rec_is_null_expr.asc(),
            SessionVideo.recorded_at.desc(),
            SessionClipCandidate.session_video_id.desc(),
            SessionClipCandidate.start_s.asc(),
            SessionClipCandidate.id.asc(),
        )
    elif tab in ("incomplete", "recent"):
        query = query.filter(
            _incomplete_clause() if tab == "incomplete" else (SessionClipCandidate.triage_status != "pending")
        )
        if cursor_data is not None:
            try:
                u_dt = _parse_cursor_dt(cursor_data.get("u"))
                cid_val = _parse_cursor_int(cursor_data["id"])
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                raise HTTPException(422, "Invalid pagination cursor") from exc
            query = query.filter(
                _keyset_after_clause(
                    [
                        (SessionClipCandidate.updated_at, "desc", u_dt),
                        (SessionClipCandidate.id, "desc", cid_val),
                    ]
                )
            )
        query = query.order_by(SessionClipCandidate.updated_at.desc(), SessionClipCandidate.id.desc())
    else:
        if cursor_data is not None:
            try:
                rn_flag = _parse_cursor_int(cursor_data["rn"])
                vid_val = _parse_cursor_int(cursor_data["vid"])
                start_val = _parse_cursor_float(cursor_data["s"])
                cid_val = _parse_cursor_int(cursor_data["id"])
                if rn_flag not in (0, 1):
                    raise ValueError("invalid bounds")
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                raise HTTPException(422, "Invalid pagination cursor") from exc
            terms = [(rec_is_null_expr, "asc" if rn_flag == 0 else "eq", rn_flag)]
            if rn_flag == 0:
                terms.append((SessionVideo.recorded_at, "desc", _parse_cursor_dt(cursor_data.get("ra"))))
            terms.extend(
                [
                    (SessionClipCandidate.session_video_id, "desc", vid_val),
                    (SessionClipCandidate.start_s, "asc", start_val),
                    (SessionClipCandidate.id, "asc", cid_val),
                ]
            )
            query = query.filter(_keyset_after_clause(terms))
        query = query.order_by(
            rec_is_null_expr.asc(),
            SessionVideo.recorded_at.desc(),
            SessionClipCandidate.session_video_id.desc(),
            SessionClipCandidate.start_s.asc(),
            SessionClipCandidate.id.asc(),
        )

    effective_offset = 0 if cursor_data is not None else bounded_offset
    rows = query.offset(effective_offset).limit(bounded_limit + 1).all()
    has_more = len(rows) > bounded_limit
    page = rows[:bounded_limit]

    video_ids = list({c.session_video_id for c in page})
    videos_by_id = (
        {
            v.id: v
            for v in db.query(SessionVideo).filter(SessionVideo.id.in_(video_ids)).all()
        }
        if video_ids
        else {}
    )
    # Derive suggested-diver scope strictly from authorized videos (never raw caller session_id).
    authorized_sess_ids = list({v.session_id for v in videos_by_id.values() if v.session_id is not None})

    days: dict[int, Any] = {}
    titles: dict[int, str] = {}
    if authorized_sess_ids:
        table = TrainingSession.__table__
        days = {
            d.id: d
            for d in db.execute(
                select(table.c.id, table.c.date, table.c.calendar_occurrence_id).where(
                    table.c.id.in_(authorized_sess_ids)
                )
            ).all()
        }
        from app.services.session_calendar import session_titles

        titles = session_titles(
            db, [d.calendar_occurrence_id for d in days.values() if d.calendar_occurrence_id]
        )

    run_ids = list({c.latest_run_id or c.first_run_id for c in page if (c.latest_run_id or c.first_run_id)})
    runs_by_id = (
        {
            r.id: (r.detector_name, r.detector_version)
            for r in db.query(SessionClipRun.id, SessionClipRun.detector_name, SessionClipRun.detector_version)
            .filter(SessionClipRun.id.in_(run_ids))
            .all()
        }
        if run_ids
        else {}
    )

    visible_diver_ids = None if user.is_admin else owned_diver_ids(db, user.id)
    diver_ids = [
        did
        for did in {c.diver_id for c in page if c.diver_id is not None}
        if visible_diver_ids is None or did in visible_diver_ids
    ]
    with unscoped_reads(db):
        divers_by_id = (
            {
                d.id: d.display_name
                for d in db.query(Diver.id, Diver.display_name).filter(Diver.id.in_(diver_ids)).all()
            }
            if diver_ids
            else {}
        )

    items = []
    for cand in page:
        video = videos_by_id[cand.session_video_id]
        day = days.get(video.session_id) if video.session_id is not None else None
        mask_diver = (
            cand.diver_id is not None
            and visible_diver_ids is not None
            and cand.diver_id not in visible_diver_ids
        )
        items.append(
            serialize_candidate(
                cand,
                video=video,
                session_date=day.date.isoformat() if day else (video.recorded_date.isoformat() if video.recorded_date else None),
                session_title=titles.get(day.calendar_occurrence_id) if day else None,
                diver_name=divers_by_id.get(cand.diver_id) if cand.diver_id is not None else None,
                run_info=runs_by_id.get(cand.latest_run_id or cand.first_run_id),
                mask_diver=mask_diver,
            )
        )

    next_cursor: Optional[str] = None
    if has_more and page:
        last_cand = page[-1]
        last_video = videos_by_id[last_cand.session_video_id]
        if tab == "pending":
            next_cursor = _encode_queue_cursor(
                {
                    "t": "pending",
                    "sk": 0 if last_cand.skipped_at is None else 1,
                    "ska": last_cand.skipped_at.isoformat() if last_cand.skipped_at else None,
                    "rn": 0 if last_video.recorded_at is not None else 1,
                    "ra": last_video.recorded_at.isoformat() if last_video.recorded_at else None,
                    "vid": last_cand.session_video_id,
                    "s": float(last_cand.start_s),
                    "id": last_cand.id,
                }
            )
        elif tab in ("incomplete", "recent"):
            next_cursor = _encode_queue_cursor(
                {
                    "t": tab,
                    "u": (last_cand.updated_at or last_cand.created_at or datetime.utcnow()).isoformat(),
                    "id": last_cand.id,
                }
            )
        else:
            next_cursor = _encode_queue_cursor(
                {
                    "t": tab,
                    "rn": 0 if last_video.recorded_at is not None else 1,
                    "ra": last_video.recorded_at.isoformat() if last_video.recorded_at else None,
                    "vid": last_cand.session_video_id,
                    "s": float(last_cand.start_s),
                    "id": last_cand.id,
                }
            )

    divers_page = _suggested_and_all_divers(db, user, authorized_sess_ids)
    return {
        "items": items,
        "has_more": has_more,
        "next_offset": (effective_offset + bounded_limit) if has_more else None,
        "next_cursor": next_cursor,
        "divers": divers_page["items"],
        "divers_total": divers_page["total"],
        "divers_has_more": divers_page["has_more"],
    }


def get_triage_candidate(db: Session, user: AppUser, candidate_id: int) -> dict[str, Any]:
    """Fetch a single candidate directly under uniform 404 authorization checks."""
    cand = db.get(SessionClipCandidate, candidate_id)
    if cand is None:
        raise HTTPException(404, "Clip candidate not found")
    video = db.get(SessionVideo, cand.session_video_id)
    if (
        video is None
        or video.status != "ready"
        or video.deleted_at is not None
        or not can_manage_video(user, video)
    ):
        raise HTTPException(404, "Clip candidate not found")
    return _serialize_one_candidate(db, cand, video, viewer=user)


def _serialize_one_candidate(
    db: Session,
    cand: SessionClipCandidate,
    video: SessionVideo,
    viewer: Optional[AppUser] = None,
) -> dict[str, Any]:
    day = None
    title = None
    if video.session_id is not None:
        table = TrainingSession.__table__
        day = db.execute(
            select(table.c.id, table.c.date, table.c.calendar_occurrence_id).where(
                table.c.id == video.session_id
            )
        ).first()
        if day and day.calendar_occurrence_id:
            from app.services.session_calendar import session_titles

            title = session_titles(db, [day.calendar_occurrence_id]).get(day.calendar_occurrence_id)
    run_id = cand.latest_run_id or cand.first_run_id
    run_info = None
    if run_id:
        r = db.query(SessionClipRun.detector_name, SessionClipRun.detector_version).filter_by(id=run_id).first()
        if r:
            run_info = (r[0], r[1])
    diver_name = None
    mask_diver = False
    if cand.diver_id is not None:
        can_see_diver = (
            viewer is None
            or viewer.is_admin
            or cand.diver_id in owned_diver_ids(db, viewer.id)
        )
        if can_see_diver:
            with unscoped_reads(db):
                d = db.get(Diver, cand.diver_id)
                diver_name = d.display_name if d else None
        else:
            mask_diver = True
    return serialize_candidate(
        cand,
        video=video,
        session_date=day.date.isoformat() if day else (video.recorded_date.isoformat() if video.recorded_date else None),
        session_title=title,
        diver_name=diver_name,
        run_info=run_info,
        mask_diver=mask_diver,
    )


def _resolve_batch_id_for_diver(db: Session, video_id: int, diver_id: int) -> str:
    """Reuse an active un-sent batch for (video, diver); start a fresh one only after send."""
    base = f"clip-sv-{video_id}"
    rows = (
        db.query(BatchEmailOutbox.batch_id, BatchEmailOutbox.status)
        .filter(
            BatchEmailOutbox.diver_id == diver_id,
            or_(
                BatchEmailOutbox.batch_id == base,
                BatchEmailOutbox.batch_id.like(f"{base}-%"),
            ),
        )
        .order_by(BatchEmailOutbox.id.desc())
        .limit(20)
        .all()
    )
    if not rows:
        return base
    for batch_id, st in rows:
        if st in (BatchEmailOutbox.STATUS_HELD, BatchEmailOutbox.STATUS_PENDING):
            return batch_id
    return f"{base}-{uuid.uuid4().hex[:6]}"


def _queue_batch_email_safe(
    db: Session,
    *,
    batch_id: str,
    diver_id: int,
    exclude_user_id: Optional[int],
) -> None:
    """Conflict-safe held email enqueue that can never abort Dive publication."""
    try:
        db.flush()  # Ensure Dive insert is flushed before opening savepoint.
        with db.begin_nested():
            deposit_batches.queue_batch_email(
                db,
                batch_id=batch_id,
                diver_id=diver_id,
                exclude_user_id=exclude_user_id,
                hold=True,
            )
    except IntegrityError:
        # Concurrent worker created the identical (batch_id, diver_id, user_id) row.
        pass
    except Exception:
        logger.exception("clip triage: batch email queue failed for batch=%s diver=%s", batch_id, diver_id)


def _lock_divers_in_order(db: Session, diver_ids: list[Optional[int]]) -> dict[int, Diver]:
    """Lock Diver rows in ascending id order so ownership checks serialize with admin unbind_diver."""
    ordered = sorted({int(did) for did in diver_ids if did is not None})
    if not ordered:
        return {}
    with unscoped_reads(db):
        rows = (
            db.query(Diver)
            .filter(Diver.id.in_(ordered))
            .order_by(Diver.id.asc())
            .with_for_update()
            .all()
        )
    return {row.id: row for row in rows}


def maybe_publish_candidate(
    db: Session,
    cand: SessionClipCandidate,
    video: SessionVideo,
    actor: Optional[AppUser] = None,
    retired_paths: Optional[list[Path]] = None,
) -> Optional[Dive]:
    """Promote a kept, explicitly publish-confirmed, extracted candidate into a real Dive.

    Requires:
      - live source video (`status == 'ready'`, `deleted_at is None`)
      - `triage_status == 'kept'`, `extraction_status == 'ready'`, `publish_requested_at is not None`
      - `is_metadata_complete(cand)` and `clip_video_uuid`
      - own diver OR admin depositor (matches `dives.py` upload policy)
    """
    def _clear_invalid_confirmation() -> None:
        cand.publish_requested_at = None
        cand.publish_requested_by_user_id = None
        cand.updated_at = datetime.utcnow()

    if cand.dive_id is not None:
        return db.get(Dive, cand.dive_id)
    # If the confirming user was deleted (ON DELETE SET NULL), clear the orphaned timestamp.
    if cand.publish_requested_at is not None and cand.publish_requested_by_user_id is None:
        _clear_invalid_confirmation()
        return None
    if (
        video.status != "ready"
        or video.deleted_at is not None
        or cand.triage_status != "kept"
        or cand.extraction_status != "ready"
        or cand.publish_requested_at is None
        or cand.publish_requested_by_user_id is None
        or not is_metadata_complete(cand)
        or not cand.clip_video_uuid
    ):
        return None

    if not cand.source_etag or not video.etag or cand.source_etag != video.etag:
        # Source ETag missing or changed since cut -> retire stale cut & re-queue fresh extraction
        # against a verified source ETag so the confirmed clip auto-publishes once re-cut.
        stale_paths = _invalidate_cut_lease(db, cand, next_status="queued")
        if retired_paths is not None:
            retired_paths.extend(stale_paths)
        cand.updated_at = datetime.utcnow()
        return None

    with unscoped_reads(db):
        # Lock Diver row so ownership recheck serializes against concurrent admin_users.unbind_diver.
        diver = (
            db.query(Diver)
            .filter(Diver.id == cand.diver_id)
            .with_for_update()
            .first()
        )
        if diver is None:
            _clear_invalid_confirmation()
            return None
        parsed = DiveCodeParser.parse(f"{cand.dive_code} {cand.performance} {cand.height}")
        if not parsed.is_valid:
            _clear_invalid_confirmation()
            return None

        # Revalidate BOTH source-video management rights AND diver ownership/admin role.
        depositor = (
            actor
            if (actor is not None and actor.id == cand.publish_requested_by_user_id)
            else db.get(AppUser, cand.publish_requested_by_user_id)
        )
        if depositor is None or not can_manage_video(depositor, video):
            _clear_invalid_confirmation()
            return None
        is_own = cand.diver_id in owned_diver_ids(db, depositor.id)
        if not is_own and not depositor.is_admin:
            _clear_invalid_confirmation()
            return None

        session_id = video.session_id
        if video.recorded_at is not None:
            dive_dt = video.recorded_at + timedelta(seconds=cand.effective_start_s)
        else:
            day = video.recorded_date or datetime.utcnow().date()
            dive_dt = datetime(day.year, day.month, day.day, 12, 0, 0) + timedelta(
                seconds=cand.effective_start_s
            )
        if session_id is None:
            from app.services.session_videos import training_session_for

            session_id = training_session_for(db, dive_dt.date()).id

        dd_row = (
            db.query(DDLookup)
            .filter_by(dive_code=parsed.dive_code, height=cand.height)
            .first()
        )
        official_dd = dd_row.dd_value if dd_row else None

        dive_notes = cand.notes if is_own else None
        dive_vis = cand.visibility if is_own else "private"

        context = db.info.get(CONTEXT_KEY)
        saved_sys = context.get("system_mutation") if context is not None else None
        if context is not None:
            context["system_mutation"] = True
        try:
            dive = Dive(
                session_id=session_id,
                diver_id=diver.id,
                person_name=diver.display_name,
                visibility=dive_vis,
                dive_code=parsed.dive_code,
                dive_number=parsed.dive_code[:-1],
                position=parsed.position,
                direction=parsed.direction if parsed.direction in (1, 2, 3, 4, 5) else None,
                performance=cand.performance,
                performance_numeric=ORDINAL_SCORE[cand.performance],
                phase1_performance=cand.phase1_performance,
                phase1_numeric=ORDINAL_SCORE[cand.phase1_performance] if cand.phase1_performance else None,
                phase2_performance=cand.phase2_performance,
                phase2_numeric=ORDINAL_SCORE[cand.phase2_performance] if cand.phase2_performance else None,
                height=cand.height,
                platform_type="springboard" if cand.height in ("1m", "3m") else "platform",
                notes=dive_notes,
                video_uuid=cand.clip_video_uuid,
                video_filename=f"{parsed.dive_code}_{cand.id}.mp4",
                photos_asset_id=cand.photos_asset_id,
                official_dd=official_dd,
                dive_datetime=dive_dt,
                history_occurred_at=dive_dt,
            )
            db.add(dive)
            db.flush()

            batch_id = _resolve_batch_id_for_diver(db, video.id, diver.id)
            pending_diver = deposit_batches.finalize_synced_dive(
                db,
                dive,
                batch_id=batch_id,
                created=True,
                depositor=depositor,
                raw_caption=cand.notes,
            )
            if pending_diver is not None:
                _queue_batch_email_safe(
                    db,
                    batch_id=batch_id,
                    diver_id=pending_diver,
                    exclude_user_id=depositor.id if depositor else None,
                )

            now = datetime.utcnow()
            cand.dive_id = dive.id
            cand.extraction_status = "published"
            cand.published_at = now
            cand.updated_at = now
            invalidate_analysis_cache(db)
            return dive
        finally:
            if context is not None:
                if saved_sys is None:
                    context.pop("system_mutation", None)
                else:
                    context["system_mutation"] = saved_sys


def _invalidate_cut_lease(
    db: Session,
    cand: SessionClipCandidate,
    *,
    next_status: str,
    rotate_identity: bool = True,
) -> list[Path]:
    """Bump cut_revision, clear active lease, and rotate unpublished clip_video_uuid.

    Rotating `clip_video_uuid` before a re-cut ensures returning to an earlier trim
    (A -> B -> A) gets its own fresh MediaRevision row instead of reusing an older
    revision ID behind B. Returns local cache paths to unlink post-commit.
    """
    retired_paths: list[Path] = []
    if rotate_identity and cand.dive_id is None and cand.photos_asset_id is not None:
        with unscoped_reads(db):
            entries = (
                db.query(MediaCacheEntry)
                .filter(MediaCacheEntry.photos_asset_id == cand.photos_asset_id)
                .all()
            )
            for entry in entries:
                if entry.storage_path:
                    retired_paths.append(Path(entry.storage_path))
                db.delete(entry)
        cand.photos_asset_id = None
    if rotate_identity and cand.dive_id is None:
        cand.clip_video_uuid = str(uuid.uuid4()) if next_status == "queued" else None

    cand.cut_revision += 1
    cand.extraction_status = next_status
    cand.lease_token = None
    cand.claimed_by = None
    cand.claimed_at = None
    cand.claimed_until = None
    cand.extraction_attempts = 0
    cand.extraction_error = None
    cand.source_etag = None
    return retired_paths


def update_candidate(
    db: Session,
    user: AppUser,
    candidate_id: int,
    updates: dict[str, Any],
) -> dict[str, Any]:
    """Fast single-request autosave / keep / reject / skip / undo / trim / publish.

    Locks SessionVideo then SessionClipCandidate in consistent order.
    """
    cand_row = db.query(SessionClipCandidate.session_video_id).filter_by(id=candidate_id).first()
    if cand_row is None:
        raise HTTPException(404, "Clip candidate not found")

    video = (
        db.query(SessionVideo)
        .filter(SessionVideo.id == cand_row[0])
        .with_for_update()
        .first()
    )
    if video is None or video.status != "ready" or video.deleted_at is not None or not can_manage_video(user, video):
        raise HTTPException(404, "Clip candidate not found")

    cand = (
        db.query(SessionClipCandidate)
        .filter(SessionClipCandidate.id == candidate_id)
        .with_for_update()
        .first()
    )
    if cand is None:
        raise HTTPException(404, "Clip candidate not found")

    if cand.dive_id is not None:
        raise HTTPException(409, "Clip is already published as a dive")

    now = datetime.utcnow()
    bounds_changed = False
    before_meta = (
        cand.diver_id,
        cand.dive_code,
        cand.height,
        cand.performance,
        cand.phase1_performance,
        cand.phase2_performance,
        cand.notes,
        cand.visibility,
    )

    # 1. Trim bounds (ignore sub-10ms noise; cap at MAX_CLIP_SPAN_S)
    if "trimmed_start_s" in updates or "trimmed_end_s" in updates:
        new_start = updates.get("trimmed_start_s", cand.effective_start_s)
        new_end = updates.get("trimmed_end_s", cand.effective_end_s)
        if new_start is None and new_end is None:
            if cand.trimmed_start_s is not None or cand.trimmed_end_s is not None:
                cand.trimmed_start_s = None
                cand.trimmed_end_s = None
                bounds_changed = True
        else:
            if new_start is None or new_end is None:
                raise HTTPException(422, "Both trimmed_start_s and trimmed_end_s are required")
            s_val, e_val = _validated_span(new_start, new_end)
            if video.duration_seconds is not None:
                e_val = min(e_val, float(video.duration_seconds))
                if e_val - s_val < MIN_CLIP_SPAN_S:
                    raise HTTPException(422, "Invalid clip trim bounds")
            s_val = round(s_val, 2)
            e_val = round(e_val, 2)
            if (
                abs(s_val - cand.effective_start_s) >= TRIM_EPSILON_S
                or abs(e_val - cand.effective_end_s) >= TRIM_EPSILON_S
            ):
                cand.trimmed_start_s = s_val
                cand.trimmed_end_s = e_val
                bounds_changed = True

    # 2. Diver assignment & diver-scoping guard: lock involved Diver rows first so ownership
    # checks serialize against concurrent admin_users.unbind_diver, then verify ORIGINAL assignment.
    requested_diver_id = (
        int(updates["diver_id"])
        if ("diver_id" in updates and updates["diver_id"] is not None)
        else None
    )
    locked_divers = _lock_divers_in_order(db, [cand.diver_id, requested_diver_id])
    user_owned_divers = None if user.is_admin else owned_diver_ids(db, user.id)
    was_other_diver = (
        user_owned_divers is not None
        and cand.diver_id is not None
        and cand.diver_id not in user_owned_divers
    )
    if was_other_diver and (
        "diver_id" in updates
        or (DIVER_SCOPED_UPDATE_FIELDS & updates.keys())
        or updates.get("triage_status") == "kept"
    ):
        raise HTTPException(403, "Cannot edit or reassign another diver's clip")

    if "diver_id" in updates:
        diver_id = updates["diver_id"]
        next_triage = updates.get("triage_status", cand.triage_status)
        if diver_id is None:
            if next_triage == "kept":
                raise HTTPException(422, "A kept clip must remain assigned to a diver")
            cand.diver_id = None
        else:
            target_id = int(diver_id)
            if user_owned_divers is not None and target_id not in user_owned_divers:
                raise HTTPException(403, "Choose a diver you own")
            diver = locked_divers.get(target_id)
            if diver is None:
                raise HTTPException(404, "Diver not found")
            cand.diver_id = diver.id

    # 3. Dive code
    if "dive_code" in updates:
        raw_code = updates["dive_code"]
        if raw_code is None or str(raw_code).strip() == "":
            cand.dive_code = None
        else:
            code = str(raw_code).strip().upper()
            parsed = DiveCodeParser.parse(f"{code} M 3m")
            if not parsed.is_valid:
                raise HTTPException(422, parsed.error or "Invalid dive code")
            cand.dive_code = parsed.dive_code

    # 4. Height
    if "height" in updates:
        raw_h = updates["height"]
        if raw_h is None or str(raw_h).strip() == "":
            cand.height = None
        else:
            h_val = str(raw_h).strip().lower()
            if h_val not in VALID_HEIGHTS:
                raise HTTPException(422, "Height must be one of 1m, 3m, 5m, 7.5m, 10m")
            cand.height = h_val

    # 5. Scoring (strictly follows docs/SCORING.md)
    phase_keys = {"phase1_performance", "phase2_performance"} & updates.keys()
    if phase_keys:
        p1 = updates.get("phase1_performance", cand.phase1_performance)
        p2 = updates.get("phase2_performance", cand.phase2_performance)
        p1 = str(p1).strip().upper() if p1 else None
        p2 = str(p2).strip().upper() if p2 else None
        if (p1 is None) != (p2 is None):
            raise HTTPException(422, "Both phases must be rated together")
        if p1 is not None:
            if p1 not in VALID_RATINGS or p2 not in VALID_RATINGS:
                raise HTTPException(422, "Invalid phase rating")
            cand.phase1_performance = p1
            cand.phase2_performance = p2
            cand.performance = PhaseValidator.infer_legacy_score(p1, p2)
        else:
            cand.phase1_performance = None
            cand.phase2_performance = None
            if "performance" in updates:
                perf = str(updates["performance"]).strip().upper() if updates["performance"] else None
                if perf is not None and perf not in VALID_RATINGS:
                    raise HTTPException(422, "Invalid rating")
                cand.performance = perf
            else:
                cand.performance = None
    elif "performance" in updates:
        raw_perf = updates["performance"]
        if raw_perf is None or str(raw_perf).strip() == "":
            cand.performance = None
            cand.phase1_performance = None
            cand.phase2_performance = None
        else:
            perf = str(raw_perf).strip().upper()
            if perf not in VALID_RATINGS:
                raise HTTPException(422, "Invalid rating")
            cand.performance = perf
            cand.phase1_performance = None
            cand.phase2_performance = None

    # 6. Notes & visibility
    if "notes" in updates:
        raw_notes = updates["notes"]
        cand.notes = str(raw_notes).strip()[:2000] or None if raw_notes is not None else None
    if "visibility" in updates and updates["visibility"] is not None:
        vis = str(updates["visibility"]).strip().lower()
        if vis not in ("private", "public"):
            raise HTTPException(422, "Visibility must be private or public")
        cand.visibility = vis

    # 7. Skip action
    if updates.get("skip"):
        cand.skipped_at = now

    retired_paths: list[Path] = []

    # 8. Every effective trim invalidates prior/in-flight cut (even while pending after Undo!).
    if bounds_changed and cand.extraction_status != "none":
        retired_paths.extend(
            _invalidate_cut_lease(
                db,
                cand,
                next_status="queued" if cand.triage_status == "kept" else "none",
            )
        )
    elif bounds_changed:
        cand.cut_revision += 1

    # 9. Triage status transition (fences in-flight Mac leases on reject/undo!)
    if "triage_status" in updates and updates["triage_status"] is not None:
        next_status = str(updates["triage_status"]).strip().lower()
        if next_status not in ("pending", "kept", "rejected"):
            raise HTTPException(422, "Invalid triage_status")
        if next_status == "kept":
            if cand.diver_id is None:
                raise HTTPException(422, "Assign a diver before keeping a clip")
            if not user.is_admin and cand.diver_id not in owned_diver_ids(db, user.id):
                raise HTTPException(403, "Choose a diver you own")
            cand.triage_status = "kept"
            cand.reject_reason = None
            cand.triaged_by_user_id = user.id
            cand.triaged_at = now
            cand.skipped_at = None
            if cand.clip_video_uuid is None:
                cand.clip_video_uuid = str(uuid.uuid4())
            if cand.extraction_status in ("none", "failed"):
                cand.extraction_status = "queued"
                cand.extraction_attempts = 0
                cand.extraction_error = None
        elif next_status == "rejected":
            reason = str(updates.get("reject_reason") or "false_positive").strip().lower()
            if reason not in VALID_REJECT_REASONS:
                raise HTTPException(422, "Invalid reject_reason")
            cand.triage_status = "rejected"
            cand.reject_reason = reason
            cand.triaged_by_user_id = user.id
            cand.triaged_at = now
            cand.skipped_at = None
            cand.publish_requested_at = None
            cand.publish_requested_by_user_id = None
            if cand.extraction_status != "none":
                retired_paths.extend(_invalidate_cut_lease(db, cand, next_status="none"))
        else:
            cand.triage_status = "pending"
            cand.reject_reason = None
            cand.triaged_at = None
            cand.skipped_at = None
            cand.publish_requested_at = None
            cand.publish_requested_by_user_id = None
            if cand.extraction_status != "none":
                retired_paths.extend(_invalidate_cut_lease(db, cand, next_status="none"))

    # 10. Bind publish confirmation strictly to the exact confirmed draft + cut_revision + confirming user.
    after_meta = (
        cand.diver_id,
        cand.dive_code,
        cand.height,
        cand.performance,
        cand.phase1_performance,
        cand.phase2_performance,
        cand.notes,
        cand.visibility,
    )
    if after_meta != before_meta or bounds_changed:
        cand.publish_requested_at = None
        cand.publish_requested_by_user_id = None

    if "confirm_publish" in updates:
        if updates["confirm_publish"] is True:
            if cand.triage_status != "kept":
                raise HTTPException(422, "Keep the clip before publishing")
            if not is_metadata_complete(cand):
                raise HTTPException(422, "Complete diver, code, height and rating before publishing")
            if not user.is_admin and cand.diver_id not in owned_diver_ids(db, user.id):
                raise HTTPException(403, "Choose a diver you own")
            cand.publish_requested_at = now
            cand.publish_requested_by_user_id = user.id
        elif updates["confirm_publish"] is False:
            cand.publish_requested_at = None
            cand.publish_requested_by_user_id = None

    cand.updated_at = now
    db.flush()

    maybe_publish_candidate(db, cand, video, actor=user, retired_paths=retired_paths)
    db.commit()
    if retired_paths:
        _unlink_replaced_paths(retired_paths)
    db.refresh(cand)
    return _serialize_one_candidate(db, cand, video, viewer=user)


def retry_candidate_extraction(db: Session, user: AppUser, candidate_id: int) -> dict[str, Any]:
    cand_row = db.query(SessionClipCandidate.session_video_id).filter_by(id=candidate_id).first()
    if cand_row is None:
        raise HTTPException(404, "Clip candidate not found")
    video = db.query(SessionVideo).filter_by(id=cand_row[0]).with_for_update().first()
    if video is None or video.status != "ready" or video.deleted_at is not None or not can_manage_video(user, video):
        raise HTTPException(404, "Clip candidate not found")
    cand = db.query(SessionClipCandidate).filter_by(id=candidate_id).with_for_update().first()
    if cand is None:
        raise HTTPException(404, "Clip candidate not found")
    if cand.triage_status != "kept":
        raise HTTPException(409, "Only kept clips can be queued for extraction")
    if cand.dive_id is not None:
        raise HTTPException(409, "Clip is already published")
    _lock_divers_in_order(db, [cand.diver_id])
    if (
        not user.is_admin
        and cand.diver_id is not None
        and cand.diver_id not in owned_diver_ids(db, user.id)
    ):
        raise HTTPException(403, "Cannot retry extraction for another diver's clip")
    retired_paths = _invalidate_cut_lease(db, cand, next_status="queued")
    cand.updated_at = datetime.utcnow()
    db.commit()
    if retired_paths:
        _unlink_replaced_paths(retired_paths)
    db.refresh(cand)
    return _serialize_one_candidate(db, cand, video, viewer=user)


def list_video_runs(
    db: Session,
    video: SessionVideo,
    *,
    limit: int = DEFAULT_RUNS_PAGE_LIMIT,
    offset: int = 0,
) -> dict[str, Any]:
    """Paginated detector runs with full-scope count and explicit continuation."""
    bounded_limit = max(1, min(limit, MAX_RUNS_PAGE_LIMIT))
    bounded_offset = max(0, offset)
    total_runs = int(
        db.query(func.count(SessionClipRun.id))
        .filter(SessionClipRun.session_video_id == video.id)
        .scalar()
        or 0
    )
    rows = (
        db.query(SessionClipRun)
        .filter(SessionClipRun.session_video_id == video.id)
        .order_by(SessionClipRun.created_at.desc(), SessionClipRun.id.desc())
        .offset(bounded_offset)
        .limit(bounded_limit + 1)
        .all()
    )
    has_more = len(rows) > bounded_limit
    runs = rows[:bounded_limit]
    if not runs:
        return {
            "runs": [],
            "total_runs": total_runs,
            "has_more": False,
            "next_offset": None,
        }

    total_kept = (
        db.query(func.count(SessionClipCandidate.id))
        .filter(
            SessionClipCandidate.session_video_id == video.id,
            SessionClipCandidate.triage_status == "kept",
        )
        .scalar()
        or 0
    )

    run_ids = [r.id for r in runs]
    match_stats = (
        db.query(
            SessionClipRunMatch.run_id,
            func.sum(case((SessionClipCandidate.triage_status == "kept", 1), else_=0)),
            func.sum(case((SessionClipCandidate.triage_status == "rejected", 1), else_=0)),
            func.sum(case((SessionClipCandidate.triage_status == "pending", 1), else_=0)),
        )
        .join(SessionClipCandidate, SessionClipCandidate.id == SessionClipRunMatch.candidate_id)
        .filter(SessionClipRunMatch.run_id.in_(run_ids))
        .group_by(SessionClipRunMatch.run_id)
        .all()
    )
    stats_by_run = {
        int(rid): (int(k or 0), int(rej or 0), int(pend or 0))
        for rid, k, rej, pend in match_stats
    }

    out = []
    for r in runs:
        tp, fp, pend = stats_by_run.get(r.id, (0, 0, 0))
        triaged = tp + fp
        precision = round(tp / triaged, 4) if triaged > 0 else None
        recall = round(tp / total_kept, 4) if total_kept > 0 else None
        out.append(
            {
                "id": r.id,
                "session_video_id": r.session_video_id,
                "detector_name": r.detector_name,
                "detector_version": r.detector_version,
                "submitted_count": r.submitted_count,
                "created_count": r.created_count,
                "deduped_count": r.deduped_count,
                "kept_matches": tp,
                "rejected_matches": fp,
                "pending_matches": pend,
                "precision": precision,
                "recall": recall,
                "created_at": r.created_at.replace(tzinfo=timezone.utc).isoformat(),
            }
        )
    return {
        "runs": out,
        "total_runs": total_runs,
        "has_more": has_more,
        "next_offset": (bounded_offset + bounded_limit) if has_more else None,
    }


def export_video_ground_truth(
    db: Session,
    video: SessionVideo,
    *,
    limit: int = MAX_GT_PAGE_LIMIT,
    offset: int = 0,
    viewer: Optional[AppUser] = None,
) -> dict[str, Any]:
    """Export human-triaged Ground Truth JSON with full-scope counts and explicit pagination."""
    bounded_limit = max(1, min(limit, MAX_GT_PAGE_LIMIT))
    bounded_offset = max(0, offset)

    # Full-scope counts in one SQL aggregate (never truncated by page window).
    totals = (
        db.query(
            func.sum(case((SessionClipCandidate.triage_status == "kept", 1), else_=0)),
            func.sum(case((SessionClipCandidate.triage_status == "rejected", 1), else_=0)),
            func.sum(
                case(
                    (
                        and_(
                            SessionClipCandidate.triage_status.in_(("kept", "rejected")),
                            or_(
                                SessionClipCandidate.trimmed_start_s.is_not(None),
                                SessionClipCandidate.trimmed_end_s.is_not(None),
                            ),
                        ),
                        1,
                    ),
                    else_=0,
                )
            ),
        )
        .filter(SessionClipCandidate.session_video_id == video.id)
        .one()
    )

    rows = (
        db.query(SessionClipCandidate)
        .filter(
            SessionClipCandidate.session_video_id == video.id,
            SessionClipCandidate.triage_status.in_(("kept", "rejected")),
        )
        .order_by(SessionClipCandidate.start_s.asc(), SessionClipCandidate.id.asc())
        .offset(bounded_offset)
        .limit(bounded_limit + 1)
        .all()
    )
    has_more = len(rows) > bounded_limit
    candidates = rows[:bounded_limit]

    visible_diver_ids = (
        None if (viewer is None or viewer.is_admin) else owned_diver_ids(db, viewer.id)
    )
    diver_ids = [
        did
        for did in {c.diver_id for c in candidates if c.diver_id is not None}
        if visible_diver_ids is None or did in visible_diver_ids
    ]
    with unscoped_reads(db):
        divers_by_id = (
            {
                d.id: d.display_name
                for d in db.query(Diver.id, Diver.display_name).filter(Diver.id.in_(diver_ids)).all()
            }
            if diver_ids
            else {}
        )

    positives = []
    negatives = []
    for c in candidates:
        was_trimmed = c.trimmed_start_s is not None or c.trimmed_end_s is not None
        entry = {
            "candidate_id": c.id,
            "start_s": c.effective_start_s,
            "end_s": c.effective_end_s,
            "original_start_s": c.start_s,
            "original_end_s": c.end_s,
            "trimmed": was_trimmed,
            "confidence": c.confidence,
        }
        if c.triage_status == "kept":
            mask_diver = (
                c.diver_id is not None
                and visible_diver_ids is not None
                and c.diver_id not in visible_diver_ids
            )
            entry.update(
                diver_id=None if mask_diver else c.diver_id,
                diver_name=None if mask_diver else (divers_by_id.get(c.diver_id) if c.diver_id is not None else None),
                dive_code=None if mask_diver else c.dive_code,
                height=None if mask_diver else c.height,
                performance=None if mask_diver else c.performance,
                dive_id=None if mask_diver else c.dive_id,
            )
            positives.append(entry)
        else:
            entry["reject_reason"] = c.reject_reason or "false_positive"
            negatives.append(entry)

    runs_page = list_video_runs(db, video, limit=DEFAULT_RUNS_PAGE_LIMIT, offset=0)
    return {
        "schema_version": "session_clip_gt_v1",
        "session_video_id": video.id,
        "session_id": video.session_id,
        "filename": PurePosixPath(video.object_key).name,
        "duration_seconds": video.duration_seconds,
        "counts": {
            "positives": int(totals[0] or 0),
            "negatives": int(totals[1] or 0),
            "trimmed": int(totals[2] or 0),
        },
        "has_more": has_more,
        "next_offset": bounded_offset + bounded_limit if has_more else None,
        "positives": positives,
        "negatives": negatives,
        "runs": runs_page["runs"],
        "runs_total": runs_page["total_runs"],
        "runs_has_more": runs_page["has_more"],
        "runs_next_offset": runs_page["next_offset"],
    }


def _encode_gt_export_cursor(state: dict[str, Any]) -> str:
    raw = json.dumps(state, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_gt_export_cursor(cursor: Optional[str]) -> Optional[dict[str, Any]]:
    """Decode and validate an opaque streaming GT export continuation cursor."""
    if not cursor:
        return None
    try:
        pad = "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(cursor + pad).decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("not a dict")
        section = data.get("s")
        if section not in ("positives", "negatives", "runs"):
            raise ValueError("bad section")
        if section in ("positives", "negatives"):
            if "start_s" in data or "id" in data:
                start_s = float(data["start_s"])
                cid = int(data["id"])
                if not math.isfinite(start_s) or cid < 1:
                    raise ValueError("bad bounds")
                return {"s": section, "start_s": start_s, "id": cid}
            return {"s": section}
        if "created_at" in data or "id" in data:
            created_at = datetime.fromisoformat(str(data["created_at"]))
            rid = int(data["id"])
            if rid < 1:
                raise ValueError("bad run id")
            return {"s": "runs", "created_at": created_at, "id": rid}
        return {"s": "runs"}
    except Exception:
        raise HTTPException(422, "Invalid export cursor") from None


def iter_video_ground_truth_json(
    db: Session,
    video: SessionVideo,
    *,
    viewer: Optional[AppUser] = None,
    cursor_state: Optional[dict[str, Any]] = None,
    max_bytes: int = GT_EXPORT_MAX_BYTES,
) -> Iterator[bytes]:
    """Stream bounded Ground Truth JSON (`session_clip_gt_v1`) with explicit continuation.

    Bounds rows per query (`GT_STREAM_CHUNK_SIZE`), query count (`GT_EXPORT_MAX_CHUNKS`),
    retained memory (O(1 chunk) tuple rows), and total response bytes (`max_bytes`)
    separately, emitting `has_more` and `next_cursor` whenever more data remains.
    """
    video_id = video.id
    session_id = video.session_id
    filename = PurePosixPath(video.object_key).name
    duration_seconds = video.duration_seconds
    visible_diver_ids = (
        None if (viewer is None or viewer.is_admin) else owned_diver_ids(db, viewer.id)
    )
    byte_cap = max(GT_EXPORT_MIN_BYTES, min(int(max_bytes), GT_EXPORT_MAX_BYTES))
    trailer_reserve = 384
    byte_budget = max(512, byte_cap - trailer_reserve)

    totals = (
        db.query(
            func.sum(case((SessionClipCandidate.triage_status == "kept", 1), else_=0)),
            func.sum(case((SessionClipCandidate.triage_status == "rejected", 1), else_=0)),
            func.sum(
                case(
                    (
                        and_(
                            SessionClipCandidate.triage_status.in_(("kept", "rejected")),
                            or_(
                                SessionClipCandidate.trimmed_start_s.is_not(None),
                                SessionClipCandidate.trimmed_end_s.is_not(None),
                            ),
                        ),
                        1,
                    ),
                    else_=0,
                )
            ),
        )
        .filter(SessionClipCandidate.session_video_id == video_id)
        .one()
    )
    total_positives = int(totals[0] or 0)
    total_negatives = int(totals[1] or 0)
    total_trimmed = int(totals[2] or 0)
    total_runs = int(
        db.query(func.count(SessionClipRun.id))
        .filter(SessionClipRun.session_video_id == video_id)
        .scalar()
        or 0
    )

    def _dumps(obj: Any) -> str:
        return json.dumps(obj, ensure_ascii=False, allow_nan=False)

    start_section = cursor_state["s"] if cursor_state else "positives"
    section_order = {"positives": 0, "negatives": 1, "runs": 2}
    start_rank = section_order[start_section]

    prefix_bytes = (
        '{"schema_version":"session_clip_gt_v1",'
        f'"session_video_id":{_dumps(video_id)},'
        f'"session_id":{_dumps(session_id)},'
        f'"filename":{_dumps(filename)},'
        f'"duration_seconds":{_dumps(duration_seconds)},'
        f'"counts":{{"positives":{total_positives},"negatives":{total_negatives},"trimmed":{total_trimmed}}},'
        '"positives":['
    ).encode("utf-8")
    yield prefix_bytes

    emitted_bytes = len(prefix_bytes)
    emitted_items = 0
    chunks_used = 0
    next_cursor: Optional[str] = None
    runs_has_more = False

    def _budget_reached(extra_bytes: int = 0) -> bool:
        return emitted_items > 0 and (
            (emitted_bytes + extra_bytes) > byte_budget or chunks_used >= GT_EXPORT_MAX_CHUNKS
        )

    # 1. Stream positives (kept) in keyset order (start_s ASC, id ASC)
    if start_rank <= 0 and next_cursor is None:
        first_pos = True
        last_start_s: Optional[float] = (
            float(cursor_state["start_s"])
            if cursor_state and start_section == "positives" and "start_s" in cursor_state
            else None
        )
        last_id: Optional[int] = (
            int(cursor_state["id"])
            if cursor_state and start_section == "positives" and "id" in cursor_state
            else None
        )
        while True:
            if _budget_reached():
                has_any = (
                    db.query(SessionClipCandidate.id)
                    .filter(
                        SessionClipCandidate.session_video_id == video_id,
                        SessionClipCandidate.triage_status == "kept",
                        *(
                            [
                                or_(
                                    SessionClipCandidate.start_s > last_start_s,
                                    and_(
                                        SessionClipCandidate.start_s == last_start_s,
                                        SessionClipCandidate.id > last_id,
                                    ),
                                )
                            ]
                            if last_start_s is not None and last_id is not None
                            else []
                        ),
                    )
                    .limit(1)
                    .first()
                    is not None
                )
                if has_any:
                    state = (
                        {"s": "positives", "start_s": last_start_s, "id": last_id}
                        if last_start_s is not None and last_id is not None
                        else {"s": "positives"}
                    )
                    next_cursor = _encode_gt_export_cursor(state)
                break

            q = db.query(
                SessionClipCandidate.id,
                SessionClipCandidate.start_s,
                SessionClipCandidate.end_s,
                SessionClipCandidate.trimmed_start_s,
                SessionClipCandidate.trimmed_end_s,
                SessionClipCandidate.confidence,
                SessionClipCandidate.diver_id,
                SessionClipCandidate.dive_code,
                SessionClipCandidate.height,
                SessionClipCandidate.performance,
                SessionClipCandidate.dive_id,
            ).filter(
                SessionClipCandidate.session_video_id == video_id,
                SessionClipCandidate.triage_status == "kept",
            )
            if last_start_s is not None and last_id is not None:
                q = q.filter(
                    or_(
                        SessionClipCandidate.start_s > last_start_s,
                        and_(
                            SessionClipCandidate.start_s == last_start_s,
                            SessionClipCandidate.id > last_id,
                        ),
                    )
                )
            rows = (
                q.order_by(SessionClipCandidate.start_s.asc(), SessionClipCandidate.id.asc())
                .limit(GT_STREAM_CHUNK_SIZE + 1)
                .all()
            )
            chunks_used += 1
            more_in_db = len(rows) > GT_STREAM_CHUNK_SIZE
            chunk = rows[:GT_STREAM_CHUNK_SIZE]
            if not chunk:
                break
            diver_ids = [
                did
                for did in {row[6] for row in chunk if row[6] is not None}
                if visible_diver_ids is None or did in visible_diver_ids
            ]
            with unscoped_reads(db):
                divers_by_id = (
                    {
                        d.id: d.display_name
                        for d in db.query(Diver.id, Diver.display_name).filter(Diver.id.in_(diver_ids)).all()
                    }
                    if diver_ids
                    else {}
                )
            parts: list[bytes] = []
            stopped_mid_chunk = False
            for (
                cid,
                start_s,
                end_s,
                trimmed_start_s,
                trimmed_end_s,
                confidence,
                diver_id,
                dive_code,
                height,
                performance,
                dive_id,
            ) in chunk:
                was_trimmed = trimmed_start_s is not None or trimmed_end_s is not None
                mask_diver = (
                    diver_id is not None
                    and visible_diver_ids is not None
                    and diver_id not in visible_diver_ids
                )
                entry = {
                    "candidate_id": cid,
                    "start_s": trimmed_start_s if trimmed_start_s is not None else start_s,
                    "end_s": trimmed_end_s if trimmed_end_s is not None else end_s,
                    "original_start_s": start_s,
                    "original_end_s": end_s,
                    "trimmed": was_trimmed,
                    "confidence": confidence,
                    "diver_id": None if mask_diver else diver_id,
                    "diver_name": None if mask_diver else (divers_by_id.get(diver_id) if diver_id is not None else None),
                    "dive_code": None if mask_diver else dive_code,
                    "height": None if mask_diver else height,
                    "performance": None if mask_diver else performance,
                    "dive_id": None if mask_diver else dive_id,
                }
                encoded = (("" if first_pos else ",") + _dumps(entry)).encode("utf-8")
                if emitted_items > 0 and (emitted_bytes + len(encoded)) > byte_budget:
                    state = (
                        {"s": "positives", "start_s": last_start_s, "id": last_id}
                        if last_start_s is not None and last_id is not None
                        else {"s": "positives"}
                    )
                    next_cursor = _encode_gt_export_cursor(state)
                    stopped_mid_chunk = True
                    break
                parts.append(encoded)
                emitted_bytes += len(encoded)
                emitted_items += 1
                first_pos = False
                last_start_s = float(start_s)
                last_id = int(cid)
            if parts:
                yield b"".join(parts)
            if stopped_mid_chunk or not more_in_db:
                break

    sep_neg = b'],"negatives":['
    yield sep_neg
    emitted_bytes += len(sep_neg)

    # 2. Stream negatives (rejected) in keyset order (start_s ASC, id ASC)
    if start_rank <= 1 and next_cursor is None:
        first_neg = True
        last_start_s = (
            float(cursor_state["start_s"])
            if cursor_state and start_section == "negatives" and "start_s" in cursor_state
            else None
        )
        last_id = (
            int(cursor_state["id"])
            if cursor_state and start_section == "negatives" and "id" in cursor_state
            else None
        )
        while True:
            if _budget_reached():
                has_any = (
                    db.query(SessionClipCandidate.id)
                    .filter(
                        SessionClipCandidate.session_video_id == video_id,
                        SessionClipCandidate.triage_status == "rejected",
                        *(
                            [
                                or_(
                                    SessionClipCandidate.start_s > last_start_s,
                                    and_(
                                        SessionClipCandidate.start_s == last_start_s,
                                        SessionClipCandidate.id > last_id,
                                    ),
                                )
                            ]
                            if last_start_s is not None and last_id is not None
                            else []
                        ),
                    )
                    .limit(1)
                    .first()
                    is not None
                )
                if has_any:
                    state = (
                        {"s": "negatives", "start_s": last_start_s, "id": last_id}
                        if last_start_s is not None and last_id is not None
                        else {"s": "negatives"}
                    )
                    next_cursor = _encode_gt_export_cursor(state)
                break

            q = db.query(
                SessionClipCandidate.id,
                SessionClipCandidate.start_s,
                SessionClipCandidate.end_s,
                SessionClipCandidate.trimmed_start_s,
                SessionClipCandidate.trimmed_end_s,
                SessionClipCandidate.confidence,
                SessionClipCandidate.reject_reason,
            ).filter(
                SessionClipCandidate.session_video_id == video_id,
                SessionClipCandidate.triage_status == "rejected",
            )
            if last_start_s is not None and last_id is not None:
                q = q.filter(
                    or_(
                        SessionClipCandidate.start_s > last_start_s,
                        and_(
                            SessionClipCandidate.start_s == last_start_s,
                            SessionClipCandidate.id > last_id,
                        ),
                    )
                )
            rows = (
                q.order_by(SessionClipCandidate.start_s.asc(), SessionClipCandidate.id.asc())
                .limit(GT_STREAM_CHUNK_SIZE + 1)
                .all()
            )
            chunks_used += 1
            more_in_db = len(rows) > GT_STREAM_CHUNK_SIZE
            chunk = rows[:GT_STREAM_CHUNK_SIZE]
            if not chunk:
                break
            parts = []
            stopped_mid_chunk = False
            for cid, start_s, end_s, trimmed_start_s, trimmed_end_s, confidence, reject_reason in chunk:
                was_trimmed = trimmed_start_s is not None or trimmed_end_s is not None
                entry = {
                    "candidate_id": cid,
                    "start_s": trimmed_start_s if trimmed_start_s is not None else start_s,
                    "end_s": trimmed_end_s if trimmed_end_s is not None else end_s,
                    "original_start_s": start_s,
                    "original_end_s": end_s,
                    "trimmed": was_trimmed,
                    "confidence": confidence,
                    "reject_reason": reject_reason or "false_positive",
                }
                encoded = (("" if first_neg else ",") + _dumps(entry)).encode("utf-8")
                if emitted_items > 0 and (emitted_bytes + len(encoded)) > byte_budget:
                    state = (
                        {"s": "negatives", "start_s": last_start_s, "id": last_id}
                        if last_start_s is not None and last_id is not None
                        else {"s": "negatives"}
                    )
                    next_cursor = _encode_gt_export_cursor(state)
                    stopped_mid_chunk = True
                    break
                parts.append(encoded)
                emitted_bytes += len(encoded)
                emitted_items += 1
                first_neg = False
                last_start_s = float(start_s)
                last_id = int(cid)
            if parts:
                yield b"".join(parts)
            if stopped_mid_chunk or not more_in_db:
                break

    sep_runs = b'],"runs":['
    yield sep_runs
    emitted_bytes += len(sep_runs)

    # 3. Stream runs in keyset order (created_at DESC, id DESC)
    if next_cursor is None:
        first_run = True
        last_created_at: Optional[datetime] = (
            cursor_state["created_at"]
            if cursor_state and start_section == "runs" and "created_at" in cursor_state
            else None
        )
        last_run_id: Optional[int] = (
            int(cursor_state["id"])
            if cursor_state and start_section == "runs" and "id" in cursor_state
            else None
        )
        while True:
            if _budget_reached():
                has_any = (
                    db.query(SessionClipRun.id)
                    .filter(
                        SessionClipRun.session_video_id == video_id,
                        *(
                            [
                                or_(
                                    SessionClipRun.created_at < last_created_at,
                                    and_(
                                        SessionClipRun.created_at == last_created_at,
                                        SessionClipRun.id < last_run_id,
                                    ),
                                )
                            ]
                            if last_created_at is not None and last_run_id is not None
                            else []
                        ),
                    )
                    .limit(1)
                    .first()
                    is not None
                )
                if has_any:
                    state = (
                        {
                            "s": "runs",
                            "created_at": last_created_at.isoformat(),
                            "id": last_run_id,
                        }
                        if last_created_at is not None and last_run_id is not None
                        else {"s": "runs"}
                    )
                    next_cursor = _encode_gt_export_cursor(state)
                    runs_has_more = True
                break

            rq = db.query(
                SessionClipRun.id,
                SessionClipRun.session_video_id,
                SessionClipRun.detector_name,
                SessionClipRun.detector_version,
                SessionClipRun.submitted_count,
                SessionClipRun.created_count,
                SessionClipRun.deduped_count,
                SessionClipRun.created_at,
            ).filter(SessionClipRun.session_video_id == video_id)
            if last_created_at is not None and last_run_id is not None:
                rq = rq.filter(
                    or_(
                        SessionClipRun.created_at < last_created_at,
                        and_(
                            SessionClipRun.created_at == last_created_at,
                            SessionClipRun.id < last_run_id,
                        ),
                    )
                )
            run_rows = (
                rq.order_by(SessionClipRun.created_at.desc(), SessionClipRun.id.desc())
                .limit(GT_STREAM_RUN_CHUNK_SIZE + 1)
                .all()
            )
            chunks_used += 1
            more_runs_in_db = len(run_rows) > GT_STREAM_RUN_CHUNK_SIZE
            run_chunk = run_rows[:GT_STREAM_RUN_CHUNK_SIZE]
            if not run_chunk:
                break
            run_ids = [int(r[0]) for r in run_chunk]
            match_stats = (
                db.query(
                    SessionClipRunMatch.run_id,
                    func.sum(case((SessionClipCandidate.triage_status == "kept", 1), else_=0)),
                    func.sum(case((SessionClipCandidate.triage_status == "rejected", 1), else_=0)),
                    func.sum(case((SessionClipCandidate.triage_status == "pending", 1), else_=0)),
                )
                .join(SessionClipCandidate, SessionClipCandidate.id == SessionClipRunMatch.candidate_id)
                .filter(SessionClipRunMatch.run_id.in_(run_ids))
                .group_by(SessionClipRunMatch.run_id)
                .all()
            )
            stats_by_run = {
                int(rid): (int(k or 0), int(rej or 0), int(pend or 0))
                for rid, k, rej, pend in match_stats
            }
            parts = []
            stopped_mid_chunk = False
            for (
                rid,
                sv_id,
                det_name,
                det_ver,
                sub_cnt,
                cre_cnt,
                ded_cnt,
                created_at,
            ) in run_chunk:
                tp, fp, pend = stats_by_run.get(int(rid), (0, 0, 0))
                triaged = tp + fp
                precision = round(tp / triaged, 4) if triaged > 0 else None
                recall = round(tp / total_positives, 4) if total_positives > 0 else None
                run_obj = {
                    "id": rid,
                    "session_video_id": sv_id,
                    "detector_name": det_name,
                    "detector_version": det_ver,
                    "submitted_count": sub_cnt,
                    "created_count": cre_cnt,
                    "deduped_count": ded_cnt,
                    "kept_matches": tp,
                    "rejected_matches": fp,
                    "pending_matches": pend,
                    "precision": precision,
                    "recall": recall,
                    "created_at": created_at.replace(tzinfo=timezone.utc).isoformat(),
                }
                encoded = (("" if first_run else ",") + _dumps(run_obj)).encode("utf-8")
                if emitted_items > 0 and (emitted_bytes + len(encoded)) > byte_budget:
                    state = (
                        {
                            "s": "runs",
                            "created_at": last_created_at.isoformat(),
                            "id": last_run_id,
                        }
                        if last_created_at is not None and last_run_id is not None
                        else {"s": "runs"}
                    )
                    next_cursor = _encode_gt_export_cursor(state)
                    runs_has_more = True
                    stopped_mid_chunk = True
                    break
                parts.append(encoded)
                emitted_bytes += len(encoded)
                emitted_items += 1
                first_run = False
                last_created_at = created_at
                last_run_id = int(rid)
            if parts:
                yield b"".join(parts)
            if stopped_mid_chunk or not more_runs_in_db:
                break
    elif total_runs > 0:
        runs_has_more = True

    has_more = next_cursor is not None
    yield (
        f'],"runs_total":{total_runs},'
        f'"runs_has_more":{"true" if runs_has_more else "false"},'
        '"runs_next_offset":null,'
        f'"has_more":{"true" if has_more else "false"},'
        '"next_offset":null,'
        f'"next_cursor":{_dumps(next_cursor)}}}\n'
    ).encode("utf-8")


# ----------------------------------------- Durable orphan B2 object ledger ---


def record_staging_b2_object(
    db: Session,
    *,
    bucket: str,
    object_key: str,
    blob_sha256: str,
    byte_size: int,
    candidate_id: Optional[int] = None,
) -> None:
    """Durably track a staged B2 clip object before DB commit so failed finalizations can be reclaimed.

    Serializes against `reclaim_orphan_clip_objects` via `FOR UPDATE` on `(bucket, object_key)`.
    If a durable delete claim (`status == 'deleting'`) is in flight for this exact object,
    rejects with a retryable 503 so no publisher uploads or commits into a key being deleted.
    """
    now = datetime.utcnow()
    eligible_after = now + ORPHAN_B2_GRACE_PERIOD
    existing = (
        db.query(SessionClipOrphanObject)
        .filter_by(bucket=bucket, object_key=object_key)
        .with_for_update()
        .first()
    )
    if existing is not None:
        if existing.status == "deleting":
            db.rollback()
            raise HTTPException(
                503,
                "Storage object reclamation in progress; retry shortly",
                headers={"Retry-After": "5"},
            )
        if existing.status != "retained":
            existing.blob_sha256 = blob_sha256
            existing.byte_size = max(0, int(byte_size))
            existing.candidate_id = candidate_id
            existing.status = "pending"
            existing.eligible_after = eligible_after
            existing.reclaimed_at = None
            existing.last_error = None
            db.commit()
        else:
            db.rollback()
        return

    row = SessionClipOrphanObject(
        bucket=bucket,
        object_key=object_key,
        blob_sha256=blob_sha256,
        byte_size=max(0, int(byte_size)),
        candidate_id=candidate_id,
        status="pending",
        created_at=now,
        eligible_after=eligible_after,
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        existing = (
            db.query(SessionClipOrphanObject)
            .filter_by(bucket=bucket, object_key=object_key)
            .with_for_update()
            .first()
        )
        if existing is not None:
            if existing.status == "deleting":
                db.rollback()
                raise HTTPException(
                    503,
                    "Storage object reclamation in progress; retry shortly",
                    headers={"Retry-After": "5"},
                ) from None
            if existing.status != "retained":
                existing.blob_sha256 = blob_sha256
                existing.byte_size = max(0, int(byte_size))
                existing.candidate_id = candidate_id
                existing.status = "pending"
                existing.eligible_after = eligible_after
                existing.reclaimed_at = None
                existing.last_error = None
    db.commit()


def claim_b2_object_retained(
    db: Session,
    *,
    bucket: str,
    object_key: str,
    fail_open_missing_table: bool = False,
) -> None:
    """Serialize publication against orphan reclamation by locking `(bucket, object_key)` `FOR UPDATE`.

    Called inside the publisher's commit transaction BEFORE writing `MediaBlobLocation`/`MediaRevision`.
    If the reclaimer already holds a durable `'deleting'` claim (or already `'reclaimed'` the object),
    raises retryable HTTP 503 so no published dive can ever reference deleted B2 bytes.
    """
    if not bucket or not object_key:
        return
    try:
        with db.begin_nested():
            row = (
                db.query(SessionClipOrphanObject)
                .filter_by(bucket=bucket, object_key=object_key)
                .with_for_update()
                .first()
            )
    except (OperationalError, ProgrammingError):
        if fail_open_missing_table:
            return
        raise
    if row is None:
        return
    if row.status in ("deleting", "reclaimed"):
        raise HTTPException(
            503,
            "Storage object was reclaimed or is being deleted; retry upload",
            headers={"Retry-After": "5"},
        )
    if row.status != "retained":
        row.status = "retained"
        row.reclaimed_at = datetime.utcnow()
        row.last_error = None
        db.flush()


def _b2_object_is_referenced(db: Session, bucket: str, object_key: str, blob_sha256: str) -> bool:
    """Return True if any committed media backbone record still references this object or content SHA."""
    if (
        db.query(MediaBlobLocation.id)
        .filter(
            or_(
                and_(
                    MediaBlobLocation.bucket == bucket,
                    MediaBlobLocation.object_key == object_key,
                ),
                and_(
                    MediaBlobLocation.bucket == bucket,
                    MediaBlobLocation.blob_sha256 == blob_sha256,
                ),
            )
        )
        .limit(1)
        .first()
        is not None
    ):
        return True
    if (
        db.query(MediaRevision.id)
        .filter(MediaRevision.blob_sha256 == blob_sha256)
        .limit(1)
        .first()
        is not None
    ):
        return True
    if (
        db.query(MediaBlob.sha256)
        .filter(MediaBlob.sha256 == blob_sha256)
        .limit(1)
        .first()
        is not None
    ):
        return True
    return False


def reclaim_orphan_clip_objects(
    db: Session,
    *,
    limit: int = MAX_ORPHAN_RECLAIM_BATCH,
    delete_fn=None,
) -> dict[str, int]:
    """Reclaim uncommitted staged B2 clip objects past their grace period using a durable delete claim.

    Protocol (zero TOCTOU between reclaimer and publishers):
    1. Lock the `(bucket, object_key)` row `FOR UPDATE`, verify due grace + zero references,
       and commit `status = 'deleting'` BEFORE releasing the DB transaction.
    2. While `status == 'deleting'`, every publisher (`record_staging_b2_object`,
       `complete_clip_cut`, `browser_upload.persist_original`) refuses to commit references
       to that object (retryable 503).
    3. Execute remote B2 `delete_object` with no DB lock held.
    4. Commit `status = 'reclaimed'` on success; on transient error keep `status = 'deleting'`
       and push `eligible_after` by retry backoff so the delete completes on a later tick.
    """
    bounded = max(1, min(int(limit), 50))
    now = datetime.utcnow()
    stats = {"reclaimed": 0, "retained": 0, "failed": 0}
    try:
        due_rows = (
            db.query(
                SessionClipOrphanObject.id,
                SessionClipOrphanObject.bucket,
                SessionClipOrphanObject.object_key,
                SessionClipOrphanObject.blob_sha256,
            )
            .filter(
                SessionClipOrphanObject.status.in_(("pending", "deleting")),
                SessionClipOrphanObject.eligible_after <= now,
            )
            .order_by(SessionClipOrphanObject.eligible_after.asc(), SessionClipOrphanObject.id.asc())
            .limit(bounded)
            .all()
        )
    except (OperationalError, ProgrammingError):
        db.rollback()
        return stats

    deleter = delete_fn or browser_upload.delete_b2_object
    for row_id, bucket, object_key, blob_sha256 in due_rows:
        check_time = datetime.utcnow()
        # Step 1: Lock row FOR UPDATE, verify grace & references, and commit durable 'deleting' claim.
        live = (
            db.query(SessionClipOrphanObject)
            .filter(
                SessionClipOrphanObject.id == row_id,
                SessionClipOrphanObject.status.in_(("pending", "deleting")),
                SessionClipOrphanObject.eligible_after <= check_time,
            )
            .with_for_update()
            .first()
        )
        if live is None:
            db.rollback()
            continue
        if _b2_object_is_referenced(db, bucket, object_key, blob_sha256):
            live.status = "retained"
            live.reclaimed_at = check_time
            live.last_error = None
            db.commit()
            stats["retained"] += 1
            continue

        live.status = "deleting"
        live.eligible_after = check_time + ORPHAN_DELETE_CLAIM_TTL
        live.last_error = None
        db.commit()

        # Step 2: Remote B2 DELETE runs with NO DB lock held, fenced by durable 'deleting' claim.
        try:
            deleter(bucket, object_key)
        except Exception as exc:
            err_msg = sanitize_worker_error(str(exc))
            (
                db.query(SessionClipOrphanObject)
                .filter(
                    SessionClipOrphanObject.id == row_id,
                    SessionClipOrphanObject.status == "deleting",
                )
                .update(
                    {
                        SessionClipOrphanObject.eligible_after: datetime.utcnow() + ORPHAN_B2_RETRY_BACKOFF,
                        SessionClipOrphanObject.last_error: err_msg,
                    },
                    synchronize_session=False,
                )
            )
            db.commit()
            stats["failed"] += 1
            continue

        # Step 3: Finalize durable 'reclaimed' state.
        (
            db.query(SessionClipOrphanObject)
            .filter(
                SessionClipOrphanObject.id == row_id,
                SessionClipOrphanObject.status == "deleting",
            )
            .update(
                {
                    SessionClipOrphanObject.status: "reclaimed",
                    SessionClipOrphanObject.reclaimed_at: datetime.utcnow(),
                    SessionClipOrphanObject.last_error: None,
                },
                synchronize_session=False,
            )
        )
        db.commit()
        stats["reclaimed"] += 1

    return stats


# --------------------------------------------------- Mac-agent clip cut lease ---


def lease_clip_cuts(db: Session, *, agent_id: str, limit: int = 1) -> list[dict[str, Any]]:
    """Atomically lease queued (or expired-lease) kept clips for Mac-agent ffmpeg cut."""
    bounded = max(1, min(limit, 4))
    now = datetime.utcnow()
    lease_until = now + CUT_LEASE_TTL

    # 1. Bounded sweep: fail expired leases that exhausted MAX_EXTRACTION_ATTEMPTS
    # so they never stay stuck in claimed/extracting forever.
    exhausted_ids = [
        r[0]
        for r in db.query(SessionClipCandidate.id)
        .filter(
            SessionClipCandidate.extraction_status.in_(("claimed", "extracting")),
            SessionClipCandidate.claimed_until < now,
            SessionClipCandidate.extraction_attempts >= MAX_EXTRACTION_ATTEMPTS,
        )
        .limit(50)
        .all()
    ]
    if exhausted_ids:
        (
            db.query(SessionClipCandidate)
            .filter(
                SessionClipCandidate.id.in_(exhausted_ids),
                SessionClipCandidate.extraction_status.in_(("claimed", "extracting")),
                SessionClipCandidate.claimed_until < now,
            )
            .update(
                {
                    SessionClipCandidate.extraction_status: "failed",
                    SessionClipCandidate.extraction_error: "Cut lease expired after max attempts",
                    SessionClipCandidate.lease_token: None,
                    SessionClipCandidate.claimed_by: None,
                    SessionClipCandidate.claimed_until: None,
                    SessionClipCandidate.updated_at: now,
                },
                synchronize_session=False,
            )
        )

    # 2. Lease up to `bounded` ready jobs whose source video has a verified non-empty ETag.
    # Joining SessionVideo here prevents missing-ETag or deleted videos from starving valid clips.
    query = (
        db.query(SessionClipCandidate)
        .join(SessionVideo, SessionVideo.id == SessionClipCandidate.session_video_id)
        .filter(
            SessionVideo.status == "ready",
            SessionVideo.deleted_at.is_(None),
            SessionVideo.etag.is_not(None),
            SessionVideo.etag != "",
            SessionClipCandidate.triage_status == "kept",
            SessionClipCandidate.dive_id.is_(None),
            SessionClipCandidate.extraction_attempts < MAX_EXTRACTION_ATTEMPTS,
            or_(
                SessionClipCandidate.extraction_status == "queued",
                and_(
                    SessionClipCandidate.extraction_status.in_(("claimed", "extracting")),
                    SessionClipCandidate.claimed_until < now,
                ),
            ),
        )
        .order_by(SessionClipCandidate.updated_at.asc(), SessionClipCandidate.id.asc())
        .limit(bounded)
    )
    if db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update(of=SessionClipCandidate, skip_locked=True)
    else:
        query = query.with_for_update()

    candidates = query.all()
    if not candidates:
        if exhausted_ids:
            db.commit()
        return []

    video_ids = list({c.session_video_id for c in candidates})
    videos = {
        v.id: v
        for v in db.query(SessionVideo)
        .filter(
            SessionVideo.id.in_(video_ids),
            SessionVideo.status == "ready",
            SessionVideo.deleted_at.is_(None),
            SessionVideo.etag.is_not(None),
            SessionVideo.etag != "",
        )
        .all()
    }

    # Snapshot plain job dicts BEFORE db.commit() so no post-commit ORM reloads run.
    snapshots: list[dict[str, Any]] = []
    for cand in candidates:
        video = videos.get(cand.session_video_id)
        if video is None or not (video.etag or "").strip():
            continue
        if cand.clip_video_uuid is None:
            cand.clip_video_uuid = str(uuid.uuid4())
        token = str(uuid.uuid4())
        cand.extraction_status = "claimed"
        cand.lease_token = token
        cand.claimed_by = agent_id[:100]
        cand.claimed_at = now
        cand.claimed_until = lease_until
        cand.extraction_attempts += 1
        cand.extraction_error = None
        cand.source_etag = video.etag
        snapshots.append(
            {
                "candidate_id": cand.id,
                "session_video_id": video.id,
                "clip_video_uuid": cand.clip_video_uuid,
                "cut_revision": cand.cut_revision,
                "lease_token": token,
                "claimed_until": lease_until.replace(tzinfo=timezone.utc).isoformat(),
                "start_s": cand.effective_start_s,
                "end_s": cand.effective_end_s,
                "source_filename": PurePosixPath(video.object_key).name,
                "color_transfer": video.color_transfer,
                "source_etag": video.etag,
                "_bucket": video.bucket,
                "_object_key": video.object_key,
            }
        )

    db.commit()

    # Presign B2 URLs AFTER releasing the DB transaction (bound to source_etag via If-Match when present).
    # If B2 storage is temporarily unavailable, defer the lease without consuming an attempt and omit
    # the job so workers never fail it against a missing presigned URL.
    jobs = []
    deferred_leases: list[tuple[int, str]] = []
    for snap in snapshots:
        bucket = snap.pop("_bucket")
        key = snap.pop("_object_key")
        etag = snap.get("source_etag")
        try:
            source_url = sv_service.presign_get(
                bucket,
                key,
                CUT_SOURCE_URL_TTL_SECONDS,
                if_match=etag,
            )
        except sv_service.SessionsStorageUnavailable:
            logger.warning(
                "Deferring clip cut lease for candidate %s: session video storage unavailable",
                snap["candidate_id"],
            )
            deferred_leases.append((int(snap["candidate_id"]), str(snap["lease_token"])))
            continue
        snap["source_url"] = source_url
        jobs.append(snap)

    if deferred_leases:
        for cid, token in deferred_leases:
            (
                db.query(SessionClipCandidate)
                .filter(
                    SessionClipCandidate.id == cid,
                    SessionClipCandidate.extraction_status == "claimed",
                    SessionClipCandidate.lease_token == token,
                )
                .update(
                    {
                        SessionClipCandidate.extraction_status: "queued",
                        SessionClipCandidate.extraction_attempts: case(
                            (
                                SessionClipCandidate.extraction_attempts > 0,
                                SessionClipCandidate.extraction_attempts - 1,
                            ),
                            else_=0,
                        ),
                        SessionClipCandidate.lease_token: None,
                        SessionClipCandidate.claimed_by: None,
                        SessionClipCandidate.claimed_at: None,
                        SessionClipCandidate.claimed_until: None,
                    },
                    synchronize_session=False,
                )
            )
        db.commit()
    return jobs


def require_valid_lease_context(
    db: Session,
    candidate_id: int,
    agent_id: str,
    lease_token: str,
    cut_revision: int,
) -> tuple[SessionVideo, SessionClipCandidate]:
    """Lock SessionVideo then SessionClipCandidate in consistent order and verify lease."""
    vid_row = db.query(SessionClipCandidate.session_video_id).filter_by(id=candidate_id).first()
    if vid_row is None:
        raise HTTPException(404, "Clip cut job not found")

    video = db.query(SessionVideo).filter_by(id=vid_row[0]).with_for_update().first()
    cand = db.query(SessionClipCandidate).filter_by(id=candidate_id).with_for_update().first()
    if cand is None or video is None or video.status != "ready" or video.deleted_at is not None:
        raise HTTPException(409, "Source session video is no longer available")
    if (
        cand.triage_status != "kept"
        or cand.extraction_status not in ("claimed", "extracting")
        or cand.claimed_by != agent_id
        or cand.lease_token != lease_token
        or cand.cut_revision != cut_revision
    ):
        raise HTTPException(409, "Clip cut lease expired or superseded")
    if cand.claimed_until is not None and cand.claimed_until < datetime.utcnow():
        raise HTTPException(409, "Clip cut lease expired")
    if not cand.source_etag or not video.etag or cand.source_etag != video.etag:
        raise HTTPException(409, "Source session video ETag missing or changed during cut")
    return video, cand


def heartbeat_clip_cut(
    db: Session,
    *,
    candidate_id: int,
    agent_id: str,
    lease_token: str,
    cut_revision: int,
) -> dict[str, Any]:
    _, cand = require_valid_lease_context(db, candidate_id, agent_id, lease_token, cut_revision)
    now = datetime.utcnow()
    cand.extraction_status = "extracting"
    cand.claimed_until = now + CUT_LEASE_TTL
    db.commit()
    return {
        "candidate_id": cand.id,
        "status": cand.extraction_status,
        "claimed_until": cand.claimed_until.replace(tzinfo=timezone.utc).isoformat(),
    }


def fail_clip_cut(
    db: Session,
    *,
    candidate_id: int,
    agent_id: str,
    lease_token: str,
    cut_revision: int,
    error: str,
) -> dict[str, Any]:
    _, cand = require_valid_lease_context(db, candidate_id, agent_id, lease_token, cut_revision)
    now = datetime.utcnow()
    retryable = cand.extraction_attempts < MAX_EXTRACTION_ATTEMPTS
    cand.extraction_status = "queued" if retryable else "failed"
    cand.extraction_error = sanitize_worker_error(error)
    cand.lease_token = None
    cand.claimed_by = None
    cand.claimed_until = None
    cand.updated_at = now
    db.commit()
    return {
        "candidate_id": cand.id,
        "status": cand.extraction_status,
        "attempts": cand.extraction_attempts,
    }


def _unlink_replaced_paths(paths: list[Path]) -> None:
    for p in paths:
        try:
            p.unlink(missing_ok=True)
            parent = p.parent
            if parent.name.startswith("cand-"):
                parent.rmdir()
        except OSError:
            pass


def complete_clip_cut(
    db: Session,
    *,
    candidate_id: int,
    agent_id: str,
    lease_token: str,
    cut_revision: int,
    mp4_path: Path,
    mp4_sha256: str,
    mp4_size_bytes: int,
    b2_manifest: dict[str, Any],
    poster_path: Optional[Path] = None,
    poster_sha256: Optional[str] = None,
    poster_size_bytes: Optional[int] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    duration_seconds: Optional[float] = None,
) -> dict[str, Any]:
    """Verify fenced lease + B2 durability, register asset/cache, and publish if confirmed."""
    video, cand = require_valid_lease_context(db, candidate_id, agent_id, lease_token, cut_revision)

    now = datetime.utcnow()
    clip_uuid = cand.clip_video_uuid
    if not clip_uuid:
        raise HTTPException(409, "Clip identity missing")

    replaced_paths: list[Path] = []
    remote_ok = browser_upload.remote_playback_configured()

    with unscoped_reads(db):
        asset = db.query(PhotosAsset).filter_by(video_uuid=clip_uuid).first()
        if asset is None:
            clip_dt = (
                video.recorded_at + timedelta(seconds=cand.effective_start_s)
                if video.recorded_at
                else now
            )
            asset = PhotosAsset(
                video_uuid=clip_uuid,
                original_filename=f"session_{video.id}_clip_{cand.id}.mp4",
                media_type="video",
                file_size_bytes=mp4_size_bytes,
                photos_created_at=clip_dt,
            )
            db.add(asset)
            db.flush()

        # Serialize publication against orphan reclamation BEFORE committing MediaBlobLocation/MediaRevision!
        if b2_manifest.get("bucket") and b2_manifest.get("object_key"):
            claim_b2_object_retained(
                db,
                bucket=str(b2_manifest["bucket"]),
                object_key=str(b2_manifest["object_key"]),
            )
        # Commit durable verified B2 original revision before publishing!
        commit_verified_ingest(db, **b2_manifest, commit=False)

        def _upsert_cache(
            rendition: str,
            path: Path,
            content_type: str,
            size: int,
            sha: str,
            pinned: bool,
            expires_at: Optional[datetime],
        ):
            media_key = build_media_key(clip_uuid, rendition)
            entry = db.query(MediaCacheEntry).filter_by(media_key=media_key).first()
            if entry is None:
                entry = MediaCacheEntry(
                    photos_asset_id=asset.id,
                    media_key=media_key,
                    rendition=rendition,
                    storage_backend="local_fs",
                    storage_path=str(path),
                    content_type=content_type,
                    size_bytes=size,
                    checksum_sha256=sha,
                    width=width,
                    height=height,
                    duration_seconds=duration_seconds,
                    status="ready",
                    pinned=pinned,
                    expires_at=expires_at,
                )
                db.add(entry)
            else:
                old = Path(entry.storage_path)
                if old != path:
                    replaced_paths.append(old)
                entry.storage_path = str(path)
                entry.size_bytes = size
                entry.checksum_sha256 = sha
                entry.width = width
                entry.height = height
                entry.duration_seconds = duration_seconds
                entry.status = "ready"
                entry.pinned = pinned
                entry.expires_at = expires_at

        _upsert_cache(
            "original",
            mp4_path,
            "video/mp4",
            mp4_size_bytes,
            mp4_sha256,
            pinned=not remote_ok,
            expires_at=now + timedelta(days=30),
        )
        if poster_path is not None and poster_sha256 and poster_size_bytes:
            _upsert_cache(
                "poster",
                poster_path,
                "image/jpeg",
                poster_size_bytes,
                poster_sha256,
                pinned=True,
                expires_at=None,
            )

    cand.photos_asset_id = asset.id
    cand.extraction_status = "ready"
    cand.extraction_error = None
    cand.lease_token = None
    cand.claimed_by = None
    cand.claimed_at = None
    cand.claimed_until = None
    cand.updated_at = now
    db.flush()

    dive = None
    try:
        with db.begin_nested():
            dive = maybe_publish_candidate(db, cand, video, retired_paths=replaced_paths)
    except Exception:
        logger.exception(
            "clip triage: deferred publish failed for candidate=%s; keeping verified cut ready",
            cand.id,
        )
        cand.publish_requested_at = None
        cand.publish_requested_by_user_id = None
        cand.updated_at = datetime.utcnow()
    result = {
        "candidate_id": cand.id,
        "extraction_status": cand.extraction_status,
        "clip_video_uuid": cand.clip_video_uuid,
        "photos_asset_id": cand.photos_asset_id,
        "dive_id": dive.id if dive else cand.dive_id,
    }
    db.commit()

    # Clean superseded local files ONLY after commit succeeded.
    _unlink_replaced_paths(replaced_paths)
    return result
