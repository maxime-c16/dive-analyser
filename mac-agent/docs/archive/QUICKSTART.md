# 🚀 Diving Analyser - Quick Start Guide

## 30-Second Overview

Diving Analyser is a **real-time dive tracking system** that:
1. 📱 Extracts dives from your macOS Photos library automatically
2. 📤 Syncs to server with WebSocket live status
3. 🎯 Detects milestones with AI coaching insights
4. 📊 Shows real-time progress on web dashboard
5. 🔄 Works offline with automatic sync when online

## Installation (2 minutes)

### Server Setup
```bash
# 1. Clone and navigate
git clone <repo> && cd diving-analyser/backend
python3 -m venv venv && source venv/bin/activate

# 2. Install and setup database
pip install -r requirements.txt
python -m alembic upgrade head

# 3. Start server
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Mac-Agent Setup
```bash
# On your Mac
cd diving-analyser/mac-agent
./install.sh

# Follow prompts:
# - Server URL: https://your-server:8000
# - API Key: (get from server)
# - Photos library path: ~/Pictures/Photos\ Library.photoslibrary
```

### Dashboard (React Frontend)
```bash
# Optional: For real-time web dashboard
cd diving-analyser/frontend
npm install && npm start
# Opens http://localhost:3000
```

## First Sync (1 minute)

### Step 1: Tag Dives in Photos
Open Photos app and add captions to dive videos:
```
101B P 1m        ← Forward somersault, Perfect, 1m
201C G 3m        ← Back dive, Good, 3m
5231D P 5m SYNC  ← Inward twists, Perfect, 5m, synchronized
```

### Step 2: Start Mac-Agent
```bash
# Agent auto-starts on login via LaunchAgent
# Or manually:
~/.diveanalyzer/venv/bin/python -m src.main

# Check status:
launchctl list | grep diveanalyzer
```

### Step 3: Monitor on Dashboard
1. Open http://your-server:8000 (or http://localhost:3000 if running locally)
2. Watch real-time sync progress:
   - 🟢 **Sync Started**: Video extraction begins
   - 🔵 **50/500**: Real-time video counter
   - 🟡 **Milestone Detected**: "First Perfect Dive!"
   - ✅ **Sync Complete**: All done in 2.5s

## Usage

### View Sync Status
```bash
# Check if agent is running
launchctl list | grep diveanalyzer

# View live logs
tail -f ~/Library/Logs/diveanalyzer.log

# Check pending videos in offline queue
cat ~/.diveanalyzer/queue.json | jq '.videos | length'
```

### View Journey & Milestones
```bash
# REST API
curl https://your-server:8000/api/v1/journey

# Or web dashboard: https://your-server:8000/dashboard
```

### Manual Sync Commands
```bash
# Force sync immediately (instead of waiting for cron)
~/.diveanalyzer/venv/bin/python -m src.main --sync-now

# Extract only (don't sync)
~/.diveanalyzer/venv/bin/python -m src.main --extract-only

# View extracted metadata
cat ~/.diveanalyzer/last_extraction.json | jq '.dives | length'
```

## Real-time Updates

### WebSocket Connection
```javascript
// JavaScript example (React)
const ws = new WebSocket('wss://your-server/api/v1/ws/sync?client_id=dashboard-1');

ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);

  if (msg.type === 'sync_started') {
    console.log(`Sync starting: ${msg.data.total_videos} videos`);
  }
  if (msg.type === 'sync_progress') {
    console.log(`Progress: ${msg.data.synced_count}/${msg.data.total_videos}`);
  }
  if (msg.type === 'milestone_detected') {
    console.log(`🎉 Milestone: ${msg.data.title}`);
  }
};
```

### Event Types
| Event | Payload | Example |
|-------|---------|---------|
| `sync_started` | `{total_videos: 500}` | Batch sync begins |
| `sync_progress` | `{synced_count: 50, total_videos: 500}` | Every 50 dives |
| `sync_complete` | `{synced_count: 500}` | Sync finished |
| `milestone_detected` | `{type: "first_success", title: "..."}` | Achievement unlocked |
| `sync_error` | `{error: "..."}` | Failure message |

## Troubleshooting

### Agent Not Syncing
```bash
# 1. Check if running
launchctl list | grep diveanalyzer

# 2. Check logs
tail -100 ~/Library/Logs/diveanalyzer.log

# 3. Verify config
cat ~/.diveanalyzer/config.yaml

# 4. Test connection
curl -k https://your-server:8000/health

# 5. Manual restart
launchctl unload ~/Library/LaunchAgents/com.diveanalyzer.agent.plist
launchctl load ~/Library/LaunchAgents/com.diveanalyzer.agent.plist
```

### Server Not Responding
```bash
# 1. Check server status
curl https://your-server:8000/health

# 2. Check logs
ssh mcauchy@192.168.1.57 "tail -100 /var/log/diveanalyzer/app.log"

# 3. Check database
ssh mcauchy@192.168.1.57 "psql -d diving_analyser -c 'SELECT COUNT(*) FROM dives;'"

# 4. Restart server
ssh mcauchy@192.168.1.57 "systemctl restart diveanalyzer"
```

### Offline Queue Not Syncing
```bash
# 1. Check queue size
cat ~/.diveanalyzer/queue.json | jq '.videos | length'

# 2. Check network
ping google.com

# 3. Manual sync attempt
~/.diveanalyzer/venv/bin/python -m src.main --force-sync

# 4. Clear and restart if corrupted
rm ~/.diveanalyzer/queue.json
launchctl unload ~/Library/LaunchAgents/com.diveanalyzer.agent.plist
launchctl load ~/Library/LaunchAgents/com.diveanalyzer.agent.plist
```

## Caption Format Reference

### Basic Syntax
```
DIVECODE PERF [HEIGHT] [SYNC] [SMACK] [PERSON]
```

### Dive Codes (FINA format)
- **1xx** - Forward dives (101-108)
- **2xx** - Back dives (201-208)
- **3xx** - Reverse dives (301-308)
- **4xx** - Inward dives (401-408)
- **5xxx** - Twisting dives (5111-5238)

Position suffix: `A`, `B`, `C`, `D` (straight, pike, tuck, free)

### Examples
```
101B M 1m              Forward somersault, Medium, 1m
201C G 3m              Back dive pike, Good, 3m
301C P 5m              Reverse pike, Perfect, 5m
5231D P 10m SYNC       Inward 1.5 twists, Perfect, 10m, synced
010B M                 Front lineup (formation)
103B F SMACK           Belly flop indicator
```

### Performance Ratings
- `F` = Failed (0/4) - Landed on back/side
- `B` = Bad (1/4) - Missed rotation or entry
- `M` = Medium (2/4) - Decent entry, some splash
- `G` = Good (3/4) - Minimal splash, good technique
- `P` = Perfect (4/4) - Excellent entry, no splash

## Configuration

### `~/.diveanalyzer/config.yaml`
```yaml
server:
  url: "https://192.168.1.57:8000"
  api_key: "your-40-char-api-key-here"
  timeout_seconds: 30

photos:
  library_path: "~/Pictures/Photos Library.photoslibrary"

sync:
  interval_seconds: 300        # Check every 5 minutes
  batch_size: 50               # Videos per batch
  max_retries: 3               # Retry 3 times on failure

logging:
  level: "INFO"                # DEBUG, INFO, WARNING, ERROR
  file: "~/Library/Logs/diveanalyzer.log"
  rotate_mb: 10                # Rotate at 10MB
  keep_files: 5                # Keep 5 old files
```

## Advanced Usage

### API Endpoints
```bash
# Get all active syncs
curl https://your-server:8000/api/v1/ws/sync/status

# Get specific sync status
curl https://your-server:8000/api/v1/ws/sync/status/{sync_id}

# Get Journey milestones
curl https://your-server:8000/api/v1/journey

# Get dive analytics
curl https://your-server:8000/api/v1/analytics
```

### Performance Monitoring
```bash
# Track agent resource usage
top -p $(pgrep -f "diveanalyzer")

# Monitor server load
ssh mcauchy@192.168.1.57 "watch -n 1 'top -b -n 1 | head -15'"

# Check sync success rate (last 24h)
ssh mcauchy@192.168.1.57 "grep -c 'sync_complete' /var/log/diveanalyzer/app.log"
```

### Batch Operations
```bash
# Extract and sync 1000 videos at once
~/.diveanalyzer/venv/bin/python -m src.main --batch-size 100 --max-batch 10

# Sync with specific video filter
~/.diveanalyzer/venv/bin/python -m src.main --from-date 2026-01-01
```

## Support & Help

| Issue | Solution |
|-------|----------|
| Agent crashes | Check `diveanalyzer.log`, auto-restart via heartbeat |
| Connection timeout | Increase `timeout_seconds` in config, check firewall |
| Database full | Delete old metadata: `rm ~/.diveanalyzer/metadata_*.json` |
| Photos not found | Verify path in config, check Photos app access |
| Duplicate syncs | UUID deduplication prevents, safe to retry |

## Next Steps

1. **Tag 20+ dives** in Photos with proper captions
2. **Wait for first sync** (happens automatically in 5 min)
3. **Check dashboard** for real-time progress
4. **View milestones** to see achievements
5. **Analyze journey** with coaching insights

## Documentation

- 📖 **Full User Guide**: [README.md](README.md)
- 🏗️ **Architecture**: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- 🔒 **Security**: [docs/SECURITY.md](docs/SECURITY.md)
- 📊 **API Reference**: [docs/API.md](docs/API.md)
- 🚀 **Deployment**: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)

---

**Status**: Production Ready ✅
**Last Updated**: Jan 31, 2026
**Support**: Check logs or open an issue
