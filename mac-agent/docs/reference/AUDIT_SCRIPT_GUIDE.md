# Data Science Audit Script Guide

## Overview

`dive_audit.py` is a comprehensive Python script that automatically calculates all data quality metrics and psychological bias indicators for your diving analytics data.

This script was designed to automate the manual audit we performed in [DATA_SCIENCE_AUDIT.md](DATA_SCIENCE_AUDIT.md).

---

## Quick Start

### Basic Usage

```bash
python dive_audit.py
```

This runs a complete audit on the default metadata file and outputs results to the console and JSON file.

### With Custom Input/Output

```bash
python dive_audit.py --input dive_metadata_report_final.json --output-dir analytics
```

### Full Detailed Output

```bash
python dive_audit.py --full
```

This prints the complete audit data structure including raw values.

---

## Features

### Temporal Analysis
Tracks how your rating standards have evolved over time:
- **Monthly progression** - Performance metrics for each month
- **Calibration drift** - Detects significant shifts in rating patterns
- **Early vs late period comparison** - Quantifies the magnitude of change

Example output:
```
TEMPORAL CALIBRATION ANALYSIS
  ✓ Calibration drift DETECTED
    Early period: 2024-11 to 2025-02
      Avg performance: 1.44, Failed: 27.4%
    Late period: 2025-07 to 2025-12
      Avg performance: 2.35, Failed: 2.3%
    SHIFT: +0.92 points, Failed: -25.1%
```

### Psychological Bias Detection

#### Central Tendency Bias
Identifies tendency to avoid extreme ratings (Failed/Perfect):
- Compares actual distribution vs expected normal distribution
- Detects underreporting of "Bad" and overreporting of "Good"

#### Recency/Fatigue Analysis
Analyzes within-session patterns:
- Compares first half vs second half of training sessions
- Detects fatigue effects or momentum effects

#### Dive-Specific Patterns
Identifies inconsistency in how specific dives are rated:
- Shows average rating and standard deviation by dive code
- Finds dives with high variance (inconsistent performance)
- Identifies most/least consistent dives

#### Dunning-Kruger Patterns
Detects if you're overconfident about easy dives or underconfident about practiced dives:
- Compares low-attempt dives vs high-attempt dives
- Flags potential overconfidence in learning dives
- Flags potential underconfidence in practiced dives

### Data Quality Assessment

#### Data Capture Analysis
Shows what information is being recorded:
- Percentage of dives with dive code captured (should be 100%)
- Percentage with performance rating (should be 100%)
- Percentage with height recorded (should be 100%)
- Lists 13 critical fields that are NOT captured

#### Dive Code Completeness
- Actual dives vs lineups breakdown
- Identifies that lineups (010, 020) are ~10.9% of data

### Height-Based Analysis
Analyzes performance patterns by training height:
- 1m springboard
- 3m springboard
- 5m platform
- 7m platform

Shows selection bias patterns (conservative dive selection on platform vs exploratory on springboard).

### Statistical Anomalies
Detects unusual patterns:
- **Bad rating underreporting** - If "Bad" appears less than expected
- **Missing months** - If there are gaps in training (e.g., August 2025)
- **Volume anomalies** - Unusual training intensity changes

### Data Validity Assessment
Provides confidence scores for different metrics:

```
✅ DATA VALIDITY ASSESSMENT
  ✓ dive_code_accuracy: High (95% confidence)
  ✓ height_tracking: High (95% confidence)
  ✗ absolute_performance: Low (30% confidence)
  ✓ relative_performance_same_period: Medium (60% confidence)
  ✗ trend_over_time: Low (25% confidence)
  ⚠ dive_specific_comparison: Medium (55% confidence)
  ✗ monthly_progression: Low (30% confidence)
```

---

## Output Files

### Console Output
Formatted report printed to terminal showing key findings.

### JSON Report
`analytics/diving_audit_report.json` - Structured data containing:

```json
{
  "metadata": {
    "generated": "2026-01-08T10:22:10.397852",
    "total_personal_dives": 1290,
    "actual_dives": 1150,
    "lineups": 140,
    "date_range": {...}
  },
  "temporal_analysis": {
    "monthly_progression": [...],
    "calibration_shift": {...}
  },
  "psychological_biases": {
    "central_tendency": {...},
    "recency_fatigue": {...},
    "dive_specific_patterns": {...},
    "dunning_kruger": {...}
  },
  "data_capture": {...},
  "height_analysis": {...},
  "statistical_anomalies": {...},
  "validity_assessment": {...}
}
```

---

## Using the Output

### For Understanding Your Data

1. **Check calibration_shift** - Are your standards evolving? By how much?
2. **Check central_tendency** - Are you avoiding extreme ratings?
3. **Check validity_assessment** - Which metrics can you trust?

### For Future Improvements

1. Review **dive_specific_patterns** to identify inconsistent dives
2. Use **data_capture** to see what critical fields are missing
3. Check **statistical_anomalies** for data quality issues

### For Implementing Audit Improvements

The audit identifies areas for improvement:
1. Recalibrate using anchoring examples
2. Add missing data fields (DD, coach assessment)
3. Implement component ratings (entry/execution)

---

## Integration with Other Scripts

### DivingAudit Class

You can import and use the `DivingAudit` class in other scripts:

```python
from dive_audit import DivingAudit
import json

# Load audit
audit = DivingAudit('dive_metadata_report_final.json')

# Get specific analysis
temporal = audit.temporal_calibration_analysis()
biases = audit.central_tendency_bias_analysis()
validity = audit.validity_assessment()

# Generate full report
full_report = audit.generate_full_audit_report()
```

### With Analytics Pipeline

Run after updating metadata:

```bash
# Extract data
python batch_extract_metadata.py --library "..." --output dive_metadata_report_final.json

# Run audit
python dive_audit.py

# Run analytics
python dive_analytics.py
```

---

## Interpreting Results

### Calibration Drift

**Finding:** Rating shift of +0.92 points over time

**Interpretation:** Your internal standard for "Good" has risen. What was "Good" in Nov 2024 might be "Medium" in Dec 2025.

**Action:** Use relative rating (vs personal best) instead of absolute ratings for long-term tracking.

### Central Tendency Bias

**Finding:** Bad is underreported by 12.3%, Good is overreported by 8.3%

**Interpretation:** You're psychologically avoiding the "Bad" label (self-image protection) and gravitating toward "Good" (humility bias).

**Action:** Implement anchoring examples to standardize rating thresholds.

### Dunning-Kruger Patterns

**Finding:** Low-attempt dives (learning) rated differently than high-attempt dives (practiced)

**Interpretation:** Possible over/underconfidence affecting ratings on different dive types.

**Action:** Track confidence separately or use coach validation.

### Validity Scores

**High Confidence (≥80%):** Use these metrics for analysis
**Medium Confidence (40-79%):** Use with caution, acknowledge limitations
**Low Confidence (<40%):** Do not use for decision-making without external validation

---

## Advanced Usage

### Running Audits for Specific Subsets

Modify the script to audit only certain periods or dive types:

```python
audit = DivingAudit('dive_metadata_report_final.json')

# Analyze only actual dives (excluding lineups)
actual_only = [d for d in audit.personal_dives if not d['dive_code'].startswith('0')]

# Analyze only certain height
springboard_only = [d for d in audit.personal_dives if d['height'] in ['1m', '3M']]
```

### Generating Historical Audits

Store audit reports over time to track how data quality metrics evolve:

```bash
# Monthly audit runs
for month in $(seq -w 1 12); do
  python dive_audit.py --output-dir "analytics/audits/2026_$month"
done
```

---

## Troubleshooting

### No calibration shift detected

- **Cause:** Dataset is too small or rating patterns are consistent
- **Solution:** This is actually good! Means your ratings are well-calibrated

### Missing statistical anomalies

- **Cause:** Your data is clean with no obvious issues
- **Solution:** This is good! No data quality red flags

### Very low validity scores

- **Cause:** Calibration drift or central tendency bias is significant
- **Solution:** Implement anchoring examples or switch to relative rating

---

## See Also

- [DATA_SCIENCE_AUDIT.md](DATA_SCIENCE_AUDIT.md) - Manual audit findings and interpretation guide
- [LINEUP_SEPARATION_REPORT.md](LINEUP_SEPARATION_REPORT.md) - Impact of separating lineups
- [dive_analytics.py](dive_analytics.py) - Performance analytics engine
- [README_ANALYTICS_SETUP.md](README_ANALYTICS_SETUP.md) - Complete system guide

---

## Script Details

- **File:** `dive_audit.py`
- **Lines:** 620+
- **Classes:** `DivingAudit` - Main audit class
- **Methods:** 15+ specialized audit functions
- **Output:** Console + JSON
- **Dependencies:** json, statistics, collections, datetime, pathlib, argparse

**Status:** Production ready ✅

Run audits regularly to track data quality over time!
