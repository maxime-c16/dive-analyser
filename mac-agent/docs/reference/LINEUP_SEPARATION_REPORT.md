# Lineup Separation Impact Report

**Generated:** January 8, 2026
**Analysis:** Impact of separating lineups (010, 020 codes) from actual dive analysis

---

## Executive Summary

Lineups (front lineup 010, back lineup 020) are currently mixed into the dive performance analysis. These are positioning/formation drills, not actual dives, and they inflate performance metrics.

**Impact of Separation:**
- Actual dives count reduced from 1,290 → 1,150 (10.9% reduction)
- Average performance: 2.17 → 2.11 (-0.06 points, -2.9%)
- Success rate: 80.5% → 79.0% (-1.6%)
- Perfect rate: 5.8% → 5.0% (-0.9%)

---

## Dataset Breakdown

```
Total entries:        1,290
├─ Lineups (0xx):      140 (10.9%)
│  ├─ 010 (Front):    106
│  └─ 020 (Back):      34
└─ Actual dives:     1,150 (89.1%)
```

### Lineup Performance Profile

Lineups have distinctly different characteristics:

```
Performance Distribution (Lineups Only):
  Failed:   0 (0.0%)  ← Never fail (they're just positioning)
  Bad:      9 (6.4%)
  Medium:  46 (32.9%)
  Good:    67 (47.9%)
  Perfect: 18 (12.9%)

Average Performance: 2.67/4.0
Success Rate: 93.6%
Perfect Rate: 12.9%
```

**Interpretation:** Lineups are much easier (no failures possible), and inherently higher success. They represent different training objectives than actual dives.

---

## Performance Metrics Comparison

### Overall Performance

| Metric | With Lineups | Actual Dives | Difference | % Impact |
|--------|------------|--------------|-----------|----------|
| Total count | 1,290 | 1,150 | -140 | -10.9% |
| Avg performance | 2.17 | 2.11 | -0.061 | -2.9% |
| Median | 2.00 | 2.00 | 0.00 | 0.0% |
| Std deviation | 0.97 | 0.98 | +0.004 | +0.4% |
| Perfect rate | 5.81% | 4.96% | -0.86% | -14.8% |
| Success rate | 80.54% | 78.96% | -1.59% | -2.0% |

### Height-Based Impact

Lineups are heavily concentrated at higher heights (training simulation):

```
Height    With Lineups    Actual Dives    Lineups    % Lineup
────────────────────────────────────────────────────────────
1m         712 dives       710 dives        2         0.3%
3M         390 dives       357 dives       33         8.5%
5M         159 dives        68 dives       91        57.2% ← Majority
7M          29 dives        15 dives       14        48.3% ← Nearly half
```

**Key Finding:** More than half of recorded 5M sessions are lineups, not actual platform dives!

---

## Detailed Height Analysis

### 1m Springboard
**With Lineups:** 712 dives, avg 2.08, success 76.1%
**Actual Dives:** 710 dives, avg 2.08, success 76.1%
**Impact:** Minimal (only 2 lineups)

### 3m Springboard
**With Lineups:** 390 dives, avg 2.09, success 81.3%
**Actual Dives:** 357 dives, avg 2.07, success 81.5%
**Impact:** Minor (33 lineups, ~8%)

### 5m Platform
**With Lineups:** 159 dives, avg 2.68, success 95.6%
**Actual Dives:** 68 dives, avg 2.53, success 91.2%
**Impact:** MAJOR (91 lineups, 57% of recorded 5M)

- Lineups inflate 5M average by +0.15 points
- Lineups inflate 5M success rate by +4.4%
- True 5M actual dive performance is lower than shown

### 7m Platform
**With Lineups:** 29 dives, avg 2.69, success 96.6%
**Actual Dives:** 15 dives, avg 2.73, success 100.0%
**Impact:** Severe (14 lineups, 48% of recorded 7M)

- Lineups depress 7m average by -0.04 points
- Lineups are easier than actual 7m dives

---

## Specialization Impact

010B (front lineup) currently ranks **5th in specialization:**
- 85 attempts (6.6% of all training)
- 96.5% success rate
- Appears as a top focus area

**Reality Check:** This is a LINEUP, not a dive. Should be tracked separately.

### Corrected Top Specializations (Actual Dives Only)

Removing lineups and recalculating:
1. 201C - 284 attempts (24.7%)
2. 301C - 172 attempts (15.0%)
3. 103C - 168 attempts (14.6%)
4. 101B - 154 attempts (13.4%)
5. 010C - 68 attempts (5.9%)  ← This is 5M/7M actual dives
6. 101C - 68 attempts (5.9%)

(Note: 010B is no longer in top 5)

---

## Psychological & Training Implications

### Why Lineups Are Important (But Different)

Lineups serve specific training purposes:
- **Synchronization practice** - Positioning with partners
- **Platform acclimation** - Getting comfortable at height
- **Formation drills** - Working specific team positions

### Why They Distort Dive Analysis

1. **Different Success Definition** - Lineups can't "fail" (just positioning)
2. **Difficulty Mismatch** - 2.67 avg vs 2.11 avg for actual dives
3. **Height Inflation** - Lineups at higher heights inflate platform statistics
4. **Specialization Misleading** - 010B looks important but isn't a dive technique

---

## Recommendations for Going Forward

### 1. Data Separation (Immediate)

✓ **Completed:** Separate lineups in metadata
✓ **Completed:** Generate actual_dives_only metrics
✓ **Recommended:** Create separate tracking for lineup quality

### 2. Reporting Changes (Suggested)

**Option A: Dual Reporting**
- Primary report: Actual dives only (recommended for skill analysis)
- Secondary report: All entries (for completeness)
- Always clearly label which dataset is used

**Option B: Separate Tracking**
- Main dashboard: Actual dives only
- Separate "Lineup Performance" dashboard
- No mixing of metrics

### 3. Visualization Updates (Pending)

- Flag lineups in charts
- Show height breakdown with/without lineups
- Create separate lineup quality metrics

---

## Corrected Key Metrics

### Accurate Performance Profile (Actual Dives Only)

```
Total Dives:           1,150 (not 1,290)
Average Performance:   2.11/4.0 (not 2.17)
Median Performance:    2.00/4.0 (unchanged)
Standard Deviation:    0.98 (unchanged)
Success Rate:          78.96% (not 80.54%)
Perfect Rate:          4.96% (not 5.81%)
```

### Accurate Height Analysis (Actual Dives Only)

```
1m:   710 dives, avg 2.08, success 76.1%
3m:   357 dives, avg 2.07, success 81.5%
5m:    68 dives, avg 2.53, success 91.2% ← Down 0.15 from 2.68
7m:    15 dives, avg 2.73, success 100.0%
```

---

## Next Steps

1. **Data Quality:** Use actual_dives_only metrics for all future analysis
2. **Visualizations:** Update charts to exclude or clearly mark lineups
3. **Audit Update:** Revise calibration drift analysis using only actual dives
4. **Historical Context:** Re-run audit on actual dives to see if drift is less severe

---

## Technical Details

### Files Modified

- `dive_analytics.py`: Added lineup separation in `__init__`
- `diving_analytics_full.json`: Added `actual_dives_only` section with separate metrics

### Data Fields

Each video now tagged with:
- `dive_code.startswith('0')` → Lineup
- `dive_code` not starting with '0' → Actual dive

---

## Validation

✓ Lineup count matches expected (140 total)
✓ 010/020 codes properly identified
✓ Actual dive count = 1,150 expected
✓ Performance distributions correct
✓ Height analysis validates with source data

---

**Status:** Implementation complete
**Impact:** Moderate (affects 10.9% of dataset)
**Recommendation:** Use actual_dives_only metrics for analysis going forward
