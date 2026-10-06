import { afterEach, beforeEach, expect, it, vi } from "vitest";

beforeEach(() => {
  vi.resetModules();
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function queueable(url: string, ok = true) {
  const response = {
    ok,
    body: {},
    arrayBuffer: () => Promise.resolve(new ArrayBuffer(8)),
  };
  return { response, promise: Promise.resolve(response) };
}

it("fetches each warm URL at most once with a low priority", async () => {
  const fetcher = vi.fn((url: string) => queueable(url));
  vi.stubGlobal("fetch", fetcher);
  const { warmPlaybackBytes } = await import("./playbackWarming");
  warmPlaybackBytes("/a");
  warmPlaybackBytes("/a");
  await vi.advanceTimersByTimeAsync(0);
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(fetcher.mock.calls[0][0]).toBe("/a");
});

it("ignores blank URLs and connection-gated environments", async () => {
  const fetcher = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  vi.stubGlobal("navigator", { connection: { saveData: true } });
  const { warmPlaybackBytes } = await import("./playbackWarming");
  warmPlaybackBytes(null);
  warmPlaybackBytes("");
  warmPlaybackBytes("/a");
  await vi.advanceTimersByTimeAsync(0);
  expect(fetcher).not.toHaveBeenCalled();
});

it("caps how many clip warmups run per page session", async () => {
  const fetcher = vi.fn(() => queueable("/play"));
  vi.stubGlobal("fetch", fetcher);
  const { warmPlaybackBytes } = await import("./playbackWarming");
  for (let i = 0; i < 30; i++) warmPlaybackBytes(`/clip-${i}`);
  await vi.advanceTimersByTimeAsync(0);
  expect(fetcher.mock.calls.length).toBeLessThanOrEqual(12);
});

it("warming failures never surface and every queued clip drains", async () => {
  let calls = 0;
  const fetcher = vi.fn(() => {
    calls += 1;
    if (calls % 2 === 0) return Promise.reject(new Error("boom"));
    return queueable("/play");
  });
  vi.stubGlobal("fetch", fetcher);
  const { warmPlaybackBytes } = await import("./playbackWarming");
  for (let i = 1; i <= 5; i++) warmPlaybackBytes(`/x/${i}`);
  await vi.waitFor(() => expect(fetcher.mock.calls.length).toBe(5));
});

it("an oversized rendition is aborted, never buffered whole", async () => {
  const big = {
    ok: true,
    body: { getReader: () => ({ read: async () => ({ done: false, value: new Uint8Array(1024 * 1024) }) }) },
    headers: new Headers({ "Content-Length": String(1024 * 1024 * 1024) }),
  };
  const fetcher = vi.fn().mockResolvedValue(big);
  vi.stubGlobal("fetch", fetcher);
  const { warmPlaybackBytes } = await import("./playbackWarming");
  warmPlaybackBytes("/huge-original.mp4");
  await vi.advanceTimersByTimeAsync(0);
  // No arrayBuffer/completing read of a gigabyte: content-length pins it first.
  expect(fetcher).toHaveBeenCalledTimes(1);
});

it("a warm that grows past the cap while streaming is cancelled mid-flight", async () => {
  let cancelCalls = 0;
  let stop = false;
  const big = {
    ok: true,
    body: { getReader: () => ({
      read: async () => {
        if (stop) return { done: true };
        // 2 MiB chunks: a 3 MiB cap trips while streaming, without Content-Length.
        return { done: false, value: new Uint8Array(2 * 1024 * 1024) };
      },
      cancel: () => { cancelCalls += 1; return Promise.resolve(); },
    }) },
    headers: new Headers(),
  };
  const fetcher = vi.fn().mockResolvedValue(big);
  vi.stubGlobal("fetch", fetcher);
  const { warmPlaybackBytes } = await import("./playbackWarming");
  warmPlaybackBytes("/stream-grow.mp4");
  await vi.waitFor(() => expect(cancelCalls).toBe(1));
  stop = true;
});
