"""Evaluation from the clip player: one vote per member and dive.

A member who can watch a dive (request-wide visibility filter) can rate it
when one of the two existing circuits accepts the vote:

* ``request``: the owner opened an evaluation request (active) — it wins,
  because the owner asked for it and may have left a prompt for the jury;
* ``automatic``: otherwise, any eligible public dive with ready media
  (``matchmaking.eligible``), without requiring the daily selection.

A vote already stored in either circuit is shown instead of a new keypad, so
the player never counts the same member twice for one dive. Owners never vote
on their own dives; they see the results of the circuit in use. Peer votes
stay hidden until the member's own vote is stored (same rule as the jury).
"""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.dive import Dive
from app.models.evaluation import EvaluationRating
from app.models.matchmaking import AutomaticRating, ReviewExclusion
from app.services import evaluation_access, evaluation_ratings, matchmaking
from app.services.dive_access import owned_diver_ids


def visible_dive(db: Session, dive_id: int) -> Dive:
    """The dive as the member's Library sees it (query, never the identity map)."""
    dive = db.query(Dive).filter(Dive.id == dive_id).first()
    if dive is None:
        raise HTTPException(404, "Not found")
    return dive


def _automatic_open(db: Session, user, dive: Dive) -> bool:
    return (
        matchmaking.eligible(db, user)
        .filter(Dive.id == dive.id, matchmaking._ready_clause())
        .first()
        is not None
    )


def _automatic_excluded(db: Session, dive: Dive) -> bool:
    row = db.query(ReviewExclusion).filter(ReviewExclusion.dive_id == dive.id).first()
    return bool(row and row.excluded)


def context(db: Session, user, dive: Dive) -> dict:
    is_owner = dive.diver_id is not None and dive.diver_id in set(owned_diver_ids(db, user.id))
    request_row = evaluation_access.request_for_dive(db, dive.id)
    request_vote = (
        db.query(EvaluationRating)
        .filter(EvaluationRating.request_id == request_row.id, EvaluationRating.evaluator_user_id == user.id)
        .first()
        if request_row is not None
        else None
    )
    automatic_vote = (
        db.query(AutomaticRating)
        .filter(AutomaticRating.dive_id == dive.id, AutomaticRating.evaluator_user_id == user.id)
        .first()
    )
    request_active = bool(request_row is not None and request_row.active)
    out = {"dive_id": dive.id, "state": "closed", "circuit": None, "prompt": None, "results": None, "my_rating": None}

    if request_vote is not None:
        results = evaluation_ratings._results_payload(db, request_row, user.id)
        return {**out, "state": "rated", "circuit": "request", "prompt": request_row.prompt,
                "results": results, "my_rating": results["my_rating"]}
    if automatic_vote is not None:
        results = matchmaking.results(db, user, dive.id)
        return {**out, "state": "rated", "circuit": "automatic", "results": results, "my_rating": results["my_rating"]}
    if is_owner:
        if request_active:
            return {**out, "state": "owner", "circuit": "request", "prompt": request_row.prompt,
                    "results": evaluation_ratings._results_payload(db, request_row, user.id)}
        if dive.visibility == "public":
            return {**out, "state": "owner", "circuit": "automatic",
                    "results": matchmaking.results(db, user, dive.id),
                    "automatic_excluded": _automatic_excluded(db, dive)}
        return {**out, "state": "owner"}
    if request_active and dive.video_uuid:
        return {**out, "state": "open", "circuit": "request", "prompt": request_row.prompt}
    if _automatic_open(db, user, dive):
        return {**out, "state": "open", "circuit": "automatic"}
    return out


def rate(db: Session, user, dive: Dive, score_half_steps: int, comment: str | None) -> dict:
    current = context(db, user, dive)
    if current["state"] == "owner":
        raise evaluation_ratings.SubmissionBlocked("SELF_EVALUATION", "You cannot rate your own dive", 403)
    if current["circuit"] == "request":
        request_row = evaluation_access.request_for_dive(db, dive.id)
        out = evaluation_ratings.submit_rating(db, user, request_row.id, score_half_steps, comment)
    elif current["circuit"] == "automatic":
        out = matchmaking.rate(db, user, dive.id, score_half_steps, comment, dive.video_uuid, require_assignment=False)
    else:
        raise evaluation_ratings.SubmissionBlocked("EVALUATION_CLOSED", "This dive is not open to ratings", 409)
    return {**out, "circuit": current["circuit"]}
