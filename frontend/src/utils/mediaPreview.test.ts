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
