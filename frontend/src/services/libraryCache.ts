import type { Attempt } from '../utils/attemptPresentation';
import type { AuthUser } from '../contexts/AuthContext';

export type LibrarySnapshot = {
  dives: Attempt[];
  divers: { id: number; display_name: string; is_primary_user: boolean }[];
  savedAt: number;
};
const STORAGE_KEY = 'dive-library-v1';
export const LIBRARY_FRESH_MS = 60_000;
const RETAIN_MS = 24 * 60 * 60_000;
let memory: { key: string; snapshot: LibrarySnapshot } | null = null;
let pending: { key: string; promise: Promise<LibrarySnapshot> } | null = null;
let generation = 0;

export function libraryKey(user: AuthUser | null) {
  return user ? JSON.stringify([user.user_id, user.role, user.is_admin,
    (user.divers ?? []).map(d => `${d.diver_id}:${d.access_kind}`).sort()]) : null;
}

export function clearLibraryCache() {
  generation++;
  memory = null;
  pending = null;
  try { localStorage.removeItem(STORAGE_KEY); } catch { /* Memory-only fallback. */ }
}

export function readLibraryCache(key: string | null): LibrarySnapshot | null {
  if (!key) return null;
  if (!memory) {
    try {
      const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? 'null');
      if (stored && typeof stored.key === 'string' && Array.isArray(stored.snapshot?.dives) &&
          Array.isArray(stored.snapshot?.divers) && Number.isFinite(stored.snapshot?.savedAt)) memory = stored;
    } catch { /* Unavailable storage or corrupt snapshot: use the network. */ }
  }
  if (!memory) return null;
  const age = Date.now() - memory.snapshot.savedAt;
  if (memory.key !== key || age < 0 || age >= RETAIN_MS) {
    clearLibraryCache();
    return null;
  }
  return memory.snapshot;
}

export function loadLibraryCache(key: string | null, load: () => Promise<Omit<LibrarySnapshot, 'savedAt'>>) {
  const snapshot = readLibraryCache(key);
  if (snapshot && Date.now() - snapshot.savedAt < LIBRARY_FRESH_MS) return Promise.resolve(snapshot);
  if (key && pending?.key === key) return pending.promise;
  const started = generation;
  const promise = load().then(data => {
    const snapshot = { ...data, savedAt: Date.now() };
    if (key && started === generation) {
      memory = { key, snapshot };
      try { localStorage.setItem(STORAGE_KEY, JSON.stringify(memory)); } catch { /* Quota/privacy mode: memory still works. */ }
    }
    return snapshot;
  }).finally(() => { if (pending?.promise === promise) pending = null; });
  if (key) pending = { key, promise };
  return promise;
}

// Another tab may log out, mutate a dive, or replace the saved snapshot.
// Drop this tab's in-memory copy so the next navigation reads current storage.
if (typeof window !== 'undefined') {
  window.addEventListener('storage', event => {
    if (event.key === STORAGE_KEY || event.key === null) {
      generation++;
      memory = null;
      pending = null;
    }
  });
}
