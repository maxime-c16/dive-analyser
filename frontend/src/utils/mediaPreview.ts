import { getMediaStatus } from "../services/mediaApi";

export type MediaPreview = {
  posterUrl: string | null;
  videoThumbUrl: string | null;
  ready: boolean;
};

const previewCache = new Map<string, MediaPreview>();
const CREATED = { posterUrl: null, videoThumbUrl: null, ready: false } as const;

export function cachedPreview(videoUuid: string): MediaPreview | undefined {
  return previewCache.get(videoUuid);
}

const BATCH_FLUSH_MS = 50;
const BATCH_MAX = 100;

type PendingEntry = { videoUuid: string; resolve: (preview: MediaPreview) => void };
const batchQueue: PendingEntry[] = [];
const inFlight = new Map<string, Promise<MediaPreview>>();
let flushTimer: ReturnType<typeof setTimeout> | null = null;

export function getPreview(videoUuid: string): Promise<MediaPreview> {
  if (!videoUuid) return Promise.resolve({ ...CREATED });
  const cached = previewCache.get(videoUuid);
  if (cached) return Promise.resolve(cached);
  const alreadyRunning = inFlight.get(videoUuid);
  if (alreadyRunning) return alreadyRunning;

  const promise = new Promise<MediaPreview>((resolve) => {
    batchQueue.push({ videoUuid, resolve });
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
    // When no poster exists, use the playback URL so DiveThumbnail can
    // render a <video preload="metadata"> that shows the first frame.
    // The proxy URL never expires (backend generates a fresh presign each
    // time the browser hits it), so it's safe to cache indefinitely.
    videoThumbUrl: !status.poster_url && status.playback_url ? status.playback_url : null,
    ready: Boolean(status.playback_url),
  };
}

function settle(entry: PendingEntry, preview: MediaPreview) {
  previewCache.set(entry.videoUuid, preview);
  inFlight.delete(entry.videoUuid);
  entry.resolve(preview);
}

function scheduleFlush() {
  if (flushTimer !== null) return;
  flushTimer = setTimeout(() => {
    flushTimer = null;
    const entries = batchQueue.splice(0, batchQueue.length);
    if (entries.length === 0) return;
    for (const chunk of chunkOf(entries, BATCH_MAX)) {
      // Sequential chunks keep request pressure bounded; a grid bigger than
      // one batch fills in as each chunk lands.
      void flushChunk(chunk);
    }
  }, BATCH_FLUSH_MS);
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
    // Transport failure: fall back to the single-asset endpoint so the
    // grid still fills progressively instead of staying empty.
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
  await Promise.all(
    entries.map(async (entry) => {
      try {
        settle(entry, previewFromStatus(entry.videoUuid, await getMediaStatus(entry.videoUuid)));
      } catch {
        settle(entry, { ...CREATED });
      }
    }),
  );
}

function chunkOf<T>(list: T[], size: number): T[][] {
  const chunks: T[][] = [];
  for (let index = 0; index < list.length; index += size) {
    chunks.push(list.slice(index, index + size));
  }
  return chunks;
}
