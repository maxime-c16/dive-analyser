# DIVER_ID_19_HARDENING_V2

**Packet:** DIVE_ANALYZER_SUBJECT_REFERENCE_ACQUISITION_V2 (Phase 0.2)
**Date:** 2026-09-13
**Status:** PHANTOM_DIVER_HARDENING_GREEN
**Predecessor:** docs/audits/DIVER_ID_19_PHANTOM_REPAIR_V1.md (3dafd8b)

## Intent

The orphan `divers.id=19` ("RIP", a caption-parsing phantom with zero Dive
references after the V1 live repair) is retired generically: inactive divers
are never resolved by normal identity resolution. No destructive delete, no
RIP-specific branch.

## Changes

1. **Live DB (explicit transaction, snapshot-proven):**
   `UPDATE divers SET active=false WHERE id=19`.
2. **`backend/app/services/diver_identity.py` — `resolve_diver()`:**
   - canonical-name/alias resolution now requires `Diver.active IS TRUE`
     (generic rule; no name-specific branch);
   - create-path: if a RETIRED (inactive) diver already owns the requested
     canonical name (directly or via alias), the resolver refuses to create a
     duplicate identity row and returns None - historical RIP-style input can
     never silently reattach a Dive to diver 19, and cannot crash on the
     `unique(canonical_name)` constraint either. Caller leaves diver_id NULL.
3. **`backend/app/models/analysis.py` - bounded test-env repair:**
   postgresql.UUID columns get a sqlite-compatible variant so the in-memory
   sqlite test harness can create the analysis tables (pre-existing
   environment breakage; Postgres behavior unchanged - verified by the
   identical full-suite failure set before/after the change).
4. **Tests** (`backend/tests/test_divers.py`, 9/9 pass):
   - inactive diver not resolved by canonical name;
   - inactive diver not resolved via alias;
   - retired-name input cannot reattach the retired row (create=False -> None;
     create=True -> None, not a new row, never the retired id);
   - active ALL-CAPS athletes (TOM/PAUL/FANNY/SARA/MAT) still resolve;
   - historical dives of a retired diver remain intact and inspectable.
5. **Regression safety:** full backend suite failure set is IDENTICAL to the
   pristine pre-change image (19 failed / 14 errors pre-existing, enumerated
   in the V2 science report); the targeted suites touching the resolver
   (test_video_sync, test_integration_mac_agent_sync, test_data_integrity)
   pass 44/44.

## Post-deploy verification (live backend)

- `resolve_diver("RIP", create=False) -> None` (diver 19 excluded);
- TOM/PAUL/FANNY/SARA/MAT resolve to their active rows;
- diver 19 remains directly queryable (historical inspectability preserved);
- `Dive.diver_id=19` rows: none exist (V1 repair moved 6 rows to diver 1).

## Semantics preserved

- No destructive delete; no RIP-specific branch in the generic resolver;
- active real all-caps athletes unaffected; historical data inspectable;
- parser (mac-agent, 3dafd8b) already prevents RIP from being treated as a
  person name - this hardening closes the product-side resolver surface.

Live-DB snapshot (docker exec, at 2026-09-13T12:14:21Z):

```json
{
 "at": "2026-09-13T12:14:21.127505Z",
 "before": {
  "diver19": {
   "id": 19,
   "display_name": "RIP",
   "active": true
  },
  "dive_counts": {
   "1": 2517
  }
 },
 "after": {
  "diver19": {
   "id": 19,
   "display_name": "RIP",
   "active": false
  },
  "dive_counts": {
   "1": 2517
  }
 }
}
```
