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
cookie ONLY to the explicit validated Library origin, NEVER auto-followed
to storage; presigned storage Range/full-GET/expiry-replay fetched in
separate credential-free requests with per-hop allowlist validation;
full-GET SHA+size, ffprobe + source-bound frame cadence (video: SHA-pinned
source reference with exact frames + timing tolerance; poster still N/A),
strict content-type, authorized 302/Range
206/401-404-denied/measured-expiry -- never mints auth, fails closed). Budget
guard: `backend/app/services/canary_budget.py` (durable reservation
ledger `canary_slot_reservations` keyed by EXACT B2 namespace
bucket+object_key -- identical bytes under different keys are distinct
objects and count separately; the SAME key retried charges AGAIN per
PUT attempt (verified full-GET reuse skips both PUT and charge);
orphan/failed-PUT rows persist across publisher rollbacks, never refunded) + publish-time enforcement in
`POST /jobs/{job_id}/package/slots` (CANARY ONLY: scope derived from the
server-persisted job reason `canary_web_package`, never a client bool;
prestream is a size-cap-only advisory gate -- the route holds NO durable
row before fencing) and `derivative_publisher.publish_derivative(...,
canary_scope=<server-derived>)` (per-slot-cap check, then pre-PUT
full-GET reuse probe, then per-PUT charge committed BEFORE the PUT
streams + verified roundtrip, canary-scoped only --
never a global cap on future packages). Migrations (additive, manual,
BEFORE deploy, idempotent): `backend/migrations/add_canary_slot_reservations.sql`
then `backend/migrations/add_canary_slot_reservation_exact_key.sql`
then `backend/migrations/add_canary_put_attempt_charges.sql` (drops the
UNIQUE bucket+key constraint: same-key duplicates are concurrent/retry
attempts, each counted).
Tests: `backend/tests/test_canary_budget_d3b2.py` (helpers) +
`backend/tests/test_canary_ops_cli_d3b2.py` (CLI: admit/verify/resume/
phase2-fresh-proof/host-facts, scope/orphan/stale-proof/reuse, SQLite fake DB) +
`backend/tests/test_postgres_canary_budget_d3b2.py` (real-PG concurrency:
distinct-key cap race, SAME-KEY racers each charge, same-key cap race
one-wins, orphan persistence, PUT-skip) +
`backend/tests/test_canary_proof_collect_e2e.py` (collector fakes: 302,
credential-free full-GET SHA corruption, Range 206 with STRICT content-type
(video/mp4 hq/light, image/jpeg poster; text/html refused), logged-out denial
(401/403/404 only; NO redirect counts -- not a grant redirect, not a
same-origin login/playback redirect), measured exact-object expiry denial, cookie isolation on
two distinct local origins + redirect chains, malicious/userinfo
redirect refusal, SOURCE-BOUND frame cadence (synthetic 60fps preserved pass /
30fps transcode reject / drop reject / missing-ref + SHA-mismatch fail-closed /
VFR count+duration with PTS-exact NOT claimed / poster still N/A / real-ffmpeg
synthetic 60-vs-30 census / bounded -count_frames with no frame list),
missing ffprobe, proof-gate source-integrity + cadence-evidence checks).
Tests: `backend/tests/test_canary_budget_d3b2.py` (helpers) +
`backend/tests/test_canary_ops_cli_d3b2.py` (CLI: admit/verify/resume/
phase2/parallel-dedup/budget-failure/host-facts, SQLite fake DB).

Bounds (hard, shared by tool + guard + tests):

- Phase 1: <= 5 clips (first wave may stop early, but a smaller wave
  NEVER unlocks phase 2). Only on 100% PROOF of EXACTLY 5 distinct
  phase-1 clips (5/5 proven -- explicit
  proof records, never ready-only) may phase 2 admit <= 25 additional
  (fleet total <= 30, DB-authoritative: a reset state dir can never
  bypass the total).
- New B2 bytes HARD cumulative <= 2 GiB, counting EVERY attempted
  PUT including safe orphans and failed PUTs (durable per-PUT charge
  ledger `canary_slot_reservations` keyed by EXACT B2 namespace
  bucket+object_key: identical bytes under different clips/roles/versions
  are distinct objects and count separately; the SAME bucket+key retried
  charges AGAIN per attempt -- each PUT may store a new B2 version, and
  a concurrent same-key race that both misses the pre-PUT full-GET
  reuse check PUTs twice, so both attempts must count; the one-package
  lease does NOT serialize duplicate HTTP/stale in-flight B2 attempts.
  Same-key/different-bytes fails closed (corrupt claim, no charge).
  Verified full-GET reuse (same key already proves the same bytes)
  skips the PUT and charges nothing new). Estimates are
  PREFLIGHT ONLY; the slot route refuses overshoot authoritatively with
  409 BEFORE bytes stream for CANARY jobs only (claimed-size pre-check +
  per-slot cap, NO durable row -- untrusted route claims never consume
  committed budget for another job; the D2 fenced guard still runs
  row-locked in the publisher), and the publisher charges the ACTUAL
  bytes per PUT with the exact B2 key AFTER the reuse GET misses and
  BEFORE the PUT streams (cap-checked under a PG advisory lock,
  committed before the PUT so orphans stay counted, never refunded;
  replay over-counts rather than under-counts). Per-slot caps (canary
  only): hq <= 1.2 GB, light <= 700 MB, poster <= 8 MB.
  The pre-charge READY baseline ALWAYS counts per exact derivative object (not
  per SHA), PLUS every attempt charge -- a successful canary PUT counts twice
  by design (charge + baseline). This intentional conservative over-count keeps
  the 2 GiB bound STRICTER than actual stored bytes (monotonic, never UNCOUNTs a
  baseline row, never lets actual stored exceed the budget when the proof passes),
  and a READY row with no blob size fails the proof closed
  (no silent under-count). Only a DEFINITE-absent reuse GET (typed NoSuchKey/404)
  authorizes charge+PUT; any other reuse GET failure fails closed with no PUT.
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
2. Apply the additive migrations on the server DB BEFORE deploy (parent,
   manual): `psql $DATABASE_URL -f backend/migrations/add_canary_slot_reservations.sql`
   then `add_canary_slot_reservation_exact_key.sql`
   then `add_canary_put_attempt_charges.sql`
   (idempotent; create the `canary_slot_reservations` per-PUT charge ledger). Without them
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
# Phase 2 additionally requires --phase1-manifest (EXACTLY 5 distinct phase-1 clips):
#   admit --phase 2 --phase1-manifest ~/.config/.../phase1-manifest.json \
#     --apply --host-facts ... (refused unless EXACTLY 5/5 distinct phase-1 proven + DB cohort + fresh proofs)
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
# Collect read-only evidence with YOUR session (cookie ONLY to the
# explicit Library origin; storage fetched credential-free; expiry ONLY
# via a measured denial; video cadence ONLY via a SHA-pinned source
# reference -- see ops/canary_proof_collect.py --help):
python3 ops/canary_proof_collect.py \
  --play-url '<library-play-url>' \
  --library-origin '<https://library-host>' \
  --storage-origin '<https://b2-host>' \
  --expired-url '<expired-grant-same-object>' \
  --expected-sha '<ledger-sha>' --expected-size <ledger-bytes> \
  --cookies ~/.config/diveanalyzer/canary-cookies.txt \
  --slot light --video-uuid '<uuid>' --operator '<name>' \
  --source-storage-url-file ~/.config/diveanalyzer/source-url-<uuid>.txt \
  --expected-source-sha '<db-canonical-source-sha>' \
  --expected-source-size <db-canonical-source-bytes> \
  --out ~/.config/diveanalyzer/proof-<uuid>-light.json
# --source-storage-url-file: private file OUTSIDE the repo (0600) holding
#   exactly the operator-supplied current canonical-original presigned URL
#   (existing authorized access; the tool never mints presigns). Same
#   validated --storage-origin, credential-free bounded full GET AFTER the
#   derivative GET; hashed MUST equal --expected-source-sha/size.
#   REQUIRED for hq/light (missing/mismatch fails closed; local
#   --source-reference alone never proves B2). Poster runs omit it
#   (video cadence explicitly N/A -- still scope).
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
evidence -- source/version, per-slot artifact SHA+bytes, source-bound
cadence evidence, and auth/range/expiry outcomes::

    {"video_uuid": "<uuid>", "source_sha256": "<64hex>",
     "source_revision_id": 123, "transform_version": "<v>",
     "slots": {"hq"|"light"|"poster": {"derivative_sha256": "<64hex>",
                                       "byte_size": 123}, ...},
     "checks": {"b2_full_get_sha_match": true, "ffprobe_clean": true,
                "frame_cadence_match": true, "library_auth_302": true,
                "range_206": true, "grant_expiry_checked": true,
                "logged_out_denied": true, "source_bytes_sha_match": true,
                "original_storage_integrity_checked": true},
     "cadence_evidence": {"source_sha256": "<64hex>", "source_frames": 600,
                          "source_fps": 60.0, "source_duration": 10.0,
                          "outputs": {"light": {"frames": 600, ...}}, ...,
                          "vfr": false, "pts_exact_claimed": false},
     "source_integrity_evidence": {"sha": "<64hex>", "size": 123,
                          "measured_at": "<ISO-8601>",
                          "method": "full_get_after_publication"},
     "recorded_at": "<ISO-8601>", "operator": "<name>"}

All `checks` must be boolean true (evidence required); the tool
cross-checks every slot SHA+size against the READY ledger rows for the
CURRENT source + transform and rejects on source/revision drift.
`cadence_evidence` is REQUIRED for video slots: `source_sha256` must
equal the proof source (bound reference); `outputs` covers EXACTLY the
video slots present (hq/light; poster is explicitly N/A and never
listed); every output frame count EXACTLY equals the source count (a
nominal 60->30 transcode fails even though the output count is
positive); fps/duration within tolerance (VFR preserved by
count+duration); `pts_exact_claimed` is always false -- per-frame PTS
exactness is NOT proven by the bounded `-count_frames` census (which
never loads an unbounded frame/packet list) and claiming true is
refused. `source_integrity_evidence` is REQUIRED for video slots:
`sha`/`size` must equal the proof source/canonical blob size,
`method` must be `full_get_after_publication` (actual B2 re-read, never
local scratch/metadata), `measured_at` ISO-8601, no URLs/secrets. The DB
cross-check additionally requires the canonical source blob row to still
exist plus a verified PROD replica AND the evidence SHA/size to match
the canonical bytes (revision metadata or local scratch alone never
suffices). Slots
must be `hq+light+poster`; `light+poster` (no HQ) is accepted ONLY with
a server-trusted DB producer alias proof (the clip's `web_package` job
`finalized_slots` pin matches the proof source/revision/version with
`hq_aliased_to == "light"`, durable complete, AND the durable resolver
still validates the alias) -- the proof JSON claim or coded-dims
inference alone never suffices, and unknown alias state requires HQ.
No
fake or minted bypass exists: B2 and Library checks run with the
operator's own existing user session (see `canary_proof_check.py`
checklist -- cookie to the Library origin only, storage fetched without
credentials); logged-out denial means 401/403/404 (an unauthenticated
302 to a presigned grant is access, NOT denial; NO redirect counts
(including same-Library-origin login/playback redirects)) and expired-grant denial means a MEASURED
credential-free replay of an expired grant for the EXACT object with a
provably-past timestamp (a live grant's expiry parameter alone never
counts; there is no wait loop for a live TTL) -- never assumed.

Required per clip (all must hold before the NEXT admission; phase 2
only after 5/5 PROVEN):

1. Reused source SHA: job pin == canonical B2 source SHA (lease pin,
   slot guard, and ledger agree; no Photos bytes unless exact SHA proof).
2. Outputs SHA: FULL B2 GET of each slot == ledger
   `derivative_blob_sha256` (streamed bytes, never HEAD-only); ffprobe
   format/tags/faststart clean; video frame cadence SOURCE-BOUND B2
   re-read (operator `--source-storage-url-file` presigned original,
   credential-free full GET after derivative GET, hashed == canonical
   source SHA/size; bounded `-count_frames` census on both files; exact
   decoded frame count plus fps/duration tolerance; 60->30 fails; VFR by
   count+duration with per-frame PTS exact NOT claimed; local
   --source-reference alone never proves B2; poster still = video
   cadence N/A). Upload staging rejects oversize DURING the stream
   (claimed size and slot cap enforced per chunk with cleanup, never
   buffered first).
3. Original intact: canonical source revision bytes re-read from B2 AFTER
   publication unchanged (`source_bytes_sha_match` +
   `original_storage_integrity_checked` + `source_integrity_evidence`
   sha/size/method full_get_after_publication + blob row + verified
   replica; local scratch/metadata alone never suffices).
4. Library authorized route: 302 to allowlisted presigned storage with a
   live user session (cookie to the Library origin ONLY, redirects never
   auto-followed); storage `Range` returns 206 with STRICT content-type
   (`video/mp4` hq/light, `image/jpeg` poster -- `text/html` fails);
   expired-grant replay denied (exact object, past
   timestamp, credential-free -- measured, never parameter presence);
   logged-out request denied with 401/403/404 (no auth bypass for probes).
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
   `canary_slot_reservations` ledger (same-key retries charge per PUT
   attempt -- over-counts replays by design; corrupt
   claims fail closed with no new charge). What is NOT built: a B2
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
   task). The collector's credential separation (cookie to the Library
   origin only; credential-free storage fetches; measured expiry denial)
   IS covered by stubbed + two-local-origin tests, but those are fakes,
   not prod evidence. The `prove` gate enforces the evidence shape and DB
   cross-check, but the per-clip device/browser pass stays explicitly
   unproven until a later device pass covers it (checklist item 6).

`Release notes: none — internal, flag-off, no user impact.`
