# Disaster Recovery and Rollback Procedures

**Version**: 1.0
**Date**: Jan 31, 2026
**Status**: COMPLETE

## Overview

Comprehensive disaster recovery procedures for the Diving Analyser system, covering scenarios from data loss to complete system failure.

## Recovery Time Objectives (RTO)

| Scenario | RTO | RPO |
|----------|-----|-----|
| WebSocket Connection Loss | 5-15 sec | 0 sec |
| Single Sync Failure | 2-5 min | 0 (auto-resume) |
| Database Corruption | 15-30 min | 1 hour |
| Backend Service Down | 5-10 min | 1 hour |
| Frontend App Crash | < 1 sec | 0 sec |
| Partial Data Loss | 30-60 min | 1 hour |
| Complete Data Loss | 2-4 hours | 24 hours |

## Scenario 1: WebSocket Connection Loss

### Symptoms
- UI shows "Disconnected" status
- Toast notification appears
- Sync operations pause

### Immediate Actions
1. Check backend service status
2. Verify network connectivity
3. Check browser console for errors

### Recovery Steps

```bash
# Check backend WebSocket endpoint
curl http://192.168.1.57:8000/api/v1/ws/health

# Should respond with:
{
  "status": "healthy",
  "connected_clients": 5,
  "active_syncs": 2,
  "completed_syncs": 8
}
```

**Automatic Recovery**:
- Client automatically reconnects after 5 seconds
- No manual intervention typically needed
- All queued messages resent after reconnection

**Manual Recovery** (if auto-recovery fails):
```typescript
// In browser console
const context = window.__SYNC_STATUS_CONTEXT__
context.connect()  // Force reconnection
```

## Scenario 2: Single Sync Failure

### Symptoms
- Sync starts but stalls at certain percentage
- Error message displayed in UI
- Retry button available

### Immediate Actions
1. Check error message for specifics
2. Verify network connectivity
3. Check backend logs

### Recovery Steps

```bash
# Check sync status
curl http://192.168.1.57:8000/api/v1/ws/sync/status

# Get specific sync status
curl http://192.168.1.57:8000/api/v1/ws/sync/status/[SYNC_ID]
```

**Auto-Resume**:
- Failed syncs automatically resume from last checkpoint
- No data loss due to built-in checkpointing

**Manual Retry**:
1. Click "Retry" button in UI error panel
2. System attempts sync again with exponential backoff
3. Max 3 retry attempts per sync

**Force Reset**:
```bash
# On mac-agent machine
python src/batch_extract_metadata.py --force-restart

# This clears the queue and starts fresh
```

## Scenario 3: Database Corruption

### Symptoms
- Query failures in backend
- 500 errors from API
- Incomplete milestone data

### Detection
```bash
# Check database integrity
python -m pytest backend/tests/test_data_integrity.py -v

# Verify sync state
curl http://192.168.1.57:8000/api/v1/journey/milestones
# Should return valid JSON
```

### Recovery Steps

**Step 1: Identify Corruption**
```bash
# Check database logs
tail -f /var/log/postgres/postgresql.log

# Run integrity check
psql -U diving_analyzer -d diving_analyzer_db -c "
  SELECT COUNT(*) FROM dives;
  SELECT COUNT(*) FROM milestones;
  SELECT COUNT(*) FROM sync_operations;
"
```

**Step 2: Restore from Backup**
```bash
# List available backups
ls -lah /backups/diving-analyser/

# Restore latest backup (within 1 hour)
pg_restore -U diving_analyzer -d diving_analyzer_db \
  /backups/diving-analyser/backup_20260131_0200.sql

# Verify restoration
psql -U diving_analyzer -d diving_analyzer_db -c "
  SELECT COUNT(*) FROM dives;
"
```

**Step 3: Resume Operations**
```bash
# Restart backend service
systemctl restart diving-analyser-backend

# Wait for health check
while ! curl -s http://localhost:8000/api/v1/ws/health | grep -q healthy; do
  sleep 2
done

echo "Backend recovered"
```

**Step 4: Restart Syncs**
```bash
# Resume any interrupted syncs
python src/batch_extract_metadata.py --resume-sync
```

## Scenario 4: Backend Service Down

### Symptoms
- All API calls return connection refused
- UI shows "Backend unavailable"
- WebSocket connections close

### Detection
```bash
# Check service status
systemctl status diving-analyser-backend

# Check if process is running
ps aux | grep -i diving

# Try to connect
curl http://192.168.1.57:8000/api/v1/ws/health
# Connection refused
```

### Recovery Steps

**Step 1: Restart Service**
```bash
# Restart backend
sudo systemctl restart diving-analyser-backend

# Monitor startup
journalctl -u diving-analyser-backend -f
```

**Step 2: Verify Health**
```bash
# Wait for startup (typically 30-60 seconds)
sleep 60

# Check health
curl http://192.168.1.57:8000/api/v1/ws/health

# Expected: 200 OK with health data
```

**Step 3: Reconnect Clients**
- UI automatically reconnects after 5 seconds
- No manual client action needed

**Step 4: Verify Data**
```bash
# Check recent syncs
curl http://192.168.1.57:8000/api/v1/ws/sync/status

# Check milestones
curl http://192.168.1.57:8000/api/v1/journey/milestones
```

## Scenario 5: Frontend App Crash

### Symptoms
- Browser shows error page or blank screen
- Console errors visible
- UI completely unresponsive

### Immediate Actions
1. Refresh page (Cmd+R)
2. Check browser console for errors (Cmd+Option+I)
3. Clear browser cache if needed

### Recovery Steps

**Step 1: Refresh Application**
```
1. Press Cmd+R to refresh
2. Wait 5 seconds for app to load
3. Check connection indicator
```

**Step 2: Clear Cache** (if refresh fails)
```
1. Open DevTools (Cmd+Option+I)
2. Right-click refresh button, select "Empty Cache and Hard Refresh"
3. Wait for page load
```

**Step 3: Check Backend**
```
1. Open DevTools → Network tab
2. Look for failed API calls
3. Check response status codes

If see 5xx errors:
  - Backend may be down
  - Follow "Backend Service Down" recovery
```

**Step 4: Verify Frontend Build**
```bash
# On deployment machine
cd frontend
npm run build

# Check for build errors
tail -f build-output.log

# Serve updated frontend
npm run preview
```

## Scenario 6: Partial Data Loss (Specific Records)

### Symptoms
- Missing milestones for date range
- Incomplete sync results
- Gaps in journey timeline

### Recovery Steps

**Step 1: Identify Missing Data**
```bash
# Check last sync date
curl http://192.168.1.57:8000/api/v1/journey/journey \
  | jq '.overview.latest_dive_date'

# Expected: Recent date
```

**Step 2: Recover from Backup**
```bash
# Restore specific table from backup
pg_restore -U diving_analyzer -d diving_analyzer_db \
  --table=milestones \
  /backups/diving-analyser/backup_20260131_0200.sql

# Verify
psql -U diving_analyzer -d diving_analyzer_db -c "
  SELECT COUNT(*) FROM milestones
  WHERE created_at > '2026-01-30'
"
```

**Step 3: Re-Detect Milestones**
```bash
# Force milestone re-detection
python backend/app/services/milestone_detector.py --force-redetect

# This recalculates all milestones from raw dive data
```

**Step 4: Rebuild Analytics**
```bash
# Rebuild analytics from raw data
python src/dive_analytics.py --input dive_metadata_report_final.json --force-rebuild

# Verify counts match
curl http://192.168.1.57:8000/api/v1/journey/journey | jq '.overview'
```

## Scenario 7: Complete Data Loss

### Symptoms
- Database completely gone/deleted
- All data unavailable
- System cannot start

### Recovery Steps (Assumes 24-hour backup)

**Step 1: Restore Database**
```bash
# Restore from daily backup
pg_restore -U diving_analyzer -d diving_analyzer_db \
  /backups/diving-analyser/backup_20260130_0200.sql

# Verify restore
psql -U diving_analyzer -d diving_analyzer_db -c "SELECT 1"
```

**Step 2: Verify Data Integrity**
```bash
# Run data integrity tests
python -m pytest backend/tests/test_data_integrity.py -v

# If tests fail, specific data recovery needed
```

**Step 3: Restart System**
```bash
# Start backend
sudo systemctl start diving-analyser-backend

# Start frontend
cd frontend && npm run preview &

# Verify connections
curl http://192.168.1.57:8000/api/v1/ws/health
```

**Step 4: Check Data Freshness**
```bash
# See what data is available
curl http://192.168.1.57:8000/api/v1/journey/journey

# If data is stale (>24 hours old), re-extract:
python src/batch_extract_metadata.py
```

## Rollback Procedures

### Rollback from Failed Deployment

**Version Check**:
```bash
# Check current version
curl http://192.168.1.57:8000/api/version

# See recent deployments
ls -lt /var/www/diving-analyser/releases/
```

**Rollback Steps**:
```bash
# 1. Stop current version
sudo systemctl stop diving-analyser-backend
cd /var/www/diving-analyser && npm run stop

# 2. Switch to previous version
cd /var/www/diving-analyser/releases
ln -sfn previous_version current

# 3. Start previous version
sudo systemctl start diving-analyser-backend
cd /var/www/diving-analyser && npm run start

# 4. Verify health
curl http://192.168.1.57:8000/api/v1/ws/health
```

### Rollback Database Schema

```bash
# List available schema backups
ls -lah /backups/diving-analyser/schemas/

# Restore previous schema
psql -U diving_analyzer -d diving_analyzer_db -f \
  /backups/diving-analyser/schemas/schema_20260130.sql

# Re-apply migrations up to safe point
alembic downgrade -1  # Roll back one migration
```

## Prevention Best Practices

### 1. Automated Backups
```bash
# Daily 02:00 UTC backup
# Location: /backups/diving-analyser/
# Retention: 30 days
# Backup script: /scripts/backup.sh

# Verify backup automation
crontab -l | grep backup
```

### 2. Health Monitoring
```bash
# Health check runs every 30 seconds
# Alerts on failure (email + Slack)
# Script: /scripts/health_check.sh

# Manual health check
curl http://192.168.1.57:8000/api/v1/ws/health
```

### 3. Data Validation
```bash
# Weekly integrity tests
# Run: Sunday 03:00 UTC
# Script: /scripts/verify_integrity.sh

# Manual run
python -m pytest backend/tests/test_data_integrity.py -v
```

### 4. Connection Resilience
```bash
# Auto-reconnect on WebSocket loss (5s interval)
# Sync resume on failure (exponential backoff)
# Queue persistence (survives browser restart)

# Test resilience
python backend/tests/test_load_concurrent.py -v
```

## Escalation Procedure

### If Recovery Fails

**Level 1: Engineering Team**
- Attempt automated recovery
- Check logs and error messages
- 15 minute response time

**Level 2: Database Administrator**
- Manual database inspection
- Advanced recovery procedures
- 30 minute response time

**Level 3: Data Center Team**
- Hardware issues
- Machine restart/recovery
- 60 minute response time

### Contact Information
```
On-Call: Maxime Cauchy <mcauchy@diving.local>
Backup: Engineering Team
Escalation: CTO <cto@diving.local>
```

## Testing Recovery Procedures

```bash
# Test disaster recovery quarterly
bash /scripts/test_recovery_procedures.sh

# This runs through:
# - Connection loss simulation
# - Sync failure recovery
# - Database backup/restore
# - Complete system restart

# Results: /var/log/recovery_tests/
```

## Documentation Updates

- [ ] Review quarterly
- [ ] Update contact info as needed
- [ ] Test procedures before deployment
- [ ] Log all actual recovery events
- [ ] Measure and report RTO/RPO metrics

## Summary

| Scenario | Automation | RTO | RPO |
|----------|-----------|-----|-----|
| WebSocket Loss | Full | 5-15s | 0s |
| Sync Failure | Full | 2-5m | 0s |
| DB Corruption | Partial | 15-30m | 1h |
| Backend Down | Partial | 5-10m | 1h |
| Frontend Crash | Full | <1s | 0s |
| Partial Data Loss | Manual | 30-60m | 1h |
| Complete Loss | Manual | 2-4h | 24h |

---

**Document Status**: APPROVED
**Last Updated**: Jan 31, 2026
**Next Review**: Apr 31, 2026
