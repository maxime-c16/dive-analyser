import { getMediaStatus, getPlaybackUrlFromStatus } from '../services/mediaApi'

export type MediaPreview = {
  posterUrl: string | null;
  videoThumbUrl: string | null;
  playbackUrl: string | null;
  ready: boolean;
  originalPlaybackUrl?: string | null;
};

const previewCache = new Map<string, MediaPreview>();
let previewGeneration = 0;
const CREATED = { posterUrl: null, videoThumbUrl: null, playbackUrl: null, ready: false } as const;

export function cachedPreview(videoUuid: string): MediaPreview | undefined {
  return previewCache.get(videoUuid);
}

const BATCH_FLUSH_MS = 50;
const BATCH_MAX = 100;

type PendingEntry = { generation: number; videoUuid: string; resolve: (preview: MediaPreview) => void };
const batchQueue: PendingEntry[] = [];
const inFlight = new Map<string, Promise<MediaPreview>>();
let flushing = false;
let flushTimer: ReturnType<typeof setTimeout> | null = null;

export function getPreview(videoUuid: string): Promise<MediaPreview> {
  if (!videoUuid) return Promise.resolve({ ...CREATED });
  const cached = previewCache.get(videoUuid);
  if (cached) return Promise.resolve(cached);
  const alreadyRunning = inFlight.get(videoUuid);
  if (alreadyRunning) return alreadyRunning;

  const promise = new Promise<MediaPreview>((resolve) => {
    batchQueue.push({ generation: previewGeneration, videoUuid, resolve });
  });
  inFlight.set(videoUuid, promise);
  scheduleFlush();
  return promise;
}

type StatusShape = {
  poster_url?: string | null
  playback_url?: string | null
  status: string
};

function previewFromStatus(videoUuid: string, status: StatusShape | undefined): MediaPreview {
  if (!status) {
    return { ...CREATED };
  }
  return {
    posterUrl: status.poster_url || null,
    // Keep playback availability for the viewer; Library tiles use posters only.
    // playbackUrl is retained separately so instant open/swipe can seed the
    // player without waiting for its own status round-trip.
    videoThumbUrl: !status.poster_url && status.playback_url ? status.playback_url : null,
    playbackUrl: status.playback_url || null,
    ready: Boolean(status.playback_url),
  };
}

function settle(entry: PendingEntry, preview: MediaPreview) {
  if (entry.generation !== previewGeneration) { entry.resolve({ ...CREATED }); return; }
  previewCache.set(entry.videoUuid, preview);
  inFlight.delete(entry.videoUuid);
  entry.resolve(preview);
}

function scheduleFlush() {
  if (flushTimer !== null || flushing) return;
  flushTimer = setTimeout(() => {
    flushTimer = null;
    void drainQueue();
  }, BATCH_FLUSH_MS);
}

async function drainQueue() {
  flushing = true;
  try {
    while (batchQueue.length) {
      await flushChunk(batchQueue.splice(0, BATCH_MAX));
    }
  } finally {
    flushing = false;
  }
}

async function flushChunk(entries: PendingEntry[]): Promise<void> {
  let payload: Record<string, StatusShape> | null = null;
  try {
    const response = await fetch("/api/v1/media/status/batch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ video_uuids: entries.map(({ videoUuid }) => videoUuid) }),
    });
    if (!response.ok) throw new Error(`media status batch failed: ${response.status}`);
    payload = (await response.json()) as Record<string, StatusShape>;
  } catch {
    // Keep placeholders on transport failure. Never fan a failed batch
    // out into up to 100 individual requests against an overloaded server.
  }
  if (payload !== null) {
    // The backend answers for every requested uuid; unknown assets report
    // "missing", matching a failed single lookup (also cached, same as the
    // pre-batch behavior so absent renders never stutter).
    for (const entry of entries) {
      settle(entry, previewFromStatus(entry.videoUuid, payload[entry.videoUuid]));
    }
    return;
  }
  for (const entry of entries) {
    if (entry.generation === previewGeneration) inFlight.delete(entry.videoUuid);
    entry.resolve({ ...CREATED });
  }
}

// Only the bounded playback window needs this extra lookup. Thumbnail
// batches stay cheap; they deliberately omit cache-entry details. Resolve
// an existing local preview instead of streaming a large cloud original.
const playbackLookups = new Map<string, Promise<MediaPreview>>()
export function getPreviewForPlayback(videoUuid: string): Promise<MediaPreview> {
  const pending = playbackLookups.get(videoUuid)
  if (pending) return pending
  const epoch = previewGeneration
  const lookup = getPreview(videoUuid).then(async preview => {
    if (!preview.playbackUrl?.includes('/media/revisions/')) return preview
    try {
      const status = await getMediaStatus(videoUuid)
      const playbackUrl = getPlaybackUrlFromStatus(status, true)
      const result = { ...preview, playbackUrl, originalPlaybackUrl: status.playback_url, ready: Boolean(playbackUrl) }
      if (epoch === previewGeneration) previewCache.set(videoUuid, result)
      return result
    } catch {
      return preview
    }
  }).finally(() => { if (playbackLookups.get(videoUuid) === lookup) playbackLookups.delete(videoUuid) })
  playbackLookups.set(videoUuid, lookup)
  return lookup
}

export function resetMediaPreviews() {
  previewGeneration++
  previewCache.clear()
  inFlight.clear()
  playbackLookups.clear()
  if (flushTimer !== null) clearTimeout(flushTimer)
  flushTimer = null
  for (const entry of batchQueue.splice(0)) entry.resolve({ ...CREATED })
}
