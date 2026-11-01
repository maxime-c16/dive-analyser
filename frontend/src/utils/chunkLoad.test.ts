import { afterEach, describe, expect, it, vi } from "vitest";
import {
  clearReloadGuard,
  chunkRecovery,
  loadChunk,
  RELOAD_COOLDOWN_MS,
} from "./chunkLoad";

afterEach(() => {
  clearReloadGuard();
  vi.restoreAllMocks();
});

describe("loadChunk", () => {
  it("resolves a chunk that loads on the first attempt", async () => {
    const reload = vi
      .spyOn(chunkRecovery, "reload")
      .mockImplementation(() => undefined);
    const chunk = { default: () => null };
    const load = vi.fn().mockResolvedValue(chunk);

    await expect(loadChunk(load)).resolves.toBe(chunk);
    expect(load).toHaveBeenCalledTimes(1);
    expect(reload).not.toHaveBeenCalled();
  });

  it("recovers a transient failure with one in-place retry, no reload", async () => {
    const reload = vi
      .spyOn(chunkRecovery, "reload")
      .mockImplementation(() => undefined);
    const chunk = { default: () => null };
    const load = vi
      .fn()
      .mockRejectedValueOnce(new Error("Failed to fetch dynamically imported module"))
      .mockResolvedValueOnce(chunk);

    await expect(loadChunk(load)).resolves.toBe(chunk);
    expect(load).toHaveBeenCalledTimes(2);
    expect(reload).not.toHaveBeenCalled();
  });

  it("falls back to one guarded reload after a second failure and rethrows", async () => {
    const reload = vi
      .spyOn(chunkRecovery, "reload")
      .mockImplementation(() => undefined);
    const load = vi.fn().mockRejectedValue(
      new Error("Failed to fetch dynamically imported module"),
    );

    await expect(loadChunk(load)).rejects.toThrow(
      /Failed to fetch dynamically imported module/,
    );
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("refuses to reload inside the cooldown and surfaces the error instead", async () => {
    const reload = vi
      .spyOn(chunkRecovery, "reload")
      .mockImplementation(() => undefined);
    sessionStorage.setItem(
      "dive:chunk-reload-at",
      String(Date.now() - RELOAD_COOLDOWN_MS / 2),
    );
    const load = vi
      .fn()
      .mockRejectedValue(new Error("Failed again"));

    await expect(loadChunk(load)).rejects.toThrow("Failed again");
    expect(reload).not.toHaveBeenCalled();
  });

  it("allows a new guarded reload after the cooldown has elapsed", async () => {
    const reload = vi
      .spyOn(chunkRecovery, "reload")
      .mockImplementation(() => undefined);
    sessionStorage.setItem(
      "dive:chunk-reload-at",
      String(Date.now() - RELOAD_COOLDOWN_MS - 1_000),
    );
    const load = vi.fn().mockRejectedValue(new Error("Stale again"));

    await expect(loadChunk(load)).rejects.toThrow("Stale again");
    expect(reload).toHaveBeenCalledTimes(1);
  });
});

 it("does not auto-reload when the persistent reload guard cannot be written", async () => {
   const reload = vi.spyOn(chunkRecovery, "reload").mockImplementation(() => undefined);
   vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("storage blocked"); });
   await expect(loadChunk(() => Promise.reject(new Error("chunk missing")))).rejects.toThrow("chunk missing");
   expect(reload).not.toHaveBeenCalled();
 });
