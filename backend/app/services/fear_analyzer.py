"""Fear analysis and psychological plateau detection for athlete development."""

import logging
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.models.dive import Dive
from app.models.session import Session as SessionModel
from app.models.journey import Journey, JourneyMilestone
from app.models.emotional_state import EmotionalState

logger = logging.getLogger(__name__)


class FearAnalyzer:
    """Analyze fear patterns, psychological blocks, and confidence trends."""

    def __init__(self, db: Session):
        """Initialize fear analyzer with database session.

        Args:
            db: SQLAlchemy database session
        """
        self.db = db

    def detect_fear_plateau(self, user_id: Optional[int] = None) -> Dict:
        """Identify dives avoided despite capability.

        A fear plateau occurs when an athlete can execute dives at a certain level
        but avoids attempting more difficult dives despite having the skill.

        Returns:
            Dictionary with:
            - avoided_dives: List of (dive_code, height) tuples with avoidance data
            - dd_gap: Degree of difficulty gap between capable and attempted dives
            - confidence_blocks: Emotional patterns blocking progress
            - risk_level: "low", "medium", or "high" (based on gap and pattern)
        """
        # Get all dives (user_id filtering can be added in future)
        dives = self.db.execute(
            select(Dive).where(Dive.is_lineup == False).order_by(Dive.dive_datetime.asc())
        ).scalars().all()

        if not dives:
            return {
                "avoided_dives": [],
                "dd_gap": 0,
                "confidence_blocks": [],
                "risk_level": "low",
                "message": "No dive data available for fear analysis"
            }

        # Group dives by (code, height)
        dive_groups = defaultdict(list)
        for dive in dives:
            key = (dive.dive_code, dive.height)
            dive_groups[key].append(dive)

        # Identify successful dives (to establish capability level)
        successful_dives = defaultdict(int)
        for dive in dives:
            if dive.performance_numeric >= 2:  # Success threshold
                key = (dive.dive_code, dive.height)
                successful_dives[key] += 1

        # Find the highest DD dives attempted
        max_official_dd = max([d.official_dd for d in dives if d.official_dd], default=0)

        # Detect avoided dives
        avoided_dives = []
        now = datetime.utcnow()
        days_threshold = 30

        for (code, height), dive_attempts in dive_groups.items():
            if len(dive_attempts) < 3:  # Need minimum attempts to establish pattern
                continue

            # Find most recent attempt
            last_attempt = max(dive_attempts, key=lambda d: d.dive_datetime)
            days_since = (now - last_attempt.dive_datetime).days

            if days_since >= days_threshold:
                # Calculate success rate
                successes = sum(1 for d in dive_attempts if d.performance_numeric >= 2)
                success_rate = successes / len(dive_attempts)

                # Get official DD if available
                official_dd = last_attempt.official_dd or 0

                # Emotional pattern
                emotional_states = self.db.execute(
                    select(EmotionalState).where(
                        EmotionalState.dive_id.in_([d.id for d in dive_attempts])
                    )
                ).scalars().all()

                fear_emotions = sum(1 for e in emotional_states if e.pre_dive_emotion in ["fearful", "anxious"])
                fear_pattern = fear_emotions > 0 and fear_emotions >= len(emotional_states) * 0.5

                avoided_dives.append({
                    "dive_code": code,
                    "height": height,
                    "days_since_attempt": days_since,
                    "total_attempts": len(dive_attempts),
                    "success_rate": round(success_rate * 100, 1),
                    "official_dd": float(official_dd),
                    "fear_pattern": fear_pattern,
                    "avoidance_score": self._calculate_avoidance_score(
                        days_since, success_rate, fear_pattern
                    )
                })

        # Sort by avoidance score
        avoided_dives.sort(key=lambda x: x["avoidance_score"], reverse=True)

        # Calculate DD gap (ensure numeric types are consistent)
        dd_gap = float(max_official_dd or 0) - max([d["official_dd"] for d in avoided_dives], default=0.0)

        # Extract confidence blocks
        confidence_blocks = self._extract_confidence_blocks(avoided_dives)

        # Assess risk level
        risk_level = self._assess_risk_level(len(avoided_dives), dd_gap, confidence_blocks)

        return {
            "avoided_dives": avoided_dives[:10],  # Top 10 avoided dives
            "dd_gap": round(dd_gap, 1),
            "confidence_blocks": confidence_blocks,
            "risk_level": risk_level,
            "total_avoided_patterns": len(avoided_dives),
        }

    def calculate_fear_coefficient(self, dive_code: str, user_id: Optional[int] = None) -> Dict:
        """Calculate fear level vs objective difficulty.

        Fear coefficient interpretation:
        - >1.5: Irrational fear (avoiding despite capability)
        - 0.5-1.5: Balanced progression
        - <0.5: Appropriate caution

        Returns:
            Dictionary with:
            - fear_coefficient: Float between 0 and 3
            - interpretation: "irrational_fear", "balanced", or "appropriate_caution"
            - objective_difficulty: Official FINA DD value
            - performance_vs_difficulty: How well athlete performs at this difficulty
            - recommendation: Suggested next step
        """
        # Get all dives of this code
        dives = self.db.execute(
            select(Dive).where(
                Dive.dive_code == dive_code,
                Dive.is_lineup == False
            )
        ).scalars().all()

        if not dives:
            return {
                "fear_coefficient": 0,
                "interpretation": "insufficient_data",
                "objective_difficulty": 0,
                "performance_vs_difficulty": 0,
                "recommendation": f"No data available for {dive_code}"
            }

        # Get objective difficulty (FINA DD)
        official_dd = dives[0].official_dd or 0

        # Calculate performance metrics
        successes = sum(1 for d in dives if d.performance_numeric >= 2)
        success_rate = successes / len(dives) if dives else 0

        # Calculate attempt frequency (how often they try vs how often available)
        dates = [d.dive_datetime for d in dives]
        if len(dates) > 1:
            days_span = (max(dates) - min(dates)).days
            days_per_attempt = max(1, days_span / len(dives))
        else:
            days_per_attempt = 1

        # Calculate confidence pattern from emotional states
        emotional_states = self.db.execute(
            select(EmotionalState).where(
                EmotionalState.dive_id.in_([d.id for d in dives])
            )
        ).scalars().all()

        avg_confidence = 0
        if emotional_states:
            confidence_ratings = [e.confidence_rating for e in emotional_states if e.confidence_rating]
            avg_confidence = sum(confidence_ratings) / len(confidence_ratings) if confidence_ratings else 0

        fear_emotions = sum(1 for e in emotional_states if e.pre_dive_emotion in ["fearful", "anxious"])
        fear_emotion_rate = fear_emotions / len(emotional_states) if emotional_states else 0

        # Calculate fear coefficient
        # High success rate lowers fear coefficient
        # High frequency of fear emotions raises it
        # Low confidence ratings raise it
        performance_factor = success_rate  # 0-1: higher = lower fear
        confidence_factor = avg_confidence / 5.0  # 0-1: higher = lower fear
        emotional_factor = fear_emotion_rate  # 0-1: higher = higher fear

        # Weighted formula
        fear_coefficient = (
            (1 - performance_factor) * 0.5 +  # Poor performance increases fear
            (1 - confidence_factor) * 0.3 +   # Low confidence increases fear
            emotional_factor * 0.2              # Fear emotions increase fear
        )

        # Adjust for attempt frequency (avoiding increases coefficient)
        if days_per_attempt > 7:
            fear_coefficient *= 1.5

        # Cap at 3.0
        fear_coefficient = min(fear_coefficient, 3.0)

        # Interpret coefficient
        if fear_coefficient > 1.5:
            interpretation = "irrational_fear"
            recommendation = (
                f"Despite {success_rate*100:.0f}% success rate on {dive_code}, "
                "you're avoiding it. Consider tackling fear through exposure and visualization."
            )
        elif fear_coefficient < 0.5:
            interpretation = "appropriate_caution"
            recommendation = (
                f"Your caution with {dive_code} matches the difficulty level. "
                "Continue building skills systematically."
            )
        else:
            interpretation = "balanced"
            recommendation = f"Your approach to {dive_code} is balanced. Steady progress!"

        return {
            "dive_code": dive_code,
            "fear_coefficient": round(fear_coefficient, 2),
            "interpretation": interpretation,
            "objective_difficulty": float(official_dd),
            "success_rate": round(success_rate * 100, 1),
            "avg_confidence_rating": round(avg_confidence, 2),
            "fear_emotion_frequency": round(fear_emotion_rate * 100, 1),
            "total_attempts": len(dives),
            "recommendation": recommendation
        }

    def get_emotional_triggers(self, user_id: Optional[int] = None) -> Dict:
        """Correlate emotions with dive difficulty.

        Returns:
            Dictionary with:
            - high_fear_dives: Dives triggering fear/anxiety emotions
            - confidence_drivers: Dives building confidence
            - emotional_patterns: Common patterns across dives
            - recommendations: How to address emotional triggers
        """
        # Get all dives
        dives = self.db.execute(
            select(Dive).where(Dive.is_lineup == False)
        ).scalars().all()

        if not dives:
            return {
                "high_fear_dives": [],
                "confidence_drivers": [],
                "emotional_patterns": [],
                "recommendations": "No dive data available"
            }

        # Get emotional states
        emotional_states = self.db.execute(
            select(EmotionalState).where(
                EmotionalState.dive_id.in_([d.id for d in dives])
            )
        ).scalars().all()

        # Create dive lookup
        dive_map = {d.id: d for d in dives}

        # Categorize by emotion
        high_fear_dives = defaultdict(lambda: {"attempts": 0, "successes": 0, "fear_count": 0})
        confidence_drivers = defaultdict(lambda: {"attempts": 0, "successes": 0, "confidence_count": 0})

        for emotion in emotional_states:
            dive = dive_map.get(emotion.dive_id)
            if not dive:
                continue

            key = (dive.dive_code, dive.height)

            # Track fear triggers
            if emotion.pre_dive_emotion in ["fearful", "anxious"]:
                high_fear_dives[key]["attempts"] += 1
                high_fear_dives[key]["fear_count"] += 1
                if dive.performance_numeric >= 2:
                    high_fear_dives[key]["successes"] += 1

            # Track confidence drivers
            if emotion.post_dive_emotion in ["proud", "satisfied"]:
                confidence_drivers[key]["attempts"] += 1
                confidence_drivers[key]["confidence_count"] += 1
                if dive.performance_numeric >= 4:
                    confidence_drivers[key]["successes"] += 1

        # Format results
        high_fear_list = [
            {
                "dive_code": code,
                "height": height,
                "fear_frequency": round(data["fear_count"] / data["attempts"] * 100, 1),
                "success_despite_fear": data["successes"],
                "official_dd": float(dive_map[next(d.id for d in dives if (d.dive_code, d.height) == (code, height))].official_dd or 0)
            }
            for (code, height), data in high_fear_dives.items()
            if data["fear_count"] > 0
        ]

        confidence_list = [
            {
                "dive_code": code,
                "height": height,
                "confidence_frequency": round(data["confidence_count"] / data["attempts"] * 100, 1),
                "perfect_dives": data["successes"],
            }
            for (code, height), data in confidence_drivers.items()
            if data["confidence_count"] > 0
        ]

        # Sort
        high_fear_list.sort(key=lambda x: x["fear_frequency"], reverse=True)
        confidence_list.sort(key=lambda x: x["confidence_frequency"], reverse=True)

        # Extract patterns
        patterns = self._extract_emotional_patterns(emotional_states, dive_map)

        # Generate recommendations
        recommendations = self._generate_emotional_recommendations(
            high_fear_list, confidence_list, patterns
        )

        return {
            "high_fear_dives": high_fear_list[:10],
            "confidence_drivers": confidence_list[:10],
            "emotional_patterns": patterns,
            "recommendations": recommendations,
        }

    def track_confidence_trends(self, user_id: Optional[int] = None, days: int = 30) -> Dict:
        """Track 30-day confidence trends.

        Returns:
            Dictionary with:
            - daily_trend: Day-by-day confidence changes
            - weekly_summary: Week-by-week progress
            - slope: Trend direction (improving, stable, declining)
            - recommendations: Suggestions based on trend
        """
        # Get cutoff date
        cutoff = datetime.utcnow() - timedelta(days=days)

        # Get dives in timeframe
        recent_dives = self.db.execute(
            select(Dive).where(
                Dive.dive_datetime >= cutoff,
                Dive.is_lineup == False
            ).order_by(Dive.dive_datetime.asc())
        ).scalars().all()

        if not recent_dives:
            return {
                "daily_trend": [],
                "weekly_summary": [],
                "slope": "insufficient_data",
                "message": f"No dive data in last {days} days"
            }

        # Get emotional data for recent dives
        emotional_states = self.db.execute(
            select(EmotionalState).where(
                EmotionalState.dive_id.in_([d.id for d in recent_dives])
            )
        ).scalars().all()

        # Create emotional lookup
        emotion_map = {e.dive_id: e for e in emotional_states}

        # Build daily trend
        daily_data = defaultdict(lambda: {"confidence_ratings": [], "success_rate": 0, "dives": 0})

        for dive in recent_dives:
            date_key = dive.dive_datetime.date().isoformat()
            daily_data[date_key]["dives"] += 1

            if dive.performance_numeric >= 2:
                daily_data[date_key]["success_rate"] += 1

            emotion = emotion_map.get(dive.id)
            if emotion and emotion.confidence_rating:
                daily_data[date_key]["confidence_ratings"].append(emotion.confidence_rating)

        # Calculate daily summaries
        daily_trend = []
        for date_str in sorted(daily_data.keys()):
            data = daily_data[date_str]
            avg_confidence = (
                sum(data["confidence_ratings"]) / len(data["confidence_ratings"])
                if data["confidence_ratings"] else 0
            )
            daily_trend.append({
                "date": date_str,
                "avg_confidence": round(avg_confidence, 2),
                "dives": data["dives"],
                "success_rate": round(data["success_rate"] / data["dives"] * 100, 1) if data["dives"] else 0
            })

        # Build weekly summary
        weekly_data = defaultdict(lambda: {"confidence_ratings": [], "dives": 0, "successes": 0})

        for dive in recent_dives:
            week_key = dive.dive_datetime.isocalendar()[1]  # ISO week number
            weekly_data[week_key]["dives"] += 1

            if dive.performance_numeric >= 2:
                weekly_data[week_key]["successes"] += 1

            emotion = emotion_map.get(dive.id)
            if emotion and emotion.confidence_rating:
                weekly_data[week_key]["confidence_ratings"].append(emotion.confidence_rating)

        weekly_summary = [
            {
                "week": week,
                "avg_confidence": round(
                    sum(data["confidence_ratings"]) / len(data["confidence_ratings"]), 2
                ) if data["confidence_ratings"] else 0,
                "dives": data["dives"],
                "success_rate": round(data["successes"] / data["dives"] * 100, 1) if data["dives"] else 0
            }
            for week, data in sorted(weekly_data.items())
        ]

        # Calculate slope
        if len(daily_trend) >= 2:
            first_week = daily_trend[:len(daily_trend)//4]
            last_week = daily_trend[-len(daily_trend)//4:]

            first_avg = sum(d["avg_confidence"] for d in first_week) / len(first_week) if first_week else 0
            last_avg = sum(d["avg_confidence"] for d in last_week) / len(last_week) if last_week else 0

            difference = last_avg - first_avg
            if difference > 0.5:
                slope = "improving"
            elif difference < -0.5:
                slope = "declining"
            else:
                slope = "stable"
        else:
            slope = "insufficient_data"

        # Generate recommendations
        recommendations = self._generate_trend_recommendations(slope, daily_trend, weekly_summary)

        return {
            "daily_trend": daily_trend,
            "weekly_summary": weekly_summary,
            "slope": slope,
            "days_analyzed": days,
            "total_dives": len(recent_dives),
            "recommendations": recommendations,
        }

    # Private helper methods

    @staticmethod
    def _calculate_avoidance_score(days_since: int, success_rate: float, fear_pattern: bool) -> float:
        """Calculate how strongly a dive is being avoided.

        Higher score = more likely being actively avoided due to fear.
        """
        score = days_since * (1 - success_rate)
        if fear_pattern:
            score *= 1.5
        return score

    @staticmethod
    def _extract_confidence_blocks(avoided_dives: List[Dict]) -> List[Dict]:
        """Extract common patterns in avoided dives."""
        blocks = []

        if not avoided_dives:
            return blocks

        # Group by fear pattern
        fear_driven = [d for d in avoided_dives if d["fear_pattern"]]
        difficulty_driven = [d for d in avoided_dives if not d["fear_pattern"]]

        if fear_driven:
            blocks.append({
                "type": "emotional_block",
                "count": len(fear_driven),
                "dives": [d["dive_code"] for d in fear_driven[:3]],
                "description": "Fear or anxiety preventing attempts"
            })

        if difficulty_driven:
            blocks.append({
                "type": "difficulty_plateau",
                "count": len(difficulty_driven),
                "dives": [d["dive_code"] for d in difficulty_driven[:3]],
                "description": "Avoiding due to technical difficulty without fear pattern"
            })

        return blocks

    @staticmethod
    def _assess_risk_level(num_avoided: int, dd_gap: float, confidence_blocks: List) -> str:
        """Assess overall risk level of plateau."""
        if num_avoided == 0 or dd_gap < 0.5:
            return "low"
        elif num_avoided <= 3 and dd_gap < 1.5:
            return "medium"
        else:
            return "high"

    @staticmethod
    def _extract_emotional_patterns(emotional_states: List[EmotionalState],
                                    dive_map: Dict) -> List[Dict]:
        """Extract common emotional patterns from states."""
        patterns = []

        # Count pre-dive emotions
        pre_emotions = defaultdict(int)
        post_emotions = defaultdict(int)

        for emotion in emotional_states:
            if emotion.pre_dive_emotion:
                pre_emotions[emotion.pre_dive_emotion] += 1
            if emotion.post_dive_emotion:
                post_emotions[emotion.post_dive_emotion] += 1

        # Most common pre-dive emotion
        if pre_emotions:
            most_common_pre = max(pre_emotions.items(), key=lambda x: x[1])
            patterns.append({
                "pattern": f"Pre-dive: {most_common_pre[0]}",
                "frequency": most_common_pre[1],
                "description": f"Athletes most commonly feel {most_common_pre[0]} before dives"
            })

        # Most common post-dive emotion
        if post_emotions:
            most_common_post = max(post_emotions.items(), key=lambda x: x[1])
            patterns.append({
                "pattern": f"Post-dive: {most_common_post[0]}",
                "frequency": most_common_post[1],
                "description": f"Athletes most commonly feel {most_common_post[0]} after dives"
            })

        return patterns

    @staticmethod
    def _generate_emotional_recommendations(high_fear_list: List[Dict],
                                           confidence_list: List[Dict],
                                           patterns: List[Dict]) -> List[str]:
        """Generate recommendations based on emotional analysis."""
        recommendations = []

        if high_fear_list:
            top_fear = high_fear_list[0]
            recommendations.append(
                f"Address fear of {top_fear['dive_code']} from {top_fear['height']} "
                f"({top_fear['fear_frequency']}% fear frequency) through visualization and gradual exposure."
            )

        if confidence_list:
            top_confidence = confidence_list[0]
            recommendations.append(
                f"Build on success with {top_confidence['dive_code']} from {top_confidence['height']} "
                f"({top_confidence['perfect_dives']} perfect dives) - you excel at these!"
            )

        if not recommendations:
            recommendations.append("Continue consistent training and emotional tracking for pattern analysis.")

        return recommendations

    @staticmethod
    def _generate_trend_recommendations(slope: str, daily_trend: List[Dict],
                                       weekly_summary: List[Dict]) -> List[str]:
        """Generate recommendations based on confidence trend."""
        recommendations = []

        if slope == "improving":
            recommendations.append(
                "Your confidence is improving! Maintain your current training approach and "
                "consider tackling one feared dive during this positive momentum."
            )
        elif slope == "declining":
            recommendations.append(
                "Your confidence appears to be declining. Consider reducing difficulty temporarily "
                "and focusing on mastering fundamentals at lower heights."
            )
            recommendations.append(
                "Increase positive reinforcement - celebrate small wins and session successes."
            )
        else:
            recommendations.append(
                "Your confidence is stable. Focus on incremental progressions and "
                "set small achievable goals to maintain momentum."
            )

        # Check if recent dives show improvement
        if len(daily_trend) >= 3:
            recent_avg = sum(d["avg_confidence"] for d in daily_trend[-3:]) / 3
            earlier_avg = sum(d["avg_confidence"] for d in daily_trend[:3]) / 3
            if recent_avg > earlier_avg:
                recommendations.append(
                    "Recent sessions show more confidence - you're responding well to your training!"
                )

        return recommendations
