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
(no duplicates). Used by the P2 canary; wired to the P4 commit endpoint.

## STORAGE AUTHORITY (P4.3)

CONTENT IDENTITY and PHYSICAL STORAGE REPLICAS are separate concepts
(P4.3 packet §2/§3; exercised live by the P4.2 cross-environment cohort):

- **CONTENT AUTHORITY**: `media_blobs` is content identity ONLY — one row
  per SHA-256 with immutable content-level metadata. Its `storage_backend`
  / `bucket` / `object_key` / `remote_object_id` columns are
  **transitional / non-authoritative**: they record the first-seen location
  only, are retained for compatibility, and must never be consulted for
  "where is this replica?".
- **STORAGE LOCATION AUTHORITY**: `media_blob_locations`
  (`backend/app/models/media_backbone.py::MediaBlobLocation`, migration
  `add_media_blob_locations.sql`) is the authoritative per-replica record:
  unique on `(storage_backend, bucket, object_key)` (physical replica
  identity — a location key is bound to exactly one content SHA; a
  conflicting SHA is rejected, never overwritten) and on
  `(blob_sha256, storage_backend, bucket, object_key)` (idempotent
  storage-location dedupe). Each row carries `environment`, `verified`,
  `verified_at`.
- **ENVIRONMENT AUTHORITY**: environment belongs to the physical
  storage/commit context, never to the SHA. `environment=dev` commits may
  only reference the DEV bucket; `environment=prod` only the PROD bucket
  (enforced in the commit service AND the commit API, fail-closed from the
  same settings allowlist). One SHA = one `MediaBlob`; one blob → zero or
  more verified locations (e.g. one DEV replica + one PROD replica as two
  first-class rows).
- **P5 LOOKUP SEMANTICS**: the internal-only helpers
  `resolve_verified_location(db, sha, environment)` and
  `resolve_media_revision_location(db, video_uuid, environment)` answer
  "where is the verified PROD object for this MediaRevision?"
  deterministically: join content → verified replica for the environment
  (`verified=false` locations are never returned — not playback-eligible;
  newest-verified-wins ordering is deterministic even if a future
  deployment ever held several verified replicas per environment). No P5
  playback surface is exposed by P4.3.

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

## P5 authenticated playback grant architecture (2026-09-10)

Packet `MEDIA_BACKBONE_P5_ACCELERATED_AUTH_PLAYBACK_V1`. Authority:
`docs/architecture/USER_AUTHORIZATION_V1.md`; audit:
`docs/audits/MEDIA_BACKBONE_P5_ACCELERATED_AUTH_PLAYBACK_V1.md`.

- **New route (fail-closed, flag-gated)**:
  `GET /api/v1/media/revisions/{revision_id}/play`
  `session → can_user_access_media → verified-PROD location → B2 presign
  (TTL 120 s) → HTTP 302 Location`.
- **Grant model**: 302 redirect preferred over JSON URL — frontend JS
  needs no provider URL, `<video src>` semantics stay simple,
  authorization stays same-origin, and no B2 CORS is required (verified
  live: Chromium + WebKit metadata/play/seek/Range all GREEN without any
  bucket CORS mutation).
- **Backend presigner**: `backend/app/services/b2_presign.py` (boto3
  pinned 1.34.69) over the S3-compatible API, region/endpoint/credential
  from runtime env only (`B2_PLAYBACK_*`), TTL clamped to [1, 300] s,
  `PresignUnavailable` → explicit 503 provider-failure family (never a
  redirect to an arbitrary location, never a legacy fallback).
- **Canary listing endpoint** (bounded to the same flags):
  `GET /api/v1/media/playback/canary/revisions` — media revisions the
  current user may access that resolve to exactly one verified PROD
  location (ids + coarse metadata only).
- **Frontend canary (bounded)**: `frontend/src/pages/P5Canary.tsx` at
  `/media/p5-canary` — login surface, authenticated playback of the
  cohort `<video src="/api/v1/media/revisions/{id}/play">` with NO
  `crossorigin` attribute and no JS media fetch, and logout. It does not
  replace any legacy video URL anywhere.
- **Content-Type (future ingest only)**: mac-agent
  `media_content_type.video_content_type()` derives the wire MIME from
  ffprobe container/codec evidence (`video/quicktime` / `video/mp4` /
  `video/webm` / `video/x-matroska`, fail-closed default
  `binary/octet-stream`); `ObjectStoreIngestCoordinator` forwards it to
  `put(..., content_type=...)`; the B2 adapter passes `ContentType` to
  both boto3 upload paths and omits it when unset (legacy behavior
  preserved). Historical objects are NOT rewritten.
- **Rollback**: `USER_AUTH_ENABLED=false` + `B2_PLAYBACK_CANARY_ENABLED=false`
  (the post-canary default) makes every new route 404 and leaves the
  legacy playback pipeline untouched; re-activation is a `.env` flip +
  backend restart. Distinguish `AUTHORIZATION_DENIED` (404) from
  `B2_PROVIDER_FAILURE` (503) — never bypass auth because B2 is down.


## P6 — B2-default playback for the authorized owner (2026-09-10)

Packet `MEDIA_BACKBONE_P6_ACCELERATED_DEFAULT_PLAYBACK_V1` (audit:
`docs/audits/MEDIA_BACKBONE_P6_ACCELERATED_DEFAULT_PLAYBACK_V1.md`):

- **Single playback URL**: `GET /api/v1/media/revisions/{id}/play` is the
  one application playback route; the backend decides the source. The
  frontend never sees B2 storage keys, bucket names, or presigned URLs in
  state; the `<video>` element follows the 302 natively (no crossorigin,
  no fetch) and seek/Range go straight to the provider.
- **Source policy** (authorization ALWAYS first): verified PROD B2
  replica + credential proven usable at grant time (provider HEAD) →
  presigned GET redirect (TTL 120 s); NO_PROD_B2_REPLICA or
  B2_TEMPORARY_FAILURE → authenticated server-side legacy stream with
  Range (cache rendition preference proxy_720p > proxy_360p > original,
  else the exact legacy file candidates, allowed-roots constrained);
  ambiguous/integrity faults → fail-closed 404; AUTH_DENIED never falls
  back.
- **Legacy routes auth-gated** while auth enabled (rollback = flags off):
  `/videos/{uuid}`, `/videos/check/{uuid}`, `/media/cache/{id}/play`,
  `/media/events/viewed`.
- **Production default for the current OWNER**: B2 playback enabled
  (`USER_AUTH_ENABLED=true`, `B2_PLAYBACK_CANARY_ENABLED=true`), cohort
  9/9 via B2 (provider 206 each), legacy fallback live-proven, both
  rollback paths proven. Future ingest Content-Type derivation unchanged
  and still inert for history.


## P7 — continuous dual-write + historical migration (2026-09-10)

Packet `MEDIA_BACKBONE_P7_ACCELERATED_CONTINUOUS_INGEST_MIGRATION_V1` (audit:
`docs/audits/MEDIA_BACKBONE_P7_ACCELERATED_CONTINUOUS_INGEST_MIGRATION_V1.md`;
migration engine authority: `docs/architecture/HISTORICAL_MEDIA_MIGRATION_V1.md`).

- **Continuous activation boundary**: the legacy media-job event stream is the
  production trigger. `ProductionDualWrite.should_process(video_uuid,
  request_reason)` accepts the exact configured `dual_write.trigger_reason`
  (default `new_captioned_ingestion` — jobs created only for NEWLY inserted
  captioned dives). The 5-10 UUID cohort allowlist is now canary/debug-only;
  normal production requires NO hand-edited UUID lists.
- **Historical backlog isolation**: the continuous path performs no discovery
  of any kind (no Photos crawl / DB walk / album tap); renovation jobs
  (population/upgrade/replacement) are structurally refused. History belongs
  exclusively to the migration engine.
- **Staging disk guard**: `stage_copy` refuses (bounded marker, no bytes) when
  free disk < `min_free_disk_bytes` + staged size.
- **Migration engine**: `mac-agent/src/ingest/migration.py` + backend
  inventory endpoint `GET /api/v1/media/backbone/migration/inventory`
  (agent-key gated, storage facts only). Per-item durable journal; states
  INVENTORIED→…→CLEANED (+ RETRYABLE/QUARANTINED/DEFERRED_INTERACTIVE/
  SKIPPED_ALREADY_PROD); DEV-read/PROD-ingest separate scoped keys;
  roundtrip SHA; copy-only; idempotent reruns; one active item.
- **P7 production flags**: `object_store.enabled=true`,
  `dual_write.enabled=true`, `continuous_new_ingest=true`,
  `migration.enabled=true` (engine remains one-shot).
