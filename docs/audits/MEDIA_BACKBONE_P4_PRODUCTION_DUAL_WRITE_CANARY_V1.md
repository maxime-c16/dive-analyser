# MEDIA_BACKBONE_P4_PRODUCTION_DUAL_WRITE_CANARY_V1 — Durable Audit

> Status: **P4_PRODUCTION_DUAL_WRITE_GREEN** (all closure gates complete).
> Date: 2026-09-09. Branch `media-backbone-p4-prod-dual-write-v1`
> (canonical ff-merged into `uiux-overhaul-pro-app`).
> Canonical pre-head `6ae5e3b…`, canonical post-head: see COMMITS.
> Supervisor gate: `SUPERVISOR_REVIEW_AFTER_MEDIA_BACKBONE_P4`.

## 1. What P4 proved

For ONE explicitly allowlisted NEW production clip (legacy path primary,
B2 PROD additive):

```
Photos edited rendition
        │ materialize ONCE (legacy media job 4389)
        ▼
 same canonical bytes (SHA a8579aa4…, 40,865,620 B)
        ├─→ EXISTING LEGACY PATH (unchanged; poster/360p/720p local_fs)
        └─→ B2 PROD diveanalyzer-prod-media
             SHA-addressed, private, full-GET verified
             → authenticated backend commit (HTTP, X-API-Key)
             → local journal → cleanup
```

Legacy success never depends on B2 success; failure semantics:
`LEGACY_SUCCESS + OBJECT_STORE_PENDING_RETRY`.

## 2. Resources

- Bucket `diveanalyzer-prod-media` (bucketId 7e720bcb6587827caf0b0a17),
  EU Central / Amsterdam (`s3.eu-central-003.backblazeb2.com`).
  Pre-existing with the authorized name. Object Lock: unverifiable with the
  application key (no lock-read capability) — **console check still owed by
  the maintainer**; bucket behavior is private (§8).
- PROD application key: bucket-scoped to `diveanalyzer-prod-media`;
  refresh/rotation performed by the maintainer before closure
  (`CHAT_EXPOSED_PROD_KEY_REVOKED = YES` — maintainer-attested; the active
  key is the post-rotation one, stored at 0600
  `/Users/Shared/services/data/diveanalyzer/state/object_store_prod.env`).
- Credentials: single PROD env file, 0600, owner divesensei; separate from
  the DEV file. No secret in Git, docs, logs, or reports. No presigned-URL
  logging.

## 3. P4_ACCEPTED_TEMPORARY_SECURITY_DEBT

The Backblaze console cannot express exactly
`{listFiles, readFiles, writeFiles}`; the bucket-scoped Read/Write preset
forces `deleteFiles` (plus bucket-settings caps). The maintainer explicitly
authorized proceeding for P4.

- `P4_ACCEPTED_TEMPORARY_SECURITY_DEBT = YES`
- `P5_OR_BROADER_PROD_BLOCKER = YES` — no broader PROD cohort until a
  deleteFiles-free key exists (B2 native API with master key offline) or
  the supervisor explicitly re-approves.
- Compensating controls: ingest path performs NO delete operations
  (`delete_object_explicit_operator_action` is outside every ingest/retry/
  rollback path, unit-tested); no automatic deletion anywhere; no delete
  test ever exercised; PROD canary blob retained by design (§34).

## 4. Privacy (real PROD bucket)

- anonymous bucket LIST → **403 denied**
- anonymous object GET → **401 denied** (re-verified post-commit)
- no public policy / ACL; presign GET works only signed
- retained synthetic preflight probe (content-addressed, 408 B):
  `blobs/sha256/72/72d94c7f….bin` — documented evidence object; no delete
  tested.

## 5. Production-safe commit transport (replaces P3 operator tunnel)

`POST /api/v1/media/backbone/commit` — implemented in
`backend/app/api/v1/media_backbone.py`:

- auth: existing `verify_api_key` (X-API-Key) — the established agent
  mechanism; no public endpoint; live-verified (no key → 401)
- accepts the canonical P2/P3 staged verified-ingest document
  `{payload, extra}` (receipt `input.payload` symmetry preserved)
- fail-closed validation (422): malformed UUID/SHAs, `remote_verified`
  false, storage backend ≠ `b2`, unknown bucket, dev/prod environment
  cross-wiring (allowlist via `MEDIA_BACKBONE_DEV_BUCKET` /
  `MEDIA_BACKBONE_PROD_BUCKET`), missing/unsupported environment,
  object key ≠ content-addressed key of the blob SHA, caption hash
  mismatch (via `commit_verified_ingest`)
- delegates to `commit_verified_ingest` — idempotent; repeated identical
  commits return the same logical result with zero duplicate rows
- agent transport: production HTTP commit via existing `_curl_post`
  (X-API-Key, internal CA), receipt validated + persisted 0600 at the P2
  convention path; restart convergence unchanged. P3 operator tunnel is
  **DEV/CANARY DIAGNOSTIC ONLY** (still in the repo, unused in production).

## 6. Feature flags and allowlist

- `object_store.enabled` (OBJECT_STORE_INGEST_ENABLED semantics) — default
  **false**
- `dual_write.enabled` (OBJECT_STORE_PROD_DUAL_WRITE_ENABLED semantics) —
  default **false**; requires object_store.enabled + environment == prod +
  credentials env file
- hard prod allowlist: EXACTLY ONE UUID (`validate_prod_allowlist`;
  count ≠ 1 → refuse; config validation wired; unit-tested 0/2/11/
  duplicate/malformed all refused)
- single backpressure slot (max one active materialization trigger)
- one-shot production-runtime modes (`run`, `caption-mutation`) share the
  same guards and the authenticated commit transport

## 7. Canary lineage (§23)

- identity: uuid `5F884C3D-5CEE-48E6-A40B-0AEB4DAAF4E8`, `IMG_2069.MOV`,
  hasadjustments=true, newest captioned clip; NOT in DEV backbone (0/52
  local journals; 0/10 server rows in any environment) — genuine first-time
  production dual-write
- caption: stable provider `osxphotos_description_stable`, exact bytes;
  shadow `PhotosDbCaptionProviderShadow` available, **exact_equal** both
  revisions; caption SHAs `c89fe307…` (initial) → `c1cee7b9…` (mutation)
- ONE materialization: legacy job 4389 materialized the edited rendition
  once; the dual-write hook staged a copy of those bytes 0.023 s after
  legacy success; recovery paths reused the checksum-validated vault bytes
  (`media-node/sources/by_uuid/<uuid>` — byte-identical to the blob) —
  `extra_photos_materializations = 0` in every snapshot
- legacy result: jobs 4387 poster / 4388 proxy_360p / 4389 proxy_720p all
  ready → cache entries 2263/2264/2265 (local_fs) — user path untouched
- B2: `blobs/sha256/a8/a8579aa42f828b19133f469a67e13dfde2ef8b79badc536a4b088e10c65ee178.mov`
  40,865,620 B; full remote GET SHA equality (3.69 s); ETag non-authoritative
- backbone DB (environment=prod): exactly 1 `media_blobs` / 1
  `media_revisions` (id 11, fingerprint v2 `169f8754…`) / 2
  `caption_revisions` (ids 12, 13 — after §32) / 1 `ingest_object_state`
  (DB_COMMITTED, verified)
- unchanged rerun: already_terminal, 0 new rows, 0 B2 bytes (§31)
- §32 caption-only mutation: new CaptionRevision id 13 (shadow exact_equal),
  old retained, same blob, same MediaRevision, **0 B2 upload**; unchanged
  rerun → `unchanged_caption` (idempotent, 0 additional revisions)
- rollback: flags off + daemon restart (21:30 local) → 0 object-store log
  lines, no ARMED line, sync + media polling healthy (3 videos synced),
  backend health 200, legacy playback ready via cache 2265; canary object
  retained (read-only HEAD diagnostic); additive DB rows untouched

## 8. Controlled failure injections

- §25 B2 PUT: first PUT injected-failed (retryable) → legacy unaffected →
  retry succeeded → full-GET verified → converged; exactly one remote blob
- §26 backend commit: commit attempt 1 injected-failed (lost response);
  B2 object retained; journal stayed REMOTE_VERIFIED; retry converged;
  DB = 1/1/1 rows (0 duplicates); PUT skipped (content-dedupe, 0 new bytes)
- both evidenced in immutable metrics snapshots (§9)

## 9. Metrics (packet §36/§37)

Run-unique immutable snapshots (O_EXCL — overwrite raises) under
`/Users/Shared/services/data/media-node/object_ingest_state_prod/metrics/`:

| snapshot | result | put B | get B | commit attempts |
|---|---|---|---|---|
| 20260909T191151450560_5f884c3d.json | pending_retry→converged | 40,865,620 | 40,865,620 | 4 (pre-fix 422s) |
| 20260909T191419611799_5f884c3d.json | verified_committed | 0 | 0 | 1 |
| 20260909T191557992024_5f884c3d.json | verified_committed | 0 | 40,865,620 | 2 |
| (caption-mutation snapshots) | caption_revision_committed | 0 | 0 | 1 |

Latency: staging copy 0.023 s (off the legacy critical path); B2 PUT
≈10–15 s steady state (40.9 MB); full-GET verify 3.69 s; HTTP commit
< 1 s; incremental legacy latency ≈ 0.02–0.05 s per job (staging copy
only — B2 work runs in a background thread after legacy finalize).
Disk: peak temp 40.9 MB (one staged copy, cleaned at CACHE_CLEANED);
free floor ~17.9 GB observed vs 10 GiB guard.
P3 runner metrics overwrite fixed: `metrics/p3_<run_id>.json` run-unique.

## 10. Pre-existing defect repaired (preflight finding)

The production agent daemon had been blind-since-boot: its connectivity
probe curled the HTTPS backend WITHOUT the internal CA (TLS 000) so
sync/media/heartbeat loops never started (logs prove the pattern
pre-dating P4 deploys). Repair: `is_online`/`wait_for_network` accept
`ca_cert_path`; main passes `config.server.ca_cert_path`. This restored
intended legacy behavior (no behavior change).

## 11. Mutation terminology (packet §46)

```
LEGACY_PRODUCTION_BEHAVIOR_MUTATION
NONE

BACKBONE_PRODUCTION_CANARY_DB_MUTATION
YES

PRODUCTION_OBJECT_STORE_MUTATION
YES — exactly one canary logical media lineage (+ 1 retained synthetic
preflight probe)

PRODUCTION_PLAYBACK_MUTATION
NONE

SCIENTIFIC_AUTHORITIES_MUTATED
NO
```

## 12. Tests

- backend: `test_media_backbone_commit_api.py` (10) + `test_media_backbone.py`
  (22) = 32/32; full suite 310 passed / 1 pre-existing failure
  (byte-identical baseline) → `NEW_FAILURES_INTRODUCED_BY_BRANCH = 0`
- mac-agent: 164/164 (148 baseline + 16 P4: allowlist guard, flags,
  one-materialization, B2 failure isolation + recovery, commit failure
  isolation + recovery, idempotent rerun, metrics immutability,
  caption mutation + refusals, legacy-compat gating)
- `git diff --check` clean; secret scan clean (no credentials/presigned
  URLs in diffs)

## 13. Commits (canonical ff-merged)

```
21ae6c6  P4 dual-write: endpoint + agent module + tests
a1ead55  daemon connectivity-probe CA repair
72980b0  ObjectStoreConfig.storage_backend + one-shot run mode
c0e89ab  backend endpoint: canonical {payload, extra} shape
58a1c25  run-mode staging-copy reuse
57e71da  staging-copy size verification
29aba5c  run-mode vault-first re-acquisition
956000e  fallback-block indentation fix
<this commit>  P4 closure: audit docs, PROJECT_STATE, migration plan
```

## 14. Explicit non-goals honored

No P5 athlete B2 playback; no B2 default media serving; no historical
migration; no legacy decommission; no Cloudflare/R2; no Object Lock usage;
no automatic remote deletion; no local media deletion; no DiveSensei
integration; no implicit whole-library readiness (album membership was not
treated as authorization); caption authority unchanged (PhotoKit caption
API remains out of scope; shadow stays read-only NON-AUTHORITATIVE).
