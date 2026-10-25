# Media startup lots 1–3 — production rollout

**Final backfill status: complete. 0 incomplete posters, 2829 ready animations.**


25 October 2026. Main PR: https://github.com/maxime-c16/dive-analyser/pull/161.
Merged commit: `0973fa5f364e94412c6e6748c68743936ca68086`.

## Release evidence

The bot explicitly approved the final PR head `c5b35cb0`; all eight hosted checks,
including the required gate, succeeded. Squash merge was guarded by that head.
Master had advanced independently, so ship's exact-tree proof did not match and
the normal server gate ran again. No gate bypass or administrator merge override.

Another authorized server deployment held the shared lock; this rollout waited
for it to finish. The immediate previous source/backend/frontend was `0a6b94f`.
Private rollback evidence records exact image IDs and effective proxy mounts;
none of that evidence contains committed credentials.

## Manual prerequisites

- Applied additive `backend/migrations/add_poster_visuals.sql` before new backend;
  verified all four nullable columns and their types. No other lot migration.
- Generated the 64-character hexadecimal signing secret directly on the server,
  preserving the existing private environment file, mode 0600. Never printed or
  committed it. Initial emission disabled.
- Backed up effective proxy configurations/mounts outside the live checkout.
  Staged merged nginx files there and tested both with disposable containers.
  Recreated LAN and Funnel against staged files before ship because the old
  mounts could not load njs after the new config checkout. Same projects, ports,
  network, persistent cache and TLS paths; backend/frontend remained unchanged.
- Both new proxy syntax tests passed. LAN health 200; Funnel login 200 (its
  unauthenticated API guard returns 401).
- Before emission, both doors passed signed HEAD200, Range206, conditional304,
  altered-signature403 and correctly signed expired403. Private immutable cache
  max-age was bounded by capability expiry (297 seconds in this probe).

## Application deployment and measurements

Both backend and frontend run `0973fa5` (`0973fa5f364e94412c6e6748c68743936ca68086`),
version **v1.14.0**. The initial server ship succeeded with its normal gate:
784 frontend tests plus production build passed on the merged tree. After ship,
both proxies were recreated from the deployed Compose files and explicitly tested
and reloaded. Signature checks passed again. A same-SHA backend-only forced ship,
preceded by its dry-run and normal fast gate, activated signed emission. Both ship
commands exited successfully; the second backend started at **13:34:22 UTC**.
Backend health is healthy; all four service containers are running. The shared
secret matches backend and both nginx environments; emission is true.

The private e2e account was used for the required production probes, without
printing credentials or capabilities. Both measurement sessions logged out with
HTTP 200, including the additional fixed-size comparison. Xray overlay was visible
for this admin; `/auth/xray` returned 200. `/auth/me` carried
`Server-Timing: auth;dur=50.70, db;dur=50.91, app;dur=81.21`. Both nginx logs contain
`rt=`. All three release-note IDs are present in the authenticated catalog.

| Measure | Audit reference | After rollout |
|---|---:|---:|
| First poster | 1677 ms | cold: 3425 / 3383 / 2779 ms, median **3383 ms**; warm: 692 / 512 / 774 ms, median **692 ms** |
| Poster latency | handler p50 1080 ms | authenticated legacy poster HTTP p50 **193 ms**, signed poster HTTP p50 **60 ms**, 15 samples each |
| Event-loop freeze | 32 s | no such event observed; xray lifetime max **218.71 ms**, last-window p99 **13.01 ms** |
| First MiB | D5 1.90 s | five matched, exactly-1-MiB Range responses: local median **0.482 s**, D5 grant+B2 median **1.133 s**, all 206 |
| PostgreSQL idle-in-transaction kills | 2 in preceding 30 min | **0 in the initial post-rollout observation**; **4 later kills** at 14:02–14:54 UTC; **0 in the final 30-minute window** (details below) |

The browser script ran its six desktop/phone cold/warm phases with **zero aborted
status calls**. `play_probe.py` and `play_compare.py` ran unchanged. The latter
included three local files smaller than one MiB, so its raw 0.443 s local median
is not presented as a first-MiB result. A bounded additional paired probe selected
five proxies at least one MiB and verified 1,048,576 bytes on both sides. All raw
numeric evidence is in [deploy-measurements.json](deploy-measurements.json).
These are byte-transfer times, not first decoded frame measurements.

**Limits and adverse observations.** Cold first-poster display is slower than the
audit reference; no cold-start improvement is claimed. The required current probe
leaves status calls enabled, whereas the initial audit used a status-blocking
workaround, and production I/O pressure remained high. Thus this is not a matched
causal before/after benchmark. HTTP poster timings also include transport and do
not directly reproduce the audit's handler span; no current poster app-span p50
was obtained through X-Accel. Warm display, API timing and transfer measurements
are reported separately rather than hiding the cold result.

There was **one transient LAN 502** on `/media/jobs/lease` at 13:34:23 UTC, one second
after the backend restart and before readiness. Subsequent steady operation has
**zero 5xx on either door** (window begins 30 seconds after restart), no idle-tx kill,
no observed long freeze and no broken poster in the probes. No sustained runtime
regression requiring rollback was observed; no rollback was performed.

## Initial backfill deferral and resource guardrails

Backfills were deferred before any batch because sustained server I/O pressure
was already high, including full avg60 around 37–47% and some avg60 around 58–73%
during the deployment gates. Available space remained about 313–314 GiB, well above
the 26 GiB floor. Final post-build pressure was still some avg60 **33.95%**, full avg60 **22.93%**. No migration process was paused. No explicit backfill ran:
poster/ThumbHash cursor 0; animation cursor 0. A final read counted 2343 ready
posters, 2335 lacking complete visuals, and 0 ready animations. At that initial checkpoint, production animation appearance had not yet been
exercised. The completed production verification is recorded below. The initial resume plan was poster batches at limit2–4, then animations at
limit1–2 with resource checks; the explicit follow-up request below activated it. Record each
cursor, count, free-space reading and event-loop lag. Existing normal producers
may enrich newly finalized posters independently; this is not a completed corpus
backfill. No originals, media or database data were manually deleted.

## Rollback

If fresh 5xx, freezing or broken posters appear, disable capability emission,
restore the privately recorded old proxy image/config/mounts, and use
`ci/ship.sh server --ref 0a6b94f06cb99be9fa29ec26c95c329f15d011ce` (dry-run first).
Keep additive columns and generated files. Reconfirm running service SHAs and
both doors after rollback. No Mac rollout, lot4 or database tuning performed.

## Backfill started on explicit follow-up request

At Maxime's subsequent request (“fait le backfill la”), the backfill started on
25 October around14:05 UTC despite the existing I/O load, with idle I/O priority
(`ionice -c3`), nice19, a single process, poster batches2 followed by animation
batches1, and2–5 seconds between batches. The worker checkpoints cursors after
each batch, waits automatically near I/O saturation or if the xray last-window
loop maximum exceeds500ms, and stops below the 26 GiB disk floor. Migration remains
active. No cleanup or deletion is part of this worker.

Initial checkpoint:10 poster rows scanned, cursor28, no animation batch yet;
last-window loop p99 7.34ms / max46.04ms, about312GiB free. This is an in-progress
checkpoint, not completion. A persistent T3 check runs every five minutes until
completion, verifies application/resource state, and updates this report. The
private monitoring account session is revoked in the worker's finalizer.


## Backfill completion and final verification

The one worker completed its cursor pass at **18:48:39 UTC, 25 October 2026**.
All **2335** selected poster rows were processed; a final independent database
read confirms **0 posters lacking complete visuals**. It examined **2914** proxy
rows, generated **2828** animations and recorded one encode failure. A single
bounded retry of that exact source (cursor 4563) subsequently succeeded. Final
independent database count: **2829 ready animations**. The other 85 proxy rows were
skipped or returned no optional animation under the existing generator policy;
this pass does not claim every proxy must have an animation.

The worker retained one process and persisted cursors across interruptions.
Three interruptions were monitoring-session 401s: the application intentionally
revokes earlier sessions on every login, so other use of the shared e2e account
invalidated the monitor. The sessions were logged out/revoked and cookies emptied.
The operator worker then used a continuous local asynchronous `/health` response
probe (200 ms cadence, rolling 60 s maximum) for its 500 ms responsiveness guard. This
is a conservative response-latency proxy, **not** the xray event-loop counter.
No application code, auth policy, database setting or Mac service was changed.
Existing media migration stayed active. Disk remained roughly 312 GiB free versus
the 26 GiB floor. There was no manual cleanup or media deletion.

Using the authorized e2e account, an actual production signed animation returned
HTTP 200, image/webp, private immutable max-age 3600; decoded bytes were 21520,
width 202, eight frames and an animated WebP. The existing browser-probe Playwright
workflow was reused for the final UI check: two loaded animation images were
visible with normal motion; switching the real browser reduced-motion setting
removed all animated sources and retained 11 visible static images. The test
session logged out with HTTP 200. Raw numeric evidence is appended in
`deploy-measurements.json`; no capability or cookie is included.

At final verification `/auth/xray` returned 200: last-window p99 **28.54ms**, max
**581.24ms**, lifetime max **1801.28ms**. The earlier short-rollout zero-error
observation is not a claim about the entire day: over the longer observation
there were **four ingestion `package/slots` 500s**, correlated with four PostgreSQL
idle-in-transaction kills at 14:02, 14:03, 14:29 and 14:54 UTC. Two preceded bulk
backfill startup. Attribution to backfill is not established; this ingestion path
is distinct from the media status/playback reads. The final **30-minute** window
has **zero 5xx on either front door and zero idle-transaction kills**. The application
remains healthy on the same deployed SHA; no code deployment or rollback occurred
as part of backfill completion.

The persistent backfill monitor is removed after publishing this completion
record; no further encoding job or recurring backfill is installed.
