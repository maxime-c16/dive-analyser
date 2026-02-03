"""Analytics endpoints"""

from typing import Dict, Any
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.analytics_service import AnalyticsService

router = APIRouter()


@router.get("/overall", tags=["analytics"])
async def get_overall_stats(
    exclude_lineup: bool = True,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Get overall diving statistics
    """
    service = AnalyticsService(db)
    return service.get_overall_stats(exclude_lineup=exclude_lineup)


@router.get("/by-height", tags=["analytics"])
async def get_stats_by_height(
    exclude_lineup: bool = True,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Get statistics broken down by height (1m, 3m, 5m, etc.)
    """
    service = AnalyticsService(db)
    return service.get_stats_by_height(exclude_lineup=exclude_lineup)


@router.get("/by-direction", tags=["analytics"])
async def get_stats_by_direction(
    exclude_lineup: bool = True,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Get statistics broken down by direction (1xx-5xx)
    """
    service = AnalyticsService(db)
    return service.get_stats_by_direction(exclude_lineup=exclude_lineup)


@router.get("/monthly", tags=["analytics"])
async def get_monthly_stats(
    exclude_lineup: bool = True,
    db: Session = Depends(get_db),
) -> list:
    """
    Get statistics broken down by month
    """
    service = AnalyticsService(db)
    return service.get_monthly_stats(exclude_lineup=exclude_lineup)


@router.get("/trending", tags=["analytics"])
async def get_trending_dives(
    limit: int = 5,
    exclude_lineup: bool = True,
    db: Session = Depends(get_db),
) -> list:
    """
    Get dives with highest recent improvement
    """
    service = AnalyticsService(db)
    return service.get_trending_dives(limit=limit, exclude_lineup=exclude_lineup)
