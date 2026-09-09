# MEDIA_BACKBONE_P4_3_STORAGE_AUTHORITY_HARDENING_V1 — Durable Audit

> Status: **P4_3_COMPLETE** — storage-authority repair, reconciliation, and
> overnight hardening GREEN. Date: 2026-09-10 (overnight execution).
> Canonical pre-head `268bfe5cde4959261e5aca2d1c75acf834610698`
> (`uiux-overhaul-pro-app`). Canonical final head: `572516f…` (see §18).
> Previous accepted states: `P4_PRODUCTION_DUAL_WRITE_GREEN`,
> `PROD_KEY_HARDENING_GREEN`, `P4_2_COMPLETE / PRODUCTION_COHORT_GREEN`.
> **No P5 authorization; this packet does NOT start P5.**

## 0. Unattended execution

Fully unattended: no human click, no password, no TCC/Keychain/Automation
prompt, no sudo, no new credential, no Backblaze UI action, no Photos edit,
no new media ingest, no display-keeping. Every operation used existing
passwordless SSH contexts and existing runtime credentials read-only.
`INTERACTIVE_STEPS_REQUESTED = 0`. Dual-write flags remained **OFF**
throughout (verified live at close: production config `enabled: false`
for `object_store` and `dual_write`).

## 1. Cross-environment storage diagnosis (§2 gate) — DEFINITIVE

**Finding: the pre-P4.3 schema could NOT represent the same SHA in the DEV
and PROD buckets simultaneously without losing one location.**

Evidence chain (fresh, at P4.3 start):

1. Model: `MediaBlob` carried `storage_backend` / `bucket` / `object_key` /
   `remote_object_id` on the content-identity row (one row per SHA).
2. Service: `commit_verified_ingest` looked up the blob by SHA and, when it
   existed, wrote nothing location-related — the location columns were set
   only on first creation.
3. Live DB (environment rows): 15 `media_blobs` (10 `diveanalyzer-dev-media`
   + 5 `diveanalyzer-prod-media`), no row representing both. The four
   P4.2 dev-overlap UUIDs (901A95AF, F2A9B8CC, BB513C7F, EB4ACB9E) had
   `ingest_object_state` rows with `environment=dev` only — despite P4.2's
   verified 8/8 PROD uploads. Their commit receipts prove the PROD commits
   returned `blob_existed=true / media_revision_existed=true /
   caption_revision_existed=true` and the ledger lookup (then unique on
   `(video_uuid, object_key)`, with identical content-addressed object keys
   in both buckets) found the DEV row — so the PROD commit event was never
   durably recorded.

The supervisor hypothesis is confirmed: the model conflated CONTENT IDENTITY
with PHYSICAL STORAGE REPLICA.

## 2. Storage model decision (§3)

**Additive repair** (existing model invalid for the target semantics):

- **CONTENT AUTHORITY**: `media_blobs` = content identity only (one row per
  SHA-256, immutable content metadata). Its location columns are retained
  as **transitional / non-authoritative** first-seen fields; they are
  documented as such in the model and are NOT removed in this packet.
- **STORAGE LOCATION AUTHORITY**: new `media_blob_locations` table — one
  row per physical replica: `blob_sha256`, `environment`, `storage_backend`,
  `bucket`, `object_key`, `remote_object_id`, `verified`, `verified_at`.
  Uniqueness: `(storage_backend, bucket, object_key)` (physical replica
  identity; same key with conflicting SHA can never be inserted) and
  `(blob_sha256, storage_backend, bucket, object_key)` (storage-location
  dedupe).
- **ENVIRONMENT AUTHORITY**: environment lives in the physical
  storage/commit context (commit environment + bucket allowlist), never in
  the SHA. `commit_verified_ingest` and the commit API both enforce
  environment→bucket mapping (`dev` → `diveanalyzer-dev-media`, `prod` →
  `diveanalyzer-prod-media`) fail-closed from the same settings.
- **P5 LOOKUP**: internal-only helpers `resolve_verified_location(db, sha,
  environment)` and `resolve_media_revision_location(db, video_uuid,
  environment)` give the deterministic verified location for an
  environment; `verified=false` locations are never returned. No P5
  playback surface implemented.

## 3. Schema changes (§6)

`backend/migrations/add_media_blob_locations.sql` — additive, idempotent:

- `CREATE TABLE IF NOT EXISTS media_blob_locations` + 5 indexes.
- Environment-scoped ledger uniqueness: creates
  `ix_ingest_object_state_clip_env_key_unique` on
  `(video_uuid, environment, object_key)` FIRST, then drops the conflated
  pre-P4.3 `ix_ingest_object_state_clip_key_unique`. No data row deleted or
  rewritten; the replacement authority exists before the old index is
  removed.
- Idempotent backfill: one location row per currently-known `media_blobs`
  location (`WHERE NOT EXISTS`), with environment derived from the two
  canonical environment buckets only; any other bucket is NOT backfilled
  (fail-closed — an unmapped location must be reconciled explicitly, never
  invented). `verified_at` = blob row `created_at` (every backbone blob row
  was inserted only after full remote-GET SHA verification, the P2 rule).
- Reversibility documented in-file; `media_blobs` columns untouched.

Tested on REAL Postgres 16 (scratch DBs in the production container):
empty DB → re-run idempotent; cross-environment seeded state (dev-only,
prod-only, pre-existing location row, same video_uuid+key in dev AND prod)
→ exactly the expected rows, old index gone, replacement present; live DB
backfill → 0 duplicates.

## 4. Commit service repair (§10) and commit API (§11)

`commit_verified_ingest` now separates the two dedupe operations:

```
get_or_create MediaBlob by SHA                     → content identity
get_or_create MediaBlobLocation by
    (blob SHA, environment, backend, bucket, key)  → physical replica
get_or_create MediaRevision (video_uuid, blob SHA)
get_or_create CaptionRevision (video_uuid, caption SHA)
ledger row per (video_uuid, environment, object_key)
```

Verified behaviors (backend tests, 52 passing):

- repeated identical commit → 0 duplicate rows (all three `*_existed`
  returns, stable ids);
- same SHA replay in one environment → 0 duplicates;
- DEV → PROD first PROD commit of the same SHA → 0 duplicate blobs +
  1 new PROD location (blob's transitional columns untouched);
- same SHA in DEV + PROD → exactly 2 locations;
- wrong bucket for environment / PROD-referencing-DEV /
  DEV-referencing-PROD → rejected (service AND API, 422);
- same location key with conflicting SHA → rejected, fail closed;
- `verified=false` location → not playback-eligible (lookup returns None);
- P5 lookup: media revision + PROD → one deterministic verified location;
- ledger env-scoping: same (video_uuid, object_key) in dev AND prod →
  2 logical ingest events;
- caption exactness, idempotence, lost-response retry, feature-off and
  legacy-compatibility tests unchanged and green.

Commit API response extended additively: `media_blob_location_id`,
`blob_location_existed`. The API's existing fail-closed firewall
(environment allowlist, bucket allowlist, content-addressed key check,
malformed identifier rejection) is unchanged and now backed by the same
service-level validation (defense in depth).

## 5. Live reconciliation (§7/§27/§28) — completed, fail-closed

**Classification: `DATA_RECONCILIATION_REQUIRED_AND_COMPLETED`** (together
with `SCHEMA_REPRESENTATION_GAP_REPAIRED`).

- Backup first (§28): bounded `pg_dump` export of ONLY the five backbone
  tables to `~/backups/backbone_p4_3_before_reconciliation_20260910_001112.sql`
  (35,730 B, mode 600) on the server. No athlete media copied; captions
  remained in the existing DB only. Recovery procedure: restore = run the
  two backbone migrations then the dump; additive migration needs no
  destructive rollback.
- Backfill: migration ran on the live DB → 10 DEV + 5 PROD location rows,
  0 duplicates.
- Reconciliation plan (before any mutation): the four P4.2 dev-overlap
  PROD commits are missing from DB authority. Plan counts: 4 new location
  rows, 4 new env=prod ledger rows, 0 new blobs/revisions/captions.
- Method: **idempotent replay of the durable P4.2 commit receipts** — each
  receipt contains the exact staged verified-ingest document
  (`input.payload` + `input.extra`) that was posted to the commit endpoint;
  fail-closed pre-checks per row (environment==prod, bucket==PROD
  allowlist, `remote_verified`, caption SHA == sha256(caption_raw bytes),
  receipt result SHA equality, existing blob row byte_size equality,
  existing PROD location row (from the first partial replay) bound to the
  same SHA), then `commit_verified_ingest` replayed transactionally per
  UUID with per-row expected-result assertions. One implementation bug of
  the replay tool itself (nested transaction wrapper) caused the first
  replay to commit (exactly as expected) before erroring; the tool was made
  idempotency-aware and re-driven to completion — the committed row was
  verified to match its receipt exactly before continuing (fail-closed
  takeover, not blind trust).
- Post-mutation counts: `media_blobs` 15, `media_revisions` 15,
  `caption_revisions` 17 (all UNCHANGED — zero duplicate logical rows);
  `media_blob_locations` = 19 (10 dev + 9 prod, all verified=true);
  `ingest_object_state` = 19 (15 + 4 env=prod replay rows).
- B2 read-only HEAD verification (existing runtime key, no writes): all
  four dev-overlap SHAs present in the PROD bucket with byte sizes exactly
  matching the journals and DB rows (§9 below).

## 6. §16 P4.2 report reconciliation — exact classification

**`SCHEMA_REPRESENTATION_GAP_REPAIRED` + `DATA_RECONCILIATION_REQUIRED_AND_COMPLETED`.**

P4.2's conclusion "4 DEV-overlap clips copied to PROD" was operationally
true (bytes uploaded, full-GET SHA-verified) but their PROD copies were NOT
durably represented before this packet: zero `environment=prod` rows and no
PROD bucket reference existed for those four SHAs. The P4.2 "cross-
environment content-dedupe" was correct at the CONTENT level and silently
lossy at the storage-location level — the exact gap P4.3 was designed to
probe. Both the schema gap and the data gap are now closed with receipts as
durable evidence.

## 7. Cross-environment test cases (§9) — the four DEV-overlap objects

Identified from fresh evidence (live DB + P4.2 receipts + journals +
read-only B2 HEAD):

| UUID | SHA-256 (full) | DEV loc | PROD loc | B2 PROD bytes (HEAD-verified) |
|---|---|---|---|---|
| 901A95AF-8F4F-48EC-872D-32ABC96AAA52 | `9f934028ad0a80a337deac66147d3b68418b974a4ffe0e6067642eb524d2dca1` | 1 | 1 | 11,470,391 ✓ |
| F2A9B8CC-D65E-411B-8175-5B61C4A325BE | `8207a664e6fab98e1410e9945d898cecf24a5719756671e96358bc9252857111` | 1 | 1 | 13,811,585 ✓ |
| BB513C7F-2454-4D13-AFF0-1E54260E67FC | `9114f887845ea026eeb93d2ae6223765011eb1803b78542e3bf0a79cf69b6ba6` | 1 | 1 | 17,209,995 ✓ |
| EB4ACB9E-B49D-4BBF-A92E-46B228E7544F | `d8d02a65af7ccfc4a7bc3ca48b07ef8cbbb6faf3a910852f5117687c319df24b` | 1 | 1 | 15,937,716 ✓ |

Final durable shape per shared SHA: **MediaBlob = 1, DEV location = 1,
PROD location = 1** — no ambiguity (SQL proof in §10).

## 8. Ingest state / media revision / caption revision semantics (§12–§14)

- **`ingest_object_state` = logical ingest event ledger**, one row per
  `(video_uuid, environment, object_key)`. The pre-P4.3
  `(video_uuid, object_key)` uniqueness was the DEV/PROD ambiguity source
  and was repaired additively (index swap, no data change). It remains a
  server-side commit ledger, never read by agent orchestration; the local
  JSON journal remains the macOS execution/recovery authority.
- **`MediaRevision` = logical edited media revision**; it is keyed by
  `(video_uuid, blob_sha256)` and does NOT duplicate per environment. After
  the repair, a DEV→PROD content commit creates zero new MediaRevisions
  (verified in the live replay: `media_revision_existed=true` for all 4).
  Storage replicas live only in `media_blob_locations`.
- **`CaptionRevision` = business/history state**, keyed by
  `(video_uuid, caption_sha256)`; it does not duplicate on a DEV→PROD copy
  (verified live: `caption_revision_existed=true` for all 4). No caption
  semantics changed in this packet.

## 9. P5 lookup precondition (§15) — deterministic proof

`resolve_media_revision_location(db, video_uuid, "prod")` executed against
the live DB for all four shared UUIDs returns exactly one verified PROD
location row (blob→content→`environment=prod, verified=true`), each
matching its B2 HEAD byte size. In-SQL equivalent proof (deterministic,
unambiguous): every shared SHA yields `dev_locs=1, prod_locs=1` and no
other row; per-environment bucket allowlists make `(blob, environment)` a
single-verified-replica query. No athlete playback, no presign endpoint,
no frontend changes.

## 10. Duplicate daemon (§19) and singleton guard (§20)

- **Diagnosis:** a second full `src.main` daemon instance (PID 28973,
  PPID 28971, started 17:30:32, ~24 MB RSS / 3.6 s CPU over 6 h) was live
  beside the canonical LaunchAgent (36191→36193). Its ancestry is the P4.2
  §2 preflight SSH probe chain (`zsh -c … probe A/B`) — the runtime app
  binary is a DAEMON LAUNCHER (it always spawns `python -m src.main`), so
  invoking it as an SSH probe inadvertently started a full production
  daemon with the production config. Log forensics prove it NEVER got past
  its connectivity wait (no sync loop started; zero production work owned);
  it sat in the 600 s-timeout wait_for_network retry loop for 6 h,
  interleaving its `Network offline` lines into the shared application.log
  with no PID attribution (the root of the P4.2 "intermittent 000" confusion).
- **Action:** terminated cleanly (SIGTERM; graceful
  "Shutdown requested before sync loop started" at 23:40:34; probe chain
  exited). Exactly one intended production agent instance remained.
- **Singleton guard:** `mac-agent/src/daemon_lock.py` — pid/lock file
  (`<config dir>/daemon.lock`, 0600) with stale-owner verification (pid
  alive + `ps` start-time match + `src.main` command marker). Wired ONLY
  into `src.main`'s full-daemon mode; `--extract-only`, `--library-stats`,
  and the one-shot ingest CLIs (`src.ingest.dual_write`,
  `src.ingest.canary`) are untouched by design.
- **Live hardening (auto-repair loop):** the first deploy exposed two real
  bugs, both fixed and re-proven same-night: (a) `ps -o lstart=` emits the
  VALUE ONLY (no header) on macOS — the header-row assumption returned
  None for every live owner so instances stole the lock (observed live:
  the test instance took the lock and began racing the canonical daemon;
  terminated, fixed); (b) `lstart=` output is LOCALE-dependent ("Thu Sep
  10" under the daemon's C locale vs "Jeu 10 sep" under fr_FR SSH) —
  cross-context verification now forces `LC_ALL=C`. Stale takeovers are
  logged at WARNING.
- **Live proof (§20 contract):** canonical instance 38300 holds the lock;
  a second full instance launched from a French-locale SSH session REFUSED
  safely (`DAEMON_SINGLETON_REFUSE` logged at ERROR, main returned without
  starting any loop, lock untouched). Exactly one production agent
  instance before and after.
- Deployed agent code verified byte-identical to canonical pre-head
  268bfe5 before deploy; backup at
  `/Users/Shared/services/data/diveanalyzer/code/src.pre_p43_20260910`;
  post-deploy LaunchAgent restart healthy (loops running, lock held,
  probe green instantly).

## 11. Connectivity probe (§21)

- Diagnosed WITHOUT changing TLS authority (internal CA stays
  authoritative; no verification weakening, no offline detection silenced).
- **Mechanical bugs repaired:** (a) probe failures were invisible — curl
  exit code and stderr were swallowed at DEBUG so intermittent `000`s were
  undiagnosable; `is_online` now surfaces the curl exit code + stderr tail
  at WARNING; (b) `NetworkMonitor.check_connectivity()` probed WITHOUT the
  internal CA (TLS-handshake failure guaranteed offline verdicts) — the
  class now accepts and propagates `ca_cert_path`; (c) every log line now
  carries `pid:<pid>` so multi-instance log interleaving is attributable
  (the exact condition that made P4.2's finding ambiguous).
- The orphan daemon's persistent 000-loop was an artifact of the broken
  single-instance diagnosability; its own underlying curl failure mode
  remains formally `INSUFFICIENT_EVIDENCE` (its cause was only visible at
  DEBUG and the process is now gone); with (a)–(c) any recurrence is
  diagnosable in minutes. Live post-fix probe: immediate success.

## 12. iCloud materializer timeout (§22) — code/design only, no Photos test

The 600 s cap was hardcoded (`DEFAULT_EXPORT_TIMEOUT_SECONDS = 600`).
Implemented bounded configurable `media.materialization_timeout_seconds`:

- default 600 = current production behavior retained exactly;
- validated bounds [30, 3600] (never unlimited; refusals tested);
- wired through `Config` → `MediaJobRunner._build_pipeline` →
  `MediaMaterializer.export_timeout_seconds` (wiring tested);
- production config NOT changed overnight (live value remains 600 by
  default — no code change needed for future tuning).

## 13. P4.1 synthetic objects (§17)

**Classification: `EXTERNAL_OR_MANUAL_REMOVAL_MOST_LIKELY`.** Fresh
read-only LIST: PROD bucket = 10 objects (P4 preflight probe 408 B +
canary + 8 cohort blobs); `bc1fece7…` (784 B) and `a5f2bc63…` (12 MB)
absent, consistent with P4.2. Project-code deletion excluded (runtime key
hard-delete 401; zero delete/hide log matches; static no-delete firewall;
the probe-cleaning `b2-preflight` never re-ran since P4 — its object is
still present). Provider lifecycle rules cannot be excluded (bucket
lifecycle config is not readable with the least-privilege key). Nothing
recreated or deleted. Not a P5 blocker.

## 14. DEV admin key audit (§18) — audit only

`diveanalyzer-dev-agent` (`…0001`, account-wide admin) — see the P4.3
section in `MEDIA_BACKBONE_SECURITY_V1.md`: zero runtime references found
(DEV ingest uses bucket-scoped `…0003`; PROD uses `…0006`); production does
not depend on it; DEV ingest requires no admin capability. Recommendation:
revoke it in a future maintainer-attended step; treat it as
dormant-but-dangerous debt. No rotation, no secret exposure.

## 15. §24 constraints honored

Dual-write flags OFF throughout (verified in the live production config at
close); new media ingested 0; B2 write operations 0; B2 delete/hide 0;
production playback mutation NONE; legacy production behavior mutation
NONE (rendition paths untouched); science authorities untouched;
secrets added to Git NONE; DB writes confined to the backbone tables
within the P2–P4.2 authorized scope (additive schema + reconciliation of
the four dev-overlap rows).

## 16. Tests (§25/§26/§33)

- Backend backbone suites (container, Postgres-available host): **52 pass**
  (35 pre-existing + 17 new storage-location/API/migration-guard tests
  covering the full §25 matrix).
- mac-agent (production venv on the production Mac): **192/192**
  (171 baseline + daemon-lock, connectivity, and timeout suites).
- Migration on REAL Postgres: empty-DB idempotence, cross-env seeded state,
  re-run idempotence, index swap verified.
- Full backend suite: `1 failed / 312 passed / 38 skipped / 273 errors` —
  the single failure (`test_dive_analysis_service::
  test_difficulty_adjusted_execution_is_explicit_and_not_a_raw_score_replacement`)
  reproduces byte-identically on the PRE-P4.3 deployed code (baseline
  failure, not introduced by this branch; the 273 errors are the
  documented pre-existing sqlite/postgres-UUID analysis-model collection
  errors). `NEW_FAILURES_INTRODUCED_BY_BRANCH = 0`.
- `git diff --check` clean; secret scan clean; large-media scan clean
  (no media committed).

## 17. Commits (canonical)

```
88b8595  P4.3 storage authority hardening: content identity vs physical
         storage replicas — additive media_blob_locations + idempotent
         backfill, env-scoped ledger uniqueness, commit-service
         content-vs-location dedupe separation, P5 internal lookup
         helpers, real-Postgres migration tests; mac-agent daemon
         singleton guard, connectivity probe diagnosability repair,
         bounded configurable materialization_timeout_seconds
572516f  P4.3 daemon singleton guard: live-deploy repairs found
         same-night (ps lstart header suppression + locale dependence),
         §20 contract proven live
<docs>   P4.3 closure: durable audit, PROJECT_STATE P4.3 handoff,
         TARGET/SECURITY/STATE-MACHINE storage-authority sections,
         migration plan P4.3 COMPLETE
```

## 18. Verdict

All packet success targets met: the DB now represents one content SHA with
any number of verified physical locations, unambiguously per environment;
the four P4.2 dev-overlap PROD replicas are durably represented with
receipt-backed evidence and B2 HEAD byte verification; repeated identical
commits create zero duplicates; DEV→PROD content commits create exactly one
new location; conflicting locations/environments are rejected at two
independent layers; the ledger is environment-scoped; the P5 lookup
precondition is proven deterministic. Exactly one production daemon runs
under a proven singleton guard; connectivity probes are diagnosable; the
materializer timeout is bounded-configurable.

**P4_3_COMPLETE — P5_STORAGE_AUTHORITY_READY. STOP before P5.**
