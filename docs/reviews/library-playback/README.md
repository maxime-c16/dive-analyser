# Library playback regression — 2026-10-08

## Reproduction and observed cause

The real authenticated Library was tested in the shared browser against production, then against a local Vite app using the same backend and videos. A clean checkout at f68454c was served separately for the before recording.

The status API preferred a cloud original even when a small local preview already existed. Original playback requires a redirect/grant (about 2–3 seconds in the captured requests). The viewer created a new native video element on each navigation. The existing fetch warmer deliberately skipped cloud redirects because the bucket does not allow readable cross-origin fetches. Poster warming therefore did not prepare the video decoder or its first frame.

One comparable navigation to dive 2911 presented its first frame after **3,237 ms before**, versus **140 ms after**; playback events were 3,296 ms versus 77 ms. The before capture also stalled around playback seconds 3.28 and 6.48. A prepared return to dive 2912 presented a frame in 56 ms. These are individual observations on this network, not percentile or cold-network guarantees.

The actual 1080p originals decoded video in the shared browser but reported no decoded audio bytes; the local AAC previews decoded audio normally. An intermediate fix repeatedly sought the AAC video to the HQ clock, interrupting its sound about four times per second. The final implementation leaves AAC playback continuous and gently adjusts only the muted HQ clock.

## Final behavior

- Prepare native preview elements for likely Library opens and a bounded navigation window.
- Start the available local preview while the selected original loads in the background.
- Present HQ only after contiguous full buffering and a matching decoded frame.
- Keep the AAC preview as the soundtrack; pause, seek, speed and mute controls operate across the two elements.
- Retain already presented HQ in the navigation window. A return reuses the same HQ element immediately.
- Allow the temporary release-before-acquire handoff of four idle entries; otherwise the cache could evict incoming HQ just before adoption.
- Abort obsolete media and pending work on authorization reset and window eviction.

A final real-library round trip, dive 2934 → 2926 → 2934, confirmed object identity of the returning 1080p HQ element, active unmuted AAC, and active muted HQ. The low-resolution soundtrack remains hidden. Retention is bounded to the nearby navigation window; distant clips can be evicted to limit browser decoder and media memory.

## Validation

- Frontend Vitest suite and production TypeScript/Vite build.
- Six Playwright WebKit cases: desktop and iPhone layout startup, automatic HQ transition, continuous AAC (no non-loop seeks during playback), pause/play/speed/mute, prepared next/previous startup, and retained HQ on return. The mobile return test exercises the feed drag.
- The fixture uses the actual ClipViewer and AuthProvider, including React StrictMode. HTTP media delivery includes real byte ranges and a deliberately delayed original redirect.
- Pool regression tests cover the four-entry release-before-acquire case, expiration, authorization cancellation and resource disposal.

WebKit automation covers its browser engine and mobile layout, not a physical installed iOS PWA. AAC event continuity detects the original chopped-audio mechanism; it is not an acoustic measurement.

Run the fixture against an already running Vite dev app:

```sh
cd frontend
npx playwright install webkit
PLAYBACK_PREVIEW_FILE=/absolute/path/aac-preview.mp4 \
PLAYBACK_ORIGINAL_FILE=/absolute/path/silent-h264-original.mov \
npx playwright test --config playwright.playback.config.ts
```

The default files live in ignored `.codex-playback-fixtures/`. No private media, authentication state, signed URL or dev proxy is committed. Use an AAC preview about 12 seconds long and 202×360, and a matching 1080×1920 H.264 original without audio. The silent original tests that the AAC soundtrack survives independently.

Recordings are stored in this T3 thread's attachments, outside git:

- Before: attachment ending `c8bf66ac-b989-4772-9205-55c25689c9d3-mp4.mp4`.
- Progressive playback after: `45a7e5a3-89c6-405b-bebc-e1e14a57318f-mp4.mp4`.
- Final retained-HQ round trip: `4114f6fb-21a6-40af-8cbd-6f2576a7e62b-mp4.mp4`.

Release note: `backend/release-notes/library-instant-hq-playback.json`; requires frontend deployment only, with no migration or worker change.
