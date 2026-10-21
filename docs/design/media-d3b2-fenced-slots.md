# D3b2 — fenced web-package slot API + gated Mac producer (DEFAULT DISABLED)

Status: implemented locally, **not pushed, not deployed, NO production yet**.
Base `3e5c2a8` (PR142 merged + server-verified). TWO flags, both default
`false` (see "Activation" — the old single-flag step order was circular and
is replaced below):
- `MEDIA_WEB_PACKAGES_ENABLED` (master lease flag): while false, every
  touched flow is byte-identical to production (same renditions, same
  priorities, no new jobs, no new reads, leases strip `web_package`).
- `MEDIA_WEB_PACKAGES_AUTO_INGEST_ENABLED` (broad automatic ingestion,
  NEW): while false, newly ingested clips ALWAYS queue legacy poster +
  720p — even with the master flag on and a capable worker — so a bounded
  explicit canary can never trigger library-wide package queueing.
Activation is a parent decision with a healthy capable worker (see below);
never flip in code, never in this slice.

## What this slice builds (verified fixes)

Server (fenced, single-step per slot):
- `POST /media/jobs/{job_id}/package/slots` (multipart, `transform_version`
  Form echoes the lease pin): streams slot bytes to unique per-request staging
  (D2 rules, owned cleanup on every fail/cancel/hash/DB/provider path, only
  the unique staging unlinked, never the live pointer), validates format on
  ACTUAL bytes (ffprobe video/H.264 High/yuv420p/BT.709 all three
  tags/MP4-container/faststart-True/bounded-decode with `-xerror` so
  truncated packets fail, JPEG magic + mjpeg codec
  for poster, HDR reject, missing-tag reject, SHA/size, even dims, caps),
  checks the small-source `hq_aliased_to` claim against server truth (the
  LEASE-PINNED canonical dims — `MediaBlob` width/height read at lease, live
  blob read only as fallback for pre-dims pins — never PhotosAsset
  SAR/rotation, never worker-claim fallback; unknown dims refuse the alias
  fail-closed; exact expected dims via the encoder short-side rule for
  hq/light/poster — poster rides the encoder's light-scale branch so poster
  expected == light expected, no up/down beyond cap), then publishes
  through the D3b1 publisher (B2 upload + full-byte roundtrip verify, **no row
  lock held during the network**) with a fenced `pre_commit_hook` that runs
  on EVERY ready path (normal + idempotent replay + IntegrityError rival —
  no path returns ready without the D2 current-claim + source authoritative
  check, lock ordering ledger -> job consistently) and rechecks the D2 lease
  (owner/expiry/token, row-locked through commit) and the lease pin
  (claimed == pin == ctx for source AND revision AND transform on EVERY slot,
  explicit transform echo required with no ctx fallback, token bound
  to the same attempt; a missing pin REJECTS fail-closed — no web_package
  job predates pinning so there is no legacy unpinned shape to honor and no
  claim-bound retagging; source change between lease and first slot REJECTS,
  not retags; the alias is decided by the first slot — lease None means "not
  yet decided" — and cannot flip afterwards, including NONE -> light after an
  hq slot finalized) atomically with the ledger +
  `finalized_slots` commit. A mid-upload re-lease (even to the SAME agent)
  or a source change is rejected with 409 (never 500); verified B2 bytes stay
  a safe orphan, never promoted. Error taxonomy is explicit: 400 client
  format/validation, 409 client-stale (lease/source/identity), 502 B2
  provider roundtrip (sanitized), 503 storage unconfigured, 500 retryable
  internal (dirty session, invariant breach, unexpected — sanitized detail,
  chained server-side, never raw tracebacks/paths/secrets).
- `finalized_slots` (NULL = empty): `{"source_sha256", "source_revision_id",
  "source_width", "source_height", "transform_version", "hq_aliased_to",
  "slots": {...}}`, persisted at lease (ONE canonical camera source resolved
  ONCE under the advisory lock for URL/SHA/size/keys — never `browser_playback`,
  missing source skips the lease fail-closed with no attempt burned; durable
  partial slots reused only when pin + transform unchanged, otherwise reset).
  Retry idempotent per slot (same bytes dedupe, different bytes conflict).
  Job ready ONLY when every applicable slot is VERIFIED DURABLE in the ledger
  (PROD replica required — DEV never counts; current slot proven by this TX's
  roundtrip + PROD env, priors re-read from the ledger; stale/removed/SHA
  mismatch never counts; cache-only never counts).
- Lease: `web_package` pinned at lease (canonical B2 source SHA/size +
  revision + canonical dims, `transform_version`, per-slot derivative keys;
  never `browser_playback`), **global ONE active package** across the fleet
  (advisory-lock atomic, max one per lease response, concurrent agents
  serialize). Old workers never see it (capability-gated, back-compat
  defaults; master flag OFF strips `web_package` even when manually queued).
- Ingestion (`videos.py`): package INSTEAD of poster+720p ONLY when the
  master flag is true AND `MEDIA_WEB_PACKAGES_AUTO_INGEST_ENABLED` is true
  AND a healthy package-capable worker checked in within 15 min AND
  a verified canonical source exists — otherwise legacy byte-identical
  (decision reported `"package"`/`"legacy"`, never both). Master-on +
  auto-ingest-off admits ONLY explicitly queued canary jobs through leases;
  broad ingestion can never start by accident. Interactive
  priorities unchanged. No reader/status cutover (existing job status shows
  package progress for canary); full play route is D5.

Mac (`mac-agent`, gated by server + capability):
- `package_jobs.process_package_job`: B2 canonical download (SHA-verified)
  preferred; Photos fallback ONLY when its bytes hash to the pinned source
  SHA (exact camera identity). One `build_package` single pass,
  `threads_per_variant=1`, whole-job D2 keepalive + fencing + timeout, owned
  cleanup ONLY (`PackageResult` dir + download temp, never source vault).
  `PackageResult.ready` = LOCAL-VALIDATED, never durable (explicit). Slot
  publishes echo the lease `transform_version` (server enforces pin == ctx ==
  request on every slot).
- One package at a time per worker (semaphore); server enforces the fleet
  global. Vault `mark_media_ready("web_package")` sets BOTH poster + proxy
  sides ONLY after server `job_ready` (every applicable slot VERIFIED DURABLE,
  PROD replica, source SHA verified). No auto original delete, no venv
  install. Default capabilities unchanged (`["poster", "proxy_720p"]`; old
  Macs claim legacy only — a `web_package`-capable config is an explicit
  managed activation, see runbook below; server heartbeat must show the
  capability or no package ever leases/strands).

Tests: `test_web_package_fenced_slots_d3b2.py` (SQLite: flag-off legacy
parity, lease pin persisted incl. revision + canonical dims + global cap +
no-source skip, old-worker legacy, 3-slot ready + idempotent retry, expiry +
SAME-agent reclaim reject + fresh-token success, source-changed stale +
missing-pin fail-closed (no legacy binding) + missing-transform-echo reject +
NONE->light-after-hq alias-flip reject + exact hq/light/poster dims when
canonical dims known (poster expected == light expected) + alias truth
(server dims, unknown fail-closed) + corrupt/HDR/missing-BT709/bad
profile/faststart-None/malformed-JPEG rejects with real tiny JPEG + route
error taxonomy 409/502/503/500 + auto-ingest-off legacy / auto-ingest-on
package + compose/config flag defaults) +
`test_web_package_real_mp4_d3b2.py` (REAL ffprobe + ffmpeg, no fakes:
synthetic 2 s portrait 720x1280@60 produces BT.709/High/yuv420p/faststart
bytes that validate as hq AND light, real JPEG poster validates, and
75%-truncated bytes with matching SHA/size are REJECTED by the strict
`-xerror` decode probe — plus real missing-tags / no-faststart / non-MP4 /
baseline-profile rejects; skips ONLY when ffmpeg/ffprobe are absent, never
on Linux/CI; frame counts are NOT server-proven — see Non-goals) +
`test_postgres_web_package_fenced_slots_d3b2.py` (PG, disposable
`calendar_test_*` only, wired in `ci/postgres.sh`: B2-gate barrier stale
mid-network reject, concurrent 2 slots no lost JSON update + ready, global
cap serialized, source-changed first slot reject-not-retag — fake B2 barrier,
real PG TX, lease + publish paths, not guard alone) +
`test_package_jobs.py` (4 mocked: single pass/threads/slots + transform pin
echo, Photos identity refusal, lease-lost abandonment, no placeholder fail;
vault `web_package` sets both sides only after `job_ready`).
Selectable suites: D2+D3b1+D3b2 SQLite + PG tier pass (see evidence below).
Mac tests pass with a local `osxphotos` stub (this Mac lacks the module; CI
Linux runs them via its boundary).

## Activation gates (parent decision, in order — do not skip; NO production yet)

Two flags, two jobs (this replaces the old circular order where the canary
required the flag the canary was supposed to justify):
- `MEDIA_WEB_PACKAGES_ENABLED=true` admits package LEASES (bounded canary
  only) but, with auto-ingest still false, queues NOTHING new — broad
  ingestion stays legacy, so the master flag can be on without any
  library-wide effect.
- `MEDIA_WEB_PACKAGES_AUTO_INGEST_ENABLED=true` (only after canary proof)
  lets new ingests queue packages broadly.

1. Review + merge this branch (local commits only; no push/deploy from here).
2. Server deploy: `ci/ship.sh status`, then `server --dry-run`, then
   `server` for the merge SHA. Verify: live SHA, backend image SHA, direct +
   LAN + public health, both nginx reloads, `MEDIA_JOBS_REQUIRE_LEASE_TOKEN`
   still `true`, `MEDIA_WEB_PACKAGES_ENABLED` still `false`,
   `MEDIA_WEB_PACKAGES_AUTO_INGEST_ENABLED` still `false` (runtime
   `~/.config/diveanalyzer/media-jobs.env`, mode 600, never Git; compose
   defaults `false`).
   Because Compose changes, follow `docs/REPO_WORKFLOW.md` after shipping:
   `docker-compose up -d nginx` in the server stack (or the documented
   reload alternative). Ship already reloads both LAN and Funnel proxies;
   verify both reloads and health checks in its log. Recreate a proxy only
   when needed to apply changed mounts/configuration.
3. Mac deploy (managed safe path, ONE canary only): `ci/ship.sh mac` with an
   explicit `web_package`-capable config on ONE canary worker
   (`media.capabilities` adds `web_package`; default stays
   `["poster", "proxy_720p"]` so old Macs claim legacy only — enrollment is
   this explicit managed-state config on both sides, never a "default
   changed" side effect). Verify agent SHA, stable pid, heartbeat shows the
   capability AND `backend.auth server agent.allowed` capability enrollment
   shows `web_package`, or no package ever leases — silent stranded jobs are
   a misconfiguration, never retried as legacy. No pre-D3b2 worker remains
   for package work. NO canary bytes before the D5 read path is ready and the
   overnight checkpoint on prior caps has passed (parent confirms).
4. Bounded canary admission (NOT authorized in this slice, parent runs it
   through a reviewed tool under user auth): with auto-ingest still OFF, set
   ONLY `MEDIA_WEB_PACKAGES_ENABLED=true` in `media-jobs.env` and redeploy
   same-SHA with `ci/ship.sh server --ref <sha> --force`; queue an explicit
   allowlisted canary (≤5 clips first, ≤25 next — small sources with KNOWN
   canonical `MediaBlob` dims preferred, since unknown dims refuse the alias
   and leave no-upscale server-unproven) via the reviewed admin tool — never
   by flipping auto-ingest. Proofs (all required, nonce first): absent
   legacy-package interference (no `web_package` jobs exist yet); ledger
   starts empty (`SELECT COUNT(*) FROM media_derivatives` baseline recorded);
   every canary clip reaches job `ready` with 3 (or 2 + alias) `ready`
   ledger rows + PROD replicas, source-pinned, ffprobe-clean
   (BT.709/High/faststart/decode); B2 roundtrip spot checks pass; legacy
   poster/720p flows untouched; no non-allowlisted package job was queued
   (leases + queue audit).
5. Broad ingestion later: NO play-route cutover in this slice (D5). Flip
   auto-ingest ONLY after 1–4: set
   `MEDIA_WEB_PACKAGES_AUTO_INGEST_ENABLED=true` in
   `~/.config/diveanalyzer/media-jobs.env` (mode 600, never Git) and redeploy
   same-SHA with `ci/ship.sh server --ref <sha> --force` (same-SHA skip
   otherwise ignores env changes). Verify both flags in the running env.

## Rollback (exact, in order)

- Block new queueing first (if either flag ever flipped): `media-jobs.env`
  both flags back to `false` + `ci/ship.sh server --ref <sha> --force`.
  Packages stop queueing AND leasing; in-flight package leases are NOT
  killed — they reclaim normally on expiry (the worker's keepalive fails
  fenced, the job returns to `queued`, legacy flows are unaffected).
- Drain before downgrade: wait until NO `web_package` job remains in a
  leased status (`claimed/materializing/exporting/transcoding/uploading/
  verifying`); confirm read-only proof (ledger `ready` rows are append-only
  history, B2 orphans retained by design — nothing is deleted to "undo").
  Only then downgrade, SERVER first then Mac: `ci/ship.sh server --ref
  <previous-sha>` then `ci/ship.sh mac --ref <previous-sha>`. Order
  matters: a downgraded server no longer serves the slot routes, so an
  in-flight new-code worker upload would 404 — safe (fenced retry, job
  reclaims, nothing promoted without a server commit), but draining avoids
  the churn entirely. The Mac rollback also restores the default
  `["poster", "proxy_720p"]` capabilities (explicit managed config again —
  the capability disappears because the config says so, not by magic).
- Schema stays (additive D1 columns only; old code ignores them).
  `MEDIA_JOBS_REQUIRE_LEASE_TOKEN=true` is preserved through both directions
  (D2 stays enforced). #134 pins / cleaner retention / vault thresholds
  untouched throughout.
- Never roll back the D1 migration, never delete `ready` ledger rows or B2
  objects to "undo", never clear `deploy.lock` while a ship runs.

## Non-goals / explicit limits

No B2/prod queries in this slice beyond deploy health; no canary bytes
produced here; no backfill; no 360p changes; no transform-version bump
(legacy `ffmpeg-h264-v1` and derivative `ffmpeg-h264-web-v1` preserved).
Ready-claim retention (deliberate, not a leak): the fenced guard sets a
package job `ready` WITHOUT clearing its claim (owner/token/expiry stay
until they age out). A same-token same-bytes retry inside the window
dedupes; after expiry the retry fails fenced (`lease_expired`, 409) — which
is correct, because there is nothing left to do (all slots are durable) and
a next lease can never "complete" an already-complete job. The uploader's
normal response to a 409-after-ready is to stop, not to requeue.
No-upscale proof limit: with unknown canonical dims the server admits
non-alias slots on caps/format alone and CANNOT prove no-upscale — that
residual is enforced upstream by the reviewed worker encoder on the
SHA-pinned source, and the canary prefers dims-known sources. Frame counts
are likewise encoder-proven, never server-proven: the server MUST NOT trust
(or claim to verify) client frame claims.
`Release notes: none — internal, flag-off, no user impact.`
