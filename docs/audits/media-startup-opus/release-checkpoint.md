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

## Conflict and bot finding round — 25 October 2026

Rebased onto `origin/master` `0de520e3` (#160). The sole conflict was the
`member_access_context` docstring; retained master's expanded explanation and
its synchronous dependency, together with all lot changes. Old head `b7c4495`
had eight successful checks, but its bot comment explicitly requested changes
(issuecomment-6397208849); there was no approval. Inline threads and reviews
were empty after paginated inspection. Those old checks authorize no merge.

The finding is valid: detached WebP thumbnail files previously escaped accounting
and cleanup. Cache quota accounting now inventories physical content-addressed
thumbnail files once, including shared references and abandoned generations.
The existing maintenance cleanup can unlink at most 100 generated, unreferenced
WebPs per pass, after a two-hour grace (greater than the maximum signed URL
lifetime). It checks both thumbnail and primary-path references in bounded SQL
batches, skips symlinks, and serializes reference publication/unlink across
processes with a filesystem lock. A delayed publisher verifies the file still
exists before committing its reference; otherwise the static poster survives.
No new schema, original/poster eviction, manual production cleanup, media deletion,
cron or Mac action was introduced. The filesystem inventory is maintenance-only;
it is not called by media/library reads. Referenced thumbnail bytes count toward
the quota even when their protected poster keeps them retained.

Validation after rebase: **82 targeted backend tests pass**, including the real
nginx+njs configurations and eleven lot PostgreSQL integrations, then **64 tests
pass** in the separate complete PostgreSQL CI list (two new cases). New coverage
checks physical-byte accounting, shared references, refresh grace, bounded unlink,
symlink preservation, PostgreSQL reference safety and cleanup racing a delayed
publisher. **777 frontend tests / 94 files and production build pass** again.
Release catalog validation and diff whitespace checks pass. The earlier 1724-test
backend result remains historical, not a full rerun after this correction.
No production writes or cleanup were performed. Rollout ordering above is unchanged.
The disposable PostgreSQL cluster is stopped after validation.


## Hosted PostgreSQL failure and second review round — 25 October 2026

Head `41bc78c9` received an explicit REQUEST_CHANGES at
issuecomment-6397289186, not approval. Paginated reviews, inline comments and
review threads were empty; all issue comments and commit checks/statuses were
inspected. Hosted postgres job `121160386730` failed in the derived slow-HEAD
regression at a SAVEPOINT during authorization, **before the provider HEAD**.
The globally armed 100 ms test timeout mixed runner scheduling during preflight
with the intended network-transaction assertion. The test now arms the **same
100 ms** using SET LOCAL at the verified-storage boundary immediately before the
handler's rollback. HEAD still lasts 350 ms, explicitly asserts that the request
has no transaction, and holds a separate real control transaction which PostgreSQL
must terminate during that wait. No timeout threshold was raised, no assertion,
test, check or gate was disabled, and no retry was used. Gate job `121161930973`
had PLAN=success, CHECKS=success, POSTGRES=failure: its red result is only the
expected propagation of postgres, with no independent aggregator defect.

The high finding is reproduced by the scoped Original HTTP regression before the
fix. Its stale async test double hid a caller passing a synchronous Response to
asyncio.run. The route now calls play_media_revision directly in its worker.
The regression uses a synchronous Response and still tests authorization and
revocation. An AST/source audit of callers of all media/auth handlers converted
since the initial audit found no other incompatible callers; both legacy fallback
calls are already synchronous.

The medium finding is also valid: a proxy refresh, duplicate or failed publication
can leave a generated animated WebP without a ready cache row. Physical animated
files absent from ready-row accounting now count toward the quota in SQL batches
of 100. Existing conservative row accounting for shared ready animations remains.
The reference-aware maintenance cleaner covers both generated namespaces, with
**100 total unlinks per pass**, the existing two-hour URL grace and symlink
protection. Shared animations deferred by ordinary row eviction are unlinked only
by this cleaner after their final reference disappears. The same inter-process
lock covers animated publication and cleanup; delayed publishers check that their
file still exists. No original or protected poster is made eligible for eviction.
SQLite and PostgreSQL regressions cover abandoned refreshes, shared/failed
references, bounded cleanup and a cleanup/publication race. No cleanup, SQL change,
secret provisioning, backfill or other production write was executed in this round.

The hosted artifact also showed the actual animated PostgreSQL roundtrip skipped
because ffmpeg was absent. The postgres job now installs FFmpeg and checks for
libwebp_anim before running the unchanged PostgreSQL list, so that integration
must execute rather than silently skip. Local final verification: **1733 backend
tests passed, 64 optional skips, 28 performance deselections**, with the lots'
PostgreSQL and real nginx+njs integrations enabled; separate complete PostgreSQL
CI list **67 passed, zero skips**, including the final same-100ms slow-HEAD probe
and the three new animated PostgreSQL regressions. CI tooling: **53 passed**.
The disposable local PostgreSQL cluster was stopped cleanly afterward.

Frontend was replayed again: **777 passed / 94 files**, required NODE_OPTIONS,
and production build passed. Release-note validation and diff whitespace checks
passed. A separate local fast-gate wrapper attempt could not start because this
Mac has no flock executable; this is not reported as a passing gate. Its 53 CI
unit tests and release validator were run directly. Hosted CI remains mandatory
on the new head, including the unchanged required gate aggregator.

## Third bot review — bounded library visuals

Verified comment `6397441340`: the library join materialized all historical ready
poster/animation generations for the page. It now groups by asset and rendition
and selects MAX(id) among ready rows in SQL before the ORM join: at most two
visual rows per unique page asset, 200 for a full 100-clip page. Existing access
scope and newest-ready selection are preserved. A regression with 60 ready
historical generations and newer failed rows failed before the fix (60 ORM loads)
and passes after it (exactly the two newest ready rows, same payload).

Validation: 22 focused backend tests pass (lots 2/3 and library payload/bounded
player flow), including real FFmpeg WebP with the same local imageio FFmpeg 7.1
used above. An initial invocation used the Mac's unsupported default FFmpeg;
rerunning with the documented WebP-capable binary passes. Release-note validation
and diff checks pass. Frontend is unchanged. New-head hosted CI and explicit clean
bot verdict are still required; no merge or production change was made.

## Fourth bot review — bounded batch and frontend effect timing

Verified comment `6397502803`: status/batch also materialized historical ready
entries. It now ranks by created_at descending with id as deterministic tie-break,
partitioned by asset/rendition, in SQL before ORM loading. Only poster, animated,
proxy_720p and proxy_360p contribute to tile payloads; originals and other unused
renditions are excluded. At most four rows per asset (400 per 100-asset batch).
The existing ordering by generation creation and proxy preference are preserved.
The HTTP regression seeds 60 historical rows and failed newer generations;
before correction batch loads 60 rows, after correction exactly four, with the
same latest poster/animation and preferred 720p URL. The library counterpart
continues to load exactly two visual rows.

Hosted frontend job `121165162798` failed because ProfileDiveGrid.test invoked
an uninitialized observer callback: the link could be present before the child
passive effect installed its IntersectionObserver. The test resets the callback
per case and explicitly waits for observer installation before firing visibility.
No application behavior, timeout thresholds or CI gates changed.

Validation: 24 focused lots/library tests and 41 media-node/status/cache tests
pass; all 777 frontend tests in 94 files pass with the required NODE_OPTIONS.
Real WebP generation uses the documented local FFmpeg binary. Release-note
validation and diff checks pass. Production unchanged. Hosted CI and explicit
bot approval must run again on the new head before merge/deploy.

## Fifth bot review — full status and video-only consumers

Verified comment `6397569188`: full status serialized every ready generation.
`ready_entries_for_asset` now ranks ready entries by created_at/id descending in
SQL per rendition, selects rank 1, and preserves generation ordering across
renditions. Its only application caller is full status. No history is deleted.
The shared HTTP regression now covers library, batch and full status: full status
reproduced 60 entries before correction and now returns exactly five latest-ready
summaries, retaining local preview and explicit original URLs.

Audited the other cache-entry reads for effects of adding animated generations.
Analysis, representative manifests and legacy playback do not consume animations:
they now exclude that rendition in SQL. Legacy video classification additionally
rejects animated entries, preventing WebP from becoming a video fallback. Recall
planning needs only rendition names and now selects DISTINCT names in SQL rather
than loading entire generation objects. Other reads select a specific rendition,
key or row, or are lifecycle maintenance and intentionally inspect history.
The regression verifies animation-only assets cannot enter legacy video fallback
or the analysis/representative cache maps.

Validation: 98 status/library/playback/cache tests passed; 75 additional
representative/legacy/download/sharing tests passed (3 optional PostgreSQL cases
skipped in that pass); 17 analysis tests passed. These passes overlap and must not
be added. Final lot3 file passed including consumer exclusions. Release-note
validation and diff checks pass. Frontend application/tests unchanged since the
777-test pass in round four. No production changes; fresh hosted checks and an
explicit clean bot verdict remain mandatory.

## Sixth bot review — grace starts after detachment

Verified comment `6397634579`: file mtime predates reference removal and therefore
cannot guarantee signed-capability grace. Cleanup now persists a zero-byte
`.orphan` sidecar on its first observation of an unreferenced generated WebP and
waits two hours from that observation. This is conservatively at or after final
detachment, independent of the file's age. Referenced files reset the observation;
thumb and animation publishers also reset it under the same cross-process lock,
so republish/detach between cleaner passes cannot reuse an old deadline. The
sidecar survives restarts, never changes media bytes and is removed with the
orphan. Symlink markers cannot authorize unlink. Existing reference checks,
100-unlink combined limit and original/poster protections remain.

The previous refresh test manually touched bytes after detachment, masking the
bug; it now leaves the old byte timestamp intact and asserts protection. Added
republication/re-detachment coverage and animation publication marker reset.
Concurrent PostgreSQL cleanup/publication tests model an expired first-orphan
observation explicitly and retain missing-file publication safety coverage.

Validation: 33 tests passed with real local PostgreSQL, including both race
regressions, lots2/3 and enrichment fencing. Final 35-test targeted pass includes
real WebP, republish/reset, reference sharing, bounds, symlinks and media node.
Passes overlap. Release notes and diff checks passed. Disposable PG stopped.
No production action, cleanup or deletion performed. Fresh CI/explicit clean bot
verdict remain required before merge/deployment.
