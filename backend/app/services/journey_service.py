"""Journey service for automatic milestone detection after video sync."""

import logging
from typing import List, Optional, Dict
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.models.dive import Dive
from app.models.journey import Journey, JourneyMilestone
from app.models.emotional_state import RecoveryPlan, EmotionalState
from app.services.milestones import MilestoneDetector, DiveAttempt
from app.services.audit_log import get_audit_logger
from app.services.fear_analyzer import FearAnalyzer

logger = logging.getLogger(__name__)
audit_logger = get_audit_logger()


class JourneyService:
    """Service for Journey updates triggered by video sync."""

    async def sync_after_video_upload(self, db: Session, dive_ids: List[int] = None) -> dict:
        """Process Journey updates after video sync.

        Called after successful sync to update Journey with new dives and detect milestones.

        Args:
            db: Database session
            dive_ids: List of newly synced dive IDs. If None, detects all dives since last sync.

        Returns:
            Dictionary with processing results:
            {
                'processed_journeys': int,
                'milestones_detected': int,
                'success': bool,
                'error': Optional[str]
            }
        """
        try:
            # Get Journey records to update
            journeys = db.execute(select(Journey)).scalars().all()

            if not journeys:
                logger.debug("No journeys found to update")
                return {
                    'processed_journeys': 0,
                    'milestones_detected': 0,
                    'success': True,
                    'error': None
                }

            total_journeys = 0
            total_milestones = 0

            # Process each Journey
            for journey in journeys:
                try:
                    milestones_count = await self._update_journey(db, journey, dive_ids)
                    total_journeys += 1
                    total_milestones += milestones_count
                except Exception as e:
                    logger.error(f"Error updating Journey {journey.id}: {e}")
                    # Continue processing other journeys

            logger.info(
                f"Journey processing complete: {total_journeys} journeys, "
                f"{total_milestones} milestones detected"
            )

            return {
                'processed_journeys': total_journeys,
                'milestones_detected': total_milestones,
                'success': True,
                'error': None
            }

        except Exception as e:
            logger.error(f"Error in sync_after_video_upload: {e}")
            return {
                'processed_journeys': 0,
                'milestones_detected': 0,
                'success': False,
                'error': str(e)
            }

    async def _update_journey(self, db: Session, journey: Journey, dive_ids: List[int] = None) -> int:
        """Update a single Journey with new dives.

        Args:
            db: Database session
            journey: Journey record to update
            dive_ids: Specific dive IDs to process. If None, process all.

        Returns:
            Count of milestones detected
        """
        # Load all dives for this journey (or specific ones if provided)
        if dive_ids:
            dives = db.execute(
                select(Dive).where(Dive.id.in_(dive_ids))
            ).scalars().all()
        else:
            # Get all dives in the database (Journey spans all dives)
            dives = db.execute(select(Dive)).scalars().all()

        if not dives:
            return 0

        # Convert Dive records to DiveAttempt objects for milestone detection
        dive_attempts = [self._dive_to_attempt(dive) for dive in dives]

        # Detect milestones
        detector = MilestoneDetector(dive_attempts)
        milestones = detector.detect_all()

        # Store milestones in database
        new_milestones_count = 0
        for milestone in milestones:
            # Check if milestone already exists
            existing = db.execute(
                select(JourneyMilestone).where(
                    (JourneyMilestone.journey_id == journey.id) &
                    (JourneyMilestone.type == milestone.type.value) &
                    (JourneyMilestone.dive_code == milestone.dive_code)
                )
            ).scalar_one_or_none()

            if not existing:
                # Create new milestone record
                journey_milestone = JourneyMilestone(
                    journey_id=journey.id,
                    type=milestone.type.value,
                    dive_code=milestone.dive_code,
                    height=milestone.height,
                    detected_date=datetime.utcnow(),
                    occurrence_date=milestone.date,
                    title=milestone.title,
                    narrative=milestone.narrative,
                    attempts_before=milestone.attempts_before,
                    failures_before=milestone.failures_before,
                    days_since_last=milestone.days_since_last,
                    streak_length=milestone.streak_length,
                    emoji=milestone.emoji,
                    significance=milestone.significance,
                    dive_uuid=milestone.dive_uuid,
                    # Store phase information
                    phase1_performance=milestone.phase1_performance,
                    phase2_performance=milestone.phase2_performance,
                    phase_insight=milestone.phase_insight,
                )
                db.add(journey_milestone)
                new_milestones_count += 1

        # Commit all new milestones
        if new_milestones_count > 0:
            db.commit()
            logger.info(
                f"Detected {new_milestones_count} milestones for Journey {journey.id}"
            )
            _notify_milestone_owners(db, dive_ids, new_milestones_count)

        return new_milestones_count

    async def batch_detect_milestones(self, db: Session, dive_ids: List[int]) -> dict:
        """Detect milestones for a batch of newly synced dives.

        Optimized for batch processing with incremental detection.

        Args:
            db: Database session
            dive_ids: List of newly synced dive IDs

        Returns:
            Dictionary with milestone detection results:
            {
                'detected': int,
                'new_milestones': int,
                'success': bool,
                'error': Optional[str]
            }
        """
        try:
            # Load newly synced dives
            dives = db.execute(
                select(Dive).where(Dive.id.in_(dive_ids))
            ).scalars().all()

            if not dives:
                return {
                    'detected': 0,
                    'new_milestones': 0,
                    'success': True,
                    'error': None
                }

            # Load all dives for context (needed for milestone detection)
            all_dives = db.execute(select(Dive)).scalars().all()

            # Convert to DiveAttempt objects
            dive_attempts = [self._dive_to_attempt(dive) for dive in all_dives]

            # Detect milestones
            detector = MilestoneDetector(dive_attempts)
            milestones = detector.detect_all()

            new_milestones = 0

            # Get or create default Journey
            journey = db.execute(select(Journey)).scalar_one_or_none()
            if not journey:
                journey = Journey(journey_code="default", description="Default journey")
                db.add(journey)
                db.commit()
                db.refresh(journey)

            # Store milestones
            for milestone in milestones:
                existing = db.execute(
                    select(JourneyMilestone).where(
                        (JourneyMilestone.journey_id == journey.id) &
                        (JourneyMilestone.type == milestone.type.value) &
                        (JourneyMilestone.dive_code == milestone.dive_code) &
                        (JourneyMilestone.occurrence_date == milestone.date)
                    )
                ).scalar_one_or_none()

                if not existing:
                    journey_milestone = JourneyMilestone(
                        journey_id=journey.id,
                        type=milestone.type.value,
                        dive_code=milestone.dive_code,
                        height=milestone.height,
                        detected_date=datetime.utcnow(),
                        occurrence_date=milestone.date,
                        title=milestone.title,
                        narrative=milestone.narrative,
                        attempts_before=milestone.attempts_before,
                        failures_before=milestone.failures_before,
                        days_since_last=milestone.days_since_last,
                        streak_length=milestone.streak_length,
                        emoji=milestone.emoji,
                        significance=milestone.significance,
                        dive_uuid=milestone.dive_uuid,
                        phase1_performance=milestone.phase1_performance,
                        phase2_performance=milestone.phase2_performance,
                        phase_insight=milestone.phase_insight,
                    )
                    db.add(journey_milestone)
                    new_milestones += 1

            if new_milestones > 0:
                db.commit()
                logger.info(f"Batch milestone detection: {new_milestones} new milestones")
                _notify_milestone_owners(db, dive_ids, new_milestones)

            return {
                'detected': len(milestones),
                'new_milestones': new_milestones,
                'success': True,
                'error': None
            }

        except Exception as e:
            logger.error(f"Error in batch milestone detection: {e}")
            return {
                'detected': 0,
                'new_milestones': 0,
                'success': False,
                'error': str(e)
            }

    @staticmethod
    def _dive_to_attempt(dive: Dive) -> DiveAttempt:
        """Convert Dive model to DiveAttempt for milestone detection.

        Args:
            dive: Dive database record

        Returns:
            DiveAttempt object ready for milestone detection
        """
        return DiveAttempt(
            uuid=dive.video_uuid,
            dive_code=dive.dive_code,
            height=dive.height,
            performance=dive.performance,  # Use composite performance
            date=dive.dive_datetime,
            is_sync=dive.is_sync,
            is_smack=dive.is_smack,
            phase1_performance=dive.phase1_performance,
            phase2_performance=dive.phase2_performance,
        )

    async def process_new_dives(self, dive_ids: List[int], db: Session) -> None:
        """Background task to process new dives for Journey updates.

        This is called from sync endpoints as a background task.

        Args:
            dive_ids: List of newly created dive IDs
            db: Database session
        """
        try:
            result = await self.sync_after_video_upload(db, dive_ids)

            if result['success']:
                logger.info(
                    f"Background Journey processing: {result['processed_journeys']} journeys, "
                    f"{result['milestones_detected']} milestones"
                )
            else:
                logger.error(
                    f"Background Journey processing failed: {result['error']}"
                )
        except Exception as e:
            logger.error(f"Error in background Journey processing: {e}")

    def generate_mental_block_recovery_plan(
        self,
        db: Session,
        journey_id: int,
        blocked_dives: List[str]
    ) -> Dict:
        """Generate a 3-phase mental block recovery plan.

        The plan addresses psychological blocks preventing progress:
        - Phase 1 (2 weeks): Rebuild confidence at lower DD
        - Phase 2 (2 weeks): Psychological prep (visualization, video review)
        - Phase 3 (2-3 weeks): Controlled exposure at actual height

        Args:
            db: Database session
            journey_id: Journey ID
            blocked_dives: List of dive codes to target (e.g., ["101B", "201C"])

        Returns:
            Dictionary with recovery plan details:
            {
                'plan_id': int,
                'blocked_dives': List[str],
                'phase_details': List[Dict],
                'total_duration': int (days),
                'success_criteria': Dict,
                'daily_actions': Dict
            }
        """
        try:
            # Verify journey exists
            journey = db.execute(
                select(Journey).where(Journey.id == journey_id)
            ).scalar_one_or_none()

            if not journey:
                return {
                    "success": False,
                    "error": f"Journey {journey_id} not found"
                }

            # Get fear analyzer to understand baseline fear
            fear_analyzer = FearAnalyzer(db)

            # Build reason string
            fear_analysis = fear_analyzer.detect_fear_plateau()
            reason = (
                f"Mental block recovery for dives: {', '.join(blocked_dives)}. "
                f"Risk level: {fear_analysis['risk_level']}. "
                f"Confidence blocks: {len(fear_analysis['confidence_blocks'])} identified."
            )

            # Calculate fear coefficient for baseline
            fear_coefficients = []
            for dive_code in blocked_dives:
                coeff_data = fear_analyzer.calculate_fear_coefficient(dive_code)
                fear_coefficients.append(coeff_data["fear_coefficient"])

            avg_fear_coefficient = (
                sum(fear_coefficients) / len(fear_coefficients)
                if fear_coefficients else 1.0
            )

            # Create recovery plan
            plan = RecoveryPlan(
                journey_id=journey_id,
                blocked_dive_codes=",".join(blocked_dives),
                status="active",
                phase1_goal=(
                    "Rebuild confidence with lower difficulty variations of blocked dives. "
                    "Use lineups and reduced height progressions to establish success patterns."
                ),
                phase2_goal=(
                    "Psychological preparation through visualization, mental rehearsal, "
                    "video review of successful attempts, and breathing exercises."
                ),
                phase3_goal=(
                    "Controlled exposure at target height with graduated difficulty. "
                    "Establish new success patterns with full-difficulty dives."
                ),
                phase1_duration=14,
                phase2_duration=14,
                phase3_duration=21,
                current_phase=1,
                completion_percentage=0,
                initial_fear_coefficient=int(avg_fear_coefficient * 100),
                reason=reason
            )

            db.add(plan)
            db.commit()
            db.refresh(plan)

            # Define phase details
            phase_details = [
                {
                    "phase": 1,
                    "name": "Confidence Rebuilding",
                    "duration_days": 14,
                    "focus": "Lower difficulty, build success pattern",
                    "activities": [
                        "Daily lineup practice with blocked dive codes",
                        "Video review of successful attempts",
                        "Practice at lower heights (1m, 3m instead of 5m+)",
                        "Confidence-building exercises (journaling successes)",
                        "Emotional tracking before/after attempts"
                    ],
                    "success_criteria": {
                        "minimum_attempts": 20,
                        "success_rate": ">70%",
                        "confidence_rating": "average >= 3.5/5"
                    }
                },
                {
                    "phase": 2,
                    "name": "Psychological Preparation",
                    "duration_days": 14,
                    "focus": "Mental readiness, visualization, technical review",
                    "activities": [
                        "Guided visualization (imagine perfect execution)",
                        "Study video of successful attempts",
                        "Mental rehearsal with breathing techniques",
                        "Journal emotional patterns and triggers",
                        "Practice grounding techniques (5-4-3-2-1 sensory focus)",
                        "Reflection on progress so far"
                    ],
                    "success_criteria": {
                        "visualization_sessions": "3-4 per week",
                        "confidence_rating": "average >= 4.0/5",
                        "emotional_awareness": "identified 3+ personal triggers"
                    }
                },
                {
                    "phase": 3,
                    "name": "Controlled Exposure",
                    "duration_days": 21,
                    "focus": "Gradual progression to target difficulty",
                    "activities": [
                        "Week 1: Dives at intermediate heights",
                        "Week 2: Dives at 80% of target difficulty",
                        "Week 3: Full difficulty dives with psychological support",
                        "Continue emotional tracking",
                        "Celebrate successful attempts publicly",
                        "Build support network (share progress with coach/teammates)"
                    ],
                    "success_criteria": {
                        "minimum_attempts": "3+ at full difficulty",
                        "success_rate": ">=60%",
                        "confidence_rating": "average >= 4.5/5"
                    }
                }
            ]

            # Daily action plan
            daily_actions = {
                "phase_1": [
                    "Morning: 5-min confidence affirmation + breath work",
                    "Training: Lineup practice x10 with blocked dive codes",
                    "Training: Video review of 1 successful attempt",
                    "Evening: Journal 3 successful moments from training",
                    "Evening: Emotion tracking (pre/post)"
                ],
                "phase_2": [
                    "Morning: 10-min guided visualization",
                    "Study: Video review (10-15 minutes)",
                    "Mental prep: 5-min grounding exercise before training",
                    "Training: Lower difficulty progressions (2-3 attempts)",
                    "Evening: Journal emotional patterns and insights",
                    "Evening: Reflect on confidence growth"
                ],
                "phase_3": [
                    "Warm-up: Confidence building + visualization",
                    "Training: Progressed height/difficulty attempts",
                    "Focus: Quality over quantity (fewer, more intentional attempts)",
                    "Recovery: Emotional validation and support",
                    "Evening: Track progress toward goals",
                    "Weekly: Celebrate and review milestone achievements"
                ]
            }

            return {
                "success": True,
                "plan_id": plan.id,
                "blocked_dives": blocked_dives,
                "created_at": plan.created_at.isoformat(),
                "phase_details": phase_details,
                "daily_actions": daily_actions,
                "total_duration": sum(p["duration_days"] for p in phase_details),
                "estimated_completion": (
                    datetime.utcnow() + timedelta(days=sum(p["duration_days"] for p in phase_details))
                ).isoformat(),
                "fear_baseline": {
                    "average_fear_coefficient": round(avg_fear_coefficient, 2),
                    "interpretation": (
                        "irrational_fear" if avg_fear_coefficient > 1.5
                        else "balanced" if avg_fear_coefficient > 0.5
                        else "appropriate_caution"
                    )
                },
                "progress_tracking": {
                    "method": "Track confidence ratings and success rates daily",
                    "milestones": [
                        "Phase 1: 70%+ success rate at lower difficulties",
                        "Phase 2: 4.0+ avg confidence rating",
                        "Phase 3: 60%+ success at full difficulty + sustained confidence"
                    ]
                }
            }

        except Exception as e:
            logger.error(f"Error generating recovery plan: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def get_mental_blocks(self, db: Session, journey_id: int) -> Dict:
        """Identify and retrieve mental blocks for a journey.

        Args:
            db: Database session
            journey_id: Journey ID

        Returns:
            Dictionary with mental block analysis
        """
        try:
            # Get fear analyzer
            fear_analyzer = FearAnalyzer(db)

            # Detect fear plateau
            plateau_analysis = fear_analyzer.detect_fear_plateau()

            # Get emotional triggers
            triggers = fear_analyzer.get_emotional_triggers()

            # Get confidence trends
            trends = fear_analyzer.track_confidence_trends(days=30)

            # Get existing recovery plans
            recovery_plans = db.execute(
                select(RecoveryPlan).where(
                    RecoveryPlan.journey_id == journey_id,
                    RecoveryPlan.status != "completed"
                )
            ).scalars().all()

            return {
                "journey_id": journey_id,
                "plateau_analysis": plateau_analysis,
                "emotional_triggers": triggers,
                "confidence_trends": trends,
                "active_recovery_plans": [
                    {
                        "plan_id": p.id,
                        "blocked_dives": p.blocked_dive_codes.split(","),
                        "status": p.status,
                        "current_phase": p.current_phase,
                        "created_at": p.created_at.isoformat(),
                        "phase1_started": p.phase1_started_at.isoformat() if p.phase1_started_at else None,
                    }
                    for p in recovery_plans
                ]
            }

        except Exception as e:
            logger.error(f"Error retrieving mental blocks: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def update_recovery_plan_phase(
        self,
        db: Session,
        plan_id: int,
        current_phase: int,
        completion_percentage: int = None
    ) -> Dict:
        """Update recovery plan phase progress.

        Args:
            db: Database session
            plan_id: Recovery plan ID
            current_phase: Phase number (1, 2, 3, or 0 for completed)
            completion_percentage: Percentage completion

        Returns:
            Updated plan information
        """
        try:
            plan = db.execute(
                select(RecoveryPlan).where(RecoveryPlan.id == plan_id)
            ).scalar_one_or_none()

            if not plan:
                return {"success": False, "error": f"Recovery plan {plan_id} not found"}

            # Update phase and timestamps
            plan.current_phase = current_phase

            now = datetime.utcnow()

            if current_phase == 1 and not plan.phase1_started_at:
                plan.phase1_started_at = now
            elif current_phase == 2:
                if plan.phase1_completed_at is None:
                    plan.phase1_completed_at = now
                if not plan.phase2_started_at:
                    plan.phase2_started_at = now
            elif current_phase == 3:
                if plan.phase2_completed_at is None:
                    plan.phase2_completed_at = now
                if not plan.phase3_started_at:
                    plan.phase3_started_at = now
            elif current_phase == 0:  # Completed
                if plan.phase3_completed_at is None:
                    plan.phase3_completed_at = now
                plan.status = "completed"
                plan.completed_at = now
                plan.completion_percentage = 100

            if completion_percentage is not None:
                plan.completion_percentage = min(100, max(0, completion_percentage))

            plan.updated_at = now

            db.add(plan)
            db.commit()
            db.refresh(plan)

            return {
                "success": True,
                "plan_id": plan.id,
                "current_phase": plan.current_phase,
                "completion_percentage": plan.completion_percentage,
                "status": plan.status,
                "updated_at": plan.updated_at.isoformat()
            }

        except Exception as e:
            logger.error(f"Error updating recovery plan: {e}")
            return {
                "success": False,
                "error": str(e)
            }


async def process_new_dives_background(dive_ids: List[int], db: Session) -> None:
    """Standalone function for background task processing.

    Args:
        dive_ids: List of newly created dive IDs
        db: Database session
    """
    service = JourneyService()
    await service.process_new_dives(dive_ids, db)


def _notify_milestone_owners(db: Session, dive_ids, new_milestones_count: int) -> None:
    """Durable milestone inbox rows for the owners of the triggering dives.

    The real-time WS `milestone_detected` event (sync_status) stays
    ephemeral; this is its durable per-user counterpart. Defensive: a
    notification failure must never fail milestone persistence.
    """
    try:
        if not dive_ids or new_milestones_count <= 0:
            return
        from app.services import notification_service

        rows = (
            db.query(Dive.id, Dive.diver_id)
            .filter(Dive.id.in_(list(dive_ids)[:500]))
            .limit(500)
            .all()
        )
        by_diver: Dict[int, List[int]] = {}
        for did, diver_id in rows:
            if diver_id is None:
                continue
            by_diver.setdefault(diver_id, []).append(did)
        for diver_id, ids in by_diver.items():
            notification_service.notify_owners_for_diver(
                db,
                diver_id=diver_id,
                exclude_user_id=None,
                type="milestone",
                title="New milestone",
                body=(
                    f"{new_milestones_count} new milestones detected"
                    if new_milestones_count > 1
                    else "A new milestone was detected"
                ),
                dive_id=ids[0] if len(ids) == 1 else None,
            )
    except Exception:
        logger.exception("milestone notification failed")
        try:
            db.rollback()
        except Exception:
            pass
