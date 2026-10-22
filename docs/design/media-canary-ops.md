# Bounded web_package canary — admission/verification ops runbook

Status: tool + guard implemented locally, **not pushed, not deployed, NO
canary bytes produced here**. All production steps below are PARENT-run,
in order, after review + CI + merge. This slice performs NO prod query,
B2 write, job queue/config change, or deploy (local commit only).

Tool: `ops/canary_web_package.py` (DRY-RUN default; `--apply` admits at
most ONE job per run). Proof checker: `ops/canary_proof_check.py`
(schema + optional DB cross-check, never mints auth, never fetches
bytes). Proof collector: `ops/canary_proof_collect.py` (bounded
read-only evidence fetch with the OPERATOR's own private session cookies:
full-GET SHA+size, ffprobe + frame cadence, authorized 302/Range
206/unauth-denied/expiry -- never mints auth, fails closed). Budget
guard: `backend/app/services/canary_budget.py` (durable reservation
ledger `canary_slot_reservations` keyed by EXACT B2 namespace
bucket+object_key -- identical bytes under different keys are distinct
objects and count separately; same-key retry dedupes; orphan rows persist
across publisher rollbacks) + publish-time enforcement in
`POST /jobs/{job_id}/package/slots` (CANARY ONLY: scope derived from the
server-persisted job reason `canary_web_package`, never a client bool;
prestream is a size-cap-only advisory gate -- the route holds NO durable
row before fencing) and `derivative_publisher.publish_derivative(...,
canary_scope=<server-derived>)` (pre-upload reserve of the ACTUAL bytes
with the exact B2 key + verified-reuse PUT skip, canary-scoped only --
never a global cap on future packages). Migrations (additive, manual,
BEFORE deploy, idempotent): `backend/migrations/add_canary_slot_reservations.sql`
then `backend/migrations/add_canary_slot_reservation_exact_key.sql`.
Tests: `backend/tests/test_canary_budget_d3b2.py` (helpers) +
`backend/tests/test_canary_ops_cli_d3b2.py` (CLI: admit/verify/resume/
phase2-fresh-proof/host-facts, scope/orphan/stale-proof/reuse, SQLite fake DB) +
`backend/tests/test_postgres_canary_budget_d3b2.py` (real-PG concurrency:
two-attempt cap race, orphan persistence, replay dedupe, PUT-skip).
Tests: `backend/tests/test_canary_budget_d3b2.py` (helpers) +
`backend/tests/test_canary_ops_cli_d3b2.py` (CLI: admit/verify/resume/
phase2/parallel-dedup/budget-failure/host-facts, SQLite fake DB).

Bounds (hard, shared by tool + guard + tests):

- Phase 1: <= 5 clips. Only on 100% PROOF (5/5 proven -- explicit
  proof records, never ready-only) may phase 2 admit <= 25 additional
  (fleet total <= 30, DB-authoritative: a reset state dir can never
  bypass the total).
- New B2 bytes HARD cumulative <= 2 GiB, counting EVERY attempted
  unique stored object including safe orphans (durable
  `canary_slot_reservations` ledger keyed by EXACT B2 namespace
  bucket+object_key: identical bytes under different clips/roles/versions
  are distinct objects and count separately; same bucket+key retry
  dedupes; same-key/different-bytes fails closed). Estimates are
  PREFLIGHT ONLY; the slot route refuses overshoot authoritatively with
  409 BEFORE bytes stream for CANARY jobs only (claimed-size pre-check +
  per-slot cap, NO durable row -- untrusted route claims never consume
  committed budget for another job; the D2 fenced guard still runs
  row-locked in the publisher), and the publisher reserves the ACTUAL
  bytes pre-upload with the exact B2 key (deduped; verified-reuse skips
  the PUT when the same key already proves the same bytes, so retries
  create no new B2 version). Per-slot caps (canary
  only): hq <= 1.2 GB, light <= 700 MB, poster <= 8 MB.
- ONE package active fleet-wide (lease cap + tool serial gate: the tool
  never queues while ANY package job is active, queues at most one
  per run, and concurrent admits serialize on a PG advisory lock + a
  local state-dir file lock held only for the short DB decision, never
  across network -- never 30 at once despite the global lease allowing 1).
- Canary jobs queue at priority 60 (backfill level): interactive
  user_view/automatic_review/evaluation_request (5/6) and ingestion (10)
  always win the lease ordering, so the watch lease never starves.
- Admission is idempotent/resumable: ready clips skipped, active jobs
  never duplicated (`create_or_reuse_media_job` reuses the DB row after
  a crash; `--state-dir` is a resume hint, the DB cohort is the
  authority), caps count only NEW unique IDs (re-listing an admitted
  clip costs zero), `--state-dir` (private, outside git) resumes.
- Stop new admissions when: Mac Data free < 8 GiB
  (`df /Users/Shared/services/data` on the Mac), server cache volume
  free < 25 GiB (`df` on the `MEDIA_CACHE_ROOT` mount, default
  `/app/media-cache`, on deb-serv), Mac memory pressure != normal
  (`memory_pressure` warn/critical stops admission), host facts older
  than 15 min, consecutive failures >= 2, or source unknown
  (no canonical revision / dims / size / duration — fail closed).
  Host facts are an operator-provided private JSON file
  (`--host-facts F.json`, 0600, OUTSIDE the repo; the tool never
  probes hosts itself):
      {"mac_free_bytes": 9663676416, "server_cache_free_bytes": 32212254720,
       "mac_memory_pressure": "normal", "checked_at": "2026-10-21T20:00:00+00:00",
       "mac_data_path": "/Users/Shared/services/data/diveanalyzer",
       "server_cache_path": "/app/media-cache"}
- Sources: dims-known, square-pixel preferred (known SAR!=1 is blocked
  at publish by the exact-dims check — safe orphan, no promotion).
  Bounded original sizes/durations keep the worst-case estimate
  meaningful. No Photos fallback except strict source-SHA proof (the
  worker enforces this; the tool only admits clips WITH a verified B2
  canonical source).
- Photos/originals: never touched. No global backfill, no delete/unpin,
  no grace/threshold change, no MAC stop-cache-empty.

## Gate 0 — code review, CI, merge, deploy (parent, in order)

1. Review this branch (tool + guard + tests + this runbook). Merge to
   `master` ONLY on explicit APPROVE.
2. Apply the additive migration on the server DB BEFORE deploy (parent,
   manual): `psql $DATABASE_URL -f backend/migrations/add_canary_slot_reservations.sql`
   (idempotent; creates `canary_slot_reservations` only). Without it
   the slot route fails closed with 409 (ledger missing) -- no canary
   bytes can publish.
3. `ci/ship.sh status` → `ci/ship.sh server --dry-run` → `ci/ship.sh server`
   for the merge SHA. Verify: live SHA, backend image SHA, direct + LAN +
   public health, both nginx reloads, `MEDIA_JOBS_REQUIRE_LEASE_TOKEN`
   still `true`, `MEDIA_WEB_PACKAGES_ENABLED` still `false`,
   `MEDIA_WEB_PACKAGES_AUTO_INGEST_ENABLED` still `false`.
3. Mac deploy for the SAME merge SHA: `ci/ship.sh mac` (code only; no
   config change in this gate). Verify agent SHA, stable pid.

## Gate 1 — managed server master flag ON, auto-ingest stays OFF (parent)

With a healthy capable worker NOT yet required (no queueing happens
without a lease, and leases need the worker — but the flag alone with
auto-ingest OFF queues nothing new, so this order is safe):

```bash
# On deb-serv, in ~/.config/diveanalyzer/media-jobs.env (mode 600, never Git):
MEDIA_WEB_PACKAGES_ENABLED=true
MEDIA_WEB_PACKAGES_AUTO_INGEST_ENABLED=false   # stays false: no broad ingestion
# Same-SHA activation (env changed, code identical):
ci/ship.sh server --dry-run --force --ref <merge-sha>
ci/ship.sh server --force --ref <merge-sha>
```

Verify in the running env: master `true`, auto-ingest `false`
(`docker compose exec backend env | grep MEDIA_WEB` shows values from
the forwarded env file — aggregate flag check only, never echo secrets).
Proof of no broad effect: new ingests still queue legacy poster + 720p
(lease + queue audit shows zero `web_package` jobs).

## Gate 2 — enroll ONE canary worker capability (parent, approved method)

1. Add `web_package` to `media.capabilities` in the canary worker's
   MANAGED Mac config (keep `["poster", "proxy_720p"]` + append;
   preserve every other key; no manual secret edit — config method only,
   secrets stay in the existing runtime config, no new tokens).
2. Redeploy Mac code if needed (`ci/ship.sh mac --dry-run`, then `mac`)
   so the worker restarts with the new capability; verify stable pid.
3. Verify enrollment on BOTH sides before ANY admission:
   - Mac heartbeat shows the capability;
   - server `agent.allowed` capability enrollment shows `web_package`
     for exactly one agent.
   Silent stranded jobs (capability missing on either side) are a
   misconfiguration: stop, fix enrollment, never retry as legacy.

## Gate 3 — bounded canary admission (parent, reviewed tool, user auth)

Under user authorization, night limits (first <= 5; stop NEW admissions
after 08:00 Paris if unproven):

```bash
# 1. Private allowlist OUTSIDE the repo (0600; explicit UUIDs, dims-known
#    small sources preferred; never committed to Git):
cat ~/.config/diveanalyzer/canary-manifest.json   # {"phase":1,"clips":["<uuid>"...<=5]}

# 2. Fresh host facts OUTSIDE the repo (0600; checked_at <= 15 min old,
#    memory pressure explicit; the tool never probes hosts itself):
cat ~/.config/diveanalyzer/canary-host-facts.json
# {"mac_free_bytes": 9663676416, "server_cache_free_bytes": 32212254720,
#  "mac_memory_pressure": "normal", "checked_at": "<ISO-8601 now>",
#  "mac_data_path": "/Users/Shared/services/data/diveanalyzer",
#  "server_cache_path": "/app/media-cache"}
# Mac: df /Users/Shared/services/data + memory_pressure status.
# Server: df on the MEDIA_CACHE_ROOT mount (/app/media-cache).

# 3. Read-only readiness (bounded queries, aggregate output, no secrets):
DATABASE_URL='<runtime>' python3 ops/canary_web_package.py \
  --manifest ~/.config/diveanalyzer/canary-manifest.json \
  --state-dir ~/.config/diveanalyzer/canary inventory

# 4. Admit EXACTLY ONE (dry-run first, then explicit apply with host facts):
DATABASE_URL='<runtime>' python3 ops/canary_web_package.py \
  --manifest ~/.config/diveanalyzer/canary-manifest.json \
  --state-dir ~/.config/diveanalyzer/canary \
  admit --phase 1 --host-facts ~/.config/diveanalyzer/canary-host-facts.json
DATABASE_URL='<runtime>' python3 ops/canary_web_package.py \
  --manifest ~/.config/diveanalyzer/canary-manifest.json \
  --state-dir ~/.config/diveanalyzer/canary \
  admit --phase 1 --apply --host-facts ~/.config/diveanalyzer/canary-host-facts.json
# Re-run admit (plan or apply) ONLY after the queued job reaches a
# terminal state AND the clip is PROVEN: serial, one at a time.
# Phase 2 additionally requires --phase1-manifest (exact phase-1 cohort):
#   admit --phase 2 --phase1-manifest ~/.config/.../phase1-manifest.json \
#     --apply --host-facts ... (refused unless 5/5 phase-1 proven + DB cohort)
```

`DATABASE_URL` comes from the existing runtime config (same value the
server uses); it is passed through the environment, never printed,
logged, or stored by the tool.

## Gate 4 — verification proofs (parent, per clip, before next admission)

READY != PROVEN. `verify` records ledger-readiness only (`ready_seen`);
it NEVER marks proven. Phase 2 requires explicit proof records.

```bash
DATABASE_URL='<runtime>' python3 ops/canary_web_package.py \
  --manifest ~/.config/diveanalyzer/canary-manifest.json \
  --state-dir ~/.config/diveanalyzer/canary verify
# Schema-check a proof record without writing (stdlib only; --db adds
# the DB cross-check with the runtime DATABASE_URL):
python3 ops/canary_proof_check.py --proof ~/.config/.../proof-<uuid>.json
DATABASE_URL='<runtime>' python3 ops/canary_proof_check.py \
  --proof ~/.config/.../proof-<uuid>.json --db
# Record a validated proof (schema + DB cross-check enforced; ready-only
# NEVER marks proven; failure leaves phase 2 blocked):
DATABASE_URL='<runtime>' python3 ops/canary_web_package.py \
  --manifest ~/.config/diveanalyzer/canary-manifest.json \
  --state-dir ~/.config/diveanalyzer/canary prove --proof ~/.config/.../proof-<uuid>.json
```

Proof record (private JSON, OUTSIDE the repo, 0600) carries the exact
evidence -- source/version, per-slot artifact SHA+bytes
(format/frame counts in `checks`), and auth/range/expiry outcomes::

    {"video_uuid": "<uuid>", "source_sha256": "<64hex>",
     "source_revision_id": 123, "transform_version": "<v>",
     "slots": {"hq"|"light"|"poster": {"derivative_sha256": "<64hex>",
                                       "byte_size": 123}, ...},
     "checks": {"b2_full_get_sha_match": true, "ffprobe_clean": true,
                "frame_cadence_match": true, "library_auth_302": true,
                "range_206": true, "grant_expiry_checked": true,
                "logged_out_denied": true},
     "recorded_at": "<ISO-8601>", "operator": "<name>"}

All `checks` must be boolean true (evidence required); the tool
cross-checks every slot SHA against the READY ledger rows for the
CURRENT source + transform and rejects on source/revision drift. No
fake or minted bypass exists: B2 and Library checks run with the
operator's own existing user session (see `canary_proof_check.py`
curl checklist); logged-out and expired-grant denials are required
evidence, never assumed.

Required per clip (all must hold before the NEXT admission; phase 2
only after 5/5 PROVEN):

1. Reused source SHA: job pin == canonical B2 source SHA (lease pin,
   slot guard, and ledger agree; no Photos bytes unless exact SHA proof).
2. Outputs SHA: FULL B2 GET of each slot == ledger
   `derivative_blob_sha256` (streamed bytes, never HEAD-only); ffprobe
   format/tags/faststart clean; frame cadence matches source nominal
   (encoder-proven; server decode probe is corruption-only).
3. Original intact: canonical source revision bytes + SHA re-read
   unchanged after publication.
4. Library authorized route: 302 to presigned B2 with a live user
   session; `Range` returns 206 with correct content-type; expired-grant
   replay denied; logged-out request denied (no auth bypass for probes).
5. Ledger: 3 (or 2 + `hq_aliased_to=light`) `ready` rows + verified PROD
   replicas for the CURRENT source + transform; no non-allowlisted
   `web_package` job queued (leases + queue audit).
6. NOT claimed: playback on an actual device Safari, or anything
   beyond proxied-desktop verification, stays unproven until a later
   device pass explicitly covers it.

## Rollback / stop

- Stop queueing: `admit` already serial — just stop running it. If any
  flag was flipped: both flags back to `false` + same-SHA
  `ci/ship.sh server --ref <sha> --force`. In-flight package leases
  reclaim normally on expiry (legacy flows unaffected).
- Drain before downgrade: wait until NO `web_package` job remains in a
  leased status; then server-downgrade first, Mac second (order matters:
  a downgraded server 404s slot uploads, which is safe but churny).
- Schema stays (additive D1 columns). D2 fencing stays enforced.
  Ledger `ready` rows and B2 orphans are retained, never deleted.

## Gaps (returned concretely, not promised away)

1. **Orphan accounting is reservation-based, not B2-reconciled.**
   Retained B2 orphans (crashed attempts, SAR!=1 refusals, stale-token
   uploads, claim/actual mismatches) ARE counted via the durable
   `canary_slot_reservations` ledger (same-SHA retry dedupes; corrupt
   claims fail closed and over-count). What is NOT built: a B2
   prefix-listing vs ledger reconciler (would catch bytes written
   outside the reservation path, e.g. a future non-canary bug). The
   bound is therefore hard for all canary-path bytes and conservative
   (over-counts) for corrupt claims; a full B2 audit remains a later
   slice and is NOT claimed here.
2. **No display-dims/SAR provenance server-side.** `MediaBlob` holds
   coded dims only; SAR!=1 honest output fails closed at publish (safe
   orphan, reservation retained) but spends uplink. Mitigation:
   dims-known + phone-camera preference; the narrow fix (nullable
   `display_width/height` at ingest) is documented in
   `web_packages.check_small_source_alias`, not built here.
3. **Host facts are operator-provided (freshness-enforced).** The tool
   enforces fresh (`checked_at` <= 15 min), free-space (8 GiB / 25 GiB
   on the real `df` paths above), and explicit
   `mac_memory_pressure == "normal"` stops -- but never probes hosts
   itself. Automated host telemetry is a later slice; a stale or
   pressured host fails closed here (no admission).
4. **Evaluation consumers untouched.** Library playback (D5) is the only
   reader in this slice; evaluation-grid consumers stay on legacy
   previews until the canary is proven (parent decision, later night).
5. **Not yet proven in this slice (candid):** end-to-end B2 full-GET
   SHA + ffprobe + frame-cadence + Library 302/Range/expiry checks have
   NOT been executed here (no prod queries, no B2, no deploys in this
   task). The `prove` gate enforces the evidence shape and DB
   cross-check, but the per-clip device/Safari pass stays explicitly
   unproven until a later device pass covers it (checklist item 6).

`Release notes: none — internal, flag-off, no user impact.`
