# API Reference

Complete API documentation for Diving Analytics Platform.

---

## Base URL

```
Production: http://192.168.1.57:6090/api/v1
Development: http://localhost:6002/api/v1
```

---

## Authentication

**Mac Agent Endpoints** (`/videos/*`):
```http
X-API-Key: your-api-key-here
```

**Frontend Endpoints**: No authentication required (internal network)

---

## Endpoints

### Dives

#### GET /dives
Get all dives with pagination.

**Query Parameters:**
- `skip` (int): Offset for pagination (default: 0)
- `limit` (int): Number of results (default: 100, max: 1000)
- `dive_code` (string): Filter by dive code (e.g., "101B")
- `performance` (string): Filter by performance (F/B/M/G/P)
- `height` (string): Filter by height (1m, 3m, 5m, 7m, 10m)

**Response:**
```json
[
  {
    "id": 1,
    "dive_code": "101B",
    "performance": "G",
    "phase1_performance": "G",
    "phase2_performance": "P",
    "height": "5m",
    "dive_date": "2026-01-31T14:30:00Z",
    "session_id": 42
  }
]
```

#### GET /dives/{id}
Get single dive by ID.

#### GET /dives/recent
Get recent dives (sorted by date DESC).

### Sessions

#### GET /sessions
Get all sessions.

**Response:**
```json
[
  {
    "id": 1,
    "date": "2026-01-31",
    "dive_count": 25,
    "avg_performance": 2.4,
    "dives": [...]
  }
]
```

### Analytics

#### GET /analytics/overall
Overall performance statistics.

**Response:**
```json
{
  "total_dives": 1721,
  "avg_performance": 2.11,
  "success_rate": 0.77,
  "perfect_rate": 0.059,
  "consistency": 0.82
}
```

### Journey

#### GET /journey/milestones
Get milestone timeline.

**Response:**
```json
[
  {
    "id": 1,
    "type": "breakthrough",
    "dive_code": "201C",
    "message": "First success after 5 failures!",
    "phase_insight": "Good flight, Perfect entry",
    "date": "2026-01-15T14:30:00Z"
  }
]
```

#### GET /journey/phase-analysis
Two-phase coaching analysis.

**Response:**
```json
{
  "summary": {
    "total_dives": 1721,
    "two_phase_dives": 115,
    "legacy_dives": 1606
  },
  "phase1_analysis": {
    "label": "Hurdle + Flight (Takeoff)",
    "average": 2.53,
    "distribution": {"P": 9, "G": 53, "M": 45, "B": 6, "F": 2}
  },
  "phase2_analysis": {
    "label": "Opening + Entry (Landing)",
    "average": 2.35,
    "distribution": {"P": 13, "G": 37, "M": 44, "B": 19, "F": 2}
  }
}
```

### Video Sync (Mac Agent)

#### POST /videos/sync
Sync single dive from Mac agent.

**Request:**
```json
{
  "dive_code": "101B",
  "phase1_performance": "G",
  "phase2_performance": "P",
  "height": "5m",
  "video_uuid": "ABC-123",
  "dive_date": "2026-02-01T14:30:00Z",
  "is_sync": false,
  "is_smack": false
}
```

**Response:**
```json
{
  "status": "success",
  "dive_id": 1722,
  "milestones_detected": [...]
}
```

#### POST /videos/batch
Batch sync multiple dives.

**Request:**
```json
{
  "dives": [
    { "dive_code": "101B", ... },
    { "dive_code": "201C", ... }
  ]
}
```

---

## WebSocket

**Endpoint:** `ws://SERVER_IP:6090/api/v1/ws`

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
    "message": "First success after 5 failures!",
    "phase_insight": "Good flight, Perfect entry"
  }
}
```

---

## Error Codes

| Code | Meaning |
|------|---------|
| 200 | Success |
| 201 | Created |
| 400 | Bad Request (validation error) |
| 401 | Unauthorized (invalid API key) |
| 404 | Not Found |
| 500 | Internal Server Error |

---

## Rate Limiting

- **Mac Agent**: 100 requests/minute
- **Frontend**: Unlimited (internal network)

See [ARCHITECTURE.md](ARCHITECTURE.md) for detailed API design decisions.
