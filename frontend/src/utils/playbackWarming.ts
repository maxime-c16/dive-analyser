// Warming adjacent clip bytes for instant open/swipe.
//
// Playback URLs are local media-cache responses with
// `Cache-Control: private, max-age=3600`, so a finished GET seeds the
// browser HTTP cache and the later `<video>` load for that clip resolves
// without a network wait. Envelope sizes on the live dataset are small
// (median proxy ~0.6 MiB), so full fetch is cheap next to the latency tax
// it removes from every swipe.
import { getPreview } from "./mediaPreview";
import { canPrefetch } from "../hooks/useNavigationIntent";

const MAX_CONCURRENT = 2;
const MAX_WARMUPS = 12;
// Bounded memory: warms are pulled in chunks and dropped once a file exceeds
// the cap (a warmer must never buffer an original rendition into RAM). Files
// above the cap still never enter the browser HTTP cache wholesale, so the
// late `<video>` load just streams them the simple way.
const MAX_WARM_BYTES = 3 * 1024 * 1024;

let active = 0;
let scheduled = 0;
const queue: Array<() => void> = [];
const started = new Set<string>();

function pump() {
  while (active < MAX_CONCURRENT && queue.length) {
    const run = queue.shift()!;
    active += 1;
    void run();
  }
}

async function drain(url: string) {
  try {
    const response = await fetch(url, { priority: "low" as RequestPriority });
    if (!response.ok || !response.body) return;
    // Content-Length pins the extreme case: abort before buffering anything.
    const declared = Number(response.headers.get("Content-Length") ?? "");
    const reader = response.body.getReader();
    if (declared > MAX_WARM_BYTES) {
      // Abort the new fetch stream itself; skipping without cancel would
      // leave the transfer draining network in the background.
      await reader.cancel();
      return;
    }

    let received = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) return;
      received += value.byteLength;
      if (received > MAX_WARM_BYTES) {
        await reader.cancel();
        return;
      }
    }
  } catch {
    // Warming is opportunistic; a failure must never surface.
  } finally {
    active -= 1;
    pump();
  }
}

export function warmPlaybackBytes(url: string | null | undefined): void {
  if (!url || !canPrefetch() || started.has(url)) return;
  if (scheduled >= MAX_WARMUPS) return;
  started.add(url);
  scheduled += 1;
  queue.push(() => drain(url));
  pump();
}

/**
 * Status-warm the clip's neighbors and byte-warm their ready renditions.
 * Call when the viewer swaps to a new attempt: neighbors become ready from
 * their status lookup while playback bytes continue in the background, so
 * the next swipe meets an already-full HTTP cache.
 */
export function warmAdjacentClips(videoUuids: Array<string | null | undefined>): void {
  for (const videoUuid of videoUuids) {
    if (!videoUuid) continue;
    void getPreview(videoUuid).then((preview) => {
      warmPlaybackBytes(preview.posterUrl);
      warmPlaybackBytes(preview.playbackUrl);
    });
  }
}
