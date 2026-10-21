# Bounded web_package canary — admission/verification ops runbook

Status: tool + guard implemented locally, **not pushed, not deployed, NO
canary bytes produced here**. All production steps below are PARENT-run,
in order, after review + CI + merge. This slice performs NO prod query,
B2 write, job queue/config change, or deploy (local commit only).

Tool: `ops/canary_web_package.py` (DRY-RUN default; `--apply` admits at
most ONE job per run). Budget guard: `backend/app/services/canary_budget.py`
+ publish-time enforcement in `POST /jobs/{job_id}/package/slots`.
Tests: `backend/tests/test_canary_budget_d3b2.py` (SQLite, fake B2 only).

Bounds (hard, shared by tool + guard + tests):

- Phase 1: <= 5 clips. Only on 100% proof (5/5 ready + proofs below) may
  phase 2 admit <= 25 additional (fleet total <= 30).
- New B2 derivatives HARD cumulative <= 2 GiB (committed ledger bytes +
  the in-flight slot). The tool's worst-case estimate is PREFLIGHT ONLY;
  the slot route refuses overshoot authoritatively with 409 BEFORE bytes
  stream (`check_publish_budget` on the claimed `size_bytes`).
- ONE package active fleet-wide (lease cap + tool serial gate: the tool
  never queues while ANY package job is active, and queues at most one
  per run — never 30 at once despite the global lease allowing 1).
- Canary jobs queue at priority 60 (backfill level): interactive
  user_view/automatic_review/evaluation_request (5/6) and ingestion (10)
  always win the lease ordering, so the watch lease never starves.
- Admission is idempotent/resumable: ready clips skipped, active jobs
  never duplicated, `--state-dir` (private, outside git) resumes.
- Stop new admissions when: Mac Data free < 8 GiB, server cache volume
  free < 25 GiB (operator-provided `--mac-free-bytes` /
  `--server-cache-free-bytes`; the tool never probes hosts), memory
  pressure, consecutive failures >= 2, or source unknown
  (no canonical revision / dims / size / duration — fail closed).
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
2. `ci/ship.sh status` → `ci/ship.sh server --dry-run` → `ci/ship.sh server`
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

# 2. Read-only readiness (bounded queries, aggregate output, no secrets):
DATABASE_URL='<runtime>' python3 ops/canary_web_package.py \
  --manifest ~/.config/diveanalyzer/canary-manifest.json \
  --state-dir ~/.config/diveanalyzer/canary inventory

# 3. Admit EXACTLY ONE (dry-run first, then explicit apply with host facts):
DATABASE_URL='<runtime>' python3 ops/canary_web_package.py \
  --manifest ~/.config/diveanalyzer/canary-manifest.json \
  --state-dir ~/.config/diveanalyzer/canary \
  admit --phase 1 --mac-free-bytes <BYTES> --server-cache-free-bytes <BYTES>
DATABASE_URL='<runtime>' python3 ops/canary_web_package.py \
  --manifest ~/.config/diveanalyzer/canary-manifest.json \
  --state-dir ~/.config/diveanalyzer/canary \
  admit --phase 1 --apply --mac-free-bytes <BYTES> --server-cache-free-bytes <BYTES>
# Re-run admit (plan or apply) ONLY after the queued job reaches a
# terminal state AND `verify` proves it: serial, one at a time.
```

`DATABASE_URL` comes from the existing runtime config (same value the
server uses); it is passed through the environment, never printed,
logged, or stored by the tool.

## Gate 4 — verification proofs (parent, per clip, before next admission)

```bash
DATABASE_URL='<runtime>' python3 ops/canary_web_package.py \
  --manifest ~/.config/diveanalyzer/canary-manifest.json \
  --state-dir ~/.config/diveanalyzer/canary verify
```

Required per clip (all must hold before the NEXT admission; phase 2
only after 5/5):

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

1. **Orphans invisible to the budget.** Retained B2 orphans (crashed
   attempts, SAR!=1 refusals) have no ledger row. Bound: committed +
   one in-flight slot (hard); orphan waste bounded procedurally
   (serial, max_attempts=2, stop-on-error). A future orphan-accounting
   pass (B2 prefix listing vs ledger) would close this; not in this slice.
2. **No display-dims/SAR provenance server-side.** `MediaBlob` holds
   coded dims only; SAR!=1 honest output fails closed at publish (safe)
   but spends uplink. Mitigation: dims-known + phone-camera preference;
   the narrow fix (nullable `display_width/height` at ingest) is
   documented in `web_packages.check_small_source_alias`, not built here.
3. **Host disk facts are operator-provided.** The tool enforces the
   8 GiB / 25 GiB stops but never probes hosts itself; automated host
   telemetry is a later slice.
4. **Evaluation consumers untouched.** Library playback (D5) is the only
   reader in this slice; evaluation-grid consumers stay on legacy
   previews until the canary is proven (parent decision, later night).

`Release notes: none — internal, flag-off, no user impact.`
