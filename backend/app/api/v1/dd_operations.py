"""API endpoints for DD (Difficulty Degree) operations"""

from typing import List, Dict
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from decimal import Decimal

from app.database import get_db
from app.services.dd_calculator import DDCalculator
from app.services.dd_lookup_manager import DDLookupManager
from app.services.dd_auto_assign import DDAutoAssigner


router = APIRouter(prefix="/dd", tags=["dd"])


@router.get("/lookup/{dive_code}/{height}")
async def lookup_dd_value(
    dive_code: str,
    height: str,
    db: Session = Depends(get_db),
) -> Dict:
    """
    Look up DD value for a specific dive code and height.

    Example: GET /api/v1/dd/lookup/101B/1m
    """
    dive_code = dive_code.strip().upper()
    height = height.strip().lower()

    calculator = DDCalculator(db)
    dd_value = calculator.lookup_dd(dive_code, height)

    if dd_value is None:
        raise HTTPException(
            status_code=404,
            detail=f"DD value not found for {dive_code} at {height}",
        )

    return {
        "dive_code": dive_code,
        "height": height,
        "dd_value": float(dd_value),
    }


@router.get("/lookup-all/{dive_code}")
async def lookup_all_heights(
    dive_code: str,
    db: Session = Depends(get_db),
) -> Dict:
    """
    Look up DD values for all heights for a dive code.

    Example: GET /api/v1/dd/lookup-all/101B
    """
    dive_code = dive_code.strip().upper()

    calculator = DDCalculator(db)
    dd_values = calculator.lookup_dd_all_heights(dive_code)

    if not dd_values:
        raise HTTPException(
            status_code=404,
            detail=f"No DD values found for {dive_code}",
        )

    return {
        "dive_code": dive_code,
        "heights": dd_values,
    }


@router.get("/by-group/{group}/{height}")
async def lookup_by_group(
    group: int,
    height: str,
    db: Session = Depends(get_db),
) -> Dict:
    """
    Look up DD values for all dives in a group at a height.

    Example: GET /api/v1/dd/by-group/1/1m
    """
    if group < 1 or group > 6:
        raise HTTPException(status_code=400, detail="Group must be 1-6")

    height = height.strip().lower()

    calculator = DDCalculator(db)
    dives = calculator.lookup_dd_by_group(group, height)

    if not dives:
        raise HTTPException(
            status_code=404,
            detail=f"No dives found in group {group} at {height}",
        )

    return {
        "group": group,
        "height": height,
        "dives": dives,
    }


@router.get("/statistics/{height}")
async def get_dd_statistics(
    height: str,
    db: Session = Depends(get_db),
) -> Dict:
    """
    Get DD statistics for a specific height.

    Example: GET /api/v1/dd/statistics/1m
    """
    height = height.strip().lower()

    calculator = DDCalculator(db)
    stats = calculator.get_statistics(height)

    return {
        "height": height,
        **stats,
    }


@router.post("/add-entry")
async def add_dd_entry(
    entry: Dict,
    db: Session = Depends(get_db),
) -> Dict:
    """
    Add a new DD entry to the database.

    Request body:
    {
        "dive_code": "101B",
        "height": "1m",
        "dd_value": 1.3,
        "platform_type": "springboard",
        "notes": "Optional notes"
    }
    """
    manager = DDLookupManager(db)

    try:
        result = manager.add_dd_entry(
            dive_code=entry["dive_code"],
            height=entry.get("height", "1m"),
            dd_value=Decimal(str(entry["dd_value"])),
            platform_type=entry.get("platform_type", "springboard"),
            notes=entry.get("notes"),
        )

        return {
            "success": True,
            "dive_code": result.dive_code,
            "height": result.height,
            "dd_value": float(result.dd_value),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/batch-add")
async def batch_add_dd_entries(
    entries: List[Dict],
    db: Session = Depends(get_db),
) -> Dict:
    """
    Add multiple DD entries in batch.

    Request body: List of entry objects
    """
    manager = DDLookupManager(db)
    success_count, errors = manager.add_dd_batch(entries)

    return {
        "total": len(entries),
        "success": success_count,
        "failed": len(errors),
        "errors": errors,
    }


@router.get("/coverage")
async def get_dd_coverage(
    db: Session = Depends(get_db),
) -> Dict:
    """Get DD table completeness statistics"""
    manager = DDLookupManager(db)
    coverage = manager.verify_completeness()

    return coverage


@router.get("/all")
async def get_all_dds(
    db: Session = Depends(get_db),
) -> Dict:
    """Get all DD values from database"""
    calculator = DDCalculator(db)
    dds = calculator.get_all_dds()

    return {
        "total": len(dds),
        "entries": dds,
    }


@router.post("/auto-assign/{dive_id}")
async def auto_assign_dd(
    dive_id: int,
    db: Session = Depends(get_db),
) -> Dict:
    """
    Automatically assign DD value to a dive.

    Example: POST /api/v1/dd/auto-assign/123
    """
    assigner = DDAutoAssigner(db)
    success, result = assigner.assign_dd_to_dive(dive_id)

    if not success:
        raise HTTPException(status_code=400, detail=result.get("error", "Assignment failed"))

    return result


@router.post("/auto-assign-batch")
async def auto_assign_batch(
    dive_ids: List[int],
    db: Session = Depends(get_db),
) -> Dict:
    """
    Automatically assign DD values to multiple dives.

    Request body: {"dive_ids": [1, 2, 3]}
    """
    assigner = DDAutoAssigner(db)
    result = assigner.assign_dd_to_dives_batch(dive_ids)

    return result


@router.post("/auto-assign-session/{session_id}")
async def auto_assign_session(
    session_id: int,
    db: Session = Depends(get_db),
) -> Dict:
    """
    Automatically assign DD values to all dives in a session.

    Example: POST /api/v1/dd/auto-assign-session/42
    """
    assigner = DDAutoAssigner(db)
    result = assigner.assign_dd_to_session_dives(session_id)

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return result


@router.get("/statistics-session/{session_id}")
async def get_session_statistics(
    session_id: int,
    db: Session = Depends(get_db),
) -> Dict:
    """Get DD assignment statistics for a session"""
    assigner = DDAutoAssigner(db)
    stats = assigner.get_assignment_statistics(session_id)

    if "error" in stats:
        raise HTTPException(status_code=400, detail=stats["error"])

    return stats
