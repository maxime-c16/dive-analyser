"""Analytics endpoints"""

from typing import Dict, Any
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.workspace_access import require_workspace_user
from app.services.write_guard import effective_diver_scope
from app.services.analytics_service import AnalyticsService

router = APIRouter(dependencies=[Depends(require_workspace_user)])


@router.get("/overall", tags=["analytics"])
def get_overall_stats(
    request: Request,
    exclude_lineup: bool = True,
    diver_scope: str = Query("self", pattern="^(self|all)$"),
    diver_id: int | None = None,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Get overall diving statistics
    """
    diver_scope = effective_diver_scope(request, db, diver_scope)
    service = AnalyticsService(db)
    return service.get_overall_stats(exclude_lineup=exclude_lineup, diver_scope="selected" if diver_id else diver_scope, diver_id=diver_id)


@router.get("/by-height", tags=["analytics"])
def get_stats_by_height(
    request: Request,
    exclude_lineup: bool = True,
    diver_scope: str = Query("self", pattern="^(self|all)$"),
    diver_id: int | None = None,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Get statistics broken down by height (1m, 3m, 5m, etc.)
    """
    diver_scope = effective_diver_scope(request, db, diver_scope)
    service = AnalyticsService(db)
    return service.get_stats_by_height(exclude_lineup=exclude_lineup, diver_scope="selected" if diver_id else diver_scope, diver_id=diver_id)


@router.get("/by-direction", tags=["analytics"])
def get_stats_by_direction(
    request: Request,
    exclude_lineup: bool = True,
    diver_scope: str = Query("self", pattern="^(self|all)$"),
    diver_id: int | None = None,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Get statistics broken down by direction (1xx-5xx)
    """
    diver_scope = effective_diver_scope(request, db, diver_scope)
    service = AnalyticsService(db)
    return service.get_stats_by_direction(exclude_lineup=exclude_lineup, diver_scope="selected" if diver_id else diver_scope, diver_id=diver_id)


@router.get("/monthly", tags=["analytics"])
def get_monthly_stats(
    request: Request,
    exclude_lineup: bool = True,
    diver_scope: str = Query("self", pattern="^(self|all)$"),
    diver_id: int | None = None,
    db: Session = Depends(get_db),
) -> list:
    """
    Get statistics broken down by month
    """
    diver_scope = effective_diver_scope(request, db, diver_scope)
    service = AnalyticsService(db)
    return service.get_monthly_stats(exclude_lineup=exclude_lineup, diver_scope="selected" if diver_id else diver_scope, diver_id=diver_id)


@router.get("/trending", tags=["analytics"])
def get_trending_dives(
    request: Request,
    limit: int = 5,
    exclude_lineup: bool = True,
    diver_scope: str = Query("self", pattern="^(self|all)$"),
    diver_id: int | None = None,
    db: Session = Depends(get_db),
) -> list:
    """
    Get dives with highest recent improvement
    """
    diver_scope = effective_diver_scope(request, db, diver_scope)
    service = AnalyticsService(db)
    return service.get_trending_dives(limit=limit, exclude_lineup=exclude_lineup, diver_scope="selected" if diver_id else diver_scope, diver_id=diver_id)
