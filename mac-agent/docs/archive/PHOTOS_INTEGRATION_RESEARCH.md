# Photos Library Integration Research

## Overview
This document summarizes research on efficiently integrating Apple Photos library videos into the Diving Analyser without excessive storage overhead.

**Key Finding:** The fundamental constraint is that cloud-only Photos require download for access, but APFS cloning and symlinks can minimize local storage impact.

---

## 1. Current Blocker: Cloud Photos Export

### Problem
`osxphotos export` fails with "exported: 0, missing: 1" for cloud-only photos because:
- Cloud photos aren't stored locally on disk
- Photos.app must download them from iCloud first
- Requires Apple's PhotoKit API (not just AppleScript)
- Requires interactive user session with Full Disk Access

### Solution Approaches

#### Option A: Using `--use-photokit` with `--download-missing`
**Most promising approach for background automation.**

```bash
osxphotos export \
  --download-missing \
  --use-photokit \
  --update \
  --export-by-date \
  /path/to/export/directory
```

**Advantages:**
- Uses PhotoKit API (faster than AppleScript)
- Can download missing originals in batch
- Properly handles cloud photos

**Limitations:**
- Marked as "highly experimental alpha feature"
- Doesn't work with iTerm2 (needs Terminal.app or direct shell)
- May require Interactive session context

**References:**
- [osxphotos GitHub Documentation](https://github.com/RhetTbull/osxphotos)
- [Issue #1662: --download-missing without exporting](https://github.com/RhetTbull/osxphotos/issues/1662)

---

## 2. Storage Efficiency: Symlinks & Hardlinks

### APFS Cloning (Recommended)
**When using `--export-as-hardlink` on APFS volumes**, files are automatically cloned instead.

**How it works:**
- APFS clone = instant copy-on-write reference
- Zero initial storage overhead
- Copy-on-write semantics: only modifying a file allocates new space
- Unlike hardlinks, works across different volumes

**Advantages:**
- No additional storage until files are modified
- Fast to create
- Transparent to applications

**Limitations:**
- APFS-only (not available on external HFS+ drives)
- Only works for regular files (not directories)

**References:**
- [APFS: Files and clones (The Eclectic Light Company, 2024)](https://eclecticlight.co/2024/03/20/apfs-files-and-clones/)
- [Copy, move and clone files in APFS (The Eclectic Light Company, 2020)](https://eclecticlight.co/2020/04/14/copy-move-and-clone-files-in-apfs-a-primer/)
- [Can APFS special files save storage space? (2025)](https://eclecticlight.co/2025/04/02/can-apfs-special-files-save-storage-space/)

### Symlinks as Alternative
**If cloning not available or for cross-volume scenarios.**

```bash
# Create symlinks to Photos originals
ln -s /path/to/Photos/Masters/actual/file.mov /path/to/exported/file.mov
```

**Advantages:**
- Zero storage overhead
- Works cross-volume
- Can be synced/backed up

**Limitations:**
- Broken symlinks if original Photos file is moved
- Requires Photos library to remain stable

**References:**
- [How to Create Symbolic Links on Mac (The How-To Geek)](https://www.howtogeek.com/297721/how-to-create-and-use-symbolic-links-aka-symlinks-on-a-mac/)
- [Aliases, hard links, symlinks, and copies in Mojave's APFS (Eclectic Light)](https://eclecticlight.co/2019/01/05/aliases-hard-links-symlinks-and-copies-in-mojaves-apfs/)

---

## 3. osxphotos API Integration

### PhotoInfo Object
The core object for programmatic access to Photos library:

```python
from osxphotos import PhotosDB

# Access library
db = PhotosDB()

# Get photo by UUID
photo = db.photo(uuid)

# Access properties
print(photo.path)           # Original file path on disk
print(photo.filesize)       # File size in bytes
print(photo.ismissing)      # True if cloud-only
print(photo.hasoriginal)    # Has original version
```

### Export Methods

#### Method 1: Direct File Access (if already local)
```python
if photo.path and not photo.ismissing:
    # File already on disk, use symlink or clone
    os.symlink(photo.path, destination)
```

#### Method 2: Programmatic Export
```python
# Uses osxphotos export logic (respects --download-missing)
photo.export(destination, filename_template="{original_filename}")
```

#### Method 3: Export with Download
```python
# For cloud-only: triggers Photos.app to download
osxphotos export \
  --uuid {video_uuid} \
  --download-missing \
  --use-photokit \
  {destination_dir}
```

**References:**
- [OSXPhotos CLI Documentation](https://rhettbull.github.io/osxphotos/cli.html)
- [OSXPhotos Overview & API](https://rhettbull.github.io/osxphotos/)
- [How to use osxphotos for library recreation (Discussion #1267)](https://github.com/RhetTbull/osxphotos/discussions/1267)

---

## 4. Recommended Implementation Strategy

### Phase 1: Local Videos (Current - Working ✓)
- Videos in `/media/videos/` (Docker mount)
- Direct file serving from API
- No Photos integration needed
- Use for testing & development

### Phase 2: Symlink-Based Access (Low Overhead)
**Timeline: Next iteration**

**Approach:**
1. Create symlinks to Photos originals at startup
2. Point `/videos/` symlinks to `~/Pictures/Photos\ Library.photoslibrary/Masters/...`
3. On app startup: scan database and create missing symlinks
4. Zero storage cost (symlinks only)
5. Works for locally-available originals

**Pseudocode:**
```python
# At app startup or on-demand
from osxphotos import PhotosDB
import os
from pathlib import Path

db = PhotosDB()
videos_dir = Path('/videos')
videos_dir.mkdir(exist_ok=True)

for dive in dives_with_videos:
    photo = db.photo(dive.video_uuid)
    if photo and photo.path and not photo.ismissing:
        # Symlink to original Photos file
        link_path = videos_dir / f"{dive.video_uuid}.mp4"
        if not link_path.exists():
            os.symlink(photo.path, link_path)
```

**Benefits:**
- Zero storage overhead
- Fast (just symlinks)
- Works immediately for local originals
- No background export needed

**Limitations:**
- Requires Photos library to remain accessible
- Won't work for cloud-only photos
- Symlinks break if Photos reorganizes

### Phase 3: Selective Cloud Download (If Needed)
**Timeline: Future, if users request real dive videos**

**Approach:**
1. Use `--use-photokit` to download only accessed videos
2. Cache downloaded videos with TTL (e.g., 7 days)
3. Only download on-demand when user clicks to play
4. Clean up old cached videos automatically

**Pseudocode:**
```python
async def stream_video(video_uuid):
    # Check if already available
    if symlink_exists(video_uuid):
        return stream_local(video_uuid)

    # Check if cached recently
    cache_file = Path(f'/tmp/dive_videos/{video_uuid}')
    if cache_file.exists() and recently_modified(cache_file):
        return stream_local(cache_file)

    # Download on-demand in background
    if not download_pending(video_uuid):
        schedule_download(video_uuid)

    return {"status": "downloading", ...}

def schedule_download(video_uuid):
    # osxphotos export --uuid {uuid} --download-missing --use-photokit /tmp/dive_videos/
    subprocess.Popen(['osxphotos', 'export', '--uuid', video_uuid,
                      '--download-missing', '--use-photokit',
                      '/tmp/dive_videos/'])
```

**Benefits:**
- Zero up-front storage
- Download only what's needed
- Automatic cleanup

**Limitations:**
- Requires `--use-photokit` reliability
- User waits for download on first play
- Complex state management

---

## 5. Photos Library Access Methods Comparison

| Method | Storage | Speed | Reliability | Session Req | Complexity |
|--------|---------|-------|-------------|-------------|------------|
| **Symlinks to local** | None | Instant | Medium | None | Low |
| **APFS clone** | Copy-on-write | Fast | High | None | Low |
| **Hardlinks** | None | Instant | High | None | Low |
| **osxphotos export** | Full copy | Slow | Low (cloud) | Interactive | Medium |
| **--use-photokit** | Full copy | Faster | Medium (alpha) | Interactive? | High |
| **Streaming from cache** | Temporary | Variable | Complex | Background | High |

---

## 6. Technical Constraints & Workarounds

### Problem: Daemon Process Can't Download Cloud Photos

**Root Cause:**
- Downloading cloud originals requires AppleScript → Photos.app
- Photos.app only responds in interactive sessions
- Background daemons run outside interactive session

**Possible Workarounds:**
1. **Use `--use-photokit`**: PhotoKit API doesn't require user interaction (supposedly)
2. **Run via cron in user session**: Use LaunchAgent instead of LaunchDaemon
3. **On-demand download from Flask server**: When user requests video, trigger export in foreground process
4. **Pre-download via manual sync**: User runs export periodically, symlinks auto-populate

### Problem: Photos.app Reorganizes Files

**Risk:** Symlinks break if Photos moves/reorganizes library

**Solutions:**
1. **Monitor symlink validity**: Check periodically, regenerate if broken
2. **Use UUIDs in symlink names**: Easier to track Photo identity
3. **Store original file path in DB**: Fall back to Photos API lookup if symlink breaks

---

## 7. Recommended Next Steps

### Immediate (This Week)
1. **Test Phase 2 approach** - Symlinks to local originals
   - Create osxphotos wrapper to scan library
   - Auto-populate symlinks at startup
   - Verify API can serve symlinked videos

2. **Document current limitation**: In UI, note which videos are cloud-only

### Short-term (Next 2 Weeks)
1. **Investigate `--use-photokit` reliability**
   - Test with actual cloud photos
   - Verify it works from background process
   - Check if LaunchAgent helps

2. **Implement symlink regeneration**
   - Periodic check for broken symlinks
   - Auto-repair from Photos API

### Medium-term (If Needed)
1. **On-demand download system** - Only if users request real video playback
2. **Caching strategy** - LRU cache with TTL cleanup
3. **Progress UI** - Show download status while videos load

---

## 8. Key References

- [osxphotos GitHub](https://github.com/RhetTbull/osxphotos)
- [osxphotos CLI Docs](https://rhettbull.github.io/osxphotos/cli.html)
- [osxphotos PyPI](https://pypi.org/project/osxphotos/)
- [Gist: Force Photos to download from iCloud](https://gist.github.com/RhetTbull/834e70717f95931044531dee273b8d1d)
- [APFS Cloning Deep Dive](https://eclecticlight.co/2024/03/20/apfs-files-and-clones/)
- [Backing up iCloud Photos](https://tmault.co.uk/blog/backing-up-icloud-photos-to-an-external-drive/)
- [Alternative: photos-sync project](https://github.com/kasparsd/photos-sync)

---

## 9. Current Architecture

**Status:** Working with test videos in `/media/videos/`

**Next logical step:** Phase 2 (Symlinks) - minimal overhead, immediate results

**Blocking issue:** cloud-only photos require `--use-photokit` testing

---

## Decision: Why NOT Host Streamer

The original host streamer approach had good intent but is unnecessary because:

1. **Symlinks solve the problem better**: Zero storage, no process management
2. **osxphotos API is mature**: Better than wrapping CLI
3. **APFS has native clone support**: Leverage OS capabilities
4. **On-demand is premature**: Test with symlinks first

---

*Last updated: 2026-01-13*
