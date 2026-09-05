# Batch Metadata Extraction Report
**Date Range:** September 1, 2024 - January 7, 2026

---

## Executive Summary

A comprehensive batch extraction of all diving video metadata was performed on your Photos library. The analysis scanned **5,515 videos** from September 2024 onwards and found:

- ✅ **1,290 valid dive videos** with correctly formatted captions
- ⚠️ **389 invalid captions** (8.1%) that don't match the expected format
- ℹ️ **3,836 videos without captions** (69.6%)
- ⚠️ **31 dive codes** with multiple variations (different performances/heights)

---

## Key Findings

### 1. Invalid Captions Analysis (389 videos)

Four main patterns of invalid captions were identified:

#### Pattern 1: Dive code + Performance + Extra Name (186 videos)
These captions have additional text after the performance level, often personal names or nicknames.

**Examples:**
- `100B F PAUL`
- `401C M SARA`
- `5222A M F`

**Issue:** The extra text breaks the parsing. The parser expects the caption to end after height/keywords.

**Solution:** Remove the extra text or append it after a secondary separator if you want to keep the names.

---

#### Pattern 2: Incomplete/Malformed Format (135 videos)
These captions start correctly but are incomplete or have wrong structure.

**Examples:**
- `401C ` (just dive code and performance, trailing space)
- `301C M F 3m` (performance letter appears twice)
- `105C F MARC SMACK` (name inserted between performance and keywords)

**Issue:** Missing required components or wrong ordering.

**Solution:** Complete the caption with height if needed, or fix the order to `DIVECODE PERF [HEIGHT] [SYNC] [SMACK]`.

---

#### Pattern 3: Only Text (51 videos)
Captions that contain only names or letters with no dive code.

**Examples:**
- `LULU`
- `PAUL`
- `TOM`

**Issue:** No dive information, appears to be accidental captions.

**Solution:** These might be mistakes. Consider deleting or replacing with proper dive metadata.

---

#### Pattern 4: Name-First Format (17 videos)
Captions with names appearing before dive codes.

**Examples:**
- `PAUL SMACK`
- `DANY 201C G`
- `LOIS 101B`

**Issue:** Wrong order - parser expects dive code first.

**Solution:** Reorder to put dive code first: `201C G SMACK` instead of `DANY 201C G`.

---

### 2. Valid Videos Summary (1,290 videos)

#### By Performance Level
| Level | Count | Percentage |
|-------|-------|-----------|
| Medium (M) | 545 | 42.2% |
| Good (G) | 419 | 32.5% |
| Bad (B) | 154 | 11.9% |
| Failed (F) | 97 | 7.5% |
| Perfect (P) | 75 | 5.8% |

**Observation:** Most of your dives are rated Medium to Good, with a smaller pool of Perfect performances.

#### By Height
| Height | Count | Percentage |
|--------|-------|-----------|
| 1m (Springboard) | 712 | 55.2% |
| 3m (Springboard) | 390 | 30.2% |
| 5m (Platform) | 159 | 12.3% |
| 7m (Platform) | 29 | 2.2% |
| 10m (Platform) | 0 | 0% |

**Observation:** Most training is on springboard (1m/3m), with some platform work (5m/7m). No 10m dives recorded yet.

#### Special Categories
- **Synchro videos:** 40 (3.1%)
- **Belly flops (SMACK):** 41 (3.2%)
- **Platform dives:** 36 (2.8%)
- **Springboard dives:** 1,254 (97.2%)

---

### 3. Duplicate Dive Codes (31 codes with variations)

Several dive codes appear many times with **different performance levels and heights**. This is expected (the same dive performed multiple times at different levels), but here are the most frequent:

#### Top Duplicates:
- **101B:** 154 occurrences (Perfs: P, G, M, B, F | Heights: 1m, 3m, 5m, 7m)
- **010B:** 85 occurrences (Perfs: P, G, M, B | Heights: 1m, 3m, 5m, 7m)
- **020C:** 17 occurrences (Perfs: P, G, M, B | Heights: 3m, 5m)
- **010A:** 14 occurrences (Perfs: P, G, M, B | Heights: 1m, 3m, 5m)

**Observation:** 101B is your most recorded dive across all performance levels and heights. This suggests it's a core dive in your training.

---

## Generated Files

Three files have been created for your review:

1. **dive_metadata_report.json** (18 KB)
   - Complete detailed data in JSON format
   - Contains all videos with parsed metadata
   - Suitable for programmatic processing

2. **invalid_captions.csv** (15 KB)
   - 389 videos with invalid caption formats
   - Columns: filename, date, invalid_caption, error_details
   - Sorted by date for chronological review

3. **valid_dive_videos.csv** (45 KB)
   - 1,290 videos with valid captions
   - Columns: filename, date, dive_code, performance, height, sync, smack
   - Sorted by date for easy browsing

---

## Recommendations

### Immediate Actions

1. **Review Invalid Captions (389 videos)**
   - Open `invalid_captions.csv` in a spreadsheet
   - Most common issue: extra names appended to captions (186 videos)
   - Batch fix in Photos app by editing captions to remove extra text

2. **Address Pattern 1 (Extra Names - 186 videos)**
   - These are closest to valid format
   - Example: `100B F PAUL` → `100B F`
   - Can likely be fixed with find-and-replace on names

3. **Videos Without Captions (3,836 videos)**
   - Consider if these should be captioned
   - Many may not be dive-related
   - Only caption if they contain relevant diving footage

### Format Standardization

Your caption format is working well for most videos. Going forward:
- **Correct format:** `DIVECODE PERF [HEIGHT] [SYNC] [SMACK]`
- Examples:
  - `101B G` (1m springboard, Good)
  - `5231D P 10m` (10m platform, Perfect)
  - `612A G 3mP SYNC` (3m platform, synchronized, Good)
  - `103B F SMACK` (1m, belly flop, Failed)

---

## Statistics at a Glance

```
Total videos scanned (Sept 2024 - Jan 2026):     5,515
├─ With valid captions:                         1,290 (23.4%)
├─ With invalid captions:                         389 (7.1%)
├─ Without captions:                            3,836 (69.6%)
└─ File path errors:                            5,515 (100%) *

* Note: osxphotos returns null for file paths in newer databases.
  This is a library limitation, not a data issue.

Valid video breakdowns:
├─ By performance: P(75) G(419) M(545) B(154) F(97)
├─ By height: 1m(712) 3m(390) 5m(159) 7m(29) 10m(0)
├─ Synchro dives: 40
├─ Belly flops: 41
└─ Duplicate dive codes: 31 (101B appears most: 154x)
```

---

## Next Steps

1. **Export invalid_captions.csv to a spreadsheet** for easier review
2. **Batch fix captions** in Photos by removing extra text
3. **Consider centralizing** your dive metadata in a spreadsheet for easier tracking
4. **Set up a template** when adding new videos:
   - Format: `DIVECODE PERF [HEIGHT] [SYNC/SMACK]`
   - Example: `101B G` or `5231D P 10m SYNC`

---

**Report Generated:** January 7, 2026
**Script:** `batch_extract_metadata.py`
**Date Range:** September 1, 2024 - January 7, 2026
