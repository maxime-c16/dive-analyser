# Diving Analyser Mac Agent

Auto-sync dive videos from macOS Photos library to Diving Analyser server with automatic retry logic, offline resilience, and crash recovery.

## Features

- **Automatic Extraction**: Extracts dive metadata from Photos library captions
- **Smart Sync**: Posts videos to server with exponential backoff retry logic
- **Offline Support**: Queues videos when network is unavailable
- **Auto-Recovery**: Resumes from queue after network restoration
- **LaunchAgent Integration**: Starts automatically on login
- **Crash Recovery**: Detects stale heartbeats and resumes from last checkpoint
- **Log Rotation**: Automatically rotates and compresses logs to save space
- **Configuration Validation**: Validates all settings with helpful error messages

## Installation

### Quick Start

```bash
./install.sh
```

Follow prompts for server URL, API key, and Photos library path.

### Manual Installation

```bash
mkdir -p ~/.diveanalyzer
python3.12 -m venv ~/.diveanalyzer/venv
source ~/.diveanalyzer/venv/bin/activate
pip install -r requirements.txt
pip install -e .
cp config.example.yaml ~/.diveanalyzer/config.yaml
cp com.diveanalyzer.agent.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.diveanalyzer.agent.plist
```

## Configuration

Edit `~/.diveanalyzer/config.yaml`:

```yaml
server:
  url: "https://192.168.1.57:8000"
  api_key: "your_40_character_api_key"
  timeout_seconds: 30

photos:
  library_path: "~/Pictures/Photos Library.photoslibrary"

sync:
  interval_seconds: 300
  batch_size: 50
  max_retries: 3

logging:
  level: "INFO"
  file: "~/Library/Logs/diveanalyzer.log"
  rotate_mb: 10
  keep_files: 5
```

## Usage

### Check Status

```bash
launchctl list | grep diveanalyzer
tail -f ~/Library/Logs/diveanalyzer.log
```

### Operations

```bash
./upgrade.sh       # Upgrade agent
./uninstall.sh     # Remove agent
```

## Troubleshooting

### Agent Not Running

```bash
launchctl list | grep diveanalyzer
tail -100 ~/Library/Logs/diveanalyzer.log
```

### Configuration Issues

Check that:
- `server.url` uses HTTPS
- `api_key` is 40+ characters
- `photos.library_path` exists and is readable
- All required fields are present

### Network Issues

Agent automatically queues videos offline:

```bash
cat ~/.diveanalyzer/queue.json | jq '.videos | length'
```

## Architecture

### Extraction
- Reads Photos library with osxphotos
- Parses dive captions (legacy & two-phase formats)
- Tracks checkpoint for incremental extraction
- Error recovery for locked databases

### Sync
- Async HTTPS with connection pooling
- Exponential backoff (1s → 30s)
- Batch processing (50 videos/batch)
- Offline queue with atomic persistence
- Network detection with wait logic
- Rate limiting (429 handling)

## Performance

| Operation | Time |
|-----------|------|
| Extract | 30-45s |
| Sync single | <500ms |
| Sync batch (50) | <3s |
| Online check | <5s |

## Requirements

- macOS 10.13+
- Python 3.12+
- 500MB disk space
- HTTPS connectivity to server

## Data Locations

- Config: `~/.diveanalyzer/config.yaml`
- Logs: `~/Library/Logs/diveanalyzer.log`
- Queue: `~/.diveanalyzer/queue.json`
- LaunchAgent: `~/Library/LaunchAgents/com.diveanalyzer.agent.plist`

## Support

1. Check logs: `~/Library/Logs/diveanalyzer.log`
2. Verify configuration: `cat ~/.diveanalyzer/config.yaml`
3. Check network: `curl -k https://192.168.1.57:8000/health`
4. Review troubleshooting section above
