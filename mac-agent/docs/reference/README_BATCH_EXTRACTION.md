# Batch Extraction Complete ✅

## Quick Summary

Your Photos library diving videos have been extracted, parsed, and triaged:

| Metric | Count |
|--------|-------|
| **Total videos scanned** | 5,515 |
| **✅ Valid dive videos** | **1,538** |
| **👤 Your personal dives** | **1,290** |
| **👥 Other people's dives** | 248 |
| **⚠️ Invalid captions** | 141 |
| **ℹ️ No captions** | 3,836 |

---

## Key Files to Review

### 1. **FINAL_TRIAGE_REPORT.md** ⭐ START HERE
Comprehensive analysis with:
- Detailed breakdown of your diving profile
- Performance and height distribution
- Identified improvements made
- Recommendations for fixing remaining issues
- Complete statistics and technical details

### 2. **your_dive_videos.csv**
Open in Excel/Google Sheets for easy filtering:
- **1,290 rows** of your personal dives
- Columns: filename, date, dive_type, dive_code, performance, height, platform, sync, smack
- Already sorted by date
- Ready for analysis and reporting

### 3. **other_peoples_dives.csv**
Videos of training partners:
- **248 rows** clearly organized by person
- Columns: person, filename, date, dive_code, performance, height, platform, sync, smack
- Groups: FANNY (136), SARA (52), LEO (16), and others

### 4. **remaining_invalid_captions.csv**
Edge cases that still need manual review:
- **141 rows** of captions that couldn't be auto-parsed
- Lists the formatting issue for each
- Open in spreadsheet to batch-fix in Photos app

### 5. **dive_metadata_report_final.json**
Complete structured data (for developers/programmatic use):
- All video metadata in JSON format
- Parsed dive information
- Perfect for building tools or dashboards

---

## What Was Fixed

✅ **Lineup detection** - Codes starting with 0 (010, 020, etc.) now recognized
✅ **Open pike support** - Codes with O suffix (201BO, 301CO) now parsed
✅ **Person name extraction** - Dives with names appended (101B G FANNY) now split correctly
✅ **Name consolidation** - "F" shorthand mapped to "FANNY" for consistency
✅ **Keyword preservation** - "SYNC" and "SMACK" now treated as keywords, not names

---

## Your Diving Stats (1,290 videos)

### By Performance
- 🥇 Perfect (P): 75 videos (5.8%)
- 🟢 Good (G): 419 videos (32.4%)
- 🟡 Medium (M): 545 videos (42.2%)
- 🟠 Bad (B): 154 videos (11.9%)
- 🔴 Failed (F): 97 videos (7.5%)

### By Height
- **1m springboard**: 888 videos (68.8%)
- **3m springboard**: 455 videos (35.3%)
- **5m platform**: 165 videos (12.8%)
- **7m platform**: 29 videos (2.2%)
- **10m platform**: 1 video (0.1%)

### Special
- **Synchro dives**: 41 videos
- **Belly flops (SMACK)**: 41 videos
- **Lineups**: 140 videos
- **Individual dives**: 1,150 videos

---

## Next Steps

1. **Review** FINAL_TRIAGE_REPORT.md for complete analysis
2. **Open** your_dive_videos.csv in Excel/Google Sheets
3. **Check** remaining_invalid_captions.csv for any you want to fix
4. **Use** the standardized caption format for future videos:
   ```
   DIVECODE PERF [HEIGHT] [SYNC] [SMACK] [PERSON]
   Examples:
   - 101B M
   - 202A G 3m FANNY
   - 010B G (lineup)
   - 201BO M 3m (open pike)
   - 101B M SYNC (synchronized)
   - 103B F SMACK (belly flop)
   ```

---

## Files Included

**Main Reports:**
- `FINAL_TRIAGE_REPORT.md` (9.9 KB) - Complete analysis
- `BATCH_EXTRACTION_REPORT.md` (6.6 KB) - Original findings
- `README_BATCH_EXTRACTION.md` (this file)

**Data Exports (Ready to Use):**
- `your_dive_videos.csv` (100 KB) - Your 1,290 dives
- `other_peoples_dives.csv` (19 KB) - Other people's 248 dives
- `remaining_invalid_captions.csv` (16 KB) - 141 captions needing fixes

**Raw Data (for developers):**
- `dive_metadata_report_final.json` (4.5 MB) - Complete structured data
- Previous versions for reference (v1, v2, v3)

**Documentation:**
- `CLAUDE.md` - For future AI assistant context
- `guide.md` - Background on Apple Photos caption access

---

## Support

For detailed information about:
- How the parsing works
- What each dive code means
- Platform vs springboard detection
- See: **FINAL_TRIAGE_REPORT.md**

For questions about the data or corrections needed:
- Review: **remaining_invalid_captions.csv**
- Reference: **your_dive_videos.csv** (your master record)

---

**Generated:** January 7, 2026
**Duration:** 5,515 videos in ~15 minutes
**Format Support:** Excel, Google Sheets, Python, JSON

