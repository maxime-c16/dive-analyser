"""Psychology and emotional state API endpoints for mental health and fear analysis."""

import logging
from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.database import get_db
from app.services.write_guard import require_owner_for_mutation
from app.services.workspace_access import require_workspace_user
from app.models.dive import Dive
from app.models.emotional_state import EmotionalState, RecoveryPlan
from app.models.journey import Journey
from app.services.fear_analyzer import FearAnalyzer
from app.services.journey_service import JourneyService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/psychology", tags=["psychology"], dependencies=[Depends(require_owner_for_mutation), Depends(require_workspace_user)])


# Schema models for request/response
class EmotionalStateCreate:
    """Request model for logging emotional state."""

    def __init__(self, dive_id: int, pre_dive_emotion: Optional[str] = None,
                 post_dive_emotion: Optional[str] = None, confidence_rating: Optional[int] = None,
                 emotional_notes: Optional[str] = None):
        self.dive_id = dive_id
        self.pre_dive_emotion = pre_dive_emotion
        self.post_dive_emotion = post_dive_emotion
        self.confidence_rating = confidence_rating
        self.emotional_notes = emotional_notes


class RecoveryPlanCreate:
    """Request model for creating recovery plan."""

    def __init__(self, journey_id: int, blocked_dives: List[str]):
        self.journey_id = journey_id
        self.blocked_dives = blocked_dives


# Endpoints


@router.post("/dive")
def log_emotional_state(
    dive_id: int = Query(..., description="Dive ID to associate emotions with"),
    pre_emotion: Optional[str] = Query(None, description="Pre-dive emotion: confident, nervous, excited, fearful, anxious"),
    post_emotion: Optional[str] = Query(None, description="Post-dive emotion: satisfied, frustrated, proud, disappointed, relieved"),
    confidence: Optional[int] = Query(None, ge=1, le=5, description="Confidence rating 1-5"),
    notes: Optional[str] = Query(None, description="Optional notes about emotional state"),
    db: Session = Depends(get_db),
):
    """Log emotional state for a dive.

    Captures pre- and post-dive emotions to track psychological patterns and
    identify fear-based blocks to progression.

    Valid emotions:
    - Pre-dive: confident, nervous, excited, fearful, anxious
    - Post-dive: satisfied, frustrated, proud, disappointed, relieved
    - Confidence: 1-5 scale where 5 is most confident
    """
    # Verify dive exists
    dive = db.execute(select(Dive).where(Dive.id == dive_id)).scalar_one_or_none()
    if not dive:
        raise HTTPException(status_code=404, detail=f"Dive {dive_id} not found")

    # Check if emotional state already exists for this dive
    existing = db.execute(
        select(EmotionalState).where(EmotionalState.dive_id == dive_id)
    ).scalar_one_or_none()

    if existing:
        # Update existing
        if pre_emotion:
            existing.pre_dive_emotion = pre_emotion
        if post_emotion:
            existing.post_dive_emotion = post_emotion
        if confidence is not None:
            existing.confidence_rating = confidence
        if notes:
            existing.emotional_notes = notes
        existing.updated_at = datetime.utcnow()
        db.add(existing)
    else:
        # Create new
        emotional_state = EmotionalState(
            dive_id=dive_id,
            pre_dive_emotion=pre_emotion,
            post_dive_emotion=post_emotion,
            confidence_rating=confidence,
            emotional_notes=notes
        )
        db.add(emotional_state)

    db.commit()

    return {
        "success": True,
        "dive_id": dive_id,
        "pre_emotion": pre_emotion,
        "post_emotion": post_emotion,
        "confidence_rating": confidence,
        "message": "Emotional state logged successfully"
    }


@router.get("/fear-analysis")
def get_fear_analysis(
    db: Session = Depends(get_db)
):
    """Analyze fear patterns and psychological plateaus.

    Returns:
    - avoided_dives: Dives being avoided despite capability
    - dd_gap: Degree of difficulty gap indicating plateau
    - confidence_blocks: Emotional patterns blocking progress
    - risk_level: Overall risk assessment (low, medium, high)
    """
    fear_analyzer = FearAnalyzer(db)
    result = fear_analyzer.detect_fear_plateau()

    return {
        "success": True,
        "analysis": result,
        "recommendation": (
            "High-risk plateau detected - consider mental block recovery plan"
            if result["risk_level"] == "high"
            else "Monitor progression - focus on building confidence"
            if result["risk_level"] == "medium"
            else "Good progression - continue current approach"
        )
    }


@router.get("/fear-coefficient/{dive_code}")
def get_fear_coefficient(
    dive_code: str,
    db: Session = Depends(get_db)
):
    """Calculate fear coefficient for a specific dive.

    Fear coefficient interpretation:
    - >1.5: Irrational fear (avoiding despite capability)
    - 0.5-1.5: Balanced progression
    - <0.5: Appropriate caution

    Returns:
    - fear_coefficient: Score 0-3
    - interpretation: Category of fear response
    - success_rate: Historical success percentage
    - recommendation: Suggested next step
    """
    fear_analyzer = FearAnalyzer(db)
    result = fear_analyzer.calculate_fear_coefficient(dive_code)

    return {
        "success": True,
        "dive_code": dive_code,
        "analysis": result
    }


@router.get("/emotional-triggers")
def get_emotional_triggers(
    db: Session = Depends(get_db)
):
    """Identify emotional triggers and confidence drivers.

    Shows:
    - High-fear dives: Which dives trigger fear/anxiety emotions
    - Confidence drivers: Which dives build confidence and success
    - Emotional patterns: Common patterns across all dives
    - Recommendations: How to address emotional blocks
    """
    fear_analyzer = FearAnalyzer(db)
    result = fear_analyzer.get_emotional_triggers()

    return {
        "success": True,
        "analysis": result
    }


@router.get("/confidence-trends")
def get_confidence_trends(
    days: int = Query(30, ge=7, le=365, description="Number of days to analyze"),
    db: Session = Depends(get_db)
):
    """Track confidence trends over time.

    Shows:
    - Daily trend: Day-by-day confidence changes
    - Weekly summary: Week-by-week progress
    - Slope: Trend direction (improving, stable, declining)
    - Recommendations: Based on trend analysis
    """
    fear_analyzer = FearAnalyzer(db)
    result = fear_analyzer.track_confidence_trends(days=days)

    return {
        "success": True,
        "days_analyzed": days,
        "analysis": result
    }


@router.post("/recovery-plan")
def create_recovery_plan(
    journey_id: int = Query(..., description="Journey ID"),
    blocked_dives: List[str] = Query(..., description="Dive codes to target (e.g., 101B,201C)"),
    db: Session = Depends(get_db)
):
    """Generate a 3-phase mental block recovery plan.

    Creates a personalized recovery plan with:
    - Phase 1 (2 weeks): Confidence rebuilding at lower DD
    - Phase 2 (2 weeks): Psychological preparation (visualization, video review)
    - Phase 3 (2-3 weeks): Controlled exposure at target height

    Each phase includes specific activities and success criteria.

    Returns:
    - plan_id: ID of created recovery plan
    - phase_details: Detailed plan for each phase
    - daily_actions: Suggested daily activities
    - progress_tracking: How to measure success
    """
    # Get journey
    journey = db.execute(
        select(Journey).where(Journey.id == journey_id)
    ).scalar_one_or_none()

    if not journey:
        raise HTTPException(status_code=404, detail=f"Journey {journey_id} not found")

    # Use journey service to create plan
    service = JourneyService()
    result = service.generate_mental_block_recovery_plan(db, journey_id, blocked_dives)

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to create recovery plan"))

    return {
        "success": True,
        "plan": result
    }


@router.get("/mental-blocks/{journey_id}")
def get_mental_blocks(
    journey_id: int,
    db: Session = Depends(get_db)
):
    """Identify and analyze mental blocks for a journey.

    Returns:
    - plateau_analysis: Fear plateau detection
    - emotional_triggers: Emotions correlated with difficulty
    - confidence_trends: 30-day confidence trajectory
    - active_recovery_plans: Current recovery plans
    """
    # Get journey
    journey = db.execute(
        select(Journey).where(Journey.id == journey_id)
    ).scalar_one_or_none()

    if not journey:
        raise HTTPException(status_code=404, detail=f"Journey {journey_id} not found")

    # Use journey service
    service = JourneyService()
    result = service.get_mental_blocks(db, journey_id)

    if isinstance(result, dict) and result.get("success") is False:
        raise HTTPException(status_code=400, detail=result.get("error"))

    return {
        "success": True,
        "journey_id": journey_id,
        "analysis": result
    }


@router.put("/recovery-plan/{plan_id}")
def update_recovery_plan_progress(
    plan_id: int,
    current_phase: int = Query(..., ge=0, le=3, description="Current phase (1, 2, 3, or 0 for completed)"),
    completion_percentage: Optional[int] = Query(None, ge=0, le=100, description="Completion percentage"),
    db: Session = Depends(get_db)
):
    """Update recovery plan phase progress.

    Track progression through the 3-phase recovery plan.
    - Phases 1-3: Active recovery
    - Phase 0: Recovery completed

    Returns:
    - plan_id: Updated plan ID
    - current_phase: Current phase
    - completion_percentage: Overall progress
    - status: Plan status
    """
    # Verify plan exists
    plan = db.execute(
        select(RecoveryPlan).where(RecoveryPlan.id == plan_id)
    ).scalar_one_or_none()

    if not plan:
        raise HTTPException(status_code=404, detail=f"Recovery plan {plan_id} not found")

    # Use journey service
    service = JourneyService()
    result = service.update_recovery_plan_phase(db, plan_id, current_phase, completion_percentage)

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))

    return {
        "success": True,
        "plan": result
    }


@router.get("/recovery-plans/{journey_id}")
def get_recovery_plans(
    journey_id: int,
    status: Optional[str] = Query(None, description="Filter by status: active, in_progress, completed, abandoned"),
    db: Session = Depends(get_db)
):
    """Get all recovery plans for a journey.

    Returns:
    - active_plans: Currently active recovery plans
    - completed_plans: Finished recovery plans
    - total_plans: Count of all plans
    """
    # Get journey
    journey = db.execute(
        select(Journey).where(Journey.id == journey_id)
    ).scalar_one_or_none()

    if not journey:
        raise HTTPException(status_code=404, detail=f"Journey {journey_id} not found")

    # Get recovery plans
    query = select(RecoveryPlan).where(RecoveryPlan.journey_id == journey_id)

    if status:
        query = query.where(RecoveryPlan.status == status)

    plans = db.execute(query).scalars().all()

    return {
        "success": True,
        "journey_id": journey_id,
        "total_plans": len(plans),
        "plans": [
            {
                "plan_id": p.id,
                "blocked_dives": p.blocked_dive_codes.split(","),
                "status": p.status,
                "current_phase": p.current_phase,
                "completion_percentage": p.completion_percentage,
                "created_at": p.created_at.isoformat(),
                "estimated_completion": (
                    (p.created_at + (
                        timedelta(days=p.phase1_duration + p.phase2_duration + p.phase3_duration)
                    )).isoformat()
                    if p.status != "completed" else p.completed_at.isoformat()
                ),
                "phase_progress": {
                    "phase_1": {
                        "status": "completed" if p.phase1_completed_at else ("in_progress" if p.phase1_started_at else "pending"),
                        "started": p.phase1_started_at.isoformat() if p.phase1_started_at else None,
                        "completed": p.phase1_completed_at.isoformat() if p.phase1_completed_at else None
                    },
                    "phase_2": {
                        "status": "completed" if p.phase2_completed_at else ("in_progress" if p.phase2_started_at else "pending"),
                        "started": p.phase2_started_at.isoformat() if p.phase2_started_at else None,
                        "completed": p.phase2_completed_at.isoformat() if p.phase2_completed_at else None
                    },
                    "phase_3": {
                        "status": "completed" if p.phase3_completed_at else ("in_progress" if p.phase3_started_at else "pending"),
                        "started": p.phase3_started_at.isoformat() if p.phase3_started_at else None,
                        "completed": p.phase3_completed_at.isoformat() if p.phase3_completed_at else None
                    }
                }
            }
            for p in plans
        ]
    }


# Import timedelta for recovery plan duration calculation
from datetime import timedelta
