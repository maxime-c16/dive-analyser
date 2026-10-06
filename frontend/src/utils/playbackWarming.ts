// Warming adjacent clip bytes for instant open/swipe.
//
// The first warmer used a page-lifetime budget of 12 URLs that never
// decreased and that posters counted against, so warming stopped after a
// handful of dives in a large feed. This version keeps a bounded, ROLLING
// window keyed to the current clip and the navigation direction: only a
// small neighbourhood ahead of (and behind, mirroring the travel
// direction) the viewer is prepared, irrelevant queued/running work is
// cancelled as the window slides, and failures retry with backoff and a
// per-lane cooldown instead of burning their slot or hammering a URL.
// Posters and playback bytes run in separate lanes with separately capped
// concurrency, so an image can never starve the video budget.
//
// Playback URLs are local media-cache responses with
// `Cache-Control: private, max-age=3600`, so a finished GET seeds the
// browser HTTP cache and the later `<video>` load for that clip resolves
// without a network wait. Status can instead return a B2 redirect (an
// explicit URL to Backblaze); those cross-origin URLs are NOT warmed —
// the bucket's intentionally absent CORS policy makes readable fetches
// fail there, and no-cors opaque responses cannot support the size
// checks below. B2-backed clips keep their player-driven streaming.
//
// The current clip is never freshly warmed: a speculative GET here would
// only race its own playback load, so the warmer merely lets an
// already-running preparation for it finish.
import { getPreview } from "./mediaPreview";
import { canPrefetch } from "../hooks/useNavigationIntent";

export type WarmDirection = -1 | 0 | 1;
type WarmKind = "video" | "poster";
type WarmState = "queued" | "running" | "landed" | "failed";

type WarmJob = {
  kind: WarmKind;
  videoUuid: string;
  url: string | null;
  state: WarmState;
  // Lower is more urgent; re-ranked against the live window on every update.
  rank: number;
  retries: number;
  // Set on every cancel/evict/reset path. Async continuations consult this
  // (never the map alone: a same-key successor may exist) and stand down.
  cancelled: boolean;
  // Deduplicated in-flight status lookup; retried with bounded backoff.
  preview: Promise<void> | null;
  previewRetries: number;
  controller: AbortController | null;
  timer: ReturnType<typeof setTimeout> | null;
};

const MAX_CONCURRENT = 2;
const MAX_RETRIES = 2;
const INITIAL_RETRY_DELAY_MS = 1000;
// After retries exhaust, the lane waits this long before a fresh bounded
// burst may start — repeated window updates cannot restart an
// unbounded hammering cycle on a struggling lane.
const RETRY_COOLDOWN_MS = 20_000;
// Bounded memory: warms are pulled in chunks and dropped once a file exceeds
// the cap (a warmer must never buffer an original rendition into RAM). Files
// above the cap still never enter the browser HTTP cache wholesale, so the
// late `<video>` load just streams them the simple way.
const MAX_WARM_BYTES = 3 * 1024 * 1024;
// Posters are tiny; the cap only pins the runaway case (never an original).
const MAX_POSTER_BYTES = 512 * 1024;
// Rolling neighbourhood, symmetric around the travel direction: two clips
// ahead in the swipe direction, the opposite neighbor, then the far clip in
// the travel direction. Bounded, so a long session never schedules the
// whole library.
const WINDOW_OFFSETS: Record<"forward" | "reverse", number[]> = {
  forward: [1, 2, -1, 3],
  reverse: [-1, -2, 1, -3],
};
// Landed-tracking bound per kind: once completed warms exceed this many,
// they stop being tracked. The browser HTTP cache keeps the bytes itself;
// bounding this tracker bounds the warmer's own retained bookkeeping, which
// is what would otherwise grow unbounded during a long session.
const MAX_LANDED = 8;

const jobs = new Map<string, WarmJob>();
// Lane key → cooldown expiry timestamp, after exhausted retries.
const laneCooldown = new Map<string, number>();
let windowUuids = new Set<string>();

const jobKey = (kind: WarmKind, videoUuid: string) => `${kind}:${videoUuid}`;
const inCooldown = (key: string) => (laneCooldown.get(key) ?? 0) > Date.now();

function outsideWindow(videoUuid: string): boolean {
  return !windowUuids.has(videoUuid);
}

function dropJob(job: WarmJob) {
  if (job.cancelled) return;
  job.cancelled = true;
  if (job.timer !== null) {
    clearTimeout(job.timer);
    job.timer = null;
  }
  if (job.controller !== null) {
    job.controller.abort();
    job.controller = null;
  }
  // Identity-checked: never delete a same-key successor.
  if (jobs.get(jobKey(job.kind, job.videoUuid)) === job) {
    jobs.delete(jobKey(job.kind, job.videoUuid));
  }
}

function markLanded(job: WarmJob) {
  if (job.cancelled || jobs.get(jobKey(job.kind, job.videoUuid)) !== job) return;
  job.state = "landed";
  job.controller = null;
  job.rank = 0;
}

// Completed warms beyond MAX_LANDED per kind leave the tracking map (the
// bytes stay in the browser HTTP cache; only bookkeeping is bounded here).
function evictSpentLanded() {
  const landed = [...jobs.values()]
    .filter((job) => job.state === "landed")
    .sort((a, b) => b.rank - a.rank);
  while (landed.length > MAX_LANDED) dropJob(landed.pop()!);
}

// A failed warm becomes retryable unless the server decided the request is
// wrong (statuses a retry cannot fix). Oversized originals play out as 413
// and are treated the same way: never re-requested.
function isRetryableStatus(status: number): boolean {
  return status >= 500 || status === 429;
}

class StatusError extends Error {
  constructor(readonly status: number) {
    super(`warm failed: ${status}`);
  }
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

// Content-Length pins the extreme case: abort before buffering anything.
// The streaming cap then catches responses that lie or grow while reading.
// Content-Length pins the extreme case: abort before buffering anything.
// The streaming cap then catches responses that lie or grow while reading.
// Only local media-cache URLs are warmed: a status can return a revision
// route (`/api/v1/media/revisions/...`) that 302s to B2, where the
// bucket's intentionally absent CORS policy (see
// docs/architecture/EXTERNAL_ACCESS_V1.md) makes readable fetches fail.
// No-cors opaque responses cannot support the size checks, so such clips
// are left to the player's own <video> streaming instead of being warmed.
function isWarmableUrl(url: string): boolean {
  try {
    const parsed = new URL(url, window.location.href);
    return (
      parsed.origin === window.location.origin &&
      parsed.pathname.startsWith("/api/v1/media/cache/")
    );
  } catch {
    return false;
  }
}

async function drain(url: string, signal: AbortSignal, kind: WarmKind): Promise<void> {
  const cap = kind === "video" ? MAX_WARM_BYTES : MAX_POSTER_BYTES;
  const response = await fetch(url, {
    priority: "low" as RequestPriority,
    signal,
  });
  if (!response.ok || !response.body) {
    throw new StatusError(response.status);
  }
  const declared = Number(response.headers.get("Content-Length") ?? "");
  const reader = response.body.getReader();
  if (declared > cap) {
    // Abort the new fetch stream itself; skipping without cancel would
    // leave the transfer draining network in the background.
    await reader.cancel();
    throw new StatusError(413);
  }
  let received = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) return;
    received += value.byteLength;
    if (received > cap) {
      await reader.cancel();
      throw new StatusError(413);
    }
  }
}

// The one error path: aborted/evicted jobs stand down silently; permanent
// statuses are abandoned; anything else retries with backoff until
// MAX_RETRIES and then parks the lane on cooldown. Identity checks happen
// before every mutation, after every await.
function settleFailure(job: WarmJob, error: unknown) {
  if (job.cancelled || jobs.get(jobKey(job.kind, job.videoUuid)) !== job) return;
  if (isAbort(error) || outsideWindow(job.videoUuid)) {
    dropJob(job);
    return;
  }
  const status = error instanceof StatusError ? error.status : null;
  if (status !== null && !isRetryableStatus(status)) {
    dropJob(job);
    return;
  }
  job.retries += 1;
  if (job.retries > MAX_RETRIES) {
    laneCooldown.set(jobKey(job.kind, job.videoUuid), Date.now() + RETRY_COOLDOWN_MS);
    dropJob(job);
    return;
  }
  job.state = "failed";
  const delay = INITIAL_RETRY_DELAY_MS * 2 ** (job.retries - 1);
  job.timer = setTimeout(() => {
    job.timer = null;
    if (job.cancelled || outsideWindow(job.videoUuid)) {
      dropJob(job);
      return;
    }
    job.state = "queued";
    pump();
  }, delay);
}

async function runJob(job: WarmJob) {
  const { url, kind } = job;
  const controller = job.controller;
  if (!url || !controller || job.cancelled) {
    refresh();
    return;
  }
  job.state = "running";
  try {
    await drain(url, controller.signal, kind);
    markLanded(job);
  } catch (error) {
    settleFailure(job, error);
  }
  // Occupancy is recomputed from the live map, so a cancelled job can never
  // leave a zombie slot that freezes the lane.
  refresh();
}

function nextQueued(kind: WarmKind): WarmJob | undefined {
  return [...jobs.values()]
    .filter((job) => job.kind === kind && job.state === "queued" && job.url !== null)
    .sort((a, b) => a.rank - b.rank)[0];
}

function pump() {
  for (const kind of ["video", "poster"] as const) {
    for (;;) {
      let running = 0;
      for (const job of jobs.values()) {
        if (job.kind === kind && job.state === "running" && !job.cancelled) running += 1;
      }
      if (running >= MAX_CONCURRENT) break;
      const job = nextQueued(kind);
      if (!job || !canPrefetch()) break;
      if (outsideWindow(job.videoUuid)) {
        dropJob(job);
        continue;
      }
      job.controller = new AbortController();
      job.state = "running";
      void runJob(job);
    }
  }
}

// Ask the shared preview cache for what this lane can prepare; B2 redirect
// URLs are recognised and skipped (no readable-fetch race against a bucket
// without CORS). Lookups are deduplicated per job (repeated window updates
// must not re-enter one) and retried on rejection with bounded backoff. A
// batch resolution that still leaves the lane without a URL is retried the
// same way, until the bound declares the clip unservable right now.
function resolvePreview(job: WarmJob) {
  if (job.cancelled || job.preview) return;
  job.preview = getPreview(job.videoUuid)
    .then((preview) => {
      job.preview = null;
      if (job.cancelled || jobs.get(jobKey(job.kind, job.videoUuid)) !== job) return;
      if (outsideWindow(job.videoUuid)) {
        dropJob(job);
        return;
      }
      const url = job.kind === "video" ? preview.playbackUrl : preview.posterUrl;
      if (!url) {
        // Nothing this lane can prepare for this clip — unless the empty
        // preview itself came from a failed status round-trip, which
        // mediaPreview swallows into placeholders. Those get the same
        // bounded retry as a rejected lookup instead of a silent skip;
        // genuinely missing assets exhaust the bound and drop.
        resolvePreviewFailure(job);
        return;
      }
      job.url = url;
      job.state = "queued";
      job.previewRetries = 0;
      if (!isWarmableUrl(url)) {
        // B2-backed (cross-origin) rendition: the readable request path
        // this warmer needs cannot succeed there (bucket CORS is
        // intentionally absent), so leave the bytes to the player.
        dropJob(job);
        return;
      }
      pump();
    })
    .catch(() => {
      job.preview = null;
      resolvePreviewFailure(job);
    });
}

function resolvePreviewFailure(job: WarmJob) {
  if (job.cancelled || jobs.get(jobKey(job.kind, job.videoUuid)) !== job) return;
  job.previewRetries += 1;
  if (job.previewRetries > MAX_RETRIES) {
    laneCooldown.set(jobKey(job.kind, job.videoUuid), Date.now() + RETRY_COOLDOWN_MS);
    dropJob(job);
    return;
  }
  const delay = INITIAL_RETRY_DELAY_MS * 2 ** (job.previewRetries - 1);
  job.timer = setTimeout(() => {
    job.timer = null;
    if (job.cancelled || outsideWindow(job.videoUuid)) {
      dropJob(job);
      return;
    }
    resolvePreview(job);
  }, delay);
}

function upsertJob(kind: WarmKind, videoUuid: string, rank: number): WarmJob {
  const key = jobKey(kind, videoUuid);
  const existing = jobs.get(key);
  if (existing && !existing.cancelled) {
    existing.rank = rank;
    return existing;
  }
  const job: WarmJob = {
    kind,
    videoUuid,
    url: null,
    state: "queued",
    rank,
    retries: 0,
    cancelled: false,
    preview: null,
    previewRetries: 0,
    controller: null,
    timer: null,
  };
  jobs.set(key, job);
  return job;
}

function enqueueClip(videoUuid: string, rank: number, isCurrent: boolean) {
  for (const kind of ["video", "poster"] as const) {
    const key = jobKey(kind, videoUuid);
    if (inCooldown(key)) continue; // wait out the exhausted-retry cooldown
    const existing = jobs.get(key);
    if (existing && !existing.cancelled) {
      // Already queued/running/landed/failed-retrying: just re-rank it.
      existing.rank = rank;
      continue;
    }
    if (isCurrent) continue; // never freshly warm the live clip
    resolvePreview(upsertJob(kind, videoUuid, rank));
  }
}

// Called after every window recomputation: prune, enqueue, re-rank, restart.
function refresh() {
  pruneCooldowns();
  evictSpentLanded();
  pump();
}

// Bound the cooldown bookkeeping itself: an expired entry only ever means
// "may retry now", never "remembered forever".
function pruneCooldowns() {
  for (const [key, expiry] of [...laneCooldown]) {
    if (expiry <= Date.now()) laneCooldown.delete(key);
  }
}

/**
 * Keep a bounded rolling neighbourhood of clips prepared for instant
 * open/swipe. Call whenever the viewer moves: `direction` is the swipe that
 * landed here (`0` on first open), and the window slides with it, holding
 * the next clips ahead and the previous clip behind. Cancels queued or
 * active warm work that fell out of the window, without interrupting the
 * live player.
 */
export function warmAdjacentClips(args: {
  attempts: ReadonlyArray<{ video_uuid?: string | null }>;
  index: number;
  direction?: WarmDirection;
}): void {
  const { attempts, index, direction = 0 } = args;
  const desired = new Set<string>();
  const uuids: Array<{ uuid: string; rank: number; current: boolean }> = [];
  if (index < 0 || index >= attempts.length) {
    recomputeWindow(desired, uuids);
    return;
  }
  const offsets = WINDOW_OFFSETS[direction < 0 ? "reverse" : "forward"];
  offsets.forEach((offset, rank) => {
    const uuid = attempts[index + offset]?.video_uuid;
    if (!uuid || desired.has(uuid)) return;
    desired.add(uuid);
    uuids.push({ uuid, rank, current: false });
  });
  const here = attempts[index]?.video_uuid;
  if (here && !desired.has(here)) {
    desired.add(here);
    uuids.push({ uuid: here, rank: uuids.length, current: true });
  }
  recomputeWindow(desired, uuids);
}

function recomputeWindow(
  desired: Set<string>,
  uuids: Array<{ uuid: string; rank: number; current: boolean }>,
) {
  windowUuids = desired;
  for (const job of [...jobs.values()]) {
    if (desired.has(job.videoUuid)) continue;
    // Queued/in-flight/retrying work is cancelled outright; spent landed
    // and abandoned-failed entries leave the tracking map the same way.
    dropJob(job);
  }
  for (const { uuid, rank, current } of uuids) enqueueClip(uuid, rank, current);
  refresh();
}

/**
 * Forget every warm: abort in-flight transfers, clear timers and cooldowns.
 * Call on sign-out so torn-down authorization leaves no runaway downloads
 * behind; a future session starts its attempts anew.
 */
export function resetPlaybackWarming(): void {
  for (const job of [...jobs.values()]) dropJob(job);
  laneCooldown.clear();
  windowUuids = new Set();
}
