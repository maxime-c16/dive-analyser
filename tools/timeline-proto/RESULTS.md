# Physical-iPhone feedback and modes v3 — 2026-10-28

This section supersedes the original unified-player behavior recorded below.

The real iPhone run `1793217107064-0.9622401716331185` recorded 1,151 image scrub
samples, 4 Images-only variant events, one `mini_available`, **zero `mini_ready`**,
and no speed events. Video and ×30 were disabled pending `loadeddata`, an event
Safari did not produce during preload. It also had 3 rejected plays; old code
only used click for controls. Image scrubbing around 16–17 ms is preserved.

v3 uses direct trusted touchend handlers with synthesized-click suppression,
plus click support. Published asset readiness enables Video/×30 independently of
media preload events. Explicit JS state revisions, requested/applied mode,
DOM aria/button confirmation and play rejection names are recorded. This
standalone page has no React runtime; its actual state and DOM are measured.

- Images: same atlas paint and strip, manual marks and ◀/▶ only. No original
  attachment on initial entry; no video playback or warm-seek work in this mode.
- Video: same image strip; persistent original with preload=auto and sound after
  release. At most one warm seek is in flight, starts spaced at least 650 ms;
  Safari fastSeek is used when available. During drag only, original playback
  runs muted at ×0.25 behind the atlas to keep the decoder/network active.
- ×30 uses a separate silent element, retaining the original source and buffers.
  ×1 restores original playback/audio at the matching source timestamp.
- The server caches its 6-hour signature for 5h50. Repeated endpoint HEAD checks
  returned the same capability; the capability itself was never logged.
- The image overlay is hidden only after a matching, generation-fenced video
  frame callback. Actual release-to-frame includes settling/inertia, with media
  timestamp and target delta. Seeked is retained separately, not called latency.

WebKit iPhone profile, real B2, trusted `.tap()` control events: all mode/speed
state proofs were `ok`; manual Images made zero original requests; the whole
Images→Video→×30→×1→Images sequence attached the original exactly once. No page
errors. Landscape and common marks were checked. Touch hold retained the preview;
hidden warm playback was muted. These remain emulated checks, not a physical fix
confirmation until Maxime repeats the test.

Two final warm-release trials: **1,125 ms** and **3,159 ms** by actual frame
callbacks. Target/frame deltas were −0.003 s / −0.020 s. **The <1.5 s target is
not consistently achieved**. Cold mode entry was ~4.8–5.9 s; the ×1 return after
skipping ahead was ~4.5–7.7 s. The implementation retains the atlas throughout.
Final pure touch-scrub samples: Images p50 **15 ms**, p95 **74 ms** (52 samples);
Video p50 **22 ms**, p95 **42 ms** (26 samples). This Mac scheduling tail does
not replace the physical iPhone's excellent 16–17 ms baseline.

Next physical run: reload the same URL and confirm `build=iphone-modes-v3` in
metrics. Tap Video and ×30/×1, confirm applied states, scrub both modes, and compare
`release_to_frame` (not seeked), `warm_seek`, `warm_hit`, `play_rejected` and
`control_state`. `input=touchend`, `trusted=true` distinguishes real activation.

---

# Session timeline prototype — 2026-10-28

Final behavior: one custom inline player. Drag previews use either Images or
Vidéo; release resumes the original with sound. ×30 plays a muted accelerated
miniature; ×1 returns to the same source timestamp. Marks are explicit, common
to both speeds and persistent in localStorage. No audio computation or suggestions.

## Preparation on this Mac

Apple M2, 8 CPU cores. Original: 1,936.802 s, HEVC 10-bit HLG, 1920×1080 with
−90° container rotation, displayed as 1080×1920 portrait. Frames are tone mapped
to SDR, never cropped. The full original is streamed, never stored.

| Stage / variant | Wall time | Child CPU | Delivered media |
| --- | ---: | ---: | ---: |
| Shared B2 probe/read + 1 fps keyframe extraction | 1,107.695 s | 136.391 s | intermediate JPEG frames |
| Images packaging only | 1.119 s | 2.344 s | 20 atlases, 20,701,627 B |
| H.264 packaging only (both MP4s) | 3.609 s | 20.665 s | 46,032,087 B |
| Images from original | **18 min 28.814 s** | **138.736 s** | 160×284 useful portrait frames |
| Video from original | **18 min 31.304 s** | **157.056 s** | 270×480 portrait frames |

The extraction stage is measured once and shared, not counted twice in a
combined run. Each variant's total = shared extraction + its own packaging.
Both sample exactly the same 1,937 source frames. Packaging timings include
local disk reads. Peak child RSS: 296,419,328 B (282.7 MiB).
Exploratory/aborted runs before the final requirements are excluded.

- `search.mp4`: **36,058,193 B**, 1 fps, 1,937 s.
- `fast.mp4`: **9,973,894 B**, 30 fps, **64.567 s** (source ×30 at native playback rate 1).
- Both: H.264, every one of 1,937 packets is a keyframe, zero audio streams,
  yuv420p, `ftyp → moov → free → mdat`. Native-rate fast playback avoids Safari
  restrictions on `playbackRate=30`.
- Index JSON is about 15 KB per variant. Intermediate low-resolution JPEGs are
  disposable derivatives outside Git, not a copy of the original.

Read-only `ssh diveanalyzer-server lscpu`: Pentium 3550M @ 2.30 GHz, 2 cores /
2 threads. No workload was run there. Planning estimate at comparable B2
throughput: **20–40 minutes**, unbenchmarked. Mac CPU usage averaged only ~0.12
core during extraction; network waiting dominates. CPU model/core count alone
cannot establish a precise conversion, especially if server bandwidth differs.

## Browser evidence

Playwright headless WebKit with iPhone 13 profile, on this Mac, real B2 original
and full final derivatives. These are **not physical-iPhone measurements**.
All preview paint times are double-RAF browser scheduling estimates, not
physical touch-to-photon latency.

| Measurement | Images | Mini-video |
| --- | ---: | ---: |
| Scrub samples | 26 | 24 |
| Scrub p50 | 23 ms | 34 ms |
| Scrub p95 | 67 ms | 58 ms |
| Scrub max | 82 ms | 126 ms |
| Mini seek completion p50 / p95 | — | 4 / 29 ms |
| Release to real original frame | 3.698 s | 5.616 s |

Interactive page: 115 ms in this run; prepared-image download/decode: 314 ms;
mini download/decode readiness: 131 ms. Local Mac timings do not predict phone
Wi-Fi throughput. The original's loadeddata event separately measures its
network/decoder startup. Assets activate automatically after preparation.

×30, final touch-hold recheck: **296 actual frame callbacks** in 10 s; interval
p50 **33 ms**, p95 **50 ms**, max **68 ms**. Browser quality counters:
**309 frames / 2 dropped**. The preceding full run had 300 callbacks and 0 dropped;
release latencies were 2.883 / 4.382 s. Both runs are retained. Counters and
callback counts have different browser semantics; both are retained.

Validation passed: original + simple ruler before assets are available; automatic
activation of prepared controls; both preview variants; release to original;
only explicit marks in ◀/▶; marks during ×30; ×1 return at the same source time;
landscape layout; four marks preserved on reload. A 250 ms stationary touch hold explicitly verifies
that playback stays paused until real touchend, even after pointercancel. Chromium Pixel 7 profile with
an explicitly failed original verified real H.264 fallback, scrubbing, marks,
and ×30 through the actual local HTTP Range server. HEAD and 206 byte ranges
were checked. The fallback does not classify an ordinary buffering seek as a
codec failure.

## Recover the actual iPhone measurements

Stack left running: `http://192.168.1.151:8796/proto/timeline/1`, no login, LAN only.
Independent empty Postgres on 55435; no existing stack or production writes.

Test Safari: start playback, sweep/fling both preview choices, release at distant
positions, use ×30 and mark dives, return ×1, jump between marks and rotate.
Leave the page open briefly after the final gesture.

GET `http://192.168.1.151:8796/api/timeline/metrics` or read
`/tmp/tl-stack/metrics.jsonl`. Physical runs have no `webkit-` prefix; synthetic
ones do. Summarize with `python3 tools/timeline-proto/measurements.py --human-only`.
Preparation report: `/api/timeline/data/comparison.json`.

Limits: coarse 1-source-frame/s previews; original seek remains network/HEVC
bound; Images decodes roughly 336 MiB of pixels, whereas the H.264 preview keeps
a much smaller decoder working set. Image assets load only when that variant is
chosen. Physical iPhone latency, memory pressure and ×30 fluidity await Maxime's
test; no number above is presented as measured on his phone.
