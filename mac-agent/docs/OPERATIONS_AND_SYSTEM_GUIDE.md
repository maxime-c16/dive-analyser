# DiveSensei Operations and System Guide

This document is for future local agents and maintainers. It explains how the
live DiveSensei system works, how the Mac and Debian server cooperate, what is
safe to do, what must not be done, and how to recover common failures.

The system is LAN/WireGuard oriented. Do not assume public-internet hardening.

## 1. Mental Model

DiveSensei is a two-machine system:

- **Debian production server** at `192.168.1.57`
  - Runs Docker Compose services.
  - Owns the PostgreSQL database.
  - Serves the backend API, nginx, and frontend.
  - Stores finalized media cache artifacts under `media/cache`.
- **MacBook media agent**
  - Has access to the macOS Photos library through `osxphotos`.
  - Syncs Photos metadata to the server.
  - Leases one media job at a time.
  - Materializes exactly one Photos asset when needed.
  - Transcodes poster/proxy renditions.
  - Uploads and finalizes artifacts into the Debian cache.

The key architectural rule is:

```text
Debian stores truth, jobs, and cache.
Mac owns Photos access and media fulfillment.
```

The server must never directly access the Photos library. The Mac agent must not
write directly to production database tables. It talks to the backend API.

## 2. Production Locations

### Debian

```bash
ssh mcauchy@192.168.1.57
cd /home/mcauchy/dive-analyser
```

Important services:

```text
dive-analyser-postgres-1
dive-analyser-backend-1
dive-analyser-frontend-1
dive-analyser-nginx-1
dive-analyser-adminer-1
```

Important paths:

```text
/home/mcauchy/dive-analyser
/home/mcauchy/dive-analyser/media/cache
/home/mcauchy/dive-analyser/backups
```

Important ports:

```text
6090  LAN nginx app
6002  backend container port exposed on host
6001  frontend container port exposed on host
5433  PostgreSQL host port
8080  Adminer
```

### Mac

Important paths:

```text
~/.diveanalyzer/config.yaml
~/.diveanalyzer/code
~/.diveanalyzer/venv
~/.diveanalyzer/media_tmp
~/.diveanalyzer/materialized_assets
~/Library/LaunchAgents/com.diveanalyzer.agent.plist
~/Library/Logs/diveanalyzer.log
~/Library/Logs/diveanalyzer.error.log
```

The launchd agent runs:

```text
~/.diveanalyzer/venv/bin/python3 -m src.main
```

from:

```text
~/.diveanalyzer/code
```

## 3. Current Safety Policy

The live media policy is intentionally constrained:

```yaml
media:
  enabled: true
  max_jobs: 1
  fail_unimplemented_jobs: false
  allow_original: false
  allow_icloud_download: false
  allow_single_asset_materialization: true
  materialization_cleanup_after_success: true
  capabilities:
    - poster
    - proxy_360p
```

Do not enable:

```text
original
proxy_720p
bulk warming
public exposure
more than one Mac job
global Photos "Download Originals to this Mac"
```

Important nuance:

```text
allow_single_asset_materialization=true
```

means the agent may run a single-UUID `osxphotos export --download-missing`
command for the exact leased job UUID. It is not a license for broad iCloud
download or bulk Photos export.

Current config validation also treats single-asset materialization as requiring:

```text
media.max_jobs = 1
```

Do not raise Mac concurrency unless that invariant is intentionally redesigned,
tested, and documented.

## 4. Data Model Overview

Core tables:

```text
dives
sessions
photos_assets
dive_modifiers
divers
diver_aliases
training_periods
media_jobs
media_cache_entries
media_population_runs
media_population_run_items
representative_media_selections
```

Key relationships:

```text
dives.video_uuid -> photos_assets.video_uuid
dives.photos_asset_id -> photos_assets.id
media_jobs.photos_asset_id -> photos_assets.id
media_cache_entries.photos_asset_id -> photos_assets.id
dives.diver_id -> divers.id
```

`dives.person_name` is retained for compatibility, but normalized diver identity
is `dives.diver_id`.

## 5. Diver Scope Rules

The base app is self-centered.

Default behavior:

```text
diver_scope=self
```

Base analytics, charts, videos, representative media, and derived statistics
should use the primary diver only.

Explicit alternatives:

```text
diver_scope=all
diver_scope=selected&diver_id=<id>
diver_scope=selected&diver_ids=<ids>
```

Do not silently mix all divers into base statistics. Peer/other-diver analysis
must be intentional and visible in the UI.

Known primary diver:

```text
Maxime
```

Examples:

```bash
curl "http://localhost:6090/api/v1/dive-analysis/103B"
curl "http://localhost:6090/api/v1/dive-analysis/103B?diver_scope=all"
curl "http://localhost:6090/api/v1/media/representatives?diver_scope=self"
curl "http://localhost:6090/api/v1/media/representatives?diver_scope=all"
```

## 6. Dive Code Semantics

The final letter of the canonical dive code is the dive position:

```text
A = straight
B = pike
C = tuck
D = free
```

Examples:

```text
103B P -> dive_code=103B, position=B, performance=P
103B G -> dive_code=103B, position=B, performance=G
103C B -> dive_code=103C, position=C, performance=B
```

Do not interpret the second token as position. It is usually the performance
label.

Expected exact search behavior:

```text
103B -> only 103B attempts
103C -> only 103C attempts
103  -> no exact analysis, unless a future family mode is explicit
```

Straight jumps such as `100B` are excluded from performance analytics and should
return HTTP 422 from per-dive analysis.

## 7. Media Pipeline

### Happy Path

```text
UI calls GET /api/v1/media/{uuid}/status
User clicks Prepare
UI calls POST /api/v1/media/{uuid}/request
Backend creates/reuses one media job
Mac leases job
Mac resolves source file
Mac transcodes poster/proxy_360p
Mac uploads temp artifact
Backend verifies checksum and cache path
Backend finalizes media_cache_entries row
UI plays /api/v1/media/cache/{entry_id}/play
```

### Renders

Supported renditions:

```text
poster
proxy_360p
```

Forbidden in this deployment:

```text
proxy_720p
original
```

### Media Status API

```bash
curl -sS "http://localhost:6090/api/v1/media/<UUID>/status" | jq
```

Important fields:

```text
status
available_renditions
poster_url
playback_url
job
can_request
```

### Playback API

```text
GET  /api/v1/media/cache/{entry_id}/play
HEAD /api/v1/media/cache/{entry_id}/play
```

The server supports Safari-compatible:

```text
HEAD
Range
206 Partial Content
Content-Range
Accept-Ranges
Content-Disposition: inline
```

## 8. Photos Materialization Nuances

This is the subtle part of the system.

macOS Photos may show a video as visible/playable while `osxphotos` initially
reports:

```text
ismissing=True
incloud=True
path=None
```

or it may export only a tiny placeholder file around 685-695 bytes.

Observed states:

### Good local path

```text
ismissing=False
path=/Users/.../Photos Library.photoslibrary/originals/.../<UUID>.mov
file size is MBs
```

The agent should use the local `photo.path` directly.

### Placeholder-only export

```text
osxphotos export --uuid <UUID> ...
-> IMG_1234.mov, 685 bytes
```

This is not a usable video. The job is marked:

```text
materialization_only_placeholders
```

### Stale agent cache after Photos refresh

After manually opening/downloading videos in Photos, the long-running Mac agent
may still hold an old PhotosDB view where the asset has no path. The fix is:

```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.diveanalyzer.agent.plist || true
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.diveanalyzer.agent.plist
```

Then retry.

This exact sequence fixed the representative rescue batch:

```text
open/download videos in Photos
verify local Photos original file is MB-sized
restart Mac agent
retry media jobs
```

## 9. Representative Media System

Representative media is a curated, bounded feature, not bulk warming.

Goal per canonical dive code:

```text
Low
Typical
High
```

Each representative is selected from the exact canonical dive code and, by
default, the primary diver only.

Important endpoints:

```text
GET  /api/v1/media/representative-manifest
POST /api/v1/media/representative-manifest/prepare
GET  /api/v1/media/representative-manifest/runs/{id}
GET  /api/v1/media/representatives
GET  /api/v1/media/representatives/coverage
GET  /api/v1/media/representatives/{dive_code}/{role}/replacement-candidates
POST /api/v1/media/representatives/{dive_code}/{role}/replace
```

The manifest endpoint must remain read-only. It must not create jobs.

Representative states:

```text
ready
partial
missing
unavailable
replacement_available
replacement_exhausted
```

Use `Typical` in user-facing UI for the median representative.

### Replacement Rules

Replacement candidates must:

```text
belong to the same exact canonical dive code
respect diver scope
not duplicate another active representative
avoid known placeholder failures by default
prefer ready/previously successful/untested candidates
preserve context where possible
```

Replacement with `prepare=true` may create at most missing poster/proxy jobs for
that one selected candidate. It is not a bulk retry.

## 10. Frontend Model

The frontend must use the media API for normal video flow:

```text
GET  /api/v1/media/{uuid}/status
POST /api/v1/media/{uuid}/request
GET  /api/v1/media/cache/{entry_id}/play
```

Legacy routes remain as compatibility fallback only:

```text
GET /api/v1/videos/check/{uuid}
GET /api/v1/videos/{uuid}
```

Do not build new playback against legacy routes.

Important frontend routes:

```text
/
/dives
/dives/analysis/:diveCode
/media/representatives
/sessions
/journey
/analytics
```

Important source files:

```text
frontend/src/pages/DiveAnalysis.tsx
frontend/src/pages/RepresentativeMedia.tsx
frontend/src/services/diveAnalysisApi.ts
frontend/src/services/representativeMediaApi.ts
frontend/src/services/mediaApi.ts
frontend/src/router.tsx
```

## 11. Backend Model

Important backend files:

```text
backend/app/api/v1/media.py
backend/app/api/v1/dive_analysis.py
backend/app/api/v1/analytics.py
backend/app/services/media_jobs.py
backend/app/services/media_cache.py
backend/app/services/representative_media.py
backend/app/services/representative_population.py
backend/app/services/dive_analysis_service.py
backend/app/services/diver_identity.py
backend/app/services/performance_scoring.py
```

Media job statuses:

```text
queued
waiting_for_mac
claimed
materializing
exporting
transcoding
uploading
verifying
ready
failed
unavailable
```

Active statuses:

```sql
queued,
waiting_for_mac,
claimed,
materializing,
exporting,
transcoding,
uploading,
verifying
```

Duplicate active jobs for the same `media_key` must never appear.

## 12. Mac Agent Model

Important Mac source files:

```text
mac-agent/src/main.py
mac-agent/src/config.py
mac-agent/src/photos_reader.py
mac-agent/src/media_jobs.py
mac-agent/src/media_exporter.py
mac-agent/src/media_materializer.py
mac-agent/src/transcoder.py
mac-agent/src/media_uploader.py
mac-agent/src/sync_client.py
```

Agent flow:

```text
load config
sync metadata periodically
poll backend for media jobs
lease up to max_jobs
resolve source
transcode
upload
finalize
cleanup temp/materialized source if success
retain failed diagnostics according to TTL policy
```

## 13. Common Commands

### Production Health

```bash
ssh mcauchy@192.168.1.57
cd /home/mcauchy/dive-analyser
docker-compose ps
curl -f http://localhost:6090/api/v1/health
curl -f "http://localhost:6090/api/v1/dives?limit=1"
curl -f "http://localhost:6090/api/v1/analytics/overall"
```

### DB Media Summary

```bash
docker exec dive-analyser-postgres-1 psql \
  -U diving \
  -d diving_analyzer_db \
  -c "
SELECT status, rendition, count(*)
FROM media_jobs
GROUP BY status, rendition
ORDER BY rendition, status;

SELECT rendition, count(*), sum(size_bytes)
FROM media_cache_entries
GROUP BY rendition
ORDER BY rendition;
"
```

### Active Job Check

```bash
docker exec dive-analyser-postgres-1 psql \
  -U diving \
  -d diving_analyzer_db \
  -c "
SELECT count(*) AS active_jobs
FROM media_jobs
WHERE status IN (
  'queued',
  'waiting_for_mac',
  'claimed',
  'materializing',
  'exporting',
  'transcoding',
  'uploading',
  'verifying'
);
"
```

### Duplicate Active Job Check

```bash
docker exec dive-analyser-postgres-1 psql \
  -U diving \
  -d diving_analyzer_db \
  -c "
SELECT media_key, rendition, status, count(*)
FROM media_jobs
WHERE status IN (
  'queued',
  'waiting_for_mac',
  'claimed',
  'materializing',
  'exporting',
  'transcoding',
  'uploading',
  'verifying'
)
GROUP BY media_key, rendition, status
HAVING count(*) > 1;
"
```

### Mac Agent Restart

```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.diveanalyzer.agent.plist || true
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.diveanalyzer.agent.plist
launchctl print gui/$(id -u)/com.diveanalyzer.agent | sed -n '1,80p'
```

### Mac Logs

```bash
tail -n 150 ~/Library/Logs/diveanalyzer.log
tail -n 150 ~/Library/Logs/diveanalyzer.error.log
```

### Photos UUID Probe

```bash
~/.diveanalyzer/venv/bin/python - <<'PY'
import osxphotos
UUID = "<UUID>"
db = osxphotos.PhotosDB()
for p in db.photos(uuid=[UUID]):
    print({
        "uuid": p.uuid,
        "filename": p.filename,
        "description": p.description,
        "ismovie": p.ismovie,
        "ismissing": p.ismissing,
        "incloud": getattr(p, "incloud", None),
        "path": str(p.path) if p.path else None,
        "path_edited": str(p.path_edited) if getattr(p, "path_edited", None) else None,
    })
PY
```

### Verify Actual Photos File

```bash
ls -lh "/Users/mcauchy/Pictures/Photos Library.photoslibrary/originals/.../<UUID>.mov"
file "/Users/mcauchy/Pictures/Photos Library.photoslibrary/originals/.../<UUID>.mov"
du -h "/Users/mcauchy/Pictures/Photos Library.photoslibrary/originals/.../<UUID>.mov"
```

A valid video should be MB-sized. A 685-695 byte `.mov` is a placeholder.

## 14. Build and Deploy Notes

### Backend

Backend Compose has a build definition.

```bash
docker-compose up -d --no-deps --build backend
```

### Frontend

On production, Compose defines frontend as an image-only service. Do not assume:

```bash
docker-compose build frontend
```

will rebuild it. Use the production Dockerfile explicitly:

```bash
docker build -f frontend/Dockerfile.deploy -t dive-analyser-frontend:latest frontend
docker-compose up -d --no-deps frontend
```

Do not build production frontend with `frontend/Dockerfile`; that is a dev-server
container and can cause nginx `502 Bad Gateway`.

### Frontend Asset Check

```bash
curl -sS http://localhost:6090/ | sed -n '1,20p'
```

## 15. Validation Commands

Backend representative tests:

```bash
PYTHONPATH=backend .phase-test-venv/bin/python -m pytest \
  backend/tests/test_representative_media.py \
  backend/tests/test_representative_population.py \
  -q
```

Mac media tests:

```bash
PYTHONPATH=mac-agent .phase-test-venv/bin/python -m pytest \
  mac-agent/tests/test_metadata.py \
  mac-agent/tests/test_media_safety.py \
  -q
```

Frontend:

```bash
cd frontend
npm run typecheck
npm run test -- --run
npm run build
```

Static audit:

```bash
grep -Rni "/api/v1/videos\|videos/check" frontend/dist || true
grep -Rni "/api/v1/media" frontend/dist || true
```

## 16. Recovery Procedures

### Backup Before Production DB Changes

```bash
mkdir -p backups/database

docker exec dive-analyser-postgres-1 pg_dump \
  -U diving \
  -d diving_analyzer_db \
  -Fc \
  -f /tmp/divesensei-backup.dump

docker cp \
  dive-analyser-postgres-1:/tmp/divesensei-backup.dump \
  backups/database/divesensei-backup-$(date +%Y%m%d-%H%M%S).dump
```

### Archive Frontend Before Replacing

```bash
mkdir -p backups/frontend
docker cp dive-analyser-frontend-1:/usr/share/nginx/html backups/frontend/live-ui-$(date +%Y%m%d-%H%M%S)
```

Rollback:

```bash
docker cp backups/frontend/<archive>/. dive-analyser-frontend-1:/usr/share/nginx/html
docker restart dive-analyser-frontend-1
```

### Media Job Stuck

1. Check active jobs.
2. Check Mac logs.
3. Check backend logs.
4. If the Mac agent has stale Photos state, restart launchd.
5. Do not delete jobs unless you understand the state machine.

### Placeholder Failures

If a job fails with:

```text
materialization_only_placeholders
```

Do not bulk retry. Instead:

1. Identify exact UUID/date/caption.
2. Open/download that exact video in Photos.
3. Confirm actual original path is MB-sized.
4. Restart Mac agent.
5. Retry exactly that UUID.

### Permission Failures

Potential structured errors:

```text
permission_required
photos_access_denied
osxphotos_export_timeout
osxphotos_export_failed
```

For permission-like failures:

1. Stop creating new media jobs.
2. Check macOS privacy prompt.
3. Confirm Photos access with a read-only `osxphotos query`.
4. Restart agent.
5. Retry once.

### Frontend 502 After Rebuild

Likely cause: frontend image built with dev Dockerfile.

Fix:

```bash
docker build -f frontend/Dockerfile.deploy -t dive-analyser-frontend:latest frontend
docker-compose up -d --no-deps frontend
```

## 17. What Not To Do

Do not:

```text
enable original rendition
enable proxy_720p
raise max_jobs above 1 while single-asset materialization is enabled
bulk request all clips
bulk retry placeholder failures
run broad osxphotos export
use Photos "Download Originals to this Mac" globally
delete production tables
drop additive migration tables casually
remove backend legacy video fallback yet
serve frontend from unrecovered/minified bundle edits
mix all divers into base stats or representative media
build new UI playback against /api/v1/videos/*
delete materialized diagnostics outside configured cleanup policy
follow symlinks during cleanup
```

## 18. Basic Management Checklist

Daily/after changes:

```text
backend health OK
frontend route loads
Mac agent running
Photos access status OK
active jobs reasonable
duplicate active jobs zero
media/cache disk usage acceptable
base app uses self scope
all-diver mode remains explicit
```

## 19. Advanced Management Checklist

Before any rollout:

```text
record git status and commit
record Docker state
backup PostgreSQL
archive frontend
run targeted tests
deploy only required services
verify health/API/UI
verify no passive media jobs
verify representative coverage if media changed
document rollback
```

Before media population:

```text
save manifest
audit exact canonical dive grouping
confirm diver_scope=self unless intentionally all/selected
estimate cache growth
confirm active jobs = 0
confirm Mac Photos access OK
process bounded queue only
validate artifacts
record failures with date/caption/UUID
```

## 20. Current Known Limitations

```text
LAN/WireGuard only; auth remains weak for public exposure.
Photos/iCloud local availability is operationally fragile.
The Mac agent may need restart after manual Photos downloads.
Representative coverage depends on available Photos originals.
Some historical active selections may exist for all-diver mode; self mode filters them out.
Frontend bundle is large and could use future code splitting.
Compatibility fallback for legacy /api/v1/videos remains temporary.
```

## 21. Last Known Good Operational Pattern

For representative rescue:

```text
1. Identify self-scoped failed representative UUIDs.
2. User opens/downloads exact videos in Photos.
3. Verify osxphotos reports path and actual file is MB-sized.
4. Restart Mac agent.
5. Retry poster.
6. If poster ready, retry proxy_360p.
7. Validate HEAD/Range on cache entries.
8. Confirm active jobs = 0.
```

This pattern successfully rescued:

```text
102C
105C
5122A
104C
201B
```

after the agent restart refreshed the PhotosDB view.
