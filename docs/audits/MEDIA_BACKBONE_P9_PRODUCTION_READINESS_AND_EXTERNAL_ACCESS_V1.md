# MEDIA_BACKBONE_P9_PRODUCTION_READINESS_AND_EXTERNAL_ACCESS_V1 — Durable Audit

> Task packet `MEDIA_BACKBONE_P9_PRODUCTION_READINESS_AND_EXTERNAL_ACCESS_V1`.
> Executed 2026-09-10 on top of the accepted P8 state (canonical HEAD
> `9da23103df7385b3f10aaa6e27bcd663c07d5c92`, fresh-verified on server +
> Mac). Branch `media-backbone-p9-production-readiness-v1`.
> Verdicts: **P9_PRODUCTION_READINESS_GREEN**,
> **CONTINUOUS_NATURAL_INGEST_PENDING**,
> **EXTERNAL_ACCESS_PROVIDER_GATE**,
> **LEGACY_DECOMMISSION_DRY_RUN_READY** (LEGACY_PHYSICAL_DELETION_READY = NO).
> Absolute counters: **B2 delete/hide = 0; legacy media deleted = 0;
> Photos deletes = 0; science mutated = NO; secrets in Git = NO.**

## 1. Fresh preflight (verified)

- Canonical `mcauchy@192.168.1.57:~/dive-analyser` @ `9da2310` (branch
  `uiux-overhaul-pro-app`); worktree `~/.perso/diveanalyzer-p9` branch
  `media-backbone-p9-production-readiness-v1` created from that HEAD.
- Deployed backend healthy; `USER_AUTH_ENABLED=true`,
  `B2_PLAYBACK_CANARY_ENABLED=true`; `CORS_ALLOW_ORIGINS` exact list
  (no wildcards).
- Mac production config: `object_store.enabled=true`,
  `dual_write.enabled=true`, `continuous_new_ingest=true`,
  `migration.enabled=true`, vault enabled.
- DB: 15 revisions / 15 verified PROD locations / 25 ledger rows
  (all DB_COMMITTED) / 1 real OWNER user + 2 historical synthetic
  negatives (P9-D cleanup target).

## 2. P9-B — continuous natural ingest (STILL PENDING, instrumentation now durable)

`CONTINUOUS_NATURAL_INGEST = STILL_PENDING`. No legitimate new captioned
clip entered the legacy pipeline during the P8+P9 windows (dives = 2805
throughout; 0 active media jobs; extractor reports 0 new dives ready).
No synthetic production clip was created to force the gate.

P9 added the durable passive capture so the next natural clip closes the
gate WITHOUT an operator watching:

- `dual_write.stage_copy` records trigger provenance ONCE (0600 stage
  meta): `triggered_at`, `request_reason`, `activation` (continuous vs
  allowlist) — first-trigger-wins, never clobbered.
- Every dual-write run's metrics snapshot now carries `trigger` +
  `commit` (durable server-side identity summary from the commit receipt:
  environment, blob SHA, PROD location id, revision/caption/ledger ids).
- New read-only composer `mac-agent/src/ingest/natural_ingest_evidence.py`:
  stage meta + journal + evidence + commit receipt + metrics →
  `natural_ingest/<uuid>.json` (0600), NO raw caption content, with a
  completeness gate (exact request reason, trigger ts, legacy success,
  legacy-byte reuse, 0 extra Photos materializations, media SHA, PROD
  location commit, terminal CACHE_CLEANED) and a `--latest` CLI
  (exit 3 = nothing observed yet).
- Deployed LIVE to the production agent runtime (daemon restarted under
  launchd singleton; dual-write re-armed and healthy).

## 3. P9-C — backup authority (GREEN, live)

PostgreSQL business/auth metadata (the ONLY database authority):

- **Policy frozen**: `docs/architecture/BACKUP_AND_RETENTION_V1.md` +
  machine-readable `ops/retention_policy_v1.json` (test-enforced).
- **Backup executor live**: `ops/postgres-backup.sh` — daily 03:15 cron
  (installed, existing crontab preserved), `pg_dump -Fc` → AES-256-CBC +
  PBKDF2 encryption (key 0600, never in Git) → `pg_restore --list`
  readability gate (fail-closed) → retention (14 daily + 8 weekly) →
  optional restricted-key off-host rsync.
- **Live evidence**: backup 2.58 MB, total 3 s (dump 1 s / encrypt <1 s /
  verify 1 s); off-host push to the ingest Mac OK; sha256 manifests
  equal on both hosts (`85833958…fb4`).
- **Off-host credential**: dedicated ed25519 push key; the Mac's
  authorized_keys entry is restricted (`restrict,from="192.168.1.57"`);
  discovered and repaired live: an invalid `pty=no` sshd option made
  macOS sshd ignore the line (replaced by `restrict`); rsync needed
  `--no-times --no-perms` under the restricted key (repaired).

## 4. Restore validation (GREEN, live, non-destructive)

`ops/postgres-restore-test.sh`: decrypt newest archive → restore into an
ISOLATED throwaway postgres:16 container (loopback-only port) →
row-count reconciliation vs production for 14 critical tables →
ownership-chain + verified-PROD-location proofs. Production DB never
written. **Live PASS**: decrypt 0 s / restore 45 s / total 73 s; all 14
tables equal (app_users, user_credentials, user_sessions,
user_diver_access, login_attempts, media_playback_grants, dives 2805,
divers 23, media_blobs 15, media_revisions 15, caption_revisions 17,
media_blob_locations 25, ingest_object_state 25, security_audit_log 4);
ownership chain 15/15; verified PROD locations 15/15.

## 5. B2 recovery model (documented, no new provider)

B2 PROD = primary durable application-media backbone (content-addressed,
private, least-privilege keys). V1 operating assumption: single-provider
durable copy + Photos source + legacy retained. RECOMMENDATION recorded in
BACKUP_AND_RETENTION_V1 §5: before any physical deletion becomes ready, a
second independent replica (second cloud or offline) should exist —
decision left to the human; NO provider was created.

## 6. Retention policy (FROZEN)

`ops/retention_policy_v1.json` + BACKUP_AND_RETENTION_V1 §6: verified PROD
media retained indefinitely (no automatic delete/hide); caption/media
revisions append-only; legacy cache + /videos = rebuildable caches only;
Photos never deleted; logical delete = DB-state design only (§7), physical
purge = separate delayed operator lifecycle. Invariants test-enforced.

## 7. P9-D — production user/session cleanup (GREEN)

- Audited: `app_users` had 3 rows — 1 real (maxime → diver 1 OWNER) +
  2 historical synthetic negatives (`p5-synthetic-negative@test.local`,
  `p6-negative@example.test`) with live + revoked sessions.
- Removed both synthetic accounts from production via SQL with
  `user_disabled` audit rows appended first (trail preserved, now 6 rows).
  Session cascade verified: **0 orphan sessions** (before AND after);
  removed-account login → uniform 401 (no existence oracle).
- Production end state: exactly **1 legitimate real user**; test-database
  fixtures untouched (none exist in production).
- Bounded session cleanup re-verified structurally (P6/P8 suites 51/51).

## 8. P9-E — external access (all machine-side work DONE; one provider action)

- Fresh cloudflared audit (read-only): `cloudflared-navidrome.service` =
  ephemeral QUICK tunnel (`--url http://127.0.0.1:4533`), no config/credentials
  on the host, no owned hostname; periodic DNS-refresh errors visible in
  journal. Decision: **separate NAMED tunnel** for Dive Analyzer (the
  navidrome service was not touched at any point).
- No owned Cloudflare domain exists (DuckDNS `mcauchysmontreuil` cannot
  host the required CNAME) → the hostname requires a human choice.
- **External-path evidence (temporary quick tunnel, ~25 min, then torn
  down — verified dead, HTTP 530)** from a genuinely external client:
  - login with exact Origin → 200, cookie HttpOnly+Secure+SameSite=Strict
  - foreign Origin → 403; wrong password → uniform 401
  - unauth: B2 play 401 / legacy video 401 / legacy check 401 / me 401
  - wrong-owner (temporary non-owner identity, created + removed; audit
    retained): B2 play 404, legacy video 404, legacy cache play 404
    — no externally reachable historical IDOR
  - owner: 302 → presigned B2; provider ranged GET 206 (bytes 0-65535 of
    21,601,174; `video/quicktime`); seek range 206; expired presign →
    provider 401 → fresh grant → 302/206
  - 15 external grants per pass; error bodies privacy-safe (no paths,
    no bucket/keys in JSON bodies, no stack traces, no other-diver data);
    `private, no-store` / `no-referrer` / `nosniff` headers present
  - two temporary synthetic identities used for the login/wrong-owner
    proofs were deleted afterwards (0 production users besides the owner;
    audit trail retained)
- Machine-side prep committed (NOT enabled): named-tunnel config + systemd
  unit (separate from navidrome) + loopback-only `127.0.0.1:6091` external
  vhost (`/adminer/` refused; `Host $http_host` preserved; trusted-proxy
  chain unchanged) + activation checklist (EXTERNAL_ACCESS_V1 §7-§8).
- NO router ports opened; no raw public nginx; no wildcard origins; no
  B2 CORS change (not required — same-origin 302 proven externally).

## 9. P9-F — extended playback/ingest soak (GREEN)

- **Playback grants (automated representative + external, P9 window)**:
  **192 ALLOWED** / 16 DENIED (intentional negative probes) /
  0 provider failures / 0 unexpected outcomes / 0 presign leaks. Target
  ≥ 100 exceeded (P8 had 62+). Tool: `backend/scripts/playback_soak.py`
  (operator session mint, read-only traffic, privacy-safe summary;
  static-tested for no destructive primitives).
  Metrics: end-to-end grant latency avg ~202 ms (max 881 ms, incl.
  provider ranged fetch); presign-path avg ~77 ms (max 726 ms);
  in-process grant_refresh counters live (32 on one pass).
- **Continuous ingest soak**: single production daemon (launchd, singleton
  guard), ledger 25/25 DB_COMMITTED, 0 staging bytes in temp, 17 GiB free,
  0 active media jobs, no retryable backlog. Daemon live-redeployed
  (P9-B instrumentation) and re-armed without incidents.
- **§40 rollback revalidated LIVE**: `B2_PLAYBACK_CANARY_ENABLED=false` →
  play route fail-closed 404 → authenticated legacy video 307→200
  (video/mp4) with Range 206; unauth 401; then flags restored (play → 302).
  User auth never disabled. (Operational note: this host uses standalone
  `docker-compose`; the `docker compose` plugin is absent.)

## 10. §41 metrics durability (GREEN)

In-process counters (auth_metrics, playback_metrics) are per-worker and
reset on restart. Durable equivalents now exposed via
`app/services/ops_metrics.py` (aggregation over the append-only
`login_attempts` / `media_playback_grants` / `security_audit_log`, 24 h
window, no identifiers) wired into `/api/v1/auth/metrics` and
`/api/v1/media/playback/metrics`. Live-verified after a backend restart:
in-process counters 0, durable block correct (31 login success / 19
failure / 192 allowed / 16 denied / security events). No analytics system.

## 11. §28/§29 reconciliation (GREEN, live)

- Storage reconciliation (tool `backend/scripts/storage_reconciliation.py`):
  **15/15 eligible OWNER revisions have exactly one verified PROD
  location (100%), 0 drift**, 0 non-owner revisions.
- B2 inventory (tool `mac-agent/src/ingest/b2_inventory.py`, read-only
  LIST with the least-privilege ingest key + DB inventory endpoint):
  **16 objects / 345,568,956 bytes**, all content-addressed, 15/15
  verified DB keys present, 1 documented P4 preflight evidence object
  (72d94c7f…, 408 B) — 0 unexplained orphans, 0 missing real media.
  Orphans are reported only; nothing deleted/hidden.

## 12. P9-G — legacy dry-run readiness (DRY_RUN_READY; deletion NOT authorized)

Live dry-run (`backend/scripts/legacy_dry_run.py`, DRY-RUN ONLY, no delete
primitives — static-tested):

- **Cache (server media-cache, container view)**: 1718 files / 890 MB;
  29 files (10.7 MB) classified as B2-derivable candidates (the 15
  verified-PROD revisions' derivations) with the blocking dependency
  "cache is the ACTIVE playback/poster substrate"; 1689 files conservative
  KEEP (no verified replacement).
- **/videos (§32 classification, evidence-backed)**: 176 files / 14.28 GB,
  ALL `IMG_*.MOV` icloudpd downloads; **0 of 176 match any dives
  video_uuid** (production dives.video_path NULL for all 2805 dives);
  `video_labels.video_filename` references UUID-named files only;
  provenance = `ops/icloud-video-sync.sh` (icloudpd `--size original`
  downloads copied into the app cache for the historical fallback era);
  recovery = iCloud re-download (icloudpd). Classification:
  **ORPHAN_CACHE/SOURCE_ARTIFACT — reclaimable candidate, NOT authorized;
  not a hidden recovery authority** (iCloud is the source authority).
- **Source vault (13 GB / 440 sources)**: ACTIVE_REQUIRED; bounded-cache
  conditions documented (needs CONTINUOUS_NATURAL_INGEST=GREEN + recovery
  strategy not depending on the vault). DESIGN ONLY.
- **Science data**: excluded from every reclamation calculation; the
  tool enumerates the science root as KEEP-only.
- Prerequisites scorecard: all §30 prerequisites GREEN except
  CONTINUOUS_NATURAL_INGEST (PENDING) and the rollback-independence of
  legacy bytes. Per §37 the dry-run verdict is allowed with the explicit
  `LEGACY_PHYSICAL_DELETION_READY = NO`.

**LEGACY_DECOMMISSION_VERDICT: LEGACY_DECOMMISSION_DRY_RUN_READY**
(with LEGACY_PHYSICAL_DELETION_READY = NO).

## 13. Production flags (final, live-verified)

`USER_AUTH_ENABLED=true`, `B2_PLAYBACK_CANARY_ENABLED=true`,
`object_store.enabled=true`, `dual_write.enabled=true`,
`continuous_new_ingest=true`, `migration.enabled=true`.
All rollback paths proven (§9 above). No flag weakened to complete P9.

## 14. Test results

- mac-agent (production venv, deployed code): **248/248** (incl. 12 new
  P9-B evidence tests + 5 B2-inventory tests).
- Backend container: `test_p9_production_readiness.py` **10 pass + 1 skip**
  (mac-agent-source static firewall skips in the container layout —
  passes in full layouts); P5(21)+P6(30)+P8(10)+media_backbone(91 pass)
  — the 1 media_backbone failure is the PRE-EXISTING env-only static
  test (`/mac-agent` path inside the container), byte-identical on base.
- Restore test: PASS (§4 above).
- Repair during testing: tests initially imported without `os` import;
  `_client_for` signature; reconciliation expectations fixed to the
  seeded world (1 OWNER binding); wildcard-origin assertion corrected to
  the structural exact-match property; sha256 manifest filename mismatch
  in the backup script repaired.

## 15. Deployments performed (production)

- Backend: new durable-metrics code + scripts deployed (docker cp) and
  backend restarted twice (rollback proof + restoration) — healthy after
  each restart; flags returned to the desired state.
- Mac agent: P9-B instrumentation deployed to the production runtime;
  daemon restarted under the launchd singleton; dual-write re-armed
  ("P7 continuous dual-write ARMED" in the live log).
- Server ops: postgres-backup.sh + cron + encryption key + off-host
  restricted push key (documented in BACKUP_AND_RETENTION_V1); the
  navidrome cloudflared service was NOT modified; no external config was
  enabled on the live host.

## 16. Next gate

`SUPERVISOR_REVIEW_AFTER_MEDIA_BACKBONE_P9` — the single remaining
HUMAN_PROVIDER_ACTION (external hostname/tunnel) is in
EXTERNAL_ACCESS_V1 §7; the natural-clip window continues passively;
legacy physical deletion remains blocked (§5a conditions).
