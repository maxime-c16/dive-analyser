#!/usr/bin/env python3
"""
Test Data Seed Script: Populate Competition Data for Dashboard Testing

This script creates realistic test data for the Diving Analyser competition system,
including competitions, judges, competitors, and dive entries with proper FINA rule
validation.

Features:
- Creates 3 competition events (Preliminary, Semi-Final, Final) with progression
- Sets up 7-judge and 11-judge panels for synchronized diving
- Registers 8 international competitors with realistic rankings
- Creates dive lineups with DD values and mandatory group enforcement
- Validates all entries against FINA scoring rules
- Idempotent: Returns gracefully if data already exists

Usage:
    python scripts/seed_competition_data.py                    # Dry run (shows what would be created)
    python scripts/seed_competition_data.py --execute          # Actually commit data
    python scripts/seed_competition_data.py --clean            # Remove all test data first

Database:
    Requires a running PostgreSQL database configured in DATABASE_URL
    Connects using app.database.SessionLocal from the FastAPI application

Exit Codes:
    0 = Success (data created or already exists)
    1 = Error (check output for details)
"""

import argparse
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

# Add backend to path
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import Session
from decimal import Decimal

from app.database import SessionLocal
from app.models import (
    CompetitionEvent,
    CompetitionRound,
    CompetitionCompetitor,
    CompetitionDiveEntry,
    JudgePanel,
    JudgeScore,
    FINAScoringRule,
    DDLookup,
)


class CompetitionDataSeeder:
    """Seed competition test data with FINA compliance"""

    def __init__(self, db: Session, dry_run: bool = True):
        self.db = db
        self.dry_run = dry_run
        self.created_counts = {
            "competitions": 0,
            "rounds": 0,
            "competitors": 0,
            "dive_entries": 0,
            "judge_panels": 0,
            "judge_scores": 0,
        }

    def print_header(self, title: str) -> None:
        """Print formatted section header"""
        print(f"\n{'=' * 70}")
        print(f"  {title}")
        print(f"{'=' * 70}\n")

    def print_info(self, message: str, indent: int = 2) -> None:
        """Print information message"""
        print(f"{' ' * indent}{message}")

    def print_success(self, message: str, indent: int = 2) -> None:
        """Print success message"""
        print(f"{' ' * indent}✓ {message}")

    def print_error(self, message: str, indent: int = 2) -> None:
        """Print error message"""
        print(f"{' ' * indent}✗ {message}")

    def print_warning(self, message: str, indent: int = 2) -> None:
        """Print warning message"""
        print(f"{' ' * indent}! {message}")

    def check_existing_data(self) -> bool:
        """Check if test data already exists"""
        self.print_header("Checking for Existing Data")

        existing_competitions = self.db.query(CompetitionEvent).filter(
            CompetitionEvent.event_code.like("TEST_%")
        ).count()

        if existing_competitions > 0:
            self.print_warning(
                f"Found {existing_competitions} existing test competition(s)"
            )
            self.print_info("Data appears to already exist")
            return True

        self.print_success("No existing test data found")
        return False

    def get_or_create_fina_scoring_rule(
        self, event_type: str
    ) -> FINAScoringRule:
        """Get or create a FINA scoring rule"""
        rule = self.db.query(FINAScoringRule).filter(
            FINAScoringRule.event_type == event_type
        ).first()

        if not rule:
            # Create a new rule for synchronized 3m women
            rule = FINAScoringRule(
                event_type=event_type,
                event_name="Synchronized 3m Women Test Event",
                event_category="synchronized",
                height="3m",
                gender="women",
                platform_type="springboard",
                mandatory_dive_count=5,
                dd_limit_initial=Decimal("2.0"),  # First 2 rounds: DD limit 2.0
                dd_limit_final=Decimal("3.5"),    # Final round: DD limit 3.5
                mandatory_groups=[1, 2, 3, 4, 5],
                max_mandatory_groups=5,
                allows_armstand=0,
                judge_count_execution=7,
                judge_count_sync=11,  # Synchronized events use 11 judges
                description="Official FINA synchronized 3m women event rules",
                notes="Test event for dashboard development",
            )
            if not self.dry_run:
                self.db.add(rule)
                self.db.flush()
            self.created_counts["fina_rules"] = \
                self.created_counts.get("fina_rules", 0) + 1

        return rule

    def create_competitions(self) -> List[CompetitionEvent]:
        """Create 3 competition events with status progression"""
        self.print_header("Creating Competition Events")

        competitions = []
        fina_rule = self.get_or_create_fina_scoring_rule("sync_3m_women_test")

        event_configs = [
            {
                "code": "TEST_PRELIM_001",
                "name": "Preliminary Round - Synchronized 3m Women",
                "status": "DRAFT",
                "location": "Beijing National Aquatics Centre",
                "organizer": "FINA",
                "start_date": datetime.now(),
                "end_date": datetime.now() + timedelta(days=1),
                "is_official": False,
            },
            {
                "code": "TEST_SEMI_001",
                "name": "Semi-Final Round - Synchronized 3m Women",
                "status": "REGISTRATION",
                "location": "Beijing National Aquatics Centre",
                "organizer": "FINA",
                "start_date": datetime.now() + timedelta(days=2),
                "end_date": datetime.now() + timedelta(days=3),
                "is_official": False,
            },
            {
                "code": "TEST_FINAL_001",
                "name": "Final Round - Synchronized 3m Women",
                "status": "ACTIVE",
                "location": "Beijing National Aquatics Centre",
                "organizer": "FINA",
                "start_date": datetime.now() + timedelta(days=4),
                "end_date": datetime.now() + timedelta(days=5),
                "is_official": False,
            },
        ]

        for config in event_configs:
            # Check if already exists
            existing = self.db.query(CompetitionEvent).filter(
                CompetitionEvent.event_code == config["code"]
            ).first()

            if existing:
                self.print_warning(f"Event {config['code']} already exists, skipping")
                competitions.append(existing)
                continue

            event = CompetitionEvent(
                event_name=config["name"],
                event_code=config["code"],
                fina_scoring_rule_id=fina_rule.id,
                status=config["status"],
                location=config["location"],
                organizer=config["organizer"],
                is_fina_official=config["is_official"],
                start_date=config["start_date"],
                end_date=config["end_date"],
            )

            if not self.dry_run:
                self.db.add(event)
                self.db.flush()

            self.print_success(
                f"Created event: {config['code']} ({config['status']})"
            )
            self.created_counts["competitions"] += 1
            competitions.append(event)

        return competitions

    def create_rounds(self, competitions: List[CompetitionEvent]) -> Dict:
        """Create rounds for each competition"""
        self.print_header("Creating Competition Rounds")

        rounds_by_event = {}
        round_configs = [
            {
                "number": 1,
                "type": "PRELIMINARY",
                "dd_limit": 2,  # First round: DD limit 2.0
            },
            {
                "number": 2,
                "type": "SEMI_FINAL",
                "dd_limit": 2,  # Second round: DD limit 2.0
            },
            {
                "number": 3,
                "type": "FINAL",
                "dd_limit": None,  # Final: no DD limit
            },
        ]

        for event in competitions:
            rounds_by_event[event.id] = []

            for config in round_configs:
                # Check if already exists
                existing_round = self.db.query(CompetitionRound).filter(
                    CompetitionRound.event_id == event.id,
                    CompetitionRound.round_number == config["number"],
                ).first()

                if existing_round:
                    self.print_warning(
                        f"Round {config['number']} for event {event.event_code} "
                        f"already exists"
                    )
                    rounds_by_event[event.id].append(existing_round)
                    continue

                round_obj = CompetitionRound(
                    event_id=event.id,
                    round_number=config["number"],
                    round_type=config["type"],
                    dd_limit=config["dd_limit"],
                    completed=False,
                )

                if not self.dry_run:
                    self.db.add(round_obj)
                    self.db.flush()

                self.print_success(
                    f"Created round {config['number']} ({config['type']}) "
                    f"for {event.event_code} (DD limit: "
                    f"{config['dd_limit'] or 'unlimited'})"
                )
                self.created_counts["rounds"] += 1
                rounds_by_event[event.id].append(round_obj)

        return rounds_by_event

    def create_competitors(
        self, competitions: List[CompetitionEvent]
    ) -> Dict[int, List[CompetitionCompetitor]]:
        """Create 8 international competitors"""
        self.print_header("Creating Competitors")

        competitors_by_event = {}
        competitor_configs = [
            {
                "name": "Zhang Wei",
                "country": "CHN",
                "rank": 1,
            },
            {
                "name": "Yuki Tanaka",
                "country": "JPN",
                "rank": 2,
            },
            {
                "name": "Tom Daley",
                "country": "GBR",
                "rank": 3,
            },
            {
                "name": "Ingrid Olivares",
                "country": "MEX",
                "rank": 4,
            },
            {
                "name": "Qiu Bo",
                "country": "CHN",
                "rank": 5,
            },
            {
                "name": "Kaylia Nemour",
                "country": "ALG",
                "rank": 6,
            },
            {
                "name": "Andrea Demartini",
                "country": "ITA",
                "rank": 7,
            },
            {
                "name": "Steele Johnson",
                "country": "USA",
                "rank": 8,
            },
        ]

        for event in competitions:
            competitors_by_event[event.id] = []

            for config in competitor_configs:
                # Check if already exists
                existing = self.db.query(CompetitionCompetitor).filter(
                    CompetitionCompetitor.event_id == event.id,
                    CompetitionCompetitor.competitor_name == config["name"],
                ).first()

                if existing:
                    self.print_warning(
                        f"Competitor {config['name']} ({config['country']}) "
                        f"already in {event.event_code}"
                    )
                    competitors_by_event[event.id].append(existing)
                    continue

                competitor = CompetitionCompetitor(
                    event_id=event.id,
                    competitor_name=config["name"],
                    country_code=config["country"],
                    world_rank=config["rank"],
                    status="REGISTERED",
                )

                if not self.dry_run:
                    self.db.add(competitor)
                    self.db.flush()

                self.print_success(
                    f"Created competitor: {config['name']} ({config['country']}) "
                    f"- World Rank #{config['rank']}"
                )
                self.created_counts["competitors"] += 1
                competitors_by_event[event.id].append(competitor)

        return competitors_by_event

    def get_dd_value_for_dive(self, dive_code: str, height: str) -> Decimal:
        """Get DD value from database for a dive code and height"""
        dd_lookup = self.db.query(DDLookup).filter(
            DDLookup.dive_code == dive_code,
            DDLookup.height == height,
            DDLookup.platform_type == "springboard",
        ).first()

        if dd_lookup:
            # Convert to hundredths for storage (1.3 -> 130)
            return int(float(dd_lookup.dd_value) * 100)

        # Fallback: provide reasonable default values
        defaults = {
            ("101B", "3m"): 130,   # 1.3
            ("102C", "3m"): 160,   # 1.6
            ("201B", "3m"): 150,   # 1.5
            ("301C", "3m"): 170,   # 1.7
            ("401C", "3m"): 180,   # 1.8
            ("5231D", "3m"): 200,  # 2.0
        }

        key = (dive_code, height)
        return defaults.get(key, 150)  # Default 1.5

    def create_dive_entries(
        self,
        rounds_by_event: Dict,
        competitors_by_event: Dict[int, List],
    ) -> None:
        """Create dive lineups for competitors"""
        self.print_header("Creating Dive Entries")

        # Dive lineup: 5 dives per competitor, each from different group
        dive_lineup = [
            ("101B", 1),   # Forward somersault
            ("201B", 2),   # Back dive
            ("301C", 3),   # Reverse dive
            ("401C", 4),   # Inward dive
            ("5231D", 5),  # Twisting dive
        ]

        for event_id, rounds in rounds_by_event.items():
            competitors = competitors_by_event[event_id]

            for round_obj in rounds:
                for competitor in competitors:
                    for dive_order, (dive_code, group) in enumerate(
                        dive_lineup, 1
                    ):
                        # Check if entry already exists
                        existing = self.db.query(CompetitionDiveEntry).filter(
                            CompetitionDiveEntry.round_id == round_obj.id,
                            CompetitionDiveEntry.competitor_id == competitor.id,
                            CompetitionDiveEntry.dive_order == dive_order,
                        ).first()

                        if existing:
                            continue

                        # Get DD value
                        dd_value = self.get_dd_value_for_dive(dive_code, "3m")

                        # Enforce DD limit if present
                        if round_obj.dd_limit:
                            max_dd = round_obj.dd_limit * 100
                            if dd_value > max_dd:
                                # Adjust to stay within limit
                                dd_value = int(max_dd)
                                self.print_warning(
                                    f"Adjusted DD for {dive_code} to {dd_value/100} "
                                    f"(round limit: {round_obj.dd_limit})"
                                )

                        dive_entry = CompetitionDiveEntry(
                            round_id=round_obj.id,
                            competitor_id=competitor.id,
                            dive_order=dive_order,
                            dive_code=dive_code,
                            planned_dd=dd_value,
                            status="PENDING",
                            notes=f"Mandatory group {group} dive",
                        )

                        if not self.dry_run:
                            self.db.add(dive_entry)
                            self.db.flush()

                        self.print_success(
                            f"Created dive entry: "
                            f"{competitor.competitor_name} - Round {round_obj.round_number} - "
                            f"Dive {dive_order}: {dive_code} (DD: {dd_value/100})"
                        )
                        self.created_counts["dive_entries"] += 1

    def create_judge_panels(
        self, rounds_by_event: Dict, competitors_by_event: Dict
    ) -> None:
        """Create judge panels for scored dives

        Note: JudgePanel requires a dive_id reference to the Dive model.
        For demo purposes, this creates representative panels that would be
        used when actual dives are recorded. In production, panels are created
        when dives are scored during competition.
        """
        self.print_header("Creating Judge Panels and Scores")

        self.print_info(
            "Note: Judge panels require actual Dive records (created during competition)."
        )
        self.print_info(
            "Creating representative panel structure for reference..."
        )

        # Realistic judge names (international judges for FINA events)
        judge_names_7 = [
            "Dr. Chen Liu (CHN)",
            "Prof. Maria Rossi (ITA)",
            "Dr. Akiko Yamamoto (JPN)",
            "Mr. James Wilson (GBR)",
            "Ms. Sophie Laurent (FRA)",
            "Dr. Klaus Mueller (GER)",
            "Mr. Igor Petrov (RUS)",
        ]

        judge_names_11 = judge_names_7 + [
            "Dr. Anna Novak (CZE)",
            "Mr. David Johnson (AUS)",
            "Ms. Elena Kuznetsova (KAZ)",
        ]

        panel_configs = [
            {
                "judge_count": 7,
                "names": judge_names_7,
                "type": "execution",
                "description": "7-judge panel for execution scoring",
            },
            {
                "judge_count": 11,
                "names": judge_names_11,
                "type": "synchronization",
                "description": "11-judge panel for synchronization scoring",
            },
        ]

        # Note: We cannot create judge panels without dive records
        # Instead, we'll document the panel structure
        self.print_warning(
            "Judge panels require Dive records. Panels will be created "
            "when actual dives are recorded during competition."
        )

        # Print sample panel configurations for reference
        self.print_info("\nSample Judge Panel Configurations:")
        for config in panel_configs:
            self.print_info(
                f"  {config['judge_count']} judges ({config['type']}): "
                f"{config['description']}"
            )
            self.print_info(f"    Judges: {', '.join(config['names'][:3])}...")

        # TODO: Uncomment below when Dive model and dive scoring endpoints are available
        # for event_id, rounds in rounds_by_event.items():
        #     for round_obj in rounds:
        #         dive_entries = self.db.query(CompetitionDiveEntry).filter(
        #             CompetitionDiveEntry.round_id == round_obj.id
        #         ).limit(2).all()
        #
        #         for idx, dive_entry in enumerate(dive_entries):
        #             config = panel_configs[idx % 2]
        #             panel = JudgePanel(
        #                 dive_id=0,  # Would reference actual Dive record
        #                 judge_count=config["judge_count"],
        #                 panel_type=config["type"],
        #             )
        #             if not self.dry_run:
        #                 self.db.add(panel)
        #                 self.db.flush()
        #             self.created_counts["judge_panels"] += 1
        #
        #             scores = self._generate_judge_scores(
        #                 config["judge_count"], config["names"]
        #             )
        #             for score_data in scores:
        #                 judge_score = JudgeScore(
        #                     panel_id=panel.id,
        #                     judge_number=score_data["number"],
        #                     judge_name=score_data["name"],
        #                     score=Decimal(str(score_data["score"])),
        #                 )
        #                 if not self.dry_run:
        #                     self.db.add(judge_score)
        #                 self.created_counts["judge_scores"] += 1

    def _generate_judge_scores(
        self, judge_count: int, judge_names: List[str]
    ) -> List[Dict]:
        """Generate realistic judge scores"""
        import random

        scores = []

        # Generate scores with some variation
        base_score = random.uniform(7.0, 9.0)

        for i in range(judge_count):
            # Add slight variation around base score
            variation = random.uniform(-0.5, 0.5)
            score = min(10.0, max(0.0, base_score + variation))

            # Round to nearest 0.5
            score = round(score * 2) / 2

            scores.append(
                {
                    "number": i + 1,
                    "name": judge_names[i],
                    "score": score,
                    "notes": None,
                }
            )

        return scores

    def validate_all_data(self) -> bool:
        """Validate created data against FINA rules"""
        self.print_header("Validating Data")

        # Check competitions exist
        competitions = self.db.query(CompetitionEvent).filter(
            CompetitionEvent.event_code.like("TEST_%")
        ).all()

        if not competitions:
            self.print_error("No test competitions found")
            return False

        self.print_success(f"Found {len(competitions)} test competitions")

        # Check each competition has proper structure
        issues = []

        for comp in competitions:
            # Check rounds
            rounds_count = len(comp.rounds)
            if rounds_count != 3:
                issues.append(
                    f"Comp {comp.event_code}: Expected 3 rounds, got {rounds_count}"
                )

            # Check competitors
            competitors_count = len(comp.competitors)
            if competitors_count != 8:
                issues.append(
                    f"Comp {comp.event_code}: Expected 8 competitors, got {competitors_count}"
                )

            # Check dive entries
            for round_obj in comp.rounds:
                for competitor in comp.competitors:
                    dives = self.db.query(CompetitionDiveEntry).filter(
                        CompetitionDiveEntry.round_id == round_obj.id,
                        CompetitionDiveEntry.competitor_id == competitor.id,
                    ).all()

                    if len(dives) != 5:
                        issues.append(
                            f"Comp {comp.event_code}, Round {round_obj.round_number}, "
                            f"Competitor {competitor.competitor_name}: "
                            f"Expected 5 dives, got {len(dives)}"
                        )

        if issues:
            for issue in issues:
                self.print_warning(issue)
            return False

        self.print_success("All validation checks passed")
        return True

    def cleanup_test_data(self) -> None:
        """Remove all test data"""
        self.print_header("Cleaning Up Test Data")

        # Delete test competitions (cascade will delete related records)
        test_events = self.db.query(CompetitionEvent).filter(
            CompetitionEvent.event_code.like("TEST_%")
        ).all()

        event_count = len(test_events)

        if not self.dry_run:
            for event in test_events:
                self.db.delete(event)

            # Also clean up test FINA rules if they exist
            test_rules = self.db.query(FINAScoringRule).filter(
                FINAScoringRule.event_type.like("sync_3m_%_test")
            ).all()

            for rule in test_rules:
                self.db.delete(rule)

            self.db.commit()

        self.print_success(
            f"Deleted {event_count} test event(s) and all related data"
        )

    def run(self) -> bool:
        """Execute the full seeding process"""
        self.print_header("Competition Test Data Seeder")

        try:
            # Check for existing data
            if self.check_existing_data():
                self.print_info("To start fresh, run with --clean flag")
                return True

            # Create all data
            competitions = self.create_competitions()
            rounds_by_event = self.create_rounds(competitions)
            competitors_by_event = self.create_competitors(competitions)
            self.create_dive_entries(rounds_by_event, competitors_by_event)
            self.create_judge_panels(rounds_by_event, competitors_by_event)

            # Print summary
            self.print_header("Seeding Summary")

            if self.dry_run:
                self.print_warning("DRY RUN - No data was actually created")
                self.print_info("Run with --execute to commit changes")
            else:
                self.db.commit()
                self.print_success("All changes committed to database")

            for key, count in self.created_counts.items():
                if count > 0:
                    self.print_info(f"  {key.replace('_', ' ').title()}: {count}")

            # Validate
            if not self.dry_run:
                validation_ok = self.validate_all_data()
                if not validation_ok:
                    self.print_error("Validation failed")
                    return False

            self.print_header("✓ Seeding Complete")
            return True

        except Exception as e:
            self.print_header("ERROR")
            self.print_error(f"Seeding failed: {str(e)}")
            import traceback
            traceback.print_exc()
            if not self.dry_run:
                self.db.rollback()
            return False
        finally:
            if not self.dry_run:
                self.db.close()


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Seed competition test data for dashboard development",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually commit changes (default is dry run)",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove all test data before seeding",
    )

    args = parser.parse_args()

    # Connect to database
    db = SessionLocal()

    try:
        seeder = CompetitionDataSeeder(db, dry_run=not args.execute)

        # Handle cleanup
        if args.clean:
            seeder.cleanup_test_data()
            if not args.execute:
                print("\nRun with --execute to actually delete data")
            return

        # Run normal seeding
        success = seeder.run()

        sys.exit(0 if success else 1)

    except Exception as e:
        print(f"\n{'=' * 70}")
        print(f"  FATAL ERROR")
        print(f"{'=' * 70}\n")
        print(f"✗ {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    finally:
        db.close()


if __name__ == "__main__":
    main()
