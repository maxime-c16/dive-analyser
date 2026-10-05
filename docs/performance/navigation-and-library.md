# Navigation and Library performance experiment (2026-10-05)

Baseline: `378d96d` (origin/master when the experiment began).

The main win is retaining the Library list rather than fetching it on every
mount. Route intent also overlaps module downloads with API reads. Thumbnail
status requests were already viewport-gated and batched, but batch chunks
actually ran concurrently and a failed batch fanned out into individual reads.
Tiles without posters also loaded video metadata, adding media traffic.

## Changes and boundaries

- Library snapshots are keyed by authenticated user, role and diver bindings.
  Memory handles route returns; localStorage handles reloads and browser restarts.
  A snapshot is fresh for 60 seconds and retained for at most 24 hours. Older
  snapshots render immediately while a background request refreshes the list.
  Authentication still completes before the Library renders. Failed refreshes
  leave saved dives visible with a retry notice. Refresh explicitly bypasses the
  cache. Writes, uploads, logout, auth failures and access-key changes invalidate
  it. Requests finishing after invalidation cannot refill storage. Storage
  events discard other tabs' in-memory copies. Quota/privacy failures fall back
  to memory; those browsers cannot restore the list across reloads.
- Navigation waits for 120 ms of hover/focus or starts on pointer-down. Only
  Overview, Analytics and Sessions prefetch their initial list/statistics GETs.
  Other navigation destinations prepare code only. No media renditions, video
  bytes or background recall jobs are requested on hover. Data saver, offline
  and slow-2g/2g skip speculative work. Unsupported network hints fall back to
  the bounded intent policy. Prefetched data expires after 10 seconds, is
  consumed once, and has a 12-entry cap. Failed speculative reads can retry on
  actual navigation. Overview's optional personal values and child charts still
  load normally; this is not a claim that every destination becomes instant.
- The Library stays eagerly bundled to avoid a new code-to-data waterfall on
  cold entry. The viewer and public share page load separately. Opening the
  first viewer can consequently wait for a small additional module download.
- Status batches have at most 100 assets and one request in flight. A failed
  batch resolves placeholders without 100 fallback requests; it is not cached
  as a permanent missing result. Visible tiles use poster images only. A dive
  without a poster displays its dive code instead of extracting a video frame.
  Actual playback still uses the existing player and recall flow.

## Measurements

Production Vite builds, shared T3 browser at 1280 × 800, synthetic API fixtures
with 300 ms response delay, 80 ms JavaScript response delay, no HTTP cache.
There was no bandwidth/CPU throttling. The browser and fixture server were on
separate LAN machines; scheduling/network noise was substantial. Timings are
click to destination content plus one animation frame, sampled three times.
The Library fixture contains 2,506 attempts (roughly 0.88 MB JSON), matching the
live row count but not its exact field/payload distribution.

| Scenario | Samples (ms) | Median (ms) | Requests |
| --- | --- | --- | --- |
| Analytics, baseline click | 1535, 1325, 1303 | 1325 | 4 analytics reads |
| Analytics, candidate click without hover | 1190, 1374, 1070 | 1190 | 4 analytics reads |
| Analytics, candidate after 600 ms hover | 949, 1608, 476 | 949 | 4 analytics reads, no click-time duplicates |
| Return to Library, baseline | 1187, 1285, 1436 | 1285 | 1 dive + 1 diver read each time |
| Return to fresh Library, candidate | 18, 366, 13 | 18 | 0 dive/diver reads each time |

The hover median improved about 28%, with one slower sample. The 600 ms lead
is time spent before clicking, not free time removed from total work. This is
an experiment showing useful overlap, not a production percentile/SLA claim.
Cache request elimination was consistent; timings will vary by device/data.
A full candidate reload also restored 2,506 attempts with zero dive/diver reads.
It still checks authentication and fetches visible thumbnail status normally.

At the same viewport, the posterless baseline created 12 `<video>` thumbnails;
the candidate created zero. Successful visible status lookups remained batched.
Tests verify 205 lookups become three serialized batches and 48 lookups during
a 503 become one failed batch rather than an individual-request burst.

Baseline entry JavaScript was 356.35 kB / 109.84 kB gzip. Candidate entry is
approximately 316 kB / 100 kB gzip (about 11% raw / 9% gzip smaller). This is the
entry chunk, not the sum of every asset eventually loaded by every route.

## Read-only production check

The deployed backend was healthy and idle during the sample (about 0.2% CPU,
149 MiB memory). Direct read-only execution of its existing Library query and
serialization returned 2,506 non-lineup dives. Python JSON encoding occupied
2,013,767 bytes, before HTTP compression. Three query/serialization samples
were 642.1/137.4 ms, 80.3/119.9 ms and 83.9/107.3 ms. These are internal stages,
not authenticated HTTP request or browser timings. No production files,
configuration, database records or deployed services were changed.

## Reproduce

Build baseline and candidate into separate directories, then run:

```sh
python3 frontend/perf/serve-fixtures.py \
  --baseline /tmp/dive-perf-baseline-dist --candidate frontend/dist
```

Use `--host 0.0.0.0` only when testing from the collaborative browser on another
LAN host. Baseline is port 4180; candidate is 4181. Open `/dives?scope=all`.
The fixture uses only synthetic identities/attempts, never production APIs.
Missing fake videos return 404; inspect attempted metadata requests rather than
expecting playable footage. Clear `dive-library-v1` in localStorage for a cold
candidate Library. Reload within 60 seconds to test fresh reuse; age its
`savedAt` beyond 60 seconds to test visible stale data/background refresh.

For each Analytics sample, start with a full navigation to Library (a new JS
module realm), wait for attempt cards, optionally dispatch a bubbling
`mouseover` to `aside a[href="/analytics"]` and wait 600 ms, then record
`performance.now()` before clicking it. Stop after the Analytics h1 appears
and one `requestAnimationFrame`. Inspect Resource Timing for the four
`/api/v1/analytics/` requests and absence of duplicates. For Library returns,
visit Analytics then click `aside a[href="/dives"]`; stop when
`[data-attempt-id]` cards render. Count new dive/diver resources after click.
