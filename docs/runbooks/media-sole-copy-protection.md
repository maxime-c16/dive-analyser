# Runbook — Lot A: sole-copy browser-safe retention

Scope: media-paths audit F1/F2 (P0). Companion to the audit, not to
`docs/MEDIA_PLAYBACK.md` (left untouched: Lot B owns reader selection and
360p consumers).

## 1. Confirmed expiry/eviction policy (code as of this lot)

Cleaner: `backend/app/services/media_cache.py::cleanup_cache`, run from
`upload_queue.py` every ~10 min at idle AND from `POST /cache/cleanup`.
Both paths run inside the backend container and call the same function.
Two bounded passes (100 rows each), fail-safe in two layers:

| Pass | Deletes | Spares |
|---|---|---|
| TTL | `status=ready`, unpinned, `expires_at < now`, not sole | pinned rows, NULL-expiry rows, ALL sole copies |
| Quota trim | unpinned `ready` rows, LRU, until under `media_cache_max_bytes` | pinned rows (any expiry), ALL sole copies |

Layer 1 — dynamic sole-copy exclusion (`_sole_copy_exclusion_clause`):
selection never returns a ready `proxy_720p`/`poster` row, nor a ready
`proxy_360p` row with no ready `proxy_720p` for the same asset —
**regardless of pinned**. Stock rows are spared the moment the new backend
is live, before any migration runs, and rows born under the old runtime
after the last UPDATE are spared without any trigger.

Layer 2 — atomic per-row re-check (`_delete_if_still_evictable`): the
eligibility check and the DELETE are one statement, so a row pinned (or
un-expired, or moved out of ready) after selection is skipped — never
unlinked. Deletes commit before any file is unlinked: a crash can leak a
file, never lose one.

Key point: **`expires_at=NULL` alone never protects a row from the quota
trim.** The sole-copy guarantee is `pinned=TRUE` (durable marker) plus the
two cleaner layers above (runtime enforcement).

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
| `proxy_360p` new rows | none (no new 360p in this lot) | FALSE, spared by layer 1 while sole-proxy | +30 d |

Pre-existing guard (kept): when remote playback is NOT configured,
`cleanup_cache` additionally excludes `browser-uploads/` original/720p/poster
rows via the read predicate, so an unpinned browser row is still spared
without a catalog-wide write
(`test_cleanup_preserves_browser_playback_when_remote_path_is_disabled`).

## 2. What this lot changes (no re-encode, no file deletion)

- `finalize_cache_entry` pins `proxy_720p`/`poster`, expiry NULL for 720p.
  It deliberately does NOT pin new `proxy_360p` rows: this lot produces no
  new 360p (no backfill, no finalizer change; Lot B stops new 360p jobs),
  and a missing 360p is never a production requirement. New sole-proxy 360p
  rows are still spared by cleaner layer 1 (protection without a pin), so
  when a verified 720p later shadows them they are unpinned and stay
  eligible for the planned retirement.
- `cache_upload` pins browser posters unconditionally with NULL expiry;
  playback MP4 keeps the conditional pin; `browser_source` stays 1-day
  disposable.
- `cleanup_cache` is fail-safe (§1, two layers) and exposes its seam:
  `select_cleanup_candidates` (select, never touch) +
  `evict_cleanup_candidates` (atomic re-check, commit, then unlink).
- Migration `backend/migrations/protect_browser_safe_cache_entries.sql`
  pins the stock (ready 720p/poster rows, PLUS ready `proxy_360p` rows that
  are still the ONLY ready proxy of their clip). Shadowed 360p rows stay
  unpinned on the upgrade-retirement path. No rendition bytes are rewritten.
- `backend/scripts/verify_browser_safe_files.py` (read-only): reports
  sole-copy rows whose file is missing from disk. Pre-UPDATE gate (§3).
- No INSERT trigger, no transient guard. See §2b for why.

## 2b. Why there is no trigger, and why the SQL runs AFTER the deploy

The stock UPDATE is **data-only**: it sets `pinned`/`updated_at`/`expires_at`
on existing columns. No column added/removed, no table created, no row or
file touched. Consequences, all load-bearing for the procedure:

1. **The SQL is not a schema prerequisite.** The old backend runs fine on
   pinned rows (its cleaner already excludes `pinned` rows from both
   passes), and the new backend runs fine on unpinned stock (cleaner layer 1
   spares sole copies regardless of pin). Either order boots; the safe order
   is code first, data second.
2. **The swap is the barrier that ends old cleaners.** `ci/ship.sh server`
   recreates the backend container (`compose up --force-recreate`): the old
   process is stopped and only the new image serves afterwards. Both cleanup
   paths (idle worker, `POST /cache/cleanup`) and the finalizer live in that
   container — the Mac agent only uploads bytes and calls the finalize API,
   so no old writer survives the swap. After the barrier, the ONLY cleaner
   that can race the UPDATE is the new fail-safe one, and the ONLY writers
   are the new pinning finalizer (plus the unchanged 360p job path, covered
   by layer 1 while sole-proxy).
3. **A trigger cannot fix the old-cleaner race anyway.** A DB trigger fires
   on INSERT; it cannot cancel a filesystem UNLINK the old cleaner already
   decided on (`cleanup_cache` unlinks selected files before deleting their
   rows). The only real fix for a pre-selected row is the one in §1: re-check
   eligibility atomically at DELETE time and unlink only deleted rows — plus
   never letting an old cleaner exist past the barrier.
4. **No protection is claimed against old-runtime actions before the
   barrier.** Rows the old cleaner evicted before the swap are gone (status
   quo ante, bounded: they were evictable under the old policy too); the
   migration only protects what is still on disk, verified by the file gate
   (§3 step 4). The procedure MUST NOT start the UPDATE before the barrier
   is confirmed — that confirmation is steps 1–3 below, not an assumption.

## 3. Babysitter procedure (apply AFTER merge, never in this lot)

Order is the guarantee: **barrier first, data second.** Reads AND uploads
keep serving throughout (no pause, no restart beyond the deploy's own
container swap; the UPDATE itself takes only row locks).

1. `git fetch origin && git status` on a checkout at the merged master SHA.
2. Dry-run first: `ci/ship.sh server --dry-run` and read the output.
   `ship.sh` warns that `backend/migrations/` changed: that is expected —
   the SQL below is applied by hand in steps 5–6, never automatically.
3. Deploy normally: `ci/ship.sh server` (Mac deploy NOT required: no agent
   change — the agent calls the backend finalize API). Record the deployed
   backend SHA from the ship output.
4. Confirm the barrier (all must hold; this is the step the old procedure
   assumed away):
   - ship health checks passed AND `docker inspect dive-analyser-backend-1
     --format '{{index .Config.Labels "dive.analyser/sha"}}'` equals the
     deployed SHA (single backend container, new image);
   - `docker ps` shows no container on the previous backend image.
   From this point no pre-Lot-A cleaner or finalizer exists anywhere: the
   old code is a stopped container, not a paused flag.
5. Preflight (read-only, Postgres):
   `psql "$DATABASE_URL" -f backend/scripts/protect_browser_safe_preflight.sql`
   Record: rows/bytes per rendition (§1), total protected bytes vs `df` on
   the media-cache volume, first/last expiry of the frozen wave.
   Expected scale (audit 2026-10-21): ~1 651 previews + posters, ~1.7 Go,
   plus the 360-only legacy remainder counted separately in §1 (small
   volume per audit; record the aggregate counts/bytes, no per-clip
   detail).
6. File gate (read-only, from the live checkout on deb-serv):
   `docker compose exec backend python scripts/verify_browser_safe_files.py`
   Gate: `missing_files` MUST be 0. A non-zero count means an old-runtime
   eviction raced the swap kill (file unlinked, row delete rolled back) or
   a file was removed by hand: STOP and investigate — do NOT pin dead rows
   and declare them protected. (A missing file is never resurrected by the
   UPDATE; this lot performs no backfill by design.)
7. Apply the stock UPDATE by hand (no migration runner):
   `psql "$DATABASE_URL" -f backend/migrations/protect_browser_safe_cache_entries.sql`
   Record the `UPDATE <n>` count but do NOT require `<n>` == preflight
   rows_to_protect: concurrent jobs may have committed between preflight
   and apply (new-writer rows land pinned or layer-1-spared, so they only
   ever add to the protected set, never to the residual). Safe to re-run
   (idempotent WHERE clause). Single applier: do NOT run the file from two
   sessions at once.
8. Postflight: same preflight script. Gate: §4
   `residual_unprotected_rows` MUST be 0. §5a must show zero
   browser_source/original rows touched; §5b lists shadowed 360p rows
   (720p ready present) and must show zero pinned by this migration —
   those rows stay on the upgrade-retirement path. If residual > 0 after
   the first apply, re-run the stock UPDATE AT MOST ONCE and re-check:
   the only possible residual is a transaction that committed late — no new
   unpinned inflow can appear (new writers pin; layer 1 spares the rest),
   so this converges. A second non-zero residual is a real finding: stop
   and investigate, do not loop.
9. Verify: `SELECT COUNT(*) FROM media_cache_entries WHERE status='ready'
   AND (pinned IS NOT TRUE OR expires_at IS NOT NULL)
   AND (rendition IN ('proxy_720p','poster')
     OR (rendition = 'proxy_360p'
       AND NOT EXISTS (SELECT 1 FROM media_cache_entries newer
         WHERE newer.photos_asset_id = media_cache_entries.photos_asset_id
           AND newer.rendition = 'proxy_720p'
           AND newer.status = 'ready')));` → 0.

## 4. Rollback

No rollback SQL exists for the stock UPDATE, by design: the migration only
pins rows and clears their TTL; reverting the backend does not unpin
anything (fail-safe direction). If a row must ever become evictable again,
that is an explicit per-row admin unpin (`POST /media/cache/{id}/pin`),
never a migration. Do NOT unpin sole-copy rows until a future durable
pipeline (outside Lots A/B) publishes verified durable replicas and
documents the unpin-on-replicate rule. Lot B (#135) only repoints 360p
consumers; it does not authorize unpinning.

A rollback to the old backend **re-opens the window LOUDLY, never
silently**: the old cleaner has no layer 1, so 720p/poster rows born
unpinned under the old finalizer are evictable again until re-upgrade.
After any rollback:

1. Re-run the residual query (§3 step 9) immediately: it is 0 for all
   pinned rows (rollback unpins nothing) and non-zero only for rows born
   under the old code — re-run the stock UPDATE to pin those, then
   re-deploy forward as soon as gates allow. Minimize time on the old code;
   do NOT treat "residual was 0 before rollback" as "protected during
   rollback".
2. Rows evicted while the old code served are gone (no backfill in this
   lot); the file gate (§3 step 6) tells exactly which, if any.
3. Keep the additive schema/data on app rollback; the new code runs fine on
   it. No trigger to reinstall — there is none, and none is needed: the
   fix is the deployed code, not a database object.

## 5. Limits / non-goals

- Capacity is bounded but not infinite: protection retains ~1.7 Go + growth.
  Watch the media-cache volume; quota trim still evicts everything else.
- Quota pressure with all sole copies spared can only evict non-sole rows;
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
- New 360p rows born mid-transition (old prepare jobs completing, old or
  new runtime) land unpinned with their normal TTL. They are spared by
  cleaner layer 1 exactly while they are the sole proxy of their clip —
  best-effort retention, as before this lot — and become normally
  evictable/retireable once a ready 720p shadows them. Do not claim they
  are pinned; they are protected by exclusion, not by marker. CI proves
  this on real Postgres
  (`backend/tests/test_postgres_media_cutover.py`).
