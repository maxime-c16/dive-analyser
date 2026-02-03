"""Import endpoints for loading dive data"""

import os
from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.import_service import ImportService, find_latest_json

router = APIRouter()

# Default paths to look for JSON data
JSON_PATHS = [
    '/app/reports/dive_metadata_report_final.json',  # Docker path
    '/app/dive_metadata_report_final.json',  # Alternative Docker path
    'dive_metadata_report_final.json',  # Local path
    'reports/dive_metadata_report_final.json',  # Local reports path
]


def find_json_file() -> str:
    """Find the JSON file from known paths"""
    for path in JSON_PATHS:
        if os.path.exists(path):
            return path

    # Try the find_latest_json function
    for base_path in ['/app/reports', '/app', 'reports', '.']:
        result = find_latest_json(base_path)
        if result:
            return result

    raise HTTPException(
        status_code=404,
        detail="No dive metadata JSON file found. Run the extraction pipeline first."
    )


@router.post("/sync", tags=["import"])
async def sync_data(
    db: Session = Depends(get_db),
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """
    Sync dive data from the latest JSON file into the database.

    - Finds the latest dive_metadata JSON file
    - Imports new sessions and dives (skips duplicates by UUID)
    - Updates session statistics

    Args:
        force_refresh: If True, clears all data before importing
    """
    json_path = find_json_file()

    service = ImportService(db)

    # Optionally clear existing data
    if force_refresh:
        clear_stats = service.clear_all_data()
    else:
        clear_stats = None

    # Import data
    import_stats = service.import_from_json(json_path)

    return {
        "status": "success",
        "json_file": json_path,
        "cleared": clear_stats,
        "import_stats": import_stats,
    }


@router.post("/clear", tags=["import"])
async def clear_data(
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Clear all dive and session data from the database.

    WARNING: This will delete all data!
    """
    service = ImportService(db)
    stats = service.clear_all_data()

    return {
        "status": "success",
        "cleared": stats,
    }


@router.get("/status", tags=["import"])
async def import_status(
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Get the current import status and data counts.
    """
    from app.models.dive import Dive
    from app.models.session import Session as SessionModel
    from sqlalchemy import func

    # Count records
    session_count = db.query(func.count(SessionModel.id)).scalar()
    dive_count = db.query(func.count(Dive.id)).scalar()
    personal_dive_count = db.query(func.count(Dive.id)).filter(Dive.is_lineup == False).scalar()

    # Get date range
    min_date = db.query(func.min(SessionModel.date)).scalar()
    max_date = db.query(func.max(SessionModel.date)).scalar()

    # Find JSON file info
    try:
        json_path = find_json_file()
        json_exists = True
        json_mtime = os.path.getmtime(json_path)
    except HTTPException:
        json_path = None
        json_exists = False
        json_mtime = None

    return {
        "database": {
            "sessions": session_count,
            "total_dives": dive_count,
            "personal_dives": personal_dive_count,
            "date_range": {
                "start": str(min_date) if min_date else None,
                "end": str(max_date) if max_date else None,
            },
        },
        "json_source": {
            "path": json_path,
            "exists": json_exists,
            "modified_timestamp": json_mtime,
        },
    }
