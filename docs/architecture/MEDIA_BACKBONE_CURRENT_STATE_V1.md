# MEDIA_BACKBONE_CURRENT_STATE_V1 — P0 Current-State Audit

Task packet: `MEDIA_BACKBONE_P0_P1_V1` (DIVE_ANALYZER_MEDIA_BACKBONE_V1)
Status: **P0 AUDIT COMPLETE — evidence-backed**
Canonical base HEAD: `4b192dc0a90cc2ffb0ec85f334bb8ffc329a93e2` (branch `uiux-overhaul-pro-app`)

## Authority / freshness

- Canonical repository per `docs/PROJECT_STATE.md`: `mcauchy@192.168.1.57:~/dive-analyser`
  (Debian 12, `deb-serv`), branch `uiux-overhaul-pro-app`, HEAD verified via SSH on
  2026-09-09: `4b192dc0a90cc2ffb0ec85f334bb8ffc329a93e2`. No remotes on the server.
- The task packet's `/home/mcauchy/dive-analyser` path corresponds to that server repo.
  Fresh evidence: the Mac clone `~/dive-analyser` is in sync with the server HEAD
  (the Mac's `origin/uiux-overhaul-pro-app` tracking ref is stale but server
  `git rev-parse HEAD` returns the identical SHA).
- Concurrent threads observed (DO NOT TOUCH):
  - Mac worktree `~/.perso/diveanalyzer-perception` (scientific, HQ/perception thread).
  - Server untracked annotation work under `docs/science/localization_annotations_v1/`
    and `experiments/landmark_pilot/annotate_d5_server.py` etc.
- All findings below were traced in code on the Mac clone at the base HEAD; file:line
  references are against that tree.

## Terminology mapping to the packet

- The packet's `caption_raw` corresponds to the existing column name **`raw_caption`**
  (used in `dives`, `photos_assets`, `video_labels`, `captioned_media_catalog`,
  `dive_modifiers`). Semantic meaning is identical: exact primary human text.
- The packet's `PHOTOS_EDITED_RENDITION` corresponds to what osxphotos export
  produces for an asset (see §Rendition authority below).

---

# CURRENT

## 1. macOS ingestion agent map (`mac-agent/`)

### Entrypoint / orchestration

| Aspect | Evidence |
|---|---|
| Entrypoint | `mac-agent/src/main.py:284` `main()`; `asyncio.run(main())` `:354`. Flags `--config` (default `~/.diveanalyzer/config.yaml`), `--extract-only`, `--library-stats`. |
| Main loop | `run_sync_loop(config)` `main.py:138`. Blocks on `wait_for_network` (network.py:45) before starting workers. |
| Workers | `run_media_job_loop` (media_jobs.py:213, if `media.enabled`), heartbeat loop every 300s (`main.py:105`), `run_catalog_loop` (media_catalog.py:87, 60s), `run_source_cleanup_loop` (900s), metadata extraction loop (extractor.py:258-286, `sync.interval_seconds` default 300). |
| Transport | All HTTP via **curl subprocess** (`sync_client.py:1-6`, `:22-57`), because macOS Sequoia blocks LaunchAgent socket access (Errno 65). JSON + `X-API-Key` header; multipart for media upload (`:60-96`). |

### Photos discovery

| Aspect | Evidence |
|---|---|
| Mechanism | **osxphotos** library reading the Photos SQLite DB directly (`photos_reader.py:3`, `:22`). No PhotoKit for discovery; PhotoKit only as opt-in osxphotos export flag (`--use-photokit`, materializer). |
| Fresh reads | `_refresh_database()` (`photos_reader.py:51-65`) builds a new `osxphotos.PhotosDB(library_path)` before every scan to pick up new captions without restart. Library path from `config.photos.library_path` (default `~/Pictures/Photos Library.photoslibrary`, config.py:182). |
| Selection rule | `get_all_videos()` (`:80-118`): movies only (`photos(images=False, movies=True)`), non-empty caption (`:87`). **No album usage anywhere** — albums are an explicitly *forbidden* export selector (`media_materializer.py:220`). |
| Readiness rules | Readiness = caption present + parse succeeds (see caption). No "Ready" album exists; `"DiveAnalyzer Ready"` has **zero hits repo-wide**. The only album reference in the repo is the icloudpd album `Dive Analyzer` in `ops/icloud-video-sync.env.example:16` (Linux-side legacy path, separate from the Mac agent). |
| Health probe | Direct read-only sqlite probe of `Photos.sqlite` (`main.py:24-35`, `mode=ro`, `PRAGMA query_only`, count `ZASSET WHERE ZKIND=1`); TCC denial detected via PermissionError (`:57-59`) and surfaced in heartbeat (`photos_access_status`). |

### Caption retrieval / parsing

| Aspect | Evidence |
|---|---|
| Source | `photo.description` from osxphotos (photos_reader.py:87). Single validated caption provider path. |
| Transformations observed | `.strip()` applied at `extractor.py:125` (sync path) and `photos_reader.py:126` (catalog path). No Unicode normalization, no whitespace collapse, no punctuation rewriting. Case normalization only on parsed tokens (dive code `upper()` metadata.py:224, performance `:127`, label values `:196`). **Documented boundary: the LEGACY production path strips leading/trailing whitespace before persistence. REPAIR R1 note: this historical behavior is unchanged for the legacy path, but the NEW backbone caption authority (`CaptionRevision.caption_raw`) now persists the EXACT provider-returned string BEFORE any application-level strip (the strip lives only in `legacy_caption_transform`, legacy path only).** |
| State / dedupe | `~/.diveanalyzer/sync_state.json` uuid→`md5(caption)[:12]` (extractor.py:42, `:55-58`); atomic tmp+replace write (`:79-91`). Edited captions re-sync on hash change; server upsert is the dedupe backstop. |
| Dive grammar | `parse_dive_caption` (metadata.py:68-176): whitespace token split; token 1 = dive code `^\d{3,4}[A-D]$` or `BO`→`B` shorthand (`:217-253`); remaining tokens any order: height `^(1\|3\|5\|7\|10)m[p]?$` (defaults `1m`), `SYNC`, `SMACK`/`BELLY`, drills `{SD,DB,HU}`, performance `F\|B\|M\|G\|P` / 0-4 / two-phase `X/Y`, person-name rule. Requires ≥1 performance else None. |
| Label grammar | `parse_video_label` (metadata.py:179-214): single token → drill or person label. |
| Caption hash | MD5-12 of the stripped caption (`extractor.py:55-58`). Not sha256; server does not verify it. |

### Materialization / renditions

| Aspect | Evidence |
|---|---|
| Export | `MediaMaterializer` (media_materializer.py:45): `osxphotos export <dir> --uuid <uuid> --only-movies --download-missing --update --verbose` (`:106-120`); `--use-photokit` optional (`media.materialization_use_photokit`, default False, config.py:102). This is the only iCloud download path (`--download-missing`). |
| Selection | `_find_materialized_video` (`:122-148`): recursive scan, extensions {.mov,.mp4,.m4v,.avi,.hevc}, rejects <16 KiB and > `materialization_max_bytes` (2 GB default), **picks the largest**. |
| Hardening | UUID regex validation; path containment (`:66-68`); argv list forbids `--album/--folder/--keyword/--person/--query/--regex/--selected` and enforces exactly one `--uuid` (`_validate_command`, `:211-224`); 600s subprocess timeout with terminate→kill (`:85-96`); failure classification incl. TCC markers (`:239-269`). |
| Resolver | `MediaExporter.resolve_local_asset` (media_exporter.py:41-108): source vault → Photos local path → manual override → single-asset materialization (then vault import + dedupe delete). `source_for_job` blocks `original` rendition unless `allow_original` (`:118-119`). |
| Rendition authority | osxphotos `export` without `--skip-edited` exports the **edited rendition when an edit exists** (osxphotos documented behavior); the vault "source" is therefore the user's edited/trimmed representation. **No code path selects `ORIGINAL_CAMERA_MASTER` for production artifacts.** `media.allow_original=false` by default (config.py:96) further guards this. (The P0 science thread separately established that for the HQ corpus, "original" exports were byte-identical to edited renditions — Phase A `ORIGINAL_MASTER_NOT_INDEPENDENTLY_PROVEN` — so rendition provenance recording in the new backbone is mandatory, see TARGET doc.) |
| ffprobe/ffmpeg | `Transcoder` (transcoder.py:29): poster @1s JPEG; proxy_360p/720p libx264 + bt709 + faststart, audio only when ffprobe finds a real stream (`:95-127`); SHA-256 checksum per artifact (`:151-156`). |
| Cache/temp | `media.temp_dir` default `~/.diveanalyzer/media_tmp` (config.py:105); materialization dir `~/.diveanalyzer/materialized_assets`; failed exports retained 24h by default (`retain_failed_materialization`). |
| Free-space gates | media_jobs.py:53-66: internal disk < `internal_stop_free_bytes` (18 GiB default) → stop; vault < 5% → stop. Catalog floor = 22 GiB legacy / `internal_warning_free_bytes` 35 GiB (media_catalog.py:18-33). Vault tiers warn/pause/auto-pause/stop = 35/30/24/18 GiB defaults (config.py:53-56). These ARE the current `min_free_disk`-family guards. |

### Upload

| Aspect | Evidence |
|---|---|
| Metadata | `POST /api/v1/videos/sync` (sync_client.py:336) with parsed fields + `raw_caption` + `caption_hash` + `cloud_guid` (extractor.py:161-181). |
| Media | Lease-based job pipeline: `POST /api/v1/media/jobs/lease` → upload multipart `/api/v1/media/jobs/{id}/upload` (fields `agent_id, checksum_sha256, size_bytes, file`) → `/finalize` (sync_client.py:634-686). Artifact deleted after upload (media_uploader.py:18). |
| Retries | `sync_video` retry loop: ≤3 attempts, exponential 1s→30s; non-retryable 400/401/403/409; 429 → 60s client rate-limit window (sync_client.py:147-209, `:361-365`). |
| Idempotence | Dedupe key = `video_uuid` (server 409/upsert). Media: `checksum_sha256`+`size_bytes` verified server-side on upload (media.py:961-981). Job lease expiry + 45s materialization keepalive (media_jobs.py:25, `:168-185`). |

### State persistence / crash recovery

- Live state: `~/.diveanalyzer/sync_state.json` only. Media job state lives **server-side** (lease/status columns in `media_jobs`).
- `crash_recovery.HeartbeatManager` and `queue.VideoQueue` are **dead code** (not imported by main.py or tests).
- No local SQLite DB on the agent; sqlite3 appears only as the read-only health probe.

### Source vault

- `MediaSourceVault` (source_vault.py:36): per-UUID `<root>/<UUID>/source<ext>` + JSON sidecar on validated external APFS volume (volume-UUID check via `diskutil`, `:54-74, :329-353`). `.partial` copy + SHA-256 verify + atomic rename (`:133-138`). Retention classes permanent/recent(30d)/temporary/diagnostic/failed/quarantine; cleanup only after `durable_outputs_verified` (poster+proxy finalized), bounded per run (`cleanup_max_items=20`, `cleanup_max_bytes=5 GiB`). Default root `/Users/Shared/services/data/media-node/recalled_sources/by_uuid` (config.py:50).

### Runtime / TCC / deployment

- LaunchAgent in **GUI (Aqua) domain** `gui/$(id -u)` (install.sh:17, `:199`); plist `~/Library/LaunchAgents/com.diveanalyzer.agent.plist`; `KeepAlive.SuccessfulExit=false`, `ThrottleInterval=30`.
- Production plist `mac-agent/deploy/com.diveanalyzer.agent.mac-media-01.plist`: interpreter `/Users/Shared/services/data/diveanalyzer/venv/bin/python`, config `/Users/Shared/services/data/diveanalyzer/state/config.yaml`, WorkingDirectory `.../code`, PATH prepends `/Users/Shared/services/data/diveanalyzer/bin` (matches the packet's expected runtime; **the packet's "DiveSensei Python Runtime.app" / `com.diveanalyzer.python-runtime` bundle has zero hits in the repo — treated as stale/external hypothesis, see DEVIATIONS**).
- TCC model: interactive "Photos privacy rehearsal" as GUI user `divesensei`, accept privacy prompts, verify via backend heartbeat `photos_access_status=ok` (docs/mac-media-node-operations.md:3-13). Do NOT replace with SSH-launched PhotoKit.
- Host/user hypothesis `mac-server.home` / `divesensei` consistent with PROJECT_STATE topology table (Machine B @ 192.168.1.19).

### mac-agent tests today

- `tests/test_metadata.py` (parser), `test_media_safety.py` (480 lines: materializer hardening, config defaults, proxy cmd shape, cleanup semantics), `test_source_vault.py`, `test_sync_client.py` (curl contract), `test_media_catalog.py`. Gaps: main loop, photos_reader, media upload endpoints, extractor state file.

## 2. Server map (`backend/`)

### Identity

- Logical clip identity chain: **`dives.video_uuid` (String(100) UNIQUE, dive.py:52) ↔
  `photos_assets.video_uuid` (UNIQUE canonical, photos_asset.py:22) ↔ per-agent local
  identity `photos_asset_agent_identities.local_uuid` (unique per `(agent_id, local_uuid)`)
  ↔ `captioned_media_catalog.agent_local_uuid`**. `cloud_guid` is provenance (not unique).
- This IS an application-owned stable clip identity (`video_uuid`); Photos asset ids are
  provenance locators, matching packet doctrine.

### Tables / caption storage

| Table | Key columns (file:line) |
|---|---|
| `dives` | `id`, `video_uuid` UNIQUE, `photos_asset_id` FK, `raw_caption` Text (dive.py:49), parsed columns (`dive_code`, `height`, `phase1/2_performance`, `is_sync`, `is_smack`, `person_name`), `video_filename`, `video_path` (legacy, not source of truth), `synced_at`, `official_dd_migration_id` FK |
| `photos_assets` | `video_uuid` UNIQUE, `cloud_guid`, `raw_caption` (:39), `caption_hash` (:40), `metadata_fingerprint`, `photos_path`, `local_available/is_missing/icloud_status`, `duration_seconds/width/height/file_size_bytes` |
| `video_labels` | non-dive captions: `video_uuid`, `label_type`, `label_value`, `raw_caption`, unique `(video_uuid, label_type, source)` |
| `media_cache_entries` | `media_key` UNIQUE (sha256 of `uuid:rendition:transform_version:export_policy_version`, services/media_keys.py:8-17), `rendition` (poster/proxy_360p/proxy_720p/original), `storage_backend` default **"local_fs"**, `storage_path`, `checksum_sha256`, `status`, `pinned`, `expires_at` |
| `media_jobs` | job state machine `queued→waiting_for_mac→claimed→materializing→…→ready/failed`, lease fields, `upload_tmp_path`, `output_checksum_sha256` |
| `captioned_media_catalog` | `agent_local_uuid` (unique per agent), `canonical_video_uuid`, `raw_caption` NOT NULL, `canonical_dive_code`, state flags, `metadata_json` (holds agent-supplied `parsed_metadata`) |
| `recalled_media_sources` | `video_uuid`, `source_path`, `volume_uuid`, `checksum_sha256` NOT NULL, `retention_class`, `expires_at` |
| `migration_logs` | data-migration bookkeeping with `rollback_snapshot` JSON |

### Migrations framework

- **Not Alembic in practice.** Raw SQL files in `backend/migrations/` with additive
  idempotent patterns (`CREATE TABLE IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`);
  `init.sql` auto-applied on first Postgres boot via docker-compose
  (`docker-entrypoint-initdb.d`). `alembic==1.12.1` is an unused requirements line.
- Tests use **in-memory SQLite + `Base.metadata.create_all`** (conftest.py:21, 81-149);
  SQL migration files are not exercised by tests today.

### Upload / duplicates

- `POST /api/v1/videos/sync` (videos.py:373-478): **upsert, not 409** — `_upsert_synced_dive`
  (videos.py:188-230) finds by `photos_asset_id` then `video_uuid`; same clip twice =
  `created=False, updated=…`; one commit per sync (`:415`). First canonical `video_uuid`
  kept (`:222-223`).
- Media binaries: chunked multipart upload verified by size + `sha256_file` (media.py:961-981);
  temp `media_cache_root/tmp/job-{id}-{key}.partial`; final sharded path
  `{root}/{rendition}/{key[:2]}/{key[2:4]}/{key}{ext}` (media_cache.py:95-102, chmod 0644
  so the nginx front doors can byte-serve via X-Accel-Redirect);
  promote is a no-op for duplicates (`media_cache.py:150-153`).

### Serving / auth

- Modern: `GET /api/v1/media/cache/{entry_id}/play` (media.py:852-866) → manual HTTP-Range
  `StreamingResponse` (`:178-229`); path-inside-cache-root realpath guard (media_cache.py:62-84).
- Legacy: `GET /api/v1/videos/{video_uuid}` (videos.py:604-704): FileResponse probing
  `/videos/` and `/photos_library/` mounts, or 307 redirect to `playback_url`.
- Frontend: `DiveVideoPlayer.tsx` calls `GET /api/v1/media/{uuid}/status` and uses the
  server-returned `playback_url` — video URLs are server-generated; nothing hardcodes paths.
- Auth: `verify_api_key` (security.py:11-36, `X-API-Key` vs `MAC_AGENT_API_KEYS`) on
  agent-write endpoints only. **No user/athlete auth middleware exists**; athlete scoping
  is a query param (`diver_scope`) on media listing endpoints. LAN-only deployment.

### Deletion

- `DELETE /api/v1/dives/{id}` / `sessions/{id}`: DB cascade rows only; **no media file
  cleanup** on dive deletion. File deletion only via cache lifecycle (`cleanup_cache`,
  `_remove_entry_file`) and vault retention.

### Config / secrets

- pydantic-settings `Settings` (config.py:13-17, `.env`, `extra=ignore`) + `os.getenv`
  defaults; `get_settings()` lru_cached. `MAC_AGENT_API_KEYS`, `DATABASE_URL`,
  `MEDIA_CACHE_ROOT` (`/app/media-cache`), `MEDIA_TRANSFORM_VERSION`,
  `MEDIA_CACHE_MAX_BYTES`, `NEW_VIDEO_AUTO_MEDIA_ENABLED`. Secrets only via
  docker-compose env substitution — server-side only.

## 3. Answers to the packet's explicit server questions

```text
How is a clip identified now?
  dives.video_uuid (canonical, mirrored unique on photos_assets.video_uuid),
  with per-agent local_uuid mapping and cloud_guid provenance.

Where is caption source-of-truth now?
  dives.raw_caption (primary app row) + photos_assets.raw_caption (cache row);
  agent-supplied caption_hash (MD5-12) recorded but NOT verified server-side.
  captioned_media_catalog.raw_caption is a catalog snapshot. Append-only caption
  history does NOT exist today — caption change overwrites in place (upsert).

What media representation does the server receive?
  Posters/proxies/original generated by the agent (Transcoder) from the vault/
  materialized source (edited rendition semantics, see §Rendition authority);
  uploaded multipart per media job; verified by size+sha256 at upload; stored
  under MEDIA_CACHE_ROOT sharded by media_key.

What happens when the same clip is seen twice?
  Metadata: upsert (created=False). Media: media_key unique; duplicate promote
  no-op; active-job partial unique index prevents duplicate jobs.

What does the home server need on local disk for playback?
  MEDIA_CACHE_ROOT renditions (proxies/posters) — serving reads only from
  media_cache_entries.storage_path (realpath-guarded) with legacy fallback to
  /videos and /photos_library read-only mounts.

What tables/fields can be extended additively?
  photos_assets (provenance), media_cache_entries (storage_backend already
  exists as a column → object-store backend can be an additive value),
  captioned_media_catalog, and new packet tables (blobs/revisions) as new
  additive tables without touching legacy columns.
```

## 4. Repo-wide negative-space findings (fresh evidence)

- `"presign"`, `"B2"`/`"backblaze"`, `"object storage"`, `"DiveAnalyzer Ready"`:
  **zero hits** anywhere in the repo. Nothing exists yet for this packet — fully greenfield
  additions are appropriate and additive-only.
- `DiveSensei Python Runtime.app` / `com.diveanalyzer.python-runtime`: zero hits
  (see DEVIATIONS in the final report).

## 5. Known risks in current architecture (ranked)

1. **Caption overwrite semantics**: caption change today mutates `dives.raw_caption`
   in place; no history. Packet requires append-only revisions → new additive table,
   legacy behavior untouched.
2. **caption_hash not verified server-side** (agent-computed MD5-12 of stripped text).
   New backbone uses SHA-256 over exact persisted UTF-8 bytes; legacy hash untouched.
3. **`.strip()` at the agent boundary** — the raw→persisted boundary is
   stripped-raw. The backbone must hash the exact persisted representation and must
   not re-normalize; changing the agent's strip behavior is out of scope (would
   alter production upload payloads).
4. **Serving depends on server-local MEDIA_CACHE_ROOT** — single-disk dependency
   (mitigated by vault/proxy architecture, but still the playback path).
5. **No athlete-facing auth** on media endpoints (LAN trust model) — presigned-URL
   future must not loosen this.
6. **Dead code** (`VideoQueue`, `HeartbeatManager`) may mislead future maintainers —
   do not build on them.
7. **Docs drift** on free-space thresholds (docs/media-source-vault.md vs config.py
   defaults vs config.example.yaml).

---

# TARGET

See `MEDIA_BACKBONE_TARGET_V1.md` (companion doc). Summary: additive
`MediaBlob` / `MediaRevision` / `CaptionRevision` server tables + agent-side
`IngestCoordinator` state machine with JSON-persisted resumable state,
`ObjectStore` abstraction (`FakeObjectStore` for tests, `BackblazeB2Store`
adapter ready for DEV credentials), content-addressed keys
`blobs/sha256/<2>/<sha>`, verified-ingest roundtrip rule (local SHA == remote
full-GET SHA), and a hard-off-by-default `OBJECT_STORE_INGEST` flag leaving all
production paths byte-identical.

# REUSE

- `mac-agent/src/media_materializer.py` — export machinery (targeted single-UUID,
  iCloud download, hardening) reused as `MediaMaterializer` seam.
- `mac-agent/src/photos_reader.py` — `PhotosSource` seam (fresh-DB scan semantics).
- `mac-agent/src/extractor.py` + `metadata.py` — stable caption authority + parser
  (`CurrentStableCaptionProvider`).
- `mac-agent/src/transcoder.py`, `media_exporter.py`, `source_vault.py` — untouched.
- `backend/app/models/media.py` `MediaCacheEntry.storage_backend` — already a
  text column; additive "b2_dev"/"b2_prod" values are compatible with future serving.
- `backend/app/services/media_cache.py` `sha256_file` pattern; migration SQL
  idempotent style; conftest in-memory SQLite pattern.

# REFACTOR

- None required in P1. New ingest backbone is implemented **beside** legacy code
  behind a feature flag; the `LegacyServerSink` seam is documented
  (see TARGET §Seams) rather than forced into the live upload path.

# DEPRECATE_LATER

- `mac-agent/src/queue.py` (`VideoQueue`) and `mac-agent/src/crash_recovery.py`
  (`HeartbeatManager`) — dead code; candidate for removal in a later packet
  (not removed here to keep the diff strictly additive).
- `mac-agent/src/photos_reader.py get_videos_since` (dead path).
- `MediaConfig.allow_icloud_download` (parsed, never consulted).
- Legacy `/api/v1/videos/{uuid}` FileResponse probing path (future P6/P7).

---

# Science authority firewall

- Inspected read-only: `docs/PROJECT_STATE.md` science sections,
  `docs/science/*` references, `experiments/landmark_pilot/` layout, HQ media root
  references (`/Users/Shared/services/data/media-node/highres_analysis_source_v1/`).
- Nothing under `experiments/`, `docs/science/`, frozen artifacts, detector/Event
  Logic/PTS authority was modified by this packet. The new backbone stores
  *application* (athlete-visible) media bytes only and explicitly does NOT
  intersect the HQ analysis-source corpus or any frozen evaluation artifact.
- `PRODUCTION_ANALYSIS_REPRESENTATION_REMAINS_PROXY_360P` untouched.

# Dependency map (media-relevant)

```text
Photos library (iCloud, Optimize Storage ON)
  → osxphotos read (discovery/caption)
  → osxphotos export --download-missing (materialization, edited rendition)
  → vault import (.partial+sha256+rename)
  → Transcoder (ffmpeg/ffprobe → poster/proxy)
  → curl multipart upload → media_cache_entries (local_fs) → HTTP Range serving
Metadata: caption → parser → /videos/sync upsert → dives/photos_assets
```

Object-store backbone inserts **beside** the last two media steps only, behind
the feature flag, without duplicate Photos/iCloud downloads (the coordinator
consumes the same materialized bytes and hashes them once).
