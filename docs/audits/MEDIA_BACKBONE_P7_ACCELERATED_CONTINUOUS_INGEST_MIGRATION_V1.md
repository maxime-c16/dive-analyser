# MEDIA_BACKBONE_P7_ACCELERATED_CONTINUOUS_INGEST_MIGRATION_V1 — durable audit

Task packet: `MEDIA_BACKBONE_P7_ACCELERATED_CONTINUOUS_INGEST_MIGRATION_V1`
(phases P7-A..P7-H). Executed 2026-09-10 on the canonical repository
`mcauchy@192.168.1.57:~/dive-analyser`, branch `uiux-overhaul-pro-app`,
reported base `5c48122c2d65dca49c341a942566e829303dbc3b` (P6 closure) —
verified fresh at packet start (`git rev-parse HEAD` matched exactly).

## 0. P6 state re-verification (fresh, before any change)

- Canonical HEAD `5c48122c…` verified via SSH; local Mac `~/.perso/diveanalyzer`
  again confirmed NOT a git repo (partial reference slice only).
- Untracked science artifacts (`experiments/landmark_pilot/*`,
  `docs/science/localization_annotations_v1/D5_ANNOTATION_BATCH/frames/`)
  present and NEVER staged/modified; science worktree
  `hurdle-identity-repair` untouched throughout (P7-A preflight + final
  status identical).
- Deployed production flags re-proved: `USER_AUTH_ENABLED=true`,
  `B2_PLAYBACK_CANARY_ENABLED=true` (server `.env`, backend healthy);
  backend container healthy; nginx 6090/6443 ingress unchanged.
- Mac agent runtime: config had `object_store.enabled=false`,
  `dual_write.enabled=false` (P4.2 cohort allowlist of 8 UUIDs retained as
  canary shape); daemon singleton healthy (exactly one instance).
- Backbone DB fresh: 15 media_revisions (ALL diver_id=1), 15 media_blobs,
  19 media_blob_locations (10 dev + 9 prod, all verified), 17 caption
  revisions, 15 ingest ledger rows (10 dev / 5 prod… final counts below).

## 1. P7-B: continuous production dual-write (§5/§6/§7)

**Trigger boundary (implemented exactly):** the pre-existing production
media-job event stream (`MediaJobProcessor._process_job`) passes the job's
`request_reason` to the dual-write trigger. `ProductionDualWrite.should_process`
now accepts:

- continuous mode (`dual_write.continuous_new_ingest=true`): ONLY jobs whose
  `request_reason` equals the configured `trigger_reason`
  (default `new_captioned_ingestion` — a genuinely NEW captioned production
  clip, created only for newly inserted dives by `_queue_new_captioned_media`);
- canary/debug mode (`continuous_new_ingest=false`): the unchanged P4.2
  bounded allowlist guard (5-10 explicit UUIDs, REFUSE TO ARM outside).

**No allowlist dependency in normal production (§7):** continuous mode
requires no hand-edited UUID lists; the allowlist field remains only for
canary/debug (and as a harmless debug filter). Rollback capability is fully
preserved (`dual_write.enabled=false` → byte-identical legacy-only behavior,
proven live §7-G below).

**Historical backlog isolation (§6):** enabling continuous dual-write adds NO
discovery/scanning surface: no Photos crawl, no DB walk, no album tap. The
only callers of `stage_copy` receive bytes already materialized by a real
production job. Renovation/population/upgrade jobs (request reasons
`catalog_population_stage_*`, `resolution_upgrade_720p`,
`representative_replacement`, …) for HISTORICAL assets are structurally
REFUSED (unit-tested for each reason + live daemon log). Historical media is
reached ONLY by the dedicated migration engine.

**Staging hardening (§24/§33):** `stage_copy` now checks free disk against
`min_free_disk_bytes` + the staged size BEFORE copying and records a bounded
`insufficient_disk_for_staging` marker instead of staging (legacy
unaffected); verified by test with an absurd guard.

**One materialization (§8):** unchanged P4 semantics — the legacy export is
the single source; `stage_copy` copies it; the dual-write driver reuses the
staged bytes (`extra_photos_materializations: 0`), never a second Photos
export.

**Legacy independence (§9):** `_trigger_dual_write` still catches every
failure → legacy result durable, object-store leg left pending-retry in the
journal; tests cover staging/launch failure isolation; live soak confirmed
lease-outage resilience (one transient 502 during backend recreation → next
poll 200 OK, no legacy effect).

## 2. P7-C/D/E: DB-driven inventory + bounded historical migration

**Inventory authority (§11/§12/§46):** new agent-key-gated read-only backend
endpoint `GET /api/v1/media/backbone/migration/inventory` returns, for every
MediaRevision, identity + storage facts ONLY (no captions, no filenames): the
deterministic chain `MediaRevision.video_uuid → dives (UNIQUE) → diver_id`,
verified DEV/PROD location facts with exact object keys, OWNER-binding facts
(`UserDiverAccess.access_kind='OWNER'`), byte sizes. An unresolved chain is
reported `has_diver_chain=false` → agent-side class E quarantine, never
guessed. Photos is NOT an inventory source (migration plan doctrine).

**Inventory result (computed BEFORE any byte op):**

| Class | Count | Bytes |
|---|---|---|
| A already verified PROD | 9 | — |
| B verified DEV only | 6 | 137,309,564 |
| C local source | 0 | — |
| D Photos/iCloud materialization | 0 | — |
| E ownership/source conflict | 0 | — |
| F missing | 0 | — |

15/15 revisions are OWNER (diver 1) with intact diver chains. Scope exactly
matches the existing Dive Analyzer logical corpus — no
MIGRATION_SCOPE_AUTHORITY_MISMATCH.

**Migration engine (§14/§25/§26):** new `mac-agent/src/ingest/migration.py`
(one-shot CLI modes `--inventory` / `--drive B` / `--status`; NEVER a daemon
component). Per-item durable journal (0600, atomic `tmp+os.replace`, keyed by
blob SHA) with states INVENTORIED → SOURCE_READY → LOCAL_VERIFIED →
PROD_UPLOAD_STARTED → PROD_UPLOADED → PROD_VERIFIED → DB_COMMITTED → CLEANED
(+ RETRYABLE with recorded `resume_state`, QUARANTINED, DEFERRED_INTERACTIVE,
SKIPPED_ALREADY_PROD). Strictly one active item; bounded waves; per-asset
persistence; no RAM queue; no fanout.

**Execution (P7-E):** one wave, 6/6 `CLEANED`, 0 retries, 0 quarantines:

- DEV GET (DEV canary key …0003, dev bucket only) → SHA == known blob SHA →
  bounded temp stage → PROD PUT (PROD ingest key …0006, prod bucket only) →
  full PROD GET → SHA equality (roundtrip §22) → authenticated commit
  (`environment=prod`) → temp cleanup.
- Metrics: dev_get 137,309,564 B / 14.6 s; prod_put 137,309,564 B / 16.3 s;
  prod_get_verify 137,309,564 B / 12.6 s; per-asset source-read 1.4-4.0 s,
  upload 1.9-3.3 s, verify 0.9-3.0 s; min free disk 17.85 GB (guard 10 GiB).
- Caption authority (§19): the EXACT original provider captions were reused
  from the original ingest receipts (matched by blob SHA + video UUID); no
  caption was manufactured from normalized legacy text; CaptionRevisions
  remained 17 (dedupe collapses identical re-commit).
- DB authority after migration: 15 blobs / 15 revisions / 17 caption
  revisions (ZERO duplicates); 15 verified PROD locations (all revisions
  PROD-backed); 25 ledger rows (10 dev + 15 prod).

**Idempotence (§27):** second complete pass over all 15 items → 6 CLEANED
journals respected with ZERO new byte ops/commits, 9 SKIPPED_ALREADY_PROD;
backend inventory now reports 15/15 `verified_prod` so a `--drive B` rerun
requests 0 items. 0 duplicate blobs/locations/uploads/commits.

**Content-Type (§10):** the 6 migrated objects were real PUTs with the
ffprobe-evidence MIME (`video/quicktime` verified by provider HEAD on the
migrated object); no historical `binary/octet-stream` object was rewritten.

**Safety (§35/§36):** copy-only — the migration module contains no
delete/hide primitives (static test bans the identifiers); legacy DEV
replicas, legacy cache, legacy files, Photos assets all untouched; DEV
locations remain (10 rows).

## 3. P7-F: playback convergence + authorization (§29/§30/§38/§41)

Automatic convergence proven WITHOUT frontend changes: temporary synthetic
OWNER (bound to diver 1, P6 pattern; deleted after proofs) sampled migrated
revisions 1, 3, 5, 10 (DEV→PROD class) + 11, 15 (already-PROD controls):

- `GET /api/v1/media/revisions/{id}/play` → 302 → presigned B2 → provider
  Range fetch 206 for ALL 6 samples (early/middle/late coverage).
- Unauthenticated: play 401, legacy video 401, legacy cache play 401.
- Wrong owner (no diver access account): play 404, legacy video 404.
- No manual playback mapping was created; policy is the P6 single-route
  source policy.

## 4. P7-G: soak, restart, rollback (§32/§49/§51)

- **Rollback proof (both directions, live):**
  1. `B2_PLAYBACK_CANARY_ENABLED=false` (auth stays on): play route 404
     fail-closed; authenticated legacy playback GREEN (legacy video 307 →
     cache 200); unauth legacy video 401. Re-enabled after proof.
  2. `dual_write.enabled=false`: daemon restarted → legacy loops fully
     healthy (sync/extract/media-job polling), zero object-store arming;
     re-armed after proof.
- **Soak:** bounded observation of production with continuous dual-write ON:
  daemon singleton (exactly 1 instance; historical singleton-refuse evidence
  still on record), 0 dual-write triggers (no new production clips during
  the run), staging dir empty, disk 17.4 GB free, backend healthy
  (lease 200s), playback 302-GREEN.
- **No natural new clip (§31):** last production ingest is 2026-09-09 (P4.2
  era). Per §31 the continuous path is validated by the offline integration
  suite (36 new mac-agent tests) + a live production-runtime wiring proof
  (one-shot continuous run-mode against an already-terminal journal asset →
  `already_terminal`, `zero_new_ops`) and is left correctly armed for the
  next natural clip.
- **B2 outage/backpressure (§33):** offline tests prove legacy continuity
  under B2 failure, one-active-materialization backpressure with bounded
  pending markers, and staging disk bounds; live staging refusal path
  test-covered. No staged-byte accumulation possible by design (staging copy
  exists for at most ONE asset; dropped after verified commit).

## 5. Metrics & cost (§43/§44/§45)

- Continuous ingest: 0 new legacy ingests observed during the run → 0
  dual-write attempts; legacy critical path overhead at zero events
  (staging copy measured at ~1-2 s per ~20-40 MB asset in the migration
  wave; the same copy operation is the continuous trigger's overhead).
- Historical: inventory 15 (A 9 / B 6 / C-E-F 0); migrated 6; skipped 9;
  retried 0; quarantined 0; deferred 0; missing 0. Bytes: 137,309,564 read
  from DEV; 137,309,564 uploaded to PROD; 137,309,564 full-GET verified.
- PROD bucket after P7: **16 objects, 345,568,956 bytes** (9 pre-existing
  media + 6 migrated + the retained P4 synthetic probe).
- Migration traffic: GET 137.3 MB (DEV) + 137.3 MB (PROD verify);
  uploads 137.3 MB.
- Cost estimate (documented pricing: $6.95/TB-month, first 10 GB free,
  egress free ≤ 3× storage, else $0.01/GB): storage ≈ 345.6 MB ≈ **$0.0024
  /month** (within free tier); egress fully within the free 3× allowance.
  No billing caps touched.

## 6. Tests

- New `mac-agent/tests/test_p7_continuous_ingest.py` (13 tests): activation
  boundary (exact-reason trigger, refusals for every other reason incl.
  population/upgrade/replacement/None), canary allowlist retained (with
  bounded-cohort guard), continuous arm requires no allowlist + REFUSES
  without object_store/prod env, staging accepts reason/refuses history,
  no-scan structural proof, insufficient-disk refusal marker, bounded
  backpressure marker, feature-off legacy-only, hook wiring, static
  no-delete firewall extension over migration.py.
- New `mac-agent/tests/test_p7_migration.py` (23 tests): classification
  matrix + fail-closed ownership + missing; scope guard never re-drives
  already-PROD; DEV→PROD full flow (bucket/environment binding, one PUT,
  one GET verify, DEV read-only, receipt caption verbatim reuse, temp
  cleanup); roundtrip SHA mismatch → quarantine with batch continuity;
  DEV-SHA-verified-before-PUT fail-closed; resume after mid-upload failure
  (exactly one successful PUT) and after commit failure (re-commit once, no
  re-upload); second-pass idempotence; PROD-object-present path (no DEV
  read, no upload, still full-GET verified + committed); local-source
  migration + SHA-tamper fail-closed; Photos materialization seam;
  interactive failure defers ONE asset while the wave continues; caption
  authority never manufactured; journal classification/state history;
  wave persistence with per-asset isolation; disk guard; min-free-disk
  recording.
- mac-agent full suite (production mac runtime): **218/218 passed**
  (182 pre-existing + 36 new).
- Backend: backbone + commit-api + P5 + P6 suites **102 passed** (+ the one
  documented pre-existing environmental failure: agent-coordinator path test
  inside the container). Media/auth/video keyword subset: 71 passed /
  5 skipped / 53 errors — all errors are the documented pre-existing
  SQLAlchemy/SQLite `visit_UUID` environment set (P6 baseline).
  `NEW_FAILURES_INTRODUCED = 0`.

## 7. Deployment evidence

- Backend: `docker-compose up -d backend` after bind-mounted code update;
  `/health` 200 (6090 + 6443); inventory endpoint live (15 items).
- Mac agent: code deployed to `/Users/Shared/services/data/diveanalyzer/code`
  (config.py, media_jobs.py, dual_write.py, migration.py + tests); daemon
  restarted via launchctl (singleton enforced); log:
  `P7 continuous dual-write ARMED: trigger reason 'new_captioned_ingestion'
  (bucket=diveanalyzer-prod-media); no allowlist dependency`.
- Production runtime config: `object_store.enabled=true`,
  `dual_write.enabled=true`, `continuous_new_ingest=true`,
  `migration.enabled=true` (state/temp dirs under media-node; separate DEV
  and PROD credential files; wave_size 3; min_free_disk 10 GiB).

## 8. Final production state (§50)

```text
USER_AUTH_ENABLED=true
B2 authenticated playback=true (B2 default + authenticated legacy fallback)
object_store.enabled=true
dual_write.enabled=true
continuous_new_ingest=true
allowlist dependency: REMOVED for normal production (canary/debug only)
historical migration: COMPLETE (15/15 verified PROD, 0 residuals)
```

## 9. Verdict

Continuous ingest GREEN + historical migration COMPLETE with zero residuals,
zero destructive operations, zero delete/hide (0), science untouched.

```
P7_CONTINUOUS_AND_HISTORY_GREEN
```
