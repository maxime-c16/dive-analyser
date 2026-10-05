import { afterEach, describe, expect, it, vi } from 'vitest';
import { clearIntentData, takeIntentData, warmIntentData } from './intentCache';

afterEach(() => { clearIntentData(); vi.useRealTimers(); });

describe('navigation data handoff', () => {
  it('shares an in-flight hover request, deduplicates repeated intent, and consumes once', async () => {
    let resolve!: (value: string) => void;
    const warm = vi.fn(() => new Promise<string>(r => { resolve = r; }));
    const normal = vi.fn().mockResolvedValue('fresh');
    warmIntentData('a', warm);
    warmIntentData('a', warm);
    const result = takeIntentData('a', normal);
    resolve('hover');
    expect(await result).toBe('hover');
    expect(warm).toHaveBeenCalledTimes(1);
    expect(normal).not.toHaveBeenCalled();
    expect(await takeIntentData('a', normal)).toBe('fresh');
  });

  it('expires unused responses after ten seconds', async () => {
    vi.useFakeTimers();
    warmIntentData('a', () => Promise.resolve('old'));
    vi.advanceTimersByTime(10_001);
    expect(await takeIntentData('a', () => Promise.resolve('new'))).toBe('new');
  });

  it('retries a speculative failure when navigation is already waiting', async () => {
    const retry = vi.fn().mockResolvedValue('recovered');
    warmIntentData('a', () => Promise.reject(new Error('offline')));
    expect(await takeIntentData('a', retry)).toBe('recovered');
    expect(retry).toHaveBeenCalledTimes(1);
  });

  it('does not hand off data after invalidation, even if an old request finishes late', async () => {
    let resolve!: (value: string) => void;
    warmIntentData('a', () => new Promise<string>(r => { resolve = r; }));
    clearIntentData();
    resolve('previous account');
    expect(await takeIntentData('a', () => Promise.resolve('new account'))).toBe('new account');
  });

  it('bounds abandoned intent to twelve entries', async () => {
    for (let i = 0; i < 13; i++) warmIntentData(String(i), () => Promise.resolve(i));
    expect(await takeIntentData('0', () => Promise.resolve(-1))).toBe(-1);
    expect(await takeIntentData('12', () => Promise.resolve(-1))).toBe(12);
  });
});
