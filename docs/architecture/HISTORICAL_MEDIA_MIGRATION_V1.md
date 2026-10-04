# HISTORICAL_MEDIA_MIGRATION_V1 — DB-driven historical migration engine

Packet: `MEDIA_BACKBONE_P7_ACCELERATED_CONTINUOUS_INGEST_MIGRATION_V1`.
Authority companion to `MEDIA_BACKBONE_MIGRATION_PLAN_V1.md` (doctrine) and
`MEDIA_INGEST_STATE_MACHINE_V1.md` (continuous-ingest state machine).

## Scope authority

The DB/domain graph defines the migration queue:

```
MediaRevision.video_uuid → dives.video_uuid (UNIQUE) → dives.diver_id
    → user_diver_access OWNER binding (bootstrapped OWNER)
```

Photos is a source/materialization provider, NEVER the migration inventory
authority. No Photos-library crawl exists in the engine. Migration is
authorized ONLY for existing Dive Analyzer logical media of the bootstrapped
OWNER diver; ambiguous ownership/chain → class E QUARANTINE.

## Inventory endpoint

`GET /api/v1/media/backbone/migration/inventory` (agent API key, read-only)
returns per-revision identity + storage facts (no captions, no filenames):
chain facts, verified DEV/PROD locations with exact object keys, byte size.
Agent-side classification:

| Class | Meaning |
|---|---|
| A | already verified PROD B2 → skip |
| B | verified DEV B2 only → DEV read → PROD write |
| C | no PROD, checksum-validated local/vault source |
| D | no PROD, targeted Photos edited-rendition materialization |
| E | ownership/source/caption/provenance conflict → QUARANTINE |
| F | genuinely missing → QUARANTINE |

## Engine (mac-agent/src/ingest/migration.py)

One-shot CLI modes (`--inventory`, `--drive <classes>`, `--status`); never a
daemon component (cannot become a second production daemon). Per-item
journal `<blob_sha>.mig.json` (0600, atomic) is the ONLY orchestration
authority; states:

```
INVENTORIED → SOURCE_READY → LOCAL_VERIFIED → PROD_UPLOAD_STARTED →
PROD_UPLOADED → PROD_VERIFIED → DB_COMMITTED → CLEANED
```

Retryable failures record `resume_state` and re-enter at that state
(re-validated evidence); verification failures and fatal errors QUARANTINE
the single item; the wave continues (failure isolation).

Source priority: PROD-object-present (HEAD) > verified DEV replica (separate
DEV-read / PROD-ingest bucket-scoped credentials; no cross-bucket admin
authority) > local checksum-validated vault source > targeted Photos
materialization (production GUI-launchd context, bounded).

## Roundtrip verification (binding)

Every new PROD replica: `source SHA A → PROD PUT → full PROD GET → SHA B`,
require A == B and byte_size match. ETags never substituted. Mismatch →
QUARANTINED, batch continues. PROD HEAD before any PUT (idempotence); a
present object is still full-GET verified against the KNOWN source SHA.

## Caption authority

`CaptionRevision.caption_raw` remains the EXACT provider string. The engine
reuses the original ingest receipt captions (matched by blob SHA + video
UUID) or reads the exact provider caption fresh; it NEVER manufactures a
caption from normalized legacy DB text. Unavailable → QUARANTINED with an
explicit reason (no silent skips).

## Idempotence

A complete second pass performs zero byte ops: verified-PROD inventory facts
short-circuit classification to A (SKIPPED_ALREADY_PROD), terminal journals
are respected, PROD HEAD prevents re-upload, and the commit endpoint dedupes
blob/revision/caption/location rows. Proven live at P7: second pass over 15
items → 0 uploads, 0 GETs, 0 commits, 0 duplicate rows.

## Safety invariants

Copy-only (no delete/hide primitives are imported or callable; static test).
Legacy retention absolute (DEV replicas, cache, files, Photos untouched).
One active item, bounded waves, per-asset persistence, bounded temp (cleaned
after verified commit), min-free-disk guard before every byte operation.
