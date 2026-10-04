"""
Journey API - Narrative-based progress tracking.

This isn't analytics. This is your story.
"""

from datetime import datetime, timedelta
from typing import List, Optional
from dateutil.relativedelta import relativedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.dive import Dive
from app.services.milestones import (
    MilestoneDetector,
    JourneyNarrator,
    DiveAttempt,
    MilestoneType,
)
from app.services.performance_scoring import athlete_score_10
from app.services.dd_overview_service import DDOverviewService
from app.services.dive_eligibility import is_performance_attempt
from app.services.workspace_access import require_workspace_read

router = APIRouter(dependencies=[Depends(require_workspace_read)])


def get_dd_progression(db: Session) -> dict:
    """Compatibility payload sourced from the same live DD formula as the UI."""
    overview = DDOverviewService(db).overview(scope="self")
    months = []
    highest_dd = 0.0
    for item in overview["timeline"]:
        month_max = item["max_dd"]
        if month_max is not None and month_max > highest_dd:
            highest_dd = month_max
            breakthroughs = [f"New personal best: {month_max:.1f}"]
        else:
            breakthroughs = []
        months.append({
            "month": datetime.strptime(item["month"], "%Y-%m").strftime("%b %Y"),
            "max_dd": month_max or 0,
            "attempts": item["attempt_count"],
            "breakthroughs": breakthroughs,
        })
    current_max = months[-1]["max_dd"] if months else 0
    return {"months": months, "current_max": current_max, "highest_achieved": highest_dd}


def get_attempts(db: Session) -> List[DiveAttempt]:
    """Convert database records to DiveAttempt objects for personal dives only."""
    dives = db.query(Dive).filter(
        Dive.person_name.is_(None),  # Personal dives only
        Dive.dive_code.isnot(None),
        Dive.performance.isnot(None),
        Dive.is_lineup.is_(False),
    ).order_by(Dive.dive_datetime.asc()).all()

    return [
        DiveAttempt(
            uuid=d.video_uuid or str(d.id),
            dive_code=d.dive_code,
            height=d.height or "3m",
            performance=d.performance,
            date=d.dive_datetime or datetime.now(),
            is_sync=d.is_sync or False,
            is_smack=d.is_smack or False,
            # Two-phase scoring (new format)
            phase1_performance=d.phase1_performance,
            phase2_performance=d.phase2_performance,
        )
        for d in dives
        if is_performance_attempt(d)
    ]


@router.get("/milestones")
def get_milestones(
    db: Session = Depends(get_db),
    dive_code: Optional[str] = Query(None, description="Filter by dive code"),
    min_significance: int = Query(1, description="Minimum significance (1-5)"),
    limit: int = Query(50, description="Maximum milestones to return"),
):
    """
    Get all detected milestones in your diving journey.

    Milestones are meaningful moments:
    - First attempts and successes
    - Breakthroughs after failures
    - Consistency achievements
    - Comebacks from avoidance
    """
    attempts = get_attempts(db)

    if not attempts:
        return {
            "message": "No dive data yet. Your journey awaits.",
            "milestones": [],
        }

    detector = MilestoneDetector(attempts)
    milestones = detector.detect_all()

    # Filter
    if dive_code:
        milestones = [m for m in milestones if m.dive_code == dive_code]

    milestones = [m for m in milestones if m.significance >= min_significance]

    # Most recent first
    milestones = sorted(milestones, key=lambda m: m.date, reverse=True)[:limit]

    return {
        "total": len(milestones),
        "milestones": [m.to_dict() for m in milestones],
    }


@router.get("")
def get_journey_summary(db: Session = Depends(get_db)):
    """
    Get a narrative summary of your complete diving journey.

    This is the big picture: your growth story.
    """
    attempts = get_attempts(db)

    if not attempts:
        return {
            "message": "Your journey hasn't started yet.",
            "summary": {
                "narrative": "Every expert was once a beginner. "
                            "The first dive is the hardest — not physically, but mentally. "
                            "Start there."
            }
        }

    detector = MilestoneDetector(attempts)
    milestones = detector.detect_all()
    narrator = JourneyNarrator(milestones)

    # Basic stats
    total_dives = len(attempts)
    unique_dives = len(set((a.dive_code, a.height) for a in attempts))
    date_range = (attempts[-1].date - attempts[0].date).days

    # Performance trajectory
    first_month = [a for a in attempts if a.date < attempts[0].date + timedelta(days=30)]
    last_month = [a for a in attempts if a.date > attempts[-1].date - timedelta(days=30)]

    first_avg = sum(a.performance_value for a in first_month) / len(first_month) if first_month else 0
    last_avg = sum(a.performance_value for a in last_month) / len(last_month) if last_month else 0

    # Get DD progression
    dd_progression = get_dd_progression(db)

    # Calculate psychological indicators
    psychological = {
        "mental_blocks_detected": 0,  # Placeholder for plateau detection
        "fear_coefficient": 1.0,      # Placeholder for fear vs difficulty
        "confidence_trend": "improving" if last_avg > first_avg else "stable",
        "emotional_state_data": [],   # Placeholder for emotional tracking
    }

    return {
        "overview": {
            "total_dives": total_dives,
            "unique_dive_combinations": unique_dives,
            "days_of_training": date_range,
            "first_dive_date": attempts[0].date.isoformat(),
            "latest_dive_date": attempts[-1].date.isoformat(),
        },
        "growth": {
            "first_month_average": round(first_avg, 2),
            "last_month_average": round(last_avg, 2),
            "improvement": round(last_avg - first_avg, 2),
            "trajectory": "improving" if last_avg > first_avg else "plateauing" if last_avg == first_avg else "struggling",
        },
        "journey": narrator.generate_journey_summary(),
        "dd_progression": dd_progression,
        "psychological": psychological,
    }


@router.get("/dive/{dive_code}/{height}")
def get_dive_story(
    dive_code: str,
    height: str,
    db: Session = Depends(get_db),
):
    """
    Get the complete story of a specific dive.

    Every dive has a narrative arc: first attempt, struggles, breakthroughs, mastery.
    """
    attempts = get_attempts(db)

    # Filter to this specific dive
    dive_attempts = [a for a in attempts
                    if a.dive_code == dive_code and a.height == height]

    if not dive_attempts:
        return {
            "dive_code": dive_code,
            "height": height,
            "message": "You haven't attempted this dive yet.",
            "narrative": f"{dive_code} from {height} awaits. "
                        f"When you're ready, the story begins.",
        }

    # Get milestones for this dive
    detector = MilestoneDetector(attempts)
    all_milestones = detector.detect_all()
    narrator = JourneyNarrator(all_milestones)

    story = narrator.generate_dive_story(dive_code, height)

    # Add stats
    successes = len([a for a in dive_attempts if a.is_success])
    perfects = len([a for a in dive_attempts if a.is_perfect])
    smacks = len([a for a in dive_attempts if a.is_smack])

    story["stats"] = {
        "total_attempts": len(dive_attempts),
        "successes": successes,
        "success_rate": round(successes / len(dive_attempts) * 100, 1),
        "perfects": perfects,
        "smacks": smacks,
        "smacks_recovered_from": smacks,  # You're still here
    }

    # Current streak
    streak = 0
    for a in reversed(dive_attempts):
        if a.is_success:
            streak += 1
        else:
            break
    story["current_streak"] = streak

    return story


@router.get("/breakthroughs")
def get_breakthroughs(
    db: Session = Depends(get_db),
    limit: int = Query(10, description="Number of breakthroughs to return"),
):
    """
    Get your most significant breakthrough moments.

    These are the moments that define a diver:
    success after repeated failure.
    """
    attempts = get_attempts(db)

    if not attempts:
        return {"breakthroughs": [], "message": "No breakthroughs yet. Keep showing up."}

    detector = MilestoneDetector(attempts)
    milestones = detector.detect_all()

    # Filter to breakthrough types
    breakthrough_types = {
        MilestoneType.BREAKTHROUGH,
        MilestoneType.REDEMPTION,
        MilestoneType.PLATEAU_BROKEN,
        MilestoneType.AVOIDED_DIVE_ATTEMPTED,
    }

    breakthroughs = [m for m in milestones if m.type in breakthrough_types]
    breakthroughs = sorted(breakthroughs, key=lambda m: m.significance, reverse=True)[:limit]

    return {
        "total_breakthroughs": len(breakthroughs),
        "breakthroughs": [
            {
                **m.to_dict(),
                "why_it_matters": _explain_breakthrough(m),
            }
            for m in breakthroughs
        ],
    }


@router.get("/avoided")
def get_avoided_dives(
    db: Session = Depends(get_db),
    days_threshold: int = Query(30, description="Days since last attempt to consider 'avoided'"),
):
    """
    Surface dives you might be avoiding.

    Sometimes the most growth comes from facing what we've been
    unconsciously avoiding. This endpoint helps you see those patterns.
    """
    attempts = get_attempts(db)

    if not attempts:
        return {"avoided": [], "message": "No dive history yet."}

    # Group by dive+height
    by_dive = {}
    for a in attempts:
        key = (a.dive_code, a.height)
        if key not in by_dive:
            by_dive[key] = []
        by_dive[key].append(a)

    now = datetime.now()
    avoided = []

    for (code, height), dive_attempts in by_dive.items():
        last_attempt = max(dive_attempts, key=lambda a: a.date)
        days_since = (now - last_attempt.date).days

        if days_since >= days_threshold:
            # Calculate historical difficulty
            failures = len([a for a in dive_attempts if not a.is_success])
            failure_rate = failures / len(dive_attempts)

            # More failures = more likely avoiding for a reason
            avoidance_score = days_since * (1 + failure_rate)

            avoided.append({
                "dive_code": code,
                "height": height,
                "days_since_attempt": days_since,
                "total_attempts": len(dive_attempts),
                "failure_rate": round(failure_rate * 100, 1),
                "last_performance": last_attempt.performance,
                "avoidance_score": round(avoidance_score, 1),
                "message": _generate_avoidance_message(code, height, days_since, failure_rate),
            })

    # Sort by avoidance score
    avoided = sorted(avoided, key=lambda x: x["avoidance_score"], reverse=True)

    return {
        "total_avoided": len(avoided),
        "avoided": avoided,
        "encouragement": "Every avoided dive is an opportunity waiting. "
                        "Pick one. Show up. The rest will follow.",
    }


@router.get("/phase-analysis")
def get_phase_analysis(
    db: Session = Depends(get_db),
    dive_code: Optional[str] = Query(None, description="Filter by dive code"),
):
    """
    Analyze your two-phase scoring patterns (Hurdle+Flight vs Opening+Entry).

    Shows:
    - How many dives use the new two-phase format
    - Phase performance distribution
    - Specific strengths and development areas
    - Personalized coaching based on phase scores
    """
    attempts = get_attempts(db)

    if not attempts:
        return {
            "message": "No dive data yet. Start logging dives to see phase analysis.",
            "phase_data": None,
        }

    # Filter by dive code if requested
    if dive_code:
        attempts = [a for a in attempts if a.dive_code == dive_code]

    # Separate two-phase and legacy dives
    two_phase_dives = [a for a in attempts if a.is_two_phase]
    legacy_dives = [a for a in attempts if not a.is_two_phase]

    if not two_phase_dives:
        return {
            "message": "You haven't logged any dives with the new two-phase format yet. "
                      "Start using 'Code P/G Height' format to get detailed phase analysis!",
            "total_dives": len(attempts),
            "legacy_dives": len(legacy_dives),
            "two_phase_dives": 0,
            "phase_data": None,
        }

    # Analyze phase performance
    phase1_scores = {}
    phase2_scores = {}
    phase_combinations = {}

    for dive in two_phase_dives:
        # Count phase1 scores
        p1 = dive.phase1_performance
        phase1_scores[p1] = phase1_scores.get(p1, 0) + 1

        # Count phase2 scores
        p2 = dive.phase2_performance
        phase2_scores[p2] = phase2_scores.get(p2, 0) + 1

        # Count combinations
        combo = f"{p1}/{p2}"
        phase_combinations[combo] = phase_combinations.get(combo, 0) + 1

    # Calculate averages
    phase1_values = [athlete_score_10(a.phase1_performance) for a in two_phase_dives if a.phase1_performance is not None]
    phase2_values = [athlete_score_10(a.phase2_performance) for a in two_phase_dives if a.phase2_performance is not None]

    phase1_avg = sum(phase1_values) / len(phase1_values) if phase1_values else 0
    phase2_avg = sum(phase2_values) / len(phase2_values) if phase2_values else 0

    # Identify patterns and insights
    insights = []

    if phase1_avg > phase2_avg + 0.5:
        insights.append({
            "pattern": "Strong Flight, Weaker Entry",
            "coaching": "Your takeoff mechanics are solid. Focus on entry control, timing, and body awareness during landing.",
        })
    elif phase2_avg > phase1_avg + 0.5:
        insights.append({
            "pattern": "Weaker Flight, Strong Recovery",
            "coaching": "You show remarkable adaptability and recovery. Strengthen takeoff mechanics to make full dives more consistent.",
        })
    else:
        insights.append({
            "pattern": "Balanced Execution",
            "coaching": "Both phases are developing similarly. Continue comprehensive technical work.",
        })

    # Count perfect phases
    phase1_perfects = phase1_scores.get('P', 0)
    phase2_perfects = phase2_scores.get('P', 0)

    if phase1_perfects >= phase2_perfects and phase1_perfects > 0:
        insights.append({
            "pattern": f"Takeoff Excellence",
            "coaching": f"You've mastered the flight phase {phase1_perfects} times. Now refine entry execution.",
        })
    elif phase2_perfects > phase1_perfects and phase2_perfects > 0:
        insights.append({
            "pattern": f"Entry Mastery",
            "coaching": f"Perfect entries {phase2_perfects} times! Your landing control is exceptional.",
        })

    return {
        "message": f"Two-phase analysis for {len(two_phase_dives)} dives",
        "summary": {
            "total_dives": len(attempts),
            "two_phase_dives": len(two_phase_dives),
            "legacy_dives": len(legacy_dives),
            "percentage_new_format": round((len(two_phase_dives) / len(attempts) * 100), 1) if attempts else 0,
        },
        "phase1_analysis": {
            "label": "Hurdle + Flight (Takeoff)",
            "average": round(phase1_avg, 2),
            "distribution": phase1_scores,
            "description": "How well you execute the takeoff and flight phases.",
        },
        "phase2_analysis": {
            "label": "Opening + Entry (Landing)",
            "average": round(phase2_avg, 2),
            "distribution": phase2_scores,
            "description": "How well you execute the opening and water entry phases.",
        },
        "phase_combinations": {
            "label": "Phase Score Combinations",
            "most_common": max(phase_combinations.items(), key=lambda x: x[1])[0] if phase_combinations else None,
            "distribution": phase_combinations,
        },
        "coaching_insights": insights,
        "recommendation": "The two-phase format helps identify exactly where to focus your training. "
                         "Use these insights to target specific technical improvements!",
    }


def _explain_breakthrough(milestone) -> str:
    """Generate explanation of why a breakthrough matters."""
    explanations = {
        MilestoneType.BREAKTHROUGH:
            "Success after repeated failure is the purest form of growth. "
            "This moment proves that persistence works.",
        MilestoneType.REDEMPTION:
            "Going from belly flop to perfection takes mental strength. "
            "You didn't let the failure define you.",
        MilestoneType.PLATEAU_BROKEN:
            "Plateaus feel like stagnation, but they're consolidation. "
            "Breaking through means the foundation is solid.",
        MilestoneType.AVOIDED_DIVE_ATTEMPTED:
            "Facing a dive you've been avoiding is courage. "
            "The result matters less than the decision to try.",
    }
    return explanations.get(milestone.type, "A meaningful moment in your journey.")


def _generate_avoidance_message(code: str, height: str, days: int, failure_rate: float) -> str:
    """Generate encouraging message about an avoided dive."""
    if failure_rate > 0.7:
        return f"{code} has been tough ({int(failure_rate*100)}% difficulty). " \
               f"Maybe start with some lineups to rebuild confidence."
    elif failure_rate > 0.5:
        return f"You've had mixed results with {code}. " \
               f"Consider what made the successes different from the failures."
    else:
        return f"Your success rate on {code} is actually decent. " \
               f"Maybe it's time to return?"
