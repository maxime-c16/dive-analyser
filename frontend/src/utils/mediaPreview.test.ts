import { afterEach, beforeEach, expect, it, vi } from 'vitest';
beforeEach(() => { vi.resetModules(); vi.useFakeTimers(); });
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });
it('serializes batches of at most 100 even as more tiles enter view', async () => {
  const resolvers: Array<(value: unknown) => void> = [];
  const fetcher = vi.fn((_url: string, _options: { body: string }) => new Promise(resolve => resolvers.push(resolve)));
  vi.stubGlobal('fetch', fetcher);
  const { getPreview } = await import('./mediaPreview');
  const previews = Array.from({ length: 205 }, (_, i) => getPreview(`uuid-${i}`));
  await vi.advanceTimersByTimeAsync(50);
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(JSON.parse(fetcher.mock.calls[0][1].body).video_uuids).toHaveLength(100);
  for (let i = 0; i < 3; i++) {
    resolvers[i]({ ok: true, json: async () => ({}) });
    await vi.advanceTimersByTimeAsync(0);
    expect(fetcher).toHaveBeenCalledTimes(Math.min(i + 2, 3));
  }
  await Promise.all(previews);
});
it('does not fan a failed batch out into individual media requests or cache a failure', async () => {
  const fetcher = vi.fn().mockResolvedValue({ ok: false, status: 503 });
  vi.stubGlobal('fetch', fetcher);
  const { getPreview, cachedPreview } = await import('./mediaPreview');
  const previews = Array.from({ length: 48 }, (_, i) => getPreview(`uuid-${i}`));
  await vi.advanceTimersByTimeAsync(50);
  await Promise.all(previews);
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(cachedPreview('uuid-0')).toBeUndefined();
});
it('keeps the playback URL alongside the poster so instant open can seed it', async () => {
  const fetcher = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({
      'uuid-a': { status: 'ready', poster_url: '/poster.jpg', playback_url: '/play' },
      'uuid-b': { status: 'ready', poster_url: null, playback_url: '/play2' },
    }),
  });
  vi.stubGlobal('fetch', fetcher);
  const { getPreview, cachedPreview } = await import('./mediaPreview');
  const batch = Promise.all([getPreview('uuid-a'), getPreview('uuid-b')]);
  await vi.advanceTimersByTimeAsync(50);
  const [withPoster, withoutPoster] = await batch;
  expect(withPoster.playbackUrl).toBe('/play');
  expect(withPoster.ready).toBe(true);
  expect(withoutPoster.playbackUrl).toBe('/play2');
  expect(cachedPreview('uuid-a')!.playbackUrl).toBe('/play');
});
it('resolves the ready local startup preview while retaining the original for HQ', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({ ok: true, json: async () =>
    url.endsWith('/batch') ? { 'hq': { status: 'ready', playback_url: '/api/v1/media/revisions/123/play' } }
      : { status: 'ready', playback_url: '/api/v1/media/revisions/123/play', cache_entries: [
        { rendition: 'poster', playback_url: '/poster.jpg' },
        { rendition: 'proxy_360p', playback_url: '/small.mp4' },
        { rendition: 'proxy_720p', playback_url: '/hq-preview.mp4' },
      ] },
  })))
  const { getPreviewForPlayback, cachedPreview } = await import('./mediaPreview')
  const pending = getPreviewForPlayback('hq')
  await vi.advanceTimersByTimeAsync(50)
  const preview = await pending
  expect(preview.playbackUrl).toBe('/hq-preview.mp4')
  expect(preview.originalPlaybackUrl).toBe('/api/v1/media/revisions/123/play')
  expect(cachedPreview('hq')).toEqual(preview)
})
it('does not let a pre-logout status response repopulate the next account cache', async () => {
  let resolve!: (response: unknown) => void
  vi.stubGlobal('fetch', vi.fn(() => new Promise(done => { resolve = done })))
  const { getPreview, cachedPreview, resetMediaPreviews } = await import('./mediaPreview')
  const old = getPreview('private')
  await vi.advanceTimersByTimeAsync(50)
  resetMediaPreviews()
  resolve({ ok: true, json: async () => ({ private: { status: 'ready', playback_url: '/private.mp4' } }) })
  await vi.advanceTimersByTimeAsync(0)
  expect((await old).playbackUrl).toBeNull()
  expect(cachedPreview('private')).toBeUndefined()
})
