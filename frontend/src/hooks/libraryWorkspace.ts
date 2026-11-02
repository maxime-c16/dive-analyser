/**
 * Library workspace memory across rubriques (discovery 2026-11-01).
 *
 * The Library keeps its whole working state in the URL (search, scope,
 * height, context, rating, modifiers, view, sort). Leaving to Messages or
 * Calendar and tapping "Library" lands on a bare `/dives`, which used to
 * throw away filters and scroll depth. This module remembers that state per
 * account for the current tab so returning to a *bare* URL restores it.
 *
 * Explicit URLs keep priority: as soon as the URL carries any Library key
 * (or a `clip` deep link), the memory is ignored. The memory is keyed by the
 * account identity, so a login/logout never serves another account's
 * filters, and it lives in sessionStorage — a fresh browser session starts
 * clean instead of resurrecting week-old results.
 */
import type { AuthUser } from "../contexts/AuthContext";
import { libraryKey } from "../services/libraryCache";

export const LIBRARY_VIEW_KEYS = [
  "q", "scope", "height", "context", "performance", "modifiers", "view", "sort", "period",
] as const;

const STORAGE_PREFIX = "dive-library-view:v1";

export type LibraryWorkspace = { params: URLSearchParams; scrollY: number; resume?: LibraryResume | null };

/** Bounded reprise hint for a paginated depth: the anchor is a REAL row
 * (oldest loaded dive id), `pages` counts the server pages that were loaded.
 * No rows are ever stored — the resume re-reads exactly that many pages,
 * capped by MAX_RESUME_PAGES, instead of re-charging the whole history. */
export type LibraryResume = { anchor: number | null; pages: number };
/** Never resume more than this many pages past page 1. */
export const MAX_RESUME_PAGES = 6;

/** True when the URL carries none of the Library's own working state. */
export function isBareLibraryUrl(params: URLSearchParams): boolean {
  return LIBRARY_VIEW_KEYS.every((key) => !params.has(key));
}

/** The library-owned subset of a URL (foreign keys and clips stay out). */
export function librarySearchParams(params: URLSearchParams): URLSearchParams {
  const owned = new URLSearchParams();
  for (const key of LIBRARY_VIEW_KEYS) {
    const value = params.get(key);
    if (value) owned.set(key, value);
  }
  return owned;
}

/** Save on leaving the Library; storage failures are non-fatal. */
export function saveLibraryWorkspace(user: AuthUser | null, params: URLSearchParams, scrollY: number,
    resume?: LibraryResume | null): void {
  const owned = librarySearchParams(params);
  const bounded = resume && resume.pages > 0
    ? { anchor: typeof resume.anchor === 'number' ? resume.anchor : null, pages: Math.min(Math.max(1, Math.floor(resume.pages)), MAX_RESUME_PAGES) }
    : undefined;
  try {
    sessionStorage.setItem(
      `${STORAGE_PREFIX}:${libraryKey(user) ?? 'anonymous'}`,
      JSON.stringify({ p: owned.toString(), y: Math.max(0, Math.round(scrollY || 0)), d: bounded ?? null }),
    );
  } catch { /* Private mode or quota: memory-only, nothing to restore. */ }
}

/** Null when storage is empty, unreadable, or keyed to another account. */
export function readLibraryWorkspace(user: AuthUser | null): LibraryWorkspace | null {
  try {
    const raw = sessionStorage.getItem(`${STORAGE_PREFIX}:${libraryKey(user) ?? 'anonymous'}`);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { p?: unknown; y?: unknown; d?: unknown };
    if (typeof parsed.p !== "string") return null;
    const resume = parsed.d && typeof parsed.d === 'object'
      && typeof (parsed.d as LibraryResume).pages === 'number'
      ? { anchor: typeof (parsed.d as LibraryResume).anchor === 'number' ? (parsed.d as LibraryResume).anchor : null,
          pages: Math.min(Math.max(1, Math.floor((parsed.d as { pages: number }).pages)), MAX_RESUME_PAGES) }
      : null;
    return {
      params: new URLSearchParams(parsed.p),
      scrollY: Number.isFinite(parsed.y) ? Math.max(0, Number(parsed.y)) : 0,
      resume,
    };
  } catch {
    return null;
  }
}

/** Bare URL + remembered state: same foreign keys, library keys replaced. */
export function mergeLibraryParams(base: URLSearchParams, workspace: LibraryWorkspace): URLSearchParams {
  const merged = new URLSearchParams(base);
  for (const key of LIBRARY_VIEW_KEYS) {
    merged.delete(key);
    const value = workspace.params.get(key);
    if (value) merged.set(key, value);
  }
  return merged;
}
