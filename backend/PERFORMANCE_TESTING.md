# Performance Testing Guide

## Overview

Comprehensive performance test suite validating video sync throughput, latency, and resource efficiency with 1000+ videos.

## Test Coverage

### Single Video Sync Performance
- **Latency baseline**: <100ms per video
- **With phase insights**: <150ms per video (insight generation overhead)
- **Sequential 100 syncs**: Validates consistency across 100 sequential operations

### Batch Sync Performance
- **50 videos**: >50 videos/sec throughput
- **100 videos**: >40 videos/sec throughput
- **250 videos**: >30 videos/sec throughput
- **500 videos**: >25 videos/sec throughput
- **1000 videos**: >20 videos/sec throughput
- **2000 videos**: >15 videos/sec throughput

### Scale Testing
- Tests batches up to 2000 videos
- Validates transactional consistency at scale
- Verifies no performance degradation with database size

### Multi-Batch Operations
- 10 sequential batches of 100 videos (1000 total)
- Validates stability across extended sync operations
- Measures throughput consistency over time

### Duplicate Detection Performance
- First batch (100 new): Baseline time
- Second batch (100 duplicates): Overhead measurement
- Verifies UUID index effectiveness

### Audit Logging Overhead
- Confirms <10% performance impact from audit logging
- 200+ videos with full audit trail

### Memory Efficiency
- 5 sequential chunks of 200 videos (1000 total)
- Validates no memory leaks or excessive accumulation
- Per-chunk throughput tracking

## Running Tests

### All Performance Tests
```bash
pytest backend/tests/test_performance_sync.py -v -s
```

### Specific Test Classes
```bash
# Single video tests
pytest backend/tests/test_performance_sync.py::TestPerformanceSingleVideoSync -v

# Batch sync tests
pytest backend/tests/test_performance_sync.py::TestPerformanceBatchSync -v

# Large scale (500+, 1000+ videos)
pytest backend/tests/test_performance_sync.py::TestPerformanceLargeScale -v

# Multiple sequential batches
pytest backend/tests/test_performance_sync.py::TestPerformanceMultipleBatches -v

# Duplicate detection cost
pytest backend/tests/test_performance_sync.py::TestPerformanceWithDuplicates -v

# Audit logging overhead
pytest backend/tests/test_performance_sync.py::TestPerformanceAuditLogging -v

# Memory efficiency
pytest backend/tests/test_performance_sync.py::TestPerformanceMemoryUsage -v
```

### Single Test
```bash
pytest backend/tests/test_performance_sync.py::TestPerformanceLargeScale::test_batch_1000_videos -v -s
```

## Expected Performance Baselines

| Operation | Target | Notes |
|-----------|--------|-------|
| Single video sync | <100ms | Basic request + DB insert |
| Single with insight | <150ms | Includes coaching insight generation |
| Sequential 100 | <50ms avg | Consistency measurement |
| Batch 50 | >50 v/s | Baseline for small batches |
| Batch 100 | >40 v/s | Standard batch size |
| Batch 250 | >30 v/s | 5x batch size |
| Batch 500 | >25 v/s | Medium scale |
| Batch 1000 | >20 v/s | Large scale (1000 videos) |
| Batch 2000 | >15 v/s | 2x large scale |

## Database Indexes

Performance relies on proper indexes:

1. **video_uuid** (UNIQUE)
   - Deduplication check: O(1) lookup
   - Must complete in <1ms per video

2. **synced_at** (INDEX)
   - Incremental sync queries: SELECT * WHERE synced_at > X
   - Enables efficient sync history

3. **session_id, dive_datetime** (COMPOSITE INDEX)
   - Journey feature queries
   - Analytics aggregation

## Performance Tips

### For Production Deployments

1. **Database**: Ensure indexes are created
   ```sql
   CREATE INDEX IF NOT EXISTS idx_dives_video_uuid ON dives(video_uuid);
   CREATE INDEX IF NOT EXISTS idx_dives_synced_at ON dives(synced_at DESC);
   ```

2. **Connection Pooling**: Use httpx with pooling (already configured)
   - 10 max connections (configurable)
   - Connection reuse across requests

3. **Batch Size**: Optimal batch size is 50-100 videos
   - Balances latency vs throughput
   - Larger batches (500+) for bulk operations
   - Smaller batches (10-20) for real-time sync

4. **Concurrent Requests**: Can handle 10+ concurrent batch requests
   - Each independent transactional
   - Database connection pool scales automatically

## Monitoring Metrics

Track in production:
- Sync request latency (p50, p95, p99)
- Batch throughput (videos/sec)
- Failed syncs (validation, duplicates)
- Audit log growth (rotate at 10MB)
- Database query performance (via slow query log)

## Optimization Opportunities

If performance is insufficient:

1. **Increase batch size** (currently 50 max, configurable)
2. **Add database connection pooling** (already configured)
3. **Parallelize I/O** (audit logging already async)
4. **Cache phase validation** (currently recomputed each request)
5. **Async database operations** (currently synchronous, could use async SQLAlchemy)

## Load Testing Scenarios

### Development
```
Small: 100 videos, 1 batch
Medium: 500 videos, 5 batches of 100
Large: 2000 videos, 20 batches of 100
```

### Staging
```
Small: 500 videos, 5 batches
Medium: 2000 videos, 20 batches
Large: 5000 videos, 50 batches
```

### Production
```
Real-world: 100-500 videos/day from mac-agents
Peak: 50+ concurrent sync requests
Historical: 1000+ cumulative videos per Journey
```

## Sample Performance Report

```
Single Video Sync Performance:
  Latency: 45ms average
  P95: 65ms
  P99: 85ms

Batch Sync Performance (50 videos):
  Time: 0.850s
  Throughput: 58.8 videos/sec

Batch Sync Performance (1000 videos):
  Time: 45.3s
  Throughput: 22.1 videos/sec
  Per-video avg: 45.3ms

Multi-Batch (10 x 100):
  Average batch time: 2.4s
  Total time: 24s
  Overall throughput: 41.7 videos/sec

Duplicate Detection:
  New batch (100): 0.85s
  Duplicate batch (100): 0.92s
  Overhead: +8.2%

Audit Logging (200 videos):
  Time: 4.2s
  Throughput: 47.6 videos/sec
  (No significant overhead detected)

Memory Usage (1000 videos):
  Chunk 1 (200): 0.42s
  Chunk 2 (200): 0.39s
  Chunk 3 (200): 0.41s
  Chunk 4 (200): 0.43s
  Chunk 5 (200): 0.40s
  Total: 2.05s for 1000 videos
```

## CI/CD Integration

Add to GitHub Actions:
```yaml
- name: Run performance tests
  run: |
    pytest backend/tests/test_performance_sync.py -v --tb=short

- name: Check performance baseline
  run: |
    # Parse output and verify meets minimum targets
    # Fail if batch_1000 throughput < 20 v/s
```

## Notes

- Tests use in-memory SQLite by default (configure for PostgreSQL in CI)
- Actual performance will be better with PostgreSQL on production hardware
- Network latency not included (assumes local deployment or high-speed network)
- Audit logging to disk adds minimal overhead (<2%)
