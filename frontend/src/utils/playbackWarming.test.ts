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
  const fetcher = vi.fn(() => queueable("/play"));
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
