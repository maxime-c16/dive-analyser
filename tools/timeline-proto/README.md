# Disposable session timeline lab

LAN-only prototype at `http://192.168.1.151:8796/proto/timeline/1`.
No login. Never expose through Funnel or a public interface.
No production app, database, B2 object, or existing stack is changed.
The standalone frontend entry is `frontend/public/proto/timeline/index.html`.

## Preparation

Load `~/.config/dive-analyser/session-lab.env` without printing it, then run
`prepare.py` with boto3 and ffmpeg-full (zscale + tonemap). Alternatively provide
`SESSION_LAB_SOURCE_URL`. `TL_DATA` defaults to `/tmp/tl-stack/data`.
The original `inbox/IMG_2651.MOV` is streamed through its signed GET; a complete
original is never stored. Audio packets are discarded; no audio decoding,
energy analysis, suggestions or automatic dive detection exists.

The expensive B2 read + source-keyframe decoding + HDR→SDR tone mapping is
shared. A 1 fps, 270 px wide JPEG frame set is an intermediate derivative.
Then the same frames are packaged independently, with separate CPU/wall timers:

- `images/`: 160 px wide, whole portrait frames in 10×10 JPEG atlases + timestamp index.
- `video/search.mp4`: silent H.264 Main, yuv420p, 270 px wide, 1 fps, every frame key, faststart.
- `video/fast.mp4`: the same source frames at 30 fps, every frame key, silent H.264, faststart.
  It lasts about 64.6 seconds and plays at native rate 1, giving source speed ×30
  without relying on Safari supporting `playbackRate=30`.

Each variant's reported preparation = shared stage + its local packaging.
Video packaging includes both normal-search and accelerated MP4. Both variants
sample precisely the same source frames. This comparison avoids confounding two
B2 network runs and does not pretend the shared cost was measured twice.
`comparison.json` records all timing/CPU/size results. No data is committed.

## Modes (iPhone feedback v3)

Images is manual only: the existing instant atlas strip, marks and ◀/▶. No video
is attached or played on initial entry. Video uses exactly the same strip and
adds original playback with sound after release, plus ×30 / ×1. Marks are common.
The page uses plain JavaScript state, not React; state revision, DOM aria state,
requested mode, applied mode and trusted touch input are explicitly logged.

Commands accept touchend directly in the user gesture, prevent the synthesized
click, and retain click support for keyboard/mouse. Published mini assets enable
controls immediately; they never wait for loadeddata before allowing a gesture.
Safari had suppressed that preload event on the physical phone, leaving both
Video and ×30 disabled in v2.

The original has preload=auto and is attached once. The LAN server caches its
signed GET for 5h50 (signature lifetime 6h). A separate muted fast element keeps
the original's source/buffers intact during ×30. During a Video drag only, the HD
player runs muted at ×0.25 behind the atlas preview; keyframe fastSeek updates
are limited to one in-flight seek and at most one start per 650 ms. Release uses
fastSeek if needed, restores ×1/audio, and keeps the atlas visible until an actual
requestVideoFrameCallback near the target. Images mode never does that warm work.
The original remains paused on returning to Images, retaining its source.

×30 uses the 64.6 s native-rate H.264 file. ×1 restores the source timestamp in
the original. HEVC failures retain the H.264 fallback. The entire frame remains
visible in both orientations, with custom controls and no native iOS full screen.

## Measurements

Events go every 2 s and on pagehide to `/api/timeline/metrics`, stored at
`/tmp/tl-stack/metrics.jsonl`; GET that endpoint to retrieve the JSONL.
Each run has a UUID, user agent, preview variant and speed. Synthetic test runs
start `webkit-`; physical phone runs do not. No B2 capabilities/cookies/console
dumps are collected. A numerical field allowlist bounds metric payloads.

`python3 tools/timeline-proto/measurements.py --human-only` summarizes the iPhone
runs; `--json` returns machine-readable summaries. Metrics:

- `page_ready`: navigation clock to interactive custom player (before derivatives).
- `atlas_ready`, `mini_ready`: separate local asset download/decode readiness.
- `scrub_paint`: input to double requestAnimationFrame after image draw or mini seeked.
  A browser paint scheduling estimate, not physical touch-to-photon latency.
- `mini_seek_ready`: input to mini decoder seek completion.
- `resume_frame`, `release_to_frame`: actual video-frame callback after seek / release.
  `scroll_end_to_frame` separately includes settling after the last scroll input.
  Inertia and 180 ms settling are included in the latter.
- `control_input`, `mode_applied`, `control_state`, `speed_requested`,
  `speed_applied`: trusted event type, requested/applied state and DOM confirmation.
- `warm_seek`, `warm_hit`, `warm_play_*`: bounded warm work and decode readiness.
- `fast_frame`: successive actual frame callbacks during ×30; p50/p95 show fluidity.
  `fast_frames` / `fast_dropped` record browser playback quality counters.
- `hevc_fallback`, `media_error`, `play_rejected` record runtime limitations.

Physical iPhone test: start playback, sweep/fling each preview variant, release
at distant positions, switch ×30, mark dives while it runs, switch ×1, navigate
marks and rotate. Leave open briefly after the last interaction for upload.
Headless WebKit's iPhone profile validates engine/layout behavior on this Mac;
it cannot establish the physical iPhone's network, display, thermal or touch latency.

`check.cjs` runs WebKit iPhone behavior checks and Chromium Android fallback;
install Playwright under frontend/node_modules or set `TL_PLAYWRIGHT`.
The independent LAN server and Postgres process model derive from `/tmp/ss-stack`;
only the template was copied, never its running DB. Disposable Postgres is on 55435.
