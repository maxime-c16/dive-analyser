import { afterEach, beforeEach, expect, it, vi } from "vitest";

beforeEach(() => {
  vi.resetModules();
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

it("a warmed analysis promise is consumed once by the destination read", async () => {
  const fetcher = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ attempts: [1, 2, 3] }),
  });
  vi.stubGlobal("fetch", fetcher);
  const { getDiveAnalysis, warmDiveAnalysis } = await import("./diveAnalysisApi");
  warmDiveAnalysis("103B", { diver_scope: "self" });
  await vi.advanceTimersByTimeAsync(0);
  const warmed = await getDiveAnalysis("103B", { diver_scope: "self" });
  expect(warmed).toEqual({ attempts: [1, 2, 3] });
  // Speculated and actual reads share one request; a later visit fetches again.
  await getDiveAnalysis("103B", { diver_scope: "self" });
  expect(fetcher).toHaveBeenCalledTimes(2);
});

it("a stale or absent warm falls back to a plain fetch, never blocks", async () => {
  const fetcher = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ attempts: [] }),
  });
  vi.stubGlobal("fetch", fetcher);
  const { getDiveAnalysis, warmDiveAnalysis, defaultAnalysisFilters } = await import("./diveAnalysisApi");
  warmDiveAnalysis("103B", defaultAnalysisFilters("all"));
  // Advance past the intent TTL so the warm has expired.
  await vi.advanceTimersByTimeAsync(10_001);
  await expect(getDiveAnalysis("103B", defaultAnalysisFilters("all"))).resolves.toEqual({ attempts: [] });
  expect(fetcher).toHaveBeenCalledTimes(2);
});

it("the warmed and destination filters serialize identically", async () => {
  const fetcher = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ attempts: [] }),
  });
  vi.stubGlobal("fetch", fetcher);
  const { getDiveAnalysis, warmDiveAnalysis } = await import("./diveAnalysisApi");
  warmDiveAnalysis("103B", { diver_scope: "self", date_from: "2026-01-01" });
  await vi.advanceTimersByTimeAsync(0);
  await getDiveAnalysis("103B", { diver_scope: "self", date_from: "2026-01-01" });
  expect(fetcher).toHaveBeenCalledTimes(1);
});
