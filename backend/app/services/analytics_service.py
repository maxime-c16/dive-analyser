"""Analytics service for computing dive statistics"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.dive import Dive
from app.models.session import Session as SessionModel
from app.services.diver_identity import get_primary_diver
from app.services.performance_scoring import dive_score_10, is_success
from app.services.difficulty_adjustment import difficulty_summary


class AnalyticsService:
    """Service for computing analytics and statistics"""

    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _is_real_dive(dive: Dive) -> bool:
        """Straight jumps (100/200/300/400 variants) are drills, not dives."""
        return not (dive.dive_code or "").startswith(("100", "200", "300", "400"))

    @staticmethod
    def _normalize_height(height: str | None) -> str | None:
        """Normalize height labels so legacy case differences do not split the same height."""
        if not height:
            return None

        value = height.strip()
        if not value:
            return None

        if value[:-1].isdigit() and value[-1].lower() == "m":
            return f"{int(value[:-1])}m"

        return value.lower()

    def _get_analytics_dives(self, exclude_lineup: bool = True, diver_scope: str = "self", diver_id: int | None = None) -> List[Dive]:
        query = self.db.query(Dive)

        if exclude_lineup:
            query = query.filter(Dive.is_lineup == False)
        if diver_id is not None:
            query = query.filter(Dive.diver_id == diver_id)
        elif diver_scope != "all":
            primary = get_primary_diver(self.db)
            query = query.filter((Dive.diver_id == primary.id) | ((Dive.diver_id == None) & (Dive.person_name == None)))

        return [dive for dive in query.all() if self._is_real_dive(dive)]

    @staticmethod
    def _with_difficulty_metrics(dives: List[Dive]) -> Dict[str, Any]:
        """Attach transparent DD-aware descriptive fields to mixed-dive views."""
        return difficulty_summary(dives)

    def get_overall_stats(self, exclude_lineup: bool = True, diver_scope: str = "self", diver_id: int | None = None) -> Dict[str, Any]:
        """Get overall performance statistics"""
        dives = self._get_analytics_dives(exclude_lineup=exclude_lineup, diver_scope=diver_scope, diver_id=diver_id)

        if not dives:
            return {
                "total_dives": 0,
                "avg_performance": 0.0,
                "success_rate": 0.0,
                "total_sessions": 0,
            }

        total_dives = len(dives)
        avg_performance = sum(dive_score_10(d) for d in dives) / total_dives if total_dives > 0 else 0
        successful_dives = sum(1 for d in dives if is_success(d.performance))
        success_rate = (successful_dives / total_dives * 100) if total_dives > 0 else 0

        total_sessions = len(set(d.session_id for d in dives))
        difficulty = self._with_difficulty_metrics(dives)

        return {
            "total_dives": total_dives,
            "avg_performance": round(avg_performance, 2),
            "success_rate": round(success_rate, 1),
            "total_sessions": total_sessions,
            "avg_dd": difficulty["average_dd"],
            "median_dd": difficulty["median_dd"],
            "max_dd": difficulty["max_dd"],
            "dd_defined_dives": difficulty["dd_defined_attempt_count"],
            "dd_coverage_rate": difficulty["dd_coverage_rate"],
            "dd_reference": difficulty["dd_reference"],
        }

    def get_stats_by_height(self, exclude_lineup: bool = True, diver_scope: str = "self", diver_id: int | None = None) -> Dict[str, Any]:
        """Get statistics broken down by height"""
        dives = self._get_analytics_dives(exclude_lineup=exclude_lineup, diver_scope=diver_scope, diver_id=diver_id)
        grouped: Dict[str, List[Dive]] = {}
        for dive in dives:
            normalized_height = self._normalize_height(dive.height)
            if not normalized_height:
                continue
            grouped.setdefault(normalized_height, []).append(dive)

        stats_by_height: Dict[str, Any] = {}

        for height in sorted(grouped.keys(), key=lambda value: int(value[:-1]) if value[:-1].isdigit() else 999):
            height_dives = grouped[height]
            avg_perf = sum(dive_score_10(d) for d in height_dives) / len(height_dives)
            successful = sum(1 for d in height_dives if is_success(d.performance))
            success_rate = (successful / len(height_dives) * 100) if height_dives else 0

            stats_by_height[height] = {
                "total_dives": len(height_dives),
                "avg_performance": round(avg_perf, 2),
                "success_rate": round(success_rate, 1),
                **self._with_difficulty_metrics(height_dives),
            }

        return stats_by_height

    def get_stats_by_direction(self, exclude_lineup: bool = True, diver_scope: str = "self", diver_id: int | None = None) -> Dict[str, Any]:
        """Get statistics broken down by direction (1xx-5xx)"""
        dives = self._get_analytics_dives(exclude_lineup=exclude_lineup, diver_scope=diver_scope, diver_id=diver_id)
        stats_by_direction: Dict[str, Any] = {}

        for direction in sorted(set(d.direction for d in dives if d.direction)):
            dir_dives = [d for d in dives if d.direction == direction]
            if dir_dives:
                avg_perf = sum(dive_score_10(d) for d in dir_dives) / len(dir_dives)
                successful = sum(1 for d in dir_dives if is_success(d.performance))
                success_rate = (successful / len(dir_dives) * 100) if dir_dives else 0

                stats_by_direction[str(direction)] = {
                    "total_dives": len(dir_dives),
                    "avg_performance": round(avg_perf, 2),
                    "success_rate": round(success_rate, 1),
                    **self._with_difficulty_metrics(dir_dives),
                }

        return stats_by_direction

    def get_monthly_stats(self, exclude_lineup: bool = True, diver_scope: str = "self", diver_id: int | None = None) -> List[Dict[str, Any]]:
        """Get statistics broken down by month"""
        dives = self._get_analytics_dives(exclude_lineup=exclude_lineup, diver_scope=diver_scope, diver_id=diver_id)

        # Group by month
        monthly_data: Dict[str, List[Dive]] = {}
        for dive in dives:
            month_key = dive.dive_datetime.strftime("%Y-%m")
            if month_key not in monthly_data:
                monthly_data[month_key] = []
            monthly_data[month_key].append(dive)

        result = []
        for month_key in sorted(monthly_data.keys()):
            month_dives = monthly_data[month_key]
            avg_perf = sum(dive_score_10(d) for d in month_dives) / len(month_dives)
            successful = sum(1 for d in month_dives if is_success(d.performance))
            success_rate = (successful / len(month_dives) * 100) if month_dives else 0

            result.append({
                "month": month_key,
                "total_dives": len(month_dives),
                "avg_performance": round(avg_perf, 2),
                "success_rate": round(success_rate, 1),
                **self._with_difficulty_metrics(month_dives),
            })

        return result

    def get_trending_dives(self, limit: int = 5, exclude_lineup: bool = True, diver_scope: str = "self", diver_id: int | None = None) -> List[Dict[str, Any]]:
        """Get dives with highest recent improvement"""
        dives = sorted(
            self._get_analytics_dives(exclude_lineup=exclude_lineup, diver_scope=diver_scope, diver_id=diver_id),
            key=lambda dive: dive.dive_datetime,
            reverse=True,
        )

        # Group by dive code
        dive_codes: Dict[str, List[Dive]] = {}
        for dive in dives:
            if dive.dive_code not in dive_codes:
                dive_codes[dive.dive_code] = []
            dive_codes[dive.dive_code].append(dive)

        # Calculate improvement
        improvements = []
        for code, code_dives in dive_codes.items():
            if len(code_dives) >= 2:
                recent_avg = sum(dive_score_10(d) for d in code_dives[:5]) / min(5, len(code_dives))
                older_avg = sum(dive_score_10(d) for d in code_dives[5:10]) / min(5, len(code_dives) - 5) if len(code_dives) > 5 else recent_avg

                improvement = recent_avg - older_avg
                improvements.append({
                    "dive_code": code,
                    "improvement": round(improvement, 2),
                    "recent_avg": round(recent_avg, 2),
                    "total_attempts": len(code_dives),
                })

        # Sort by improvement and return top N
        improvements.sort(key=lambda x: x["improvement"], reverse=True)
        return improvements[:limit]
