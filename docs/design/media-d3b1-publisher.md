# D3b1 — internal derivative publisher (UNWIRED, no activation)

Status: implemented, no routes/jobs/readers import it. Runtime publisher
stays unwired; `Release notes: none — internal, no user impact`.

## Interface

- `backend/app/services/derivative_publisher.py`
  - `build_publication_context(db, video_uuid, role, transform_version=None)`
    → `PublicationContext` (requires a clean session; validates identity
    through the shared D1 validator, resolves the canonical camera
    source, validates B2 env/bucket/prefix). Rejects malformed identity
    before any source read.
  - `publish_derivative(db, ctx, local_path, s3_client=None)` → ready
    dict (upload → full-byte roundtrip verify → one DB transaction).
    Requires a clean caller session; owns its DB unit (commits on
    success, rolls back on any failure — row locks always released).
    Revalidates identity, canonical source, environment, bucket and
    prefix against current settings and the live DB before any upload,
    so a forged or stale context cannot divert bytes to another bucket.
    No `commit` flag: the publisher always resolves its own unit.
  - `resolve_canonical_source_revision(db, video_uuid)` → newest verified
    PROD camera revision (excludes `derived_*` + `browser_playback`;
    `browser_original` eligible). The replica fetch mirrors the
    `verified_original_clause` allowlist (B2 backend, allowlisted PROD
    bucket, non-empty key, deterministic newest-first); ambiguity fails
    closed with `MissingSourceError`.
  - `derivative_object_key(...)` → B2 key. Caller contract: the file is
    opaque bytes claimed for the role — byte identity is proven
    (SHA-256/size roundtrip), media format validity is NOT verified
    here (D3b2 slot acceptance owns that; no new pipeline in D3b1).

## Semantics

- Stale beats everything except integrity: any drift between context
  build and commit (checked after row positioning AND rechecked
  immediately before commit) commits `stale`, never `ready`. An existing
  `ready` row is never modified or downgraded — the old derivation keeps
  serving until D3b2 supersedes it. Same-bytes drifted replays go stale
  too (a drifted derivation is not current even when bytes match).
- Conflict only when current: existing `ready` + different bytes + source
  still current → `DerivativeIdentityConflict` (preflighted before any
  upload when obvious; rechecked after the upload otherwise). Drifted
  attempts never raise conflict.
- `IntegrityError` rival path re-reads the rival row AND rechecks the
  source: drifted → `StaleSourceError` with nothing committed; rival
  ready + same bytes → idempotent ready; anything else → conflict.
- Concurrency: same-identity publishers serialize on the ledger row
  (`SELECT ... FOR UPDATE` on PG; UNIQUE identity index on SQLite). No
  linearizable cutover is claimed against the many unfenced source
  writers — the pre-commit recheck is a best-effort guard; D2 fencing
  closes the residual race.
- Environment: source is always canonical PROD; the publish environment
  (dev/prod) selects the destination bucket via the allowlist. A dev
  publish commits its location in the DEV bucket only and never creates
  a PROD location. The ledger row carries no environment (content proof);
  D3b2 readers must resolve locations in their serving environment.
- Trust boundary: `PublicationContext` is an INTERNAL descriptor for
  trusted in-process callers (private factory token), NOT an API
  authorization boundary. Enforcement is revalidation in
  `publish_derivative`. D2 lease-token fencing is NOT integrated —
  `build_publication_context` performs no `media_jobs` claim check.

Canonical source policy (preserve quality): never use the
already-transcoded `browser_playback` proxy as a transcode source; use
true camera bytes (`browser_original` for browser clips,
`photos_edited_rendition` for Photos). Existing selectors untouched.

## Tests

- `tests/test_derivative_publisher_d3b1.py` — SQLite tier: ready paths
  for all roles, verify-failure matrix, idempotency, conflict preflight
  (no upload), full stale/ready matrix over prior ledger states
  (`verifying`/`ready`/`stale`/`superseded` × same/different bytes ×
  drifted/current), forged-context and settings-drift revalidation,
  dirty-session refusal, ambiguous/wrong-bucket source closure,
  dev-env location scoping, provider-error sanitization, identity-map
  refresh, pre-commit recheck (pinned at exactly two source
  resolutions), stale backbone recording without autoqueue.
- `tests/test_postgres_derivative_publisher_d3b1.py` — CI `postgres`
  tier (`ci/postgres.sh`, disposable `calendar_test_*` only): barrier-
  deterministic absent-row insert races (same bytes → one row, all
  ready; different bytes → exactly one winner, losers conflict),
  event-ordered `FOR UPDATE` serialization proof, cross-session
  identity-map refresh, drifted-replay staleness. Scoped fixtures
  (`uuid4` namespaces, own-row cleanup, parameterized SQL) coexist with
  the D1/D2 tests in the ordered tier run.
- Full-tier result (local disposable PG16): cutover + D1 + D3b1 + D2 =
  22 passed. `test_postgres_activity` + calendar files need the
  `psycopg` v3 driver, absent from this checkout's venv (pre-existing,
  unrelated to D3b1).

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
- Format/slot acceptance verifier (the publisher proves bytes, not
  playability).

## Rollback / rollout

- No migration (D1 `add_media_derivatives.sql` already live). No config,
  no Mac changes, no jobs/backfill/cleanup.
- Rollback: code rollback only (`git revert` / `ship.sh server --ref`).
  B2 orphans from crashed attempts are retained by design; never delete
  other objects. Ledger `ready` rows are append-only history.
- Activation: none. No route serves derivatives; no worker calls the
  publisher. D3b2 wires the fenced API after review.
