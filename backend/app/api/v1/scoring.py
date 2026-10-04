"""API endpoints for performance scoring in competitions"""

from typing import List, Dict, Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from decimal import Decimal
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.write_guard import require_owner_for_mutation
from app.services.performance_scorer import PerformanceScorer
from app.models.dive import Dive

router = APIRouter(prefix="/scoring", tags=["scoring"], dependencies=[Depends(require_owner_for_mutation)])


class JudgeScoreInput(BaseModel):
    """Input for adding a judge score"""
    judge_number: int = Field(1, ge=1, le=11, description="Judge position (1-11)")
    score: float = Field(..., ge=0.0, le=10.0, description="Score (0-10 in 0.5 increments)")
    judge_name: Optional[str] = None


class JudgePanelCreate(BaseModel):
    """Input for creating a judge panel"""
    dive_id: int
    judge_count: int = Field(7, ge=1, description="Number of judges (7 or 11)")
    panel_type: str = Field("execution", description="Panel type: 'execution' or 'synchronization'")
    event_id: Optional[int] = None


@router.post("/panels")
async def create_judge_panel(
    panel_data: JudgePanelCreate,
    db: Session = Depends(get_db),
) -> Dict:
    """
    Create a new judge panel for a dive.

    Example: POST /api/v1/scoring/panels
    ```json
    {
      "dive_id": 123,
      "judge_count": 7,
      "panel_type": "execution"
    }
    ```
    """
    try:
        scorer = PerformanceScorer(db)
        panel = scorer.create_judge_panel(
            dive_id=panel_data.dive_id,
            judge_count=panel_data.judge_count,
            panel_type=panel_data.panel_type,
            event_id=panel_data.event_id,
        )
        return {
            "panel_id": panel.id,
            "dive_id": panel.dive_id,
            "judge_count": panel.judge_count,
            "panel_type": panel.panel_type,
            "created_at": panel.created_at.isoformat(),
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/panels/{panel_id}/scores")
async def add_judge_score(
    panel_id: int,
    score_data: JudgeScoreInput,
    db: Session = Depends(get_db),
) -> Dict:
    """
    Add a judge's score to a panel.

    Example: POST /api/v1/scoring/panels/1/scores
    ```json
    {
      "judge_number": 1,
      "score": 8.5,
      "judge_name": "John Smith"
    }
    ```
    """
    try:
        scorer = PerformanceScorer(db)
        judge_score = scorer.add_judge_score(
            panel_id=panel_id,
            judge_number=score_data.judge_number,
            score=score_data.score,
            judge_name=score_data.judge_name,
        )
        return {
            "score_id": judge_score.id,
            "panel_id": panel_id,
            "judge_number": judge_score.judge_number,
            "score": float(judge_score.score),
            "judge_name": judge_score.judge_name,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/panels/{panel_id}/summary")
async def get_panel_summary(
    panel_id: int,
    db: Session = Depends(get_db),
) -> Dict:
    """
    Get a summary of a judge panel with all scores.

    Example: GET /api/v1/scoring/panels/1/summary
    """
    try:
        scorer = PerformanceScorer(db)
        summary = scorer.get_panel_summary(panel_id)
        return summary
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/panels/{panel_id}/calculate")
async def calculate_panel_average(
    panel_id: int,
    db: Session = Depends(get_db),
) -> Dict:
    """
    Calculate the panel's average score using FINA rules.

    FINA Rules:
    - Sort all scores
    - Drop 2 lowest and 2 highest
    - Average the remaining 3 scores
    - Result in 0.5 increments

    Example: POST /api/v1/scoring/panels/1/calculate
    """
    try:
        scorer = PerformanceScorer(db)
        average = scorer.calculate_panel_average(panel_id)

        if average is None:
            raise HTTPException(
                status_code=400,
                detail="Panel does not have all required scores for calculation"
            )

        return {
            "panel_id": panel_id,
            "panel_average": average,
            "description": "Average calculated using FINA rules: drop 2 high, 2 low, average remaining 3"
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/dives/{dive_id}/final-score")
async def calculate_final_score(
    dive_id: int,
    panel_id: int,
    db: Session = Depends(get_db),
) -> Dict:
    """
    Calculate final score for a dive: (execution_score / 10) × DD

    Example: POST /api/v1/scoring/dives/123/final-score?panel_id=1
    """
    try:
        scorer = PerformanceScorer(db)
        final_score = scorer.calculate_final_score(dive_id, panel_id)

        if final_score is None:
            raise HTTPException(
                status_code=400,
                detail="Cannot calculate final score: missing panel average or DD value"
            )

        # Get dive and panel info
        dive = db.query(Dive).filter(Dive.id == dive_id).first()
        if not dive:
            raise HTTPException(status_code=404, detail="Dive not found")

        summary = scorer.get_panel_summary(panel_id)

        return {
            "dive_id": dive_id,
            "dive_code": dive.dive_code,
            "height": dive.height,
            "panel_id": panel_id,
            "execution_score": summary["panel_average"],
            "dd": 0.0,  # Will be populated from dive.official_dd or calculated
            "final_score": float(final_score),
            "formula": "(execution_score / 10) × DD"
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rank")
async def rank_dives(
    dive_ids: List[int],
    db: Session = Depends(get_db),
) -> List[Dict]:
    """
    Rank dives by final score.

    Example: POST /api/v1/scoring/rank
    ```json
    {
      "dive_ids": [1, 2, 3, 4, 5]
    }
    ```

    Returns: Sorted list with rank, dive code, execution score, DD, and final score
    """
    try:
        scorer = PerformanceScorer(db)

        # Get dives
        dives = db.query(Dive).filter(Dive.id.in_(dive_ids)).all()
        if not dives:
            raise HTTPException(status_code=404, detail="No dives found")

        # Rank them
        rankings = scorer.rank_dives(dives, include_dd=True)
        return rankings
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
