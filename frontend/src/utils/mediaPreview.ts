import { getMediaStatus } from "../services/mediaApi";

export type MediaPreview = {
  posterUrl: string | null;
  videoThumbUrl: string | null;
  ready: boolean;
};

const previewCache = new Map<string, MediaPreview>();
const previewRequests = new Map<string, Promise<MediaPreview>>();

export function cachedPreview(videoUuid: string): MediaPreview | undefined {
  return previewCache.get(videoUuid);
}

export function getPreview(videoUuid: string): Promise<MediaPreview> {
  const cached = previewCache.get(videoUuid);
  if (cached) return Promise.resolve(cached);
  const inFlight = previewRequests.get(videoUuid);
  if (inFlight) return inFlight;
  const request = getMediaStatus(videoUuid)
    .then((status) => ({
      posterUrl: status.poster_url || null,
      // When no poster exists, use the playback URL so DiveThumbnail can
      // render a <video preload="metadata"> that shows the first frame.
      // The proxy URL never expires (backend generates a fresh presign each
      // time the browser hits it), so it's safe to cache indefinitely.
      videoThumbUrl: !status.poster_url && status.playback_url
        ? status.playback_url
        : null,
      ready: Boolean(status.playback_url),
    }))
    .catch(() => ({ posterUrl: null, videoThumbUrl: null, ready: false }))
    .then((result) => {
      previewCache.set(videoUuid, result);
      return result;
    })
    .finally(() => previewRequests.delete(videoUuid));
  previewRequests.set(videoUuid, request);
  return request;
}
