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
- `backend/app/services/media_catalog.py`: ready sets, proxy/media states,
  population planning and averages accept 720p with 360p fallback; new
  population work requests 720p, never 360p. `catalog_summary` keeps the
  legacy `proxy_360p` key (same counts) and adds `proxy_720p`/`proxy`.
  All three proxy keys count the same aggregated `proxy_state`, which is
  ready when 720p *or* legacy 360p is ready: `proxy_720p` does NOT measure
  720p-only coverage, so dashboards must not read it as true 720p counts.
- `backend/app/services/media_recall.py`: readiness exposes `proxy_720p`
  and `proxy` (any) alongside the legacy `proxy_360p` key.
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
  720p upgrade.
- `mac-agent/tests/test_source_vault_720p_finalization.py`: 720p+poster
  finalises with grace; legacy 360p still finalises; request/failed
  transcode never finalises; cleanup skips unverified/pinned/active.
- Updated: `test_representative_media.py`, `test_representative_population.py`,
  `test_media_node.py` (production target is now 720p).
