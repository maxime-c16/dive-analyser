import { afterEach, describe, expect, it, vi } from 'vitest';
import { clearLibraryCache, libraryKey, loadLibraryCache, readLibraryCache } from './libraryCache';
import type { AuthUser } from '../contexts/AuthContext';
const user = { user_id: 1, role: 'owner', is_admin: true, divers: [{ diver_id: 1, access_kind: 'OWNER' }] } as AuthUser;
const key = libraryKey(user)!;
const data = { dives: [], divers: [] };
afterEach(() => { clearLibraryCache(); vi.useRealTimers(); vi.restoreAllMocks(); });

describe('Library cache', () => {
  it('deduplicates initial loads and returns fresh data without another request', async () => {
    const load = vi.fn().mockResolvedValue(data);
    const first = loadLibraryCache(key, load);
    expect(loadLibraryCache(key, load)).toBe(first);
    await first;
    await loadLibraryCache(key, load);
    expect(load).toHaveBeenCalledTimes(1);
    expect(readLibraryCache(key)?.dives).toEqual([]);
  });
  it('hydrates a saved snapshot after a reload', () => {
    localStorage.setItem('dive-library-v1', JSON.stringify({ key, snapshot: { ...data, savedAt: Date.now() } }));
    expect(readLibraryCache(key)).toEqual({ ...data, savedAt: expect.any(Number) });
  });
  it('keeps stale data available while refreshing after one minute', async () => {
    vi.useFakeTimers();
    await loadLibraryCache(key, () => Promise.resolve(data));
    vi.advanceTimersByTime(60_001);
    expect(readLibraryCache(key)).not.toBeNull();
    const load = vi.fn().mockResolvedValue(data);
    await loadLibraryCache(key, load);
    expect(load).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(24 * 60 * 60_000);
    expect(readLibraryCache(key)).toBeNull();
  });
  it('discards data after account or access changes', async () => {
    await loadLibraryCache(key, () => Promise.resolve(data));
    expect(readLibraryCache(libraryKey({ ...user, divers: [] }))).toBeNull();
    expect(localStorage.getItem('dive-library-v1')).toBeNull();
  });
  it('does not repopulate storage with an old in-flight request after invalidation', async () => {
    let resolve!: (value: typeof data) => void;
    const request = loadLibraryCache(key, () => new Promise(r => { resolve = r; }));
    clearLibraryCache();
    resolve(data);
    await request;
    expect(readLibraryCache(key)).toBeNull();
  });
  it('works in memory when storage quota is exhausted', async () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('quota'); });
    await loadLibraryCache(key, () => Promise.resolve(data));
    expect(readLibraryCache(key)).not.toBeNull();
  });
  it('rejects structurally invalid saved attempts before they can render', () => {
    localStorage.setItem('dive-library-v1', JSON.stringify({ key,
      snapshot: { dives: [{ id: 1 }], divers: [], savedAt: Date.now() } }));
    expect(readLibraryCache(key)).toBeNull();
  });
  it('ignores corrupt saved data', () => {
    localStorage.setItem('dive-library-v1', '{bad');
    expect(readLibraryCache(key)).toBeNull();
  });
});
