"""Performance Scorer service - calculates performance scores from judge ratings"""

from typing import Optional, Dict, List, Tuple
from decimal import Decimal
from dataclasses import dataclass
from sqlalchemy.orm import Session

from app.models.judge_score import JudgePanel, JudgeScore
from app.models.dive import Dive
from app.services.dd_calculator import DDCalculator


@dataclass
class JudgeRating:
    """A single judge's rating for a dive"""
    judge_id: str
    score: Decimal  # 0.0 to 10.0
    notes: Optional[str] = None


class PerformanceScorer:
    """Scores dives based on judge ratings and official FINA rules"""

    # Official FINA judging rules
    VALID_JUDGE_COUNTS = [7, 11]  # 7 for individual, 11 for synchronized
    SCORE_MIN = Decimal("0.0")
    SCORE_MAX = Decimal("10.0")

    def __init__(self, db: Optional[Session] = None):
        """Initialize scorer with optional database connection"""
        self.db = db
        self.dd_calculator = DDCalculator(db) if db else None

    def validate_judge_score(self, score: float | Decimal) -> Tuple[bool, Optional[str]]:
        """
        Validate a judge's score per FINA rules.

        Rules:
        - Must be between 0 and 10 inclusive
        - Must be in 0.5 increments (0.0, 0.5, 1.0, 1.5, ..., 10.0)

        Returns: (is_valid, error_message)
        """
        try:
            score_float = float(score)
        except (ValueError, TypeError):
            return False, "Score must be numeric"

        if score_float < 0 or score_float > 10:
            return False, f"Score must be between 0 and 10, got {score_float}"

        # Check 0.5 increment: multiply by 2, should be integer
        if (score_float * 2) % 1 != 0:
            return False, f"Score must be in 0.5 increments, got {score_float}"

        return True, None

    def calculate_aggregate_score(self, ratings: List[JudgeRating]) -> Tuple[Decimal, Dict]:
        """
        Calculate aggregate score from multiple judge ratings using FINA rules.

        FINA rules (7-judge panel):
        - Sort all 7 scores
        - Drop 2 lowest and 2 highest
        - Average the remaining 3 middle scores
        - Result in 0.5 increments (0.0-10.0)

        For 11-judge synchronized panels, same rules apply.

        Args:
            ratings: List of judge ratings

        Returns:
            (aggregate_score, details_dict)
        """
        if not ratings:
            return Decimal("0.0"), {"error": "No ratings provided"}

        judge_count = len(ratings)
        if judge_count not in self.VALID_JUDGE_COUNTS:
            return Decimal("0.0"), {
                "error": f"Expected {self.VALID_JUDGE_COUNTS[0]} or {self.VALID_JUDGE_COUNTS[1]} judges, got {judge_count}"
            }

        # Extract scores
        scores = [Decimal(str(rating.score)) for rating in ratings]

        # Sort to drop highest and lowest
        sorted_scores = sorted(scores)

        # Drop 2 lowest and 2 highest (for both 7 and 11 judge panels)
        trimmed_scores = sorted_scores[2:-2]

        if not trimmed_scores:
            return Decimal("0.0"), {"error": "Not enough scores to calculate aggregate"}

        # Calculate average
        aggregate = sum(trimmed_scores) / len(trimmed_scores)

        # Round to 0.5
        aggregate_rounded = (aggregate * 2).quantize(Decimal("1")) / 2

        return aggregate_rounded, {
            "judge_count": len(ratings),
            "scores": [float(s) for s in scores],
            "min_score": float(sorted_scores[0]),
            "max_score": float(sorted_scores[-1]),
            "dropped_low": [float(s) for s in sorted_scores[:2]],
            "dropped_high": [float(s) for s in sorted_scores[-2:]],
            "trimmed_scores": [float(s) for s in trimmed_scores],
            "aggregate_score": float(aggregate_rounded),
        }

    def create_judge_panel(
        self,
        dive_id: int,
        judge_count: int = 7,
        panel_type: str = "execution",
        event_id: Optional[int] = None,
    ) -> JudgePanel:
        """
        Create a new judge panel for a dive.

        Args:
            dive_id: ID of the dive being scored
            judge_count: Number of judges (7 or 11)
            panel_type: Type of panel ('execution' or 'synchronization')
            event_id: Optional event ID for context

        Returns: Created JudgePanel instance
        """
        if not self.db:
            raise ValueError("Database connection required")

        if judge_count not in self.VALID_JUDGE_COUNTS:
            raise ValueError(f"judge_count must be {self.VALID_JUDGE_COUNTS}, got {judge_count}")

        # Verify dive exists
        dive = self.db.query(Dive).filter(Dive.id == dive_id).first()
        if not dive:
            raise ValueError(f"Dive {dive_id} not found")

        panel = JudgePanel(
            dive_id=dive_id,
            event_id=event_id,
            judge_count=judge_count,
            panel_type=panel_type,
        )
        self.db.add(panel)
        self.db.commit()
        self.db.refresh(panel)
        return panel

    def add_judge_score(
        self,
        panel_id: int,
        judge_number: int,
        score: float | Decimal,
        judge_name: Optional[str] = None,
    ) -> JudgeScore:
        """
        Add a judge's score to a panel.

        Args:
            panel_id: ID of the judge panel
            judge_number: Judge's position (1-7 or 1-11)
            score: Score value (0-10 in 0.5 increments)
            judge_name: Optional judge name

        Returns: Created JudgeScore instance
        """
        if not self.db:
            raise ValueError("Database connection required")

        # Validate score
        is_valid, error = self.validate_judge_score(score)
        if not is_valid:
            raise ValueError(error)

        # Get panel
        panel = self.db.query(JudgePanel).filter(JudgePanel.id == panel_id).first()
        if not panel:
            raise ValueError(f"Panel {panel_id} not found")

        # Validate judge_number is in range
        if judge_number < 1 or judge_number > panel.judge_count:
            raise ValueError(
                f"judge_number must be between 1 and {panel.judge_count}, got {judge_number}"
            )

        # Check for duplicate
        existing = (
            self.db.query(JudgeScore)
            .filter(JudgeScore.panel_id == panel_id, JudgeScore.judge_number == judge_number)
            .first()
        )
        if existing:
            # Update existing score
            existing.score = Decimal(str(score))
            existing.judge_name = judge_name
            self.db.commit()
            self.db.refresh(existing)
            return existing

        # Create new score
        judge_score = JudgeScore(
            panel_id=panel_id,
            judge_number=judge_number,
            score=Decimal(str(score)),
            judge_name=judge_name,
        )
        self.db.add(judge_score)
        self.db.commit()
        self.db.refresh(judge_score)
        return judge_score

    def calculate_panel_average(self, panel_id: int) -> Optional[float]:
        """
        Calculate the panel's average score using FINA rules.

        Rules:
        - Must have exactly judge_count scores
        - Sort scores
        - Drop 2 lowest and 2 highest
        - Average remaining scores
        - Result rounded to 0.5

        Args:
            panel_id: ID of the judge panel

        Returns: Panel average (0-10 in 0.5 increments) or None if not calculable
        """
        if not self.db:
            raise ValueError("Database connection required")

        panel = self.db.query(JudgePanel).filter(JudgePanel.id == panel_id).first()
        if not panel:
            raise ValueError(f"Panel {panel_id} not found")

        # Check if panel has all required scores
        scores = self.db.query(JudgeScore).filter(JudgeScore.panel_id == panel_id).all()
        if len(scores) != panel.judge_count:
            return None

        # Get numeric values and sort
        score_values = sorted([float(s.score) for s in scores])

        # Drop 2 lowest and 2 highest
        remaining = score_values[2:-2]

        if not remaining:
            return None

        # Calculate average
        average = sum(remaining) / len(remaining)

        # Round to nearest 0.5
        rounded = round(average * 2) / 2

        # Update panel with calculated average
        panel.panel_average = Decimal(str(rounded))
        self.db.commit()

        return rounded

    def calculate_final_score(
        self,
        dive_id: int,
        panel_id: int,
        aggregate_performance: Optional[Decimal] = None,
        dd_value: Optional[Decimal] = None,
    ) -> Optional[Decimal]:
        """
        Calculate final dive score: (execution_score / 10) × DD

        Args:
            dive_id: ID of the dive (used if aggregate_performance not provided)
            panel_id: ID of the judge panel (used if aggregate_performance not provided)
            aggregate_performance: Optional pre-calculated aggregate performance (0-10)
            dd_value: Optional pre-calculated DD value

        Returns:
            Final score or None if calculation not possible
        """
        # Get execution score
        if aggregate_performance is not None:
            execution_score = Decimal(str(aggregate_performance))
        else:
            if not self.db:
                raise ValueError("Database connection required")

            # Calculate from panel
            panel = self.db.query(JudgePanel).filter(JudgePanel.id == panel_id).first()
            if not panel:
                raise ValueError(f"Panel {panel_id} not found")

            if panel.panel_average is None:
                # Try to calculate it
                avg = self.calculate_panel_average(panel_id)
                if avg is None:
                    return None
                execution_score = Decimal(str(avg))
            else:
                execution_score = panel.panel_average

        # Get DD value
        if dd_value is not None:
            dd = Decimal(str(dd_value))
        else:
            if not self.dd_calculator:
                raise ValueError("DDCalculator not available")

            # Get dive and its DD
            dive = self.db.query(Dive).filter(Dive.id == dive_id).first()
            if not dive:
                raise ValueError(f"Dive {dive_id} not found")

            # Get DD value
            dd_lookup = self.dd_calculator.lookup_dd(dive.dive_code, dive.height)
            if dd_lookup is None:
                # Try to estimate DD
                dd_lookup = self.dd_calculator.estimate_dd_from_components(
                    dive.dive_code, dive.height
                )
                if dd_lookup is None:
                    return None

            dd = Decimal(str(dd_lookup))

        # Calculate final score
        final_score = (execution_score / Decimal("10.0")) * dd
        return final_score

    def rank_dives(
        self,
        dives: List[Dive] | List[Dict],
        include_dd: bool = True,
    ) -> List[Dict]:
        """
        Rank dives by final score.

        Args:
            dives: List of Dive objects or dicts with dive_code and final_score
            include_dd: Whether to include DD in results

        Returns:
            Sorted list with rank added
        """
        results = []

        # Handle dict input (legacy)
        if dives and isinstance(dives[0], dict):
            results = dives.copy()
        # Handle Dive objects
        elif self.db and self.dd_calculator:
            for dive in dives:
                # Get most recent panel for this dive
                panel = (
                    self.db.query(JudgePanel)
                    .filter(JudgePanel.dive_id == dive.id)
                    .order_by(JudgePanel.created_at.desc())
                    .first()
                )

                if not panel or panel.panel_average is None:
                    # Can't rank this dive
                    continue

                execution_score = float(panel.panel_average)
                dd_value = self.dd_calculator.lookup_dd(dive.dive_code, dive.height)

                if dd_value is None:
                    continue

                final_score = (execution_score / 10) * float(dd_value)

                result = {
                    "dive_id": dive.id,
                    "dive_code": dive.dive_code,
                    "height": dive.height,
                    "execution_score": execution_score,
                    "final_score": final_score,
                }

                if include_dd:
                    result["dd"] = float(dd_value)

                results.append(result)

        # Sort by final score descending
        results.sort(key=lambda x: x["final_score"], reverse=True)

        # Add rank
        for i, result in enumerate(results, 1):
            result["rank"] = i

        return results

    def get_panel_summary(self, panel_id: int) -> Dict:
        """
        Get a summary of a judge panel.

        Returns: Dict with panel info, scores, and average
        """
        if not self.db:
            raise ValueError("Database connection required")

        panel = self.db.query(JudgePanel).filter(JudgePanel.id == panel_id).first()
        if not panel:
            raise ValueError(f"Panel {panel_id} not found")

        scores = self.db.query(JudgeScore).filter(JudgeScore.panel_id == panel_id).all()

        return {
            "panel_id": panel_id,
            "dive_id": panel.dive_id,
            "judge_count": panel.judge_count,
            "panel_type": panel.panel_type,
            "scores": [
                {
                    "judge_number": s.judge_number,
                    "judge_name": s.judge_name,
                    "score": float(s.score),
                }
                for s in sorted(scores, key=lambda x: x.judge_number)
            ],
            "panel_average": float(panel.panel_average) if panel.panel_average else None,
        }

    def calculate_consistency(self, scores: List[Decimal]) -> Dict:
        """
        Calculate consistency metrics for a series of scores.

        Returns: Dict with variance, std_dev, coefficient_of_variation
        """
        if not scores or len(scores) < 2:
            return {"error": "Need at least 2 scores"}

        scores_float = [float(s) for s in scores]
        mean = sum(scores_float) / len(scores_float)

        # Variance
        variance = sum((x - mean) ** 2 for x in scores_float) / len(scores_float)

        # Std dev
        std_dev = variance ** 0.5

        # Coefficient of variation
        cv = (std_dev / mean) if mean > 0 else 0

        return {
            "mean": mean,
            "variance": variance,
            "std_dev": std_dev,
            "coefficient_of_variation": cv,
            "min": min(scores_float),
            "max": max(scores_float),
        }
