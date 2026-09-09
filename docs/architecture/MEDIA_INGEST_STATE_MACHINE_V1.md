# MEDIA_INGEST_STATE_MACHINE_V1 — Object-Store Ingest State Machine

Task packet: `MEDIA_BACKBONE_P0_P1_V1`
Implementation: `mac-agent/src/ingest/states.py`, `state_store.py`, `coordinator.py`

## States

```text
DISCOVERED → CAPTION_CAPTURED → MEDIA_REQUESTED → MEDIA_MATERIALIZED →
LOCAL_HASHED → REMOTE_UPLOAD_STARTED → REMOTE_UPLOADED → REMOTE_VERIFIED →
DB_COMMITTED → CACHE_CLEANED
```

Terminal: `CACHE_CLEANED` (success), `QUARANTINED` (fatal, fail-closed).
Retryable failures do NOT advance state: they increment `attempts`, record
`last_error` (family + detail), and leave the state unchanged for re-drive.

## Persistence

- `IngestStateStore` — one JSON state file per ingest run (atomic
  `tmp + os.replace`, same convention as the agent's `sync_state.json`).
  Path convention: `<object_store.state_dir>/<video_uuid>.json`.
- Document fields: `state`, `caption {provider, raw, sha256}`,
  `media {temp_path, byte_size, sha256, object_key}`,
  `remote {verified, attempts, last_put_sha256}`,
  `db_commit {committed}`, `attempts`, `last_error`, bounded `history[]`.
- The state file is the operational resume authority; `ingest_object_state`
  is a server-side durable commit ledger (see STATE AUTHORITY), not a second
  orchestration journal.

## STATE AUTHORITY (repair R3)

- **LOCAL EXECUTION JOURNAL** — the per-clip JSON state file
  (`IngestStateStore`): the ONLY authority for pre-commit / restart / retry
  mechanics. The agent never reads server state.
- **SERVER DB** — `media_blobs` / `media_revisions` / `caption_revisions`:
  the ONLY authority for the durable committed logical result.
- `ingest_object_state` is a **server-side durable commit ledger**: written
  exactly once per verified ingest commit by `commit_verified_ingest`; never
  read by agent orchestration; not a second state machine.

### Reconciliation matrix (each case has ONE deterministic outcome)

| Case | Deterministic reconciliation outcome |
|---|---|
| local journal exists / DB rows absent | resume journal; DB commit runs exactly once at REMOTE_VERIFIED→DB_COMMITTED (idempotent by SHA) |
| local journal lost / committed DB rows exist | fresh re-ingest converges to the SAME content-addressed result (same blob SHA, same object key); server dedupe by SHA collapses to one logical result; no duplicate rows |
| remote object exists / journal says pre-upload | idempotent re-put of identical content-addressed bytes; converge; one object |
| DB committed / journal says pre-commit (crash after effect before persist) | restart re-commits; server dedupe collapses to one logical result |

Tests: `TestStateAuthority` (agent) — the 4 reconciliation cases + a static
assertion that the agent coordinator never references server state;
`TestStateAuthorityArchitecture` (backend) — `ingest_object_state` referenced
only by its model and the commit service.

## Crash-safety ordering

| Transition | Side effect | Ordering rule |
|---|---|---|
| DISCOVERED→CAPTION_CAPTURED | read-only caption read | persist caption+hash with the transition; crash ⇒ repeatable read |
| MEDIA_REQUESTED→MEDIA_MATERIALIZED | materialize (iCloud/Photos export) | effect before persist; crash ⇒ re-materialize (osxphotos `--update` makes it idempotent) |
| MEDIA_MATERIALIZED→LOCAL_HASHED | sha256 + object key | deterministic; recompute-safe |
| LOCAL_HASHED→REMOTE_UPLOAD_STARTED | none (marker) | persisted before upload |
| REMOTE_UPLOAD_STARTED→REMOTE_UPLOADED | object put | put is idempotent (same key, same content-addressed bytes); crash mid-upload ⇒ re-put |
| REMOTE_UPLOADED→REMOTE_VERIFIED | full GET + SHA equality | mismatch ⇒ QUARANTINED (fail closed); never trust put response alone |
| REMOTE_VERIFIED→DB_COMMITTED | DB commit (idempotent by SHA) | commit before persisting `db_commit.committed`; crash ⇒ re-commit (idempotent) |
| DB_COMMITTED→CACHE_CLEANED | delete local temp dir | cleanup only when `remote.verified` AND `db_commit.committed` |

## Restart answers (contract)

After any crash + restart, from the state file alone:

- **What was completed?** `state` + `remote.verified` + `db_commit.committed`.
- **What is safe to retry?** anything below `DB_COMMITTED` — all effects are
  idempotent (re-read, re-materialize, re-hash, re-put, re-verify, idempotent commit).
- **What must not be repeated?** a second logical blob/revision/caption-revision
  (server commit dedupes by SHA) and the DB commit once `db_commit.committed=true`.
- **What remote object should already exist?** `media.object_key`
  (`blobs/sha256/<2>/<sha>`), when `state >= REMOTE_UPLOAD_STARTED`.
- **Has DB commit occurred?** `db_commit.committed`.
- **Can local temp bytes be deleted?** only after `REMOTE_VERIFIED`
  (strictly: `DB_COMMITTED` for full cleanup); stale-temp reconciliation resets
  to `MEDIA_REQUESTED` if temp bytes vanished early (re-materialize is safe).

## Failure taxonomy

| Family | Class | Behavior |
|---|---|---|
| `object_store_unavailable` | `ObjectStoreUnavailable` (interrupted upload, head/get errors) | retryable, state unchanged |
| `verification_failed` | `ObjectStoreVerificationError` (roundtrip SHA mismatch) | QUARANTINED — fail closed |
| `ingest_fatal` | caption unavailable/empty, unusable materialization | QUARANTINED |
| `insufficient_disk` | `min_free_disk_bytes` guard | retryable, state unchanged |
| config errors | `ConfigValidationError` | construction-time rejection; ingest never starts |

## Verified-ingest definition (roundtrip rule)

```text
local edited bytes → SHA256 A → put(object_key) → full remote GET → SHA256 B
require A == B (and byte_size match) else QUARANTINED
```

A successful SDK/API put response is never sufficient evidence. S3/B2 multipart
ETags are never compared to or substituted for SHA-256 (explicit test).

## Failure tests A–G (all implemented and passing)

| Crash point | Test |
|---|---|
| A. before materialization | `test_a_crash_before_materialization` |
| B. after materialization, before local hash | `test_b_crash_after_materialization_before_hash` |
| C. after local SHA, before remote upload | `test_c_crash_after_local_sha_before_upload` |
| D. interrupted mid-upload | `test_d_interrupted_mid_upload_retries` |
| E. upload complete, crash before verification | `test_e_upload_complete_crash_before_verification` |
| F. verification complete, DB commit absent | `test_f_verified_db_commit_absent_retries_commit_once` |
| G. DB commit complete, cleanup absent | `test_g_db_commit_complete_cleanup_absent` |

Each restart converges to ONE logical result: exactly one object, one blob,
one media revision, one caption revision, exactly one DB commit (test G proves
the restart does NOT re-commit), temp cleaned only at the end.
`test_no_duplicate_objects_on_full_replay` and
`test_corrupt_state_file_starts_fresh` cover restart/idempotence edges.
