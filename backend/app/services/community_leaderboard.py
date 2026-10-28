"""Rank the full visible community in SQL, materializing at most four top tens
plus the viewer. Counts, exact score medians and weekly streaks remain full-scope.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import Float, and_, case, cast, func, or_, select

from app.models.dive import Dive
from app.models.user_auth import AppUser, UserDiverAccess
from app.services.code_summaries import _round
from app.services.member_avatar import avatar_identity
from app.services.performance_scoring import ATHLETE_SCORE_10, PHASE1_WEIGHT, PHASE2_WEIGHT

PERIOD_DAYS = {"week": 7, "month": 30}
STREAK_WEEKS = 26
MIN_PROGRESS_ATTEMPTS = 5
BOARD_SIZE = 10


def _round_half_even_sql(value):
    """Round-half-to-even to two decimals, matching Python round(value, 2).

    SQL round() rounds ties away from zero on both SQLite and PostgreSQL,
    while the previous Python _round uses ties-to-even: a delta of 1.125 was
    1.12 and became 1.13, which also feeds progress ranking. Scale by 100,
    break exact ties by the parity of the floor, then scale back. Both signs
    work through floor: floor(-112.5) is -113 (odd), so -112.5 becomes -112,
    i.e. round(-1.125, 2) is -1.12, like Python.

    Stays in binary float end to end: SQLite REAL and PostgreSQL float8 are
    both IEEE doubles evaluated in the same order, so both dialects compute
    bit-identical values. The floors are explicitly typed Float because
    SQLAlchemy's generic floor() defaults to numeric, which would put
    PostgreSQL on exact-decimal semantics and diverge from both SQLite and
    Python on float-dust ties. Residual: deltas whose exact binary value
    sits within half an ulp of a tie with the dust on the odd side round by
    the tie rule instead of the dust side; no grade-achievable delta in the
    test fixtures hits that window.

    The ranked progress value and the displayed delta share this expression,
    so ranking and display can never disagree.
    """
    scaled = value * 100
    floored = cast(func.floor(scaled), Float)
    frac = scaled - floored
    odd_floor = floored - cast(func.floor(floored / 2.0), Float) * 2 != 0
    stepped = case(
        (frac < 0.5, floored),
        (frac > 0.5, floored + 1),
        (odd_floor, floored + 1),
        else_=floored,
    )
    return stepped / 100.0


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _ranking_statement(visible_clause, period, now, viewer_id):
    """Keep cardinality-dependent aggregates and rank selection inside the DB."""
    days = PERIOD_DAYS[period]
    start, previous = now - timedelta(days=days), now - timedelta(days=2 * days)
    monday = datetime.combine(_monday(now.date()), datetime.min.time())
    streak_start = monday - timedelta(weeks=STREAK_WEEKS - 1)
    owner = UserDiverAccess.user_id

    def score(column):
        # Match attempt_score_10: unknown nonempty grades map to zero.
        return case(ATHLETE_SCORE_10, value=func.upper(column), else_=0.0)

    grade = case(
        (and_(Dive.performance.is_not(None), Dive.performance != ""), case(
            (and_(Dive.phase1_performance.is_not(None), Dive.phase1_performance != "",
                  Dive.phase2_performance.is_not(None), Dive.phase2_performance != ""),
             score(Dive.phase1_performance) * PHASE1_WEIGHT + score(Dive.phase2_performance) * PHASE2_WEIGHT),
            else_=score(Dive.performance))),
        else_=None,
    )
    eligible = select(
        owner.label("uid"), Dive.id, Dive.session_id, Dive.dive_code, Dive.dive_datetime,
        grade.label("score"),
    ).select_from(Dive).join(UserDiverAccess, and_(
        UserDiverAccess.diver_id == Dive.diver_id, UserDiverAccess.access_kind == "OWNER",
    )).join(AppUser, and_(AppUser.id == owner, AppUser.is_active.is_(True))).where(
        Dive.is_lineup.is_(False), visible_clause,
        Dive.dive_datetime >= min(previous, streak_start),
    )
    if viewer_id is not None:
        own = select(UserDiverAccess.diver_id).where(
            UserDiverAccess.user_id == viewer_id, UserDiverAccess.access_kind == "OWNER")
        linked = select(UserDiverAccess.user_id).where(
            UserDiverAccess.diver_id.in_(own), UserDiverAccess.access_kind == "OWNER")
        eligible = eligible.where(or_(owner == viewer_id, owner.not_in(linked)))
    dives = eligible.cte("board_dives")
    d = dives.c
    current = select(
        d.uid, func.count().label("attempts"),
        func.count(func.distinct(d.session_id)).label("sessions"),
        func.count(func.distinct(d.dive_code)).label("codes"),
        func.max(d.dive_datetime).label("last"),
    ).where(d.dive_datetime >= start).group_by(d.uid).cte("board_current")

    # Histograms retain exact medians without sorting or fetching full histories
    # in Python. Window sums locate the two middle positions in each histogram.
    recent = case((d.dive_datetime >= start, 1), else_=0).label("recent")
    hist = select(d.uid, recent, d.score, func.count().label("n")).where(
        d.dive_datetime >= previous, d.score.is_not(None),
    ).group_by(d.uid, recent, d.score).cte("board_hist")
    h = hist.c
    cumulative = select(
        h.uid, h.recent, h.score, h.n,
        func.sum(h.n).over(partition_by=(h.uid, h.recent), order_by=h.score,
                           rows=(None, 0)).label("seen"),
        func.sum(h.n).over(partition_by=(h.uid, h.recent)).label("total"),
    ).cte("board_cumulative")
    c = cumulative.c
    lower = func.min(case((c.seen >= func.floor((c.total + 1) / 2), c.score)))
    upper = func.min(case((c.seen >= func.floor((c.total + 2) / 2), c.score)))
    medians = select(
        c.uid, c.recent, ((lower + upper) / 2.0).label("median"),
        func.max(c.total).label("n"),
    ).group_by(c.uid, c.recent).cte("board_medians")
    recent_median = medians.alias("board_recent")
    previous_median = medians.alias("board_previous")

    # Use timestamp boundaries rather than dialect-specific week arithmetic.
    # Distinct weeks, not dive days, feed the gaps-and-islands calculation.
    week = case(*[
        (and_(d.dive_datetime >= monday - timedelta(weeks=i),
              d.dive_datetime < monday - timedelta(weeks=i - 1)), i)
        for i in range(STREAK_WEEKS)
    ]).label("week")
    weeks = select(d.uid, week).where(d.dive_datetime >= streak_start).distinct().cte("board_weeks")
    w = weeks.c
    numbered = select(
        w.uid, w.week,
        func.min(w.week).over(partition_by=w.uid).label("first"),
        func.row_number().over(partition_by=w.uid, order_by=w.week).label("rn"),
    ).where(w.week.is_not(None)).cte("board_numbered_weeks")
    n = numbered.c
    streaks = select(n.uid, func.sum(case((and_(
        n.first <= 1, n.week == n.rn - 1 + n.first,
    ), 1), else_=0)).label("streak")).group_by(n.uid).cte("board_streaks")

    cur, st = current.c, streaks.c
    rm, pm = recent_median.c, previous_median.c
    delta = case((and_(rm.n >= MIN_PROGRESS_ATTEMPTS, pm.n >= MIN_PROGRESS_ATTEMPTS),
                  _round_half_even_sql(rm.median - pm.median)), else_=None)
    metrics = select(
        AppUser.id.label("uid"), func.coalesce(cur.attempts, 0).label("attempts"),
        func.coalesce(cur.sessions, 0).label("sessions"),
        func.coalesce(cur.codes, 0).label("codes"), cur.last,
        rm.median, delta.label("delta"), func.coalesce(st.streak, 0).label("streak"),
    ).outerjoin(current, cur.uid == AppUser.id).outerjoin(streaks, st.uid == AppUser.id).outerjoin(
        recent_median, and_(rm.uid == AppUser.id, rm.recent == 1),
    ).outerjoin(previous_median, and_(pm.uid == AppUser.id, pm.recent == 0)).where(
        AppUser.is_active.is_(True),
        or_(cur.uid.is_not(None), st.streak > 0, AppUser.id == viewer_id if viewer_id is not None else False),
    ).cte("board_metrics")
    m = metrics.c
    ranked = select(*m, *[
        func.row_number().over(order_by=(value.desc(), m.attempts.desc(), m.uid)).label(f"rank_{i}")
        for i, value in enumerate((m.attempts, m.streak, func.coalesce(m.delta, 0), m.codes))
    ]).cte("board_ranked")
    r = ranked.c
    return select(AppUser, r).join(ranked, r.uid == AppUser.id).where(or_(
        *(r[f"rank_{i}"] <= BOARD_SIZE for i in range(4)),
        r.uid == viewer_id if viewer_id is not None else False,
    )).order_by(r.attempts.desc(), r.uid).limit(4 * BOARD_SIZE + 1)


def leaderboard(db, visible_clause, period: str, now: datetime, viewer_id: int | None = None) -> dict:
    rows = db.execute(_ranking_statement(visible_clause, period, now, viewer_id)).all()
    members = []
    for row in rows:
        user, values = row[0], row._mapping
        members.append({
            "user_id": user.id, "display_name": user.display_name, "handle": user.handle, **avatar_identity(user),
            "attempts": values["attempts"], "sessions": values["sessions"], "codes": values["codes"],
            "median": _round(values["median"]), "delta": _round(float(values["delta"])) if values["delta"] is not None else None,
            "streak_weeks": values["streak"],
            "last_attempt_at": values["last"].isoformat() if values["last"] else None,
        })
    return {"period": period, "start": (now - timedelta(days=PERIOD_DAYS[period])).isoformat(),
            "end": now.isoformat(), "members": members}
