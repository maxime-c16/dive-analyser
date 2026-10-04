# LEGACY_DECOMMISSION_PLAN_V1 — readiness audit (P8) + dry-run readiness (P9)

> Status after `MEDIA_BACKBONE_P9_PRODUCTION_READINESS_AND_EXTERNAL_ACCESS_V1`:
> **LEGACY_DECOMMISSION_DRY_RUN_READY** (the deletion-candidate inventory can
> be trusted) with **LEGACY_PHYSICAL_DELETION_READY = NO** — because
> `CONTINUOUS_NATURAL_INGEST` is still PENDING. This document is
> READINESS-ONLY: it classifies dependencies and storage, and defines the
> dry-run. **No legacy media was or may be deleted in P8 or P9.**
> The DRY-RUN-ONLY inventory tool is `backend/scripts/legacy_dry_run.py`
> (no --delete flag, no destructive mode, no B2 client; static-tested).

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

## 4. Decommission prerequisites (packet §35) — live scorecard (P9 refresh)

| Prerequisite | State |
|---|---|
| Natural continuous-ingest proof | STILL PENDING (armed, healthy; no natural clip in the P8+P9 windows) → HARD DELETION BLOCKER (P9 §37) |
| Extended B2 playback observation | GREEN (P9: 192 ALLOWED / 16 denied-intentional / 0 provider failures / 0 unexpected; ≥100 target exceeded) |
| Multi-user auth stable | achieved (P8; P9: synthetic negatives removed, exactly 1 legitimate production user) |
| Every eligible logical media verified PROD | 15/15 = 100% (P9 re-verified, 0 drift) |
| Rollback independent of deleted legacy bytes | NOT proven (legacy fallback still the rollback path) — BLOCKS PHYSICAL DELETION, not the dry run |
| Backup/recovery policy frozen | GREEN (BACKUP_AND_RETENTION_V1 §3: daily encrypted pg_dump + off-host copy + readability gate) |
| Restore tested | GREEN (isolated-container restore PASS: 14-table row reconciliation + ownership chain + verified PROD locations) |
| Retention policy frozen | GREEN (BACKUP_AND_RETENTION_V1 §6 + ops/retention_policy_v1.json, test-enforced) |
| Logical deletion semantics defined | GREEN (DESIGN ONLY, BACKUP_AND_RETENTION_V1 §7: DB-state retirement vs delayed operator purge) |
| Provider-failure strategy accepted | GREEN (P6 matrix proven live; policy frozen in TARGET/SECURITY docs) |

## 4a. P9 dry-run evidence (live, no deletions)

Storage classification refreshed (packet §31-§34):

| Category | Size (2026-09-10 P9 refresh) | Classification |
|---|---|---|
| server media/cache | 1718 files / 890 MB | ACTIVE playback substrate; 29 files (10.7 MB) are B2-derivable candidates (15 verified-PROD revisions' derivations), 1689 conservative KEEP |
| server media/videos | 176 files / 14.28 GB, ALL `IMG_*.MOV` | ORPHAN icloudpd iCloud-ORIGINAL cache: 0 matches against any dives.video_uuid; production dives.video_path NULL for all 2805 dives; video_labels reference UUID-named files only → RECLAIMABLE CANDIDATE (not authorized), rebuildable from iCloud via icloudpd |
| Mac source vault | 13 GB / 440 sources | ACTIVE_REQUIRED (ingest + migration source); becomes a bounded cache only after CONTINUOUS_NATURAL_INGEST=GREEN + a recovery strategy that does not need the vault (DESIGN ONLY) |
| Mac highres (science) | 445 MB | SCIENCE AUTHORITY — excluded from all product reclamation |
| B2 PROD | 16 objects / 345,568,956 bytes | verified replica authority; 1 documented P4 preflight evidence object (72d94c7f, 408 B); 0 unexplained orphans; 0 missing |
| Postgres | 34 MB | encrypted daily backups (BACKUP_AND_RETENTION_V1) |

## 5. Dry-run tool (P9 §35) — IMPLEMENTED, DRY-RUN ONLY

`backend/scripts/legacy_dry_run.py` (committed, live-executed):

- Output per candidate: path, size, category, why candidate, authoritative
  replacement (verified B2 revision / iCloud source), recovery proof, and
  blocking dependency.
- Hardcoded safety (static-tested in `test_p9_production_readiness.py`):
  NO `--delete` argument, NO destructive mode, NO B2 client usage, no
  remove/unlink/rmtree primitives anywhere in the file.
- Read-only DB queries + read-only filesystem stat/list only.
- Live run: cache classification (29 B2-derivable candidates out of 1718
  cache files; the rest conservative KEEP) + /videos classification
  (176/176 orphan icloudpd artifacts, 0 DB references) + science exclusion.

## 5a. What would make LEGACY_PHYSICAL_DELETION_READY = YES (future)

1. `CONTINUOUS_NATURAL_INGEST = GREEN` (a real new clip through the
   continuous dual-write path, with the P9 observation record complete).
2. A rollback strategy that does NOT need legacy bytes (e.g. B2-native
   playback for every surface or an accepted failure model), re-proven.
3. A second independent replica of the B2 media (BACKUP_AND_RETENTION_V1
   §5 recommendation) accepted by the human.
4. A human-approved deletion manifest produced by a dry run, executed in a
   LATER packet with its own firewall. P9 does NOT implement execution.
