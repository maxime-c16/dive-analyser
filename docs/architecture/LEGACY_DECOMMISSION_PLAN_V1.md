# LEGACY_DECOMMISSION_PLAN_V1 — readiness audit (P8), no execution

> Status after `MEDIA_BACKBONE_P8_ACCELERATED_PRODUCTIONIZATION_V1`:
> **LEGACY_DECOMMISSION_NOT_READY**. This document is READINESS-ONLY:
> it classifies dependencies and storage, and defines the future P9
> dry-run. **No legacy media was or may be deleted in P8** (packet §49).

## 1. What "legacy media" means here (categories)

| Category | Location | Size (2026-09-10) | Role |
|---|---|---|---|
| (a) Canonical source/vault | Mac `/Users/Shared/services/data/media-node/sources/by_uuid` (440 sources) | 13 GB | ACTIVE_REQUIRED: ingest + migration source (PhotoKit export → vault → jobs → dual-write) |
| (b) Legacy transcoded cache | Server `media/cache` (`/app/media-cache`) | 864 MB (poster 116 MB, 360p 62 MB, 720p 671 MB; DB-tracked 849 MB) | PRIMARY playback substrate for the product UI today |
| (c) Poster/thumbnail derivatives | inside (b) | 116 MB | UI thumbnails everywhere |
| (d) Temporary/staging | `/tmp/dive_downloads`, Mac `media_tmp`, `object_ingest_tmp`, journals | ~0 (clean) | ephemeral |
| (e) `/videos` icloudpd files | Server `media/videos` (176 files) | 14 GB (largest 6.8 GB) | FALLBACK_ONLY file candidates — effectively UNREFERENCED (all 2805 dives have `video_path` NULL; name pattern doesn't match `/videos/{uuid}.mp4`) |
| (f) B2 PROD backbone | 16 objects / 345.6 MB | content-addressed | verified replica authority |

## 2. Dependency classification (code audit, HEAD `b8e5de9`+P8)

### ACTIVE_REQUIRED (cannot remove while the product works as today)
- Cache write/serve core: `media_cache.py` (playback_url, sharded paths,
  upload/finalize), `media.py` cache routes + `_serve_media_file` (also
  used by the B2 fallback — shared, load-bearing), job upload routes.
- Analysis UI media state: `dive_analysis_service.py` (poster/proxy URLs).
- Representative gallery: `representative_media.py` + frontend
  `RepresentativeMedia.tsx` (poster+proxy readiness).
- Landmark pipeline input: `analysis_pipeline_landmark_a.py` reads
  `proxy_360p` cache files directly; `analysis_pipeline_fixture.py`.
- Frontend playback/posters: all poster URLs are cache-route URLs
  (`DiveVideoPlayer.tsx`, `Dives.tsx`, `DiveAnalysis.tsx`); the ONLY B2
  surface is the P5 player page.
- Ingest chain: Photos reader/catalog (Mac), `media_jobs.py` (the job
  loop is ALSO the dual-write trigger event stream), transcoder,
  source vault, recall gates, agent heartbeat. The backbone is born
  from this loop — cannot be cut while new ingest runs.
- Operator dashboards/catalog planning: `operations_status.py`,
  catalog population/resolution-upgrade machinery.
- Auth chain for cache playback: `user_access.resolve_cache_entry_diver_owner` (reused by any future B2-native path).

### FALLBACK_ONLY (needed only when B2 is off/failing)
- `legacy_media.py` (authenticated server-side fallback), `_serve_legacy_fallback` wiring, legacy `/videos/{uuid}` + `/check/{uuid}` routes (NOT called by the frontend), `require_legacy_media_user`, `can_user_access_video`, the `/videos` mount + ops icloud sync/prune scripts.

### HISTORICAL_COMPATIBILITY (keep rows meaningful, stop relying)
- `Dive.video_path` (all NULL in production), catalog per-asset legacy
  state columns + run tables, `VideoLabel` filename fields, legacy-mode
  config keys, catalog free-space floor for vault-less agents.

### UNUSED
- `photos_library_path` config (never read), dead imports in
  `videos.py`, migration_service (not media), nginx (no media blocks).

### UNKNOWN
- Science cache provenance: `experiments/landmark_pilot` reads only
  `/tmp/diveanalyzer-exp` science-local copies (never product tables);
  provenance of those copies is outside product code.

## 3. Deletion semantics that exist today (audit)

Five sanctioned deletion sites, all bounded, none touching Photos
originals or B2: backend cache eviction (root/symlink-guarded), vault
retention cleanup (only for verified, non-pinned sources), exporter/
materializer staging cleanup, ingest staging cleanup, ops `/videos`
prune (age+byte-capped). **B2 delete/hide performed to date: 0.**

## 4. Decommission prerequisites (packet §35) — live scorecard

| Prerequisite | State |
|---|---|
| Natural continuous-ingest proof | NOT OBSERVED YET → blocker |
| Extended B2 playback observation | partial (62+ requests GREEN; longer soak owed) |
| Multi-user auth stable | achieved (P8) |
| Every eligible logical media verified PROD | 15/15 = 100% |
| Rollback independent of deleted legacy bytes | NOT proven (legacy fallback still the rollback path) |
| Backup/recovery policy frozen | NOT frozen |
| Retention policy frozen | NOT frozen |
| Provider-failure strategy accepted | partial (P6 matrix proven; policy not frozen) |

## 5. Future P9 dry-run design (when prerequisites pass) — PLAN ONLY

1. Freeze backup/retention policy + accept provider-failure strategy.
2. Enumerate exact deletable bytes: category (e) first (`/videos`, 14 GB,
   unreferenced), then obsolete cache renditions superseded by verified
   B2 replicas (per-revision reconciliation: for each MediaRevision with
   a verified PROD location, the cache renditions that are derivable
   from B2 bytes).
3. Mandatory keepers: canonical vault (a), posters while UI depends on
   them (c), analysis pipeline proxy files (A5) until B2-native fetch
   exists, all journals/state.
4. Recovery: every candidate file must be reconstructable from B2
   (roundtrip SHA) or must be explicitly declared non-recoverable and
   kept. Dry-run outputs a manifest (path, bytes, recoverable-from-B2,
   reason) — executed deletions happen only in a LATER phase after
   human approval.
5. Rollback: freeze backup image of `media/cache`+`media/videos` before
   any real run; validation = playback + analysis + gallery canaries.
