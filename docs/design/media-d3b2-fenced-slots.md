# D3b2 — fenced web-package slot API + gated Mac producer (DEFAULT DISABLED)

Status: implemented locally, **not pushed, not deployed**. Base `3e5c2a8`
(PR142 merged + server-verified). Flag `MEDIA_WEB_PACKAGES_ENABLED` defaults
`false`; while false every touched flow is byte-identical to production
(same renditions, same priorities, no new jobs, no new reads).

## What this slice builds

Server (fenced, single-step per slot):
- `POST /media/jobs/{job_id}/package/slots` (multipart): streams slot bytes
  to unique per-request staging (D2 rules), validates format on ACTUAL bytes
  (ffprobe video/h264/yuv420p/faststart/dims, JPEG magic for poster, HDR
  reject, SHA/size), checks the small-source `hq_aliased_to` claim against
  server dims (never client-only trust), then publishes through the D3b1
  publisher (B2 upload + full-byte roundtrip verify, **no row lock held
  during the network**) with a fenced `pre_commit_hook` that rechecks the D2
  lease (owner/expiry/token, row-locked) and the source pin (claimed == ctx
  == current canonical) atomically with the ledger + `finalized_slots`
  commit. A mid-upload re-lease (even to the SAME agent) or a source change
  is rejected with 409; verified B2 bytes stay a safe orphan, never promoted.
- `finalized_slots` (NULL = empty): `{"source_sha256", "transform_version",
  "hq_aliased_to", "slots": {...}}`. Retry idempotent per slot (same bytes
  dedupe, different bytes conflict). Job ready ONLY when every applicable
  slot is VERIFIED DURABLE in the ledger (cache-only never counts).
- Lease: `web_package` pinned at lease (canonical B2 source SHA/size,
  `transform_version`, per-slot derivative keys; never `browser_playback`),
  **global ONE active package** across the fleet (advisory-lock atomic, max
  one per lease response). Old workers never see it (capability-gated,
  back-compat defaults).
- Ingestion (`videos.py`): package INSTEAD of poster+720p ONLY when the flag
  is true AND a healthy package-capable worker checked in within 15 min AND
  a verified canonical source exists — otherwise legacy byte-identical
  (decision reported `"package"`/`"legacy"`, never both). Interactive
  priorities unchanged. No reader/status cutover (existing job status shows
  package progress for canary); full play route is D5.

Mac (`mac-agent`, gated by server + capability):
- `package_jobs.process_package_job`: B2 canonical download (SHA-verified)
  preferred; Photos fallback ONLY when its bytes hash to the pinned source
  SHA (exact camera identity). One `build_package` single pass,
  `threads_per_variant=1`, whole-job D2 keepalive + fencing + timeout, owned
  cleanup ONLY (`PackageResult` dir + download temp, never source vault).
  `PackageResult.ready` = LOCAL-VALIDATED, never durable (explicit).
- One package at a time per worker (semaphore); server enforces the fleet
  global. Vault `mark_media_ready` ONLY after server `job_ready`. No auto
  original delete, no venv install. Default capabilities unchanged (old Macs
  claim legacy only).

Tests: `test_web_package_fenced_slots_d3b2.py` (7 SQLite: flag-off legacy
parity, lease pin + global cap, old-worker legacy, 3-slot ready + idempotent
retry, expiry + SAME-agent reclaim reject + fresh-token success,
source-changed stale, small-source alias truth, corrupt/HDR/real-tiny-JPEG
rejects) + `test_package_jobs.py` (4 mocked: single pass/threads/slots,
Photos identity refusal, lease-lost abandonment, no placeholder fail).
Selectable suites: 85 (D2+D3b1+D1+D3b2) + 36 (media guards, 4 PG skips) +
11 (media_node) pass. Mac tests pass with a local `osxphotos` stub (this Mac
lacks the module; CI Linux runs them via its boundary).

## Activation gates (parent decision, in order — do not skip)

1. Review + merge this branch (local commits only; no push/deploy from here).
2. Server deploy: `ci/ship.sh status`, then `server --dry-run`, then
   `server` for the merge SHA. Verify: live SHA, backend image SHA, direct +
   LAN + public health, both nginx reloads, `MEDIA_JOBS_REQUIRE_LEASE_TOKEN`
   still `true`, `MEDIA_WEB_PACKAGES_ENABLED` still `false`.
3. Mac deploy: `ci/ship.sh mac` with a `web_package`-capable config on ONE
   canary worker; verify agent SHA, stable pid, heartbeat shows the
   capability, no pre-D3b2 worker remains for package work.
4. Proofs (all required, nonce first): absent legacy-package interference
   (no `web_package` jobs exist yet); ledger starts empty
   (`SELECT COUNT(*) FROM media_derivatives` baseline recorded); run a
   bounded canary (≤30 clips, ≤2 GiB — NOT authorized in this slice, parent
   runs it): every canary clip reaches job `ready` with 3 (or 2 + alias)
   `ready` ledger rows, source-pinned, ffprobe-clean; B2 roundtrip spot
   checks pass; legacy poster/720p flows untouched.
5. Readers later: NO play-route cutover in this slice (D5). Flip the flag
   ONLY after 1–4: set `MEDIA_WEB_PACKAGES_ENABLED=true` in
   `~/.config/diveanalyzer/media-jobs.env` (mode 600, never Git) and redeploy
   same-SHA with `ci/ship.sh server --ref <sha> --force` (same-SHA skip
   otherwise ignores env changes). Verify the flag in the running env.

## Rollback (exact, in order)

- Flag first (if ever flipped): `media-jobs.env` back to `false` +
  `ci/ship.sh server --ref <sha> --force`. Packages stop queueing/leasing;
  in-flight package leases reclaim normally; ledger `ready` rows are
  append-only history (never deleted), B2 orphans retained by design.
- Code: `ci/ship.sh server --ref <previous-sha>` then `ci/ship.sh mac
  --ref <previous-sha>`. Schema stays (additive D1 columns only; old code
  ignores them). `MEDIA_JOBS_REQUIRE_LEASE_TOKEN=true` is preserved through
  both directions (D2 stays enforced). #134 pins / cleaner retention /
  vault thresholds untouched throughout.
- Never roll back the D1 migration, never delete `ready` ledger rows or B2
  objects to "undo", never clear `deploy.lock` while a ship runs.

## Non-goals / explicit limits

No B2/prod queries in this slice beyond deploy health; no canary bytes
produced here; no backfill; no 360p changes; no transform-version bump
(legacy `ffmpeg-h264-v1` and derivative `ffmpeg-h264-web-v1` preserved).
`Release notes: none — internal, flag-off, no user impact.`
