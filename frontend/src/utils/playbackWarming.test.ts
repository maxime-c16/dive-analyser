// Rolling warm-window tests. Each test drives the public surface
// (warmAdjacentClips / resetPlaybackWarming) with stubbed fetch and a
// controlled preview cache, mirroring how the viewer feeds the warmer.
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { Mock } from "vitest";

vi.mock("./mediaPreview", () => ({
  getPreview: vi.fn(),
  resetMediaPreviews: vi.fn(),
  cachedPreview: vi.fn(() => undefined),
}));

type Attempt = { video_uuid: string | null };
type Call = { url: string; signal: AbortSignal };

const previewMock: { impl: Mock } = { impl: undefined as unknown as Mock };

beforeEach(async () => {
  vi.resetModules();
  vi.useFakeTimers();
  vi.stubGlobal("navigator", { onLine: true, connection: {} });
  const media = (await import("./mediaPreview")) as unknown as {
    getPreview: Mock;
  };
  previewMock.impl = media.getPreview;
  previewMock.impl.mockImplementation((uuid: string) =>
    Promise.resolve(previewFor(uuid)),
  );
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

function previewFor(uuid: string) {
  return {
    posterUrl: `/api/v1/media/cache/${uuid}/poster`,
    videoThumbUrl: null,
    playbackUrl: `/api/v1/media/cache/${uuid}/play`,
    ready: true,
  };
}

function stubFetch(options: { resolve?: (url: string, call: Call) => unknown } = {}) {
  const calls: Call[] = [];
  const fetcher = vi.fn((url: string, init?: RequestInit) => {
    const call: Call = { url, signal: init?.signal as AbortSignal };
    calls.push(call);
    return Promise.resolve(options.resolve?.(url, call) ?? okResponse(8, 1));
  });
  vi.stubGlobal("fetch", fetcher);
  return { calls, fetcher };
}

// Full-shaped success: one chunk, then done, exactly like the real
// low-priority fetch-and-read path.
function okResponse(bytes: number, chunks = 1, contentLength?: number) {
  let reads = 0;
  let cancels = 0;
  const response = {
    ok: true,
    status: 200,
    headers: new Headers({
      "Content-Length": String(contentLength ?? bytes * chunks),
    }),
    body: {
      getReader: () => ({
        read: async () =>
          reads++ >= chunks
            ? { done: true, value: undefined }
            : { done: false, value: new Uint8Array(bytes) },
        cancel: () => {
          cancels += 1;
          return Promise.resolve();
        },
      }),
    },
    canceled: () => cancels > 0,
  };
  return response;
}

function errorResponse(status: number) {
  return { ok: false, status, headers: new Headers(), body: null };
}

const attempts = (count: number): Attempt[] =>
  Array.from({ length: count }, (_, i) => ({ video_uuid: `u${i}` }));

async function flush() {
  await vi.advanceTimersByTimeAsync(0);
  await vi.advanceTimersByTimeAsync(0);
}

// Drain every pending microtask turn (chained reader reads) until the
// recorded fetch surface stops moving.
async function quiet(calls: Call[]) {
  await flush();
  for (let round = 0; round < 20; round += 1) {
    const before = calls.length;
    await vi.advanceTimersByTimeAsync(0);
    if (calls.length === before) break;
  }
  await flush();
}

function clipOrder(calls: Call[], prefix = "/play"): string[] {
  return [
    ...new Set(
      calls
        .filter((call) => call.url.includes(prefix))
        .map((call) => call.url.match(/u\d+/)?.[0] ?? ""),
    ),
  ];
}

const videoCalls = (calls: Call[]) => calls.filter((c) => c.url.includes("/play"));
const posterCalls = (calls: Call[]) => calls.filter((c) => c.url.includes("/poster"));

it("continues warming beyond 12 warmed URLs across 50 swipes", async () => {
  const { calls } = stubFetch();
  const { warmAdjacentClips } = await import("./playbackWarming");
  const feed = attempts(80);
  for (let index = 0; index < 50; index += 1) {
    warmAdjacentClips({ attempts: feed, index, direction: index === 0 ? 0 : 1 });
    await flush();
  }
  expect(new Set(calls.map((call) => call.url)).size).toBeGreaterThan(12);
  // Rolling, not a firehose: each stop prepares at most a bounded window
  // (4 neighbours × 2 lanes), never the whole feed.
  expect(calls.length).toBeLessThan(50 * 12);
});

it("forward window prepares next, next+2, previous and next+3 only", async () => {
  const { calls } = stubFetch();
  const { warmAdjacentClips } = await import("./playbackWarming");
  warmAdjacentClips({ attempts: attempts(20), index: 5, direction: 1 });
  await quiet(calls);
  expect(calls.map((call) => call.url).sort()).toEqual([
    "/api/v1/media/cache/u4/play",
    "/api/v1/media/cache/u4/poster",
    "/api/v1/media/cache/u6/play",
    "/api/v1/media/cache/u6/poster",
    "/api/v1/media/cache/u7/play",
    "/api/v1/media/cache/u7/poster",
    "/api/v1/media/cache/u8/play",
    "/api/v1/media/cache/u8/poster",
  ]);
});

it("starts warms in priority order: next, next+2, previous, next+3", async () => {
  const { calls } = stubFetch();
  const { warmAdjacentClips } = await import("./playbackWarming");
  warmAdjacentClips({ attempts: attempts(20), index: 10, direction: 1 });
  await quiet(calls);
  expect(clipOrder(calls)).toEqual(["u11", "u12", "u9", "u13"]);
  expect(clipOrder(calls, "/poster")).toEqual(["u11", "u12", "u9", "u13"]);
});

it("a reverse direction prepares the two behind clips first", async () => {
  const { calls } = stubFetch();
  const { warmAdjacentClips } = await import("./playbackWarming");
  warmAdjacentClips({ attempts: attempts(20), index: 10, direction: -1 });
  await quiet(calls);
  expect(clipOrder(calls)).toEqual(["u9", "u8", "u11", "u7"]);
});

it("never starts a fresh warm for the currently playing clip", async () => {
  const { calls } = stubFetch();
  const { warmAdjacentClips } = await import("./playbackWarming");
  warmAdjacentClips({ attempts: attempts(20), index: 2, direction: 1 });
  await quiet(calls);
  expect(calls.some((call) => call.url.endsWith("/u2"))).toBe(false);
});

it("cancels an in-flight warm once its clip falls out of the window", async () => {
  const { calls } = stubFetch({ resolve: () => new Promise(() => {}) });
  const { warmAdjacentClips } = await import("./playbackWarming");
  const feed = attempts(40);
  warmAdjacentClips({ attempts: feed, index: 10, direction: 1 });
  await flush();
  const started = [...videoCalls(calls)];
  expect(started.length).toBe(2);
  warmAdjacentClips({ attempts: feed, index: 30, direction: 1 });
  await flush();
  for (const call of started) expect(call.signal.aborted).toBe(true);
});

it("a queued job whose window moved is dropped and never fetches", async () => {
  const { calls } = stubFetch({ resolve: () => new Promise(() => {}) });
  const { warmAdjacentClips } = await import("./playbackWarming");
  const feed = attempts(40);
  warmAdjacentClips({ attempts: feed, index: 10, direction: 1 });
  await flush();
  // Both lanes top out: 2 running videos + 2 running posters hang; the
  // previous (u9) stays queued and un-started.
  expect(calls.length).toBe(4);
  warmAdjacentClips({ attempts: feed, index: 30, direction: 1 });
  await quiet(calls);
  expect(calls.length).toBe(8);
  expect(calls.some((call) => call.url.includes("/u9"))).toBe(false);
});

it("stale completions of cancelled warms keep lane slots and successors safe", async () => {
  // Hang the first u11 video fetch but hand back a controllable promise.
  const releaseFirst: { fn: (() => void) | null } = { fn: null };
  let firstU11 = true;
  const { calls } = stubFetch({
    resolve: (url) => {
      if (url === "/api/v1/media/cache/u11/play" && firstU11) {
        firstU11 = false;
        return new Promise((resolve) => {
          releaseFirst.fn = () => resolve(okResponse(8));
        });
      }
      return okResponse(8);
    },
  });
  const { warmAdjacentClips } = await import("./playbackWarming");
  const feed = attempts(40);
  warmAdjacentClips({ attempts: feed, index: 10, direction: 1 });
  await quiet(calls);
  // Slide away (u11 cancelled), come back (u12 re-enters the reverse
  // window and re-fetches), then the FIRST fetch resolves late.
  warmAdjacentClips({ attempts: feed, index: 30, direction: 1 });
  await quiet(calls);
  // Slide back: landing on 11 makes u12 a reverse-window target while the
  // old u11 fetch is still pending underneath the cancelled job.
  warmAdjacentClips({ attempts: feed, index: 11, direction: -1 });
  await quiet(calls);
  const freshU12 = videoCalls(calls).filter((c) => c.url === "/api/v1/media/cache/u12/play").length;
  expect(freshU12).toBe(2);
  releaseFirst.fn?.();
  await quiet(calls);
  // The stale success must not disturb the newer u12 work.
  const afterLate = videoCalls(calls).filter(
    (c) => c.url === "/api/v1/media/cache/u12/play" && !c.signal.aborted,
  ).length;
  expect(afterLate).toBe(freshU12);
});

it("bounds retries with backoff, then cools the lane across repeated updates", async () => {
  const fetcher = vi.fn((_url: string, _init?: RequestInit) =>
    Promise.reject(new TypeError("network down")),
  );
  vi.stubGlobal("fetch", fetcher);
  const { warmAdjacentClips } = await import("./playbackWarming");
  warmAdjacentClips({ attempts: attempts(10), index: 0, direction: 0 });
  await flush();
  const attemptsFor = () =>
    fetcher.mock.calls.filter((call) => call[0] === "/api/v1/media/cache/u1/play").length;
  expect(attemptsFor()).toBe(1);
  await vi.advanceTimersByTimeAsync(1000);
  expect(attemptsFor()).toBe(2);
  await vi.advanceTimersByTimeAsync(2000);
  expect(attemptsFor()).toBe(3);
  // Repeated updates inside the cooldown must not restart the hammer.
  for (let extra = 0; extra < 5; extra += 1) {
    await vi.advanceTimersByTimeAsync(3000);
    warmAdjacentClips({ attempts: attempts(10), index: 0, direction: 0 });
    await flush();
  }
  expect(attemptsFor()).toBe(3);
  // Past the cooldown, the lane starts one fresh bounded burst.
  await vi.advanceTimersByTimeAsync(20_000);
  warmAdjacentClips({ attempts: attempts(10), index: 0, direction: 0 });
  await flush();
  expect(attemptsFor()).toBe(4);
});

it("a permanent 404 warms once and is never retried", async () => {
  const { fetcher } = stubFetch({ resolve: () => errorResponse(404) });
  const { warmAdjacentClips } = await import("./playbackWarming");
  warmAdjacentClips({ attempts: attempts(4), index: 0, direction: 0 });
  await flush();
  expect(fetcher).toHaveBeenCalledTimes(6);
  await vi.advanceTimersByTimeAsync(60_000);
  expect(fetcher).toHaveBeenCalledTimes(6);
});

it("posters keep their own lane while both video transfers hang", async () => {
  const { calls } = stubFetch({
    resolve: (url) =>
      url.includes("/play") ? new Promise(() => {}) : okResponse(64),
  });
  const { warmAdjacentClips } = await import("./playbackWarming");
  warmAdjacentClips({ attempts: attempts(20), index: 2, direction: 1 });
  await quiet(calls);
  expect(videoCalls(calls).length).toBe(2);
  expect(posterCalls(calls).length).toBe(4);
});

it("an oversized original aborts its stream and is never re-requested", async () => {
  let cancelCalls = 0;
  const big = () => ({
    ok: true,
    status: 200,
    headers: new Headers({ "Content-Length": String(1024 * 1024 * 1024) }),
    body: {
      getReader: () => ({
        read: async () => ({ done: false, value: new Uint8Array(1024) }),
        cancel: () => {
          cancelCalls += 1;
          return Promise.resolve();
        },
      }),
    },
  });
  const { calls, fetcher } = stubFetch({
    resolve: (url) => (url.includes("/play") ? big() : okResponse(64)),
  });
  const { warmAdjacentClips } = await import("./playbackWarming");
  warmAdjacentClips({ attempts: attempts(4), index: 0, direction: 0 });
  await flush();
  expect(videoCalls(calls).length).toBe(3);
  expect(cancelCalls).toBe(3);
  await vi.advanceTimersByTimeAsync(60_000);
  expect(fetcher).toHaveBeenCalledTimes(6);
});

it("a preview lookup failure retries with backoff then parks the lanes", async () => {
  previewMock.impl.mockRejectedValue(new TypeError("status down"));
  const { calls } = stubFetch();
  void calls;
  const { warmAdjacentClips } = await import("./playbackWarming");
  warmAdjacentClips({ attempts: attempts(4), index: 0, direction: 0 });
  await quiet(calls);
  await vi.advanceTimersByTimeAsync(1000);
  await quiet(calls);
  await vi.advanceTimersByTimeAsync(2000);
  await quiet(calls);
  const lookedUp = () => previewMock.impl.mock.calls.filter(([u]) => String(u) === "u1").length;
  expect(lookedUp()).toBe(6); // 2 lanes × (1 + 2 backoff retries)
  // Repeated updates inside the cooldown never re-enter the lookups.
  for (let extra = 0; extra < 3; extra += 1) {
    await vi.advanceTimersByTimeAsync(3_000);
    warmAdjacentClips({ attempts: attempts(4), index: 0, direction: 0 });
    await quiet(calls);
  }
  expect(lookedUp()).toBe(6);
  // Past the cooldown, one fresh bounded burst per lane runs.
  await vi.advanceTimersByTimeAsync(20_000);
  warmAdjacentClips({ attempts: attempts(4), index: 0, direction: 0 });
  await quiet(calls);
  expect(lookedUp()).toBeGreaterThan(6);
});

it("sign-out reset aborts active warms and clears cooldowns", async () => {
  const { calls } = stubFetch({ resolve: () => new Promise(() => {}) });
  const { warmAdjacentClips, resetPlaybackWarming } = await import("./playbackWarming");
  warmAdjacentClips({ attempts: attempts(10), index: 0, direction: 0 });
  await flush();
  expect(calls.length).toBe(4);
  resetPlaybackWarming();
  for (const call of calls) expect(call.signal.aborted).toBe(true);
});

it("skips entirely under save-data so no runaway downloads start", async () => {
  vi.stubGlobal("navigator", { onLine: true, connection: { saveData: true } });
  const { calls } = stubFetch();
  const { warmAdjacentClips } = await import("./playbackWarming");
  for (let index = 0; index < 10; index += 1) {
    warmAdjacentClips({ attempts: attempts(20), index, direction: 1 });
    await flush();
  }
  expect(calls.length).toBe(0);
});

it("a B2-backed cross-origin rendition is never warmed", async () => {
  const { calls } = stubFetch();
  const { warmAdjacentClips } = await import("./playbackWarming");
  const feed: Attempt[] = Array.from({ length: 6 }, (_, i) => ({
    video_uuid: `b${i}`,
  }));
  previewMock.impl.mockImplementation((uuid: string) =>
    Promise.resolve({
      posterUrl: uuid === "b1"
        ? "https://b2.example.com/poster/b1.jpg"
        : `/api/v1/media/cache/${uuid}/poster`,
      videoThumbUrl: null,
      playbackUrl: uuid === "b1"
        ? "https://b2.example.com/play/b1.mp4"
        : `/api/v1/media/cache/${uuid}/play`,
      ready: true,
    }),
  );
  warmAdjacentClips({ attempts: feed, index: 0, direction: 1 });
  await quiet(calls);
  // u1's two lanes are skipped (cross-origin, bucket CORS intentionally
  // absent) while the same-origin neighbours warm normally.
  expect(calls.some((call) => call.url.includes("b2.example.com"))).toBe(false);
  expect(calls.some((call) => call.url.includes("/b2/play"))).toBe(true);
  expect(calls.some((call) => call.url.includes("b1"))).toBe(false);
});

it("an empty preview from a failed status batch retries instead of skipping", async () => {
  const { calls } = stubFetch();
  const { warmAdjacentClips } = await import("./playbackWarming");
  // First two lookups resolve empty (mediaPreview swallows transport
  // failures into placeholders), the third resolves real URLs.
  let empty = 2;
  previewMock.impl.mockImplementation((uuid: string) => {
    if (uuid === "u1" && empty > 0) {
      empty -= 1;
      return Promise.resolve({
        posterUrl: null,
        videoThumbUrl: null,
        playbackUrl: null,
        ready: false,
      });
    }
    return Promise.resolve(previewFor(uuid));
  });
  warmAdjacentClips({ attempts: attempts(10), index: 0, direction: 0 });
  await quiet(calls);
  await vi.advanceTimersByTimeAsync(1000);
  await quiet(calls);
  await vi.advanceTimersByTimeAsync(2000);
  await quiet(calls);
  // The retried lookup eventually feeds a real warm for u1.
  expect(calls.some((call) => call.url === "/api/v1/media/cache/u1/play")).toBe(true);
});

it("an expired cooldown allows a fresh bounded burst (no permanent suppression)", async () => {
  const fetcher = vi.fn((_url: string, _init?: RequestInit) =>
    Promise.reject(new TypeError("network down")),
  );
  vi.stubGlobal("fetch", fetcher);
  const { warmAdjacentClips } = await import("./playbackWarming");
  const feed = attempts(40);
  // Park the u1 lanes in cooldown (initial + 2 retries each, then 20s TTL).
  warmAdjacentClips({ attempts: feed, index: 0, direction: 0 });
  await quiet(callsFor(fetcher));
  await vi.advanceTimersByTimeAsync(3000);
  await quiet(callsFor(fetcher));
  const parked = fetcher.mock.calls.filter((c) => c[0] === "/api/v1/media/cache/u1/play").length;
  expect(parked).toBe(3);
  // Well past the 20s TTL the lane is again eligible: a fresh burst starts
  // (1 attempt now), proving no entry outlives its expiry.
  await vi.advanceTimersByTimeAsync(60_000);
  warmAdjacentClips({ attempts: feed, index: 0, direction: 0 });
  await quiet(callsFor(fetcher));
  expect(fetcher.mock.calls.filter((c) => c[0] === "/api/v1/media/cache/u1/play").length)
    .toBe(parked + 1);
});

function callsFor(fetcher: { mock: { calls: unknown[][] } }): Call[] {
  void fetcher;
  return [];
}

it("the same-origin revision route that redirects to B2 is not warmed either", async () => {
  const { calls } = stubFetch();
  const { warmAdjacentClips } = await import("./playbackWarming");
  previewMock.impl.mockImplementation((uuid: string) =>
    Promise.resolve({
      posterUrl: `/api/v1/media/cache/${uuid}/poster`,
      videoThumbUrl: null,
      playbackUrl: uuid === "u1"
        ? "/api/v1/media/revisions/42/play"
        : `/api/v1/media/cache/${uuid}/play`,
      ready: true,
    }),
  );
  warmAdjacentClips({ attempts: attempts(10), index: 0, direction: 0 });
  await quiet(calls);
  expect(calls.some((call) => call.url.includes("revisions"))).toBe(false);
  expect(calls.some((call) => call.url === "/api/v1/media/cache/u2/play")).toBe(true);
});

it("landing on a clip cancels its queued warms so nothing races the player", async () => {
  const { calls } = stubFetch({ resolve: () => new Promise(() => {}) });
  const { warmAdjacentClips } = await import("./playbackWarming");
  const feed = attempts(40);
  // Forward window at 10 hangs both video lanes; the previous clip u9 sits
  // queued and un-started.
  warmAdjacentClips({ attempts: feed, index: 10, direction: 1 });
  await quiet(calls);
  // Land on 9: u9 becomes the live clip, its queued warms are cancelled —
  // no speculative GET competes with its own playback load.
  warmAdjacentClips({ attempts: feed, index: 9, direction: -1 });
  await quiet(calls);
  expect(calls.some((call) => call.url.includes("u9"))).toBe(false);
  // The already-running neighbours from before keep their transfers.
  expect(calls.some((call) => call.url.includes("u11"))).toBe(true);
});

it("a failed warm for the live clip is dropped instead of scheduled to retry", async () => {
  const fetcher = vi.fn((_url: string, _init?: RequestInit) =>
    Promise.resolve(errorResponse(503)),
  );
  vi.stubGlobal("fetch", fetcher);
  const { warmAdjacentClips } = await import("./playbackWarming");
  // Warm u1 as a neighbour; its 503 fails and a retry timer is armed.
  warmAdjacentClips({ attempts: attempts(10), index: 0, direction: 0 });
  await quiet(callsFor(fetcher));
  const warmed = fetcher.mock.calls.filter((c) => c[0] === "/api/v1/media/cache/u1/play").length;
  expect(warmed).toBe(1);
  // Land on u1: the live clip's pending retry timer is cancelled — no
  // speculative retry races its playback.
  warmAdjacentClips({ attempts: attempts(10), index: 1, direction: 1 });
  await quiet(callsFor(fetcher));
  await vi.advanceTimersByTimeAsync(5000);
  expect(fetcher.mock.calls.filter((c) => c[0] === "/api/v1/media/cache/u1/play").length)
    .toBe(warmed);
});
