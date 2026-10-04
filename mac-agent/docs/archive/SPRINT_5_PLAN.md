# Sprint 5 - Journey Integration & Milestone Detection

**Goal**: Connect video sync pipeline to Journey feature for automatic milestone detection and analytics updates

**Status**: Starting
**Sprint Duration**: Single session
**Tasks**: 38-43 (6 tasks)

## Tasks

### Task 38: Integrate video sync with JourneyService
**Objective**: Connect sync endpoints to Journey feature for automatic processing

**Changes Required**:
- Create JourneyService integration module
- Add sync_after_video_upload() method to JourneyService
- Wire up async processing in both sync_single_video and sync_batch_videos endpoints
- Handle errors gracefully (don't fail sync if Journey processing fails)
- Log Journey processing status to audit trail

**Dependencies**: Sprint 4 (audit logging)

**Acceptance Criteria**:
- After successful video sync, Journey processing starts automatically
- Both single and batch endpoints trigger Journey updates
- Errors in Journey processing don't affect sync response
- Processing happens async in background

### Task 39: Call MilestoneDetector after batch sync
**Objective**: Trigger milestone detection for newly synced videos

**Changes Required**:
- Extend MilestoneDetector to accept new dive IDs
- Create batch milestone detection method
- Detect milestones only for new dives (since last run)
- Store detected milestones in database
- Link milestones to Journey progression

**Dependencies**: Task 38

**Acceptance Criteria**:
- Milestones detected for all new dives in batch
- Incremental detection (only new dives)
- Milestones linked to correct Journey
- Detection happens efficiently (<1s per 100 dives)

### Task 40: Store phase_insight in Milestone record
**Objective**: Populate phase_insight field with coaching recommendations

**Changes Required**:
- Pass phase1_performance and phase2_performance to MilestoneDetector
- Pass phase_insight from Dive record to Milestone
- Store phase insights in JourneyMilestone table
- Display phase insights in Journey narrative
- Use phase insights for coaching narrative generation

**Dependencies**: Task 39

**Acceptance Criteria**:
- Phase insights stored in milestone records
- Available in Journey API responses
- Properly linked to two-phase scoring context
- Incorporated into milestone narratives

### Task 41: Test milestone detection with two-phase data
**Objective**: Validate milestone detection works with two-phase performance scores

**Test Coverage**:
- Milestones detected correctly from phase1/phase2 combinations
- Phase insights included in milestone narratives
- Both legacy (single score) and new (two-phase) formats work
- Milestone significance adjusted for weak phase performance
- Cross-phase analysis (e.g., perfect phase1 but weak phase2)

**Dependencies**: Task 40

**Acceptance Criteria**:
- 15+ test cases covering two-phase scenarios
- 100% pass rate
- Coverage of edge cases (phase gaps, weak phases, etc.)

### Task 42: Write sync to milestone integration tests
**Objective**: End-to-end tests of video sync → milestone detection workflow

**Test Coverage**:
- Single video sync → milestone detection
- Batch sync → multiple milestone detection
- Phase insights passed through full pipeline
- Milestone linked to source Dive
- Journey updated with new milestones
- Audit trail tracks entire flow

**Acceptance Criteria**:
- 10+ integration test cases
- All passing
- Coverage of happy path and error scenarios

### Task 43: Performance test milestone detection
**Objective**: Validate milestone detection scales with 1000+ dives

**Test Coverage**:
- 100 dives: <500ms detection
- 500 dives: <2s detection
- 1000 dives: <5s detection
- Batch detection performance
- Index utilization validation
- Memory efficiency with large datasets

**Performance Targets**:
- Single dive milestone detection: <50ms
- Batch 100 dives: <500ms
- Batch 500 dives: <2s
- Batch 1000 dives: <5s
- No memory leaks with incremental processing

**Acceptance Criteria**:
- All performance targets met
- Baseline established for monitoring
- Index optimization recommendations

## Architecture

```
Video Sync (Sprint 4)
    ↓ [POST /sync or /batch]
    ├─ Create Dive record
    ├─ Store synced_at timestamp
    ├─ Generate phase_insight (Task 35)
    └─ Log audit trail (Task 35)
         ↓
Journey Service (Sprint 5)
    ├─ Load all dives for Journey (Task 38)
    ├─ Detect milestones (Task 39)
    ├─ Store phase_insight in milestone (Task 40)
    ├─ Update Journey progression
    └─ Generate narrative with coaching insights
         ↓
User (Via API)
    └─ See updated Journey with new milestones
        and phase-based coaching recommendations
```

## Implementation Order

1. **Task 38**: JourneyService integration (foundation)
2. **Task 39**: Batch milestone detection (core logic)
3. **Task 40**: Phase insight storage (data integration)
4. **Task 41**: Two-phase test coverage (validation)
5. **Task 42**: Integration test suite (end-to-end)
6. **Task 43**: Performance testing (scalability)

## Success Criteria

✅ All 6 tasks completed and passing tests
✅ End-to-end video sync → milestone → Journey workflow
✅ Phase insights integrated throughout pipeline
✅ Performance targets met
✅ 25+ integration and unit tests
✅ 100% code coverage for new modules
✅ Comprehensive documentation

## Notes

- Milestone detection already supports two-phase data (see existing code)
- JourneyMilestone table structure likely already exists
- Phase insights generated in Sprint 4 Task 35
- Integration should be minimal (mostly wiring)
- Focus on clean async integration to avoid blocking syncs
