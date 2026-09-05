# Diving Analyser

A comprehensive data science system for tracking, analyzing, and auditing personal diving performance.
Extracts dive data from your Photos library, performs detailed analytics, and identifies calibration drift, biases, and performance trends.

## Features

- **🎬 Automated Metadata Extraction** - Scans your Photos library for dive videos with performance captions
- **📊 Comprehensive Analytics** - Performance metrics, height analysis, dive specialization tracking
- **🔍 Data Science Audit** - Detects calibration drift, psychological biases, and statistical anomalies
- **📈 8 Visualization Charts** - Performance distributions, trends, session comparisons, and more
- **🤖 Scheduled Automation** - Weekly automated pipeline via cron job
- **📋 Lineup Separation** - Distinguishes training lineups (0xx codes) from actual dives

## Quick Start

```bash
# Install dependencies
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run once manually
bash scripts/weekly_scan.sh

# Or setup automated weekly runs
bash scripts/setup_cron.sh
```

## What Each Component Does

### Phase 1: Extraction (`src/batch_extract_metadata.py`)
- Scans Photos library (Sept 1, 2024 onwards)
- Extracts dive captions: format `[DIVE_CODE PERF HEIGHT] [PERSON_NAME]`
- Generates metadata JSON with 1,300+ personal dives

### Phase 2: Analytics (`src/dive_analytics.py`)
- Computes performance metrics by height, dive code, date
- Separates lineups from actual dives
- Tracks success rates, consistency, specialization

### Phase 3: Audit (`src/dive_audit.py`)
- Detects calibration drift over time
- Identifies central tendency bias (under/over-rating)
- Analyzes recency effects and dunning-kruger patterns
- Generates confidence scores for each metric

### Phase 4: Visualizations (`src/dive_visualizations.py`)
- **performance_distribution.png** - Rating distribution (F/B/M/G/P)
- **height_comparison.png** - Performance by training height
- **monthly_progression.png** - 14-month trend with best fit
- **specialization.png** - Top 10 most-practiced dives
- **platform_vs_springboard.png** - Position type comparison
- **consistency_scatter.png** - Performance vs attempts
- **session_comparison.png** - Last 4 training sessions
- **dashboard.png** - Comprehensive overview

## Directory Structure

```
diving-analyser/
├── docs/                      # Documentation
│   ├── README.md (this file)
│   ├── ARCHITECTURE.md        # System design
│   ├── USAGE.md              # Detailed usage guide
│   └── reference/            # Technical reference docs
├── src/                       # Python source code
│   ├── batch_extract_metadata.py
│   ├── dive_analytics.py
│   ├── dive_audit.py
│   ├── dive_visualizations.py
│   └── dive_video_filter.py
├── scripts/                   # Shell automation scripts
│   ├── weekly_scan.sh        # Main automated pipeline
│   └── setup_cron.sh         # Cron job configuration
├── data/                      # Data storage
│   ├── raw/                  # Raw extracted metadata
│   ├── processed/            # Processed data
│   └── archive/              # Old/backup data
├── reports/                   # Generated reports
│   ├── analytics_YYYYMMDD/   # Daily analytics
│   │   ├── charts/           # 8 visualization PNG files
│   │   ├── data/             # JSON and CSV metrics
│   │   └── audit/            # Audit findings
│   └── summary_YYYYMMDD.txt  # Text summary
├── logs/                      # Execution logs
├── venv/                      # Python virtual environment
└── requirements.txt           # Dependencies
```

## Output Files

Each weekly run generates:

### Metadata (`reports/dive_metadata_YYYYMMDD.json`)
- Raw extraction from Photos library
- 1,300+ total dives, 1,157 actual + 140 lineups
- All video metadata, captions, dates

### Analytics (`reports/analytics_YYYYMMDD/`)
- `diving_analytics_full.json` - All metrics
- `diving_analytics_summary.csv` - Quick reference
- `charts/` - 8 PNG visualization files
- `audit/diving_audit_report.json` - Audit findings

### Summary (`reports/summary_YYYYMMDD.txt`)
- Quick stats: total dives, yours vs others
- Extraction date range

### Logs (`logs/weekly_scan_YYYYMMDD_HHMMSS.log`)
- Full pipeline execution transcript

## Understanding the Data

### Performance Ratings
- **F (Failed)** - Dive didn't complete
- **B (Bad)** - Incomplete but controlled
- **M (Medium)** - Acceptable completion
- **G (Good)** - Clean execution
- **P (Perfect)** - Excellent with no corrections

### Dive Heights
- **1m** - Spring board (low)
- **3m** - Spring board (medium)
- **5m** - Platform (medium-high)
- **7m** - Platform (high)

### Dive Codes (FINA Notation)
- Format: `[DIGITS][LETTER]` e.g., `101B`, `305C`, `3mP`
- First digit: position (1=forward, 2=backward, 3=inward, etc.)
- Letter suffix: shape (A-D variants) or platform (P)

### Special Tags
- **SYNC** - Synchronized dive (pair diving)
- **SMACK** - Involuntary belly flop / failed entry

### Lineups
- Codes starting with `0` (e.g., `010`, `020`) are formation drills
- Not counted in actual dive metrics
- Tracked separately for training analysis

## Audit Findings

Each audit identifies:
1. **Calibration Drift** - Systematic shift in rating standards (+1.0 points detected)
2. **Central Tendency Bias** - Avoidance of extreme ratings
3. **Selection Bias** - Conservative vs exploratory training patterns
4. **Recency Effects** - Within-session fatigue or improvement
5. **Data Quality Issues** - Missing fields, anomalies
6. **Validity Scores** - Confidence levels for each metric (25-95%)

## For More Information

- `docs/ARCHITECTURE.md` - System design and decisions
- `docs/USAGE.md` - Detailed usage and examples
- `docs/reference/` - Technical documentation and reports
- `src/*.py` - Source code with inline documentation

---

**Last Updated:** January 8, 2026
**Status:** Automated weekly pipeline running
**Next Run:** Monday 2 AM (via cron)
