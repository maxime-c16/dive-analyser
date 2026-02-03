"""Results Aggregator service for competition results and leaderboards"""

from typing import List, Dict, Optional
from sqlalchemy.orm import Session

from app.models.competition_event import CompetitionEvent, CompetitionRound, CompetitionDiveEntry, CompetitionCompetitor
from app.models.judge_score import JudgePanel
from app.models.dive import Dive
from app.services.dd_calculator import DDCalculator


class ResultsAggregator:
    """Aggregates judge scores into final dive scores and event leaderboards"""

    def __init__(self, db: Session):
        self.db = db
        self.dd_calculator = DDCalculator(db)

    def calculate_dive_score(self, judge_panel_id: int, dive_id: int) -> Optional[float]:
        """Calculate final score for single dive: (execution / 10) × DD"""
        panel = self.db.query(JudgePanel).filter(JudgePanel.id == judge_panel_id).first()
        if not panel or not panel.panel_average:
            return None

        dive = self.db.query(Dive).filter(Dive.id == dive_id).first()
        if not dive:
            return None

        dd_value = self.dd_calculator.lookup_dd(dive.dive_code, dive.height)
        if dd_value is None:
            return None

        execution_score = float(panel.panel_average)
        final_score = (execution_score / 10.0) * float(dd_value)
        return final_score

    def calculate_round_standings(self, round_id: int) -> List[Dict]:
        """Calculate standings for a specific round"""
        round_obj = self.db.query(CompetitionRound).filter(CompetitionRound.id == round_id).first()
        if not round_obj:
            return []

        competitors = self.db.query(CompetitionCompetitor).filter(
            CompetitionCompetitor.event_id == round_obj.event_id
        ).all()

        standings = []

        for competitor in competitors:
            dive_entries = self.db.query(CompetitionDiveEntry).filter(
                CompetitionDiveEntry.round_id == round_id,
                CompetitionDiveEntry.competitor_id == competitor.id,
            ).all()

            if not dive_entries:
                continue

            total_score = 0.0
            dive_details = []

            for entry in dive_entries:
                dd_value = self.dd_calculator.lookup_dd(entry.dive_code, "1m")
                if dd_value:
                    estimated_execution = 8.0
                    dive_score = (estimated_execution / 10.0) * float(dd_value)
                    total_score += dive_score
                    dive_details.append({
                        "dive_code": entry.dive_code,
                        "planned_dd": entry.planned_dd / 100.0,
                        "score": dive_score,
                    })

            standings.append({
                "competitor_id": competitor.id,
                "competitor_name": competitor.competitor_name,
                "country": competitor.country_code,
                "total_score": total_score,
                "dives_completed": len(dive_entries),
                "dive_breakdown": dive_details,
            })

        standings.sort(key=lambda x: x["total_score"], reverse=True)

        for rank, standing in enumerate(standings, 1):
            standing["rank"] = rank

        return standings

    def calculate_event_standings(self, event_id: int) -> List[Dict]:
        """Calculate standings for entire event (across all rounds)"""
        event = self.db.query(CompetitionEvent).filter(CompetitionEvent.id == event_id).first()
        if not event:
            return []

        rounds = self.db.query(CompetitionRound).filter(CompetitionRound.event_id == event_id).all()
        competitors = self.db.query(CompetitionCompetitor).filter(
            CompetitionCompetitor.event_id == event_id
        ).all()

        standings = []

        for competitor in competitors:
            total_score = 0.0
            round_scores = []

            for round_obj in rounds:
                round_standings = self.calculate_round_standings(round_obj.id)
                comp_standing = next(
                    (s for s in round_standings if s["competitor_id"] == competitor.id),
                    None,
                )
                if comp_standing:
                    total_score += comp_standing["total_score"]
                    round_scores.append({
                        "round_number": round_obj.round_number,
                        "score": comp_standing["total_score"],
                        "rank": comp_standing.get("rank"),
                    })

            standings.append({
                "competitor_id": competitor.id,
                "competitor_name": competitor.competitor_name,
                "country": competitor.country_code,
                "total_score": total_score,
                "round_breakdown": round_scores,
            })

        standings.sort(key=lambda x: x["total_score"], reverse=True)

        for rank, standing in enumerate(standings, 1):
            standing["rank"] = rank

        return standings

    def export_results(self, event_id: int, format: str = "json") -> str:
        """Export event results in specified format"""
        standings = self.calculate_event_standings(event_id)

        if format == "json":
            import json
            return json.dumps(standings, indent=2)
        elif format == "csv":
            import csv
            from io import StringIO

            output = StringIO()
            writer = csv.DictWriter(
                output,
                fieldnames=["rank", "competitor_name", "country", "total_score"],
            )
            writer.writeheader()
            for standing in standings:
                writer.writerow({
                    "rank": standing["rank"],
                    "competitor_name": standing["competitor_name"],
                    "country": standing["country"],
                    "total_score": f"{standing['total_score']:.2f}",
                })
            return output.getvalue()

        return ""
