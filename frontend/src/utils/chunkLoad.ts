/**
 * Hardened dynamic-import loader (UX fix 2026-11).
 *
 * A lazy route chunk can fail for reasons outside the code itself: a deploy
 * swaps the built file set between the browser's cached index.html and a
 * later navigation (stale chunk hash → 404), or the fetch is simply
 * dropped. `loadChunk` retries once in place (network blips), then falls
 * back to ONE guarded full page reload — a fresh index.html names the
 * current chunk hashes. The guard (sessionStorage timestamp) blocks any
 * reload inside the cooldown, so the worst case is a visible error, never
 * an infinite loop and never a silently swallowed failure: when reloading
 * is not allowed the error is rethrown to the route error boundary.
 */

const RELOAD_STORAGE_KEY = "dive:chunk-reload-at";
export const RELOAD_COOLDOWN_MS = 90_000;
const RETRY_DELAY_MS = 250;

/** Real reload, isolated so tests can stub it without touching location. */
export const chunkRecovery = {
  reload: () => {
    window.location.reload();
  },
};

function delay(ms: number) {
  return new Promise<void>((resolve) => {
    setTimeout(resolve, ms);
  });
}

function lastReloadAt(): number {
  try {
    const raw = sessionStorage.getItem(RELOAD_STORAGE_KEY);
    const at = raw === null ? 0 : Number(raw);
    return Number.isFinite(at) ? at : 0;
  } catch {
    return 0;
  }
}

function markReload(now: number): number | null {
  try {
    sessionStorage.setItem(RELOAD_STORAGE_KEY, String(now));
    return now;
  } catch {
    return null;
  }
}

export function clearReloadGuard() {
  try {
    sessionStorage.removeItem(RELOAD_STORAGE_KEY);
  } catch {
    // Storage unavailable: nothing to clear.
  }
}

export async function loadChunk<T>(load: () => Promise<T>): Promise<T> {
  try {
    return await load();
  } catch {
    // Retry once in place: transient failures recover without a reload.
    try {
      await delay(RETRY_DELAY_MS);
      return await load();
    } catch (error) {
      // One guarded reload re-fetches the deployed index.html and its
      // current chunk names. Inside the cooldown the error surfaces
      // instead (route error boundary), so the user sees the failure
      // rather than a reload loop.
      const now = Date.now();
      if (lastReloadAt() + RELOAD_COOLDOWN_MS > now) throw error;
      markReload(now);
      chunkRecovery.reload();
      throw error;
    }
  }
}
