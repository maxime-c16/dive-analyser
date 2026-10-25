"""Community rankings over a week or a month, from dives visible to the viewer.

Each member is credited with the non-lineup dives of the divers they OWN.
Everything is a GROUP BY: per-member counts for the period, a score
histogram per member for the current and previous period (exact medians,
see code_summaries), and the distinct dive days of the last STREAK_WEEKS
weeks for the weekly streak. The response stays small: the top BOARD_SIZE
entries of each ranking plus the viewer, who is always present even with
zeros (the UI shows the top 10 of the selected ranking plus the viewer).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import case, func, or_

from app.models.dive import Dive
from app.models.user_auth import AppUser, UserDiverAccess
from app.services.code_summaries import _median_from_hist, _round, _score_value
from app.services.dive_access import owned_diver_ids
from app.services.member_avatar import avatar_identity

PERIOD_DAYS = {"week": 7, "month": 30}
STREAK_WEEKS = 26
MIN_PROGRESS_ATTEMPTS = 5
BOARD_SIZE = 10


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _streak(days: set[date], today: date) -> int:
    """Consecutive weeks with a dive, ending this week (or last week if this one is still empty)."""
    weeks = {_monday(day) for day in days}
    week = _monday(today)
    if week not in weeks:
        week -= timedelta(days=7)
    count = 0
    while week in weeks:
        count += 1
        week -= timedelta(days=7)
    return count


def _board_value(member: dict, category: str):
    """Ranking value, mirroring the frontend Leaderboard categories."""
    if category == "streak":
        return member["streak_weeks"]
    if category == "progress":
        return member["delta"] if member["delta"] is not None else 0
    if category == "explorer":
        return member["codes"]
    return member["attempts"]


def leaderboard(db, visible_clause, period: str, now: datetime, viewer_id: int | None = None) -> dict:
    days = PERIOD_DAYS[period]
    start, previous = now - timedelta(days=days), now - timedelta(days=2 * days)
    streak_start = datetime.combine(_monday(now.date()) - timedelta(weeks=STREAK_WEEKS - 1), datetime.min.time())
    owner = UserDiverAccess.user_id
    base = db.query(Dive).join(UserDiverAccess, (UserDiverAccess.diver_id == Dive.diver_id) & (UserDiverAccess.access_kind == "OWNER")).join(
        AppUser, (AppUser.id == owner) & AppUser.is_active.is_(True),
    ).filter(Dive.is_lineup.is_(False), visible_clause)

    current = {uid: (n, sessions, codes, last) for uid, n, sessions, codes, last in base.filter(Dive.dive_datetime >= start).with_entities(
        owner, func.count(Dive.id), func.count(func.distinct(Dive.session_id)), func.count(func.distinct(Dive.dive_code)), func.max(Dive.dive_datetime),
    ).group_by(owner).all()}

    hist: dict[tuple[int, bool], dict[float, int]] = defaultdict(lambda: defaultdict(int))
    # One labelled expression, grouped by its alias: Postgres would reject two
    # separately bound copies of `dive_datetime >= :start` as different expressions.
    # The previous half is materialized only for members with enough current
    # attempts to clear the progress gate (their only use of previous dives).
    recent = case((Dive.dive_datetime >= start, 1), else_=0).label("recent")
    contenders = [uid for uid, (n, _, _, _) in current.items() if n >= MIN_PROGRESS_ATTEMPTS]
    for uid, is_recent, performance, phase1, phase2, n in base.filter(
        Dive.dive_datetime >= previous,
        or_(Dive.dive_datetime >= start, owner.in_(contenders)),
        Dive.performance.is_not(None), Dive.performance != "",
    ).with_entities(
        owner, recent, Dive.performance, Dive.phase1_performance, Dive.phase2_performance, func.count(Dive.id),
    ).group_by(owner, recent, Dive.performance, Dive.phase1_performance, Dive.phase2_performance).all():
        score = _score_value(performance, phase1, phase2)
        if score is not None:
            hist[(uid, bool(is_recent))][score] += n

    active_days: dict[int, set[date]] = defaultdict(set)
    for uid, day in base.filter(Dive.dive_datetime >= streak_start).with_entities(owner, func.date(Dive.dive_datetime)).distinct().all():
        active_days[uid].add(day if isinstance(day, date) else date.fromisoformat(str(day)[:10]))

    uids = set(current) | {uid for uid, days_ in active_days.items() if days_}
    if viewer_id is not None:
        uids.add(viewer_id)
    users = {row.id: row for row in db.query(AppUser).filter(AppUser.id.in_(uids)).all()} if uids else {}
    members = []
    for uid in uids:
        row = users.get(uid)
        if row is None:
            continue
        attempts, sessions, codes, last = current.get(uid, (0, 0, 0, None))
        now_hist, before_hist = hist.get((uid, True), {}), hist.get((uid, False), {})
        median = _median_from_hist(now_hist.items()) if now_hist else None
        delta = None
        if sum(now_hist.values()) >= MIN_PROGRESS_ATTEMPTS and sum(before_hist.values()) >= MIN_PROGRESS_ATTEMPTS:
            delta = _round(median - _median_from_hist(before_hist.items()))
        members.append({
            "user_id": uid, "display_name": row.display_name, "handle": row.handle, **avatar_identity(row),
            "attempts": attempts, "sessions": sessions, "codes": codes,
            "median": _round(median), "delta": delta,
            "streak_weeks": _streak(active_days.get(uid, set()), now.date()),
            "last_attempt_at": last.isoformat() if last else None,
        })
    members.sort(key=lambda member: (-member["attempts"], member["user_id"]))
    # Accounts bound to one of the viewer's own divers (a second login, a test
    # account) never rank for them — except the viewer, who is always kept.
    # Determined here, not from the client's paginated directory, so the
    # directory page cap cannot leak them onto the board.
    if viewer_id is not None:
        own = owned_diver_ids(db, viewer_id)
        if own:
            bound = {uid for (uid,) in db.query(UserDiverAccess.user_id).filter(
                UserDiverAccess.access_kind == "OWNER",
                UserDiverAccess.diver_id.in_(own),
                UserDiverAccess.user_id.in_(list(uids))).all()} if uids else set()
            members = [member for member in members if member["user_id"] == viewer_id or member["user_id"] not in bound]
    # The UI ranks the top 10 of one category plus the viewer: keep the top
    # BOARD_SIZE of every category (same order as the frontend sort) plus the
    # viewer instead of every member with dives in the window.
    keep = set()
    for category in ("active", "streak", "progress", "explorer"):
        ranked = sorted(members, key=lambda member, wanted=category: (-_board_value(member, wanted), -member["attempts"], member["user_id"]))
        keep.update(member["user_id"] for member in ranked[:BOARD_SIZE])
    if viewer_id is not None:
        keep.add(viewer_id)
    members = [member for member in members if member["user_id"] in keep]
    return {"period": period, "start": start.isoformat(), "end": now.isoformat(), "members": members}
