# System Architecture

**Diving Analytics Platform** - Split Architecture Design Document

---

## Table of Contents

- [Overview](#overview)
- [Architecture Patterns](#architecture-patterns)
- [System Components](#system-components)
- [Data Flow](#data-flow)
- [Database Schema](#database-schema)
- [API Design](#api-design)
- [Real-Time Communication](#real-time-communication)
- [Security Model](#security-model)
- [Scalability & Performance](#scalability--performance)
- [Design Decisions](#design-decisions)

---

## Overview

The Diving Analytics Platform uses a **split architecture** that separates data collection from analytics and serving:

- **Mac Agent** - Runs locally on development machine, monitors Photos library, syncs to server
- **Server** - Runs in Docker on production server, stores data, performs analytics, serves web UI

This separation is necessary because:
1. macOS Photos library requires local access (security sandbox)
2. Web dashboard needs 24/7 availability
3. Analytics computations benefit from server resources
4. Multiple data sources can sync to central server in future

---

## Architecture Patterns

### 1. Split Data Collection + Centralized Analytics

```
┌────────────────────────────────────────────────────────────────┐
│                         Mac Agent                               │
│                      (Data Collection)                          │
├────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐      ┌─────────────────┐                    │
│  │   Photos     │      │  FSEvents       │                    │
│  │   Library    │─────▶│  Watcher        │                    │
│  │              │      │  (Real-time)    │                    │
│  └──────────────┘      └─────────────────┘                    │
│                                │                                │
│                                ▼                                │
│                        ┌─────────────────┐                     │
│                        │ Caption Parser  │                     │
│                        │ • Legacy format │                     │
│                        │ • Two-phase fmt │                     │
│                        └─────────────────┘                     │
│                                │                                │
│                                ▼                                │
│                        ┌─────────────────┐                     │
│                        │  Sync Client    │                     │
│                        │  • WebSocket    │                     │
│                        │  • Retry logic  │                     │
│                        │  • Offline queue│                     │
│                        └─────────────────┘                     │
└────────────────────────────────────────────────────────────────┘
                                │
                                │ HTTPS WebSocket
                                │ (Metadata JSON)
                                ▼
┌────────────────────────────────────────────────────────────────┐
│                         Server                                  │
│                   (Analytics + Serving)                         │
├────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │                    FastAPI Backend                       │ │
│  │                                                          │ │
│  │  ┌────────────────┐    ┌────────────────┐              │ │
│  │  │  REST API      │    │  WebSocket     │              │ │
│  │  │  • Dives       │    │  • Sync status │              │ │
│  │  │  • Sessions    │    │  • Milestones  │              │ │
│  │  │  • Analytics   │    │  • Real-time   │              │ │
│  │  │  • Journey     │    └────────────────┘              │ │
│  │  └────────────────┘                                     │ │
│  │                                                          │ │
│  │  ┌────────────────────────────────────────────┐         │ │
│  │  │           Business Logic Layer             │         │ │
│  │  │                                            │         │ │
│  │  │  • MilestoneDetector (17 types)           │         │ │
│  │  │  • PhaseValidator (coaching rules)        │         │ │
│  │  │  • JourneyService (narrative generation)  │         │ │
│  │  │  • AnalyticsService (metrics computation) │         │ │
│  │  │  • SyncService (batch operations)         │         │ │
│  │  └────────────────────────────────────────────┘         │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                │                                │
│                                ▼                                │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │                   PostgreSQL Database                    │ │
│  │                                                          │ │
│  │  Tables:                                                 │ │
│  │  • sessions (training days)                             │ │
│  │  • dives (1700+ attempts with phase scores)             │ │
│  │  • dive_codes_metadata (reference data)                 │ │
│  │  • analytics_cache (pre-computed metrics)               │ │
│  │  • agent_keys (authentication)                          │ │
│  └──────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────┘
                                │
                                │ HTTP/WS
                                ▼
┌────────────────────────────────────────────────────────────────┐
│                      React Frontend                             │
│                    (User Interface)                             │
├────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Pages:                                                         │
│  • Journey (progress narrative + phase analysis)               │
│  • Dashboard (real-time stats)                                 │
│  • Dives (searchable list)                                     │
│  • Sessions (training day summary)                             │
│                                                                 │
│  Components:                                                    │
│  • SyncStatus (live updates via WebSocket)                     │
│  • Charts (8 visualization types)                              │
│  • MilestoneTimeline (17 milestone types)                      │
│                                                                 │
└────────────────────────────────────────────────────────────────┘
```

---

## System Components

### Mac Agent

**Purpose:** Monitor Photos library and sync dive metadata to server

**Technologies:**
- Python 3.12
- osxphotos (Photos library access)
- FSEvents / fswatch (file monitoring)
- WebSocket client (real-time sync)
- LaunchAgent (background service)

**Key Classes:**
```python
class PhotosWatcher:
    """Monitors Photos library for new videos"""
    def watch() -> Iterator[Video]
    def parse_caption(caption: str) -> DiveMetadata

class SyncClient:
    """Syncs dive metadata to server"""
    def sync_dive(metadata: DiveMetadata) -> Response
    def batch_sync(dives: List[DiveMetadata]) -> Response
    def retry_with_backoff() -> None

class OfflineQueue:
    """Stores dives when server unavailable"""
    def enqueue(dive: DiveMetadata) -> None
    def flush() -> List[Response]
```

**Configuration:**
```yaml
server:
  url: "https://192.168.1.57:6090"
  api_key: "your-api-key"

photos:
  library_path: "/Users/you/Pictures/Photos Library.photoslibrary"
  poll_interval: 300  # seconds

sync:
  batch_size: 50
  retry_attempts: 3
  backoff_factor: 2.0
```

### Backend (FastAPI)

**Purpose:** Store data, perform analytics, serve web UI

**Technologies:**
- FastAPI 0.104+ (async web framework)
- SQLAlchemy 2.0 (ORM)
- Alembic (migrations)
- Pydantic (validation)
- pytest (testing)

**Layered Architecture:**

**1. API Layer** (`app/api/v1/`)
- REST endpoints
- WebSocket handlers
- Request validation
- Response serialization

**2. Service Layer** (`app/services/`)
- Business logic
- Analytics computation
- Milestone detection
- Journey narrative generation

**3. Data Layer** (`app/models/`, `app/schemas/`)
- SQLAlchemy models (database)
- Pydantic schemas (API contracts)
- Database queries

**Key Services:**

```python
class MilestoneDetector:
    """Detects 17 types of milestones from dive history"""
    MILESTONE_TYPES = [
        'breakthrough', 'redemption', 'streak', 'avoided_dive',
        'height_first', 'perfect_dive', 'recovery', 'consistency',
        # ... 9 more types
    ]

    def detect_milestones(dives: List[Dive]) -> List[Milestone]
    def _generate_phase_insight(dive: Dive) -> Optional[str]

class JourneyService:
    """Generates narrative-driven progress story"""
    def get_journey_data() -> JourneyData
    def get_phase_analysis() -> PhaseAnalysis
    def get_milestones() -> List[Milestone]

class AnalyticsService:
    """Computes performance metrics"""
    def calculate_overall_stats() -> OverallStats
    def calculate_by_height() -> Dict[str, HeightStats]
    def calculate_monthly_progression() -> List[MonthlyStats]
```

### Frontend (React + TypeScript)

**Purpose:** Interactive web dashboard for viewing analytics

**Technologies:**
- React 18.2 (UI library)
- TypeScript 5.2 (type safety)
- Vite (build tool)
- React Router (routing)
- Recharts (visualizations)
- Zustand (state management)
- Tailwind CSS (styling)

**Page Structure:**

```typescript
/                    → Dashboard
  /dives            → Dive browser (searchable, filterable)
  /sessions         → Session summary (training days)
  /journey          → Progress narrative
    /story          → Overall narrative
    /milestones     → Timeline view
    /phase-analysis → Two-phase coaching
    /patterns       → Avoided dives
```

**State Management:**

```typescript
// Zustand store
interface AppState {
  dives: Dive[]
  sessions: Session[]
  milestones: Milestone[]
  syncStatus: SyncStatus

  fetchDives: () => Promise<void>
  fetchSessions: () => Promise<void>
  connectWebSocket: () => void
}
```

### Database (PostgreSQL 16)

**Purpose:** Persistent storage for dive data and analytics

**Key Tables:**

```sql
-- Training sessions (one per day)
CREATE TABLE sessions (
    id SERIAL PRIMARY KEY,
    date DATE UNIQUE NOT NULL,
    dive_count INTEGER,
    avg_performance FLOAT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Individual dive attempts
CREATE TABLE dives (
    id SERIAL PRIMARY KEY,
    session_id INTEGER REFERENCES sessions(id),
    dive_code VARCHAR(10) NOT NULL,

    -- Legacy single score
    performance CHAR(1) NOT NULL,  -- F/B/M/G/P
    performance_numeric INTEGER NOT NULL,  -- 0-4

    -- Two-phase scoring (optional)
    phase1_performance CHAR(1),  -- Takeoff: Hurdle + Flight
    phase1_numeric INTEGER,
    phase2_performance CHAR(1),  -- Landing: Opening + Entry
    phase2_numeric INTEGER,

    -- Metadata
    height VARCHAR(10),  -- 1m, 3m, 5m, 7m, 10m
    is_sync BOOLEAN DEFAULT FALSE,
    is_smack BOOLEAN DEFAULT FALSE,
    video_uuid VARCHAR(255) UNIQUE,

    -- Timestamps
    dive_date TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),

    -- Indexes
    INDEX idx_dive_code (dive_code),
    INDEX idx_performance (performance_numeric),
    INDEX idx_phase1 (phase1_numeric),
    INDEX idx_phase2 (phase2_numeric),
    INDEX idx_dive_date (dive_date)
);

-- Dive code reference data
CREATE TABLE dive_codes_metadata (
    code VARCHAR(10) PRIMARY KEY,
    description TEXT,
    difficulty FLOAT,
    group_number INTEGER,  -- 1-6 (forward, back, reverse, inward, twisting, armstand)
    position CHAR(1)  -- A/B/C/D
);

-- Mac agent API keys
CREATE TABLE agent_keys (
    id SERIAL PRIMARY KEY,
    key_hash VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(100),
    last_used TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

## Data Flow

### 1. Data Collection Flow (Mac → Server)

```
Photos Library
    ↓
[FSEvents detects new video]
    ↓
[Caption Parser extracts metadata]
    {
      dive_code: "101B",
      phase1_performance: "G",  // Good takeoff
      phase2_performance: "P",  // Perfect landing
      height: "5m",
      date: "2026-02-01T14:30:00Z"
    }
    ↓
[Sync Client validates & sends]
    ↓
POST /api/v1/videos/sync
    ↓
[Backend validates phase combination]
    ↓
[Database stores dive]
    ↓
[Milestone detection triggered]
    ↓
[WebSocket broadcasts update to frontend]
    ↓
Frontend shows notification: "New dive added! 🎉"
```

### 2. Analytics Flow (Backend)

```
User requests /api/v1/analytics
    ↓
[AnalyticsService checks cache]
    ↓
[If stale, regenerates from dives table]
    ↓
[Computes metrics:]
    • Overall performance (avg, success rate, consistency)
    • By height (1m, 3m, 5m, 7m, 10m)
    • By dive code (101B, 201C, etc.)
    • Monthly progression (time series)
    • Platform vs springboard comparison
    ↓
[Stores in analytics_cache table]
    ↓
[Returns JSON to frontend]
    ↓
Frontend renders charts
```

### 3. Journey Flow (Milestone Detection)

```
Batch sync completes
    ↓
[JourneyService triggered]
    ↓
[MilestoneDetector scans all dives]
    ↓
[Detects 17 types of milestones:]
    • Breakthrough (success after 3+ failures)
    • Redemption (perfect after smack)
    • Streak (10+ consecutive successes)
    • Avoided dive (facing fear)
    • Height milestone (first attempt at new height)
    • Perfect dive
    • Recovery (good after multiple bad)
    • Consistency (low std dev over 20+ attempts)
    • ... 9 more types
    ↓
[For each milestone with phase data:]
    ↓
[PhaseInsightGenerator analyzes combination:]
    • P/P → "Perfect execution: Both phases flawless"
    • P/M → "Flight is perfect; focus on entry control"
    • G/P → "Resilient execution: Good flight, excellent recovery"
    • M/P → "Remarkable recovery: Despite weak flight, excellent entry"
    ↓
[Stores milestone + coaching in database]
    ↓
[Returns to frontend via /api/v1/journey/milestones]
    ↓
Frontend displays timeline with coaching insights
```

---

## Database Schema

### Entity Relationship Diagram

```
┌─────────────┐         ┌─────────────────┐
│  sessions   │         │  dive_codes_    │
│             │         │  metadata       │
│ id          │         │                 │
│ date        │         │ code (PK)       │
│ dive_count  │         │ description     │
│ avg_perf    │         │ difficulty      │
└─────────────┘         │ group_number    │
       │                │ position        │
       │                └─────────────────┘
       │                         │
       │ 1:N                     │ 1:N
       │                         │
       ▼                         ▼
┌─────────────────────────────────────────┐
│              dives                      │
│                                         │
│ id (PK)                                 │
│ session_id (FK → sessions.id)          │
│ dive_code (FK → dive_codes_metadata)   │
│                                         │
│ -- Legacy scoring --                   │
│ performance (F/B/M/G/P)                │
│ performance_numeric (0-4)              │
│                                         │
│ -- Two-phase scoring --                │
│ phase1_performance (Takeoff)           │
│ phase1_numeric                         │
│ phase2_performance (Landing)           │
│ phase2_numeric                         │
│                                         │
│ -- Metadata --                         │
│ height (1m, 3m, 5m, 7m, 10m)           │
│ is_sync (boolean)                      │
│ is_smack (boolean)                     │
│ video_uuid (unique)                    │
│ dive_date                              │
└─────────────────────────────────────────┘
```

### Indexing Strategy

**Performance-Critical Queries:**

1. **Recent dives:** `SELECT * FROM dives ORDER BY dive_date DESC LIMIT 100`
   - Index: `idx_dive_date` (BTREE on dive_date DESC)

2. **Dive code filtering:** `SELECT * FROM dives WHERE dive_code = '101B'`
   - Index: `idx_dive_code` (HASH on dive_code)

3. **Performance filtering:** `SELECT * FROM dives WHERE performance_numeric >= 2`
   - Index: `idx_performance` (BTREE on performance_numeric)

4. **Phase analysis:** `SELECT * FROM dives WHERE phase1_numeric IS NOT NULL`
   - Index: `idx_phase1`, `idx_phase2` (BTREE with NULL filtering)

---

## API Design

### REST Endpoints

**Base URL:** `/api/v1`

#### Dives

```http
GET /dives
GET /dives/{id}
POST /dives  (internal - used by sync client)
GET /dives/recent?limit=100
GET /dives/by-code/{dive_code}
```

#### Sessions

```http
GET /sessions
GET /sessions/{id}
GET /sessions/recent?limit=30
```

#### Analytics

```http
GET /analytics/overall
GET /analytics/by-height
GET /analytics/by-code
GET /analytics/monthly
GET /analytics/platform-vs-springboard
```

#### Journey

```http
GET /journey/journey  (overall narrative)
GET /journey/milestones
GET /journey/phase-analysis
GET /journey/breakthroughs
GET /journey/avoided-dives
```

#### Video Sync (Mac Agent)

```http
POST /videos/sync  (single dive)
POST /videos/batch  (bulk sync)
```

### Request/Response Examples

**POST /api/v1/videos/sync**

Request:
```json
{
  "dive_code": "101B",
  "phase1_performance": "G",
  "phase2_performance": "P",
  "height": "5m",
  "video_uuid": "ABC123-DEF456",
  "dive_date": "2026-02-01T14:30:00Z",
  "is_sync": false,
  "is_smack": false
}
```

Response:
```json
{
  "status": "success",
  "dive_id": 1722,
  "milestones_detected": [
    {
      "type": "perfect_dive",
      "message": "First perfect 101B at 5m!",
      "phase_insight": "Resilient execution: Good flight but excellent recovery."
    }
  ]
}
```

---

## Real-Time Communication

### WebSocket Protocol

**Endpoint:** `ws://server:6090/api/v1/ws`

**Message Types:**

1. **Sync Status**
```json
{
  "type": "sync_status",
  "data": {
    "last_sync": "2026-02-01T14:30:00Z",
    "pending_count": 0,
    "syncing": false
  }
}
```

2. **New Dive**
```json
{
  "type": "new_dive",
  "data": {
    "dive_id": 1722,
    "dive_code": "101B",
    "performance": "P"
  }
}
```

3. **New Milestone**
```json
{
  "type": "new_milestone",
  "data": {
    "type": "breakthrough",
    "message": "First success after 5 failures on 201C!",
    "phase_insight": "Medium takeoff, Perfect landing - focus on hurdle."
  }
}
```

---

## Security Model

### Authentication

**Mac Agent → Server:**
- API key in header: `X-API-Key: your-key`
- HTTPS only (TLS 1.3)
- Key stored in `agent_keys` table (bcrypt hashed)

**Frontend → Server:**
- No authentication (internal network)
- Optional: JWT tokens for multi-user support (future)

### Authorization

- Mac agent can only write to `/videos/*` endpoints
- Frontend can read all endpoints
- Admin endpoints (future) require separate credentials

---

## Scalability & Performance

### Current Performance

- **Caption parsing:** <1s per dive
- **Milestone detection:** ~5s for 1700 dives
- **WebSocket latency:** <100ms
- **Analytics regeneration:** ~30s for full dataset
- **Database queries:** <50ms (with indexes)

### Optimization Strategies

1. **Analytics caching** - Pre-compute metrics, invalidate on new data
2. **Database indexing** - Covered queries for common patterns
3. **WebSocket batching** - Group updates to reduce messages
4. **Lazy loading** - Frontend paginates large lists
5. **Docker resource limits** - Prevent OOM on small servers

### Scaling Roadmap

- **Horizontal:** Multiple Mac agents → single server
- **Vertical:** Larger server for more users
- **Caching:** Redis for session data
- **CDN:** Static assets (charts, images)

---

## Design Decisions

### 1. Why Split Architecture?

**Decision:** Separate Mac agent from server

**Rationale:**
- macOS Photos library requires local access (sandbox security)
- Server needs 24/7 uptime for web dashboard
- Future: Multiple athletes can sync to central server

**Trade-offs:**
- More complex deployment (2 components)
- Network dependency (Mac → Server)
- Offline queue needed for reliability

### 2. Why Two-Phase Scoring?

**Decision:** Support both legacy (single) and two-phase (takeoff + landing) formats

**Rationale:**
- Granular coaching insights (e.g., "your flight is good but work on entry")
- Backwards compatible with 1606 existing legacy dives
- Aligns with actual dive judging methodology

**Implementation:**
- Optional fields in database (`phase1_performance`, `phase2_performance`)
- Caption parser detects format: `101B P` vs `101B G/P`
- Analytics use composite score (MIN of phase1, phase2) for historical consistency

### 3. Why 17 Milestone Types?

**Decision:** Comprehensive milestone detection beyond simple "best score"

**Rationale:**
- Narrative engagement (progress story is motivating)
- Pattern recognition (avoid dives, streaks, recovery)
- Coaching value (phase insights on key moments)

**Examples:**
- **Breakthrough:** Success after 3+ failures
- **Redemption:** Perfect after smack
- **Avoided Dive:** Attempting a feared dive code
- **Streak:** 10+ consecutive successes

### 4. Why WebSocket for Sync?

**Decision:** Use WebSocket instead of polling

**Rationale:**
- Real-time updates (new dives appear immediately)
- Low latency (<100ms)
- Efficient (no repeated HTTP overhead)

**Implementation:**
- Server broadcasts to all connected clients
- Reconnect logic with exponential backoff
- Fallback to HTTP polling if WebSocket fails

### 5. Why PostgreSQL over SQLite?

**Decision:** Use PostgreSQL for production

**Rationale:**
- Better concurrency (multiple clients)
- Full-text search capabilities
- Advanced indexing (BTREE, HASH, GIN)
- Production-ready (ACID compliance)

**Trade-offs:**
- More complex setup (Docker container)
- Larger memory footprint
- Requires separate backup strategy

---

## Conclusion

The split architecture provides:

- **Separation of concerns** (data collection vs analytics)
- **Scalability** (add more Mac agents in future)
- **Reliability** (offline queue, retry logic)
- **Performance** (server resources for analytics)
- **Real-time updates** (WebSocket for live sync)

See [DEPLOYMENT.md](DEPLOYMENT.md) for production setup and [DEVELOPMENT.md](DEVELOPMENT.md) for local development workflow.
