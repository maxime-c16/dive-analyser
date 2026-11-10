# Smooth clip playback: ladder, grants and Auto quality — 10 November 2026

Local branch only. Nothing here is deployed. Reviewed in one council turn
(Opus 5.5 medium, GPT-6.1 Sol medium) before implementation; their blockers
are reflected below.

## What production showed (read-only, E2E account)

- **Smallest file by design.** The player started on the legacy proxy and
  never upgraded. Portrait proxies are 406×720 (1.1 Mbps) or 202×360
  (0.25 Mbps; 32 of 100 recent clips). The server already advertised
  `start=light, recommended=hq` for all 100 clips.
- **Light was not light.** It was encoded CRF 23 with no cap: 6.4 Mbps. On
  weak 4G (6 Mbps) it had 2 stalls; on 2 Mbps it was stalled 27 s for a
  12.5 s clip. HQ at 12.9 Mbps never finished on 2 Mbps.
- **Grants were slow and serialized.** `GET /media/revisions/{id}/play` took
  0.6–0.83 s of server time even with the B2 HEAD cached. Concurrent requests
  queued: ×8 took 5.4 s each. Status calls queued the same way, and opening a
  clip queued its status behind its neighbours' (first frame at 3–4 s).
- **Short-lived, single-use URLs.** Presigned URLs lived 120 s and were
  re-minted per play, so reopening a clip downloaded it again.
- **Home server ceiling.** About 18–20 Mbps aggregate. B2 delivered 31–51 Mbps
  per client.

## Measurements behind the ladder (real HLG 60 fps original)

Per-frame VMAF against a tone-mapped 1080×1920 SDR reference. The worst
windows are the turbulent water just after entry.

| Rendition | Bitrate | Size / 12.5 s | Mean | 1st pct |
|---|---|---|---|---|
| Proxy 406×720 | 1.1 Mbps | 1.8 MB | 51 | 46 |
| Light v1 (CRF only) | 6.4 Mbps | 10.1 MB | 84 | 82 |
| **Light v2** (cap 2.5M, buf 5M) | 2.7 Mbps | 4.4 MB | 76 | 73 |
| HQ cap 8M | 8.5 Mbps | 13.3 MB | 90 | 87 |
| HQ cap 10M | 10.6 Mbps | 16.6 MB | 92 | 89 |
| HQ v1/v2 (cap 12M, unchanged) | 12.9 Mbps | 20.2 MB | 93 | 91 |

HQ stays at 12M until reviewers compare paused entry frames. The agent's real
single-pass package takes 43–47 s wall time and 757–787 MB peak ffmpeg memory
on an M2, for both v1 and v2.

Throttled Chrome playback of the same clip:

| Network | Proxy | Light v1 | Light v2 | HQ |
|---|---|---|---|---|
| 6 Mbps / 80 ms | 0 stalls | 2 stalls, 1.2 s | **0 stalls** | 5 stalls, 15 s |
| 2 Mbps / 150 ms | 0 stalls | 27.5 s stalled | 6.4 s stalled | 68 s stalled |

## Changes

### Backend

- **Grant route timing and fast path.** The grant route sends per-stage
  `Server-Timing`:
  `resolve, authz, proof, location, head(hit|miss), refresh, sign(new|reused), ledger`.
  It carries no identifiers or URLs. When a recent HEAD already proved the
  object, no provider I/O happens, so there is no rollback and no second
  authority pass. A miss keeps the full post-network revalidation.
- **Cheaper grant bookkeeping.** A process-local counter replaces the
  per-grant ledger SELECT used only for `grant_refreshes`. On Postgres the
  grant-ledger insert commits with `synchronous_commit = off`; it is an audit
  trail, not an authority.
- **Playback-only TTL and per-viewer reuse.**
  - `MEDIA_PLAYBACK_GRANT_TTL_SECONDS` defaults to 300, inside the existing
    300 s ceiling. Downloads, shares and jobs keep the 120 s default.
  - A viewer reopening the same revision gets the same signed URL while at
    least half its life remains.
  - Reuse is keyed by viewer, revision, exact storage identity and credential
    fingerprint. It is process-local, bounded and never persisted or logged.
  - Authorization still runs on every request first.
  - The URL carries `response-cache-control: private, max-age=<ttl>`.
- **Role route.** `GET /media/{uuid}/play/{light|hq}` resolves the role's
  current proof once and then runs the same grant path. A role that isn't
  provably ready returns a uniform 404 and discloses nothing.
- **Batch hint.** `POST /media/status/batch` adds `start_role: "light"` from
  one bounded ledger query over already-authorized uuids. It is a hint: no
  revision ids or URLs, and tiles still mint nothing.
- **Served-version cutover.** `MEDIA_DERIVATIVE_SERVED_TRANSFORM_VERSIONS` is
  an ordered list; empty means the produced version only. Per role, the newest
  provable version for the current source wins. An older ready version keeps
  serving while a newer one is missing or verifying. The status, the role
  route and the grant proof all share this resolver.

### Mac agent

- Encode recipes are keyed by transform version (`TRANSFORM_RATE_PROFILES`).
- v1 is byte-identical to today. v2 caps Light at 2500k with a 5000k buffer;
  HQ is unchanged.
- An unknown version fails closed before probing or encoding.

### Frontend

- **Auto (default).**
  - The viewer starts on Light by role, with no status wait, when the batch
    hinted it.
  - Without the hint it starts status-driven on Light.
  - On a weak network (< 3 Mbps, 3G or Save-Data) it starts on the proxy.
- **Throughput estimate.** Measured from real buffering: media seconds per
  wall second, times the rendition's bitrate. v1 and v2 Light bitrates are
  told apart by `transform_version`. Cache-speed fills are ignored.
- **Background upgrade.** Auto climbs one step the network sustains: proxy →
  Light (≥ 1.5× Light), then → HQ (≥ 19.4 Mbps).
  - A detached element buffers the next rendition.
  - It replaces the visible one only at a natural boundary: when the viewer
    pauses (same frame, stays paused) or at the loop restart (new lap from its
    first frame).
  - Refused autoplay or a timeout (20 s) keeps the current rendition.
  - The replaced element is fully released, so no second decoder stays parked.
- **Stall step-down.** Two stalls in 20 s, or one over 2 s, step Auto down one
  rendition at the same moment.
- **Remembered choice.** A manual choice sticks to the following dives in the
  tab; "Auto · <rendition>" hands control back.
- **Warm-up priority.**
  - The visible clip holds neighbor warming until its first frame (at most
    2.5 s), so neighbor status and grant lookups no longer queue ahead of it.
  - The window is next and previous only (2 idle elements, was 3).
  - Hinted neighbors warm their Light by role, with no status call.

## Verification

- **Backend:** full suite 1915 passed, 113 skipped. New tests cover:
  - URL reuse per viewer, renewal at half-life and storage scoping;
  - no reuse after access is revoked;
  - the HEAD-hit fast path;
  - the role route (ready, unservable, stranger);
  - served-version fallback during a backfill;
  - the batch hint.
- **Mac agent:** 482 passed. The 9 failures are identical on clean
  `origin/master` with this Mac's ffmpeg (VFR fixtures using `-vsync`, HDR
  proxy brightness, HDR tone-map artifact). New recipe tests pass.
- **Frontend:** `ci/gate.sh frontend` passed. New player tests cover:
  - role start;
  - stale-hint fallback;
  - weak-network start;
  - remembered choice;
  - pause and loop swaps (including refused autoplay and the swapped element
    staying paused);
  - proxy → Light climb;
  - stall step-down;
  - warm-up hold.

  Two of them were mutation-checked.
- **Real Chrome** on a production build against production data (role route
  and hint not deployed, so the start is status-driven):
  - first frame on Light 720×1280 in 2.97 s, 3.00 s and 3.42 s;
  - pausing swapped to HQ 1080×1920 on the same frame, still paused, on
    desktop and on a 390×844 phone viewport;
  - neighbor status calls started only after the clip played.
- **Not verified:**
  - real iPhone and Android: decoder limits, autoplay of the swapped element,
    Low Power Mode;
  - grant timings on production after deploy (read them from `Server-Timing`);
  - the Postgres `synchronous_commit` effect on deb-serv's disk;
  - B2's handling of `response-cache-control` on playback URLs (downloads
    already use `response-content-disposition`);
  - real expired-grant behaviour.

## Rollout order (each step needs explicit approval)

No SQL migration. This change keeps production on v1: `docker-compose.yml`
still produces `ffmpeg-h264-web-v1` and serves v2 first, then v1 (no v2
packages exist yet). Shipping it in any order is therefore safe, including
through the merge-triggered auto-deploy.

1. **Server.** Run `ci/ship.sh server` (`--dry-run` first). It recreates the
   backend and frontend and reloads both nginx front doors (LAN
   `dive-analyser-nginx-1` and the Funnel proxy), as `docs/REPO_WORKFLOW.md`
   requires after a `docker-compose.yml` change. The new
   `/api/v1/media/{uuid}/play/{role}` route sits under the existing
   authenticated `location /api/`, so no nginx or `ops/tailscale` config
   changes. Verify `Server-Timing` on a grant, the role route and
   `start_role` in the batch.
2. **Mac agent.** Run `ci/ship.sh mac`. The agent learns v2 and still
   encodes v1 leases byte-identically. Confirm the deployed agent reports the
   v2 recipe before going on.
3. **Switch production to v2.** A separate server change sets the
   `MEDIA_DERIVATIVE_TRANSFORM_VERSION` default to `ffmpeg-h264-web-v2`; ship
   it with `ci/ship.sh server`. New packages become v2; existing clips keep
   serving v1.
4. **Backfill.** Cancel any open v1 migration run
   (`scripts/media_migration.py status`, then `cancel`), then start a v2 run
   with the existing controller (`start --budget-gib N`). It is bounded by
   budget, queue depth and the infra breaker, behind new uploads
   (priority 70). Expect about 45 s of Mac time per clip, plus about 29 MB of
   B2 download and about 25 MB of upload per clip.
5. **Retire v1.** After full coverage, remove v1 from
   `MEDIA_DERIVATIVE_SERVED_TRANSFORM_VERSIONS`. Delete v1 objects only after
   a grace period.
6. **Announce.** Once the Mac upgrade is confirmed, announce the lighter
   Light in a server PR.

## Rollout log

- 2026-11-10: PR #194 merged as `4752c180`; `ci/ship.sh server` deployed it.
  Health checks and signed-media checks passed. Production `Server-Timing`:
  - first role grant 3.27 s, dominated by a B2 HEAD miss of 2.23 s;
  - repeat role grant 0.51 s (HEAD hit, URL reused);
  - warm revision grant 0.33 s.

  B2 returns `cache-control: private, max-age=300`. Clips opened in about
  1.4 s on the proxy.
- 2026-11-10: `ci/ship.sh mac` deployed `4752c18`. The agent carries the v2
  recipe and checked in. v1 migration run 1 had finished (2983/3031 complete,
  nothing remaining).
- Follow-up (this change):
  - **Production on v2:** compose now produces v2.
  - **Better speed samples:** Auto measures the network from background
    neighbor Light downloads and exact same-origin proxy transfers
    (Resource Timing), and uses the browser downlink hint for climbing.
    Before this, production clips opened from a preloaded proxy never
    produced a sample and never climbed.
  - **Still to do:**
    - the v2 backfill (cancel run 1, start a v2 run);
    - taking the 2.2 s first-grant B2 HEAD off the request path.

### First-grant cost after a deploy (measured 2026-11-10)

The 2.2 s "HEAD miss" on the first production grant was not B2:
- **B2 HEAD:** 18–80 ms from the warm backend.
- **DNS:** 4–13 ms in the container.
- **Actual cost:** building the boto3 client, 6.3 s in a fresh process. It
  landed on the first viewer after every restart. The backend now builds the
  client on a background thread at startup, under the same lock a grant would
  take.

Remaining first-time grant cost (0.6–1.3 s):
- **Rendition resolve:** 0.19–0.49 s.
- **Post-HEAD re-check:** 0.29–0.48 s, a second full resolve.

The same resolve takes 26–70 ms (15 queries) in an idle process. The
difference is host CPU starvation: deb-serv has 2 cores, CPU pressure stays
at 42–52 %, and Navidrome alone averages 34 % CPU over 23 days. The
re-check is kept (council blocker); host capacity is the lever.
