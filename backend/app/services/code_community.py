"""Where the viewer stands on one dive code among the other divers.

Only other divers' public, non-lineup attempts count, even for admins and
machine-key reads: a private dive never shows up in someone else's numbers.
Rows stream in (diver, date) order and each diver keeps a score histogram
(a handful of distinct values, see code_summaries), the last
SPARK_ATTEMPTS scores and its best attempt, so memory is
O(divers x (distinct scores + SPARK_ATTEMPTS)) whatever the history length.
Quantiles match the frontend's `quantile` (linear interpolation).
"""

from __future__ import annotations

import math
from collections import defaultdict, deque

from app.models.dive import Dive
from app.models.diver import Diver
from app.models.user_auth import AppUser, UserDiverAccess
from app.services.code_summaries import SPARK_ATTEMPTS, SPARK_WINDOW, _rolling_median, _round, _score_value
from app.services.member_avatar import avatar_identity

MIN_GRADED = 3


def _quantile(items: list[tuple[float, int]], p: float) -> float:
    """Linear-interpolated quantile over sorted (score, count) pairs."""
    total = sum(count for _, count in items)
    position = (total - 1) * p
    low, high = math.floor(position), math.ceil(position)

    def at(rank: int) -> float:
        seen = 0
        for score, count in items:
            seen += count
            if rank < seen:
                return score
        return items[-1][0]

    return at(low) + (at(high) - at(low)) * (position - low)


class _Diver:
    __slots__ = ("attempts", "hist", "last", "best", "last_at")

    def __init__(self):
        self.attempts = 0
        self.hist: dict[float, int] = defaultdict(int)
        self.last: deque[float] = deque(maxlen=SPARK_ATTEMPTS)
        self.best: tuple[float, object, int] | None = None
        self.last_at = None


def community_for_code(db, base_query, dive_code: str, own_diver_ids: tuple[int, ...]) -> dict:
    """Per-diver medians, middle halves, recent series and best attempt ids for one code."""
    query = base_query.filter(
        Dive.dive_code == dive_code, Dive.diver_id.is_not(None),
        Dive.visibility == "public", Dive.is_lineup.is_(False),
    )
    if own_diver_ids:
        query = query.filter(Dive.diver_id.not_in(own_diver_ids))
    rows = query.with_entities(
        Dive.diver_id, Dive.id, Dive.dive_datetime,
        Dive.performance, Dive.phase1_performance, Dive.phase2_performance,
    ).order_by(None).order_by(Dive.diver_id, Dive.dive_datetime, Dive.id).yield_per(500)

    divers: dict[int, _Diver] = {}
    for diver_id, dive_id, when, performance, phase1, phase2 in rows:
        acc = divers.get(diver_id) or divers.setdefault(diver_id, _Diver())
        acc.attempts += 1
        acc.last_at = when
        score = _score_value(performance, phase1, phase2)
        if score is None:
            continue
        acc.hist[score] += 1
        acc.last.append(score)
        if acc.best is None or score >= acc.best[0]:
            acc.best = (score, when, dive_id)

    ranked = {diver_id: acc for diver_id, acc in divers.items() if sum(acc.hist.values()) >= MIN_GRADED}
    names = dict(db.query(Diver.id, Diver.display_name).filter(Diver.id.in_(ranked)).all()) if ranked else {}
    accounts: dict[int, dict] = {}
    if ranked:
        for diver_id, user in db.query(UserDiverAccess.diver_id, AppUser).join(
            AppUser, AppUser.id == UserDiverAccess.user_id
        ).filter(
            UserDiverAccess.diver_id.in_(ranked), UserDiverAccess.access_kind == "OWNER", AppUser.is_active.is_(True),
        ).order_by(AppUser.id).all():
            accounts.setdefault(diver_id, {"user_id": user.id, "display_name": user.display_name, **avatar_identity(user)})

    members = []
    for diver_id, acc in ranked.items():
        items = sorted(acc.hist.items())
        members.append({
            "diver_id": diver_id,
            "name": names.get(diver_id) or f"#{diver_id}",
            "account": accounts.get(diver_id),
            "attempt_count": acc.attempts,
            "scored_count": sum(acc.hist.values()),
            "median": _round(_quantile(items, 0.5)),
            "q1": _round(_quantile(items, 0.25)),
            "q3": _round(_quantile(items, 0.75)),
            "last_attempt_at": acc.last_at.isoformat() if acc.last_at else None,
            "series": _rolling_median(list(acc.last), SPARK_WINDOW),
            "best_id": acc.best[2],
        })
    members.sort(key=lambda member: (-member["median"], -member["scored_count"], member["diver_id"]))
    return {"dive_code": dive_code, "members": members, "hidden_count": len(divers) - len(ranked)}
