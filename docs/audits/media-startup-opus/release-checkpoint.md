# Combined release checkpoint — 25 October 2026

Scope: original audit and lots 1–3 in one ready PR to master. Server rollout,
manual additive migration, both nginx front doors, bounded backfills and production
measurements are authorized. No Mac rollout, lot 4, destructive cleanup or database
tuning is included. Waiting for CI/review is a parent handoff, not completion.

## Preparation

Rebased without conflicts on `origin/master` `2eae2137` (#159). All three immutable
release notes validate and require backend + frontend. Existing published notes
are unchanged. The full frontend suite passes: 777 tests / 94 files, with
`NODE_OPTIONS=--no-experimental-webstorage npx vitest run`; production build passes.
Final backend CI-style run: **1724 passed, 64 skipped, 28 performance deselected**
with `--asyncio-mode=auto --strict-markers` and unhandled coroutines treated as
errors. The nine new lot PostgreSQL integrations and two nginx+njs integrations
were enabled. Optional pre-existing PostgreSQL cases run separately in their CI
list. CI unit tests: 53 passed. The local FFmpeg 7.1 imageio binary includes both
WebP and zscale; the browser-upload HDR PQ/HLG cases passed in this preparation,
resolving the older local capability limit without application changes. Local nginx 1.29.4 + njs 0.9.4 integrations cover real
HTTP, Range, 304, tampering, expiration, symlinks and both effective configurations.
The updated `ci/check-proxies.sh` also passed on the server in two isolated,
network-disabled disposable containers using nginx:1.29.4-alpine and the actual
entrypoint/template/module mounts. No production service was recreated for this.

Two obsolete audit assertions expected an original to start before a local proxy.
They now assert local startup while retaining explicit original quality. The full
suite also exposed an automatic-evaluation caller left on the old `serve_entry`
signature; it now passes the cache entry, fixing its playback 500. All 67 audit +
automatic-evaluation tests pass after correction. The
browser probe no longer aborts status requests by default; `PROBE_ABORT_STATUS=1`
is reserved for reproducing the historical workaround. New PostgreSQL regression
files are included in `ci/postgres.sh`, rather than silently skipped in hosted CI.

## Read-only production preflight

At 11:29–11:32 UTC: clean detached live checkout/backend at `2eae2137`, frontend
at `4a13964`; no application deployment or production write performed. Rollback
must record these service images and refresh them immediately before rollout,
since another authorized deployment may advance them. The current four poster
visual columns are absent. FFmpeg advertises `libwebp_anim` and `libwebp`.
Both currently running nginx configurations pass `nginx -t`.

Available disk: 314 GiB (rounded `df -BG`). Baseline `/proc/pressure/io`:
some avg10/60/300 = 13.99/18.36/17.39%, full = 4.97/10.59/10.15%.
This is existing pressure, not a measured regression. Recheck before each tiny
backfill batch; stop for sustained pressure instead of competing with migration.
The 26 GiB disk floor remains mandatory. No migration process was paused.

## Mandatory rollout ordering

1. After approval/merge, refresh master, record merge SHA, current source/image
   SHAs, proxy mounts/config and PostgreSQL kill-log interval. Run
   `ci/ship.sh status` and `ci/ship.sh server --ref <merge-sha> --dry-run`.
   Inspect CD/cron and deploy locks before any writes; do not race auto-deploy.
2. Apply `backend/migrations/add_poster_visuals.sql` explicitly before the new
   backend; check all four nullable columns. No other migration is introduced.
3. Generate the signing secret directly on the server into the existing private
   `~/.config/diveanalyzer/browser-upload.env` (0600), preserving its existing
   settings. Never echo it. Start with `MEDIA_SIGNED_URLS_ENABLED=false`.
4. **First-deploy mount transition needs preparation before ship.** Current LAN
   mounts all of conf.d read-only and has no njs/template mounts. Funnel also
   lacks them. `ci/deploy.sh` calls `nginx -t` and reload immediately after its
   backend/frontend swap. Checking out the new main nginx config without new
   mounts can therefore fail that reload and roll back the deployment.
   Stage merged nginx files outside the live checkout, with disposable-container
   syntax checks first. Recreate the two existing proxy services against those
   staged files, same projects/ports/network, existing media cache and TLS paths,
   and the shared private secret. Keep backend/frontend unchanged during this
   manual proxy step. Use explicit absolute bind paths; do not let a staging
   Compose project create a different cache or database. Record old config for
   rollback. Test/reload both front doors and existing anonymous/login paths.
   No manual edit or checkout of the live directory is needed.
5. Run `ci/ship.sh server --ref <merge-sha>` normally for backend + frontend.
   Once healthy, recreate LAN nginx and the separate `dive-funnel` project from
   the now-deployed versioned Compose files, sourcing the same private env for
   **each** invocation. Test and reload both. Do not use `nginx -T` (secret).
6. Verify signed static URLs privately on both doors, including 200/206/304 and
   altered/expired 403. Only then enable signed URL emission and redeploy the
   backend through ship (`--force` if same SHA; dry-run first). Confirm rt= logs,
   API Server-Timing, admin xray, private cache policy and no new 5xx.
7. Run poster/ThumbHash batches first (start limit 2–4, after-id 0), then animated
   batches (start limit 1–2). Persist cursors/scanned/generated/failed counts and
   I/O/disk/loop-lag readings per batch. No GET generation, cron, original fetch,
   Mac changes or data deletion. Stop on durable I/O pressure; preserve state.
8. Use the private e2e account file without printing credentials, run browser
   probe **without** `PROBE_ABORT_STATUS`, then play_probe.py/play_compare.py from
   a private scratch directory with private cookie/header and library files.
   Do not log signed URLs. Logout even on failure. Count PostgreSQL idle-in-tx
   kills during/after. Compare first poster 1677 ms, handler p50 1.08 s, freeze
   32 s, D5 first MiB 1.90 s; distinguish first MiB from first decoded frame.

## Rollback and final evidence

On new 5xx, freeze or broken posters, disable signing emission, restore previous
proxy config/mounts and deploy the recorded previous SHA with ship (dry-run first).
Retain additive schema, all media and generated artifacts. Record actual running
service SHAs after rollback. Never override merge protection or deploy unmerged.

After verification, write `deploy-result.md` with exact SHAs, manual actions,
measurements/limits, kill counts and backfill state in an authorized small follow-up
PR or comment; register any follow-up PR. Final result is at most five lines.

## Broader-test limits investigated

An exploratory full run with every optional PostgreSQL test enabled gave 1768
passes, 13 skips, 31 performance deselections and four failures. One was the
automatic-evaluation regression fixed above. The other three were reproduced
unchanged from an `origin/master` archive: calendar's SQLite-specific positional
parameter assertion when forcing its entire suite onto PostgreSQL, the optional
canary missing-ledger case, and a publisher lock test killed by the cluster-wide
5 s timeout used by the startup probe. The last timeout is removed for the
separate CI PostgreSQL list via PGOPTIONS; startup tests retain their own 5 s
connection timeout. No unrelated production or calendar/canary code was changed.

Final separate PostgreSQL CI list: **62 passed in 16.15 s**, including all nine
new lot integrations, existing D5 contracts, publisher locks and slow HEAD.

A 100 ms idle-timeout playback test flaked once in auth while the exploratory
backend and PostgreSQL passes shared the CPU; both cases pass in 1.69 s when
replayed alone. This is reported separately from the intentional slow-provider
HEAD test, not hidden as a successful initial tier run.
