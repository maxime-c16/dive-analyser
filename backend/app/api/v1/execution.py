"""API endpoints for execution analysis and fault detection"""

from typing import List, Dict, Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.write_guard import require_owner_for_mutation
from app.services.execution_fault_detector import ExecutionFaultDetector, ExecutionMetrics
from app.models.dive import Dive
from app.models.session import Session as SessionModel
from app.models.execution_fault import ExecutionFault
from app.services.workspace_access import require_workspace_read


router = APIRouter(prefix="/execution", tags=["execution"], dependencies=[Depends(require_owner_for_mutation), Depends(require_workspace_read)])


class ExecutionMetricsInput(BaseModel):
    """Input model for execution metrics"""
    phase: int = Field(..., ge=1, le=2, description="Phase number (1 or 2)")
    rotation_degrees: float = Field(0.0, ge=0.0, description="Rotation in degrees")
    entry_distance_from_center: float = Field(0.0, ge=0.0, description="Entry distance from center in cm")
    entry_angle_degrees: float = Field(0.0, ge=0.0, le=90.0, description="Entry angle in degrees")
    height_achieved: float = Field(100.0, ge=0.0, description="Height achieved in cm")
    spin_consistency: float = Field(0.8, ge=0.0, le=1.0, description="Spin consistency 0-1.0")
    overall_score: float = Field(7.0, ge=0.0, le=10.0, description="Overall phase score 0-10")


class ExecutionAnalysisRequest(BaseModel):
    """Request for dive execution analysis"""
    dive_id: int = Field(..., description="ID of the dive to analyze")
    metrics: Optional[Dict] = Field(None, description="Optional execution metrics")


class FaultResponse(BaseModel):
    """Response model for a single fault"""
    fault_id: Optional[int] = None
    fault_code: str
    severity: str
    phase: Optional[int] = None
    description: str
    coaching_recommendation: str
    fina_category: str
    points_deducted: float


class ExecutionAnalysisResponse(BaseModel):
    """Response model for execution analysis"""
    dive_id: int
    execution_score: float
    adjusted_score: float
    points_deducted: float
    faults: List[FaultResponse]
    phase1_analysis: Dict
    phase2_analysis: Dict
    patterns: Dict


class SessionAnalysisResponse(BaseModel):
    """Response for session-wide analysis"""
    session_id: int
    total_dives: int
    total_faults: int
    total_points_deducted: float
    average_faults_per_dive: float
    fault_distribution: Dict[str, int]
    severity_distribution: Dict[str, int]
    common_faults: List[Dict]
    systematic_issues: List[str]


@router.post("/analyze/{dive_id}")
def analyze_dive_execution(
    dive_id: int,
    metrics: Optional[Dict] = None,
    db: Session = Depends(get_db),
) -> Dict:
    """
    Analyze execution of a specific dive and detect faults.

    Example: POST /api/v1/execution/analyze/123
    ```json
    {
      "metrics": {
        "phase1_rotation": 360,
        "phase1_entry_distance": 5,
        "phase2_rotation": 360,
        "phase2_entry_distance": 8
      }
    }
    ```
    """
    try:
        detector = ExecutionFaultDetector(db)
        analysis = detector.analyze_dive_execution(dive_id, metrics)

        # Convert ExecutionFault objects to dicts
        faults = [
            {
                "fault_id": f.id,
                "fault_code": f.fault_code,
                "severity": f.severity,
                "phase": f.phase,
                "description": f.description,
                "coaching_recommendation": f.coaching_recommendation,
                "fina_category": f.fina_category,
                "points_deducted": float(f.points_deducted or 0),
            }
            for f in analysis["faults"]
        ]

        # Convert phase analysis faults to dicts
        phase1_faults_dicts = [
            {
                "fault_id": f.id,
                "fault_code": f.fault_code,
                "severity": f.severity,
                "phase": f.phase,
                "description": f.description,
                "coaching_recommendation": f.coaching_recommendation,
                "fina_category": f.fina_category,
                "points_deducted": float(f.points_deducted or 0),
            }
            for f in analysis["phase1_analysis"]["faults"]
        ]

        phase2_faults_dicts = [
            {
                "fault_id": f.id,
                "fault_code": f.fault_code,
                "severity": f.severity,
                "phase": f.phase,
                "description": f.description,
                "coaching_recommendation": f.coaching_recommendation,
                "fina_category": f.fina_category,
                "points_deducted": float(f.points_deducted or 0),
            }
            for f in analysis["phase2_analysis"]["faults"]
        ]

        return {
            "dive_id": analysis["dive_id"],
            "execution_score": analysis["execution_score"],
            "adjusted_score": analysis["adjusted_score"],
            "points_deducted": analysis["points_deducted"],
            "faults": faults,
            "phase1_analysis": {
                "faults": phase1_faults_dicts,
                "count": analysis["phase1_analysis"]["count"],
            },
            "phase2_analysis": {
                "faults": phase2_faults_dicts,
                "count": analysis["phase2_analysis"]["count"],
            },
            "patterns": analysis["patterns"],
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analyze-session/{session_id}")
def analyze_session_execution(
    session_id: int,
    db: Session = Depends(get_db),
) -> Dict:
    """
    Analyze execution across all dives in a session.

    Example: POST /api/v1/execution/analyze-session/456
    """
    try:
        # Get session
        session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
        if not session:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

        # Get all dives in session
        dives = db.query(Dive).filter(Dive.session_id == session_id).all()

        if not dives:
            return {
                "session_id": session_id,
                "total_dives": 0,
                "total_faults": 0,
                "total_points_deducted": 0.0,
                "average_faults_per_dive": 0.0,
                "fault_distribution": {},
                "severity_distribution": {"HIGH": 0, "MEDIUM": 0, "LOW": 0},
                "common_faults": [],
                "systematic_issues": [],
            }

        detector = ExecutionFaultDetector(db)
        total_faults = 0
        total_points = 0.0
        fault_counts = {}
        severity_counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}

        # Analyze each dive
        for dive in dives:
            faults = db.query(ExecutionFault).filter(ExecutionFault.dive_id == dive.id).all()

            for fault in faults:
                total_faults += 1
                total_points += float(fault.points_deducted or 0)
                fault_counts[fault.fault_code] = fault_counts.get(fault.fault_code, 0) + 1
                severity_counts[fault.severity] += 1

        # Find common faults
        common_faults = sorted(
            [{"fault_code": code, "count": count} for code, count in fault_counts.items()],
            key=lambda x: x["count"],
            reverse=True,
        )[:5]

        # Detect systematic issues
        systematic_issues = []
        if total_faults > 0:
            avg_faults = total_faults / len(dives)
            if avg_faults >= 2:
                systematic_issues.append("High fault frequency (2+ per dive)")
            if severity_counts["HIGH"] / total_faults > 0.3:
                systematic_issues.append("High proportion of critical faults")
            if fault_counts.get("UR", 0) + fault_counts.get("OR", 0) > total_faults * 0.4:
                systematic_issues.append("Rotation issues are primary concern")

        return {
            "session_id": session_id,
            "total_dives": len(dives),
            "total_faults": total_faults,
            "total_points_deducted": total_points,
            "average_faults_per_dive": total_faults / len(dives) if dives else 0.0,
            "fault_distribution": fault_counts,
            "severity_distribution": severity_counts,
            "common_faults": common_faults,
            "systematic_issues": systematic_issues,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/fault-categories")
async def get_fault_categories() -> Dict:
    """
    Get all available fault categories and their definitions.

    Example: GET /api/v1/execution/fault-categories
    """
    detector = ExecutionFaultDetector(None)

    categories = {}
    for fault_code, fault_info in detector.FAULT_CODES.items():
        thresholds = detector.FAULT_THRESHOLDS.get(fault_code, {})
        categories[fault_code] = {
            "name": fault_info["name"],
            "severity_weight": fault_info["severity_weight"],
            "thresholds": thresholds,
            "fina_category": detector._get_fina_category(fault_code),
        }

    return {
        "fault_categories": categories,
        "severity_levels": {
            "HIGH": {"points_deducted": 1.5, "description": "Major technical issue"},
            "MEDIUM": {"points_deducted": 0.75, "description": "Moderate technical issue"},
            "LOW": {"points_deducted": 0.25, "description": "Minor technical issue"},
        },
    }


@router.get("/dive/{dive_id}/faults")
def get_dive_faults(
    dive_id: int,
    db: Session = Depends(get_db),
) -> Dict:
    """
    Get all faults detected for a specific dive.

    Example: GET /api/v1/execution/dive/123/faults
    """
    try:
        # Verify dive exists
        dive = db.query(Dive).filter(Dive.id == dive_id).first()
        if not dive:
            raise HTTPException(status_code=404, detail=f"Dive {dive_id} not found")

        # Get all faults
        faults = db.query(ExecutionFault).filter(ExecutionFault.dive_id == dive_id).all()

        detector = ExecutionFaultDetector(db)
        summary = detector.get_fault_summary_for_dive(dive_id)

        return summary
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/pattern-analysis/{session_id}")
def analyze_session_patterns(
    session_id: int,
    db: Session = Depends(get_db),
) -> Dict:
    """
    Analyze systematic fault patterns across a session.

    Example: POST /api/v1/execution/pattern-analysis/456
    """
    try:
        # Get session
        session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
        if not session:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

        # Get all faults for session
        dives = db.query(Dive).filter(Dive.session_id == session_id).all()
        all_faults = []

        for dive in dives:
            faults = db.query(ExecutionFault).filter(ExecutionFault.dive_id == dive.id).all()
            all_faults.extend(faults)

        # Analyze patterns
        detector = ExecutionFaultDetector(db)
        patterns = detector.detect_systematic_patterns(session_id, all_faults)

        # Additional pattern analysis
        phase_1_faults = sum(1 for f in all_faults if f.phase == 1)
        phase_2_faults = sum(1 for f in all_faults if f.phase == 2)

        fault_sequences = {}
        for dive in dives:
            faults = db.query(ExecutionFault).filter(ExecutionFault.dive_id == dive.id).all()
            if faults:
                sequence = tuple(sorted([f.fault_code for f in faults]))
                fault_sequences[sequence] = fault_sequences.get(sequence, 0) + 1

        # Find most common sequence
        most_common_sequence = max(fault_sequences.items(), key=lambda x: x[1])[0] if fault_sequences else None

        return {
            "session_id": session_id,
            "pattern_analysis": patterns,
            "phase_distribution": {
                "phase_1_faults": phase_1_faults,
                "phase_2_faults": phase_2_faults,
            },
            "fault_sequences": fault_sequences,
            "most_common_sequence": list(most_common_sequence) if most_common_sequence else None,
            "coaching_focus": _generate_coaching_focus(patterns, fault_sequences),
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/coaching/{dive_id}")
def get_coaching_recommendations(
    dive_id: int,
    db: Session = Depends(get_db),
) -> Dict:
    """
    Get coaching recommendations based on detected faults.

    Example: GET /api/v1/execution/coaching/123
    """
    try:
        # Verify dive exists
        dive = db.query(Dive).filter(Dive.id == dive_id).first()
        if not dive:
            raise HTTPException(status_code=404, detail=f"Dive {dive_id} not found")

        # Get all faults for dive
        faults = db.query(ExecutionFault).filter(ExecutionFault.dive_id == dive_id).all()

        if not faults:
            return {
                "dive_id": dive_id,
                "total_faults": 0,
                "coaching_recommendations": [],
                "primary_focus": "Maintain current execution level",
                "secondary_focus": [],
                "practice_suggestions": ["Continue working on consistency", "Film and analyze regularly"],
            }

        # Group faults by severity
        by_severity = {"HIGH": [], "MEDIUM": [], "LOW": []}
        for fault in faults:
            by_severity[fault.severity].append(fault)

        # Generate recommendations
        recommendations = []
        primary_focus = None
        secondary_focus = []

        # High severity faults
        if by_severity["HIGH"]:
            primary_focus = by_severity["HIGH"][0].coaching_recommendation
            recommendations.append({
                "severity": "HIGH",
                "faults": [f.fault_code for f in by_severity["HIGH"]],
                "recommendation": primary_focus,
                "priority": "Address immediately",
            })

        # Medium severity faults
        if by_severity["MEDIUM"]:
            for fault in by_severity["MEDIUM"]:
                secondary_focus.append(fault.coaching_recommendation)
                recommendations.append({
                    "severity": "MEDIUM",
                    "fault": fault.fault_code,
                    "recommendation": fault.coaching_recommendation,
                    "priority": "Address in next session",
                })

        # Practice suggestions
        practice_suggestions = _generate_practice_suggestions(faults)

        return {
            "dive_id": dive_id,
            "total_faults": len(faults),
            "coaching_recommendations": recommendations,
            "primary_focus": primary_focus or "Execution is satisfactory",
            "secondary_focus": secondary_focus,
            "practice_suggestions": practice_suggestions,
            "estimated_improvement": _estimate_improvement(faults),
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _generate_coaching_focus(patterns: Dict, fault_sequences: Dict) -> str:
    """Generate coaching focus based on patterns"""
    if not patterns["fault_codes"]:
        return "Execution is satisfactory - maintain current training approach"

    primary = patterns["primary_issue"]

    if patterns["severity_distribution"]["HIGH"] > 0:
        return f"Focus on addressing {primary} - this is limiting performance significantly"
    elif patterns["is_systematic"]:
        return f"Systematic {primary} issue detected - requires targeted technique work"
    else:
        return "Continue building consistency - faults appear random"


def _generate_practice_suggestions(faults: List[ExecutionFault]) -> List[str]:
    """Generate practice suggestions based on faults"""
    suggestions = []

    fault_codes = set(f.fault_code for f in faults)

    if "UR" in fault_codes or "OR" in fault_codes:
        suggestions.append("Dryland rotation practice - focus on consistent spin rate")
        suggestions.append("Film rotation angles and count rotations frame-by-frame")

    if "LE" in fault_codes or "EE" in fault_codes:
        suggestions.append("Practice entry position and timing")
        suggestions.append("Work on entry alignment relative to board/platform")

    if "LH" in fault_codes:
        suggestions.append("Strengthen takeoff mechanics with board repetitions")
        suggestions.append("Increase hurdle power and approach consistency")

    if "SA" in fault_codes:
        suggestions.append("Approach-only drills to build consistency")
        suggestions.append("Record approach technique and compare with video analysis")

    if "SK" in fault_codes:
        suggestions.append("Practice centered entry - use pool lane markers as guides")

    if len(suggestions) == 0:
        suggestions.append("Continue practicing this dive regularly")
        suggestions.append("Film practice sessions for periodic analysis")

    return suggestions


def _estimate_improvement(faults: List[ExecutionFault]) -> Dict:
    """Estimate potential score improvement if faults are fixed"""
    total_points_deducted = sum(float(f.points_deducted or 0) for f in faults)

    return {
        "current_points_deducted": total_points_deducted,
        "potential_improvement_points": total_points_deducted,
        "improvement_percentage": min(100, (total_points_deducted / 10.0) * 100),
        "estimated_new_score": "Full execution score if all faults eliminated",
    }
