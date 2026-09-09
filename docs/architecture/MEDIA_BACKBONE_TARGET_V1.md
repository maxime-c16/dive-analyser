# MEDIA_BACKBONE_TARGET_V1 — Target Interfaces & Seams (P0.1)

Derives minimal boundaries around the existing, working ingestion code. No large rewrite.
Companion to `MEDIA_BACKBONE_CURRENT_STATE_V1.md`. Implementation lives in
`mac-agent/src/ingest/` (agent side) and `backend/app/models/media_backbone.py` +
`backend/app/services/media_backbone.py` (server side).

## Principles

1. Additive only. Production upload/serving behavior unchanged while
   `OBJECT_STORE_INGEST` is disabled (the default).
2. Semantic boundaries over class-name ceremony; fresh code justified the following
   small set of interfaces.
3. Cache is never authority: local temp bytes may be deleted only after a safe
   persisted state (remote verified + DB-committed or explicitly retryable with
   remote state recorded).

## Interfaces (agent side, `mac-agent/src/ingest/`)

### `PhotosSource` (seam over existing code)

- Responsibility: discovery / source identity. For P1 this is satisfied by the
  existing `PhotosReader.get_all_videos()` + `get_video_by_uuid()`; the canary
  (P2) plugs an album-scoped discovery (`DiveAnalyzer Ready`) in front of the
  same reader. No new class is required yet — the seam is the existing method
  surface. Documented as the discovery boundary; least-invasive canary mechanism
  is **manual trigger** (CLI invocation of the canary flow) rather than new
  polling, per P2 canary doctrine.

### `CaptionProvider`

```python
class CaptionProvider(Protocol):
    name: str
    def get_caption(self, video_uuid: str) -> CaptionResult | None: ...
```

- `CurrentStableCaptionProvider` — wraps the existing osxphotos
  `photo.description` path (the validated production authority). Returns the
  EXACT provider string: **`caption_raw` for the new backbone authority is the
  caption obtained from the provider BEFORE any application-level whitespace
  normalization** (repair R1). No strip, no Unicode normalization, no
  whitespace collapse, no punctuation rewriting, no newline convention change.
  The historical `.strip()` (extractor.py:125) is the LEGACY payload transform
  (`legacy_caption_transform`), retained exclusively in the legacy production
  path; the backbone never applies it to the value it persists.
- `PhotosDbCaptionProviderShadow` (renamed from the misleading
  `PhotoKitCaptionProviderShadow` in repair R2) — SHADOW ONLY. Direct
  read-only SQLite access to the Photos library DB is NOT PhotoKit. Schema is
  introspected at runtime via `PRAGMA table_info`; reports
  `shadow_available=False` with an error reason if the column cannot be located
  safely. Returns the exact DB string (no strip). Never authoritative; never
  blocks ingestion; never raises into the stable path.
- Real PhotoKit caption shadow status: `PHOTOKIT_CAPTION_SHADOW_STATUS =
  NOT_IMPLEMENTED_CURRENT_RUNTIME` (P1 does not require real PhotoKit shadow
  availability; a future real PhotoKit shadow would need a valid authorized
  macOS PhotoKit runtime, not fragile name-satisfying machinery).

### `MediaMaterializer` (seam over existing code)

- The existing `MediaMaterializer` (media_materializer.py) already provides
  targeted single-UUID export with iCloud download and hardening. The backbone
  consumes its output directory; no refactor. Rendition provenance
  (`PHOTOS_EDITED_RENDITION`) is recorded on the `MediaRevision` because osxphotos
  export without `--skip-edited` yields the user's edited/trim representation.

### `IngestCoordinator`

New, `mac-agent/src/ingest/coordinator.py`. Deterministic orchestration over an
append-safe JSON state file (same atomic tmp+os.replace convention as
`sync_state.json`):

- `ObjectStoreIngestCoordinator.submit(...)` → `run_once()`
- States (state machine doc: `MEDIA_INGEST_STATE_MACHINE_V1.md`):
  `DISCOVERED → CAPTION_CAPTURED → MEDIA_REQUESTED → MEDIA_MATERIALIZED →
  LOCAL_HASHED → REMOTE_UPLOAD_STARTED → REMOTE_UPLOADED → REMOTE_VERIFIED →
  DB_COMMITTED → CACHE_CLEANED`, plus `RETRYABLE_ERROR` / `QUARANTINED`.
- Idempotence contract: every transition persists *before* performing the
  side effect where possible, and records enough evidence (sha256, object_key,
  remote presence) that a restart can answer: what completed, what is safe to
  retry, what must not be repeated, what remote object should already exist,
  whether DB commit occurred, whether local temp can be deleted.
- Convergence rule: restarting with the same state file always converges to ONE
  logical result: at most one MediaBlob (content-addressed), one MediaRevision,
  one CaptionRevision per (clip, content) — duplicates collapse by SHA.

### `StorageSink`

```python
class StorageSink(Protocol):
    def put_verified(self, *, key: str, path: Path, sha256: str) -> PutResult: ...
    def head(self, key: str) -> ObjectHead | None: ...
    def get(self, key: str) -> bytes: ...
    def presign_get(self, key: str, ttl_seconds: int) -> str: ...
```

Two implementations:

- `LegacyServerSink` — seam **documented, not forced** in P1: the existing
  lease/multipart upload path (media_jobs + sync_client) is already the legacy
  sink; adapting it would touch the live production upload path. The TARGET
  architecture allows `Photos ingestion → {LegacyServerSink | ObjectStoreSink}`
  fan-out later from the same materialized bytes (single hash pass). The exact
  future seam is the `MediaJobProcessor.process_once` boundary where a
  materialized source exists (media_jobs.py:53ff).
- `ObjectStoreSink` — wraps the `ObjectStore` port below with verified-put
  semantics (upload → full GET → SHA equality, fail closed).

## `ObjectStore` port (`mac-agent/src/ingest/objectstore/`)

```python
class ObjectStore(Protocol):
    def put(self, key: str, data_or_path) -> PutResult
    def head(self, key: str) -> ObjectHead | None      # None if absent
    def get(self, key: str) -> bytes
    def presign_get(self, key: str, ttl_seconds: int) -> str
    def delete(self, key: str)  # EXPLICITLY guarded, see below
```

- `FakeObjectStore` — deterministic in-memory/local-dir backend with fault
  injection: `fail_after_bytes` (interrupted upload), `corrupt_keys` (byte
  corruption), `head_errors`, `get_errors`. No network, no credentials.
- `BackblazeB2Store` — S3-compatible API adapter (boto3 optional import; absent
  dependency ⇒ clear construction error, tests never need it). Private bucket
  assumption, explicit endpoint/region, bounded retries, typed domain errors
  (`ObjectStoreError` family). No bucket creation, ever, at runtime.
- **Deletion guard**: `delete` exists on the port but is named on the B2 store
  as `delete_object_explicit_operator_action` and is NOT reachable from any
  ingest/sync code path; ingest synchronization code has no delete calls.
  Automatic remote purge is out of scope (packet §30).

## Content addressing

- Identity: `sha256(materialized edited rendition bytes)`, lowercase hex.
- Object key: `blobs/sha256/<first-2>/<full-sha>` (+ optional `.<ext>` suffix;
  extension never participates in identity). No PII, no caption, no dive code,
  no athlete name, no Photos title in keys.
- SHA-256 is the only application integrity identity. S3/B2 multipart ETags are
  NEVER compared to or substituted for source SHA (explicit test).

## Caption revisions (server side)

New additive tables (models in `backend/app/models/media_backbone.py`; migration
`backend/migrations/add_media_backbone_tables.sql`, idempotent, reversible by
DROP of the new tables only):

- `media_blobs` — `sha256` PK, `byte_size`, `codec`, `width`, `height`,
  `duration_seconds`, `rendition_semantics` (default `photos_edited_rendition`),
  `storage_backend`, `bucket`, `object_key`, `remote_object_id`,
  `ingest_impl_version`, `created_at`.
- `media_revisions` — `id`, `video_uuid` (FK semantics to the logical clip,
  recorded as string; no legacy-row rewrites), `blob_sha256` FK → media_blobs,
  `photos_edit_fingerprint`, `rendition_semantics`, `source_provenance` JSON,
  `observed_at`.
- `caption_revisions` — `id`, `video_uuid`, `caption_raw` (exact persisted
  representation), `caption_sha256` (UTF-8 bytes of the exact persisted
  `caption_raw`), `caption_provider`, `shadow_*` comparison fields
  (`shadow_provider`, `shadow_raw`, `shadow_sha256`, `shadow_available`,
  `exact_equal`), `parser_version`, `parsed_json`, `observed_at`. Append-only:
  same caption re-observed = identical sha → insert collapses (idempotent
  service commit), changed caption = new revision row; zero media upload.
- `ingest_object_state` — server-mirrored ingest state per (video_uuid,
  object_key): `state`, `attempts`, `error_family`, `local_temp_path`,
  `blob_sha256`, `verified`, `db_committed_at`, `updated_at`. Agent-side JSON
  state file remains the operational authority for resume; this mirror exists
  for observability/DB-commit evidence.

## Server commit service

`backend/app/services/media_backbone.py::commit_verified_ingest(...)` — the only
write path for the backbone: idempotently inserts blob/revision/caption-revision
rows keyed by SHA; re-calling with the same content returns existing rows
(no duplicates). Used by the P2 canary; wired to no endpoint in P1.

## STATE AUTHORITY (repair R3)

ONE coherent model, two layers — no competing state stores:

- **LOCAL EXECUTION JOURNAL** (mac-agent per-clip JSON state file,
  `mac-agent/src/ingest/state_store.py`): the ONLY authority for pre-commit /
  restart / retry mechanics on macOS. All orchestration decisions are made
  from this file alone.
- **SERVER DB** (`media_blobs` / `media_revisions` / `caption_revisions` +
  `ingest_object_state`): the ONLY authority for the durable committed logical
  result. `ingest_object_state` is a **server-side durable commit ledger** —
  written exactly once per verified ingest commit by
  `commit_verified_ingest`, never read by agent-side orchestration (the agent
  has no DB access; `commit_db_fn` is injected). It is not a second
  state machine. Reconciliation outcomes are deterministic (see
  `MEDIA_INGEST_STATE_MACHINE_V1.md` §Reconciliation matrix); tests prove
  restart convergence does not depend on two divergent mutable state stores.

## Feature flag / rollback

- Agent config: `object_store.enabled: false` (default) + `environment: dev|prod`,
  bucket, endpoint/region, prefix, `min_free_disk_bytes` guard. When disabled,
  `ObjectStoreIngestCoordinator` is never constructed and no B2 code is imported
  on the hot path (lazy import).
- Server config: `OBJECT_STORE_INGEST=false` default; no endpoint serves from B2
  in this packet.
- Rollback = flip flag off; legacy pipeline untouched throughout.

## Local cache semantics

- Prefer 1 active large asset (existing media job `max_jobs` cap preserved).
- `min_free_disk_bytes` guard checked before materialization in the coordinator
  (reuses existing free-space tier philosophy; coordinator stops with
  `RETRYABLE_ERROR` rather than risking the disk).
- Cleanup only after `REMOTE_VERIFIED` (+`DB_COMMITTED` for full cleanup),
  with stale-temp reconciliation on restart.

## B2 configuration firewall

Validated at construction time (typed errors): missing credentials, empty bucket,
dev/prod bucket cross-wiring (`diveanalyzer-prod-media` selected while
`environment=dev` and vice versa), unexpected object prefix, malformed SHA (must
match `^[0-9a-f]{64}$`), public-access expectation (private bucket is a required
provisioning invariant and is checked at the config level at P1; actual
anonymous-access denial is verified against the real DEV bucket at P2), missing endpoint/region.
