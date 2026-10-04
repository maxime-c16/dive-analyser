# Usage Guide

## Initial Setup

### 1. Install Dependencies

```bash
# Navigate to project root
cd /Users/mcauchy/diving-analyser

# Create virtual environment
python3.12 -m venv venv
source venv/bin/activate

# Install required packages
pip install -r requirements.txt
```

### 2. Configure Cron (Automated Weekly Runs)

```bash
bash scripts/setup_cron.sh
```

This will prompt you to choose when the analysis runs:
- **Option 1 (default):** Monday 2 AM
- **Option 2:** Sunday 3 AM
- **Option 3:** Friday 6 PM
- **Option 4:** Custom schedule

The script will:
- Make `weekly_scan.sh` executable
- Update your crontab entry
- Show the installed cron job

### 3. Manual First Run (Optional)

```bash
bash scripts/weekly_scan.sh
```

This runs the complete 6-stage pipeline once.

## Usage Scenarios

### Run Everything Automatically

**Setup once:**
```bash
bash scripts/setup_cron.sh
```

**Then:** Pipeline runs every week on your chosen day at the chosen time.

**Check if running:**
```bash
crontab -l | grep diving
```

**View logs:**
```bash
tail -f logs/*.log
```

### Run Everything Manually

```bash
bash scripts/weekly_scan.sh
```

Output: Full pipeline transcript + all reports

### Extract Metadata Only

```bash
source venv/bin/activate
python src/batch_extract_metadata.py \
  --library "/Users/mcauchy/Pictures/Photos Library.photoslibrary" \
  --output "reports/dive_metadata_$(date +%Y%m%d).json"
```

Output: `reports/dive_metadata_YYYYMMDD.json` (4.7 MB)

### Generate Analytics Only

```bash
source venv/bin/activate
python src/dive_analytics.py \
  --input "dive_metadata_report_final.json" \
  --output-dir "reports/analytics_$(date +%Y%m%d)"
```

Output:
- `reports/analytics_YYYYMMDD/diving_analytics_full.json`
- `reports/analytics_YYYYMMDD/diving_analytics_summary.csv`

### Run Audit Only

```bash
source venv/bin/activate
python src/dive_audit.py \
  --input "dive_metadata_report_final.json" \
  --output-dir "reports/analytics_$(date +%Y%m%d)/audit"
```

Output: `reports/analytics_YYYYMMDD/audit/diving_audit_report.json`

### Generate Visualizations Only

```bash
source venv/bin/activate
python src/dive_visualizations.py \
  --input "reports/analytics_$(date +%Y%m%d)/diving_analytics_full.json" \
  --output-dir "reports/analytics_$(date +%Y%m%d)"
```

Output: 8 PNG visualization files

### View Latest Reports

```bash
# Open latest analytics dashboard
open reports/analytics_*/dashboard.png

# View latest audit report (JSON)
cat reports/analytics_*/audit/diving_audit_report.json | python -m json.tool

# View summary statistics
cat reports/summary_*.txt
```

## Understanding the Reports

### Metadata Report (`dive_metadata_YYYYMMDD.json`)

**What it contains:** Raw dive data from your Photos library

**Key sections:**
```json
{
  "metadata": {
    "total_personal_dives": 1297,
    "actual_dives": 1157,        # Excludes lineups
    "lineups": 140,              # Formation drills (0xx codes)
    "date_range": { "start": "2024-10-30", "end": "2026-01-06" }
  },
  "valid_dive_videos": [
    {
      "dive_code": "201C",
      "performance": "G",        # F/B/M/G/P
      "height": "1m",            # 1m/3m/5m/7m
      "date": "2025-11-20",
      "person": null,            # null = your dive, name = someone else
      "is_sync": false,
      "is_smack": false,
      "is_lineup": false
    }
  ]
}
```

**Size:** ~4.7 MB (large because includes all video metadata)

**Retention:** Kept for 12 weeks, then auto-deleted

### Analytics Report (`diving_analytics_full.json`)

**What it contains:** Computed performance metrics and statistics

**Key sections:**
```json
{
  "metadata": { counts and date range },
  "overall_performance": {
    "total_dives": 1157,
    "average_performance": 2.11,
    "success_rate": 77.2,
    "perfect_rate": 5.9,
    "std_dev": 0.97
  },
  "by_height": {
    "1m": { count: 718, avg_performance: 2.08, success_rate: 76.2 },
    "3m": { count: 391, avg_performance: 2.09, success_rate: 81.1 },
    "5m": { count: 159, avg_performance: 2.68, success_rate: 95.6 },
    "7m": { count: 29, avg_performance: 2.69, success_rate: 96.6 }
  },
  "by_dive_code": {
    "201C": { attempts: 284, avg_performance: 2.28, success_rate: 81.0 },
    ...
  },
  "monthly_progression": {
    "2024-11": { count: 22, avg_performance: 1.23, ... },
    "2024-12": { count: 29, avg_performance: 1.28, ... },
    ...
  },
  "actual_dives_only": {
    ...same metrics excluding lineups...
  }
}
```

**Size:** ~18 KB

**Usage:** Data source for visualizations and audits

### Audit Report (`diving_audit_report.json`)

**What it contains:** Data quality analysis and bias detection

**Key sections:**
```json
{
  "calibration_shift": {
    "detected": true,
    "early_avg": 1.44,              # Nov 2024-Feb 2025
    "late_avg": 2.44,               # Sep 2025-Jan 2026
    "rating_shift": 1.0
  },
  "psychological_biases": {
    "central_tendency": {
      "extreme_ratings_actual": 13.3,
      "extreme_ratings_expected": 13.4,
      "distribution": {
        "Bad": { "actual": 12.0, "expected": 24.2 },
        "Good": { "actual": 32.5, "expected": 24.2 }
      }
    }
  },
  "validity_assessment": {
    "dive_code_accuracy": { validity: "High", confidence: 95 },
    "trend_over_time": { validity: "Low", confidence: 25 },
    "absolute_performance": { validity: "Low", confidence: 30 }
  }
}
```

**Size:** ~12 KB

**Interpretation:**
- Calibration shift +1.0 = you're rating yourself 1 point higher now than early 2025
- Central tendency = slight avoidance of "Bad" rating, slight over-reporting of "Good"
- Validity scores tell you which metrics are trustworthy (95% = very trustworthy, 25% = use with caution)

### Visualization Charts

**Performance Distribution**
- Bar chart of F/B/M/G/P counts
- Shows spread of performance ratings

**Height Comparison**
- Bars for each height (1m, 3m, 5m, 7m)
- Shows average performance improves at higher heights
- Higher platform dives typically easier

**Monthly Progression**
- Line chart showing average performance each month
- Trend line shows overall improvement (calibration shift)
- Recent months show higher averages

**Specialization**
- Top 10 most-practiced dives
- 201C most common (284 attempts)
- Shows your focus areas

**Platform vs Springboard**
- Comparison of the two position types
- Platform: typically higher because you're selective
- Springboard: more exploratory

**Consistency Scatter**
- X-axis: number of attempts
- Y-axis: average performance
- Shows improvement correlation with practice

**Session Comparison**
- Last 4 training days
- Each subplot shows that day's performance distribution
- Compare trends across recent sessions

**Dashboard**
- Comprehensive overview of all key metrics
- 7 panels + summary box
- Use for quick status check

## Troubleshooting

### Python Virtual Environment Issues

**Problem:** `python src/dive_analytics.py` fails with module not found

**Solution:**
```bash
# Make sure you've activated venv
source venv/bin/activate

# Verify matplotlib installed
pip install matplotlib seaborn numpy

# Or reinstall everything
pip install -r requirements.txt
```

### Cron Job Not Running

**Check if installed:**
```bash
crontab -l | grep diving
```

**Check if it ran:**
```bash
ls -la logs/ | tail -5
```

**Check errors:**
```bash
tail -100 logs/weekly_scan_*.log
```

**Reinstall:**
```bash
bash scripts/setup_cron.sh
# Choose option 1 (Monday 2 AM)
```

### No Recent Analytics

**Problem:** Analytics folder is empty

**Solution:**
```bash
# Run extraction first
python src/batch_extract_metadata.py \
  --library "/Users/mcauchy/Pictures/Photos Library.photoslibrary" \
  --output "reports/dive_metadata_$(date +%Y%m%d).json"

# Then run analytics
python src/dive_analytics.py \
  --input "dive_metadata_report_final.json" \
  --output-dir "reports/analytics_$(date +%Y%m%d)"
```

### Charts Not Generated

**Problem:** PNG files missing, but JSON generated

**Solution:** Visualization generation might have warnings. Check if files exist:
```bash
ls -la reports/analytics_*/

# If PNG files exist but are 0 bytes, check matplotlib:
python src/dive_visualizations.py \
  --input "reports/analytics_20260108/diving_analytics_full.json" \
  --output-dir "reports/analytics_20260108"
```

## Data Maintenance

### View Directory Sizes

```bash
# What's taking space?
du -sh reports/
du -sh logs/
du -sh data/archive/

# Clean up old metadata (keep 12 weeks)
find reports -name "dive_metadata_*.json" -mtime +84
```

### Archive Old Data

```bash
# Move old metadata to archive
mv reports/dive_metadata_*.json data/archive/

# Keep only latest reports
```

### Regenerate Latest Analysis

```bash
# Use latest metadata
python src/dive_analytics.py \
  --input "dive_metadata_report_final.json" \
  --output-dir "reports/analytics_$(date +%Y%m%d)"
```

## Integration with Other Tools

### Export to CSV

```bash
# Analytics summary is already CSV
cat reports/analytics_20260108/diving_analytics_summary.csv

# Convert metadata to CSV
python -c "
import json
import csv
with open('dive_metadata_report_final.json') as f:
    data = json.load(f)
with open('dives_export.csv', 'w') as f:
    w = csv.DictWriter(f, fieldnames=['dive_code', 'performance', 'height', 'date'])
    w.writeheader()
    for dive in data['valid_dive_videos']:
        if not dive.get('person'):
            w.writerow({k: dive.get(k) for k in ['dive_code', 'performance', 'height', 'date']})
"
```

### View JSON with Pretty Print

```bash
# Pretty print audit report
python -m json.tool < reports/analytics_20260108/audit/diving_audit_report.json

# Count specific performance level
python -c "
import json
with open('dive_metadata_report_final.json') as f:
    data = json.load(f)
    perfs = {}
    for dive in data['valid_dive_videos']:
        if not dive.get('person'):
            p = dive.get('performance', 'U')
            perfs[p] = perfs.get(p, 0) + 1
    for p in 'FBMGP':
        print(f'{p}: {perfs.get(p, 0)}')"
```

## Performance Tips

### Speed Up Analytics

For testing with fewer dives:
```bash
# Filter metadata first
python -c "
import json
with open('dive_metadata_report_final.json') as f:
    data = json.load(f)
    # Keep only recent dives
    data['valid_dive_videos'] = data['valid_dive_videos'][-500:]
    with open('recent_dives.json', 'w') as out:
        json.dump(data, out)
"

# Then analyze subset
python src/dive_analytics.py --input recent_dives.json --output-dir test_output/
```

### Parallel Execution

For faster weekly runs, could run stages in parallel:
```bash
# Run all 3 Python scripts in background
python src/dive_analytics.py --input dive_metadata_report_final.json --output-dir reports/analytics_$(date +%Y%m%d) &
python src/dive_audit.py --input dive_metadata_report_final.json --output-dir reports/analytics_$(date +%Y%m%d)/audit &
python src/dive_visualizations.py --input reports/analytics_$(date +%Y%m%d)/diving_analytics_full.json --output-dir reports/analytics_$(date +%Y%m%d) &
wait
```

## Questions?

For technical details, see:
- `docs/ARCHITECTURE.md` - How the system works
- `docs/reference/` - Additional documentation
- `src/*.py` - Source code with comments
