# Troubleshooting Guide - Diving Analyser Stack

## Issue: Blank Page at Frontend URL

### Symptoms
- ✗ Blank white page when visiting `http://192.168.1.57:3000`
- ✗ No HTML content rendered
- ✗ 404 errors on inspect/dev tools

### Root Cause Detection Steps

**Step 1: Check if HTML file exists**
```bash
ssh mcauchy@192.168.1.57 "ls -lh /var/www/diving-analyser/dist/index.html"
```
- ✅ File exists → Move to Step 2
- ✗ File missing → Run frontend build

**Step 2: Check if file has content**
```bash
ssh mcauchy@192.168.1.57 "head -10 /var/www/diving-analyser/dist/index.html"
```
- ✅ Shows `<!DOCTYPE html>` → Move to Step 3
- ✗ Empty or corrupted → Rebuild frontend

**Step 3: Check server logs**
```bash
ssh mcauchy@192.168.1.57 "cat /var/www/diving-analyser/dist/server.log"
```
- ✅ No errors → Move to Step 4
- ✗ "Address already in use" → Port conflict (see below)
- ✗ Permission denied → Check file permissions

**Step 4: Check what's listening on port 3000**
```bash
ssh mcauchy@192.168.1.57 "lsof -i :3000"
```
- ✅ Python http.server → Server is running
- ✗ Different process → Kill and restart
- ✗ Nothing → Server not started

### Common Issues & Fixes

#### Issue: Port 3000 Already in Use
**Cause**: Old process (npm http-server) still running
```bash
# Kill all processes on port 3000
ssh mcauchy@192.168.1.57 "sudo killall -9 node npm http-server"

# Restart server
ssh mcauchy@192.168.1.57 "cd /var/www/diving-analyser/dist && nohup python3 -m http.server 3000 > server.log 2>&1 &"
```

#### Issue: HTML File Missing or Corrupted
**Cause**: Frontend build failed
```bash
# Check React build
ssh mcauchy@192.168.1.57 "cd /var/www/diving-analyser/current/frontend && npm run build"

# Or use minimal HTML
ssh mcauchy@192.168.1.57 "cp /var/www/diving-analyser/dist/index.html /tmp/backup.html"
```

#### Issue: Server Running but 404 on Files
**Cause**: Server in wrong directory
```bash
# Verify server is in correct directory
ssh mcauchy@192.168.1.57 "ps aux | grep http.server"

# Restart in correct directory
ssh mcauchy@192.168.1.57 "cd /var/www/diving-analyser/dist && nohup python3 -m http.server 3000 &"
```

### Quick Diagnostic Commands

```bash
# Test 1: File exists and has content
curl -s http://192.168.1.57:3000/ | wc -l
# Expected: >100 lines

# Test 2: Page loads in browser
curl -I http://192.168.1.57:3000/
# Expected: HTTP/1.1 200 OK

# Test 3: Backend is reachable from frontend
curl -s http://192.168.1.57:8002/health | jq .
# Expected: {"status":"healthy",...}

# Test 4: Check console errors
# Open browser → F12 → Console tab
# Look for red error messages
```

### Prevention Tips

1. **Always check file exists before testing**
   ```bash
   ls /var/www/diving-analyser/dist/index.html
   ```

2. **Verify server is running**
   ```bash
   curl -I http://192.168.1.57:3000/
   ```

3. **Check server logs on any issue**
   ```bash
   tail -50 /var/www/diving-analyser/dist/server.log
   ```

4. **Keep ports available**
   ```bash
   # Check all listening ports
   netstat -tuln | grep LISTEN
   ```

5. **Test early and often**
   - After code deployment
   - After server restart
   - Before debugging browser issues

### Advanced Debugging

**View HTTP server requests in real-time**
```bash
ssh mcauchy@192.168.1.57 "cd /var/www/diving-analyser/dist && python3 -m http.server 3000"
# Don't use nohup - see requests directly
```

**Check browser network tab**
1. Open `http://192.168.1.57:3000`
2. Press F12 → Network tab
3. Reload page
4. Look for failed requests (red 404s)
5. Check API calls are hitting backend on port 8002

**Verify API connectivity from frontend**
- Open browser console (F12)
- Frontend dashboard shows API test results
- Click "Test Connection" button
- Should see successful health check

---

## Full Stack Health Check

```bash
#!/bin/bash
# Quick health check for entire stack

echo "1. Backend API:"
curl -s http://192.168.1.57:8002/health | jq . && echo "✅ Backend OK" || echo "✗ Backend DOWN"

echo ""
echo "2. Frontend Server:"
curl -I http://192.168.1.57:3000/ 2>&1 | grep "200\|404" && echo "✅ Frontend OK" || echo "✗ Frontend DOWN"

echo ""
echo "3. Database:"
ssh mcauchy@192.168.1.57 "psql -U diving -d diving_analyzer_db -c 'SELECT 1;' 2>&1" && echo "✅ Database OK" || echo "✗ Database DOWN"

echo ""
echo "4. Services:"
ssh mcauchy@192.168.1.57 "ps aux | grep -c 'uvicorn\|http.server' | grep -E '2|3'" && echo "✅ Services OK" || echo "⚠ Check services"
```

---

**Key Takeaway**: Always test early with curl before assuming frontend issues are code problems. Most "blank page" issues are file serving or port conflicts, not HTML/JS problems.
