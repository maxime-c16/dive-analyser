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
| Scrub p50 | 19 ms | 33 ms |
| Scrub p95 | 64 ms | 51 ms |
| Scrub max | 84 ms | 133 ms |
| Mini seek completion p50 / p95 | — | 5 / 30 ms |
| Release to real original frame | 2.883 s | 4.382 s |

Interactive page: 76 ms in this run; prepared-image download/decode: 277 ms;
mini download/decode readiness: 170 ms. Local Mac timings do not predict phone
Wi-Fi throughput. The original's loadeddata event separately measures its
network/decoder startup. Assets activate automatically after preparation.

×30: **300 actual frame callbacks** in 10 s; interval p50 **33 ms**, p95 **50 ms**,
max **51 ms**. Browser quality counters: **309 frames / 0 dropped**. Counters and
callback counts have different browser semantics; both are retained.

Validation passed: original + simple ruler before assets are available; automatic
activation of prepared controls; both preview variants; release to original;
only explicit marks in ◀/▶; marks during ×30; ×1 return at the same source time;
landscape layout; four marks preserved on reload. Chromium Pixel 7 profile with
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
