# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Diving Video Filter** is a macOS command-line tool that reads from your Photos library and filters diving videos based on custom caption metadata. The tool parses a specific caption format and provides filtering, statistics, and export functionality.

## Installation & Setup

### Dependencies

The project requires Python 3 and the `osxphotos` package:

```bash
pip install osxphotos
```

The `osxphotos` package is critical to this project—it reads the Photos.sqlite database directly to access caption data that is not exposed through Apple's public APIs. See `guide.md` for detailed background on why direct database access is necessary.

## Running the Script

### Basic Usage

```bash
python dive_video_filter.py [options]
```

### Common Commands

```bash
# List all diving videos in your Photos library
python dive_video_filter.py

# Filter by performance level (F, B, M, G, P)
python dive_video_filter.py --performance P

# Filter by height (1m, 3m, 3mP, 5m, 7m, 10m)
python dive_video_filter.py --height 10m

# Show only synchro (synchronized) dives
python dive_video_filter.py --sync

# Show only belly flops (marked with SMACK)
python dive_video_filter.py --smack

# Filter by specific dive code (e.g., 101B, 5231D)
python dive_video_filter.py --dive 101B

# Output results as JSON
python dive_video_filter.py --json

# Show statistics about your dive videos
python dive_video_filter.py --stats

# Export matching videos to a directory
python dive_video_filter.py --performance P --export ~/Desktop/perfect_dives

# Use a specific Photos library path
python dive_video_filter.py --library "/path/to/Photos Library.photoslibrary"
```

### Combining Filters

Filters can be combined:

```bash
python dive_video_filter.py --height 10m --sync --export ~/output
```

## Architecture & Code Structure

The script follows a functional, modular architecture:

1. **Caption Parsing** (`parse_dive_caption`): Parses the custom caption format `[DIVECODE PERF HEIGHT SYNC SMACK]` and extracts structured dive information. Returns `None` if caption doesn't match the expected format.

2. **Data Retrieval** (`get_dive_videos`): Uses `osxphotos.PhotosDB` to access the Photos library and builds a list of all videos with valid dive captions. Each video is enriched with metadata like filename, UUID, path, date, and duration.

3. **Filtering** (`filter_videos`): Applies zero or more filters (performance, height, sync, smack, dive code) to the video list. Filters are combined with AND logic.

4. **Output Formatting**: Three output modes are available:
   - Table format (`print_video_table`): Human-readable columnar display
   - JSON (`json.dumps`): Machine-readable structured data
   - Statistics (`print_statistics`): Aggregated analytics by performance, height, and dive code

5. **Export** (`export_videos`): Copies matching videos to a specified directory with renamed filenames that include dive metadata.

### Caption Format

Videos must have captions in the format: `DIVECODE PERF [HEIGHT] [SYNC] [SMACK]`

- **DIVECODE**: 3-4 digits + position (A-D), e.g., `101B`, `5231D`
- **PERF**: Single letter (F, B, M, G, P) representing Failed, Bad, Medium, Good, Perfect
- **HEIGHT**: Optional; defaults to `1m`. Format: `3m`, `5m`, `7m`, `10m`, or with `P` suffix for platform (e.g., `3mP`)
- **SYNC**: Optional keyword indicating synchronized dive
- **SMACK**: Optional keyword indicating belly flop

Examples:
- `101B G` → 101B dive, Good performance, 1m springboard (default)
- `5231D P 10m` → 5231D dive, Perfect, 10m platform
- `612A G 3mP SYNC` → 612A dive, Good, 3m platform, synchronized

## Performance Level Mapping

| Code | Name |
|------|------|
| F | Failed |
| B | Bad |
| M | Medium |
| G | Good |
| P | Perfect |

## Key Design Notes

- **osxphotos Dependency**: The tool relies on `osxphotos` reading the Photos.sqlite database directly. This is necessary because Apple provides no API for accessing the iOS 14+ Caption field. See `guide.md` for historical context.

- **Case Insensitivity**: Input is case-insensitive; internally everything is normalized to uppercase (e.g., `--performance p` works the same as `-p P`).

- **Platform Detection**: Heights of 5m, 7m, or 10m are automatically classified as platform dives. Heights with an explicit `P` suffix (e.g., `3mP`) are also marked as platform. Other heights default to springboard.

- **Video File Paths**: Exported filenames include the dive code, performance, and height to make organized export directories human-readable. Original file paths are preserved from the Photos library metadata.

## Important Files

- `dive_video_filter.py`: Main script containing all logic
- `guide.md`: Detailed explanation of Apple Photos caption access methods and why osxphotos is used
- `CLAUDE.md`: This file
