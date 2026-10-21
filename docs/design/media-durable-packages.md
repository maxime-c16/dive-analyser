# Media durable packages (`hq` / `light` / `poster`) — concrete build plan

> D1 AMENDMENT (2026-10-21, implementation slice `t3/durable-media-foundation`):
> this doc's D1 summaries disagreed — §9 calls D1 "publish- and read-inert"
> while the D1 bullet lists the `persist_derivative` B2 network publisher
> and a `MEDIA_TRANSFORM_VERSION` default change. The implemented D1 resolves
> the contradiction explicitly:
> - **No `persist_derivative`.** The B2 upload→roundtrip-verify→commit
>   publisher is deferred to the publication slice (after D2 lease fencing;
>   D3). D1 contains no network publisher, no jobs, no routes.
> - **No `MEDIA_TRANSFORM_VERSION` change.** The legacy default stays
>   `ffmpeg-h264-v1` so existing cache/job keys are byte-identical. New
>   derivative keys use a SEPARATE setting
>   `MEDIA_DERIVATIVE_TRANSFORM_VERSION` (default `ffmpeg-h264-web-v1`).
> - **Selector change = derivative exclusion only.** The shared policy
>   excludes `derived_*` (prefix) on top of each selector's existing
>   filter — a strict no-op until derived rows exist. Playback selectors
>   keep excluding `browser_original`; the transcode source keeps including
>   it (true camera bytes, no quality regression).
> - **`finalized_slots` ships NULL-default** (not `DEFAULT '[]'`): NULL =
>   no slot finalized yet; avoids PG JSON-default quirks. Old code ignores
>   both new job columns.

Source: `docs/reviews/media-paths-audit-2026-10-21.md` (+ `media-quality-tests-2026-10-21.md`
§6 contract / §4 bench [M] / §7 Q1–Q7). Codebase state: `9322dc0` (#134 + #135
merged, deployed server + Mac). This doc is the engineering plan, not a new
audit. Target contract (unchanged): per clip (`video_uuid`) and per source
revision (`blob_sha256`):

| Role | Transform (one shared pass) | Served as |
|---|---|---|
| `hq` | H.264 High, 8-bit SDR BT.709 tone-mapped, short side min(source,1080), source fps (`-fps_mode passthrough`), CRF 23, `maxrate` 12M, GOP 1s, AAC from first **decodable** audio track, faststart | Opened clip, jury, slow-mo |
| `light` | Same chain, short side 720, CRF 23 | Start, preload of neighbours, Save-Data/cellular, grid hover |
| `poster` | JPEG SDR tone-mapped, from the same pass | Grids |
| `original` | Unchanged bytes (camera HEVC/HDR) | Explicit "Original" + download |

Rules carried over from the quality annex: no conversion at click, no
upscale, `hq`+`light` produced in one decode/tone-map pass, server backend is
only a slow bounded fallback for `light`. Existing #134 retention
(`protect_browser_safe_cache_entries.sql`, `SOLE_COPY_*` / `CLEANER_RETAINED_*`
in `backend/app/services/media_cache.py`) is **untouched** by this plan: legacy
`proxy_720p`/`poster`/sole-`360p` rows stay pinned + cleaner-excluded until a
durable derivative replaces them.

## 1. Transform version + rendition identity

- `MEDIA_TRANSFORM_VERSION` default becomes `ffmpeg-h264-web-v1`
  (`backend/app/config.py:45`). Meaning: "this exact filter/encode chain for
  `hq`/`light`/`poster`" (zscale→hable→BT.709, scale short-side, High@CRF23,
  GOP 1s, faststart, AAC). Any filter/CRF/profile change bumps it; a bump
  retires the old derivation identity (see §5), it never rewrites bytes.
  > D1 AMENDMENT: NOT implemented in D1 — the legacy default stays
  > `ffmpeg-h264-v1` (changing it would invalidate existing cache/job
  > keys). The web-chain version lives in the SEPARATE
  > `MEDIA_DERIVATIVE_TRANSFORM_VERSION` setting (same default value,
  > new keys only). This bullet describes the intended end state, not D1.
- Cache keys: legacy `build_media_key` (`backend/app/services/media_keys.py`)
  is **not** changed (old rows/jobs keep working). New function
  `build_derivative_media_key(video_uuid, role, source_sha256, transform_version)`
  = `sha256("derivative-v1|" + video_uuid + "|" + role + "|" + source_sha256
  + "|" + transform_version)`. Derivation identity is therefore
  `(video_uuid, source_blob_sha256, role, transform_version)` — this also
  fixes F18 (preview untied to source version) for the new renditions; legacy
  rows keep their old keys and their #134 pinning.
- Audio rule (fixes Q2 on both producers): never `-map 0:a:0?`. Probe and map
  the first audio stream with a usable decoder — same rule as the Mac's
  `_real_audio_stream_index` (`mac-agent/src/transcoder.py:138`), extended
  with a decoder denylist containing `apac` (iPhone spatial audio, no ffmpeg
  decoder in 8.1.2 — Q2 repro). The server producer (`browser_upload.py:63`)
  gets the same selector; add a regression test running the exact Q2 command
  shape against a fixture probe JSON with an `apac` first track.
- Portrait rule (fixes Q1): scale on the **short side** — portrait
  `scale=<short>:-2` (width-fixed, e.g. `scale=720:-2` → 720×1280),
  landscape `scale=-2:<short>` (height-fixed, e.g. `scale=-2:720` →
  1280×720) — computed from display (rotation-adjusted) dimensions, never
  the legacy `scale=-2:720` height-fixed-for-everything shape that produced
  406×720 portrait previews. D3a implements this as explicit even W:H dims
  under the same short-side rule (long side proportional, ceil-to-even,
  stepped down if the ceil overshoots the source). No upscale: source short
  side < 720 gets `light` only (= source size, still tone-mapped/SDR/
  faststart); source short side < 1080 gets no distinct `hq` (reported
  honestly as absent-aliased-to-light, never a duplicate encode).

## 2. Schema (additive; manual SQL, see §7)

New table `media_derivatives` — the durable-derivative ledger. One row per
derivation, content linked by SHA (uniform with the backbone: blobs in
`media_blobs`, replicas in `media_blob_locations`, committed through the same
verify-then-commit path):

```sql
CREATE TABLE media_derivatives (
  id SERIAL PRIMARY KEY,
  video_uuid VARCHAR(100) NOT NULL,
  source_blob_sha256 CHAR(64) NOT NULL,
  role VARCHAR(20) NOT NULL CHECK (role IN ('hq','light','poster')),
  transform_version VARCHAR(40) NOT NULL,
  derivative_blob_sha256 CHAR(64) NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'verifying'
    CHECK (status IN ('verifying','ready','stale','superseded')),
  verified_at TIMESTAMPTZ NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT uq_media_derivative_identity UNIQUE
    (video_uuid, source_blob_sha256, role, transform_version)
);
CREATE INDEX ix_media_derivative_clip_role
  ON media_derivatives (video_uuid, role, status);
```

- Derivative bytes are committed with the **existing**
  `commit_verified_ingest(..., verified=True)` (roundtrip-verify first, §4)
  using new `rendition_semantics` values `derived_hq` / `derived_light` /
  `derived_poster`. No change to `MediaBlob` / `MediaBlobLocation` /
  `MediaRevision` columns.
- Consequence, handled in the same PR as the schema (D1): every
  "original-selection" site currently excludes only `browser_original` and
  would otherwise pick up a derivative revision as the "original". Harden
  with the shared derivative-exclusion policy
  (`derived_semantics_exclusion_clause`, prefix `derived_*`, in
  `app/services/media_backbone.py`) applied ON TOP of each site's existing
  filter at: `backend/app/api/v1/media.py::_backbone_playback_url` (+
  `_backbone_revision_ids_bulk`), `matchmaking.original_revision_id`,
  `evaluation_access.backbone_originals`, `media_jobs._b2_source`,
  `dive_sharing.guest_video`, `clip_downloads.download_clip`. This is NOT
  a camera-original allowlist: playback selectors keep their existing
  `!= 'browser_original'` exclusion, while the transcode source
  (`_b2_source`) and the newest-revision picks (guest/download) keep
  serving every non-derivative semantic — including `browser_original`,
  the true camera bytes for browser clips (using the already-transcoded
  `browser_playback` as the transcode source would be a quality
  regression). With no `derived_*` rows the clause is a strict no-op; any
  future read-behavior change beyond derivative exclusion needs an
  explicit parent decision, not an invented policy.
- `media_cache_entries`: two **nullable** columns (backward compatible,
  legacy rows keep NULL = pre-derivative stock, served under #134 rules
  until replaced):
  `source_blob_sha256 CHAR(64) NULL`, `transform_version VARCHAR(40) NULL`.
  Read path serves an `hq`/`light`/`poster` row only if its
  `source_blob_sha256` matches the clip's current newest verified original
  revision (or the row is legacy-NULL). Legacy `proxy_720p` handling is
  unchanged.
- `media_jobs`: two columns for publication integrity (§3):
  `lease_token CHAR(36) NULL`, `finalized_slots JSON NULL DEFAULT '[]'`.
  (`source_blob_sha256` for the job is already derivable at lease time via
  `_b2_source`; the leased payload gains `source_sha256`,
  `transform_version`, and per-slot media keys — §3.)

## 3. Publication integrity: lease fencing, keepalive, ffmpeg timeout

F12 (`media_jobs.py`, `media.py` lease/heartbeat/upload/finalize routes,
`mac-agent/src/media_jobs.py`) — required before any durable publish:

- **Fencing.** `lease_media_jobs` sets `lease_token = uuid4().hex` on claim
  (and on every reclaim after expiry). The token is returned in the leased
  payload. `heartbeat_media_job`, `mark_job_uploaded`, `finalize_cache_entry`
  (and the three HTTP routes) require **both**
  `claimed_by == agent_id` **and** `lease_token == request token`; mismatch →
  409 `media_job_lease_token_mismatch`, no state change. A job re-leased to
  the same agent after expiry invalidates the stale attempt's token: the
  late heartbeat/upload/finalize of the dead attempt is rejected instead of
  resurrecting it. Reclaim (`reclaim_expired_media_jobs`) clears the token
  alongside `claimed_by`.
- **Keepalive scope.** The Mac's keepalive today covers only Photos
  materialization (`_keep_materialization_lease_alive`). Extend it to the
  whole `_process_job` (materialize + transcode + upload): one keepalive task
  spanning the job, cancelled in `finally`. Server: every accepted heartbeat
  extends `claimed_until` by +5 min (unchanged) and the heartbeat route
  accepts the `transcoding`/`uploading` statuses for package jobs.
- **ffmpeg timeout.** `Transcoder.build` gains a hard timeout
  (`asyncio.wait_for`, default 2700 s, env-overridable, kill-on-timeout);
  timeout → job `failed` with `ffmpeg_timeout`, temp artifacts removed. Same
  bound for the server fallback producer. No unbounded subprocess, ever.
- **`asyncio.gather` (F13).** `process_once` uses
  `gather(..., return_exceptions=True)` so one slot's crash cannot silently
  free a second concurrent slot; exceptions are logged and counted.

Package-job shape (Mac primary producer): the schedulable unit for web
renditions becomes one job with `rendition='web_package'` (queued by
ingestion in place of poster+720p — `videos.py:_queue_new_captioned_media` —
and by interactive prepare). The lease co-schedules the triple implicitly
(one job, one source download, one ffmpeg pass with split outputs reusing
`single_pass.py` from the quality annex: one decode + tone-map, two x264
encodes + JPEG). Three sequential upload→finalize cycles run against the
same `job_id` with a `slot ∈ {hq,light,poster}` field (upload + finalize
requests gain `slot`; `finalized_slots` accumulates; `mark_job_ready` only
when all three slots — or the applicable subset for small sources, recorded
in the job — are finalized). Each slot maps to its own cache entry
(`rendition` = slot, `media_key` = per-slot derivative key, `source_sha` +
  `transform_version` stamped). If the source is smaller than a role's floor
  (§1), that slot is recorded `skipped_small_source`, not failed.

## 4. Dual-write publish + partial-failure recovery (no stale publish)

Per slot, in order (Mac package job and server fallback share the sequence;
server fallback does `light` only):

1. Transcode slot artifact → sha256 + size.
2. Upload bytes to PROD bucket under
   `<prefix>/derived/<source_sha[:2]>/<role>-<transform>-<sha>` with
   `Content-Type` (`video/mp4` / `image/jpeg`) + `Metadata: {sha256}`.
3. **Roundtrip verify**: ranged GET the object back, compare sha256 + size
   (same pattern as `persist_original` in `browser_upload.py:119`).
4. Commit (one DB transaction): `commit_verified_ingest` (blob + verified
   location + revision with `derived_*` semantics) + upsert
   `media_derivatives` row → `ready`. **Nothing is marked ready before step
   3.** Factor step 2–4 into `persist_derivative()` next to
   `persist_original`.
5. Upload slot artifact to the cache tmp path → finalize cache entry
   (existing `finalize_cache_entry` + slot stamping).

Recovery (idempotent by construction):

- B2 upload OK, crash before commit → retry re-uploads same bytes (content
  key) and re-verifies; `_get_or_create_location` dedupes the replica row;
  derivative upsert is on the unique identity → safe to replay.
- Derivative committed, cache finalize failed/lost → read path serves B2
  directly (§6); a bounded repair pass re-seeds cache entries from ready
  derivative rows (no re-transcode).
- Source revision changed mid-job (new `MediaRevision` for the clip landed
  after lease): at finalize time the worker's `source_sha256` ≠ current
  newest original → slot rows are committed as `stale`, never `ready`, and a
  package job for the new source is enqueued. The previous `ready`
  derivatives keep serving until the new ones verify — new sources
  invalidate, they never black out.
- Revision invalidation rule: when a new verified original revision appears
  for a clip, existing `ready` derivatives of the old source flip to
  `stale` (still served, flagged in the status payload) and a package job
  for `(new_source)` is queued at backfill priority. When the new
  derivatives go `ready`, old rows flip to `superseded` (kept, not served,
  explicit retirement later — never the generic cleaner).

## 5. Read path: one backend selection, private grants, cache as LRU

- New route `GET /media/derivatives/{id}/play` mirroring
  `media_playback.py::play_media_revision`: `can_user_access_video` on the
  derivative's `video_uuid` (uniform 404 on deny, nothing logged but the
  grant ledger), newest `ready` (else `stale`) derivative row for
  (clip, role), `_resolve_verified_prod_location`-equivalent on the
  derivative SHA, provider HEAD proof, presign (same
  `media_playback_presign_ttl_seconds` 120 s default, `no-store` 302), grant
  ledger row with the derivative id. Private clips stay private; deposit
  hold semantics reuse `_dive_access` (no new auth model). Range/seek/304
  are between Safari and B2 on the presigned URL — the backend never proxies
  bytes. The 120 s expiry during long plays stays a known H: clients refresh
  via status (same as originals today), no silent change.
- Status contract (extends `_status_for_asset` + batch +
  `evaluation_access.media_status`, one shared helper):
  `recommended ∈ {hq, light, original}`, `start` (default `light`; `hq`
  directly once the §8 device protocol picks a policy),
  `alternatives[]`, `readiness: {original, web}`, worker state
  (last heartbeat age + pause reason — reuses `operations_status.py`).
  All readers (Library grid/player, jury, automatic, representatives,
  guest) consume this instead of local precedence hacks (resolves F8).
- Grid: poster → `light` → placeholder. **Never the original in a tile**
  (F3). Player: if no web derivative/cache ready, auto-request a package
  job at interactive priority (5) even when the original is `ready` (F4/F5),
  with an honest "preparing compatible version" state; the HLG-black
  watchdog (no frame after N s while audio advances) is client-side and
  out of scope for the backend slices. Guest share (`dive_sharing.py:206`):
  web derivative first, original only as explicit link (F10).
- Consumers accept the new world: `_ready_clause` (matchmaking),
  `evaluation_queue._PLAYABLE_RENDITIONS`, `representative_media`
  (`REQUIRED_RENDITIONS` → poster + hq/light with legacy 720p/360p as
  fallback), `media_catalog` readiness, `dive_analysis_service` proxy pick,
  `evaluation_access.prepare_media` (request `web_package` at 5 / poster
  line removed — poster is a slot), `media_recall` states. Legacy
  `proxy_720p`/`proxy_360p` rows remain readable fallbacks; **no new 360p**
  (already true since #135).
- Cache becomes a pure LRU shortcut **for web renditions only after a
  durable derivative verifies**: cleaner rule addition — an
  `hq`/`light`/`poster` row with non-NULL `source_sha` is evictable only if
  a `ready` derivative row exists for
  `(video_uuid, source_sha, role, transform)`. Until then it is retained like
  #134 stock. Legacy-NULL rows keep the exact #134 behavior (no change to
  `SOLE_COPY_*` / `CLEANER_RETAINED_*` / the stock migration).
- Vault (`source_vault.mark_media_ready`): `proxy_ready` is set by any web
  rendition completion (`hq`/`light`/`proxy_720p`/legacy `360p`), unblocking
  the 12.55 Gio cleanup (F7) without reintroducing 360p production.

## 6. Sequenced PRs (small, each shippable; local commit → parent reviews)

All PRs: tests first where behavior changes, manual-SQL-before-deploy where
schema changes (per `docs/REPO_WORKFLOW.md`; data-only SQL stays code-first
per the #134 exception rule). User-visible PRs carry an immutable
`backend/release-notes/` JSON; internal ones state `Release notes: none`.

- **D1 — Derivative ledger + transform identity (FOUNDATION, first slice,
  §9).** Migration `add_media_derivatives.sql` (table §2 + nullable columns
  on `media_cache_entries` / `media_jobs`) + models +
  `build_derivative_media_key` (new separate
  `MEDIA_DERIVATIVE_TRANSFORM_VERSION`, legacy `MEDIA_TRANSFORM_VERSION`
  untouched) + shared original-selector policy (derivative-exclusion only,
  §2 site list) + unit tests (key determinism, exclusion is a no-op for
  legitimate semantics, ledger idempotency). No `persist_derivative`
  (deferred to the publication slice after D2 fencing), no producer, no
  read-path behavior change. Manual SQL **before** deploy (schema
  dependency). See the D1 AMENDMENT at the top of this doc for the
  resolved inert-scope contradiction.
- **D2 — Lease fencing + keepalive + ffmpeg timeout (F12/F13).**
  `lease_token` issue/verify on all four routes, extended Mac keepalive,
  `Transcoder` timeout, `gather(return_exceptions=True)` + tests
  (stale-attempt heartbeat rejected after re-lease; timeout kills ffmpeg).
  No schema beyond D1 columns. Internal-only.
- **D3 — Mac package producer (hq+light+poster, single pass).**
  `web_package` job type, bundle finalize slots, `persist_derivative` per
  slot, APAC-safe audio selection, short-side scaling, vault `proxy_ready`
  on web completion, `_B2_SOURCE_RENDITIONS` + `_export_options` for the new
  jobs, ingestion queues package instead of poster+720p. Tests: single-pass
  artifact assertions (dimensions/fps/transfer/faststart/GOP/audio present).
  Manual SQL: none (D1 applied). User-visible note (quality + reliability).
- **D4 — Server bounded fallback (light only).** One-at-a-time background
  worker (advisory lock, nice), only when Mac absent > X min and request
  interactive, same publish sequence (§4) incl. APAC fix in the server
  chain. Never in request path. Tests + concurrency cap test.
- **D5 — Single read contract + consumer cutover.** Status helper
  (`recommended`/`start`/`alternatives`/`readiness`/worker), derivative play
  route + grants, grid/player/jury/guest/representatives/catalog/eval
  cutover, `POST status`/`request` authZ via `can_user_access_video`
  (F15), guest web-first. Highest review surface; split further if needed
  (D5a status+grid+player, D5b jury/eval/reps/catalog/guest+authZ).
- **D6 — Invalidation + LRU + backfill.** Stale/supersede transitions,
  cleaner evictability rule for new rows, bounded backfill worker (package
  jobs at priority ≥ 60, resume-able, vault-threshold stops), 360p verified
  retirement (explicit, serializes with replacement — the deferred
  `retire_verified_proxy_entry` path), legacy docs update
  (`MEDIA_CLOUD_READINESS.md` vs `LIBRARY_PLAYBACK.md`, F19).
- **D7 — Measurement protocol (§8) + rollout validation.** Client
  instrumentation (TTFF, stalls, preload hits), grant-ledger/B2-range
  analysis queries, device test plan execution (real devices, §8), go/no-go
  for `start`-policy (`light`→`hq` vs direct `hq`).

Rollback per PR: code rollback via `ci/ship.sh server --ref <prev>` (+ `mac`
for D3); schema is additive so old code boots on new schema; never roll back
the D1 migration. Data direction is fail-safe: derivatives and pins are only
added, never removed, by every slice.

## 7. Rollout / manual-SQL order

`ci/ship.sh` never applies SQL. Order per slice:

1. D1: apply `backend/migrations/add_media_derivatives.sql` by hand
   **before** `ci/ship.sh server` (new code reads the new table/columns).
   Backward compatible: old code ignores the new table/columns.
2. D2–D5: no new SQL (D1 columns already live). Deploy code, then Mac
   (`ci/ship.sh mac`) where the Mac changes.
3. D6 backfill: bounded canary (N clips) → verify derivative rows
   `ready` + roundtrip spot-checks → widen. No cleanup/backfill runs from
   this design session (forbidden here); the babysitter runs them later,
   bounded, with the same preflight/postflight discipline as #134.

## 8. Before/after metric protocol (no bench claims here)

Real-device measurement is **pending** (not done in this session, no media
transferred). Protocol for the D7 validation, same clips + networks before
(newest 50 public clips, iPhone Safari + Chrome Android + desktop Chrome,
Wi-Fi + 4G):

- TTFF p50/p95: click (grid or player open) → first painted frame
  (client instrumentation on `<video>` `loadeddata`/rAF).
- Preload hit rate: neighbour opens served without a new grant/fetch.
- Stalls: `waiting`/`stalled` events per minute of playback.
- Source bytes per playback (entry/derivative byte size actually served).
- B2 range requests per playback (moov-at-end penalty on originals vs
  faststart derivatives) + grant-ledger rows per playback.
- Safari decode: playsinline success, HLG-black watchdog firings, 60 fps
  slow-mo frame-step integrity (visual check by 3–5 divers/judges,
  blind hq vs original vs light — quality annex §8).

Targets (from the audit §10, device-gated): 50/50 playable Mac-off +
cache-empty, first-frame p95 ≤ 2.5 s, 0 black screens, 0 `revisions/*/play`
grants per grid tile, representatives 33/33.

## 9. First implementable slice + dependencies

**D1 is the first slice** (bounded, no behavior change, unblocks
everything): schema migration + models + `build_derivative_media_key` (new
separate transform version; legacy default untouched) +
shared original-selector policy (derivative-exclusion only, no-op without
derived rows) + unit tests. `persist_derivative` is explicitly NOT in D1
(deferred to the publication slice after D2 fencing — see the D1 AMENDMENT
at the top of this doc). Dependencies: none (needs only this doc). It is
deliberately publish- and read-inert: no jobs reference the new table, no
route serves it, so it can merge and deploy with zero user impact.
D2 (fencing) is second — publication integrity must land before D3 writes
the first durable byte. D3 needs D1+D2. D4 needs D1+D3 (same sequence).
D5 needs D1 (readiness source) and is independent of D3/D4 code-wise but
meaningless without produced derivatives — schedule after D3 canary. D6
needs D3–D5. D7 needs everything.

## 10. Open decisions (for Maxime / parent review)

1. `start` policy default: `light`-then-`hq` at keyframe boundary vs direct
   `hq`? Needs the D7 device protocol; doc defaults to `light` start.
2. B2 cost ceiling: ~20–40 Gio extra (quality annex §6, extrapolation from
   2 clips [H]) + egress shift from originals to hq/light. Verify tariffs
   before D6 backfill; no cost promise made here.
3. Server fallback trigger X (Mac-absent minutes) and light-only scope —
   confirm single-slot + nice is enough, or drop D4 entirely.
4. `MEDIA_PLAYBACK_PRESIGN_TTL_SECONDS` 120 s for derivatives: keep uniform
   with originals, or longer (300 s max) since derivatives are the hot path?
5. Poster in B2 vs small durable server store (audit §8 allowed either):
   this plan puts the poster in B2 uniformly — simpler authority, costs
   bytes. Confirm.
6. `web_package` as a new job rendition vs three co-leased per-rendition
   jobs: this plan picks the package job (one lease, one source fetch, one
   pass). Confirm against Mac 8 Gio memory for parallel x264 encoders.

## 11. D3a appendix: Mac single-pass package encoder (UNWIRED, this slice)

D3a delivers the encoder + artifact validation only. Nothing is queued,
published, or served: `media_jobs.py`, ingestion, the server lease API,
schemas, and publisher jobs are untouched. `Transcoder.build` legacy
behavior is byte-identical. D2 keepalive/timeout/kill/reap/gather/Photos-lock
semantics are preserved (the encoder reuses the same timeout→SIGKILL→
shield-reap→cleanup-partial pattern and never touches the source).

### Interface (`mac-agent/src/package_encoder.py`)

- `plan_package(SourceInfo) -> PackagePlan`: pure. Display dims are
  SAR-adjusted (anamorphic sources) and rotation-adjusted (stream
  side-data → tags → first-frame fallback); HDR flag (HLG/PQ only);
  `wide_gamut_sdr` when SDR transfer rides bt2020-family space/primaries
  (needs zscale gamut conversion, else fail-closed); GOP from the nominal
  cadence; HQ/light/poster dims under the §1 short-side rule,
  `hq_aliased_to="light"` when HQ is honestly absent; `poster_thumb_t` =
  latest in-interval timestamp at-or-before 1 s (backed off ~2.5 frame
  intervals so exact-length clips still match a real frame), `None`
  (= first frame) for short/unknown durations.
- `build_package_cmd(...) -> list[str]`: pure. One decode, one tone-map
  (HDR) / gamut pre-convert (wide-gamut SDR) / direct split (narrow SDR),
  `split=` to HQ/light/poster branches, per-branch explicit even scales
  with **real matrix conversion** (`out_color_matrix=bt709`, not a
  retag) + `setsar=1` square pixels, `-fps_mode passthrough`, High@CRF23,
  `maxrate 12M`/`bufsize 24M` on HQ only, AAC from the selected track or
  `-an`, `+faststart`, poster `-q:v 3` with a safe `t>=thumb_t` select.
  Threads bounded per variant (default 2).
- `select_decodable_audio_index(streams, available_decoders=None)`: skips
  unnamed/`none`/`apac` (case-insensitive) plus any named codec with no
  local decoder when a decoder map is passed. The map
  (`ffmpeg_decoder_names`, alias-folded so `mp3` counts when only
  `mp3float` exists) preserves usable audio; an empty map is unprovable
  and keeps the denylist-only choice while the encode fails closed.
- `build_derivative_media_key(...)`: exact D1 `derivative-v1` encoding mirror
  (same fail-closed validation); parity unit-tested.
- `async build_package(source, out_dir, *, video_uuid, source_sha256, ...)
  -> PackageResult`: early D1 identity validation (bad UUID/version fails
  before any work); source must resolve OUTSIDE the output tree
  (source==finals refused, never overwritten — kept fail-closed; now
  advisory since no shared finals are ever written but still enforced);
  ACTUAL source bytes are hashed off-loop and compared to the caller SHA
  before encoding, with stat snapshots before/after hash/probe/encode
  failing closed on change; per-attempt unique scratch dir inside `out_dir`
  (concurrent builds isolated); single ffmpeg run under the D2 timeout
  (kill→shield-reap→own-attempt cleanup, source never touched);
  cancel-safe shielded validation/meta (thread awaited before
  cleanup/re-raise, never unlinking under a live probe); ffprobe
  validation of ACTUAL outputs; then ONE atomic rename of the whole
  attempt dir to a UNIQUE owned `pkg-<uuid>-<suffix>` result dir — NO
  shared stable `hq.mp4`/`light.mp4`/`poster.jpg` finals, no multi-file
  replace (no partial mixed package), no shared HQ for a small-source
  build to unlink, pre-existing `out_dir` files untouched on success AND
  failure, failure/cancel removes ONLY the owned attempt (cancel at the
  publish boundary cleans the owned result dir only, never others);
  returns `ready=True` carrying `(video_uuid, actual_source_sha256,
  transform_version)`, per-role SHAs/sizes/dims with paths INSIDE the
  owned `result_dir`, and per-role derivative media keys. The retained
  dir is an immutable local package artifact owned by the producer until
  the publisher verifies B2 and calls `PackageResult.cleanup()` (owned
  dir only, idempotent; local cleanup is not a retention policy and
  never a broad source cleanup). `ready=True` means LOCAL-VALIDATED,
  NOT durable B2. All blocking I/O runs in threads so the worker
  heartbeat stays responsive.
- `validate_package_outputs(...)`: per-mp4 codec/profile/pix-fmt/BT.709
  tags/dims/frame-count/faststart/GOP-window/audio checks; poster JPEG
  magic/dims/not-HDR-tagged. GOP allows a single keyframe for clips < 2 s
  (VFR-tolerant window, evidence recorded).

### Test evidence (`mac-agent/tests/test_package_encoder.py`, 51 tests, 1 meaningful skip)

Synthetic lavfi fixtures in pytest tmp only (no media in Git). This Mac's
Homebrew ffmpeg (8.1.2, libx264, tonemap, no zscale) ran the SDR matrix:
landscape/portrait 60/30, VFR (frame count + PTS cadence/duration
preserved, no `-r`), SEI-rotation (display 480×640 honored), anamorphic
SAR (SAR-adjusted dims, square-pixel outputs), small source (no upscale,
HQ→light alias), sub-second and EXACT-1.0 s clips (poster non-empty via a
safe in-interval thumb time), mp3-audio source (decoder-alias preserved,
AAC output), timeout kill with pre-existing finals intact + source intact,
SHA-mismatch refusal before ffmpeg, source-inside-outdir refusal, early
UUID/version failure before work, heartbeat responsiveness during blocking
phases. Package-ownership matrix (no shared finals): TWO concurrent builds
with DIFFERENT SHAs/dims/framecounts in the same out_dir — after both
return ALL first+second paths still hash-match their metadata in distinct
owned `pkg-*` dirs; small-source build cannot delete the previous HQ;
sentinel `out_dir/hq.mp4+light.mp4+poster.jpg` unmodified on SUCCESS (and
on timeout failure); injected publish/rename failure keeps the good result
intact with only its `pkg-*` dir left; repeated `PackageResult.cleanup()`
removes only the owned dir, never source/siblings/out_dir. Cancellation
during validation (source intact, nothing published, owned scratch only
removed). Command-shape tests cover
HDR single-tonemap-split, SDR tonemap-skip, matrix-convert + setsar
branches, and the wide-gamut plan flag. HDR/wide-gamut artifact cases SKIP
meaningfully on zscale-less builds while the fail-closed refusals are
proven on tagged fixtures (nothing published, sources intact). A
zscale-equipped Mac canary stays NOT authorized in this slice; HDR
tone-map output is NOT claimed verified until that artifact runs
(needs a CI/zscale ffmpeg later, no prod work now).
Synthetic timings (legit, NOT production): portrait 720×1280 package
~0.6 s, HQ 1080p package ~0.8 s, small clips < 0.2 s. No VMAF/quality or
prod-latency claims are made here.

Residual limits (accepted, recorded): no whole-package wall-clock bound
(ffmpeg timeout + per-probe bounds only); stale `.pkg-attempt-*` dirs from
a hard-killed process are left for the operator (never auto-swept, so a
live concurrent attempt is never at risk); retained `pkg-*` result dirs
are owned immutable artifacts until the publisher verifies B2 and calls
`cleanup()` — local cleanup is not a retention policy; unknown/missing
color metadata is treated as narrow SDR (documented assumption); VFR GOP
length is nominal (~1 s at r_frame_rate) with a tolerant 0.4–2.5 s
evidence window.

Memory: one package runs two bounded x264 encoders concurrently. Two
package slots (four encoders) on the 8 GiB Mac are NOT enabled until a real
Mac memory test passes.

### Next publication contract (parent B2 slice, NOT in D3a)

The publisher takes a `ready=True` `PackageResult` and, per applicable slot
(`hq` skipped when `hq_aliased_to` is set), runs the §4 sequence unchanged:
upload bytes FROM THE OWNED `result_dir` paths → ranged-GET roundtrip
sha+size verify → `persist_derivative` commit (`derived_*` semantics +
`media_derivatives` ready upsert) → cache finalize with per-slot media key
+ `source_sha`/`transform_version` stamp and `finalized_slots`
accumulation, then `PackageResult.cleanup()` (owned dir only, after
verified commit — never before). `mark_job_ready` only when all applicable
slots finalize; source-revision drift at finalize commits `stale`, never
`ready`. D3a provides the bytes + identity + proof (`ready` =
LOCAL-VALIDATED, not durable); the publisher provides durability + ledger
+ read-path wiring.
