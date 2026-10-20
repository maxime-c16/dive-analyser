# Runbook — Lot A: sole-copy browser-safe retention

Scope: media-paths audit F1/F2 (P0). Companion to the audit, not to
`docs/MEDIA_PLAYBACK.md` (left untouched: Lot B owns reader selection and
360p consumers).

## 1. Confirmed expiry/eviction policy (code as of this lot)

Cleaner: `backend/app/services/media_cache.py::cleanup_cache`, run from
`upload_queue.py` every ~10 min at idle. Two bounded passes (100 rows each):

| Pass | Deletes | Spares |
|---|---|---|
| TTL | `status=ready`, unpinned, `expires_at < now` | pinned rows, NULL-expiry rows |
| Quota trim | unpinned `ready` rows, LRU, until under `media_cache_max_bytes` | pinned rows (any expiry) |

Key point: **`expires_at=NULL` alone never protects a row from the quota
trim.** The sole-copy guarantee is `pinned=TRUE`.

Finalization defaults after this lot:

| Rendition | Source | pinned | expires_at |
|---|---|---|---|
| `proxy_720p` | Mac (`finalize_cache_entry`) | TRUE (sole copy) | NULL |
| `poster` | Mac (`finalize_cache_entry`) | TRUE (sole copy) | NULL |
| `poster` | browser (`cache_upload`) | TRUE always (no durable poster exists anywhere) | NULL |
| `original` (playback MP4) | browser (`cache_upload`) | TRUE iff remote playback NOT configured | +30 d |
| `browser_source` | browser (`cache_upload`) | FALSE (B2 roundtrip-verified) | +1 d, evictable |
| `original` | Mac local staging | FALSE | +3 d |
| `proxy_360p` sole-proxy stock | SQL stock only (migration) | TRUE until a verified 720p exists | NULL |
| `proxy_360p` shadowed (720p ready) | none here | FALSE (upgrade-retirement path) | unchanged |
| `proxy_360p` new rows | none (no new 360p in this lot) | FALSE | +30 d |

Pre-existing guard (kept): when remote playback is NOT configured,
`cleanup_cache` additionally excludes `browser-uploads/` original/720p/poster
rows via the read predicate, so an unpinned browser row is still spared
without a catalog-wide write
(`test_cleanup_preserves_browser_playback_when_remote_path_is_disabled`).

## 2. What this lot changes (no re-encode, no file deletion)

- `finalize_cache_entry` pins `proxy_720p`/`poster`, expiry NULL for 720p.
  It deliberately does NOT pin new `proxy_360p` rows: this lot produces no
  new 360p (no backfill, no finalizer change; Lot B stops new 360p jobs),
  and a missing 360p is never a production requirement.
- `cache_upload` pins browser posters unconditionally with NULL expiry;
  playback MP4 keeps the conditional pin; `browser_source` stays 1-day
  disposable.
- Migration `backend/migrations/protect_browser_safe_cache_entries.sql`
  applies the same state to the stock (ready 720p/poster rows), PLUS ready
  `proxy_360p` rows that are still the ONLY ready proxy of their clip (no
  ready `proxy_720p` for the same `photos_asset_id`). Shadowed 360p rows
  (a ready 720p exists) are NOT pinned: they stay eligible for the planned
  upgrade retirement (`advance_resolution_upgrade_runs` retires unpinned
  360p after 720p validation, and retains pinned rows without blocking the
  upgrade — so retention never prevents progression, and this lot deletes
  no stock).
- No rendition bytes are rewritten; image quality and frame rate are
  untouched (720p stays ~406x720 60 fps until a future durable HQ/light
  pipeline ships — outside Lots A/B; Lot B #135 only repoints 360p
  consumers and does not publish HQ/light replicas).

## 3. Babysitter procedure (apply AFTER merge, never in this lot)

1. `git fetch origin && git status` on a checkout at the merged master SHA.
2. Dry-run first: `ci/ship.sh server --dry-run` and read the output.
3. Preflight (read-only, Postgres):
   `psql "$DATABASE_URL" -f backend/scripts/protect_browser_safe_preflight.sql`
   Record: rows/bytes per rendition (§1), total protected bytes vs `df` on
   the media-cache volume, first/last expiry of the frozen wave.
   Expected scale (audit 2026-10-21): ~1 651 previews + posters, ~1.7 Go,
   plus the 360-only legacy remainder counted separately in §1 (small
   volume per audit; record the aggregate counts/bytes, no per-clip
   detail).
4. Apply by hand (no migration runner):
   `psql "$DATABASE_URL" -f backend/migrations/protect_browser_safe_cache_entries.sql`
   Record the `UPDATE <n>` count but do NOT require `<n>` == preflight
   rows_to_protect: finalizer jobs running concurrently may insert new
   unpinned rows between preflight and apply. Safe to re-run (idempotent
   WHERE clause). If postflight residual > 0, re-apply until 0 — including
   once more after the new finalizer is live, in case rows finalized with
   the old code appeared in between.
5. Postflight: same preflight script. Gate: §4
   `residual_unprotected_rows` MUST be 0. §5a must show zero
   browser_source/original rows touched; §5b lists shadowed 360p rows
   (720p ready present) and must show zero pinned by this migration —
   those rows stay on the upgrade-retirement path. A non-zero residual
   after the first apply is not a failure: re-run the migration
   (idempotent) and re-check until the gate passes.
6. Then deploy normally: `ci/ship.sh server` (SQL first, backend second,
   per `docs/REPO_WORKFLOW.md`). Mac deploy NOT required (no agent change).
7. Verify: `SELECT COUNT(*) FROM media_cache_entries WHERE status='ready'
   AND (pinned IS NOT TRUE OR expires_at IS NOT NULL)
   AND (rendition IN ('proxy_720p','poster')
     OR (rendition = 'proxy_360p'
       AND NOT EXISTS (SELECT 1 FROM media_cache_entries newer
         WHERE newer.photos_asset_id = media_cache_entries.photos_asset_id
           AND newer.rendition = 'proxy_720p'
           AND newer.status = 'ready')));` → 0.

## 4. Rollback

No rollback SQL needed. The migration only pins rows and clears their TTL;
reverting the backend does not unpin anything (fail-safe direction: the old
cleaner already respects `pinned`). If a row must ever become evictable
again, that is an explicit per-row admin unpin (`POST
/media/cache/{id}/pin`), never a migration. Do NOT unpin sole-copy rows
until a future durable pipeline (outside Lots A/B) publishes verified
durable replicas and documents the unpin-on-replicate rule. Lot B (#135)
only repoints 360p consumers; it does not authorize unpinning.

## 5. Limits / non-goals

- Capacity is bounded but not infinite: protection retains ~1.7 Go + growth.
  Watch the media-cache volume; quota trim still evicts everything else.
- Quota pressure with all sole copies pinned can only evict non-sole rows;
  if the volume fills, the answer is disk, not unpinning.
- 360p consumers (representatives, DiveAnalysis, catalog, vault) are Lot B:
  untouched here. Legacy 360p rows that are still the ONLY ready proxy of
  their clip are pinned by the stock migration (transitional retention,
  not a durable replica) so Lot B re-lecture keeps working until a
  verified 720p replaces them; shadowed 360p rows keep their existing
  policy and stay eligible for the planned upgrade retirement. This lot
  performs no 360p backfill, no 360p deletion, and no vault cleanup: do
  not purge 360p rows during the transition, and do not unpin sole-proxy
  360p rows until the future durable pipeline (outside Lots A/B) is live.
  360p is never a production requirement here.
- Reader selection, grille fallback, priority, leases, auth: untouched.
- The `pinned` flag now doubles as the system sole-copy marker; a manual
  unpin re-exposes a sole copy to BOTH cleaner passes. Admin UI callers
  should treat unpinning 720p/poster/sole-360p rows as destructive until
  a future durable pipeline documents the unpin-on-replicate rule
  (not Lot B).
