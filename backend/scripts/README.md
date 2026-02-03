# Scripts Directory - Competition Data and Testing

This directory contains scripts for managing and testing competition data in the Diving Analyser system.

## Quick Reference

### Main Scripts

#### 1. `seed_competition_data.py` - Create Test Data

**Purpose**: Populate database with realistic competition scenarios for dashboard testing

**Quick Start**:
```bash
# Preview what will be created (recommended first step)
python scripts/seed_competition_data.py

# Create the data
python scripts/seed_competition_data.py --execute

# Clean up and start fresh
python scripts/seed_competition_data.py --clean --execute
```

**What It Creates**:
- 3 competition events (Preliminary, Semi-Final, Final)
- 9 rounds total (3 per event)
- 24 competitors (8 per event)
- 360 dive entries (5 dives × 8 competitors × 9 rounds)
- FINA scoring rule configuration
- Judge panel reference structure

**Key Features**:
- ✓ Idempotent (safe to run multiple times)
- ✓ FINA rule compliant
- ✓ Dry-run mode (default, no database changes)
- ✓ Comprehensive logging
- ✓ Transaction rollback on error

**Time**: 2-5 seconds with `--execute`

---

#### 2. `test_competition_queries.py` - Verify Test Data

**Purpose**: Query and validate seeded competition data

**Quick Start**:
```bash
# Show summary statistics
python scripts/test_competition_queries.py

# Show detailed output
python scripts/test_competition_queries.py --full

# Run validation checks
python scripts/test_competition_queries.py --validate
```

**What It Shows**:
- Competition events and status
- Rounds with DD limits
- Competitor listings with rankings
- Dive entry summaries
- FINA rule compliance validation
- Data integrity checks

**Time**: < 1 second

---

#### 3. `migrate_dd_values.py` - Populate Official DD Values

**Purpose**: Populate official FINA Degree of Difficulty values for dive codes

**Quick Start**:
```bash
# Preview what will be populated
python scripts/migrate_dd_values.py

# Populate the DD values
python scripts/migrate_dd_values.py --execute
```

**Required Before**: `seed_competition_data.py` (for DD value lookups)

---

## Usage Workflow

### Setup Phase (First Time)

```bash
# 1. Verify database is running
export DATABASE_URL="postgresql://user:password@localhost:5432/diving"

# 2. Populate FINA dive codes and DD values
python scripts/migrate_dd_values.py --execute

# 3. Preview competition data (dry run)
python scripts/seed_competition_data.py

# 4. Create competition data
python scripts/seed_competition_data.py --execute

# 5. Verify data was created
python scripts/test_competition_queries.py
```

### Development Phase

```bash
# Use test data for dashboard development
# Endpoints available: /api/v1/competitions/

# Verify data integrity at any time
python scripts/test_competition_queries.py

# Reset test data when needed
python scripts/seed_competition_data.py --clean --execute
python scripts/seed_competition_data.py --execute
```

### Cleanup Phase

```bash
# Remove all test data (keep FINA data)
python scripts/seed_competition_data.py --clean --execute

# Verify cleanup
python scripts/test_competition_queries.py
# Should show: "No test competitions found"
```

---

## Data Overview

### Test Data Naming

All test data uses `TEST_*` prefixes for easy identification:
- Events: `TEST_PRELIM_001`, `TEST_SEMI_001`, `TEST_FINAL_001`
- Competitors: All 8 international competitors in each event
- Dives: Standard FINA codes (101B, 201B, 301C, 401C, 5231D)

### Competitors (8 Total)

```
1. Zhang Wei (CHN) - Rank #1
2. Yuki Tanaka (JPN) - Rank #2
3. Tom Daley (GBR) - Rank #3
4. Ingrid Olivares (MEX) - Rank #4
5. Qiu Bo (CHN) - Rank #5
6. Kaylia Nemour (ALG) - Rank #6
7. Andrea Demartini (ITA) - Rank #7
8. Steele Johnson (USA) - Rank #8
```

### Dive Lineup (Per Round)

```
Dive 1: 101B - Forward Somersault (Group 1) - DD: 1.3
Dive 2: 201B - Back Dive (Group 2) - DD: 1.5
Dive 3: 301C - Reverse Dive (Group 3) - DD: 1.7
Dive 4: 401C - Inward Dive (Group 4) - DD: 1.8
Dive 5: 5231D - 1.5 Twists Forward (Group 5) - DD: 2.0
```

### FINA Rules Enforced

- ✓ All 5 mandatory groups required
- ✓ DD limits: Preliminary/Semi-Final = 2.0, Final = 3.5
- ✓ 5 dives per competitor per round
- ✓ Competitor rankings verified
- ✓ Judge panel structure (7 or 11)

---

## Command Reference

### seed_competition_data.py

```bash
# Dry run (preview only)
python scripts/seed_competition_data.py

# Create data
python scripts/seed_competition_data.py --execute

# Clean existing test data (preview)
python scripts/seed_competition_data.py --clean

# Clean and create (one command)
python scripts/seed_competition_data.py --clean --execute

# Clean everything, then create fresh data
python scripts/seed_competition_data.py --clean --execute
python scripts/seed_competition_data.py --execute
```

### test_competition_queries.py

```bash
# Quick statistics
python scripts/test_competition_queries.py

# Detailed information
python scripts/test_competition_queries.py --full

# Validation checks
python scripts/test_competition_queries.py --validate
```

---

## Output Examples

### Dry Run (seed_competition_data.py)

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
... [9 rounds total]

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

### Summary Statistics (test_competition_queries.py)

```
======================================================================
  Competition Data Tests
======================================================================

======================================================================
  Competition Events
======================================================================

✓ Found 3 test competition(s)

  Event: Preliminary Round - Synchronized 3m Women
    Code: TEST_PRELIM_001
    Status: DRAFT
    Rounds: 3
    Competitors: 8
    Total Dive Entries: 120

======================================================================
  Summary Statistics
======================================================================

  Competition Events: 3
  Rounds: 9
  Competitors: 24
  Dive Entries: 360
```

---

## Troubleshooting

### Database Connection Error

```
psycopg2.OperationalError: could not translate host name "postgres" to address
```

**Solution**:
```bash
# Check DATABASE_URL
echo $DATABASE_URL

# Set it if missing
export DATABASE_URL="postgresql://user:password@localhost:5432/diving"

# Verify PostgreSQL is running
# Then retry the script
```

### Foreign Key Error

```
IntegrityError: ForeignKeyViolation
```

**Solution**:
```bash
# Ensure FINA data is populated first
python scripts/migrate_dd_values.py --execute

# Then seed competition data
python scripts/seed_competition_data.py --execute
```

### Duplicate Key Error

```
IntegrityError: UniqueViolation
```

**Solution**:
```bash
# Clean and reseed
python scripts/seed_competition_data.py --clean --execute
python scripts/seed_competition_data.py --execute
```

### Data Inconsistency

```bash
# Verify data integrity
python scripts/test_competition_queries.py --validate

# If issues found, reset and reseed
python scripts/seed_competition_data.py --clean --execute
```

---

## File Locations

```
backend/
├── scripts/
│   ├── README.md                          ← You are here
│   ├── seed_competition_data.py           ← Main seeding script
│   ├── test_competition_queries.py        ← Query and test script
│   ├── SEED_COMPETITION_DATA.md           ← Detailed documentation
│   ├── migrate_dd_values.py               ← DD population script
│   └── ... (other scripts)
└── app/
    ├── models/
    │   └── competition_event.py           ← Data models
    └── ... (rest of app)

Project Root:
└── COMPETITION_DATA_SEEDING.md            ← High-level overview
```

---

## Key Features

| Feature | Details |
|---------|---------|
| **Idempotency** | Safe to run multiple times |
| **Dry-Run** | Preview mode by default |
| **FINA Compliance** | All rules enforced |
| **Validation** | Comprehensive checks |
| **Logging** | Detailed output |
| **Error Handling** | Rollback on failure |
| **Cleanup** | Easy data removal |
| **Documentation** | Extensive guides |

---

## Performance

| Operation | Time |
|-----------|------|
| Dry run | < 1 second |
| Create (fresh) | 2-5 seconds |
| Create (existing) | < 1 second |
| Cleanup | 1-2 seconds |
| Query stats | < 1 second |
| Validation | 2-3 seconds |

---

## Common Workflows

### Testing Dashboard Locally

```bash
# 1. Start with database running
export DATABASE_URL="postgresql://user:password@localhost:5432/diving"

# 2. Ensure FINA data exists
python scripts/migrate_dd_values.py --execute

# 3. Seed test data
python scripts/seed_competition_data.py --execute

# 4. Verify data
python scripts/test_competition_queries.py

# 5. Use dashboard at http://localhost:3000
# 6. View competition data at http://localhost:8000/api/v1/competitions/
```

### Fresh Start After Code Changes

```bash
# Clean and reset everything
python scripts/seed_competition_data.py --clean --execute

# Reseed with fresh data
python scripts/seed_competition_data.py --execute

# Verify
python scripts/test_competition_queries.py
```

### Continuous Development

```bash
# Run once at start of day
python scripts/seed_competition_data.py --execute

# Develop and test
# (Repeat as needed)

# End of day cleanup
python scripts/seed_competition_data.py --clean --execute
```

---

## Documentation

- **SEED_COMPETITION_DATA.md** - Detailed script documentation
- **../COMPETITION_DATA_SEEDING.md** - High-level project overview
- **../CLAUDE.md** - Project-wide guidelines
- **../app/models/competition_event.py** - Data model definitions

---

## Support

For questions or issues:

1. Read the relevant .md file
2. Check script output for specific errors
3. Verify database configuration
4. Ensure FINA data is populated
5. Review model definitions if needed

---

## Next Steps

```bash
# 1. Create initial data
python scripts/seed_competition_data.py --execute

# 2. Test in dashboard
# Visit http://localhost:3000/competitions

# 3. Customize as needed
# Edit scripts to adjust events, competitors, dives

# 4. Integrate with dashboard
# Use /api/v1/competitions/ endpoints
```
