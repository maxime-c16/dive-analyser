# Automatic packages after the bounded canary

The four accessible canary clips passed independent B2/source/Range/expiry/frame
proofs. The fifth package is durable but its private MAT clip is correctly
unreadable to the operator; Maxime accepted closing at 4/5. Maxime then tested
clip 3017 on Safari/iPhone: complete playback and Light/HQ switching around one
second (user observation, not an instrumented latency guarantee), and authorized
automatic media processing.

Activation covers **new captioned Mac ingests**, not a historical backfill or
browser/evaluation migration. Browser uploads keep their existing behavior.
The original may not yet be in B2 when the initial sync arrives: legacy media
still run, and the verified-original commit event queues the package once a
server-recorded `new_captioned_ingestion` job exists since the activation time.
An old source/migration without that new-ingest event cannot queue packages.
Replays retain any existing package, including terminal failures; no retry
budget is replenished. Original registration and queueing commit atomically.

Packages have priority 60 (interactive requests retain their existing priorities),
max_attempts 2, and the existing global one-package fleet limit. Before leasing:
server cache must have >=25 GiB; two consecutive terminal package failures pause
further package leases. The Mac requests the package capability only with >=8 GiB
free on its scratch filesystem and `vm.memory_pressure == 0`; unknown facts pause
packages. These checks do not kill in-flight work or modify legacy vault limits,
retention, cleanup, pins, auth or source identity. The Mac probe runs off-loop and
has a 2-second timeout. Legacy capabilities remain available during a pause.

A disk pause resumes automatically when space returns. After two failures,
investigate before explicitly retrying a failed job; no blind retry/reset loop.
No new storage budget is advertised: the 2 GiB bounded-canary ledger remains
canary-only; ongoing new ingestion is not a historical bulk conversion.
SAR/display-dimension provenance remains a fail-closed availability limitation.

## Deployment and activation

1. Require CI + APPROVE on the exact head, guarded merge. Use the CURRENT merged
   `ci/ship.sh` from a development checkout on the server (never old parent
   9322dc0). Read `docs/REPO_WORKFLOW.md`; do server and Mac dry-runs first.
2. Deploy server with auto-ingestion still false, then deploy Mac; verify new
   SHA, stable worker PID, one capable healthy worker and no old duplicate.
   There is no SQL migration. Compose adds one environment value: ship reloads
   both proxies; verify reloads and health per repository workflow.
3. In the existing 0600 managed `~/.config/diveanalyzer/media-jobs.env`, preserve
   `MEDIA_JOBS_REQUIRE_LEASE_TOKEN=true`, `MEDIA_WEB_PACKAGES_ENABLED=true`;
   set `MEDIA_WEB_PACKAGES_AUTO_INGEST_SINCE` to the activation instant in UTC
   ISO8601 with timezone, and `MEDIA_WEB_PACKAGES_AUTO_INGEST_ENABLED=true`.
   `NEW_VIDEO_AUTO_MEDIA_ENABLED` must already be true for new-ingest media
   events (verify, don't silently alter unrelated policy).
4. Same-SHA server `--dry-run --force`, then normal `--force`, from the current
   server development checkout so managed env is sourced. Verify effective
   flags/cutoff, actual scratch/cache free bytes and pressure, health, fleet
   capability and zero historical jobs created by activation alone.
5. Observe the next genuine new-ingest event and its source commit. Do not
   manufacture a job/clip to claim production proof. Until such an event occurs,
   distinguish "automatic processing enabled" from "first automatic job proven".
   Keep existing canary evidence; device results are user-reported only.

Rollback: set ONLY auto-ingestion false in the same managed file and redeploy
same SHA with dry-run/force. Drain existing packages; no source/cache/derivative
purge. Keep REQUIRE true. Master flag may remain true for explicit jobs.

Release notes: none — activation plumbing; the feature also requires the Mac
upgrade and managed activation, and must not be announced prematurely by the
server-only release catalog.
