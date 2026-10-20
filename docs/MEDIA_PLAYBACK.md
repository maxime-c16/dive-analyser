# Evaluation media: staged rollout and measurement

## Current evidence (20 October 2026)

The read-only [before snapshot](reviews/media-playback/before-2026-10-20.json)
contains aggregate counts only. Six automatic-review previews in the preceding
24 hours waited a median 62.13 s (p95 103.96 s), then processed in a median
11.66 s (p95 16.68 s). These six observations are a baseline, not a robust SLA.
Queue time uses creation to latest claim; retried jobs can include retry delays.
Ready cache rows are catalog coverage, not proof that files still exist.

The active Mac has 8 logical cores, 8 GiB RAM and about 13 GiB free disk.
The [synthetic conversion benchmark](reviews/media-playback/worker-slots-2026-10-20.json)
ran identical four-job batches in order 1, 2, 2, 1 slots, two encoder threads per
job, on that Mac. Mean batch time: 3.922 s serial, 2.591 s with two slots
(33.9% shorter, 1.51x throughput). Individual jobs take longer with two slots.
This excludes Photos, downloads, uploads, live contention and peak memory;
it does not establish an end-user playback improvement or production capacity.
No live worker setting was changed for this benchmark.

### Additional file-selection diagnosis supplied at 16:18

The reported failing clip was an approximately 30 MB iPhone MOV original in
B2: HEVC 10-bit HLG (`arib-std-b67`), with the MP4/MOV `moov` metadata at the
end of the file. The report observed Safari taking 20–30 seconds to start,
then playing audio with a black image, despite an SDR proxy already being
ready. Treat these timings and file details as supplied incident evidence,
not a new measurement from our benchmark. They identify a separate cause
from worker load: which artifact the player selects and can decode.

The general player's existing selection prioritizes `full_quality_url`.
This evaluation change explicitly prefers 720p/360p previews and leaves the
original behind a quality selection; its regression tests include a ready
original plus a ready proxy. Apply the same policy to the general player in
the next playback stage. Do not assume that `yuv420p` alone produces SDR:
HLG/PQ sources require tone mapping and correct SDR color metadata during
ingestion. Verify generated proxies as H.264 8-bit SDR with fast-start metadata.

The supplied diagnosis also mentions two failing backend HDR-to-SDR tests on
master. Relevant parametrized cases exist in `test_browser_upload.py`, but
their reported failure status has not been independently reproduced here.
Reproduce both HLG and PQ cases with the deployment ffmpeg build before
declaring HDR ingestion fixed. An original downloaded for VLC/QuickTime was
reported as a temporary workaround; it does not validate browser playback.

## Stage 1: remove avoidable waits and stabilize playback

- Prefer ready browser previews, download the current and next small preview,
  retain each video element across promotion and replay. Background jobs may
  add quality choices but cannot replace a video after its first decoded frame.
- Admit ready previews to new automatic selections. Existing selections can
  still contain cold clips and remain resumable for preparation/retry, subject
  to current authorization and unchanged video identity. Resume/queue GETs do
  not create preparation jobs. This temporarily narrows the pool; it is not a
  replacement for ingestion/backfill coverage.
- Interactive preparation priority is 5 (poster 6), ahead of ingestion 10 and
  background warming 100. Reuse active jobs rather than duplicate them.
- The worker drains available batches without its old idle interval after
  every batch. Idle/error polls still wait; shutdown remains responsive.
- Serialize Photos exports within the worker, limit ffmpeg encoder/decoder
  threads, and serialize backend lease allocation across API processes.
  Sources already leased elsewhere are excluded from subsequent allocation.
- Hidden iOS videos may defer decoding: a fully downloaded blob can promote
  the next slot, while visible playback continues to wait for a decoded frame.
  Oversized previews and other streaming fallbacks become promotable once
  their source is assigned, without requiring a hidden decode event. They
  may still load after promotion; this readiness signal does not claim that
  the streaming file is downloaded or decoded.
  The decode timeout starts after the visible source exists.
- Compose DNS upstreams change to 1.1.1.1/1.0.0.1 after observed Docker DNS
  failures. Recreate the backend via normal deployment, then verify actual B2
  access; a LAN frontend preview does not apply this production setting.

Required services: backend, frontend, Mac agent. No SQL migration.
Follow REPO_WORKFLOW.md: PR, merge, `ci/ship.sh all --dry-run`, then ship.
After recreating the backend, reload both nginx front doors so cached upstream
container addresses are refreshed: the LAN `dive-analyser-nginx-1` and Funnel
`dive-funnel-funnel-proxy-1`. The normal `ci/ship.sh server` deployment performs
both reloads. Follow the Compose/nginx instructions in `REPO_WORKFLOW.md` if
applying the Compose change separately; a backend-only recreation is incomplete.
The release catalog lists the two required server services; the Mac agent must also be deployed. Do not enable extra slots before
observing the one-slot drain change with real jobs.

## Stage 2: two slots, same worker

Existing `media.max_jobs: 2` leases two distinct assets and processes them
concurrently. Keep one daemon/agent identity, not two processes sharing one
identity. B2 downloads and conversion can overlap; Photos access remains
serialized within this daemon. Fleet-wide Photos access is not serialized.

Canary with two slots only after a one-slot production observation window.
Record queue age, throughput, failures, CPU, RSS, disk and API latency for
both windows. Stop the canary on storage thresholds, materialization errors,
or worsening user-visible playback. Configuration rollout must follow the
managed deployment/configuration procedure; keep max_jobs=1 for rollback.
The synthetic result supports a canary, not increasing beyond two slots.
Before adding separate hosts, add lease generation fencing so stale work from
an expired lease cannot finalize a reassigned job under a reused identity.

## Stage 3: ingestion and coverage (remaining work)

Create and verify a browser-compatible preview and poster during ingestion,
including HEVC 10-bit HLG/PQ-to-H.264 SDR conversion and color validation,
with durable rendition storage and explicit package readiness. Browser uploads
must produce these directly without depending on Photos or a synthetic UUID.
Retain originals for explicit original-quality playback. Implement durable
readiness consistently across selection, status and serving, and repair
existing selections. Add worker health/paused reasons to preparation status.
Avoid repeated automatic retries of permanently invalid Photos identities.

Then produce a resumable backfill dry-run manifest: eligible public clips,
missing preview/poster counts, expected bytes, free-space reserve, source
availability, failures, and owner coverage. Keep background priority below
interactive work. The independent audit estimated 1,806 public clips missing
previews and about 2.1 GB preview output, but these must be recomputed before
execution. Do not start a broad backfill against a nearly full server.

## Reproduce and compare

From this checkout, snapshot before each rollout and after a comparable window:

```sh
ssh diveanalyzer-server 'docker exec -i dive-analyser-backend-1 python -' \
  < ops/media-playback-snapshot.py > /tmp/media-after.json
ssh diveanalyzer-mac '/Users/Shared/services/data/diveanalyzer/venv/bin/python - --ffmpeg /Users/Shared/services/data/diveanalyzer/bin/ffmpeg' \
  < ops/benchmark-media-slots.py > /tmp/media-slots.json
```

Snapshot queries run in a read-only repeatable-read transaction with a 10 s
statement timeout. They emit no user identities, tokens or object URLs.
Keep before and after snapshots with deployed SHA, settings, time window,
network, sample counts and competing workload. The rolling 24 h windows overlap
immediately after deployment: do not label those an independent before/after.
For a release comparison, use separate equal-duration windows and explicit
post-deployment timestamps in queries.

Playback acceptance uses the same clip set and network, with cold and warm
runs separated. Capture click-to-first-frame, next-click-to-first-frame,
preview fetch bytes/duration, status/grant latency, failures and retries;
report median/p95 and sample counts. Test real Safari/iPhone in addition to
isolated desktop WebKit. Provisional targets: first-frame p95 <=2.5 s for ready
previews, next transition p95 <=0.5 s, media-grant errors <0.1%. These are goals,
not measured outcomes. Missing media preparation is a separate metric.

Do not claim production "after" results until deployment and comparable samples
exist. Roll back through `ci/ship.sh` to the prior merged SHA if regressions
appear; preserve the baseline and failure evidence.
