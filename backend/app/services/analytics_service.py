"""Analytics service for computing dive statistics"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.dive import Dive
from app.models.session import Session as SessionModel


class AnalyticsService:
    """Service for computing analytics and statistics"""

    def __init__(self, db: Session):
        self.db = db

    def get_overall_stats(self, exclude_lineup: bool = True) -> Dict[str, Any]:
        """Get overall performance statistics"""
        query = self.db.query(Dive)

        if exclude_lineup:
            query = query.filter(Dive.is_lineup == False)

        dives = query.all()

        if not dives:
            return {
                "total_dives": 0,
                "avg_performance": 0.0,
                "success_rate": 0.0,
                "total_sessions": 0,
            }

        total_dives = len(dives)
        avg_performance = sum(d.performance_numeric for d in dives) / total_dives if total_dives > 0 else 0
        successful_dives = sum(1 for d in dives if d.performance_numeric >= 2)
        success_rate = (successful_dives / total_dives * 100) if total_dives > 0 else 0

        total_sessions = len(set(d.session_id for d in dives))

        return {
            "total_dives": total_dives,
            "avg_performance": round(avg_performance, 2),
            "success_rate": round(success_rate, 1),
            "total_sessions": total_sessions,
        }

    def get_stats_by_height(self, exclude_lineup: bool = True) -> Dict[str, Any]:
        """Get statistics broken down by height"""
        query = self.db.query(Dive)

        if exclude_lineup:
            query = query.filter(Dive.is_lineup == False)

        dives = query.all()
        stats_by_height: Dict[str, Any] = {}

        for height in sorted(set(d.height for d in dives if d.height)):
            height_dives = [d for d in dives if d.height == height]
            if height_dives:
                avg_perf = sum(d.performance_numeric for d in height_dives) / len(height_dives)
                successful = sum(1 for d in height_dives if d.performance_numeric >= 2)
                success_rate = (successful / len(height_dives) * 100) if height_dives else 0

                stats_by_height[height] = {
                    "total_dives": len(height_dives),
                    "avg_performance": round(avg_perf, 2),
                    "success_rate": round(success_rate, 1),
                }

        return stats_by_height

    def get_stats_by_direction(self, exclude_lineup: bool = True) -> Dict[str, Any]:
        """Get statistics broken down by direction (1xx-5xx)"""
        query = self.db.query(Dive)

        if exclude_lineup:
            query = query.filter(Dive.is_lineup == False)

        dives = query.all()
        stats_by_direction: Dict[str, Any] = {}

        for direction in sorted(set(d.direction for d in dives if d.direction)):
            dir_dives = [d for d in dives if d.direction == direction]
            if dir_dives:
                avg_perf = sum(d.performance_numeric for d in dir_dives) / len(dir_dives)
                successful = sum(1 for d in dir_dives if d.performance_numeric >= 2)
                success_rate = (successful / len(dir_dives) * 100) if dir_dives else 0

                stats_by_direction[str(direction)] = {
                    "total_dives": len(dir_dives),
                    "avg_performance": round(avg_perf, 2),
                    "success_rate": round(success_rate, 1),
                }

        return stats_by_direction

    def get_monthly_stats(self, exclude_lineup: bool = True) -> List[Dict[str, Any]]:
        """Get statistics broken down by month"""
        query = self.db.query(Dive)

        if exclude_lineup:
            query = query.filter(Dive.is_lineup == False)

        dives = query.all()

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
            avg_perf = sum(d.performance_numeric for d in month_dives) / len(month_dives)
            successful = sum(1 for d in month_dives if d.performance_numeric >= 2)
            success_rate = (successful / len(month_dives) * 100) if month_dives else 0

            result.append({
                "month": month_key,
                "total_dives": len(month_dives),
                "avg_performance": round(avg_perf, 2),
                "success_rate": round(success_rate, 1),
            })

        return result

    def get_trending_dives(self, limit: int = 5, exclude_lineup: bool = True) -> List[Dict[str, Any]]:
        """Get dives with highest recent improvement"""
        query = self.db.query(Dive)

        if exclude_lineup:
            query = query.filter(Dive.is_lineup == False)

        dives = query.order_by(Dive.dive_datetime.desc()).all()

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
                recent_avg = sum(d.performance_numeric for d in code_dives[:5]) / min(5, len(code_dives))
                older_avg = sum(d.performance_numeric for d in code_dives[5:10]) / min(5, len(code_dives) - 5) if len(code_dives) > 5 else recent_avg

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
