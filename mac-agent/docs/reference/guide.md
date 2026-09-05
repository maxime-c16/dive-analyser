# Accessing Photo Captions from Apple Photos

## The Bad News First

**Apple provides NO official API to read or write the “Caption” field added in iOS 14.**

From Apple Developer Forums (confirmed by Apple DTS):

> “There is no API or supported way to read or edit that caption.”
> — Apple Developer Technical Support

The caption is stored internally in the Photos.sqlite database but is NOT exposed through:

- PhotoKit framework
- AppleScript (only `description` property, not caption)
- Any public API

### What’s the Difference?

- **Title** (`name` in AppleScript): Accessible via AppleScript ✓
- **Description** (`description` in AppleScript): Accessible via AppleScript ✓
- **Caption** (iOS 14+ “Add a Caption” field): **NOT accessible** via any API ✗

Confusingly, what Photos calls “Caption” in the UI corresponds to **different database fields** than what’s exposed via AppleScript.

-----

## Your Options (Best to Worst)

### Option 1: Use `osxphotos` (RECOMMENDED - macOS)

The **osxphotos** Python package reads the Photos.sqlite database directly and CAN access the description/caption field.

```bash
# Install osxphotos
pip install osxphotos

# Or better, with pipx
brew install pipx
pipx install osxphotos
```

#### Query all videos and their descriptions:

```bash
osxphotos query --movie --json | jq '.[] | {filename: .original_filename, description: .description}'
```

#### Python script to filter your diving videos:

```python
import osxphotos
import re

def parse_dive_caption(description):
    """
    Parse your custom format: [DIVECODE PERF HEIGHT SYNC SMACK]
    Examples: 
      "101B G 3m" -> dive=101B, perf=G, height=3m
      "5231D P 10m SYNC" -> dive=5231D, perf=P, height=10m, sync=True
      "612A F SMACK" -> dive=612A, perf=F, smack=True
    """
    if not description:
        return None
    
    pattern = r'^(\d{3,4}[A-D])\s+([FBMGP])\s*(\d+m(?:P)?)?(\s+SYNC)?(\s+SMACK)?$'
    match = re.match(pattern, description.strip(), re.IGNORECASE)
    
    if not match:
        return None
    
    return {
        'dive_code': match.group(1).upper(),
        'performance': match.group(2).upper(),
        'height': match.group(3) if match.group(3) else '1m',
        'sync': bool(match.group(4)),
        'smack': bool(match.group(5))
    }

def main():
    # Open the default Photos library
    photosdb = osxphotos.PhotosDB()
    
    # Get all movies (videos)
    videos = photosdb.photos(movies=True, images=False)
    
    print(f"Found {len(videos)} videos in library\n")
    
    dive_videos = []
    
    for video in videos:
        # The 'description' field is what Photos shows as "Caption" in iOS 14+
        caption = video.description
        
        if not caption:
            continue
        
        dive_info = parse_dive_caption(caption)
        
        if dive_info:
            dive_videos.append({
                'filename': video.original_filename,
                'uuid': video.uuid,
                'path': video.path,
                'caption': caption,
                **dive_info
            })
    
    print(f"Found {len(dive_videos)} diving videos\n")
    
    # Print all diving videos
    for dv in dive_videos:
        print(f"File: {dv['filename']}")
        print(f"  Dive: {dv['dive_code']}")
        print(f"  Performance: {dv['performance']}")
        print(f"  Height: {dv['height']}")
        print(f"  Sync: {dv['sync']}")
        print(f"  Smack: {dv['smack']}")
        print()
    
    # Filter examples:
    # All perfect (P) dives
    perfect_dives = [d for d in dive_videos if d['performance'] == 'P']
    print(f"Perfect dives: {len(perfect_dives)}")
    
    # All 10m platform dives
    ten_meter = [d for d in dive_videos if d['height'] == '10m']
    print(f"10m dives: {len(ten_meter)}")
    
    # All synchro dives
    synchro = [d for d in dive_videos if d['sync']]
    print(f"Synchro dives: {len(synchro)}")
    
    # All belly flops (SMACK)
    smacks = [d for d in dive_videos if d['smack']]
    print(f"Belly flops: {len(smacks)}")
    
    return dive_videos

if __name__ == "__main__":
    main()
```

#### Export with custom filenames based on caption:

```bash
osxphotos export /path/to/export \
  --movie \
  --filename "{descr}_{original_name}" \
  --directory "{created.year}/{created.month}"
```

-----

### Option 2: Direct SQLite Query (Advanced - macOS)

You can query the Photos.sqlite database directly. **IMPORTANT:** Always work on a COPY, never the original!

#### Location of Photos.sqlite:

```
macOS: ~/Pictures/Photos Library.photoslibrary/database/Photos.sqlite
iOS: /private/var/mobile/media/PhotoData/Photos.sqlite (requires jailbreak)
```

#### Query to get videos with captions:

```sql
-- First, copy the database (while Photos is closed or use WAL mode)
-- cp ~/Pictures/Photos\ Library.photoslibrary/database/Photos.sqlite /tmp/photos_copy.sqlite

SELECT 
    ZASSET.ZUUID as uuid,
    ZASSET.ZFILENAME as filename,
    ZADDITIONALASSETATTRIBUTES.ZORIGINALFILENAME as original_filename,
    ZASSETDESCRIPTION.ZLONGDESCRIPTION as caption,
    datetime(ZASSET.ZDATECREATED + 978307200, 'unixepoch') as date_created
FROM ZASSET
LEFT JOIN ZADDITIONALASSETATTRIBUTES 
    ON ZASSET.ZADDITIONALATTRIBUTES = ZADDITIONALASSETATTRIBUTES.Z_PK
LEFT JOIN ZASSETDESCRIPTION 
    ON ZASSET.Z_PK = ZASSETDESCRIPTION.ZASSETATTRIBUTES
WHERE ZASSET.ZKIND = 1  -- 1 = video, 0 = photo
  AND ZASSETDESCRIPTION.ZLONGDESCRIPTION IS NOT NULL
ORDER BY ZASSET.ZDATECREATED DESC;
```

**Warning:** The database schema changes between iOS/macOS versions. The table `ZASSETDESCRIPTION` exists in newer versions; older versions store descriptions differently.

-----

### Option 3: AppleScript/PhotoScript (Limited - macOS)

AppleScript can access `description` which MAY correspond to caption in some cases:

```applescript
tell application "Photos"
    set selectedPhotos to selection
    repeat with p in selectedPhotos
        set desc to description of p
        log "Filename: " & filename of p & " - Description: " & desc
    end repeat
end tell
```

Or using the `photoscript` Python wrapper:

```python
import photoscript

photoslib = photoscript.PhotosLibrary()
photoslib.activate()

album = photoslib.album("Diving Videos")
for media in album.photos():
    print(f"{media.filename}: {media.description}")
```

**Limitation:** This accesses the `description` property, which corresponds to the older “Description” field, not necessarily the iOS 14+ Caption field.

-----

### Option 4: Export and Read EXIF (Workaround)

When you export photos/videos from Photos with “Include Caption Information” enabled, the caption gets embedded in EXIF metadata.

1. Select photos in Photos app
1. File > Export > Export Unmodified Original
1. Check “Include: Caption Information”
1. Use exiftool to read:

```bash
exiftool -Description -Caption-Abstract -ImageDescription *.mov
```

-----

## Recommendation for Your Use Case

Since you’re on iOS and want to filter diving videos by your custom caption format, here’s my recommended workflow:

### If you have a Mac with the same iCloud Photos library:

1. **Install osxphotos:**
   
   ```bash
   pip install osxphotos
   ```
1. **Run my Python script above** to parse and filter your videos
1. **Create smart filtering** based on your format

### If you’re iOS-only:

Unfortunately, there’s no good native solution. Your options:

1. Use the Shortcuts app to create albums based on caption content (limited)
1. Use a third-party app that can read the Photos database (rare, may require jailbreak)
1. Export videos and use metadata tools on a computer

-----

## References

- Apple Developer Forums: https://developer.apple.com/forums/thread/665185
- osxphotos: https://github.com/RhetTbull/osxphotos
- photoscript: https://github.com/RhetTbull/PhotoScript
- Photos.sqlite forensics: https://theforensicscooter.com/
