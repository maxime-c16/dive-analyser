# Library preview-first playback

The Library player, playback cache, and native preloading window now choose
an existing 720p/360p browser preview ahead of the camera original. A tile's
unresolved playback URL (local cache or cloud) no longer starts a transfer before playback
status can reveal a ready preview. Only rendition-resolved cache entries can
seed playback immediately; native warming skips unresolved results after a
failed detailed status lookup. Tile batches still request posters/status
only; the bounded playback window resolves detailed status once per cache TTL.
Ready nearby previews use native `preload=auto`; original-only speculative
sources retain `preload=metadata`. This remains browser-discretionary preloading.

The player offers an explicit quality button when both preview and original
are available. Original decode failures retain the existing Use Preview action.
A late status response can update available quality without replacing a source
that has presented a frame and is still advertised as ready. Explicit quality
changes and retries re-arm the first-frame cover. Authorization, logout cache
reset, pool bounds, cancellation and obsolete-window eviction stay in place.

This does not create missing previews, tone-map existing HDR files, or fix the
B2 DNS path. Clips with no ready preview retain the existing original fallback.
The ingestion/package and coverage work must supply those missing derivatives;
this change specifically fixes choosing a heavy original despite a ready preview.

## Validation and measurements

The baseline source policy is `origin/master` at
`f146e096192109c2b33feba845690fc78e8fef93`: `full_quality_url` first, including
native warming. Controlled regressions now assert preview selection when both
are present, 360p fallback, explicit original selection, original decode recovery,
blocking an unresolved cloud seed, and preserving an already presented preview.
The native pool test distinguishes preview byte anticipation from conservative
original warming before acquisition.

The T3 collaborative browser ran the actual player against a generated 3 s
H.264 test clip: preview playback succeeded, explicit Original produced the
fixture's intentionally unreadable source, Use Preview recovered playback,
and navigation reached the warmed second clip at readyState 4. The quality
button was inside the viewport and its text fit at 390 x 844 and desktop sizes.
This was desktop-browser mobile layout testing, not an iPhone hardware test.
It establishes behavior, not a production latency before/after.

To reproduce the fixture (no credentials or production writes):

```sh
mkdir -p frontend/node_modules/.cache
ffmpeg -v error -f lavfi -i testsrc2=size=640x360:rate=30 -t 3 \
  -c:v libx264 -pix_fmt yuv420p -movflags +faststart -y \
  frontend/node_modules/.cache/library-preview-synthetic.mp4
npm run dev --prefix frontend -- --host 127.0.0.1 --port 3022 --strictPort
```

Open `http://127.0.0.1:3022/e2e/fixtures/library-player.html`. The development-only
fixture intercepts its own status reads and never enqueues jobs. Its Original
URL is intentionally invalid so recovery can be exercised. Synthetic bytes
are generated locally and must not be committed.

After frontend rollout, compare the same representative clips and network,
separating cold opens, warm opens and next navigation. Record chosen source,
bytes transferred, click-to-presented-frame, buffering stalls, failures,
explicit quality switches, revision, network and sample count. Report median
and p95 over equal independent windows. Keep missing-preview preparation as
a separate measurement. No production after numbers are available before deploy.

Frontend-only rollout through the repository's PR/merge and `ci/ship.sh server`
procedure (dry-run first). No schema, Compose or Mac configuration change is
required by this PR; backend preparation improvements remain in PR #128.

## Local startup and animated tiles (lot 3)

An existing local 720p/360p proxy now starts ahead of durable Light/HQ. Durable
qualities remain explicit choices; status revalidation preserves a presented
local source. No automatic playback swap is attempted. With no local proxy,
durable playback remains the fallback. Covers prefer local thumbs/posters.

Optional server-generated `animated` WebP tiles respect reduced motion, data
saving and viewport visibility. Their explicit bounded backfill, disk floor,
synthetic measurement fixture and deployment order are documented in
[audit lot 3](audits/media-startup-opus/lot3-result.md).
