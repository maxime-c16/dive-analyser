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
it('uses the original from the first frame even when a local 720p preview exists', async () => {
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
  expect(preview.playbackUrl).toBe('/api/v1/media/revisions/123/play')
  expect(preview.originalPlaybackUrl).toBe('/api/v1/media/revisions/123/play')
  expect(cachedPreview('hq')).toEqual(preview)
})
it('never starts on the 360p preview when only it and the B2 original exist', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({ ok: true, json: async () =>
    url.endsWith('/batch') ? { 'sd': { status: 'ready', playback_url: '/api/v1/media/revisions/9/play' } }
      : { status: 'ready', playback_url: '/api/v1/media/revisions/9/play', cache_entries: [
        { rendition: 'poster', playback_url: '/poster.jpg' },
        { rendition: 'proxy_360p', playback_url: '/small.mp4' },
      ] },
  })))
  const { getPreviewForPlayback } = await import('./mediaPreview')
  const pending = getPreviewForPlayback('sd')
  await vi.advanceTimersByTimeAsync(50)
  const preview = await pending
  expect(preview.playbackUrl).toBe('/api/v1/media/revisions/9/play')
  expect(preview.playbackUrl).not.toBe('/small.mp4')
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

it('starts the next account batch without waiting for an aborted stalled batch', async () => {
  let finishOld!: (response: unknown) => void
  const fetcher = vi.fn()
    .mockImplementationOnce(() => new Promise(resolve => { finishOld = resolve }))
    .mockResolvedValueOnce({ ok: true, json: async () => ({ same: { status: 'ready', playback_url: '/new-account.mp4' } }) })
  vi.stubGlobal('fetch', fetcher)
  const { getPreview, resetMediaPreviews, cachedPreview } = await import('./mediaPreview')
  const old = getPreview('same')
  await vi.advanceTimersByTimeAsync(50)
  const oldSignal = fetcher.mock.calls[0][1].signal as AbortSignal
  resetMediaPreviews()
  expect(oldSignal.aborted).toBe(true)
  // The mocked transport deliberately ignores abort and remains stalled.
  const fresh = getPreview('same')
  await vi.advanceTimersByTimeAsync(50)
  expect(fetcher).toHaveBeenCalledTimes(2)
  expect((await fresh).playbackUrl).toBe('/new-account.mp4')
  finishOld({ ok: true, json: async () => ({ same: { status: 'ready', playback_url: '/old-account.mp4' } }) })
  await vi.advanceTimersByTimeAsync(0)
  expect((await old).playbackUrl).toBeNull()
  expect(cachedPreview('same')?.playbackUrl).toBe('/new-account.mp4')
})

it('refreshes a missing result when media later becomes ready', async () => {
  const fetcher = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ late: { status: 'missing', playback_url: null } }) }).mockResolvedValueOnce({ ok: true, json: async () => ({ late: { status: 'ready', playback_url: '/original.mp4' } }) })
  vi.stubGlobal('fetch', fetcher)
  const { getPreview, cachedPreview } = await import('./mediaPreview')
  const first = getPreview('late'); await vi.advanceTimersByTimeAsync(50)
  expect((await first).ready).toBe(false)
  await vi.advanceTimersByTimeAsync(5001)
  expect(cachedPreview('late')).toBeUndefined()
  const next = getPreview('late'); await vi.advanceTimersByTimeAsync(50)
  expect((await next).playbackUrl).toBe('/original.mp4')
})
