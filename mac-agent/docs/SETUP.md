# Setup Guide

Complete installation guide for Diving Analytics Platform.

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Server Setup (Docker)](#server-setup-docker)
- [Mac Agent Setup](#mac-agent-setup)
- [Verification](#verification)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Server (Production)
- Ubuntu 20.04+ or macOS
- Docker 20.10+
- Docker Compose 2.0+
- 2GB RAM minimum
- 10GB disk space
- Network access on ports: 6090 (HTTP), 6002 (backend), 6432 (postgres)

### Mac Agent (Development)
- macOS 10.13+ (High Sierra or later)
- Python 3.12+
- Photos.app with dive videos
- Network access to server

---

## Server Setup (Docker)

### 1. Clone Repository

```bash
git clone https://github.com/maxime-c16/diving-analyser.git
cd diving-analyser
```

### 2. Configure Environment

```bash
# Copy environment template
cp .env.example .env

# Edit configuration
nano .env
```

**Essential Settings:**
```bash
POSTGRES_USER=diving
POSTGRES_PASSWORD=your_secure_password_here
POSTGRES_DB=diving_analyzer_db
```

### 3. Start Services

```bash
# Start all containers
docker-compose up -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f backend
```

**Expected Output:**
```
NAME                COMMAND                  SERVICE     STATUS
diving_network-postgres-1   "docker-entrypoint.s…"   postgres    Up
diving_network-backend-1    "uvicorn app.main:ap…"   backend     Up
diving_network-frontend-1   "npm run dev"            frontend    Up
diving_network-nginx-1      "/docker-entrypoint.…"   nginx       Up
diving_network-adminer-1    "entrypoint.sh"          adminer     Up
```

### 4. Access Web UI

Open browser to:
```
http://SERVER_IP:6090
```

For local testing:
```
http://localhost:6090
```

### 5. Verify Database

Access Adminer (database admin):
```
http://SERVER_IP:6080
```

**Login Credentials:**
- System: PostgreSQL
- Server: postgres
- Username: diving
- Password: (from .env)
- Database: diving_analyzer_db

**Check Tables:**
- sessions
- dives
- dive_codes_metadata
- agent_keys

### 6. Initialize Sample Data (Optional)

```bash
# Import sample dives
docker-compose exec backend python -c "from app.services.import_service import import_sample_data; import_sample_data()"
```

---

## Mac Agent Setup

### 1. Navigate to Agent Directory

```bash
cd mac-agent
```

### 2. Install Python Dependencies

```bash
# Create virtual environment
python3.12 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Configure Agent

```bash
# Copy config template
cp config.example.yaml config.yaml

# Edit configuration
nano config.yaml
```

**Essential Settings:**
```yaml
server:
  url: "http://192.168.1.57:6090"  # Your server URL
  api_key: "your-api-key-here"     # Generate on server

photos:
  library_path: "/Users/YOUR_USERNAME/Pictures/Photos Library.photoslibrary"
  poll_interval: 300  # 5 minutes

sync:
  batch_size: 50
  retry_attempts: 3
  backoff_factor: 2.0

logging:
  level: INFO
  file: "~/Library/Logs/dive-analyzer/agent.log"
```

### 4. Generate API Key (On Server)

```bash
# On server machine
docker-compose exec backend python -c "from app.security import generate_api_key; print(generate_api_key())"
```

Copy the generated key to `config.yaml` under `server.api_key`.

### 5. Test Agent Manually

```bash
# Run agent in foreground (test mode)
source venv/bin/activate
python src/main.py
```

**Expected Output:**
```
[INFO] Dive Analyzer Agent starting...
[INFO] Connected to server: http://192.168.1.57:6090
[INFO] Watching Photos library: /Users/you/Pictures/Photos Library.photoslibrary
[INFO] Found 15 new dives
[INFO] Syncing batch of 15 dives...
[INFO] Sync complete: 15/15 successful
```

### 6. Install as Background Service

```bash
# Install LaunchAgent (auto-start on login)
./install.sh

# Check status
launchctl list | grep dive-analyzer

# View logs
tail -f ~/Library/Logs/dive-analyzer/agent.log
```

### 7. Manage Agent

```bash
# Stop agent
launchctl unload ~/Library/LaunchAgents/com.diveanalyzer.agent.plist

# Start agent
launchctl load ~/Library/LaunchAgents/com.diveanalyzer.agent.plist

# Restart agent
launchctl unload ~/Library/LaunchAgents/com.diveanalyzer.agent.plist
launchctl load ~/Library/LaunchAgents/com.diveanalyzer.agent.plist

# Uninstall agent
./uninstall.sh
```

---

## Verification

### 1. Check Server Health

```bash
# Health check endpoint
curl http://SERVER_IP:6090/api/health

# Expected response:
{"status": "healthy", "database": "connected", "version": "1.0.0"}
```

### 2. Verify Database Connection

```bash
# Check database from backend container
docker-compose exec backend python -c "from app.database import engine; print(engine.execute('SELECT COUNT(*) FROM dives').scalar())"
```

### 3. Test API Endpoints

```bash
# Get recent dives
curl http://SERVER_IP:6090/api/v1/dives/recent?limit=5

# Get analytics
curl http://SERVER_IP:6090/api/v1/analytics/overall

# Get journey data
curl http://SERVER_IP:6090/api/v1/journey/milestones
```

### 4. Verify WebSocket

Open browser console on web UI:
```javascript
const ws = new WebSocket('ws://SERVER_IP:6090/api/v1/ws')
ws.onmessage = (event) => console.log(JSON.parse(event.data))
```

Expected: Periodic sync status messages.

### 5. Test Mac Agent Sync

```bash
# Add a test dive in Photos.app
# Caption: "101B M 3m"

# Check agent logs
tail -f ~/Library/Logs/dive-analyzer/agent.log

# Expected output:
# [INFO] New dive detected: 101B M 3m
# [INFO] Syncing dive...
# [INFO] Sync successful: dive_id=1722
```

---

## Troubleshooting

### Server Won't Start

**Check Docker:**
```bash
docker --version
docker-compose --version
```

**Check Logs:**
```bash
docker-compose logs backend
docker-compose logs postgres
```

**Common Issues:**
- Port conflicts: Change ports in `docker-compose.yml`
- Permission errors: Run with `sudo` or fix Docker permissions
- Memory issues: Increase Docker memory limit

### Database Connection Fails

**Check Postgres Status:**
```bash
docker-compose ps postgres
docker-compose logs postgres
```

**Manual Connection Test:**
```bash
docker-compose exec postgres psql -U diving -d diving_analyzer_db
```

**Fix:**
```bash
# Reset database
docker-compose down -v
docker-compose up -d
```

### Frontend Shows Errors

**Check Backend Connection:**
```bash
curl http://SERVER_IP:6002/api/health
```

**Check Environment Variables:**
```bash
docker-compose exec frontend env | grep VITE
```

**Fix:**
- Ensure `VITE_API_URL` points to correct backend
- Check Nginx configuration in `nginx/nginx.conf`
- Clear browser cache

### Mac Agent Not Syncing

**Check Configuration:**
```bash
cat mac-agent/config.yaml
```

**Test Server Connection:**
```bash
curl http://SERVER_IP:6090/api/health
```

**Check API Key:**
```bash
# Verify API key is correct
grep api_key mac-agent/config.yaml
```

**Check Logs:**
```bash
tail -f ~/Library/Logs/dive-analyzer/agent.log
```

**Common Issues:**
- Photos library path incorrect
- API key invalid
- Server unreachable (firewall/network)
- Insufficient permissions (Photos access)

### No Dives Appearing

**Check Photos Library:**
```bash
# List videos with captions
python -c "
from osxphotos import PhotosDB
db = PhotosDB()
videos = [p for p in db.photos(videos=True) if p.description]
print(f'Found {len(videos)} videos with captions')
"
```

**Check Caption Format:**
- Valid: `101B M 3m`
- Valid: `101B G/P 5m`
- Invalid: `101B` (missing performance)

**Check Sync Status:**
```bash
# On server
docker-compose logs backend | grep sync
```

---

## Next Steps

After successful setup:

1. **Add Dive Captions** - Tag videos in Photos.app
2. **Monitor Sync** - Watch agent logs for sync activity
3. **View Analytics** - Open web UI to see dashboard
4. **Explore Journey** - Check milestone detection
5. **Customize** - Adjust settings in `config.yaml`

See [USAGE.md](USAGE.md) for detailed usage instructions.

---

## Support

**Having issues?**
1. Check [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
2. Review logs: `docker-compose logs -f`
3. Open an issue on GitHub
