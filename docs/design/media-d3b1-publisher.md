# D3b1 — internal derivative publisher (UNWIRED, no activation)

Status: implemented, no routes/jobs/readers import it. Runtime publisher
stays unwired; `Release notes: none — internal, no user impact`.

## Interface

- `backend/app/services/derivative_publisher.py`
  - `build_publication_context(db, video_uuid, role, transform_version=None)`
    → `PublicationContext` (validates identity, resolves canonical
    camera-original source, validates B2 env/bucket/prefix).
  - `publish_derivative(db, ctx, local_path, s3_client=None)` → ready/stale
    dict (upload → full-byte roundtrip verify → one DB transaction).
  - `resolve_canonical_source_revision(db, video_uuid)` → newest verified
    PROD camera revision (excludes `derived_*` + `browser_playback`;
    `browser_original` eligible). `derivative_object_key(...)` → B2 key.

Canonical source policy (preserve quality): never use the
already-transcoded `browser_playback` proxy as a transcode source; use
true camera bytes (`browser_original` for browser clips,
`photos_edited_rendition` for Photos). Existing selectors untouched.

## Next slice (D3b2 — fenced slot API, NOT in D3b1)

- Tighten ONLY `build_publication_context` (or a D3b2 wrapper) with
  `media_jobs._guarded_job(job_id, agent_id, lease_token)` + allowed
  `web_package` rendition gate; `publish_derivative` signature stays.
- Slot layer: per-slot (`hq`/`light`/`poster`) calls sharing one
  `PublicationContext` family; small-source rule (`hq_aliased_to=light`,
  record `skipped_small_source`, never duplicate-encode) lives in the
  slot scheduler, not the publisher.
- `finalized_slots` accumulation + `mark_job_ready` only when all
  applicable slots finalize; source-drift at finalize commits `stale`
  (this slice already does) and D3b2 enqueues the new-source job.

## Rollback / rollout

- No migration (D1 `add_media_derivatives.sql` already live). No config,
  no Mac changes, no jobs/backfill/cleanup.
- Rollback: code rollback only (`git revert` / `ship.sh server --ref`).
  B2 orphans from crashed attempts are retained by design; never delete
  other objects. Ledger `ready` rows are append-only history.
- Activation: none. No route serves derivatives; no worker calls the
  publisher. D3b2 wires the fenced API after review.
