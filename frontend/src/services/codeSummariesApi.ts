import { api } from './api'
import type { Attempt } from '../utils/attemptPresentation'

export type CodeRecentAttempt = { id: number; performance: string | null; score: number | null; dive_datetime: string; height: string }
export type CodeTrend = { delta: number; recent_count: number; baseline_count: number }
export type CodeSummary = {
  dive_code: string
  analytics: boolean
  attempt_count: number
  scored_count: number
  session_count: number
  average: number | null
  median: number | null
  best: number | null
  success_rate: number | null
  first_attempt_at: string
  last_attempt_at: string
  heights: string[]
  ratings: Partial<Record<'P' | 'G' | 'M' | 'B' | 'F', number>>
  trend: CodeTrend | null
  spark: number[]
  months: Record<string, { count: number; median: number | null }>
  recent: CodeRecentAttempt[]
  latest: Pick<Attempt, 'id' | 'dive_code' | 'dive_datetime' | 'video_uuid' | 'thumb_url' | 'thumbhash' | 'animated_url'>
}
export type ActivityWindow = { attempt_count: number; session_count: number; code_count: number; median: number | null }
export type CodeSummaries = {
  generated_at: string
  codes: CodeSummary[]
  activity: { current: ActivityWindow; previous: ActivityWindow; months: string[]; weeks: Array<{ start: string; attempt_count: number; codes: Record<string, number> }> }
}
export type LibraryCodeParams = Record<string, string | number | boolean | undefined>

const FRESH_MS = 60_000
type Entry<T> = { at: number; value?: T; promise?: Promise<T> }
let summaries = new Map<string, Entry<CodeSummaries>>()
let codeAttempts = new Map<string, Entry<{ items: Attempt[]; capped: boolean }>>()

/** Writes invalidate every derived read (see api.ts). */
export function clearCodeSummaryCache() {
  summaries = new Map()
  codeAttempts = new Map()
}

/** Library reads are viewer-dependent (own private dives included), so every key
 carries the account identity — pass `libraryKey(user)`. Login and logout go
 through native fetch, bypassing api.ts invalidation, so a key without the
 viewer would serve the previous account's private attempts after a switch. */
function scopedKey(viewer: string | null, ...rest: unknown[]) {
  return JSON.stringify([viewer, ...rest])
}

function cached<T>(store: Map<string, Entry<T>>, key: string, load: () => Promise<T>): Promise<T> {
  const hit = store.get(key)
  if (hit?.promise) return hit.promise
  if (hit?.value !== undefined && Date.now() - hit.at < FRESH_MS) return Promise.resolve(hit.value)
  const promise = load().then(value => { store.set(key, { at: Date.now(), value }); trim(store); return value })
    .catch(error => { store.delete(key); throw error })
  store.set(key, { at: Date.now(), value: hit?.value, promise })
  return promise
}

/** Attempts stay bounded in memory even across many code visits: the oldest
 * entries (insertion order) drop first, current reads always hit their key. */
function trim<T>(store: Map<string, Entry<T>>) {
  while (store.size > MAX_CACHE_ENTRIES) {
    const oldest = store.keys().next().value
    if (oldest === undefined) break
    store.delete(oldest)
  }
}

/** Last value even when stale, so a revisit paints immediately while it refreshes. */
export function peekCodeSummaries(params: LibraryCodeParams, viewer: string | null = null): CodeSummaries | null {
  return summaries.get(scopedKey(viewer, params))?.value ?? null
}

export function getCodeSummaries(params: LibraryCodeParams, viewer: string | null = null): Promise<CodeSummaries> {
  const clean = Object.fromEntries(Object.entries(params).filter(([, value]) => value !== '' && value !== undefined))
  return cached(summaries, scopedKey(viewer, params), () => api.get('/api/v1/dives/library/codes', { params: clean }).then(response => response.data))
}

export function peekCodeAttempts(code: string, scope: string, viewer: string | null = null): Attempt[] | null {
  return peekCodeAttemptsResult(code, scope, viewer)?.items ?? null
}

export type CodeAttemptsResult = { items: Attempt[]; capped: boolean }

export function peekCodeAttemptsResult(code: string, scope: string, viewer: string | null = null): CodeAttemptsResult | null {
  return codeAttempts.get(scopedKey(viewer, code.toUpperCase(), scope))?.value ?? null
}

/** Newest-attempts window for one exact code, at most this many pages of 100:
 * bounded traversal and bounded memory, never a silently truncated analysis. */
const MAX_ATTEMPT_PAGES = 10
const MAX_CACHE_ENTRIES = 16

/** Every Library attempt of one exact code (sorted oldest first), read
 * through the bounded Library pages. `capped` marks an explicit newest
 * window: the Code Analysis page says so instead of pretending the whole
 * history was walked. */
export function getCodeAttemptsResult(code: string, scope: string, viewer: string | null = null): Promise<CodeAttemptsResult> {
  const exact = code.toUpperCase()
  return cached(codeAttempts, scopedKey(viewer, exact, scope), async () => {
    const items: Attempt[] = []
    let cursor: string | null = null
    let capped = false
    for (let page = 0; page < MAX_ATTEMPT_PAGES; page++) {
      const response: { data: { items: Attempt[]; next_cursor: string | null } } = await api.get('/api/v1/dives/library', {
        params: { limit: 100, diver_scope: scope, code_prefix: exact, ...(cursor ? { cursor } : {}) },
      })
      // The Library response is newest first, so a bounded walk keeps the
      // newest window complete and says so, rather than mixing eras.
      items.push(...response.data.items.filter(item => item.dive_code.toUpperCase() === exact))
      cursor = response.data.next_cursor
      if (!cursor) return { items: items.sort((a, b) => Date.parse(a.dive_datetime) - Date.parse(b.dive_datetime) || a.id - b.id), capped: false }
    }
    capped = true
    return { items: items.sort((a, b) => Date.parse(a.dive_datetime) - Date.parse(b.dive_datetime) || a.id - b.id), capped }
  })
}

/** Backwards-compatible view of the same bounded cache. */
export function getCodeAttempts(code: string, scope: string, viewer: string | null = null): Promise<Attempt[]> {
  return getCodeAttemptsResult(code, scope, viewer).then(result => result.items)
}
