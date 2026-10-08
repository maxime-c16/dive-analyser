"""Account-aggregate diver score (0-100 composite).

Combines three signals for the signed-in account's owned divers:

- performance (60): pooled mean of received votes (automatic matchmaking
  community votes + manual jury votes on owned dives), 0-10 scaled to 0-60,
  damped by vote count so a single vote cannot max the score.
- judging (25): distinct dives the account evaluated (automatic + manual
  votes given), capped at 10 dives.
- community (15): member interactions sent + received (dive likes, dive
  comments, comment likes), capped at 50.

Aggregate only: no rater identities leak through this endpoint. Provisional
while received votes are thin (<3).
"""
from sqlalchemy import func, select

from app.models.dive import Dive
from app.models.dive_social import DiveComment, DiveCommentLike, DiveLike
from app.models.evaluation import EvaluationRating, EvaluationRequest
from app.models.matchmaking import AutomaticRating
from app.services.dive_access import owned_diver_ids
from app.services.matchmaking import community_vote_clause

PERFORMANCE_WEIGHT = 60.0
JUDGING_WEIGHT = 25.0
COMMUNITY_WEIGHT = 15.0
RECEIVED_FOR_CONFIDENCE = 5
RECEIVED_FOR_STABLE = 3
JUDGING_CAP = 10
COMMUNITY_CAP = 50


def compute(db, user) -> dict:
    owned = tuple(owned_diver_ids(db, user.id))

    received_count = 0
    received_sum_half = 0
    received_mean = None
    if owned:
        auto_count, auto_sum = db.query(
            func.count(AutomaticRating.id), func.sum(AutomaticRating.score_half_steps),
        ).join(Dive, Dive.id == AutomaticRating.dive_id).filter(
            Dive.diver_id.in_(owned),
        ).filter(community_vote_clause()).one()
        auto_count = int(auto_count or 0)
        manual_count, manual_sum = db.query(
            func.count(EvaluationRating.id), func.sum(EvaluationRating.score_half_steps),
        ).join(EvaluationRequest, EvaluationRequest.id == EvaluationRating.request_id).join(
            Dive, Dive.id == EvaluationRequest.dive_id,
        ).filter(Dive.diver_id.in_(owned)).one()
        manual_count = int(manual_count or 0)
        received_count = auto_count + manual_count
        received_sum_half = int((auto_sum or 0) + (manual_sum or 0))
        if received_count:
            received_mean = round(received_sum_half / 2.0 / received_count, 1)

    confidence = min(1.0, received_count / RECEIVED_FOR_CONFIDENCE) if received_count else 0.0
    performance_points = round((received_mean or 0.0) * 6.0 * confidence, 1)

    # Distinct judged dives across both rating sources, counted in SQL as one
    # bounded query — UNION (not UNION ALL) dedupes a dive judged both ways.
    auto_judged = db.query(AutomaticRating.dive_id).filter(
        AutomaticRating.evaluator_user_id == user.id,
    )
    manual_judged = db.query(EvaluationRequest.dive_id).join(
        EvaluationRating, EvaluationRating.request_id == EvaluationRequest.id,
    ).filter(EvaluationRating.evaluator_user_id == user.id)
    judged_dives = auto_judged.union(manual_judged).count()
    judging_points = round(min(judged_dives, JUDGING_CAP) / JUDGING_CAP * JUDGING_WEIGHT, 1)

    sent = (
        db.query(func.count(DiveLike.dive_id)).filter(DiveLike.user_id == user.id).scalar() or 0
    ) + (
        db.query(func.count(DiveComment.id)).filter(DiveComment.user_id == user.id).scalar() or 0
    ) + (
        db.query(func.count(DiveCommentLike.comment_id)).filter(DiveCommentLike.user_id == user.id).scalar() or 0
    )
    received_interactions = 0
    if owned:
        my_dives = select(Dive.id).where(Dive.diver_id.in_(owned))
        my_comments = select(DiveComment.id).where(DiveComment.user_id == user.id)
        received_interactions = (
            db.query(func.count(DiveLike.dive_id)).filter(
                DiveLike.dive_id.in_(my_dives), DiveLike.user_id != user.id,
            ).scalar() or 0
        ) + (
            db.query(func.count(DiveComment.id)).filter(
                DiveComment.dive_id.in_(my_dives), DiveComment.user_id != user.id,
            ).scalar() or 0
        ) + (
            db.query(func.count(DiveCommentLike.comment_id)).filter(
                DiveCommentLike.comment_id.in_(my_comments), DiveCommentLike.user_id != user.id,
            ).scalar() or 0
        )
    interactions = int(sent + received_interactions)
    community_points = round(min(interactions, COMMUNITY_CAP) / COMMUNITY_CAP * COMMUNITY_WEIGHT, 1)

    total = int(round(performance_points + judging_points + community_points))
    return {
        "score": max(0, min(100, total)),
        "provisional": received_count < RECEIVED_FOR_STABLE,
        "performance": {
            "mean_score": received_mean,
            "rating_count": received_count,
            "points": performance_points,
            "weight": PERFORMANCE_WEIGHT,
        },
        "judging": {
            "evaluated_dives": judged_dives,
            "points": judging_points,
            "weight": JUDGING_WEIGHT,
        },
        "community": {
            "interactions": interactions,
            "points": community_points,
            "weight": COMMUNITY_WEIGHT,
        },
    }
