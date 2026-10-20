# Lot B — 720p consumers + source-vault reconciliation (bounded dry-run)

Scope: backend + frontend consumers stop requiring `proxy_360p` once a ready
`proxy_720p` exists; ingestion queues poster + 720p only; Mac source vault
finalises on poster + any proxy (720p preferred, legacy 360p accepted).
Encodings and rendering are untouched. Recognizing the existing 720p file
does NOT validate its quality (no HQ1080 in this lot).

## What changed

- `backend/app/api/v1/videos.py`: ingestion queues `("poster", "proxy_720p")`
  only. Legacy routes prefer ready 720p, fall back to ready 360p, and report
  the actual rendition served.
- `backend/app/services/representative_media.py`: production target is
  `("poster", "proxy_720p")`; reading accepts legacy 360p as fallback.
  Playback URL, proxy state, coverage and remap planning use the preferred
  proxy. Replacement creation rejects 360p.
- `backend/app/services/dive_analysis_service.py`: attempt media prefers
  720p, falls back to 360p.
- `backend/app/services/media_catalog.py`: ready sets, poster/media states,
  population planning and averages accept 720p with 360p fallback; new
  population work requests 720p, never 360p. Target readiness is live poster
  + live TRUE 720p (`media_state` is `ready` only then; poster + legacy 360p
  is `partial`). `proxy_state` keeps the playable fallback semantic (ready
  when live 720p *or* live legacy 360p is ready) for existing dashboards.
  The plan, candidates, growth estimates, counters and refresh verify live
  ready poster/720p/360p cache entries through one bounded helper scoped to
  the catalogued assets (`_live_ready_map`) — never from stored states
  alone — so rows stored before this lot (poster + 360p recorded as `ready`)
  are still scheduled for their 720p upgrade, and a poster evicted by cache
  cleanup after cataloging is rebuilt instead of counted as cached. Stored
  states are kept only for non-ready outcomes (errors/missing); a stale
  stored `ready` with no live file reports `missing`, never `ready`.
  `catalog_summary` reports TRUE 720p coverage under `proxy_720p` (live 720p
  only: 360-only or evicted assets count as `missing`, never `ready`). The
  generic `proxy` key and the legacy `proxy_360p` key both report live
  playable any-proxy state (ready when a live 720p *or* live legacy 360p
  entry exists), so 720p output created between scans is announced without
  waiting for the next scan. Neither measures 720p-only coverage.
  Population growth counts live missing posters plus assets missing true
  720p. A job that reports `ready` without a cache entry no longer recurses
  forever; the run waits for the next refresh.
- `backend/app/services/media_recall.py`: readiness exposes true `proxy_720p`
  alongside the generic `proxy` (any) and the legacy `proxy_360p` key, which
  also reports the playable any-proxy state (not 360p-only) for old dashboards.
- `backend/app/services/representative_population.py` + schemas: Tier 1 and
  replacement endpoints accept `poster` + `proxy_720p` only.
- `mac-agent/src/source_vault.py`: `mark_media_ready` finalises on poster +
  (`proxy_720p` or legacy `proxy_360p`); grace + `durable_outputs_verified`
  only when both sides are present. Retention, pin, active-job and
  expiry guards are unchanged.
- `mac-agent/src/config.py` + `config.example.yaml`: default capabilities
  are `["poster", "proxy_720p"]`. `proxy_360p` stays in the allowed set so
  old configs still parse.
- Frontend: `RepresentativeMedia.tsx` prefers 720p with 360p fallback;
  `representativeMediaApi.ts` sends `['poster','proxy_720p']` for replace and
  types the new coverage keys; `mediaRecallApi.ts` types the new readiness
  keys. Player transport (`mediaApi.ts`, `EvaluationPlayer.tsx`) already
  preferred 720p.

## What was deliberately NOT changed (lot A ownership)

- `backend/app/services/media_cache.py` (incl. the
  `only_proxy_360p_entries_can_be_retired` guard and all expiry logic).
- `backend/app/api/v1/browser_upload.py`.
- Any retention/storage migration.
- Any transcoding command or rendition quality.

If a change here needs those files, stop and send the parent a proposed
patch instead of editing them.

## Reconciliation procedure (read-only, bounded, no destructive step)

Goal: prove which of the ~440 historical temporary sources are actually
backed by ready outputs before anything becomes cleanable. Nothing here
deletes, finalises, or mutates retention.

1. On deb-serv, read-only Postgres (10 s statement timeout), count per
   asset whether a ready `poster` + ready `proxy_720p` (or legacy 360p)
   exists. Join to the Mac vault sidecars by `video_uuid` (upper-cased).
2. On the Mac, run the vault in dry-run only:
   - `cleanup(dry_run=True)` output lists gated candidates; it never
     removes while `durable_outputs_verified` is false, `pinned`/`active_job`
     is set, the retention class is permanent, or `expires_at` is in the
     future.
   - `mark_media_ready` is only evidence of a verified server-side finalize
     (called after upload + finalize succeed). A job request, a lease, or a
     failed transcode never marks.
3. Reconcile the two lists: a source is eligible only when BOTH hold —
   server shows ready poster + ready proxy for the same `video_uuid`, AND
   the sidecar shows `poster_ready` + `proxy_ready` with
   `durable_outputs_verified=true` and a past `expires_at`.
4. Do NOT mark the 440 old sources cleanable in bulk. Re-run the dry-run
   weekly; each source becomes eligible on its own grace after its own
   verified finalize.

## Deploy prerequisites

- Server deploy (`ci/ship.sh server --dry-run`, then `server`): no SQL
  migration is required by this lot. Backend + frontend ship together;
  the release note `representative-720p-playback` becomes eligible when
  both services run this commit.
- Mac deploy is SEPARATE and required for the full benefit
  (`ci/ship.sh mac --dry-run`, then `mac`): source-vault 720p
  finalisation, no-new-360p default capabilities. Until the Mac runs this
  commit, temporary sources keep accumulating and new clips still get 360p
  jobs from the old Mac config. Server-side reading of existing 720p works
  without the Mac upgrade.
- Rollback: redeploy the previous server SHA (and previous Mac archive for
  the agent). No data migration to revert; legacy 360p rows and fallbacks
  were never deleted. The release-note JSON is immutable and stays
  published.

## Verification

- `backend/tests/test_lot_b_720p_consumers.py`: 720p-only asset is ready
  everywhere; legacy 360p-only asset stays readable but still queues a
  720p upgrade; catalog summary announces 720p only for true 720p cache
  entries while the generic/legacy proxy keys keep any-proxy compatibility.
- `backend/tests/test_catalog_720p_population_readiness.py`: poster+360p
  ingests as `partial` with a playable proxy; the plan schedules the 720p
  upgrade (including stale pre-lot rows stored as `ready`); start/refresh
  creates exactly one `proxy_720p` job, never 360p, and does not finish
  early; the item completes only after true 720p lands; 720p-ready assets
  create no duplicate jobs; representative priority classes are unchanged.
  Live-readiness round: stored-ready poster evicted with 720p present stays
  a candidate and queues a poster job (item labels downgrade the stale
  ready); 720p created after the scan is announced (`proxy`/`proxy_720p`/
  legacy keys) without a rescan and the asset counts as cached; a poster
  added after the scan is recognized and queues 720p; deleting 720p leaving
  360p stays playable but re-queues the 720p upgrade.
- `mac-agent/tests/test_source_vault_720p_finalization.py`: 720p+poster
  finalises with grace; legacy 360p still finalises; request/failed
  transcode never finalises; cleanup skips unverified/pinned/active.
- Updated: `test_representative_media.py`, `test_representative_population.py`,
  `test_media_node.py` (production target is now 720p).
