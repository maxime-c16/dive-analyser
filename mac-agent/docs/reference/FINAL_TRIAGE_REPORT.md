# Final Batch Extraction & Triage Report
**Date Range:** September 1, 2024 - January 7, 2026
**Last Updated:** January 7, 2026

---

## Executive Summary

After comprehensive batch extraction and intelligent triage of your Photos library, we've successfully categorized **1,538 valid dive videos** from 5,515 total videos scanned. The extraction now correctly handles:

- ✅ **Your personal dives:** 1,290 videos (1,150 individual dives + 140 lineups)
- 👥 **Other people's dives:** 248 videos (clearly separated by name)
- ⚠️ **Still invalid:** 141 videos (edge cases with formatting issues)
- ℹ️ **No captions:** 3,836 videos (not dive-related or incomplete)

---

## Key Improvements Made

### 1. Lineup Detection (010, 020, etc.)
✅ **FIXED** - Dive codes starting with 0 (010, 020, 030, 040) are now correctly identified as lineup formations:
- **010:** Front lineup (forward-facing formation)
- **020:** Back lineup (backward-facing formation)
- **030/040:** Other lineup configurations

**Your lineups:** 140 videos

### 2. Open Pike Recognition
✅ **FIXED** - Dive codes with "O" suffix (e.g., **201BO**, **301CO**) are now recognized as open pike position dives.

### 3. Personal Names (Other People's Dives)
✅ **FIXED** - Names appended to captions (e.g., "101B G FANNY") are now:
- Correctly extracted and associated with the person
- Consolidated with alternative abbreviations (e.g., "F" → "FANNY")
- Clearly separated from your personal dives

**Other people identified:** 15 individuals

### 4. Keyword Preservation
✅ **FIXED** - "SYNC" and "SMACK" are properly recognized as keywords, not person names

---

## Your Diving Profile

### Performance Distribution
| Level | Count | % of Total |
|-------|-------|-----------|
| Medium (M) | 545 | 42.2% |
| Good (G) | 419 | 32.4% |
| Bad (B) | 154 | 11.9% |
| Failed (F) | 97 | 7.5% |
| Perfect (P) | 75 | 5.8% |

**Key Insight:** Most of your dives are rated Medium to Good. You have a solid foundation with 497 dives rated Good or Perfect (38.5%).

### Height Distribution
| Height | Count | % of Total | Type |
|--------|-------|-----------|------|
| 1m | 888 | 68.8% | Springboard |
| 3m | 455 | 35.3% | Springboard |
| 5m | 165 | 12.8% | Platform |
| 7m | 29 | 2.2% | Platform |
| 10m | 1 | 0.1% | Platform |

**Training Focus:** Strong springboard foundation (1m/3m), with significant platform work at 5m level.

### Dive Type Breakdown
- **Individual dives:** 1,150 (89.2%)
- **Lineup formations:** 140 (10.8%)

### Special Categories
- **Synchro dives:** 41 (3.2%)
- **Belly flops (SMACK):** 41 (3.2%)

---

## Other People's Dives (248 videos)

Clearly tracked videos of training partners and other divers:

| Person | Videos | Avg Performance | Primary Heights |
|--------|--------|-----------------|-----------------|
| FANNY | 136 | Medium/Good | 1m, 3m |
| SARA | 52 | Medium | 1m, 3m |
| LEO | 16 | Medium | 1m, 3m, 5m |
| PE | 11 | Good | 1m |
| LUB | 9 | Medium | 3m |
| TOM | 6 | Good | 3m |
| PAUL | 5 | Medium | 1m |
| COCO | 4 | Medium | 1m |
| GUI | 3 | Mixed | 1m |
| Others | 8 | Various | Mixed |

---

## Remaining Invalid Captions (141 videos)

These captions have formatting issues that couldn't be automatically parsed. They fall into several categories:

### Category 1: Wrong Field Order (60+ videos)
**Pattern:** Height placed after dive code instead of after performance
```
Examples:
  301C M F 3m          (should be: 301C M 3m FANNY)
  010C M SARA 3mP      (should be: 010C M 3mP SARA)
  103C F FANNY 3m      (should be: 103C F 3m FANNY)
```
**Fix:** Reorder to: `DIVECODE PERF [HEIGHT] [SYNC/SMACK] [PERSON]`

### Category 2: Names Without Complete Dive Info (30+ videos)
**Pattern:** Just a person's name or incomplete dive code
```
Examples:
  LOIS 103B            (missing performance)
  DANY 201C            (missing performance)
  XAV                  (name only)
  ANAÏS                (name only)
```
**Fix:** Add full dive information or remove if not dive-related

### Category 3: Typos (10+ videos)
**Pattern:** Misspelled keywords or malformed codes
```
Examples:
  101B G SYNCK SMACK   (SYNCK → SYNC)
  1:07                 (timestamp, not dive code)
  20:25                (timestamp, not dive code)
```
**Fix:** Correct typos or remove timestamps

---

## Files Generated

### Main Analysis Files
1. **dive_metadata_report_final.json** (3.8 MB)
   - Complete structured data for all videos
   - Full dive parse results and metadata
   - Includes invalid captions for reference

### Spreadsheet Exports (ready to use in Excel/Sheets)
2. **your_dive_videos.csv** (45 KB)
   - 1,290 rows of your personal dives
   - Columns: filename, date, dive_type, dive_code, performance, height, platform, sync, smack
   - Sorted by date for chronological review

3. **other_peoples_dives.csv** (12 KB)
   - 248 rows of other people's dives
   - Columns: person, filename, date, dive_code, performance, height, platform, sync, smack
   - Grouped by person

4. **remaining_invalid_captions.csv** (6 KB)
   - 141 rows of captions that couldn't be parsed
   - Columns: filename, date, invalid_caption, reason
   - Helpful for manual review and correction

### Documentation
5. **FINAL_TRIAGE_REPORT.md** (this file)
   - Complete analysis and recommendations

---

## Recommendations

### Immediate Actions

1. **Review the 141 remaining invalid captions**
   - Open `remaining_invalid_captions.csv` in your spreadsheet
   - Most can be fixed by reordering fields or adding missing performance levels
   - Some are just names that shouldn't be there (can be deleted)

2. **Batch fix in Photos app**
   - Focus on Category 1 (wrong field order) first - largest group
   - Use Find & Replace if possible to fix patterns
   - Example: "301C M F 3m" → "301C M 3m FANNY"

3. **Consolidate your tracking**
   - Use `your_dive_videos.csv` as your master record
   - Keep it synchronized with your Photos captions
   - Use consistent naming for training partners

### Going Forward

1. **Caption Format (standardized)**
   ```
   DIVECODE PERF [HEIGHT] [SYNC] [SMACK] [PERSON]
   ```

   **Examples:**
   - `101B M` → 101B dive, Medium, 1m (default)
   - `202A G 3m` → 202A dive, Good, 3m springboard
   - `5231D P 5m` → 5231D dive, Perfect, 5m platform
   - `010B G` → Front lineup, Good (10B formation)
   - `201BO M 3m` → 201B dive, open pike, Medium, 3m
   - `101B M FANNY` → 101B dive, Medium, recorded with FANNY
   - `101B M SYNC` → 101B dive, Medium, synchronized dive
   - `103B F SMACK` → 103B dive, Failed, belly flop

2. **Performance Levels (consistent)**
   - **P** = Perfect
   - **G** = Good
   - **M** = Medium
   - **B** = Bad
   - **F** = Failed

3. **Height Designations**
   - **1m** (default if omitted)
   - **3m** (springboard)
   - **5m**, **7m**, **10m** (platform)
   - Add **P** suffix for platform: **3mP**, **5mP** (though heights 5m+  auto-detected as platform)

4. **Special Codes**
   - **0XX** prefix for lineups (010=front, 020=back, etc.)
   - **XXO** suffix for open pike (201BO, 301CO)
   - **SYNC** keyword for synchronized dives
   - **SMACK** keyword for belly flops

### Optional: Consolidation Projects

1. **Names as initials** (reduce errors)
   - Instead of full names, use initials: **FR** (Fanny), **SR** (Sara)
   - Reduces misspelling chance
   - Example: `101B M FR` instead of `101B M FANNY`

2. **Separate system** (recommended long-term)
   - Consider a spreadsheet parallel to Photos for detailed tracking
   - Captures more metadata (location, pool type, coach notes, etc.)
   - Easier to filter and analyze than Photos captions
   - Photos captions used for quick reference only

---

## Statistics Summary

```
TOTAL VIDEOS SCANNED: 5,515

✅ Valid Parse Results:           1,538 (27.9%)
   ├─ YOUR DIVES:                 1,290 (83.8%)
   │  ├─ Individual dives:        1,150
   │  └─ Lineups:                   140
   └─ OTHER PEOPLE:                 248 (16.1%)

⚠️  Invalid Captions:               141 (2.6%)
   (remaining edge cases)

ℹ️  No Captions:                   3,836 (69.6%)
   (videos without dive metadata)

YOUR PERSONAL DIVES:
├─ Perfect (P):                      75 videos
├─ Good (G):                        419 videos
├─ Medium (M):                      545 videos
├─ Bad (B):                         154 videos
└─ Failed (F):                       97 videos

HEIGHT DISTRIBUTION:
├─ 1m Springboard:                 888 videos
├─ 3m Springboard:                 455 videos
├─ 5m Platform:                    165 videos
├─ 7m Platform:                     29 videos
└─ 10m Platform:                     1 video
```

---

## Technical Notes

### Parsing Rules Implemented

1. **Dive Code Format:** `\d{3,4}[A-DOa-do]`
   - 3-4 digits + position letter (A-D)
   - 0-prefix codes recognized as lineups
   - O-suffix recognized as open pike position

2. **Performance Letter:** `[FBMGPfbmgp]`
   - Must follow dive code immediately
   - Case-insensitive (f, F, M, m, etc. all valid)

3. **Height (optional):** `\d+m[Pp]?`
   - Format: number + 'm' (e.g., 3m, 5m)
   - Optional 'P' suffix for platform designation
   - Heights 5m+ auto-detected as platform
   - Default to 1m if omitted

4. **Keywords (optional):**
   - SYNC: Synchronized dives
   - SMACK: Belly flops

5. **Person Names (optional):**
   - Extracted from end of caption if present
   - Must be 2+ letters (avoid single-letter codes)
   - Excludes keywords like SYNC/SMACK

---

## Next Steps

1. **Review** the three CSV files in your spreadsheet application
2. **Fix** the 141 remaining invalid captions in Photos (reference `remaining_invalid_captions.csv`)
3. **Verify** your personal dive data in `your_dive_videos.csv`
4. **Archive** these reports for future reference
5. **Apply** the standardized format to new videos going forward

---

**Report Generated:** January 7, 2026
**Processing Time:** ~15 minutes
**Script:** `batch_extract_metadata.py` v3
**Parser:** Enhanced with lineup detection, open pike support, and intelligent name extraction

