# Diving Analytics & Automation Setup Guide

## Overview

This system provides comprehensive data science analysis of your acrobatic diving performance with automated weekly scanning and reporting.

### What's Included

1. **Batch Extraction** (`batch_extract_metadata.py`)
   - Scans Photos library for diving videos
   - Parses captions into structured dive data
   - Categorizes lineups, open pike, synchro, and belly flops
   - Separates your dives from training partners

2. **Data Science Analytics** (`dive_analytics.py`)
   - Performance metrics and trends
   - Height-based analysis
   - Dive code specialization
   - Consistency metrics
   - Monthly progression tracking
   - Platform vs springboard comparison

3. **Automated Scanning** (`weekly_scan.sh`)
   - Automatic weekly Photos library scan
   - Fresh metadata extraction
   - Analytics report generation
   - Automatic cleanup of old reports
   - Logging of all operations

4. **Cron Job Setup** (`setup_cron.sh`)
   - Interactive setup for automated weekly runs
   - Configurable schedule
   - Full logging support

---

## Quick Start

### 1. Set Up Automated Weekly Scanning

```bash
cd /Users/mcauchy/diving-analyser
bash setup_cron.sh
```

This will:
- Ask you when to run the weekly analysis
- Set up a cron job to automatically scan and analyze your library
- Create logs and reports directories

### 2. Run Your First Analysis

```bash
python dive_analytics.py --input dive_metadata_report_final.json --output-dir analytics
```

### 3. View Your Reports

- **Console summary:** Printed directly to console
- **JSON report:** `analytics/diving_analytics_full.json` (complete data)
- **CSV summary:** `analytics/diving_analytics_summary.csv` (spreadsheet-friendly)

---

## Key Metrics Explained

### Overall Performance

- **Average Performance:** 0-4 scale (4=Perfect, 0=Failed)
- **Success Rate:** % of dives rated Medium or better
- **Perfect Rate:** % of dives rated Perfect
- **Standard Deviation:** Consistency indicator (lower = more consistent)

### By Height

Performance analysis for each training height:
- **1m** - Primary springboard training
- **3m** - Advanced springboard
- **5m** - Platform training
- **7m** - Higher platform
- **10m** - Elite platform

### Specialization

Your most-practiced dives:
- **Attempts:** Total repetitions
- **% of training:** What fraction of your training this represents
- **Avg performance:** Your average score on this dive
- **Success rate:** % of successful attempts
- **Improvement potential:** How much room to grow (4 = perfect)

### Consistency

How reliable your dives are:
- Score 0-100 (100 = perfect consistency)
- Based on standard deviation of repeated dives
- Only calculated for dives attempted 3+ times

### Monthly Progression

Tracks improvement over time:
- Total dives per month
- Average monthly performance
- Month-to-month improvement (positive = getting better)

### Platform vs Springboard

Comparison of performance on different equipment:
- Count of dives
- Average performance
- Consistency score
- Success rate

---

## Analysis Interpretation Guide

### 🎯 What Strong Metrics Look Like

**Perfect Performance Profile:**
- Average Performance: 3.0+
- Success Rate: 90%+
- Consistency: 85%+
- Clear specialization in 2-3 dives

**Good Progression:**
- Monthly improvements trending upward
- Platform average higher than springboard (harder)
- Consistency improving over time

**Strength in Specialization:**
- Top dives attempted 100+ times
- High success rate on specialized dives (85%+)
- Clear focus on specific dive codes

### 🚨 What to Watch For

**Areas Needing Work:**
- Success rate below 70%
- High standard deviation (inconsistency)
- No progress in monthly trends
- Large gap between platform and springboard

**Training Gaps:**
- Few 5m+ platform dives (should be 10%+ of training)
- No synchro practice (if that's a goal)
- Unbalanced focus (one dive taking >25% of training)

---

## Data Files Structure

```
diving-analyser/
├── dive_metadata_report_final.json      # Latest dive data (updated weekly)
├── analytics/
│   ├── diving_analytics_full.json       # Complete analysis (JSON)
│   └── diving_analytics_summary.csv     # Summary (spreadsheet)
├── reports/
│   ├── dive_metadata_20250107.json      # Daily snapshots
│   ├── analytics_20250107/              # Daily analysis
│   │   ├── diving_analytics_full.json
│   │   └── diving_analytics_summary.csv
│   └── summary_20250107.txt             # Quick summary
├── logs/
│   └── weekly_scan_20250107_020000.log  # Execution logs
└── ...
```

---

## Running Analyses Manually

### Full Analysis
```bash
python dive_analytics.py --input dive_metadata_report_final.json --output-dir analytics
```

### Fresh Library Scan + Analysis
```bash
bash weekly_scan.sh
```

### Just Extract Metadata
```bash
python batch_extract_metadata.py --library "/Users/mcauchy/Pictures/Photos Library.photoslibrary" \
  --output dive_metadata_fresh.json
```

---

## Cron Job Management

### View Scheduled Jobs
```bash
crontab -l | grep diving
```

### Edit or Remove Cron Job
```bash
crontab -e
# Find the diving-analyser line and edit/delete it
```

### Manually Trigger Weekly Scan
```bash
/Users/mcauchy/diving-analyser/weekly_scan.sh
```

### View Scan Logs
```bash
tail -f /Users/mcauchy/diving-analyser/logs/weekly_scan*.log
```

---

## Technical Details

### Virtual Environment
- Python 3.12 with osxphotos and dependencies
- Located in `venv/` directory
- Created during initial setup

### Data Format

**Dive Metadata JSON Structure:**
```json
{
  "dive_code": "101B",
  "performance": "M",
  "height": "3M",
  "platform_type": "springboard",
  "sync": false,
  "smack": false,
  "date": "2025-01-07T10:30:00+01:00",
  "filename": "IMG_1234.mov",
  ...
}
```

**Analytics Report Structure:**
```json
{
  "metadata": {...},
  "overall_performance": {...},
  "by_height": {...},
  "by_dive_code": {...},
  "platform_vs_springboard": {...},
  "monthly_progression": {...},
  "specialization": {...},
  "synchro_and_belly_flops": {...},
  "consistency": {...}
}
```

---

## Research Resources

The analysis system is based on research in diving performance metrics and acrobatic sports analytics:

- [World Aquatics Diving Scoring System](https://www.worldaquatics.com/diving)
- [Diving Performance Analysis Research](https://journals.sagepub.com/doi/10.1177/19417381241255329)
- [Judge Scoring Data Quality Analysis](https://www.frontiersin.org/journals/psychology/articles/10.3389/fpsyg.2024.1338405/full)
- [Multidimensional Performance Prediction](https://pmc.ncbi.nlm.nih.gov/articles/PMC9401130/)
- [Form Swim Progress Tracking](https://www.formswim.com/blogs/all/tracking-progress-swimming)

---

## Customization

### Modify Analysis Schedule
Edit `setup_cron.sh` to change available time options, or run:
```bash
crontab -e
# Manually edit the diving-analyser line
```

### Adjust Data Retention
In `weekly_scan.sh`, modify the cleanup line:
```bash
find "${REPORT_DIR}" -name "dive_metadata_*.json" -mtime +84 -delete
```
- `+84` = keep last 84 days (~12 weeks)
- Change to `+180` for 6 months, `+30` for 1 month, etc.

### Custom Analytics
Edit `dive_analytics.py` to add:
- New performance metrics
- Custom visualizations (matplotlib/plotly)
- Email notifications
- Database storage

---

## Troubleshooting

### "No module named 'osxphotos'"
```bash
source venv/bin/activate
pip install osxphotos
```

### Cron job not running
1. Check if task scheduler is available: `ls -la /usr/sbin/periodic`
2. Verify cron is running: `sudo launchctl list | grep -i cron`
3. Check for errors: `log stream --predicate 'process == "cron"'`

### Photos library not found
Verify path:
```bash
ls -d ~/Pictures/Photos\ Library.photoslibrary
# Update PHOTOS_LIBRARY in weekly_scan.sh if different
```

### Reports not generating
1. Check logs: `tail -f logs/weekly_scan*.log`
2. Verify Python path: `which python` vs using `venv/bin/python`
3. Ensure sufficient disk space

---

## Git Setup

Before pushing to GitHub:

1. **Verify .gitignore**
   ```bash
   git check-ignore -v *
   ```

2. **Add files to git**
   ```bash
   git add dive_analytics.py weekly_scan.sh setup_cron.sh .gitignore README_ANALYTICS_SETUP.md
   git add FINAL_TRIAGE_REPORT.md BATCH_EXTRACTION_REPORT.md
   ```

3. **Review changes**
   ```bash
   git status
   git diff --cached
   ```

4. **Commit**
   ```bash
   git commit -m "Add comprehensive analytics and automation system"
   ```

5. **Push to GitHub**
   ```bash
   git push origin main
   ```

---

## Support & Questions

For detailed information about:
- **Dive codes:** See `FINAL_TRIAGE_REPORT.md`
- **Data format:** See `CLAUDE.md`
- **Batch extraction:** See `BATCH_EXTRACTION_REPORT.md`
- **Initial setup:** See `README_BATCH_EXTRACTION.md`

---

**Last Updated:** January 7, 2026
**System Version:** 1.0
**Compatible:** Python 3.12+, macOS 10.13+
