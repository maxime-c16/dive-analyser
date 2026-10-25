# Media startup lots 1–3 — production rollout

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
| PostgreSQL idle-in-transaction kills | 2 in preceding 30 min | **0** since rollout preparation at 13:09:01 UTC, including after final restart |

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

## Backfills and resource guardrails

Backfills were deferred before any batch because sustained server I/O pressure
was already high, including full avg60 around 37–47% and some avg60 around 58–73%
during the deployment gates. Available space remained about 313–314 GiB, well above
the 26 GiB floor. Final post-build pressure was still some avg60 **33.95%**, full avg60 **22.93%**. No migration process was paused. No explicit backfill ran:
poster/ThumbHash cursor 0; animation cursor 0. A final read counted 2343 ready
posters, 2335 lacking complete visuals, and 0 ready animations. Consequently the
production animation appearance has not yet been exercised; local/hosted automated
coverage passes, and production verification remains for the first safe batch. Resume poster batches at limit2–4,
then animations at limit1–2 only once pressure is sustainably low. Record each
cursor, count, free-space reading and event-loop lag. Existing normal producers
may enrich newly finalized posters independently; this is not a completed corpus
backfill. No originals, media or database data were manually deleted.

## Rollback

If fresh 5xx, freezing or broken posters appear, disable capability emission,
restore the privately recorded old proxy image/config/mounts, and use
`ci/ship.sh server --ref 0a6b94f06cb99be9fa29ec26c95c329f15d011ce` (dry-run first).
Keep additive columns and generated files. Reconfirm running service SHAs and
both doors after rollback. No Mac rollout, lot4 or database tuning performed.
