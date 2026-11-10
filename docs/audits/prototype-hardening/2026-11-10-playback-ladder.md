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

### Next optimizations (2026-11-10, after the server CPU fix)

deb-serv: Navidrome had spun at 1.5–1.85 cores for 23 days with no requests,
about 1.5 M empty `read()` calls per second. It was restarted and capped at
1 core, with a daily scan; the matchmaking preview was stopped. CPU pressure
fell from 42–52 % to about 8–15 %. First-time grants went from 0.61–1.29 s
to 0.50–0.59 s.

1. **Re-encode throughput.** The agent encoded each package output on
   1 x264 thread (`threads_per_variant=1`). Measured on mac-media-01
   (i5-8257U, 8 GiB), same clip, while the live run was also encoding:

   | Threads | Wall time | Peak RSS |
   |---|---|---|
   | 1 | 105 s | 729 MB |
   | 2 | 76 s | 782 MB |
   | 3 | 76 s | 821 MB |

   Beyond 2 threads the single decode / tone-map thread is the bottleneck.
   New setting `media.package_threads_per_variant`, default 2, bounded 1–3.
   The fleet-wide one-active-package cap is unchanged.
2. **Credential probe.** Owner decision: replace the per-object first-grant
   HEAD with a background probe.
   - Every `MEDIA_PLAYBACK_CREDENTIAL_PROBE_SECONDS` (default 60), a probe
     HEADs the newest verified PROD replica.
   - While that proof is under two intervals old, for the same credential
     fingerprint, grants skip the per-object HEAD and the post-network
     authority refresh.
   - A failed or stale probe drops the proof and clears the per-object HEAD
     cache, so grants return to the per-object HEAD with its legacy-fallback
     and 503 policy.
   - A deleted or corrupt object now surfaces as a playback error, which the
     player recovers from or reports.
   - Setting the interval to 0 restores the previous behaviour.
3. **Deferred status for role starts.** A clip that starts on Light by role
   fetches `/status` after its first frame, or after at most 2.5 s, so the
   lookup no longer competes with the grant on the single worker.

### Encode recipe v3 and the tone-map floor (2026-11-10)

Measured on mac-media-01 with the Mac's ffmpeg 8.1, same HLG clip, while the
live backfill was also encoding.

**Stages:**
- Software decode: 3.2 s.
- VideoToolbox decode: 8.8 s, slower on this Mac.
- HLG→SDR tone-map + scale: 16–22 s. Scale only: 6.7 s. More filter threads
  change nothing.

**Encoders** (ffmpeg time per package; VMAF Light mean / worst 1 % / worst
frame, HQ mean):

| Encoder | Time | Light | HQ |
|---|---|---|---|
| x264 medium | 55 s | 76.3 / 72.9 / 71.7 | 92.6 |
| x264 fast | 44 s | 76.1 / 72.1 / 70.0 | 92.4 |
| x264 faster | 32 s | 75.4 / 70.8 / 67.9 | 92.1 |
| h264_videotoolbox | 21 s | 55.6 / 44.2 / 22.6 | 85.4 |

VideoToolbox is rejected: on pool water at Light's bitrate it is barely
better than the old proxy.

**HLG→SDR as a 3D LUT (haldclut, 64³)** was slower (13.2 s vs 9.6 s) and did
not match the current rendering (VMAF 57), so it was not pursued. Skipping
the tone-map entirely (relying on HLG's SDR compatibility) would save about
10 s per clip, but it changes the look of every clip; that needs an owner
visual review.

**Decision:** v3 is v2's caps with preset "faster", under a new transform
version so each version still names one exact recipe. Production produces v3
and serves v3, then v2, then v1.
### Batched clip resolution (2026-11-10)

Serving several transform versions multiplied the per-clip lookup: one
ledger, revision and location query set per role and per version. That came
to 18 queries for one clip with three served versions, run on every first
grant and every status call.

The resolver now preloads in a fixed set of queries:
- every ledger row for the current source (all roles and served versions);
- their backbone revisions;
- each blob's first `TRUSTED_REPLICA_PROBE + 1` verified replicas, through a
  window function.

Total: 6 queries including the canonical-source lookup. The replica trust
rule is one shared function (`evaluate_trusted_replicas`), used by both
`trusted_prod_location` and the batch, so they cannot diverge. No schema
change. A precomputed playback table was not built: it needs a production
migration and an invalidation path in every writer, while this removes most
of the cost without either.

### v4: fragmented MP4 for HLS, and a second encoder (2026-11-10)

Owner decision: pause the v2/v3 backfill (45 clips done) and backfill once in
v4. v4 is v3's encode (`faster`, Light capped 2.5M, HQ 12M) written as
fragmented MP4 (`+frag_keyframe+empty_moov+default_base_moof+global_sidx`).

Proof of concept on the real clip:
- **Layout:** `ftyp`, `moov` (init, about 800 B), a 196 B global `sidx`, then
  1 s `moof`/`mdat` fragments. Sizes match v3.
- **Progressive playback:** Chrome plays the file as a normal MP4, first frame
  in 86–107 ms, so older clients still work.
- **Playlists:** a byte-range HLS media playlist can be built from the first
  ~1 KB alone.
- **Adaptive switching:** hls.js started on HQ at 20 Mbps and stepped down to
  Light when the network dropped to 4 Mbps at 2.5 s, with 0.77 s of total
  stall over three laps. Progressive HQ at 6 Mbps stalls 15 s.
- **To tune in the player PR:** ABR settings, because hls.js climbs back to
  HQ after each loop.

Both the agent's and the server's validators already accept the layout
(`moov` precedes the first `mdat`).

**Second encoder:**
- `MEDIA_MAX_ACTIVE_PACKAGES` (compose default 2) caps packages fleet-wide,
  and an agent never holds two packages at once.
- `scripts/register_media_agent.py add` registers a package-only Mac with its
  own key. Only the hash is stored; the key goes to a 0600 file and is never
  printed.

**Rollout order:**
1. `ci/ship.sh mac`.
2. `ci/ship.sh server`.
3. **Proxy step after the server deploy** (`docs/REPO_WORKFLOW.md`, "Not
   automatic"). `ci/ship.sh server` already reloads both nginx front doors.
   This change's `docker-compose.yml` diff only adds backend `environment`
   values, with no nginx service, mount or `nginx/` change, so no recreate is
   needed. Verify with
   `git diff <live>..<new> -- docker-compose.yml nginx ops/tailscale`. If that
   diff ever touches nginx, run `docker-compose up -d --force-recreate nginx`
   on deb-serv.
4. Register and start the M2 agent.
5. Cancel run 2.
6. Start a v4 run.

The HLS playlists and the player come in the next PRs; the v4 files already
work as progressive MP4 meanwhile.

### HLS playback over v4 packages (2026-11-10)

Local branch `feat/hls-playback`; not deployed.

**Server**
- `GET /api/v1/media/{uuid}/hls.m3u8`: the master playlist, listing Light
  then HQ, or HQ first with `?start=hq`.
  - Each variant links to its revision's media playlist; the master carries
    no signed URL.
  - Authorization comes first; a stranger gets a uniform 404 with no
    provider I/O.
  - A clip without a ready fragmented Light gets a 404, and the player falls
    back to the files.
- `GET /api/v1/media/revisions/{id}/hls.m3u8`: the byte-range VOD playlist
  for one package.
  - It goes through the existing grant path (authorization, current
    derivative proof, verified storage, presign, grant ledger), with the
    signed URL in the body instead of a redirect.
  - Responses are `private, no-store`.
  - Source revisions are denied before any storage work.
- **Index.** The first 64 KB of each package (`ftyp`, `moov`, the per-track
  global `sidx`) is read once from B2 with a ranged GET, parsed (segments,
  `avc1`/`mp4a` codecs, resolution, peak and average bandwidth) and cached
  in-process by blob SHA-256. Bytes are content-addressed, so the cache
  never goes stale. Classic MP4s cache as "not fragmented".
- **Hints.**
  - The status sends `derivatives.hls`: `apple`, `all` or null.
  - Each Light and HQ entry gets an `hls_url`: that rendition alone.
  - The batch sends `start_hls`.
  - `MEDIA_HLS_TRANSFORM_VERSIONS` (default `ffmpeg-h264-web-v4`; empty
    turns HLS off).
  - `MEDIA_HLS_CORS_READY` (default off) switches `apple` to `all`.

**Measured in real browsers on production v4 packages** (read-only:
E2E account, existing grants, playlists rendered locally):

| Engine | Source | Playing after |
|---|---|---|
| WebKit | progressive v4 Light | 3.5–6.4 s (reads fragment by fragment) |
| WebKit | HLS | **0.8–1.0 s** |
| Chrome 157 | progressive v4 Light | 0.8 s |
| Chrome 157 | native HLS, segments on B2 | fails: `MEDIA_ERR_SRC_NOT_SUPPORTED` |
| Chrome | hls.js, segments on B2 | blocked by CORS |

- **v4 is slow progressively on Safari.** Production is already serving v4
  Lights as progressive files, so Safari and iPhone viewers of v4 clips
  start slowly today.
- **Only Apple's player works without CORS.** Chrome 157 reports native HLS
  support (`canPlayType` → `maybe`). It plays the same playlists same-origin
  or with a CORS-enabled origin, but it refuses cross-origin segments
  without CORS.
- So the player treats only Apple's player (vendor `Apple`: Safari and
  every iOS browser) as CORS-free.

**Player**
- **Auto.** It plays the master: Apple's native player, or hls.js / native
  where the server says `all`.
  - The background swap and the stall step-down stand aside, because the
    stream switches itself.
  - The menu reads "Auto · Light/HQ" from the frame size.
- **Manual choice on Apple.** It plays that rendition's own playlist. HQ
  reached 1080×1920 in 1.7 s at the same moment.
- **Other browsers** keep the progressive files.
- **Failures.**
  - A playlist source that fails before its first frame moves the clip to
    its progressive files: same choice, same moment, no error card.
  - A stream that loses its connection mid-play reloads in place (fresh
    playlists, fresh grants), up to the existing recovery limit.
  - An hls.js failure before any segment turns hls.js off for the tab.
- **hls.js** (1.7.3) is loaded lazily, only where used. It keeps the whole
  clip buffered, so loops never refetch. Segment downloads feed the shared
  network estimate.
- **Weak networks** (estimate < 3 Mbps, Save-Data, 3G) still start on the
  small proxy.

**Verification**
- **Backend:** 15 new tests.
  - Parser on synthetic v4-recipe and faststart headers.
  - Playlist format.
  - Authorization before provider I/O.
  - Grant ledger.
  - 404/503 paths.
  - Kill switch.
  - Hints and the aliased HQ.
- **Frontend:**
  - 9 engine tests with a fake hls.js;
  - 9 player tests (Apple start from the hint and from status; manual pin
    and return to Auto; fallback before the first frame; pinned-playlist
    fallback; in-place reload; Chrome without CORS; weak network). The
    fallback test was mutation-checked.
- **Real WebKit** on a local build against production data, with only the
  undeployed endpoints and hint fields stubbed: Auto streamed Light
  (720×1280), manual HQ came through its playlist, Auto returned to the
  stream, and loops played (one ~0.3 s hitch on the first restart).
- **Real Chrome:** no HLS requests; progressive files as before.
- **Not verified:**
  - real iPhone, iPad and Android;
  - hls.js against B2 (needs the CORS rule);
  - Safari's ABR switching under a real network drop (WebKit in Playwright
    cannot be throttled);
  - expired-grant recovery after 5 minutes on one clip.

**Rollout**
1. Merge; the merge deploys the server (no migration, no compose, nginx or
   `ops/tailscale` change). Apple devices then stream every v4 clip.
2. **B2 CORS (production bucket setting, owner approval).** Allow `GET` and
   `HEAD` from the app origin with the `Range` header, exposing
   `Content-Range`, `Content-Length` and `Accept-Ranges`. Then set
   `MEDIA_HLS_CORS_READY=true` and ship the server so Chrome, Android and
   desktop stream too.
