# Sprint 6 - WebSocket Real-Time Updates

**Goal**: Add real-time WebSocket support for live sync status updates to connected clients

**Status**: Starting
**Sprint Duration**: Single session
**Tasks**: 44-50 (7 tasks)

## Architecture Vision

```
Mac-Agent (Sprints 1-3)
    ↓ [Video Sync Request]
    ├─ Create Dive
    ├─ Generate Insights
    └─ Emit WebSocket events
         ↓
Server WebSocket Hub (Sprint 6)
    ├─ Receive sync events
    ├─ Track active syncs
    ├─ Broadcast status updates
    └─ Manage client connections
         ↓
Connected Clients
    ├─ Web Dashboard (React)
    ├─ Mobile App
    ├─ Mac-Agent Status Monitor
    └─ Analytics Dashboard
         ↓
Real-time Updates
    ├─ Sync in progress
    ├─ Dive created
    ├─ Milestone detected
    └─ Error occurred
```

## Tasks

### Task 44: Implement WebSocket endpoint for sync status
**Objective**: Create WebSocket endpoint for real-time sync status

**Changes Required**:
- Create `/ws/sync` WebSocket endpoint
- Handle client connections/disconnections
- Broadcast sync events to connected clients
- Event types: SYNC_STARTED, SYNC_PROGRESS, SYNC_COMPLETE, ERROR
- Per-session status tracking

**Acceptance Criteria**:
- WebSocket endpoint accepts connections
- Clients receive events in real-time
- Handles concurrent connections
- Graceful disconnection handling

### Task 45: Build SyncStatusTracker service
**Objective**: Track and manage sync operations

**Changes Required**:
- Create SyncStatusTracker class
- Track active syncs per mac-agent
- Track progress (x/y dives synced)
- Store error information
- Automatic cleanup of completed syncs

**Acceptance Criteria**:
- Track 100+ concurrent syncs
- Real-time progress updates
- Error tracking and reporting
- Automatic cleanup

### Task 46: Implement status message broadcasting
**Objective**: Emit events to WebSocket clients

**Changes Required**:
- Create WebSocketManager for event broadcasting
- Emit SYNC_STARTED when sync begins
- Emit PROGRESS every N dives
- Emit SYNC_COMPLETE when done
- Emit ERROR on failures
- Broadcast to all connected clients or filtered by client_id

**Acceptance Criteria**:
- All clients receive events
- Events include relevant data (progress, errors, etc.)
- Broadcast latency <100ms
- No event loss

### Task 47: Add connection lifecycle management
**Objective**: Manage client connections properly

**Changes Required**:
- Track connected clients
- Handle client reconnections
- Send client_id on connect
- Heartbeat to detect stale connections
- Graceful cleanup on disconnect

**Acceptance Criteria**:
- 100+ concurrent connections supported
- Heartbeat detects stale connections
- Automatic cleanup after disconnect
- Client reconnection supported

### Task 48: Write WebSocket client library for testing
**Objective**: Create Python client for WebSocket testing

**Changes Required**:
- Create websockets-based client library
- Handle connection/reconnection
- Send and receive messages
- Event handling with callbacks
- Error handling and retries

**Acceptance Criteria**:
- Can connect to server
- Can receive events
- Can send heartbeats
- Handles reconnections

### Task 49: Write multi-client WebSocket tests
**Objective**: Test concurrent WebSocket connections

**Test Coverage**:
- Single client connection
- Multiple clients (10, 50, 100)
- Event broadcasting to all clients
- Selective broadcast to client_id
- Disconnection handling
- Reconnection after temporary loss
- Event ordering and sequencing
- Error event propagation

**Acceptance Criteria**:
- 15+ test cases
- All passing
- 100+ concurrent client support validated

### Task 50: Performance test WebSocket (100+ concurrent)
**Objective**: Validate WebSocket performance at scale

**Test Coverage**:
- 100 concurrent clients
- Event broadcast latency
- Memory usage with connections
- CPU usage during broadcast
- Connection establishment time
- Disconnection handling performance

**Performance Targets**:
- Connection time: <100ms
- Broadcast latency: <50ms to all clients
- Memory: <1MB per client
- 1000 events/sec throughput

## Implementation Order

1. **Task 44**: WebSocket endpoint (foundation)
2. **Task 45**: SyncStatusTracker (state management)
3. **Task 46**: Broadcasting (event distribution)
4. **Task 47**: Connection management (lifecycle)
5. **Task 48**: Client library (testing tools)
6. **Task 49**: Integration tests (validation)
7. **Task 50**: Performance tests (scalability)

## Success Criteria

✅ WebSocket endpoint fully operational
✅ Real-time sync status streaming
✅ 100+ concurrent clients supported
✅ Event broadcast <50ms latency
✅ All tests passing
✅ 15+ integration tests
✅ Production-ready code

## Key Features

- Real-time sync progress updates
- Multi-client concurrent support
- Event-based architecture
- Graceful error handling
- Automatic connection cleanup
- Heartbeat monitoring
- Client identification

## Integration Points

1. **Sync endpoints** (Task 46)
   - Emit SYNC_STARTED
   - Emit PROGRESS every N dives
   - Emit SYNC_COMPLETE

2. **Journey Service** (Task 46)
   - Emit MILESTONE_DETECTED
   - Emit COACHING_INSIGHT_GENERATED

3. **Database** (Task 45)
   - Store active syncs
   - Track client connections

## Technical Stack

- **WebSocket Library**: FastAPI WebSockets + websockets
- **State Management**: In-memory with optional Redis for horizontal scaling
- **Testing**: pytest-asyncio + pytest-websockets
- **Client Library**: Python websockets client
- **Error Handling**: Graceful degradation, automatic reconnection

## Notes

- Initial implementation in-memory (single server)
- Can be extended with Redis for multi-server deployment
- Heartbeat every 30s to detect stale connections
- Progress updates every 50 dives to reduce event volume
- Support both broadcast and targeted messaging
