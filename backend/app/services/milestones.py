"""
Milestone Detection Engine

This isn't analytics. This is narrative extraction.

Every diver has a story. This code finds it in the data.

Milestones we detect:
- FIRST_ATTEMPT: Courage to try something new
- FIRST_SUCCESS: The breakthrough moment
- FIRST_PERFECT: Mastery glimpsed
- PERSISTENCE: Success after repeated failure (the hero's journey)
- COMEBACK: Returning to a dive after a long gap
- PLATEAU_BROKEN: Growth after stagnation
- STREAK: Consecutive successes (confidence building)
- CONSISTENCY_ACHIEVED: Low variance over time (reliability)
- AVOIDED_DIVE_ATTEMPTED: Facing what you've been avoiding
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from enum import Enum
from collections import defaultdict
import statistics

from app.services.performance_scoring import athlete_score_10, attempt_score_10, is_excellent, is_success


class MilestoneType(Enum):
    """Types of meaningful moments in a diver's journey."""

    # Courage milestones
    FIRST_ATTEMPT = "first_attempt"
    FIRST_FROM_HEIGHT = "first_from_height"
    AVOIDED_DIVE_ATTEMPTED = "avoided_dive_attempted"

    # Success milestones
    FIRST_SUCCESS = "first_success"  # First M or better
    FIRST_GOOD = "first_good"
    FIRST_PERFECT = "first_perfect"

    # Persistence milestones (the most meaningful)
    BREAKTHROUGH = "breakthrough"  # Success after 3+ failures
    REDEMPTION = "redemption"  # Perfect after a smack
    COMEBACK = "comeback"  # Return after 30+ day gap

    # Growth milestones
    PLATEAU_BROKEN = "plateau_broken"
    NEW_HEIGHT_CONQUERED = "new_height_conquered"
    CONSISTENCY_ACHIEVED = "consistency_achieved"

    # Momentum milestones
    SUCCESS_STREAK = "success_streak"
    PERFECT_STREAK = "perfect_streak"
    TRAINING_STREAK = "training_streak"  # Consecutive days

    # Special
    SYNCHRO_FIRST_SUCCESS = "synchro_first_success"
    PERSONAL_BEST = "personal_best"


@dataclass
class Milestone:
    """A meaningful moment in a diver's journey."""

    type: MilestoneType
    dive_code: Optional[str]
    height: Optional[str]
    date: datetime

    # The story
    title: str
    narrative: str  # Human-readable description

    # Context that makes it meaningful
    attempts_before: int = 0
    failures_before: int = 0
    days_since_last: int = 0
    streak_length: int = 0

    # For UI
    emoji: str = "🏊"
    significance: int = 1  # 1-5 scale

    # Reference to the triggering dive
    dive_uuid: Optional[str] = None

    # Two-phase scoring insights (new Jan 2026)
    phase1_performance: Optional[str] = None  # Hurdle + Flight score
    phase2_performance: Optional[str] = None  # Opening + Entry score
    phase_insight: Optional[str] = None  # Specific recommendation based on phases

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type.value,
            "dive_code": self.dive_code,
            "height": self.height,
            "date": self.date.isoformat(),
            "title": self.title,
            "narrative": self.narrative,
            "attempts_before": self.attempts_before,
            "failures_before": self.failures_before,
            "days_since_last": self.days_since_last,
            "streak_length": self.streak_length,
            "emoji": self.emoji,
            "significance": self.significance,
            # Include phase info if available
            "phase1_performance": self.phase1_performance,
            "phase2_performance": self.phase2_performance,
            "phase_insight": self.phase_insight,
        }


@dataclass
class DiveAttempt:
    """Single dive attempt for analysis."""
    uuid: str
    dive_code: str
    height: str
    performance: str  # F, B, M, G, P (composite or legacy)
    date: datetime
    is_sync: bool = False
    is_smack: bool = False

    # Two-phase scoring (new format as of Jan 2026)
    phase1_performance: Optional[str] = None  # Hurdle + Flight
    phase2_performance: Optional[str] = None  # Opening + Entry

    @property
    def performance_value(self) -> float:
        return attempt_score_10(self.performance, self.phase1_performance, self.phase2_performance)

    @property
    def phase1_value(self) -> Optional[float]:
        """Numeric value for Phase 1 (hurdle + flight)."""
        if self.phase1_performance:
            return athlete_score_10(self.phase1_performance)
        return None

    @property
    def phase2_value(self) -> Optional[float]:
        """Numeric value for Phase 2 (opening + entry)."""
        if self.phase2_performance:
            return athlete_score_10(self.phase2_performance)
        return None

    @property
    def is_two_phase(self) -> bool:
        """Whether this dive has two-phase scoring."""
        return self.phase1_performance is not None and self.phase2_performance is not None

    @property
    def is_success(self) -> bool:
        """M or better is a success."""
        return is_success(self.performance)

    @property
    def is_good(self) -> bool:
        return is_excellent(self.performance)

    @property
    def is_perfect(self) -> bool:
        return self.performance == "P"

    @property
    def phase1_description(self) -> str:
        """Human-readable phase 1 description."""
        if not self.phase1_performance:
            return "N/A"
        names = {'F': 'Failed', 'B': 'Bad', 'M': 'Medium', 'G': 'Good', 'P': 'Perfect'}
        return names.get(self.phase1_performance, 'Unknown')

    @property
    def phase2_description(self) -> str:
        """Human-readable phase 2 description."""
        if not self.phase2_performance:
            return "N/A"
        names = {'F': 'Failed', 'B': 'Bad', 'M': 'Medium', 'G': 'Good', 'P': 'Perfect'}
        return names.get(self.phase2_performance, 'Unknown')


class MilestoneDetector:
    """
    Detects meaningful moments in a diver's journey.

    This is not a simple threshold checker. It understands context:
    - A Perfect on your first try is impressive but different from
      a Perfect after 10 failures — the latter is a BREAKTHROUGH.
    - Coming back to a dive you've avoided for 2 months takes courage.
    - Three Good performances in a row means you're building confidence.

    The goal: surface the moments that matter to the diver's growth.
    """

    def __init__(self, attempts: List[DiveAttempt]):
        """
        Initialize with all attempts in chronological order.
        """
        self.attempts = sorted(attempts, key=lambda a: a.date)
        self._index_attempts()

    def _index_attempts(self):
        """Build indexes for efficient querying."""
        # By dive code
        self.by_code: Dict[str, List[DiveAttempt]] = defaultdict(list)
        for a in self.attempts:
            self.by_code[a.dive_code].append(a)

        # By height
        self.by_height: Dict[str, List[DiveAttempt]] = defaultdict(list)
        for a in self.attempts:
            self.by_height[a.height].append(a)

        # By date
        self.by_date: Dict[str, List[DiveAttempt]] = defaultdict(list)
        for a in self.attempts:
            date_key = a.date.strftime('%Y-%m-%d')
            self.by_date[date_key].append(a)

        # By code+height combination
        self.by_code_height: Dict[Tuple[str, str], List[DiveAttempt]] = defaultdict(list)
        for a in self.attempts:
            self.by_code_height[(a.dive_code, a.height)].append(a)

    def _generate_phase_insight(self, attempt: DiveAttempt) -> Optional[str]:
        """Generate coaching insight based on two-phase scores."""
        if not attempt.is_two_phase:
            return None

        phase1 = attempt.phase1_performance
        phase2 = attempt.phase2_performance

        # P/P: Perfect execution
        if phase1 == "P" and phase2 == "P":
            return "💎 Perfect execution: Both phases flawless. This is competition-ready."

        # P/G: Strong flight, good entry
        elif phase1 == "P" and phase2 == "G":
            return "✈️ Excellent flight, solid entry. Minor adjustments to entry could achieve perfect."

        # P/M: Strong flight, medium entry
        elif phase1 == "P" and phase2 == "M":
            return "🎯 Flight is perfect; focus on entry control and body awareness on entry."

        # P/B or P/F: Good flight but entry needs work
        elif phase1 == "P" and phase2 in {"B", "F"}:
            return "🎯 Your takeoff is excellent, but entry control needs development. Practice water entry positioning."

        # G/P: Solid flight, great recovery
        elif phase1 == "G" and phase2 == "P":
            return "🦾 Resilient execution: Good flight but excellent recovery shows great adaptability."

        # G/G: Consistent, reliable
        elif phase1 == "G" and phase2 == "G":
            return "📊 Consistent execution: Both phases solid. Continue building refinement."

        # G/M or G/B: Good flight, inconsistent entry
        elif phase1 == "G" and phase2 in {"M", "B", "F"}:
            return "📊 Flight is solid. Entry consistency needs work—focus on timing and body position."

        # M/P: Weak flight, great recovery
        elif phase1 == "M" and phase2 == "P":
            return "🦾 Remarkable recovery: Despite weak flight, excellent entry shows advanced adaptability."

        # M/M: Both need work
        elif phase1 == "M" and phase2 == "M":
            return "🔧 Both phases show room for improvement. Target flight mechanics and entry control."

        # M/G or M/F: Weak flight, decent entry
        elif phase1 == "M" and phase2 in {"B", "G"}:
            return "🔧 Flight needs development. Your entry timing is good—strengthen the takeoff."

        # F: Failed phase
        elif phase1 == "F" or phase2 == "F":
            return "💪 One phase challenging. Identify which phase and focus training there."

        return None

    def detect_all(self) -> List[Milestone]:
        """
        Detect all milestones in the diver's history.

        Returns milestones in chronological order.
        """
        milestones = []

        # Process each attempt and check for milestones
        for i, attempt in enumerate(self.attempts):
            prior_attempts = self.attempts[:i]

            milestones.extend(self._check_first_milestones(attempt, prior_attempts))
            milestones.extend(self._check_breakthrough_milestones(attempt, prior_attempts))
            milestones.extend(self._check_streak_milestones(attempt, prior_attempts))
            milestones.extend(self._check_comeback_milestones(attempt, prior_attempts))

        # Check for aggregate milestones (consistency, plateau-breaking)
        milestones.extend(self._check_consistency_milestones())
        milestones.extend(self._check_plateau_milestones())

        # Sort by date and significance
        milestones.sort(key=lambda m: (m.date, -m.significance))

        return milestones

    def _check_first_milestones(
        self,
        attempt: DiveAttempt,
        prior: List[DiveAttempt]
    ) -> List[Milestone]:
        """Check for 'first' type milestones."""
        milestones = []

        # Prior attempts of this specific dive+height
        prior_same = [a for a in prior
                      if a.dive_code == attempt.dive_code
                      and a.height == attempt.height]

        # First attempt of this dive at this height
        if not prior_same:
            milestones.append(Milestone(
                type=MilestoneType.FIRST_ATTEMPT,
                dive_code=attempt.dive_code,
                height=attempt.height,
                date=attempt.date,
                title=f"First {attempt.dive_code} from {attempt.height}",
                narrative=f"You attempted {attempt.dive_code} from {attempt.height} for the first time. "
                         f"Result: {self._performance_name(attempt.performance)}. "
                         f"Every master was once a beginner.",
                emoji="🌟",
                significance=2,
                dive_uuid=attempt.uuid,
            ))

        # First success on this dive+height
        prior_successes = [a for a in prior_same if a.is_success]
        if attempt.is_success and not prior_successes:
            failures_before = len([a for a in prior_same if not a.is_success])

            narrative = f"Your first successful {attempt.dive_code} from {attempt.height}!"
            if failures_before > 0:
                narrative += f" This came after {failures_before} previous attempt{'s' if failures_before > 1 else ''}. "
                narrative += "Persistence paid off."

            milestones.append(Milestone(
                type=MilestoneType.FIRST_SUCCESS,
                dive_code=attempt.dive_code,
                height=attempt.height,
                date=attempt.date,
                title=f"First successful {attempt.dive_code}",
                narrative=narrative,
                failures_before=failures_before,
                emoji="✅",
                significance=3,
                dive_uuid=attempt.uuid,
                # Phase information
                phase1_performance=attempt.phase1_performance,
                phase2_performance=attempt.phase2_performance,
                phase_insight=self._generate_phase_insight(attempt),
            ))

        # First Perfect on this dive+height
        prior_perfects = [a for a in prior_same if a.is_perfect]
        if attempt.is_perfect and not prior_perfects:
            attempts_before = len(prior_same)

            milestones.append(Milestone(
                type=MilestoneType.FIRST_PERFECT,
                dive_code=attempt.dive_code,
                height=attempt.height,
                date=attempt.date,
                title=f"First Perfect {attempt.dive_code}",
                narrative=f"Perfect execution of {attempt.dive_code} from {attempt.height}. "
                         f"{'First try perfection!' if attempts_before == 0 else f'After {attempts_before} attempts, mastery.'} "
                         f"This is what the work was for.",
                # Phase information
                phase1_performance=attempt.phase1_performance,
                phase2_performance=attempt.phase2_performance,
                phase_insight=self._generate_phase_insight(attempt),
                attempts_before=attempts_before,
                emoji="💎",
                significance=4,
                dive_uuid=attempt.uuid,
            ))

        # First attempt from a new height ever
        prior_from_height = [a for a in prior if a.height == attempt.height]
        if not prior_from_height:
            height_num = int(attempt.height.lower().replace('m', '').replace('p', ''))
            milestones.append(Milestone(
                type=MilestoneType.FIRST_FROM_HEIGHT,
                dive_code=attempt.dive_code,
                height=attempt.height,
                date=attempt.date,
                title=f"First dive from {attempt.height}",
                narrative=f"You dove from {attempt.height} for the first time. "
                         f"{'That platform looks different from up there.' if height_num >= 7 else 'New heights await.'}",
                emoji="🏔️" if height_num >= 7 else "📈",
                significance=3 if height_num >= 7 else 2,
                dive_uuid=attempt.uuid,
                # Phase information
                phase1_performance=attempt.phase1_performance,
                phase2_performance=attempt.phase2_performance,
                phase_insight=self._generate_phase_insight(attempt),
            ))

        return milestones

    def _check_breakthrough_milestones(
        self,
        attempt: DiveAttempt,
        prior: List[DiveAttempt]
    ) -> List[Milestone]:
        """Check for breakthrough/persistence milestones."""
        milestones = []

        prior_same = [a for a in prior
                      if a.dive_code == attempt.dive_code
                      and a.height == attempt.height]

        if not prior_same:
            return milestones

        # Count consecutive failures before this attempt
        consecutive_failures = 0
        for a in reversed(prior_same):
            if not a.is_success:
                consecutive_failures += 1
            else:
                break

        # BREAKTHROUGH: Success after 3+ consecutive failures
        if attempt.is_success and consecutive_failures >= 3:
            milestones.append(Milestone(
                type=MilestoneType.BREAKTHROUGH,
                dive_code=attempt.dive_code,
                height=attempt.height,
                date=attempt.date,
                title=f"Breakthrough on {attempt.dive_code}",
                narrative=f"You landed {attempt.dive_code} after {consecutive_failures} consecutive failed attempts. "
                         f"This is what growth looks like. Not the success — the refusal to stop trying.",
                failures_before=consecutive_failures,
                emoji="🔥",
                significance=5,  # Maximum significance
                dive_uuid=attempt.uuid,
                # Phase information
                phase1_performance=attempt.phase1_performance,
                phase2_performance=attempt.phase2_performance,
                phase_insight=self._generate_phase_insight(attempt),
            ))

        # REDEMPTION: Perfect after a smack
        recent_smacks = [a for a in prior_same[-5:] if a.is_smack]
        if attempt.is_perfect and recent_smacks:
            days_since_smack = (attempt.date - recent_smacks[-1].date).days
            milestones.append(Milestone(
                type=MilestoneType.REDEMPTION,
                dive_code=attempt.dive_code,
                height=attempt.height,
                date=attempt.date,
                title=f"Redemption: Perfect {attempt.dive_code}",
                narrative=f"From belly flop to perfection. "
                         f"{'Same day.' if days_since_smack == 0 else f'{days_since_smack} days later.'} "
                         f"The water remembers nothing. Neither should you.",
                days_since_last=days_since_smack,
                emoji="🦅",
                significance=5,
                dive_uuid=attempt.uuid,
            ))

        return milestones

    def _check_streak_milestones(
        self,
        attempt: DiveAttempt,
        prior: List[DiveAttempt]
    ) -> List[Milestone]:
        """Check for streak-based milestones."""
        milestones = []

        prior_same = [a for a in prior
                      if a.dive_code == attempt.dive_code
                      and a.height == attempt.height]

        if not attempt.is_success:
            return milestones

        # Count current success streak
        streak = 1
        for a in reversed(prior_same):
            if a.is_success:
                streak += 1
            else:
                break

        # SUCCESS_STREAK at 3, 5, 10
        if streak in [3, 5, 10]:
            milestones.append(Milestone(
                type=MilestoneType.SUCCESS_STREAK,
                dive_code=attempt.dive_code,
                height=attempt.height,
                date=attempt.date,
                title=f"{streak}x Success Streak",
                narrative=f"{streak} successful {attempt.dive_code}s in a row from {attempt.height}. "
                         f"{'Building confidence.' if streak == 3 else 'This dive is becoming yours.' if streak == 5 else 'Mastery.'}",
                streak_length=streak,
                emoji="🔥" if streak >= 5 else "📈",
                significance=2 if streak == 3 else 3 if streak == 5 else 4,
                dive_uuid=attempt.uuid,
                # Phase information
                phase1_performance=attempt.phase1_performance,
                phase2_performance=attempt.phase2_performance,
                phase_insight=self._generate_phase_insight(attempt),
            ))

        # PERFECT_STREAK at 2, 3, 5
        if attempt.is_perfect:
            perfect_streak = 1
            for a in reversed(prior_same):
                if a.is_perfect:
                    perfect_streak += 1
                else:
                    break

            if perfect_streak in [2, 3, 5]:
                milestones.append(Milestone(
                    type=MilestoneType.PERFECT_STREAK,
                    dive_code=attempt.dive_code,
                    height=attempt.height,
                    date=attempt.date,
                    title=f"{perfect_streak}x Perfect Streak",
                    narrative=f"{perfect_streak} consecutive Perfect executions of {attempt.dive_code}. "
                             f"{'Consistency emerging.' if perfect_streak == 2 else 'You own this dive.' if perfect_streak == 3 else 'Elite level.'}",
                    streak_length=perfect_streak,
                    emoji="💎",
                    significance=3 if perfect_streak == 2 else 4 if perfect_streak == 3 else 5,
                    dive_uuid=attempt.uuid,
                ))

        return milestones

    def _check_comeback_milestones(
        self,
        attempt: DiveAttempt,
        prior: List[DiveAttempt]
    ) -> List[Milestone]:
        """Check for comeback/avoided dive milestones."""
        milestones = []

        prior_same = [a for a in prior
                      if a.dive_code == attempt.dive_code
                      and a.height == attempt.height]

        if not prior_same:
            return milestones

        last_attempt = prior_same[-1]
        days_gap = (attempt.date - last_attempt.date).days

        # COMEBACK: Returning after 30+ days
        if days_gap >= 30:
            milestones.append(Milestone(
                type=MilestoneType.COMEBACK,
                dive_code=attempt.dive_code,
                height=attempt.height,
                date=attempt.date,
                title=f"Comeback: {attempt.dive_code}",
                narrative=f"You returned to {attempt.dive_code} after {days_gap} days away. "
                         f"Result: {self._performance_name(attempt.performance)}. "
                         f"{'Muscle memory is real.' if attempt.is_success else 'Courage to return is the first success.'}",
                days_since_last=days_gap,
                emoji="🔄",
                significance=3,
                dive_uuid=attempt.uuid,
                # Phase information
                phase1_performance=attempt.phase1_performance,
                phase2_performance=attempt.phase2_performance,
                phase_insight=self._generate_phase_insight(attempt),
            ))

        # AVOIDED_DIVE_ATTEMPTED: If this dive has a history of failures
        # and there was a significant gap
        if days_gap >= 14:
            failure_rate = len([a for a in prior_same if not a.is_success]) / len(prior_same)
            if failure_rate >= 0.6:  # 60%+ failure rate = scary dive
                milestones.append(Milestone(
                    type=MilestoneType.AVOIDED_DIVE_ATTEMPTED,
                    dive_code=attempt.dive_code,
                    height=attempt.height,
                    date=attempt.date,
                    title=f"Facing the fear: {attempt.dive_code}",
                    narrative=f"You've struggled with {attempt.dive_code} ({int(failure_rate*100)}% difficulty rate). "
                             f"After {days_gap} days, you faced it again. "
                             f"{'And conquered it.' if attempt.is_success else 'Showing up is winning.'}",
                    days_since_last=days_gap,
                    failures_before=len([a for a in prior_same if not a.is_success]),
                    emoji="🦁",
                    significance=4,
                    dive_uuid=attempt.uuid,
                ))

        return milestones

    def _check_consistency_milestones(self) -> List[Milestone]:
        """Check for consistency achievements across dive codes."""
        milestones = []

        for (code, height), attempts in self.by_code_height.items():
            if len(attempts) < 10:
                continue

            # Check last 10 attempts
            recent = attempts[-10:]
            perfs = [a.performance_value for a in recent]

            avg = statistics.mean(perfs)
            std = statistics.stdev(perfs) if len(perfs) > 1 else 0

            # CONSISTENCY_ACHIEVED: Low variance, high mean on the calibrated /10 scale.
            if std < 2.0 and avg >= 7.0:
                milestones.append(Milestone(
                    type=MilestoneType.CONSISTENCY_ACHIEVED,
                    dive_code=code,
                    height=height,
                    date=recent[-1].date,
                    title=f"Consistency achieved: {code}",
                    narrative=f"Your last 10 {code}s from {height} show remarkable consistency. "
                             f"Average: {self._performance_name_from_value(avg)}. "
                             f"This dive is competition-ready.",
                    emoji="🎯",
                    significance=4,
                ))

        return milestones

    def _check_plateau_milestones(self) -> List[Milestone]:
        """Check for plateau-breaking moments."""
        milestones = []

        # Analyze monthly averages
        monthly_avg: Dict[str, float] = {}
        for month, attempts in sorted(self.by_date.items()):
            month_key = month[:7]  # YYYY-MM
            if month_key not in monthly_avg:
                monthly_avg[month_key] = []
            monthly_avg[month_key].extend([a.performance_value for a in attempts])

        # Convert to actual averages
        monthly_avg = {k: statistics.mean(v) for k, v in monthly_avg.items() if v}

        # Look for plateaus followed by jumps
        months = sorted(monthly_avg.keys())
        for i in range(3, len(months)):
            # Check if previous 3 months were similar (plateau)
            prev_3 = [monthly_avg[months[j]] for j in range(i-3, i)]
            current = monthly_avg[months[i]]

            prev_avg = statistics.mean(prev_3)
            prev_std = statistics.stdev(prev_3) if len(prev_3) > 1 else 0

            # Plateau: low std in previous months
            # Break: current significantly higher
            if prev_std < 0.3 and current > prev_avg + 0.5:
                # Find an attempt from this month to attach milestone to
                month_attempts = [a for a in self.attempts
                                 if a.date.strftime('%Y-%m') == months[i]]
                if month_attempts:
                    milestones.append(Milestone(
                        type=MilestoneType.PLATEAU_BROKEN,
                        dive_code=None,
                        height=None,
                        date=month_attempts[-1].date,
                        title="Plateau broken",
                        narrative=f"After 3 months of steady performance around "
                                 f"{self._performance_name_from_value(prev_avg)}, "
                                 f"you broke through to {self._performance_name_from_value(current)} average. "
                                 f"Growth isn't linear. Keep going.",
                        emoji="📈",
                        significance=5,
                    ))

        return milestones

    def _performance_name(self, perf: str) -> str:
        """Convert performance code to name."""
        return {
            'F': 'Failed',
            'B': 'Bad',
            'M': 'Medium',
            'G': 'Good',
            'P': 'Perfect'
        }.get(perf, perf)

    def _performance_name_from_value(self, value: float) -> str:
        """Convert calibrated /10 performance to approximate name."""
        if value >= 8.5:
            return "Good-Perfect"
        elif value >= 5.75:
            return "Medium-Good"
        elif value >= 3.25:
            return "Bad-Medium"
        else:
            return "struggling"


class JourneyNarrator:
    """
    Transforms milestones into a coherent narrative of growth.

    This is what makes the tool feel human.
    """

    def __init__(self, milestones: List[Milestone]):
        self.milestones = sorted(milestones, key=lambda m: m.date)

    def generate_journey_summary(self) -> Dict[str, Any]:
        """Generate a narrative summary of the diver's journey."""
        if not self.milestones:
            return {"narrative": "Your journey is just beginning. Every expert was once a beginner."}

        # Group milestones by significance
        breakthroughs = [m for m in self.milestones if m.significance >= 4]
        recent = self.milestones[-10:]

        # Find patterns
        most_persistent_dive = self._find_most_persistent_dive()
        biggest_growth = self._find_biggest_growth()

        return {
            "total_milestones": len(self.milestones),
            "breakthroughs": len(breakthroughs),
            "most_recent": recent[-1].to_dict() if recent else None,
            "most_significant": max(self.milestones, key=lambda m: m.significance).to_dict(),
            "most_persistent_dive": most_persistent_dive,
            "biggest_growth_story": biggest_growth,
            "timeline": [m.to_dict() for m in self.milestones],
        }

    def _find_most_persistent_dive(self) -> Optional[Dict[str, Any]]:
        """Find the dive where the diver showed most persistence."""
        breakthroughs = [m for m in self.milestones
                        if m.type == MilestoneType.BREAKTHROUGH]

        if not breakthroughs:
            return None

        # Most failures before success
        most_persistent = max(breakthroughs, key=lambda m: m.failures_before)

        return {
            "dive_code": most_persistent.dive_code,
            "height": most_persistent.height,
            "failures_before_success": most_persistent.failures_before,
            "narrative": most_persistent.narrative,
        }

    def _find_biggest_growth(self) -> Optional[Dict[str, Any]]:
        """Find the most significant growth story."""
        # Look for dives that went from FIRST_ATTEMPT to CONSISTENCY_ACHIEVED
        dive_journeys: Dict[Tuple[str, str], List[Milestone]] = defaultdict(list)

        for m in self.milestones:
            if m.dive_code:
                dive_journeys[(m.dive_code, m.height)].append(m)

        # Find complete journeys
        complete_journeys = []
        for (code, height), journey in dive_journeys.items():
            types = [m.type for m in journey]
            if (MilestoneType.FIRST_ATTEMPT in types and
                (MilestoneType.CONSISTENCY_ACHIEVED in types or
                 MilestoneType.PERFECT_STREAK in types)):
                complete_journeys.append({
                    "dive_code": code,
                    "height": height,
                    "milestones": len(journey),
                    "journey": [m.to_dict() for m in journey],
                })

        if complete_journeys:
            return max(complete_journeys, key=lambda j: j["milestones"])

        return None

    def generate_dive_story(self, dive_code: str, height: str) -> Dict[str, Any]:
        """Generate the complete story of a specific dive."""
        relevant = [m for m in self.milestones
                   if m.dive_code == dive_code and m.height == height]

        if not relevant:
            return {
                "dive_code": dive_code,
                "height": height,
                "narrative": "No story yet. The first chapter awaits.",
                "milestones": [],
            }

        # Build narrative
        chapters = []
        for m in relevant:
            chapters.append({
                "date": m.date.isoformat(),
                "title": m.title,
                "narrative": m.narrative,
                "emoji": m.emoji,
            })

        # Opening and closing
        first = relevant[0]
        last = relevant[-1]

        opening = f"Your {dive_code} journey from {height} began on {first.date.strftime('%B %d, %Y')}."

        # Craft closing based on current state
        if last.type == MilestoneType.CONSISTENCY_ACHIEVED:
            closing = "This dive is now yours. Competition-ready."
        elif last.type == MilestoneType.BREAKTHROUGH:
            closing = "The breakthrough happened. Now build on it."
        elif last.type == MilestoneType.FIRST_SUCCESS:
            closing = "The first success is done. The rest is practice."
        else:
            closing = "The story continues."

        return {
            "dive_code": dive_code,
            "height": height,
            "opening": opening,
            "closing": closing,
            "chapters": chapters,
            "milestones_count": len(relevant),
        }
