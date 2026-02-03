# Test Data Seeding Script: Competition Events

This script populates the Diving Analyser database with realistic test data for competition events, judges, competitors, and dive entries. It's designed for dashboard development, testing, and demonstration purposes.

## Overview

The `seed_competition_data.py` script creates a complete competition scenario:

### Data Created

1. **3 Competition Events** with status progression:
   - **Preliminary Round** (DRAFT) - Initial stage
   - **Semi-Final Round** (REGISTRATION) - Selection stage
   - **Final Round** (ACTIVE) - Championship stage

2. **Multiple Rounds** per event:
   - Each event has 3 rounds (Preliminary, Semi-Final, Final)
   - DD limits enforced for initial rounds (2.0) and final round (3.5)
   - Proper round sequencing and status management

3. **8 International Competitors**:
   - Zhang Wei (CHN) - Rank #1
   - Yuki Tanaka (JPN) - Rank #2
   - Tom Daley (GBR) - Rank #3
   - Ingrid Olivares (MEX) - Rank #4
   - Qiu Bo (CHN) - Rank #5
   - Kaylia Nemour (ALG) - Rank #6
   - Andrea Demartini (ITA) - Rank #7
   - Steele Johnson (USA) - Rank #8

4. **Dive Lineups** (5 dives per competitor per round):
   - 101B (Forward somersault, Group 1) - DD: 1.3
   - 201B (Back dive, Group 2) - DD: 1.5
   - 301C (Reverse dive, Group 3) - DD: 1.7
   - 401C (Inward dive, Group 4) - DD: 1.8
   - 5231D (1.5 twists forward, Group 5) - DD: 2.0

5. **Judge Panel References**:
   - 7-judge panels for execution scoring
   - 11-judge panels for synchronization scoring
   - Realistic international judge names

### FINA Rule Compliance

All created data enforces official FINA rules:

- **Mandatory groups**: Must include dives from groups 1, 2, 3, 4, 5
- **DD limits** (Synchronized 3m Women):
  - Preliminary & Semi-Final: Maximum DD 2.0
  - Final Round: Maximum DD 3.5 (unlimited in some contexts)
- **Judge counts**: 7 for execution, 11 for synchronized
- **Dive entry validation**: Each competitor must perform 5 dives across all rounds

## Usage

### Basic Dry Run (Preview Only)

```bash
cd backend
python scripts/seed_competition_data.py
```

This shows what data would be created without modifying the database.

### Execute with Database Changes

```bash
python scripts/seed_competition_data.py --execute
```

Creates all test data and commits to database.

### Clean Up Test Data

```bash
# Dry run - preview what will be deleted
python scripts/seed_competition_data.py --clean

# Actually delete test data
python scripts/seed_competition_data.py --clean --execute
```

Removes all test data created by previous runs (events with codes starting with `TEST_`).

### Combine Options

```bash
# Clean and reseed in one command
python scripts/seed_competition_data.py --clean --execute
python scripts/seed_competition_data.py --execute
```

## Database Requirements

The script requires:

- PostgreSQL database (configured via `DATABASE_URL`)
- FastAPI backend initialized with all models
- DD Lookup table populated (contains official FINA DD values)

### Connection

The script uses the standard FastAPI database connection:

```python
from app.database import SessionLocal
```

Configuration comes from environment variables:

```bash
DATABASE_URL=postgresql://user:password@host:5432/database_name
```

See `backend/.env` for configuration example.

## Idempotency

The script is **idempotent**: Running it multiple times is safe.

**Behavior**:
- If test data already exists (events with `TEST_*` codes), the script will:
  1. Detect existing data
  2. Report what's already present
  3. Skip creation
  4. Return successfully without error

**To force recreation**:
```bash
python scripts/seed_competition_data.py --clean --execute
python scripts/seed_competition_data.py --execute
```

## Output Format

### Dry Run Output Example

```
======================================================================
  Competition Test Data Seeder
======================================================================

======================================================================
  Checking for Existing Data
======================================================================

✓ No existing test data found

======================================================================
  Creating Competition Events
======================================================================

✓ Created event: TEST_PRELIM_001 (DRAFT)
✓ Created event: TEST_SEMI_001 (REGISTRATION)
✓ Created event: TEST_FINAL_001 (ACTIVE)

======================================================================
  Creating Competition Rounds
======================================================================

✓ Created round 1 (PRELIMINARY) for TEST_PRELIM_001 (DD limit: 2)
✓ Created round 2 (SEMI_FINAL) for TEST_PRELIM_001 (DD limit: 2)
...

======================================================================
  Seeding Summary
======================================================================

! DRY RUN - No data was actually created
  Run with --execute to commit changes
  Competitions: 3
  Rounds: 9
  Competitors: 24
  Dive Entries: 360
```

### Execute Output Example

```
[Same as above, but with:]

✓ All changes committed to database

======================================================================
  Validating Data
======================================================================

✓ Found 3 test competitions
✓ All validation checks passed

======================================================================
  ✓ Seeding Complete
======================================================================
```

## Data Model Relationships

```
CompetitionEvent
├── CompetitionRound (3 per event)
│   └── CompetitionDiveEntry (40 per round: 8 competitors × 5 dives)
├── CompetitionCompetitor (8 per event)
│   └── CompetitionDiveEntry (40 per round)
└── FINAScoringRule (1 per event)

JudgePanel (created when dives are scored)
└── JudgeScore (7 or 11 per panel)
```

## Important Notes

### Judge Panels

The current implementation creates **reference documentation** for judge panels rather than actual `JudgePanel` records. This is because:

1. `JudgePanel` requires a `dive_id` foreign key
2. Dives are created during actual competition competition, not seeding
3. Judge scores are entered when dives are performed and scored

**When dives are actually recorded** (via API endpoints), the system will automatically create judge panels and manage scoring.

### DD Value Lookup

The script looks up official DD values from the `DDLookup` table:

```sql
SELECT dd_value
FROM dd_lookups
WHERE dive_code = '101B'
  AND height = '3m'
  AND platform_type = 'springboard'
```

If a lookup is not found, the script uses reasonable defaults:
- 101B @ 3m: 1.3
- 102C @ 3m: 1.6
- 201B @ 3m: 1.5
- 301C @ 3m: 1.7
- 401C @ 3m: 1.8
- 5231D @ 3m: 2.0

### DD Limit Enforcement

The script automatically adjusts DD values to respect round limits:

- **Preliminary & Semi-Final** (DD limit 2.0):
  - 5231D is adjusted from 2.0 to fit within limit
  - Other dives remain within limit

- **Final** (DD limit 3.5):
  - No adjustments needed for test dives

### FINA Scoring Rules

The created competitions use a test event type: `sync_3m_women_test`

**Event Configuration**:
- Event Category: Synchronized
- Height: 3m
- Platform: Springboard
- Gender: Women
- Mandatory Dives: 5
- Mandatory Groups: [1, 2, 3, 4, 5]
- Allows Armstand: No
- Initial DD Limit: 2.0
- Final DD Limit: 3.5
- Execution Judges: 7
- Synchronization Judges: 11

## Testing the Dashboard

After seeding data, you can test the dashboard:

1. **List competitions**:
   ```bash
   curl http://localhost:8000/api/v1/competitions/
   ```

2. **View competition details**:
   ```bash
   curl http://localhost:8000/api/v1/competitions/TEST_PRELIM_001/
   ```

3. **Check competitors**:
   ```bash
   curl http://localhost:8000/api/v1/competitions/TEST_PRELIM_001/competitors/
   ```

4. **Review dive entries**:
   ```bash
   curl http://localhost:8000/api/v1/competitions/TEST_PRELIM_001/rounds/1/dives/
   ```

## Troubleshooting

### Database Connection Error

```
psycopg2.OperationalError: could not translate host name "postgres" to address
```

**Solution**: Ensure PostgreSQL is running and `DATABASE_URL` is correctly configured.

```bash
# Check .env file
cat backend/.env

# Or set manually
export DATABASE_URL="postgresql://user:pass@localhost:5432/diving_db"
```

### Foreign Key Violations

```
IntegrityError: (psycopg2.errors.ForeignKeyViolation)
```

**Solution**: Ensure FINA dive codes and DD lookups are populated first.

```bash
# Populate FINA data (if needed)
python scripts/migrate_dd_values.py --execute
```

### Existing Data Conflicts

If you get duplicate key errors, clean up first:

```bash
python scripts/seed_competition_data.py --clean --execute
```

## Extending the Script

To customize seeding, edit these sections:

### Add More Competitors

In `create_competitors()`:

```python
competitor_configs = [
    # ... existing entries ...
    {
        "name": "New Athlete",
        "country": "ABC",
        "rank": 9,
    },
]
```

### Modify Dive Lineup

In `create_dive_entries()`:

```python
dive_lineup = [
    ("101B", 1),   # Forward somersault
    ("201B", 2),   # Back dive
    # ... add or replace dives ...
]
```

### Change DD Limits

In `create_rounds()`:

```python
round_configs = [
    {
        "number": 1,
        "type": "PRELIMINARY",
        "dd_limit": 1.8,  # Changed from 2.0
    },
    # ...
]
```

### Add Judge Scores

Uncomment the TODO section in `create_judge_panels()` when dive records exist:

```python
# Uncomment when Dive model integration complete
for round_obj in rounds:
    dive_entries = self.db.query(CompetitionDiveEntry)...
    # Create judge panels and scores
```

## File Location

```
backend/
├── scripts/
│   ├── seed_competition_data.py          (Main script)
│   ├── SEED_COMPETITION_DATA.md           (This documentation)
│   └── migrate_dd_values.py               (Related DD population)
└── app/
    └── models/
        └── competition_event.py           (Data models)
```

## Performance

- **Dry run**: < 1 second
- **Execute with 3 events**: 2-5 seconds
- **Database size increase**: ~50KB for test data

## Exit Codes

- `0`: Success (data created or already exists)
- `1`: Error (check output for details)

## Related Scripts

- **`migrate_dd_values.py`**: Populates official FINA DD values for all dives
- **`dive_extraction.py`**: Extracts dive metadata from Photos library
- **`dive_analytics.py`**: Computes analytics metrics

## Support

For issues or questions:

1. Check the **Troubleshooting** section above
2. Review database connection settings in `.env`
3. Ensure FINA data is populated (`migrate_dd_values.py`)
4. Check `backend/app/models/competition_event.py` for schema details
