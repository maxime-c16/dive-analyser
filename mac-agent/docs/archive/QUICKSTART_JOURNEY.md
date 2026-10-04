# Journey Feature - Quick Start Guide

## 🚀 Start the Full Stack (30 seconds)

```bash
# Navigate to project directory
cd /Users/mcauchy/diving-analyser

# Start all services (Docker required)
docker-compose up -d

# Wait for services to initialize
sleep 15

# Verify all services are healthy
docker-compose ps
```

**Expected output:**
```
NAME                         STATUS          PORTS
diving-analyser-postgres     Up (healthy)    5433:5432
diving-analyser-backend      Up (healthy)    8000:8000
diving-analyser-frontend     Up             3001:3000
diving-analyser-nginx        Up              80:80, 443:443
```

## 🌐 View in Browser

### Option 1: Development Frontend (Hot-reload)
```
http://localhost:3001
```
- Click "Journey" in navigation
- See three tabs: "Your Story" | "Milestones" | "Patterns"

### Option 2: Production Stack (Nginx reverse proxy)
```
http://localhost
```
- Same Journey UI through nginx
- Also provides: /api, /adminer for database UI

### Option 3: Mobile/Remote Testing
```
http://192.168.1.57:3001     # Dev frontend on network
http://192.168.1.57:8000     # Direct API access
```

## 🧪 Test the API

### Quick Test (all endpoints)
```bash
python backend/test_api_integration.py
```

**Expected output:**
```
✓ Journey Summary
✓ Milestones List
✓ Dive Story
✓ Breakthroughs
✓ Avoided Dives
✓ Filtering

Total: 6/6 tests passed ✓
```

### Individual Endpoint Tests

**1. Your Journey Summary**
```bash
curl http://localhost:8000/api/v1/journey/journey | python -m json.tool
```

Shows:
- Total dives: 1,328
- Unique dives: 75
- Training days: 440
- Growth improvement: +1.24 (from 1.26 → 2.51 avg)
- Trajectory: "improving"
- Most significant milestone
- Complete narrative

**2. Timeline of Milestones**
```bash
# All milestones (50 at a time, most recent first)
curl http://localhost:8000/api/v1/journey/milestones | python -m json.tool

# Filter: only significance 5 (transformational moments)
curl "http://localhost:8000/api/v1/journey/milestones?min_significance=5" | python -m json.tool

# Filter: only significance 4+ (major moments)
curl "http://localhost:8000/api/v1/journey/milestones?min_significance=4&limit=10" | python -m json.tool
```

Shows:
- 50 milestones by default (paginated)
- Each has: type, dive_code, height, date, significance (1-5)
- Narrative for each milestone
- Sorted by recency

**3. Your Breakthroughs**
```bash
curl http://localhost:8000/api/v1/journey/breakthroughs | python -m json.tool
```

Shows:
- Only significance 5 milestones (transformational)
- Types: BREAKTHROUGH, REDEMPTION, PLATEAU_BROKEN, AVOIDED_DIVE_ATTEMPTED
- Why each one matters
- Most meaningful dives

**4. Dives You Might Be Avoiding**
```bash
curl http://localhost:8000/api/v1/journey/avoided | python -m json.tool
```

Shows:
- Dives not attempted in 30+ days
- Avoidance score (days × difficulty)
- Failure rate (75%+ is hard, 50-70% is mixed, <50% is achievable)
- Encouraging coaching for returning

**5. Story of a Specific Dive**
```bash
# Get complete story of 201C from 1M height
curl "http://localhost:8000/api/v1/journey/dive/201C/1M" | python -m json.tool
```

Shows:
- Opening narrative ("Your 201C journey from 1M began on...")
- Chapter-by-chapter breakdown of all attempts
- Each chapter: date, performance result, narrative
- Stats: total attempts, success rate, current streak
- Closing statement

## 📊 Real Data Insights

Your actual database has:
- **1,328 total dives**
- **75 unique dive types**
- **440 days of training** (since Oct 30, 2024)
- **535 milestones detected**
- **103 breakthroughs** (success after failure)
- **63 avoided dives** (not attempted in 30+ days)
- **77% success rate** (similar to analytics)

## 🎯 Three Ways to Explore

### 1. **Web UI Path** (Most user-friendly)
```
localhost:3001 → Click "Journey" → Click tabs → Click milestones to expand
```

**What you'll see:**
- Colorful timeline with significance-based visual hierarchy
- Expandable cards showing full narratives
- Three sorting/filter tabs
- Stats at the top

### 2. **REST API Path** (Programmatic)
```bash
# Get everything you need for a dashboard
curl http://localhost:8000/api/v1/journey/journey
curl http://localhost:8000/api/v1/journey/milestones?min_significance=4
curl http://localhost:8000/api/v1/journey/breakthroughs
curl http://localhost:8000/api/v1/journey/avoided
```

**Good for:**
- Building custom visualizations
- Integrating with other systems
- Scripting/automation

### 3. **Database Admin Path** (Raw data)
```
localhost:8080   # Adminer (database UI)
```

Login:
- Server: `postgres`
- Username: `diver`
- Password: `diving_secure_2024`
- Database: `diving_analytics`

Query:
```sql
SELECT type, dive_code, height, COUNT(*) as count
FROM milestones
GROUP BY type, dive_code, height
ORDER BY count DESC;
```

## 🔍 Testing Different User Interactions

### Interaction 1: User views journey summary
```bash
curl -s http://localhost:8000/api/v1/journey/journey | python -m json.tool | head -40
```

**Check for:**
- ✓ Overview section (total_dives, days_of_training)
- ✓ Growth section (improvement, trajectory)
- ✓ Journey section (milestones summary)

### Interaction 2: User clicks "Milestones" tab
```bash
curl -s http://localhost:8000/api/v1/journey/milestones?limit=5 | python -m json.tool
```

**Check for:**
- ✓ total count
- ✓ Array of milestones with required fields
- ✓ Sorted by date (most recent first)
- ✓ Significance distribution

### Interaction 3: User adjusts significance filter
```bash
# Test each filter level
for sig in 1 2 3 4 5; do
  echo "=== Significance $sig+ ==="
  curl -s "http://localhost:8000/api/v1/journey/milestones?min_significance=$sig&limit=1" | \
    python -c "import json, sys; data = json.load(sys.stdin); print(f'Count: {data[\"total\"]}')"
done
```

**Expected:**
- Significance 1: All milestones (hundreds)
- Significance 2: Most milestones (hundreds)
- Significance 3: Major milestones (dozens)
- Significance 4: Very significant (tens)
- Significance 5: Transformational (10-15)

### Interaction 4: User clicks on a milestone
```bash
# Get first milestone
MILESTONE=$(curl -s http://localhost:8000/api/v1/journey/milestones?limit=1 | \
  python -c "import json, sys; m = json.load(sys.stdin)['milestones'][0]; print(f\"{m['dive_code']},{m['height']}\")")

# Get its story
IFS=',' read -r CODE HEIGHT <<< "$MILESTONE"
curl -s "http://localhost:8000/api/v1/journey/dive/$CODE/$HEIGHT" | python -m json.tool
```

**Check for:**
- ✓ Opening statement
- ✓ Chapters with dates and narratives
- ✓ Stats section
- ✓ current_streak value

### Interaction 5: User views patterns (avoided dives)
```bash
curl -s http://localhost:8000/api/v1/journey/avoided | python -m json.tool | head -60
```

**Check for:**
- ✓ total_avoided count
- ✓ Array of avoided dives
- ✓ Each has: dive_code, days_since_attempt, failure_rate, message
- ✓ Encouraging message at bottom

## 📝 Real Responses (Examples)

### Example: Journey Summary Response
```json
{
  "overview": {
    "total_dives": 1328,
    "unique_dive_combinations": 75,
    "days_of_training": 440,
    "first_dive_date": "2024-10-30T15:27:41",
    "latest_dive_date": "2026-01-13T19:46:34"
  },
  "growth": {
    "first_month_average": 1.26,
    "last_month_average": 2.51,
    "improvement": 1.24,
    "trajectory": "improving"
  },
  "journey": {
    "total_milestones": 535,
    "breakthroughs": 103,
    "most_significant": {
      "type": "breakthrough",
      "dive_code": "201C",
      "height": "1M",
      "title": "Breakthrough on 201C",
      "narrative": "You landed 201C after 5 consecutive failed attempts...",
      "significance": 5
    }
  }
}
```

### Example: Milestone Response
```json
{
  "total": 50,
  "milestones": [
    {
      "type": "comeback",
      "dive_code": "101C",
      "height": "5M",
      "title": "Comeback: 101C",
      "narrative": "You returned to 101C from 5M after 45 days away...",
      "date": "2026-01-13T19:46:34",
      "significance": 3
    }
  ]
}
```

### Example: Avoided Dive Response
```json
{
  "total_avoided": 63,
  "avoided": [
    {
      "dive_code": "301B",
      "height": "3M",
      "days_since_attempt": 342,
      "total_attempts": 8,
      "failure_rate": 100.0,
      "avoidance_score": 514.0,
      "message": "You haven't attempted 301B in 342 days. Historical difficulty: 100%. Maybe start with some lineups to rebuild confidence."
    }
  ]
}
```

## 🚨 Troubleshooting

### "Connection refused" on localhost:8000
```bash
# Check if backend is running
docker-compose ps | grep backend

# If not healthy, restart
docker-compose restart backend

# Check logs
docker-compose logs backend | tail -50
```

### "No milestones found" or empty data
- This means there's no dive data in your database yet
- Journey is still working - it returns graceful messages
- Data comes from `Dive` table in PostgreSQL
- Should see 1,328 dives if database is properly initialized

### Frontend not loading at localhost:3001
```bash
# Check frontend status
docker-compose logs frontend | grep -i error

# Rebuild if needed
docker-compose build frontend
docker-compose up -d frontend
```

### Database connection issues
```bash
# Verify database is healthy
docker-compose logs postgres | grep "ready to accept"

# Access database directly
docker-compose exec postgres psql -U diver diving_analytics -c "SELECT COUNT(*) FROM dive;"
```

## 🎬 Live Browser Demo Workflow

1. **Open browser**: `http://localhost:3001`
2. **Click "Journey"** in navigation
3. **See "Your Story"** tab with narrative summary
4. **Click "Milestones"** tab
5. **Adjust slider** from "All" → "4+" → "5 only"
6. **Click expand icon** on any milestone card
7. **See full narrative** in expanded view
8. **Click on a milestone** to open dive story modal
9. **See chapter-by-chapter** breakdown
10. **Click "Patterns"** tab to see avoided dives
11. **Read coaching messages** about each avoided dive

## ✅ Validation Checklist

After starting the stack, verify:

- [ ] `docker-compose ps` shows all 5 containers healthy
- [ ] `http://localhost:3001` loads without errors
- [ ] "Journey" link appears in navigation
- [ ] Journey page has 3 tabs: "Your Story", "Milestones", "Patterns"
- [ ] "Your Story" shows stats and trajectory
- [ ] "Milestones" shows list of milestones
- [ ] Can filter by significance level
- [ ] Can click milestone to expand
- [ ] Can click milestone card to open story modal
- [ ] "Patterns" shows avoided dives with messages
- [ ] `python backend/test_api_integration.py` returns 6/6 tests passed

## 📚 Further Reading

- **JOURNEY_GUIDE.md** - Detailed feature documentation
- **TEST_RESULTS.md** - Comprehensive test results
- **CLAUDE.md** - Architecture and system overview
- **backend/test_api_integration.py** - API test examples
- **frontend/src/pages/Journey.tsx** - Frontend implementation

---

**You're ready to see your diving story. Start the stack and click Journey!**
