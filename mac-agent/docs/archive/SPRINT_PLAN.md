# DivingAnalyzer Split Architecture: Sprint & Task Breakdown

**Date Created**: January 31, 2026
**Project**: Mac Worker + Server split architecture for continuous dive sync with phase-aware coaching
**Status**: Planning → Ready for Implementation

---

## Executive Summary

**Reorganized Plan**:
- Original: 64 tasks across 8 serial sprints = 8 weeks minimum
- Improved: 53 tasks across 8 sprints with parallelization = 3-4 weeks with concurrent work streams
- Key improvements: Test infrastructure first, database migrations before endpoints, enable parallel work streams

**Critical Changes from Original Plan**:
1. ✅ Reordered Sprint 0 to put test infrastructure first
2. ✅ Moved database migrations to Sprint 4, Task 1
3. ✅ Split large tasks into atomic, independently committable pieces
4. ✅ Enabled parallel work streams (Mac worker, Server, Frontend)
5. ✅ Added missing tasks: config management, logging, error recovery, monitoring
6. ✅ Clarified acceptance criteria for each task
7. ✅ Distributed testing throughout sprints (not deferred to end)

---

## Sprint Overview (Recommended Execution)

```
STREAM 1: MAC WORKER                STREAM 2: SERVER              STREAM 3: FRONTEND
├─ Sprint 1: Photo parsing (5d)     ├─ Sprint 0: Foundation       ├─ Sprint 6: WebSocket UI
├─ Sprint 2: Sync client (5d)       ├─ Sprint 4: Endpoints (4d)   ├─ Sprint 7: UI Integration
├─ Sprint 3: LaunchAgent (3d)       ├─ Sprint 5: Journey (3d)     └─ Full E2E (Sprint 8)
                                     └─ Sprint 6: Monitoring

STREAM 4: INTEGRATION & DEPLOYMENT
└─ Sprint 8: E2E Testing + Deploy (3-5d)

PARALLEL EXECUTION = 3-4 weeks
SEQUENTIAL EXECUTION = 8 weeks
```

---

## Sprint 0: Foundation & Testing Infrastructure (5 days)

**Goal**: Establish testing framework, database schema, API contracts, and mocking infrastructure

**Demoable Artifact**: `pytest` runs 30+ passing tests, mock server responds to sync requests

### Task 0.1: Setup pytest fixtures and conftest
**Time**: 3-4 hours | **Commit**: `test: setup pytest infrastructure`

**Description**: Create reusable pytest fixtures and configuration for all tests

**Acceptance Criteria**:
- [ ] `backend/conftest.py` exists with fixtures:
  - `db_session` - clean test database per test
  - `api_client` - test FastAPI client
  - `sample_dive` - fixture with test dive record
  - `sample_session` - fixture with test session
- [ ] Run `pytest` shows 5+ passing tests
- [ ] All fixtures are independent (no shared state between tests)
- [ ] Test database uses SQLite in-memory (fast)
- [ ] Migrations run automatically on test database setup

**Testing**:
- Unit test: Verify fixtures work individually
- Integration test: Verify fixtures compose properly

---

### Task 0.2: Create test database initialization & seeding
**Time**: 3-4 hours | **Commit**: `test: add database seeding utilities`

**Description**: Create utilities to initialize test database and populate with sample data

**Acceptance Criteria**:
- [ ] `backend/tests/fixtures/seed_data.py` contains:
  - `seed_test_database()` - creates schema + sample records
  - `clear_test_database()` - wipes all data
  - Sample data: 50 legacy dives, 25 two-phase dives, 5 sessions
- [ ] Can seed database in <500ms
- [ ] Sample dives include all heights (1m, 3m, 5m, 7m, 10m)
- [ ] Sample dives include all performance levels (F, B, M, G, P)
- [ ] Can query seeded data via SQLAlchemy

**Testing**:
- Unit test: Verify seed data is created correctly
- Unit test: Verify clear operation removes all records
- Integration test: Verify seeded data persists across operations

---

### Task 0.3: Build mock server for mac-agent testing
**Time**: 4-5 hours | **Commit**: `test: create mock sync server`

**Description**: Create mock HTTP server that simulates API responses for testing mac-agent offline

**Acceptance Criteria**:
- [ ] `backend/tests/mock_server.py` contains:
  - `MockSyncServer` class with Flask/FastAPI mock
  - Endpoints: `POST /api/v1/videos/sync`, `POST /api/v1/videos/batch`
  - Configurable responses (success, error, timeout, delay)
- [ ] Mac agent can POST to mock server without real server running
- [ ] Mock server logs all requests for assertion in tests
- [ ] Can simulate network errors (timeout, connection refused)
- [ ] Can simulate server errors (500, 503)
- [ ] Runs on localhost:9999 (non-conflicting port)

**Testing**:
- Unit test: Verify mock responds to valid requests
- Unit test: Verify error simulation works
- Integration test: Test mac-agent against mock server

---

### Task 0.4: Create Pydantic schemas for video sync API
**Time**: 2-3 hours | **Commit**: `feat: define video sync API schemas`

**Description**: Define request/response contracts for video sync endpoints

**Acceptance Criteria**:
- [ ] `backend/app/schemas/video_sync.py` contains:
  ```python
  class VideoSyncRequest(BaseModel):
      dive_code: str  # e.g., "101B"
      height: str     # e.g., "5m"
      performance: Optional[str] = None  # Legacy: F/B/M/G/P
      phase1_performance: Optional[str] = None  # New: Hurdle+Flight
      phase2_performance: Optional[str] = None  # New: Opening+Entry
      video_uuid: str  # Unique identifier for deduplication
      date: datetime
      is_sync: bool = False
      is_smack: bool = False
      person_name: Optional[str] = None

  class VideoSyncResponse(BaseModel):
      dive_id: int
      message: str
      created: bool  # True if new, False if duplicate

  class BatchSyncRequest(BaseModel):
      videos: List[VideoSyncRequest]
      max_retries: int = 3

  class BatchSyncResponse(BaseModel):
      succeeded: int
      failed: int
      errors: List[Dict]  # {video_uuid, error}
  ```
- [ ] Schema validation works with both legacy and two-phase formats
- [ ] Pydantic validators check:
  - Dive code format (e.g., "101B" or "5231D")
  - Height format (e.g., "5m", "5mP")
  - Performance letters (F, B, M, G, P)
  - Phase1/phase2 combinations (no invalid pairs)
- [ ] Schema tests for 20+ valid/invalid combinations

**Testing**:
- Unit test: Parse valid legacy format
- Unit test: Parse valid two-phase format
- Unit test: Reject invalid dive codes
- Unit test: Reject invalid phase combinations

---

### Task 0.5: Design database migrations (SQLAlchemy)
**Time**: 4-5 hours | **Commit**: `db: add migration infrastructure`

**Description**: Set up Alembic migrations and create initial schema migration

**Acceptance Criteria**:
- [ ] `backend/migrations/` directory exists with:
  - `alembic.ini` - Alembic configuration
  - `env.py` - Migration environment setup
  - `script.py.mako` - Migration template
- [ ] Create first migration: `001_add_video_sync_support.py`
  - Adds/updates columns:
    - `dives.video_uuid` (unique, indexed)
    - `dives.phase1_performance` (nullable)
    - `dives.phase2_performance` (nullable)
  - Creates `agent_keys` table for API authentication
  - Creates `sync_audit` table for tracking syncs
  - Adds indexes on frequently queried columns
- [ ] Migration can run forward and backward
- [ ] Migration from test database matches production schema
- [ ] Can run migrations via `alembic upgrade head`

**Testing**:
- Unit test: Verify migration creates expected columns
- Unit test: Verify migration can rollback
- Integration test: Run migration on test database, verify schema

---

### Task 0.6: Implement API key authentication middleware
**Time**: 3-4 hours | **Commit**: `feat: add API key authentication`

**Description**: Create authentication middleware to validate API keys from mac-agent

**Acceptance Criteria**:
- [ ] `backend/app/security.py` contains:
  ```python
  class AgentKey(Base):
      __tablename__ = "agent_keys"
      key: str (unique, indexed)
      mac_hostname: str
      ip_address: str
      created_at: datetime
      last_used: datetime
      is_active: bool
      requests_count: int

  async def verify_api_key(api_key: str = Header(...)) -> AgentKey:
      """Dependency for protecting endpoints"""
  ```
- [ ] Middleware validates `X-API-Key` header on sync endpoints
- [ ] Returns 401 Unauthorized if key invalid
- [ ] Returns 403 Forbidden if key disabled
- [ ] Updates `last_used` and `requests_count` on each request
- [ ] Can generate new keys via CLI: `python create_api_key.py`
- [ ] Can disable keys without deletion

**Testing**:
- Unit test: Verify valid key is accepted
- Unit test: Verify invalid key is rejected
- Unit test: Verify key usage is tracked
- Integration test: Verify endpoint requires auth header

---

### Task 0.7: Write health check endpoint + smoke tests
**Time**: 2-3 hours | **Commit**: `test: add health check and smoke tests`

**Description**: Create health check endpoint and basic smoke tests for all services

**Acceptance Criteria**:
- [ ] `GET /health` endpoint returns:
  ```json
  {
    "status": "ok",
    "database": "connected",
    "version": "1.0.0",
    "timestamp": "2026-01-31T..."
  }
  ```
- [ ] Health check tests:
  - Database connectivity
  - API key system readiness
  - All core endpoints are defined
  - No syntax errors in routes
- [ ] Smoke tests verify:
  - Server starts without errors
  - API documentation is available at `/docs`
  - Database is connected
  - All migrations have run
- [ ] Smoke tests run in <2 seconds

**Testing**:
- Unit test: Health check endpoint returns expected format
- Integration test: Full server startup and health check
- Integration test: Verify all endpoints are registered

---

### Task 0.8: Document API contracts and testing approach
**Time**: 2-3 hours | **Commit**: `docs: add API contract documentation`

**Description**: Create documentation for API contracts and testing strategy

**Acceptance Criteria**:
- [ ] `docs/API_CONTRACTS.md` documents:
  - Video sync endpoint request/response formats
  - Batch sync endpoint request/response formats
  - Error responses (400, 401, 409, 500)
  - Example curl commands for testing
  - Phase validation rules
  - Deduplication behavior
- [ ] `docs/TESTING_STRATEGY.md` documents:
  - How to run tests locally
  - How to use mock server
  - How to test with real database
  - Test naming conventions
  - How to add new tests
- [ ] All code examples are tested and working

**Testing**:
- Manual verification: Run example curl commands
- Manual verification: Follow test setup instructions

---

**Sprint 0 Complete**: Test framework fully functional, database migrations ready, API contracts defined, mock server running

---

## Sprint 1: Mac Worker - Photo Library Integration (5 days)

**Goal**: Extract dive metadata from Photos library, support both legacy and two-phase formats

**Demoable Artifact**: Extract 100+ real videos from Photos library, output JSON with metadata

### Task 1.1: Research Photos.sqlite structure (spike/research)
**Time**: 3-4 hours | **Commit**: `docs: add Photos.sqlite research findings`

**Description**: Document Photos.sqlite schema to understand video/caption extraction

**Acceptance Criteria**:
- [ ] `docs/PHOTOS_SQLITE_SCHEMA.md` documents:
  - Photos.sqlite location on macOS
  - Key tables: `RKVersion`, `RKAttribute`, `RKMediaItem`, `RKMaster`
  - How to join tables for video + caption data
  - SQL query to extract: video path, uuid, date, caption
  - Handle Photos library lock scenarios
  - Known issues in different macOS versions (Ventura, Sonoma, Sequoia)
- [ ] Create test query that works on local Photos library
- [ ] Document any schema changes needed for Photos app updates
- [ ] Include backup/recovery notes

**Testing**:
- Manual: Run documented SQL queries on real Photos library
- Manual: Verify extracted video paths exist on disk

---

### Task 1.2: Implement caption parser for two-phase format
**Time**: 4-5 hours | **Commit**: `feat: add two-phase dive caption parser`

**Description**: Parse dive captions supporting legacy and new two-phase format

**Acceptance Criteria**:
- [ ] `mac-agent/src/metadata.py` contains `parse_dive_caption()`:
  ```python
  def parse_dive_caption(caption: str) -> Dict[str, Any]:
      """
      Parse: "101B G/P 5m SYNC" or "101B P 5m" (legacy)
      Returns: {
        dive_code, performance, phase1_performance, phase2_performance,
        height, is_sync, is_smack, person_name
      }
      """
  ```
- [ ] Supports formats:
  - Legacy: `"101B P 5m"` → single performance
  - Two-phase: `"101B G/P 5m"` → phase1=G, phase2=P
  - Numeric: `"101B 3/4 5m"` → numeric scores
  - Platforms: `"101B P 5mP"` or `"101B P 10m"`
  - Keywords: `SYNC`, `SMACK`, person names
- [ ] Handles edge cases:
  - Uppercase/lowercase normalization
  - Extra whitespace
  - Missing optional fields
  - Malformed input (returns None safely)
- [ ] Parser tests: 50+ test cases (valid + invalid)

**Testing**:
- Unit test: 25 valid captions parse correctly
- Unit test: 25 invalid/malformed captions handled gracefully
- Unit test: Performance letters (F/B/M/G/P) and numeric scores (0-4)
- Unit test: All platform variants (1m, 3m, 5m, 7m, 10m, with P suffix)
- Unit test: Keyword parsing (SYNC, SMACK, person names)

---

### Task 1.3: Implement Photos.sqlite query & video extraction
**Time**: 4-5 hours | **Commit**: `feat: query Photos.sqlite for video metadata`

**Description**: Query Photos library and extract video records with captions

**Acceptance Criteria**:
- [ ] `mac-agent/src/photos_db.py` contains:
  ```python
  class PhotosDatabaseReader:
      def __init__(self, library_path: str):
          self.db_path = library_path / "database/Photos.sqlite"

      def get_videos_since(self, since: datetime) -> List[VideoRecord]:
          """Query for videos added/modified since timestamp"""

      def get_video_by_uuid(self, uuid: str) -> Optional[VideoRecord]:
          """Get single video by UUID"""
  ```
- [ ] Returns: VideoRecord with video_path, uuid, date, caption
- [ ] Handles Photos.sqlite locking (open read-only, retry on lock)
- [ ] Handles missing captions gracefully
- [ ] Can extract 100+ videos in <5 seconds
- [ ] Deduplicates by UUID (no duplicates in results)
- [ ] Persists checkpoint (last query time) to local file

**Testing**:
- Unit test: Parse SQL results into VideoRecord objects
- Integration test: Query real Photos library, verify results
- Integration test: Query with `since` timestamp filters correctly
- Integration test: Checkpoint persistence works across runs

---

### Task 1.4: Implement file system watcher with FSEvents
**Time**: 4-5 hours | **Commit**: `feat: watch Photos library for changes`

**Description**: Monitor Photos library directory for new/modified videos using FSEvents

**Acceptance Criteria**:
- [ ] `mac-agent/src/watcher.py` contains:
  ```python
  class PhotosLibraryWatcher:
      def __init__(self, library_path: str, on_change: Callable):
          # Watch Photos library directory for changes

      async def watch(self):
          """Block and watch for changes"""

      def stop(self):
          """Stop watching"""
  ```
- [ ] Uses FSEvents (macOS native) to watch for file changes
- [ ] Batches changes (don't trigger on every single file)
- [ ] Detects new video files added to library
- [ ] Handles Photos library locked/unlocked states
- [ ] Handles Photos app updates
- [ ] Non-blocking: runs in background thread/asyncio
- [ ] Can watch for 8+ hours without memory leaks

**Testing**:
- Unit test: FSEvents handler fires on file changes
- Integration test: Create new video in Photos, watcher detects it
- Integration test: Watch for 10+ minutes, verify no memory leak
- Integration test: Stop/restart watcher multiple times

---

### Task 1.5: Create metadata extraction orchestrator
**Time**: 3-4 hours | **Commit**: `feat: orchestrate photo extraction pipeline`

**Description**: Combine watcher + parser + database reader into extraction pipeline

**Acceptance Criteria**:
- [ ] `mac-agent/src/extractor.py` contains:
  ```python
  class MetadataExtractor:
      def __init__(self, library_path, output_file):
          self.watcher = PhotosLibraryWatcher(...)
          self.parser = CaptionParser()
          self.db = PhotosDatabaseReader(...)

      async def extract_pending_videos(self) -> List[Dict]:
          """Get new videos, extract metadata, return list"""
  ```
- [ ] Extracts metadata for all new videos
- [ ] Parses captions using two-phase format parser
- [ ] Logs unparseable captions for debugging
- [ ] Returns list ready to send to server:
  ```python
  [{
    "dive_code": "101B",
    "height": "5m",
    "performance": "P",  # Legacy
    "phase1_performance": "G",  # New
    "phase2_performance": "P",  # New
    "video_uuid": "ABC123",
    "date": "2026-01-31T...",
    "is_sync": false,
    "is_smack": false
  }, ...]
  ```
- [ ] Handles zero new videos gracefully (returns empty list)

**Testing**:
- Unit test: Orchestrator combines all components
- Integration test: Extract metadata from 10 videos
- Integration test: All extracted videos have valid format
- Integration test: Handles edge cases (missing captions, invalid videos)

---

### Task 1.6: Add configuration and logging
**Time**: 3-4 hours | **Commit**: `feat: add config parsing and logging setup`

**Description**: Load configuration from YAML file and setup structured logging

**Acceptance Criteria**:
- [ ] `mac-agent/config.example.yaml`:
  ```yaml
  server:
    url: https://192.168.1.57:8000
    api_key: YOUR-API-KEY-HERE
    timeout_seconds: 30

  photos:
    library_path: ~/Pictures/Photos Library.photoslibrary

  sync:
    interval_seconds: 300  # Check every 5 min
    batch_size: 50
    max_retries: 3

  power:
    prevent_sleep: true
    prevent_display_sleep: false

  logging:
    level: INFO
    file: ~/Library/Logs/diveanalyzer.log
    rotate_mb: 10
    keep_files: 5
  ```
- [ ] `mac-agent/src/config.py` loads and validates config
- [ ] All paths expand (~/...) correctly
- [ ] Missing required fields raise clear errors
- [ ] Logging configured with:
  - Console output (INFO level)
  - File rotation (10MB per file, keep 5 files)
  - Structured format: `{timestamp} {level} {module} {message}`
- [ ] Logger available as `from src.logger import logger`

**Testing**:
- Unit test: Load valid config file
- Unit test: Reject invalid config (missing required fields)
- Unit test: Path expansion works (~, relative paths)
- Unit test: Log rotation works correctly
- Integration test: Logger writes to file and console

---

### Task 1.7: Implement error recovery for extraction
**Time**: 3-4 hours | **Commit**: `feat: add extraction error handling`

**Description**: Handle common extraction failures gracefully

**Acceptance Criteria**:
- [ ] Errors handled:
  - Photos.sqlite locked by Photos app → Retry with backoff
  - Invalid caption format → Log warning, skip video
  - File permission denied → Log error, skip video
  - Photo library not found → Log error, pause sync
  - Disk full → Log critical error, pause sync
  - Network unavailable → Handled by sync client (next sprint)
- [ ] Retry logic:
  - Max 3 retries for transient errors (locked db)
  - Exponential backoff: 1s, 2s, 4s
  - Permanent errors: log once, move on
- [ ] Graceful degradation:
  - Bad captions don't stop sync
  - Bad videos are skipped
  - Extraction continues on single-video failures
- [ ] All errors logged with context (video UUID, caption, etc.)

**Testing**:
- Unit test: Locked database triggers retry
- Unit test: Invalid caption skipped with warning logged
- Unit test: File permission error handled gracefully
- Integration test: Partial failure (3 of 10 videos fail) → 7 synced
- Integration test: Error recovery doesn't crash process

---

**Sprint 1 Complete**: Can extract 100+ videos from Photos library with metadata, both legacy and two-phase formats parsed, errors handled gracefully

---

## Sprint 2: Mac Worker - Sync Client (5 days)

**Goal**: Build HTTPS sync client with retry logic, batch support, offline queueing

**Demoable Artifact**: Monitor Mac logs showing videos syncing to server with retries on failure

### Task 2.1: Implement core sync client (single video)
**Time**: 4-5 hours | **Commit**: `feat: add sync client for single video POST`

**Description**: Build HTTPS client that POSTs single dive metadata to server

**Acceptance Criteria**:
- [ ] `mac-agent/src/sync_client.py` contains:
  ```python
  class SyncClient:
      def __init__(self, server_url: str, api_key: str):
          self.server_url = server_url
          self.api_key = api_key
          self.session = httpx.AsyncClient(
              verify=True,  # HTTPS with cert verification
              timeout=30.0,
              headers={'X-API-Key': api_key}
          )

      async def sync_video(self, metadata: Dict) -> SyncResult:
          """POST single video to /api/v1/videos/sync"""
  ```
- [ ] POSTs to `{server_url}/api/v1/videos/sync`
- [ ] Includes API key in `X-API-Key` header
- [ ] Returns SyncResult: `{success: bool, dive_id: int, error: str}`
- [ ] Handles success (200, 201): Returns dive_id
- [ ] Handles duplicate (409): Returns error "Duplicate video"
- [ ] Handles validation error (400): Returns error with details
- [ ] Handles auth error (401, 403): Returns error "Invalid API key"
- [ ] Handles server error (500+): Raises exception (for retry logic)
- [ ] Timeout after 30 seconds

**Testing**:
- Unit test: Mock server returns 201 Created
- Unit test: Extract dive_id from response
- Unit test: Handle 409 Conflict (duplicate)
- Unit test: Handle 400 Bad Request
- Unit test: Handle 401 Unauthorized
- Unit test: Handle 500 Server Error
- Unit test: Handle timeout (mock delay)

---

### Task 2.2: Add retry logic with exponential backoff
**Time**: 4-5 hours | **Commit**: `feat: add exponential backoff retry strategy`

**Description**: Wrap sync client with retry logic for resilience

**Acceptance Criteria**:
- [ ] `mac-agent/src/sync_client.py` adds:
  ```python
  async def sync_video_with_retries(
      self,
      metadata: Dict,
      max_retries: int = 3
  ) -> SyncResult:
      """Sync with exponential backoff: 1s, 2s, 4s, 8s"""
  ```
- [ ] Retry strategy:
  - Attempt 1: immediate
  - Attempt 2: wait 1s, retry
  - Attempt 3: wait 2s, retry
  - Attempt 4: wait 4s, retry
  - Attempt 5: fail (max retries exceeded)
- [ ] Retryable errors:
  - Timeout → retry
  - 500+ Server error → retry
  - Connection refused → retry
  - Connection reset → retry
- [ ] Non-retryable errors:
  - 400 Bad Request → fail immediately
  - 401 Unauthorized → fail immediately
  - 409 Conflict → fail immediately (duplicate)
- [ ] Logs each attempt: "Attempt 2/4 for video ABC123"
- [ ] Logs final status: "Success on attempt 2" or "Failed after 4 attempts"

**Testing**:
- Unit test: First attempt succeeds → no retries
- Unit test: First attempt fails, second succeeds → 1 retry
- Unit test: All attempts fail → final error after max retries
- Unit test: Non-retryable error fails immediately
- Unit test: Exponential backoff delays are correct (1s, 2s, 4s)
- Unit test: Logs show all retry attempts

---

### Task 2.3: Implement batch sync endpoint
**Time**: 4-5 hours | **Commit**: `feat: add batch video sync support`

**Description**: Support syncing multiple videos in single HTTP request

**Acceptance Criteria**:
- [ ] `mac-agent/src/sync_client.py` adds:
  ```python
  async def sync_batch(
      self,
      videos: List[Dict],
      batch_size: int = 50,
      max_retries: int = 3
  ) -> BatchSyncResult:
      """POST batch of videos to /api/v1/videos/batch"""
  ```
- [ ] POSTs to `{server_url}/api/v1/videos/batch`
- [ ] Request format:
  ```json
  {
    "videos": [
      {dive_code, height, phase1, phase2, ...},
      {...}
    ]
  }
  ```
- [ ] Response format:
  ```json
  {
    "total": 50,
    "succeeded": 48,
    "failed": 2,
    "errors": [
      {"video_uuid": "ABC123", "error": "Invalid dive code"}
    ]
  }
  ```
- [ ] Splits large lists into batches (configurable batch_size)
- [ ] Processes batches sequentially with retries
- [ ] Returns aggregated result (total succeeded, failed, all errors)
- [ ] Batch size default 50, configurable up to 200
- [ ] Logs batch progress: "Syncing 150 videos in 3 batches"

**Testing**:
- Unit test: Single batch (< batch_size) succeeds
- Unit test: Multiple batches split correctly
- Unit test: Batch size configurable
- Unit test: Partial failure handled (failed: 2, succeeded: 48)
- Unit test: Empty batch handled
- Unit test: Large batch (5000 videos) split into 100 batches
- Integration test: Batch retries work (first batch fails, retry succeeds)

---

### Task 2.4: Test sync client against mock server
**Time**: 3-4 hours | **Commit**: `test: add sync client mock server tests`

**Description**: Verify sync client works against the mock server from Sprint 0

**Acceptance Criteria**:
- [ ] `mac-agent/tests/test_sync_client.py`:
  - Tests sync_video() against mock server
  - Tests batch sync against mock server
  - Tests retry logic with mock server timeouts
  - Tests error handling against mock 400/500 responses
- [ ] All tests pass locally
- [ ] Mock server started automatically for tests
- [ ] Tests verify:
  - API key header sent correctly
  - Request body formatted correctly
  - Response parsing works
  - Batch requests formatted correctly
- [ ] Can run tests without real server: `pytest test_sync_client.py -m mock`

**Testing**:
- Unit test: 15+ test cases for sync client behaviors
- Integration test: Real sync client against mock server

---

### Task 2.5: Add offline queue and persistence
**Time**: 4-5 hours | **Commit**: `feat: add offline video queue with persistence`

**Description**: Queue videos locally when server is unavailable

**Acceptance Criteria**:
- [ ] `mac-agent/src/queue.py` contains:
  ```python
  class VideoQueue:
      def __init__(self, queue_file: str):
          self.queue_file = queue_file  # ~/.diveanalyzer/queue.json

      def add_video(self, metadata: Dict):
          """Add video to queue"""

      def get_pending(self) -> List[Dict]:
          """Get all queued videos"""

      def mark_synced(self, video_uuid: str):
          """Remove from queue after successful sync"""

      def clear_synced(self):
          """Remove all successfully synced videos"""
  ```
- [ ] Persistence:
  - Stores queue in `~/.diveanalyzer/queue.json`
  - Survives Mac restart
  - Atomic writes (no partial saves)
  - Max queue size: 10,000 videos (~5MB)
- [ ] Queue management:
  - Add video checks for duplicates (don't queue same UUID twice)
  - Get pending returns all unsynced videos
  - Mark synced removes from queue
  - Can clear all once synced (cleanup)
- [ ] Integration with sync:
  - Check offline queue before making API call
  - Sync queued videos with retries
  - Remove from queue on success
  - Re-queue on failure (exponential backoff)

**Testing**:
- Unit test: Add video to queue
- Unit test: Persist to file and reload
- Unit test: Mark as synced removes from queue
- Unit test: Duplicate detection works
- Unit test: Max size enforcement
- Integration test: Queue survives process restart
- Integration test: Offline mode: add 100 videos, go online, sync all

---

### Task 2.6: Implement online/offline detection
**Time**: 2-3 hours | **Commit**: `feat: detect online/offline status`

**Description**: Monitor network connectivity, defer sync when offline

**Acceptance Criteria**:
- [ ] `mac-agent/src/network.py` contains:
  ```python
  async def is_online() -> bool:
      """Check if network is available"""
      # Try to reach server, or fallback to DNS check

  async def wait_for_network(timeout_seconds: int = 300):
      """Block until network available"""
  ```
- [ ] Online detection:
  - Try to reach server endpoint (fast)
  - Fallback to DNS check (resolve google.com)
  - Timeout after 5 seconds
- [ ] Offline handling:
  - Log "Network unavailable, queuing for later"
  - Add videos to offline queue
  - Wait for network with backoff
  - Retry sync when network available
- [ ] Can detect network state in <5 seconds

**Testing**:
- Unit test: Detect online network
- Unit test: Detect offline network (mock network unavailable)
- Unit test: Wait for network blocks until available
- Integration test: Queue during offline, sync when online

---

### Task 2.7: Add rate limiting and request throttling
**Time**: 3-4 hours | **Commit**: `feat: implement rate limiting and throttling`

**Description**: Respect server rate limits and avoid overwhelming server

**Acceptance Criteria**:
- [ ] Rate limiting:
  - Parse 429 Too Many Requests response
  - Read `Retry-After` header if present
  - Implement exponential backoff: wait and retry
  - Default backoff: 60 seconds if header not present
- [ ] Request throttling:
  - Max 10 requests per second (configurable)
  - Space out batch requests
  - Don't hammer server when catching up (after downtime)
- [ ] Logging:
  - Log rate limit hits: "Rate limited, waiting 60s"
  - Log throttling: "Throttling to 10 req/s"
- [ ] Configuration:
  - Max requests per second configurable in config.yaml
  - Retry-after delays configurable

**Testing**:
- Unit test: Parse Retry-After header
- Unit test: Exponential backoff calculation
- Unit test: Request throttling limits requests per second
- Integration test: Simulate 429 response, verify retry after delay

---

**Sprint 2 Complete**: Sync client can handle single/batch sync, retries with exponential backoff, offline queuing, rate limiting

---

## Sprint 3: Mac Worker - Packaging & LaunchAgent (3 days)

**Goal**: Package mac-agent for distribution, auto-start with LaunchAgent, easy installation

**Demoable Artifact**: Run installer script, see agent auto-start after Mac restart

### Task 3.1: Create distribution package structure
**Time**: 2-3 hours | **Commit**: `build: create installable mac-agent package`

**Description**: Package mac-agent as a clean, distributable artifact

**Acceptance Criteria**:
- [ ] Directory structure:
  ```
  mac-agent/
  ├── src/
  │   ├── __init__.py
  │   ├── main.py (entry point)
  │   ├── watcher.py
  │   ├── metadata.py
  │   ├── photos_db.py
  │   ├── sync_client.py
  │   ├── queue.py
  │   ├── config.py
  │   ├── logger.py
  │   └── network.py
  ├── requirements.txt (all dependencies)
  ├── pyproject.toml (package metadata)
  ├── setup.py (for pip install)
  ├── config.example.yaml (template)
  ├── install.sh (installer script)
  ├── uninstall.sh (uninstaller script)
  └── README.md (setup instructions)
  ```
- [ ] requirements.txt includes:
  - httpx (async HTTP client)
  - aiofiles (async file I/O)
  - pyyaml (YAML config)
  - fsevents (macOS file watching)
  - python-dotenv (env var support)
- [ ] pyproject.toml defines:
  - Package name, version, author
  - Entry point: `diveanalyzer = src.main:main`
  - Python version: 3.10+
- [ ] Can install via: `pip install -e .` (editable install)

**Testing**:
- Manual: Install package with pip
- Manual: Verify entry point works: `python -m src.main --help`
- Manual: All imports resolve correctly

---

### Task 3.2: Write installer script
**Time**: 3-4 hours | **Commit**: `build: add installer script with validation`

**Description**: Create installer that sets up virtual environment, validates configuration, installs LaunchAgent

**Acceptance Criteria**:
- [ ] `install.sh` script:
  ```bash
  #!/bin/bash
  # 1. Check Python 3.10+ installed
  # 2. Create ~/.diveanalyzer directory
  # 3. Create virtual environment
  # 4. Install requirements
  # 5. Copy config template
  # 6. Prompt for server URL and API key
  # 7. Validate configuration
  # 8. Install LaunchAgent plist
  # 9. Start agent
  # 10. Show status
  ```
- [ ] Checks before installing:
  - Python 3.10+ available
  - macOS 10.13+ (for Photos API)
  - Sufficient disk space (100MB)
  - Write permissions to ~/.diveanalyzer
- [ ] Creates:
  - `~/.diveanalyzer/` directory
  - Virtual environment in `~/.diveanalyzer/venv/`
  - `~/.diveanalyzer/config.yaml` from template
  - `~/Library/LaunchAgents/com.diveanalyzer.agent.plist`
- [ ] Prompts user for:
  - Server URL (validate HTTPS)
  - API key (validate length)
  - Photos library path (auto-detect default)
- [ ] Validates configuration:
  - Server is reachable
  - API key works (test sync)
  - Photos library accessible
- [ ] Error messages clear and actionable
- [ ] Non-interactive mode: `./install.sh --server=https://... --api-key=...`

**Testing**:
- Manual: Run installer on clean Mac
- Manual: Verify all files created in correct locations
- Manual: Verify LaunchAgent installed
- Manual: Test error cases (no Python, permission denied, etc.)

---

### Task 3.3: Create LaunchAgent configuration
**Time**: 2-3 hours | **Commit**: `build: add LaunchAgent plist configuration`

**Description**: Create plist file for auto-start on Mac login

**Acceptance Criteria**:
- [ ] `mac-agent/com.diveanalyzer.agent.plist`:
  ```xml
  <?xml version="1.0" encoding="UTF-8"?>
  <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "...">
  <plist version="1.0">
  <dict>
      <key>Label</key>
      <string>com.diveanalyzer.agent</string>

      <key>ProgramArguments</key>
      <array>
          <string>/usr/bin/env</string>
          <string>caffeinate</string>
          <string>-i</string>
          <string>python3</string>
          <string>~/.diveanalyzer/venv/bin/python</string>
          <string>-m</string>
          <string>src.main</string>
      </array>

      <key>RunAtLoad</key>
      <true/>

      <key>KeepAlive</key>
      <dict>
          <key>SuccessfulExit</key>
          <false/>
      </dict>

      <key>StandardOutPath</key>
      <string>~/Library/Logs/diveanalyzer.log</string>

      <key>StandardErrorPath</key>
      <string>~/Library/Logs/diveanalyzer.error.log</string>
  </dict>
  </plist>
  ```
- [ ] Configuration:
  - Auto-start on login (RunAtLoad = true)
  - Auto-restart on crash (KeepAlive.SuccessfulExit = false)
  - Prevent sleep with `caffeinate -i` (prevents idle sleep)
  - Log to standard locations: `~/Library/Logs/`
  - Use editable install path (survives reinstalls)

**Testing**:
- Manual: Verify plist is valid XML
- Manual: Verify plist installed to `~/Library/LaunchAgents/`
- Manual: Verify agent starts on Mac login
- Manual: Restart Mac and verify auto-start
- Manual: Kill process and verify auto-restart
- Manual: Check logs in ~/Library/Logs/

---

### Task 3.4: Write uninstaller and upgrade script
**Time**: 2-3 hours | **Commit**: `build: add uninstaller and upgrade scripts`

**Description**: Allow clean uninstall and upgrade of agent

**Acceptance Criteria**:
- [ ] `uninstall.sh`:
  - Stop running agent: `launchctl stop com.diveanalyzer.agent`
  - Unload LaunchAgent: `launchctl unload plist`
  - Delete files: ~/.diveanalyzer/, plist, logs
  - Confirmation prompt: "Remove ~/.diveanalyzer? (y/N)"
  - Preserve config.yaml by default (optional: --keep-config)
- [ ] `upgrade.sh`:
  - Stop current agent
  - Backup config.yaml
  - Install new version
  - Restore config.yaml
  - Restart agent
  - Show upgrade summary
- [ ] Both scripts have help: `./uninstall.sh --help`

**Testing**:
- Manual: Full uninstall removes all files
- Manual: Upgrade preserves configuration
- Manual: Re-install after uninstall works
- Manual: Error handling (permission denied, file in use)

---

### Task 3.5: Add configuration file schema validation
**Time**: 2-3 hours | **Commit**: `feat: add config schema validation`

**Description**: Validate config.yaml on startup, provide helpful error messages

**Acceptance Criteria**:
- [ ] `mac-agent/src/config_validator.py`:
  - Define schema for config.yaml
  - Validate on load: required fields, types, values
  - Validate server URL: must be HTTPS
  - Validate API key: must be 40+ characters
  - Validate paths: must exist and be readable
  - Validate logging level: must be DEBUG/INFO/WARNING/ERROR
- [ ] Error messages:
  - Missing field: "Missing required field 'server.api_key' in config.yaml"
  - Invalid URL: "server.url must be HTTPS (got http://...)"
  - Invalid path: "Photos library not found at ~/Pictures/..."
  - Invalid level: "Logging level must be one of: DEBUG, INFO, WARNING, ERROR"
- [ ] Config loads on agent start
- [ ] Validation errors prevent agent from starting
- [ ] Can validate config without running agent: `python -m src.config --validate`

**Testing**:
- Unit test: Valid config passes validation
- Unit test: Missing required field raises error
- Unit test: Invalid URL rejected
- Unit test: Non-existent path rejected
- Integration test: Agent starts with valid config
- Integration test: Agent fails to start with invalid config

---

### Task 3.6: Implement crash recovery and auto-restart
**Time**: 2-3 hours | **Commit**: `feat: add crash recovery mechanism`

**Description**: Detect crashes and recover automatically

**Acceptance Criteria**:
- [ ] Crash detection:
  - Write heartbeat file every 30 seconds: ~/.diveanalyzer/heartbeat
  - If heartbeat older than 60 seconds, agent likely crashed
  - LaunchAgent KeepAlive=true auto-restarts
- [ ] Recovery on restart:
  - Read offline queue (may have synced videos while down)
  - Resume from checkpoint (don't re-process old videos)
  - Retry failed syncs from previous session
  - Log recovery: "Recovered from crash, resuming sync"
- [ ] Error scenarios:
  - Disk full crash → Free space, restart
  - Network down → Queue videos, retry on network
  - Config invalid → Prevent restart, show error in logs
- [ ] Monitoring:
  - Can check agent health: `./check_agent_health.sh`
  - Shows: running, last heartbeat, queue size, sync status

**Testing**:
- Unit test: Heartbeat file creation and reading
- Integration test: Kill agent, verify auto-restart
- Integration test: Resume from offline queue
- Integration test: Crash recovery doesn't lose data

---

### Task 3.7: Create logging setup (rotation, archives)
**Time**: 2-3 hours | **Commit**: `feat: implement log rotation and archiving`

**Description**: Configure log rotation, compression, and long-term archiving

**Acceptance Criteria**:
- [ ] Log rotation:
  - Rotate on size: 10MB
  - Keep 5 recent files: diveanalyzer.log, diveanalyzer.log.1-4
  - Compress old logs: .gz format
  - Delete logs older than 30 days
  - Auto-cleanup before disk full
- [ ] Log format:
  - Structured: `{timestamp} {level} {module}: {message}`
  - Example: `2026-01-31 13:45:12 INFO sync_client: Synced 50 videos in 2.3s`
  - Include context: video UUID, retry count, etc.
- [ ] Log locations:
  - stdout: ~/Library/Logs/diveanalyzer.log
  - stderr: ~/Library/Logs/diveanalyzer.error.log
  - Old logs: ~/Library/Logs/diveanalyzer.log.*.gz
- [ ] Configuration:
  - Log level configurable: DEBUG/INFO/WARNING/ERROR
  - Rotation size configurable
  - Retention days configurable
- [ ] User can access logs easily: `tail -f ~/Library/Logs/diveanalyzer.log`

**Testing**:
- Unit test: Log rotation splits at correct size
- Unit test: Compression works
- Unit test: Old logs deleted after retention period
- Integration test: Agent logs over 8 hours, rotation happens

---

### Task 3.8: Write comprehensive setup and troubleshooting documentation
**Time**: 2-3 hours | **Commit**: `docs: add installation and troubleshooting guide`

**Description**: Create clear documentation for users installing mac-agent

**Acceptance Criteria**:
- [ ] `README.md`:
  - Quick start: `./install.sh`
  - What happens during install
  - Configuration options
  - How to check status
  - How to view logs
  - How to uninstall
- [ ] `TROUBLESHOOTING.md`:
  - Agent not starting: check launchctl, check logs
  - Sync errors: network issues, API key, server down
  - Photos library not found: check path in config
  - Disk full: cleanup old logs
  - Memory issues: restart agent
  - Each issue has 3-5 debugging steps
- [ ] `API_CONFIGURATION.md`:
  - How to generate API key on server
  - How to set server URL
  - How to test API key works
  - Security notes
- [ ] Code examples:
  - Test agent is running: `launchctl list | grep diveanalyzer`
  - View recent logs: `tail -50 ~/Library/Logs/diveanalyzer.log`
  - Manually sync videos: `~/.diveanalyzer/venv/bin/python -m src.main --sync-now`
  - Check agent health: `~/.diveanalyzer/venv/bin/python -m src.main --health`

**Testing**:
- Manual: Follow README on clean Mac, installation succeeds
- Manual: Follow troubleshooting steps for common issues
- Manual: Run all example commands, they work

---

**Sprint 3 Complete**: Mac agent packaged, installable via script, auto-starts on login via LaunchAgent, clear setup and troubleshooting docs

---

## Sprint 4: Server - Sync Endpoints & Database (4 days)

**Goal**: Receive video metadata from mac-agent, validate, store, with deduplication

**Demoable Artifact**: POST from mac-agent to server, see videos in database, query them back

### Task 4.1: Run database migrations
**Time**: 1-2 hours | **Commit**: `db: run video sync migrations`

**Description**: Apply Alembic migrations from Sprint 0 to production database

**Acceptance Criteria**:
- [ ] Migrations applied:
  - `001_add_video_sync_support.py` creates:
    - `dives.video_uuid` (unique, indexed)
    - `dives.phase1_performance`, `dives.phase2_performance` (nullable)
    - `agent_keys` table
    - `sync_audit` table with columns: id, video_uuid, status, error, timestamp, agent_key_id
  - All indexes created
  - Constraints enforced
- [ ] Verify schema:
  - Run migrations forward: `alembic upgrade head`
  - Verify schema matches expected
  - Test database can be queried
- [ ] Backup before migration:
  - Create database dump: `pg_dump diving_analytics > backup.sql`
  - Store safely

**Testing**:
- Manual: Run migrations on test database
- Manual: Query tables to verify columns exist
- Manual: Run migrations backward, verify rollback
- Integration test: Insert dives after migration, query successfully

---

### Task 4.2: Implement Dive model updates
**Time**: 2-3 hours | **Commit**: `feat: update Dive model for sync support`

**Description**: Update SQLAlchemy Dive model with sync-related fields

**Acceptance Criteria**:
- [ ] `backend/app/models/dive.py` updates:
  ```python
  class Dive(Base):
      __tablename__ = "dives"

      # Existing fields...

      # New sync fields:
      video_uuid = Column(String(36), unique=True, index=True, nullable=True)

      # Phase performance (already exists, verify):
      phase1_performance = Column(String(1), nullable=True)
      phase1_numeric = Column(Integer, nullable=True)
      phase2_performance = Column(String(1), nullable=True)
      phase2_numeric = Column(Integer, nullable=True)

      # Sync metadata:
      synced_at = Column(DateTime, nullable=True)
      synced_by_agent_key_id = Column(Integer, ForeignKey('agent_keys.id'))
  ```
- [ ] Relationships:
  - Dive.synced_by_agent_key → AgentKey
  - Query examples: `session.query(Dive).filter(Dive.video_uuid == uuid)`

**Testing**:
- Unit test: Create Dive with all phase fields
- Unit test: Query Dive by video_uuid
- Unit test: Relationship to AgentKey works
- Integration test: Create and query dives with phase data

---

### Task 4.3: Build video sync POST endpoint
**Time**: 4-5 hours | **Commit**: `feat: add POST /api/v1/videos/sync endpoint`

**Description**: Create endpoint to receive single video metadata from mac-agent

**Acceptance Criteria**:
- [ ] `backend/app/api/v1/videos.py`:
  ```python
  @router.post("/sync", status_code=201)
  async def sync_single_video(
      request: VideoSyncRequest,
      api_key: str = Depends(verify_api_key),
      db: Session = Depends(get_db),
  ) -> VideoSyncResponse:
      """Sync single video from mac-agent"""
  ```
- [ ] Endpoint logic:
  1. Validate API key (from middleware)
  2. Validate request schema (Pydantic)
  3. Validate phase scores if two-phase format
  4. Check for duplicate (video_uuid) → 409 if exists
  5. Create Dive record with metadata
  6. Return 201 Created with dive_id
- [ ] Request validation:
  - Dive code: 3-4 digits + A-D position (e.g., "101B")
  - Height: 1-10m, with optional P suffix
  - Performance: single F/B/M/G/P or phase1/phase2
  - Date: valid ISO datetime
- [ ] Error responses:
  - 400: Invalid dive code, height, performance, or date
  - 401: Missing or invalid API key
  - 409: Duplicate video_uuid
  - 500: Database error
- [ ] Response format:
  ```json
  {
    "dive_id": 1234,
    "message": "Video synced successfully",
    "created": true
  }
  ```

**Testing**:
- Unit test: Valid sync request creates dive
- Unit test: Duplicate video returns 409
- Unit test: Invalid dive code returns 400
- Unit test: Missing API key returns 401
- Unit test: Response includes dive_id
- Integration test: MAC can POST and see result in database

---

### Task 4.4: Build batch sync POST endpoint
**Time**: 4-5 hours | **Commit**: `feat: add POST /api/v1/videos/batch endpoint`

**Description**: Create endpoint to receive multiple videos in single request

**Acceptance Criteria**:
- [ ] `backend/app/api/v1/videos.py`:
  ```python
  @router.post("/batch", status_code=207)
  async def sync_batch_videos(
      request: BatchSyncRequest,
      api_key: str = Depends(verify_api_key),
      db: Session = Depends(get_db),
      background_tasks: BackgroundTasks,
  ) -> BatchSyncResponse:
      """Sync multiple videos from mac-agent"""
  ```
- [ ] Batch logic:
  1. Validate all requests before inserting any
  2. Transactional: all succeed or all rollback (no partial syncs)
  3. Filter out duplicates (same video_uuid)
  4. Create Dive records for new videos
  5. Queue milestone detection in background
  6. Return 207 Multi-Status with per-video results
- [ ] Validation:
  - Check all 50 videos before inserting
  - If ANY invalid, return 400 with error details
  - If ALL valid, insert and return 200
- [ ] Response format:
  ```json
  {
    "total": 50,
    "succeeded": 48,
    "failed": 2,
    "errors": [
      {"video_uuid": "ABC", "error": "Invalid dive code"},
      {"video_uuid": "DEF", "error": "Duplicate video"}
    ]
  }
  ```
- [ ] Background tasks:
  - Call JourneyService.process_new_dives() after sync
  - Don't block API response on milestone detection

**Testing**:
- Unit test: Batch of 50 videos synced
- Unit test: Partial failure (48 succeed, 2 fail)
- Unit test: Duplicate filtering works
- Unit test: Transactional: rollback on single error
- Integration test: Batch sync with 100 videos
- Integration test: Verify all dives in database after sync

---

### Task 4.5: Implement PhaseValidator service
**Time**: 3-4 hours | **Commit**: `feat: add phase score validation service`

**Description**: Validate two-phase scores, conversion to legacy format

**Acceptance Criteria**:
- [ ] `backend/app/services/phase_validator.py`:
  ```python
  class PhaseValidator:
      @staticmethod
      def validate_combination(
          phase1: str,
          phase2: str
      ) -> Tuple[bool, Optional[str]]:
          """Validate phase1/phase2 combination"""

      @staticmethod
      def infer_legacy_score(phase1: str, phase2: str) -> str:
          """Convert two-phase to single score"""
  ```
- [ ] Validation rules:
  - Both must be valid performance (F, B, M, G, P)
  - No invalid combinations (TBD with user)
  - Can be identical (e.g., G/G)
  - No restrictions on different values
- [ ] Legacy conversion:
  - Strategy: take minimum (pessimistic)
  - G/P → G (success requires both phases)
  - M/P → M
  - P/P → P
  - F/B → F
- [ ] Usage in endpoints:
  - Call before creating Dive
  - Invalid combination: reject with 400
  - Valid combination: convert to legacy for analytics

**Testing**:
- Unit test: 25 valid combinations pass
- Unit test: 10 invalid combinations fail (if any)
- Unit test: Legacy conversion correct (G/P → G, etc.)
- Integration test: Endpoint validation uses PhaseValidator

---

### Task 4.6: Add deduplication with UUID
**Time**: 3-4 hours | **Commit**: `feat: implement video deduplication by UUID`

**Description**: Detect and reject duplicate video syncs

**Acceptance Criteria**:
- [ ] Deduplication logic:
  - video_uuid is unique constraint in database
  - On sync: check if UUID already exists
  - If exists → 409 Conflict (not 201 Created)
  - Idempotent: POST same video twice → same response
- [ ] Edge cases:
  - UUID collision (cryptographically impossible with real UUIDs)
  - Sync same video from different mac-agents (allow? TBD)
  - Update existing video (current plan: don't allow, create new)
- [ ] Tracking:
  - Log all duplicate attempts: "Duplicate video ABC123 from agent XYZ"
  - Track in sync_audit table

**Testing**:
- Unit test: First sync creates dive (201)
- Unit test: Second sync same UUID returns 409
- Integration test: Two POSTs same UUID → first 201, second 409
- Integration test: Duplicate in batch: processed, marked as error

---

### Task 4.7: Add audit logging for all syncs
**Time**: 3-4 hours | **Commit**: `feat: add sync audit logging`

**Description**: Track all video syncs for debugging and compliance

**Acceptance Criteria**:
- [ ] `sync_audit` table records:
  - video_uuid
  - dive_id (if synced successfully)
  - status: "success", "duplicate", "error"
  - error_message (if failed)
  - timestamp
  - agent_key_id (which agent synced)
  - request_ip (where request came from)
  - source_device_name (if provided in request)
- [ ] Logging on sync:
  - Success: "Synced video ABC123 → dive #1234 from agent XYZ"
  - Duplicate: "Skipped duplicate ABC123"
  - Error: "Failed to sync ABC123: Invalid dive code"
- [ ] Queryable logs:
  - All syncs from specific agent
  - All syncs on specific date
  - All syncs for specific dive_code
- [ ] Audit queries:
  ```python
  session.query(SyncAudit).filter(SyncAudit.status == "error")
  session.query(SyncAudit).filter(SyncAudit.agent_key_id == 1)
  session.query(SyncAudit).filter(
      SyncAudit.timestamp >= date
  ).order_by(SyncAudit.timestamp.desc())
  ```

**Testing**:
- Unit test: Successful sync logged to audit table
- Unit test: Duplicate sync logged
- Unit test: Failed sync logged with error message
- Integration test: Query audit logs by various filters

---

### Task 4.8: Write integration tests (mac agent ↔ server)
**Time**: 4-5 hours | **Commit**: `test: add mac-to-server integration tests`

**Description**: Test actual mac-agent syncing to server endpoints

**Acceptance Criteria**:
- [ ] `backend/tests/test_sync_integration.py`:
  - Start server on localhost:8000
  - Create test API key in database
  - Call sync_client.sync_video() with test metadata
  - Verify response (201, dive_id, etc.)
  - Verify Dive created in database
  - Verify audit log entry created
- [ ] Tests:
  - Single video sync
  - Batch sync (10 videos)
  - Batch sync (100 videos)
  - Duplicate detection
  - Invalid dive code rejection
  - Phase validation
  - Error handling (server error, timeout, etc.)
- [ ] Test data:
  - Mix of legacy and two-phase videos
  - All heights (1m-10m)
  - All performance levels (F-P)
  - Syncs, smacks, person dives
- [ ] Can run: `pytest tests/test_sync_integration.py`

**Testing**:
- Integration test: 20+ end-to-end scenarios
- Performance test: Sync 1000 videos, measure time

---

### Task 4.9: Performance testing (1000+ video sync)
**Time**: 3-4 hours | **Commit**: `test: add performance testing for bulk sync`

**Description**: Verify sync endpoints can handle large batches efficiently

**Acceptance Criteria**:
- [ ] Performance benchmarks:
  - Single sync: <100ms (including validation, DB insert)
  - Batch of 50: <500ms
  - Batch of 100: <1000ms
  - Batch of 5000 (50 batches of 100): <50s
- [ ] Test scenario:
  - Generate 1000 test videos
  - Sync in batches of 100
  - Measure: time, memory, disk
  - Verify all 1000 in database
  - Verify no data loss
- [ ] Optimization if needed:
  - Bulk insert optimization
  - Index usage verification
  - Query optimization
- [ ] Acceptable performance:
  - Sync 5000 videos: <5 minutes
  - Memory usage: <500MB
  - No connection pooling issues

**Testing**:
- Performance test: Generate load, measure throughput
- Memory test: Monitor memory growth, check for leaks
- Database test: Verify indexes used correctly

---

**Sprint 4 Complete**: Server receives and stores videos, validates phase scores, deduplicates, audits all syncs, performance verified

---

## Sprint 5: Server - Journey Integration (3 days)

**Goal**: Trigger milestone detection on new videos, generate phase-aware coaching

**Demoable Artifact**: Sync new videos, see new milestones with phase coaching appear in Journey UI

### Task 5.1: Integrate video sync with JourneyService
**Time**: 3-4 hours | **Commit**: `feat: trigger milestone detection on sync`

**Description**: Call MilestoneDetector after videos are synced

**Acceptance Criteria**:
- [ ] `backend/app/services/journey_service.py`:
  ```python
  async def process_new_dives(
      self,
      dive_ids: List[int],
      db: Session
  ):
      """Called after batch sync completes"""
  ```
- [ ] Logic:
  1. Get all dives (to refresh state)
  2. Call MilestoneDetector.detect_milestones()
  3. Get returned milestones (new ones detected)
  4. For each milestone, generate phase insight if data available
  5. Store phase_insight in milestone record
  6. Emit WebSocket event (done in Sprint 6)
- [ ] Milestone detection:
  - Already implemented in milestones.py
  - Just need to call it with updated dive list
  - Filter for only new/changed dives (optimization)

**Testing**:
- Unit test: JourneyService calls MilestoneDetector
- Unit test: Phase insights generated for milestones
- Integration test: Sync new dives, verify milestones created
- Integration test: Re-run milestone detection, no duplicates

---

### Task 5.2: Call MilestoneDetector after batch sync completes
**Time**: 2-3 hours | **Commit**: `feat: async milestone detection after sync`

**Description**: Queue background task to detect milestones, don't block API

**Acceptance Criteria**:
- [ ] In `videos.py` POST /batch endpoint:
  ```python
  background_tasks.add_task(
      journey_service.process_new_dives,
      newly_synced_dive_ids,
      db
  )
  return batch_response  # Don't wait for milestone detection
  ```
- [ ] Background processing:
  - Runs after API returns 201
  - Doesn't block mac-agent
  - Any errors logged but don't fail the sync
- [ ] Logging:
  - "Queued milestone detection for 50 dives"
  - "Detected 3 new milestones"
  - "Generated phase coaching for 2 milestones"

**Testing**:
- Unit test: Background task queued correctly
- Integration test: API returns before milestones computed
- Integration test: Milestones appear within 5 seconds

---

### Task 5.3: Store phase_insight in Milestone record
**Time**: 2-3 hours | **Commit**: `feat: store phase coaching in milestone`

**Description**: Save generated insights in database

**Acceptance Criteria**:
- [ ] `backend/app/models/milestone.py` adds:
  ```python
  class Milestone(Base):
      # Existing fields...

      phase_insight = Column(Text, nullable=True)  # Coaching text
      phase1_performance = Column(String(1), nullable=True)  # From dive
      phase2_performance = Column(String(1), nullable=True)  # From dive
  ```
- [ ] When generating milestone:
  - Extract phase data from associated dives
  - Call `_generate_phase_insight()`
  - Store in phase_insight column
  - Store phase1/phase2 for display in UI
- [ ] Query examples:
  ```python
  milestones_with_coaching = session.query(Milestone).filter(
      Milestone.phase_insight.isnot(None)
  )
  ```

**Testing**:
- Unit test: Milestone created with phase_insight
- Integration test: Query milestones with coaching

---

### Task 5.4: Test milestone detection with two-phase data
**Time**: 3-4 hours | **Commit**: `test: verify milestones work with two-phase format`

**Description**: Verify all milestone types work with phase data

**Acceptance Criteria**:
- [ ] Create test dives with two-phase data
- [ ] Test all 17 milestone types:
  - Breakthrough (failure → success)
  - Perfect streak (10+ P-grade dives)
  - Redemption (smack → perfect)
  - Avoided dive (tried after failures)
  - And 13 more...
- [ ] Verify phase insights generated for each:
  - Different insight for P/P vs G/M vs M/P
  - Insights are specific to dive type
- [ ] Test with mixed legacy + two-phase dives:
  - Legacy dives: no phase insight
  - Two-phase dives: include phase insight
  - Milestones across both types work correctly

**Testing**:
- Unit test: Each milestone type detected correctly
- Unit test: Phase insights generated correctly
- Integration test: Mixed legacy + two-phase data
- Integration test: Milestones don't duplicate on re-run

---

### Task 5.5: Write integration tests (sync → milestone detection)
**Time**: 3-4 hours | **Commit**: `test: add sync-to-milestone integration tests`

**Description**: Test full flow: sync videos → detect milestones → generate coaching

**Acceptance Criteria**:
- [ ] `backend/tests/test_milestone_integration.py`:
  - Sync 20 new videos
  - Wait for background task
  - Query milestones
  - Verify milestones detected
  - Verify phase insights present (for two-phase dives)
  - Verify insights are correct text
- [ ] Test scenarios:
  - Breakthrough milestone with two-phase data
  - Perfect streak with mixed phase data
  - Redemption with phase coaching
- [ ] Can run: `pytest tests/test_milestone_integration.py`

**Testing**:
- Integration test: 10+ end-to-end scenarios
- Manual: Sync videos and watch milestones appear in Journey page

---

### Task 5.6: Performance test milestone detection (1000+ dives)
**Time**: 2-3 hours | **Commit**: `test: benchmark milestone detection performance`

**Description**: Verify milestone detection doesn't slow down under load

**Acceptance Criteria**:
- [ ] Performance targets:
  - Detect milestones for 1000 dives: <10 seconds
  - Detect milestones for 5000 dives: <60 seconds
  - Memory usage: <200MB
- [ ] Test scenario:
  - Populate database with 1000 existing dives
  - Sync 50 new dives
  - Time milestone detection
  - Verify only new milestones detected (not re-processing old)
- [ ] Optimization if needed:
  - Only process newly added dives
  - Use indexes for query efficiency
  - Cache milestone state

**Testing**:
- Performance test: Time milestone detection
- Memory test: Monitor for leaks

---

**Sprint 5 Complete**: New synced videos trigger milestone detection, phase-aware coaching generated, full integration tested

---

## Sprint 6: Server - Real-Time Monitoring (4 days)

**Goal**: WebSocket endpoint for real-time sync status updates

**Demoable Artifact**: Connect WebSocket client, see sync progress in real-time

### Task 6.1: Implement WebSocket endpoint and connection management
**Time**: 4-5 hours | **Commit**: `feat: add WebSocket endpoint for sync status`

**Description**: Create WebSocket endpoint that clients can connect to for status

**Acceptance Criteria**:
- [ ] `backend/app/api/v1/ws.py`:
  ```python
  @router.websocket("/api/v1/ws/sync-status")
  async def websocket_sync_status(websocket: WebSocket):
      """Real-time sync status updates"""
  ```
- [ ] Connection lifecycle:
  - Client connects: send `{type: "connected", timestamp: "..."}`
  - Client connected: listen for sync events
  - Client disconnects: clean up
- [ ] Error handling:
  - Handle client disconnect gracefully
  - Handle network interruptions
  - Attempt reconnection (client-side)
  - Timeout idle connections (5 min)
- [ ] Can handle:
  - 10 concurrent clients
  - 100 concurrent clients (tested)

**Testing**:
- Unit test: WebSocket accepts connections
- Unit test: WebSocket messages formatted correctly
- Unit test: Disconnect handled gracefully
- Integration test: 10 concurrent clients

---

### Task 6.2: Build SyncStatusTracker service
**Time**: 3-4 hours | **Commit**: `feat: add sync status tracking service`

**Description**: Track current sync status for broadcasting

**Acceptance Criteria**:
- [ ] `backend/app/services/sync_tracker.py`:
  ```python
  class SyncStatusTracker:
      def start_sync(self, count: int):
          """Sync of count videos starting"""

      def progress(self, processed: int, failed: int):
          """Update progress"""

      def complete(self):
          """Sync completed"""

      def get_status(self) -> Dict:
          """Current status"""
  ```
- [ ] Tracks:
  - Current sync status: idle, syncing, completed
  - Total videos: count
  - Processed count: how many done
  - Failed count: how many errors
  - Elapsed time
  - Estimated remaining time
  - Current speed: videos/second
- [ ] State machine:
  - idle → syncing (start_sync)
  - syncing → syncing (progress)
  - syncing → completed (complete)
  - completed → idle (on next sync)

**Testing**:
- Unit test: State transitions correct
- Unit test: Metrics calculated correctly
- Unit test: Handles concurrent calls

---

### Task 6.3: Implement status message broadcasting
**Time**: 3-4 hours | **Commit**: `feat: broadcast sync status to connected clients`

**Description**: Send status updates to all connected WebSocket clients

**Acceptance Criteria**:
- [ ] Messages sent to WebSocket clients:
  ```json
  {
    "type": "sync_started",
    "timestamp": "2026-01-31T...",
    "total": 50
  }
  {
    "type": "sync_progress",
    "processed": 25,
    "total": 50,
    "failed": 0,
    "speed": 12.5
  }
  {
    "type": "sync_completed",
    "total": 50,
    "succeeded": 50,
    "failed": 0,
    "duration_seconds": 4.5
  }
  {
    "type": "error",
    "message": "Network error during sync"
  }
  ```
- [ ] Broadcasting logic:
  - Maintain list of connected WebSocket clients
  - On status update, send to all clients
  - Handle client disconnect mid-message
  - Retry broadcast if client unresponsive (timeout)
- [ ] Message frequency:
  - Sync started: immediately
  - Progress: every 1 second (or every 10% progress)
  - Sync completed: immediately
  - Errors: immediately

**Testing**:
- Unit test: Broadcast reaches all clients
- Unit test: Client disconnect doesn't break broadcast
- Integration test: 10 clients receive sync progress

---

### Task 6.4: Add connection lifecycle management
**Time**: 2-3 hours | **Commit**: `feat: manage WebSocket connection lifecycle`

**Description**: Track, cleanup, and manage WebSocket connections

**Acceptance Criteria**:
- [ ] Connection tracking:
  - Store all active WebSocket connections
  - Track client ID, connection time, last message
  - Remove on disconnect
- [ ] Lifecycle events:
  - on_connect: Log connection, send current status
  - on_disconnect: Remove from connection list
  - on_error: Log error, close connection
- [ ] Idle timeout:
  - Disconnect clients idle >5 minutes
  - Send ping every 30 seconds to detect dead connections
  - Client responds with pong
- [ ] Metrics:
  - Track total connections (current + lifetime)
  - Track disconnections per reason (client close, timeout, error)
  - Log connection patterns

**Testing**:
- Unit test: Connection lifecycle correct
- Unit test: Idle timeout works
- Integration test: Ping/pong keeps connection alive

---

### Task 6.5: Write WebSocket client library for testing
**Time**: 2-3 hours | **Commit**: `test: add WebSocket test client`

**Description**: Create simple test client for WebSocket testing

**Acceptance Criteria**:
- [ ] `backend/tests/ws_client.py`:
  ```python
  class WSTestClient:
      async def connect(self, url: str) -> List[Dict]:
          """Connect and collect messages"""

      async def wait_for(self, message_type: str, timeout: float):
          """Wait for specific message"""

      async def disconnect(self):
          """Close connection"""
  ```
- [ ] Can connect to WebSocket server
- [ ] Can receive and parse messages
- [ ] Can disconnect cleanly
- [ ] Can wait for specific message types
- [ ] Can timeout on missing message

**Testing**:
- Unit test: Connect and receive message
- Unit test: Wait for specific message
- Unit test: Timeout if message not received

---

### Task 6.6: Write integration tests (multiple concurrent clients)
**Time**: 3-4 hours | **Commit**: `test: add WebSocket multi-client integration tests`

**Description**: Test WebSocket behavior with multiple clients

**Acceptance Criteria**:
- [ ] `backend/tests/test_ws_integration.py`:
  - Connect 5 clients
  - Simulate sync: send progress updates
  - Verify all clients receive updates
  - Disconnect client mid-sync
  - Verify remaining clients still receive updates
  - Reconnect new client
  - Verify new client receives current status
- [ ] Test scenarios:
  - 5 clients, 1 sync: all receive progress
  - 10 clients, concurrent syncs: correct sync to each
  - Client disconnect: others unaffected
  - Network latency: messages arrive eventually
- [ ] Can run: `pytest tests/test_ws_integration.py`

**Testing**:
- Integration test: 10+ concurrent client scenarios
- Stress test: 100 clients connecting/disconnecting rapidly

---

### Task 6.7: Performance test WebSocket (100+ concurrent connections)
**Time**: 2-3 hours | **Commit**: `test: benchmark WebSocket performance`

**Description**: Verify WebSocket handles expected load

**Acceptance Criteria**:
- [ ] Performance targets:
  - 100 concurrent connections: <1s setup, <100MB memory
  - Broadcast to 100 clients: <100ms per message
  - Message latency: <50ms (p99)
- [ ] Test scenario:
  - Connect 100 clients
  - Send sync progress (every 100ms for 10s)
  - Measure latency, memory, CPU
  - Verify all clients receive all messages
- [ ] Optimization if needed:
  - Async I/O efficiency
  - Connection pooling
  - Message batching

**Testing**:
- Performance test: Load test with 100 clients
- Memory test: Monitor for leaks under sustained load

---

**Sprint 6 Complete**: WebSocket server operational, real-time status broadcasts to multiple concurrent clients, performance verified

---

## Sprint 7: Frontend - Real-Time Sync Status (4 days)

**Goal**: UI component showing live sync status and progress

**Demoable Artifact**: See real-time sync progress bar and notifications in browser

### Task 7.1: Create SyncStatusContext (React state management)
**Time**: 2-3 hours | **Commit**: `feat: add SyncStatusContext for state management`

**Description**: Create React Context to share sync status across components

**Acceptance Criteria**:
- [ ] `frontend/src/contexts/SyncStatusContext.tsx`:
  ```typescript
  interface SyncStatus {
    status: 'idle' | 'syncing' | 'completed' | 'error'
    total: number
    processed: number
    failed: number
    speed: number
    message: string
  }

  export const SyncStatusContext = createContext<SyncStatus | null>(null)
  export const SyncStatusProvider: React.FC = ({children}) => {...}
  ```
- [ ] Provider logic:
  - Maintain sync status state
  - Connect to WebSocket on mount
  - Update state on messages
  - Disconnect on unmount
- [ ] Hook for consumption:
  ```typescript
  export const useSyncStatus = () => useContext(SyncStatusContext)
  ```

**Testing**:
- Unit test: Context provides correct initial state
- Unit test: State updates correctly on WebSocket messages
- Integration test: Components can consume sync status

---

### Task 7.2: Build SyncStatus notification component
**Time**: 3-4 hours | **Commit**: `feat: add SyncStatus display component`

**Description**: Display sync progress bar, status badge, and notifications

**Acceptance Criteria**:
- [ ] `frontend/src/components/SyncStatus.tsx`:
  - Progress bar: shows processed/total
  - Status badge: "Idle", "Syncing", "Completed", "Error"
  - Sync stats: "50/100 videos, 2 errors, 12.5 videos/sec"
  - Elapsed time: "4:23 elapsed"
  - Error display: show last error if sync failed
- [ ] Visual states:
  - Idle: gray badge, no progress bar
  - Syncing: blue badge, animated progress bar
  - Completed: green badge, filled progress bar
  - Error: red badge, error message
- [ ] Responsive:
  - Mobile: compact version
  - Desktop: full stats
  - Tooltip: detailed stats on hover
- [ ] Accessible:
  - ARIA labels for progress bar
  - Keyboard navigation
  - High contrast colors

**Testing**:
- Unit test: Component renders with sync status
- Unit test: Progress bar updates correctly
- Integration test: Component consumes SyncStatusContext
- Visual: Manual testing on mobile/desktop

---

### Task 7.3: Implement real-time WebSocket connection
**Time**: 3-4 hours | **Commit**: `feat: connect frontend to WebSocket sync status`

**Description**: Connect React app to WebSocket endpoint

**Acceptance Criteria**:
- [ ] `frontend/src/services/syncWebSocket.ts`:
  ```typescript
  class SyncWebSocket {
      connect(wsUrl: string): Promise<void>
      onMessage(callback: (msg: any) => void): void
      disconnect(): void
      isConnected(): boolean
  }
  ```
- [ ] Connection logic:
  - Connect on app load
  - Handle disconnects and reconnect
  - Exponential backoff on reconnect
  - Max 10 reconnect attempts
- [ ] Message handling:
  - Parse WebSocket messages
  - Update SyncStatusContext
  - Handle errors and invalid messages
- [ ] Automatic connection:
  - Connect on app mount
  - Disconnect on app unmount
  - Reconnect if dropped
- [ ] Configuration:
  - WebSocket URL from environment
  - Timeout configurable (30s default)
  - Max reconnect attempts configurable

**Testing**:
- Unit test: Connect to mock WebSocket
- Unit test: Parse and handle messages
- Unit test: Reconnect on disconnect
- Integration test: Real server WebSocket connection

---

### Task 7.4: Add sync notification component
**Time**: 2-3 hours | **Commit**: `feat: add sync notifications (toast/snackbar)`

**Description**: Toast notifications for sync events

**Acceptance Criteria**:
- [ ] `frontend/src/components/SyncNotification.tsx`:
  - Show toast on sync started: "Syncing 50 videos..."
  - Show progress toast: "25/50 synced (50%)"
  - Show success toast: "✓ Synced 50 videos in 4.5s"
  - Show error toast: "✗ Sync failed: Network error"
- [ ] Notification behavior:
  - Auto-dismiss success after 3s
  - Auto-dismiss error after 8s
  - Clickable to dismiss early
  - Stack multiple notifications
  - Accessible (ARIA live region)

**Testing**:
- Unit test: Notifications render correctly
- Unit test: Auto-dismiss works
- Integration test: Notifications appear on sync events

---

### Task 7.5: Integrate SyncStatus into Journey page
**Time**: 2-3 hours | **Commit**: `feat: add sync status to Journey page`

**Description**: Show sync status alongside journey data

**Acceptance Criteria**:
- [ ] Journey page (`frontend/src/pages/Journey.tsx`):
  - Add SyncStatus component at top
  - Refresh Journey data on sync completion
  - Show "Last synced: 5 min ago"
  - Show "Pending syncs: 3 videos"
- [ ] Refresh on sync complete:
  - Call API to get updated journey data
  - Show new milestones
  - Update phase analysis
- [ ] Integration points:
  - Import SyncStatusContext
  - Watch for `sync_completed` message
  - Refetch journey data
  - Show new milestones in timeline

**Testing**:
- Unit test: Component renders with sync status
- Integration test: Journey data refreshes on sync completion
- Manual: See real-time updates in Journey UI

---

### Task 7.6: Add real-time milestone notifications
**Time**: 2-3 hours | **Commit**: `feat: notify on new milestones`

**Description**: Show toast when new milestone is detected

**Acceptance Criteria**:
- [ ] WebSocket message for new milestones:
  ```json
  {
    "type": "new_milestones",
    "milestones": [
      {
        "type": "breakthrough",
        "description": "Nailed 101B after 5 failures!",
        "phase_insight": "Both phases perfect..."
      }
    ]
  }
  ```
- [ ] Notification UI:
  - Toast: "🎉 Breakthrough! Nailed 101B after 5 failures"
  - Shows phase_insight if available
  - Click to view full milestone in Journey
  - Sound notification (optional, toggle in settings)
- [ ] Auto-update Journey page:
  - Add milestone to timeline immediately
  - Show phase coaching if available

**Testing**:
- Unit test: Milestone notification renders correctly
- Integration test: WebSocket message triggers notification
- Manual: See notification when syncing produces milestone

---

### Task 7.7: Implement error handling and retry UI
**Time**: 2-3 hours | **Commit**: `feat: add sync error handling and retry`

**Description**: Handle sync errors gracefully, allow manual retry

**Acceptance Criteria**:
- [ ] Error handling:
  - Show error toast: "Sync failed: Network error"
  - Show error detail: "Connection timeout after 30s"
  - Show retry button: "Retry Now"
  - Show manual sync button: "Sync Now"
- [ ] Retry logic:
  - Click "Retry Now" → manually trigger sync
  - Wait for WebSocket to show status
  - Show new notification on success/failure
- [ ] Manual sync:
  - Button to manually request sync from server
  - POST to `/api/v1/videos/sync-now` (if implemented)
  - Or show queue status: "X videos queued"

**Testing**:
- Unit test: Error messages display correctly
- Integration test: Manual retry works
- Manual: Test error scenarios

---

### Task 7.8: Add accessibility and responsive design
**Time**: 2-3 hours | **Commit**: `feat: improve sync UI accessibility and responsiveness`

**Description**: Ensure sync status accessible on all devices and screen readers

**Acceptance Criteria**:
- [ ] Accessibility:
  - Progress bar has ARIA label: "Sync progress: 25 of 50"
  - Live region for status updates: aria-live="polite"
  - Keyboard navigation: Tab through all controls
  - Color not sole indicator (text + icon)
  - Sufficient contrast ratio (4.5:1 minimum)
- [ ] Responsive:
  - Mobile: Compact progress bar, no detailed stats
  - Tablet: Medium layout with key stats
  - Desktop: Full stats with tooltips
  - Notifications: Adapted for small screens
- [ ] Testing:
  - Axe accessibility audit
  - Keyboard navigation testing
  - Screen reader testing
  - Visual testing on mobile/tablet/desktop

**Testing**:
- Accessibility: axe audit, keyboard nav, screen reader
- Responsive: visual testing on different screen sizes
- Manual: Test on actual devices

---

**Sprint 7 Complete**: Real-time sync status UI, WebSocket integrated, notifications for sync events and milestones, accessible and responsive

---

## Sprint 8: Integration Testing & Deployment (5 days)

**Goal**: Full end-to-end testing, gradual rollout to production, deployment to 192.168.1.57

**Demoable Artifact**: Complete working system: Photos → Mac agent → Server → Database → Journey UI

### Task 8.1: End-to-end test: Photos → Milestone → UI
**Time**: 4-5 hours | **Commit**: `test: add complete E2E test scenario`

**Description**: Test full flow from Photos library to UI milestone display

**Acceptance Criteria**:
- [ ] Test flow:
  1. Add test video to Photos with caption "101B G/P 5m"
  2. Mac agent extracts metadata
  3. Mac agent POSTs to server
  4. Server stores dive
  5. Server detects milestone (if applicable)
  6. WebSocket broadcasts update
  7. Frontend receives and displays
  8. Verify in Journey UI: new dive visible, phase data shown
- [ ] Test duration: full flow should complete in <30 seconds
- [ ] Can run: `pytest tests/test_e2e.py -v`
- [ ] Should pass consistently (no flakiness)

**Testing**:
- E2E test: 5+ complete scenarios
- Flakiness testing: Run 10 times, verify passes every time
- Performance: Measure end-to-end latency

---

### Task 8.2: Load testing with realistic data
**Time**: 3-4 hours | **Commit**: `test: add load testing with realistic workload`

**Description**: Test system with realistic data volumes and patterns

**Acceptance Criteria**:
- [ ] Load test scenario:
  - Simulate 100 dives per day (realistic rate)
  - Run for 1 week simulated time (700 dives)
  - Sync in batches of 50 (realistic)
  - Mix of legacy and two-phase dives
  - Parallel: 5 WebSocket clients monitoring
- [ ] Metrics:
  - Sync throughput: videos/second
  - API latency: p50, p95, p99
  - Database query performance
  - Memory usage (steady state)
  - WebSocket message latency
- [ ] Acceptable performance:
  - Sync throughput: >50 videos/sec
  - API latency p99: <500ms
  - Memory: <500MB
  - WebSocket latency p99: <100ms
- [ ] Can run: `pytest tests/test_load.py`

**Testing**:
- Load test: 700 dives, measure metrics
- Identify bottlenecks if needed

---

### Task 8.3: Data integrity and consistency testing
**Time**: 3-4 hours | **Commit**: `test: verify data integrity across operations`

**Description**: Ensure no data loss, corruption, or inconsistency

**Acceptance Criteria**:
- [ ] Test scenarios:
  - Sync 1000 dives, verify all in database
  - Sync same dive twice (UUID), verify no duplicates
  - Sync batch, kill server mid-way, resume → no data loss
  - Mixed legacy + two-phase dives: both work
  - Verify dive count matches sync reports
  - Verify audit log accuracy
- [ ] Consistency checks:
  - Dive UUID unique across database
  - Foreign key constraints enforced
  - Timestamps are consistent
  - Phase data only present for two-phase dives
- [ ] Recovery testing:
  - Database backup and restore
  - Verify data intact after restore
  - Offline queue recovery

**Testing**:
- Data integrity test: 10+ scenarios
- Consistency validation queries
- Recovery simulation

---

### Task 8.4: Disaster recovery and rollback procedures
**Time**: 2-3 hours | **Commit**: `docs: add disaster recovery procedures`

**Description**: Document and test rollback/recovery procedures

**Acceptance Criteria**:
- [ ] Procedures documented:
  - Database backup: `make db-backup`
  - Database restore: `make db-restore`
  - Rollback to previous version: `make rollback`
  - Reset to clean state: `make clean-slate`
- [ ] Tested procedures:
  - Backup captures all data
  - Restore from backup works
  - Rollback restores previous state
  - Clean slate removes all data
- [ ] Runbooks:
  - Sync failures recovery
  - Server down scenarios
  - Database issues
  - Network issues
- [ ] Time to recover: <5 minutes for most scenarios

**Testing**:
- Manual: Run each recovery procedure
- Verify: Data integrity after recovery

---

### Task 8.5: Security hardening and validation
**Time**: 3-4 hours | **Commit**: `test: add security validation tests`

**Description**: Verify API security, authentication, rate limiting

**Acceptance Criteria**:
- [ ] Security tests:
  - Missing API key: rejected (401)
  - Invalid API key: rejected (401)
  - Expired API key: rejected (401)
  - Rate limiting: enforced (429 after limit)
  - SQL injection attempts: rejected
  - XSS attempts in captions: sanitized/escaped
  - CSRF protection: headers verified
- [ ] API key security:
  - Keys hashed in database
  - Can't leak plaintext
  - Can rotate without downtime
  - Can revoke immediately
- [ ] HTTPS:
  - All traffic encrypted (TLS)
  - Certificate valid
  - No insecure fallback
- [ ] Logging:
  - Auth attempts logged
  - Security events tracked
  - No sensitive data in logs

**Testing**:
- Security test: 20+ attack scenarios
- Penetration testing (basic): SQL injection, XSS, auth bypass
- Manual review of auth/crypto code

---

### Task 8.6: Documentation completeness
**Time**: 2-3 hours | **Commit**: `docs: complete system documentation`

**Description**: Ensure all documentation is current and complete

**Acceptance Criteria**:
- [ ] Documentation files:
  - `README.md` - Project overview
  - `INSTALLATION.md` - Setup instructions
  - `ARCHITECTURE.md` - System design
  - `API_REFERENCE.md` - API endpoints + examples
  - `DEPLOYMENT_GUIDE.md` - Production deployment
  - `TROUBLESHOOTING.md` - Common issues
  - `CONTRIBUTING.md` - Development guidelines
  - `SECURITY.md` - Security considerations
- [ ] Each document:
  - Current (no outdated info)
  - Complete (covers all major features)
  - Has examples (working curl/code examples)
  - Tested (examples run successfully)
- [ ] Generated docs:
  - API Swagger at `/docs` (auto-generated)
  - Architecture diagrams (SVG or PNG)

**Testing**:
- Manual: Read all docs, verify accuracy
- Manual: Run all example commands, verify they work
- Check: Links in docs are valid

---

### Task 8.7: Feature flag and canary deployment setup
**Time**: 2-3 hours | **Commit**: `feat: add feature flags for gradual rollout`

**Description**: Setup infrastructure for gradual rollout

**Acceptance Criteria**:
- [ ] Feature flags:
  - `enable_mac_agent_sync` - gates all sync endpoints
  - `enable_phase_aware_coaching` - gates new phase features
  - Per-agent: can enable for specific agents first
- [ ] Canary deployment:
  - Deploy to canary environment first
  - Monitor for errors
  - Gradually shift traffic (10% → 50% → 100%)
  - Can rollback if issues detected
- [ ] Monitoring:
  - Error rate tracking
  - Performance metrics
  - WebSocket connection health
  - Database query performance

**Testing**:
- Manual: Test feature flag toggling
- Manual: Simulate canary deployment
- Manual: Simulate rollback

---

### Task 8.8: Gradual rollout plan execution
**Time**: 3-4 hours | **Commit**: `docs: execute gradual rollout to production`

**Description**: Implement phased rollout to 192.168.1.57

**Acceptance Criteria**:
- [ ] Phase 1 (Week 1): Canary
  - Deploy to test server (192.168.1.57)
  - Run integration tests
  - Manual testing with real Photos library
  - Monitor for errors
  - Enable sync endpoints (disabled by default)
- [ ] Phase 2 (Week 2): Limited rollout
  - Deploy to production
  - Enable sync for test agent only
  - Monitor for 2+ days
  - Gradually enable more agents
- [ ] Phase 3 (Week 3): Full rollout
  - Enable sync for all agents
  - Monitor closely
  - Have rollback plan ready
  - Can revert to previous version in <5 min
- [ ] Rollout status:
  - Tracked in deployment log
  - Visible in monitoring dashboard
  - Can be paused/resumed

**Testing**:
- Manual: Execute each phase
- Verify: Monitoring shows all systems healthy
- Test: Rollback procedures work

---

### Task 8.9: Monitoring and alerting setup
**Time**: 2-3 hours | **Commit**: `devops: add monitoring and alerting`

**Description**: Setup monitoring dashboard and alerts

**Acceptance Criteria**:
- [ ] Monitoring dashboard shows:
  - System health: green/yellow/red
  - Sync status: success/fail rate
  - API response times: p50, p95, p99
  - Database performance: query times, connections
  - WebSocket connections: count, latency
  - Error rate: by endpoint
  - Resource usage: CPU, memory, disk
- [ ] Alerts trigger on:
  - Error rate >5%
  - API latency p99 >1s
  - WebSocket disconnections >10%
  - Database unavailable
  - Low disk space (<10GB remaining)
  - High memory usage (>80%)
- [ ] Alert delivery:
  - Email
  - Slack (if configured)
  - Dashboard notification
  - Log entries
- [ ] Can view dashboard at: `http://192.168.1.57:3001/monitoring`

**Testing**:
- Manual: Trigger each alert condition
- Verify: Alert delivered correctly
- Verify: Can acknowledge and resolve alerts

---

### Task 8.10: Production deployment to 192.168.1.57
**Time**: 3-4 hours | **Commit**: `deploy: production deployment to server`

**Description**: Deploy complete system to production server

**Acceptance Criteria**:
- [ ] Deployment steps:
  1. Backup current database
  2. Pull latest code from git
  3. Run database migrations
  4. Build Docker images
  5. Start services (docker-compose up)
  6. Run smoke tests
  7. Enable feature flags gradually
  8. Monitor for errors
  9. Rollback if needed
- [ ] Pre-deployment:
  - All tests pass
  - Documentation reviewed
  - Deployment plan documented
  - Team notified of deployment
- [ ] Post-deployment:
  - Verify all endpoints accessible
  - Check database tables exist
  - Verify WebSocket connection works
  - Monitor error rates
  - Collect feedback
- [ ] Can access:
  - API: https://192.168.1.57:8000/docs
  - Frontend: https://192.168.1.57:3001/
  - Status: https://192.168.1.57:3001/monitoring

**Testing**:
- Manual: Deploy to production
- Smoke test: All endpoints work
- Verify: WebSocket connects
- Verify: Journey page loads

---

### Task 8.11: Post-deployment validation and monitoring
**Time**: 2-3 hours | **Commit**: `ops: validate production deployment`

**Description**: Verify production system is working correctly

**Acceptance Criteria**:
- [ ] Validation checks (running for 24 hours):
  - Zero critical errors
  - Error rate <1%
  - API latency acceptable (p99 <500ms)
  - WebSocket connections stable
  - Database performance normal
  - No memory leaks
  - Disk usage stable
- [ ] User-facing:
  - Can sync from any Mac agent
  - Videos appear in database
  - Milestones detected correctly
  - Journey UI updates real-time
  - Notifications show on sync
- [ ] Issues resolution:
  - Any errors logged and investigated
  - Hotfixes deployed if critical
  - Post-mortems on any failures
- [ ] Documentation:
  - Update deployment guide with lessons learned
  - Document any known issues
  - Update troubleshooting guide

**Testing**:
- Manual: Monitor for 24 hours
- Verify: All systems healthy
- Collect: User feedback

---

### Task 8.12: Handoff and team documentation
**Time**: 1-2 hours | **Commit**: `docs: add team handoff documentation`

**Description**: Document system for future maintenance

**Acceptance Criteria**:
- [ ] Documentation:
  - How to add new features
  - How to debug issues
  - How to scale system
  - Common maintenance tasks
  - How to respond to alerts
  - How to rollback version
  - How to backup/restore
- [ ] Runbooks:
  - Database is down
  - API is down
  - WebSocket not connecting
  - Sync not working
  - Need to rotate API keys
  - Need to add new agent
- [ ] Contact information:
  - Who to contact for issues
  - On-call schedule
  - Escalation procedures
- [ ] Architecture summary:
  - Why decisions were made
  - Trade-offs considered
  - Future improvements planned

**Testing**:
- Manual: Follow runbooks, they work
- Verify: Team understands documentation

---

**Sprint 8 Complete**: Fully tested, secured, and deployed production system, running smoothly with monitoring and alerting

---

## Task Dependencies & Critical Path

### Critical Dependencies
```
Sprint 0 BLOCKS: All other sprints
├─ Database schema
└─ Test infrastructure

Sprint 1 PARALLEL with Sprint 4
├─ Mac photo parsing
└─ Server endpoints

Sprint 2 PARALLEL with Sprint 5
├─ Mac sync client
└─ Server journey integration

Sprint 3 SEQUENTIAL after Sprint 2
├─ LaunchAgent packaging
└─ Mac agent deployment

Sprint 6 PARALLEL with Sprint 7
├─ Server WebSocket
└─ Frontend UI (can mock WebSocket)

Sprint 7 DEPENDS ON Sprint 6
└─ Real-time UI sync status

Sprint 8 SEQUENTIAL after all
└─ Full E2E testing + production deployment
```

### Parallelization Opportunity
- Sprints can run in parallel:
  - Sprint 1 + 4 (2 weeks)
  - Sprint 2 + 5 (2 weeks)
  - Sprint 3 (1 week)
  - Sprint 6 (2 weeks, overlaps with 7)
  - Sprint 7 (1 week)
  - Sprint 8 (1 week)
  - **Total: 3-4 weeks instead of 8 weeks**

---

## Testing Summary

### Unit Tests (Per Sprint)
- Sprint 0: 30 tests (pytest infrastructure)
- Sprint 1: 50 tests (caption parsing, photo querying)
- Sprint 2: 40 tests (sync client, retry logic)
- Sprint 3: 15 tests (config validation, logging)
- Sprint 4: 50 tests (endpoints, validation)
- Sprint 5: 20 tests (milestone detection)
- Sprint 6: 30 tests (WebSocket, state)
- Sprint 7: 25 tests (React components, state)
- Sprint 8: 100+ tests (E2E, load, security)
- **Total: 360+ unit tests**

### Integration Tests (Per Sprint)
- Each sprint includes 5-10 integration tests
- Cover component interaction
- Mock external dependencies

### End-to-End Tests (Sprint 8)
- 5+ complete flow scenarios
- Photos → UI
- Realistic data volumes
- Failure scenarios

---

## Task Completion Checklist Template

Each task should have:
- [ ] Code written
- [ ] Tests written & passing
- [ ] Code reviewed
- [ ] PR merged
- [ ] Documentation updated
- [ ] Ready for demo

---

**Total Tasks: 53 across 8 sprints**
**Estimated Timeline: 3-4 weeks with parallelization**
**Total Test Cases: 360+ unit + integration + E2E**
