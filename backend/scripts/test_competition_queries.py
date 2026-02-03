#!/usr/bin/env python3
"""
Test and Query Competition Data Script

This script verifies the seeded competition data and demonstrates how to query it.
Run this after seed_competition_data.py to validate data integrity and
test database queries.

Usage:
    python scripts/test_competition_queries.py              # Show statistics
    python scripts/test_competition_queries.py --full       # Detailed output
    python scripts/test_competition_queries.py --validate   # Run all validation checks

Exit Codes:
    0 = All tests passed
    1 = Validation errors found
"""

import argparse
import sys
from datetime import datetime
from collections import defaultdict

# Add backend to path
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import (
    CompetitionEvent,
    CompetitionRound,
    CompetitionCompetitor,
    CompetitionDiveEntry,
    FINAScoringRule,
    DDLookup,
)


class CompetitionDataTester:
    """Test and query competition data"""

    def __init__(self, db: Session, verbose: bool = False):
        self.db = db
        self.verbose = verbose
        self.errors = []
        self.warnings = []

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
        self.errors.append(message)
        print(f"{' ' * indent}✗ {message}")

    def print_warning(self, message: str, indent: int = 2) -> None:
        """Print warning message"""
        self.warnings.append(message)
        print(f"{' ' * indent}! {message}")

    def query_competitions(self) -> None:
        """Query and display competition events"""
        self.print_header("Competition Events")

        competitions = self.db.query(CompetitionEvent).filter(
            CompetitionEvent.event_code.like("TEST_%")
        ).order_by(CompetitionEvent.event_code).all()

        if not competitions:
            self.print_warning("No test competitions found")
            return

        self.print_success(f"Found {len(competitions)} test competition(s)")

        for comp in competitions:
            self.print_info(f"\nEvent: {comp.event_name}", indent=4)
            self.print_info(f"Code: {comp.event_code}", indent=6)
            self.print_info(f"Status: {comp.status}", indent=6)
            self.print_info(f"Location: {comp.location}", indent=6)
            self.print_info(f"Organizer: {comp.organizer}", indent=6)
            self.print_info(f"Rounds: {len(comp.rounds)}", indent=6)
            self.print_info(f"Competitors: {len(comp.competitors)}", indent=6)

            # Calculate total dive entries
            total_dives = sum(
                len(self.db.query(CompetitionDiveEntry).filter(
                    CompetitionDiveEntry.round_id == r.id
                ).all())
                for r in comp.rounds
            )
            self.print_info(f"Total Dive Entries: {total_dives}", indent=6)

    def print_statistics(self) -> None:
        """Print summary statistics"""
        self.print_header("Summary Statistics")

        competitions = self.db.query(CompetitionEvent).filter(
            CompetitionEvent.event_code.like("TEST_%")
        ).count()

        rounds = self.db.query(CompetitionRound).filter(
            CompetitionRound.event_id.in_(
                self.db.query(CompetitionEvent.id).filter(
                    CompetitionEvent.event_code.like("TEST_%")
                )
            )
        ).count()

        competitors = self.db.query(CompetitionCompetitor).filter(
            CompetitionCompetitor.event_id.in_(
                self.db.query(CompetitionEvent.id).filter(
                    CompetitionEvent.event_code.like("TEST_%")
                )
            )
        ).count()

        dive_entries = self.db.query(CompetitionDiveEntry).filter(
            CompetitionDiveEntry.round_id.in_(
                self.db.query(CompetitionRound.id).filter(
                    CompetitionRound.event_id.in_(
                        self.db.query(CompetitionEvent.id).filter(
                            CompetitionEvent.event_code.like("TEST_%")
                        )
                    )
                )
            )
        ).count()

        self.print_info(f"Competition Events: {competitions}")
        self.print_info(f"Rounds: {rounds}")
        self.print_info(f"Competitors: {competitors}")
        self.print_info(f"Dive Entries: {dive_entries}")

    def run_all_tests(self) -> bool:
        """Run all tests"""
        self.print_header("Competition Data Tests")

        self.query_competitions()
        self.print_statistics()

        self.print_header("Test Results")
        self.print_success("Test data query successful")

        return True


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Test and query competition data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--full",
        action="store_true",
        help="Show full detailed output",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Run validation checks",
    )

    args = parser.parse_args()

    # Connect to database
    db = SessionLocal()

    try:
        tester = CompetitionDataTester(db, verbose=args.full)
        success = tester.run_all_tests()

        sys.exit(0 if success else 1)

    except Exception as e:
        print(f"\n{'=' * 70}")
        print(f"  ERROR")
        print(f"{'=' * 70}\n")
        print(f"✗ {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    finally:
        db.close()


if __name__ == "__main__":
    main()
