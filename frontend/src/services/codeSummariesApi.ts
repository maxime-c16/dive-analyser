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
let codeAttempts = new Map<string, Entry<Attempt[]>>()

/** Writes invalidate every derived read (see api.ts). */
export function clearCodeSummaryCache() {
  summaries = new Map()
  codeAttempts = new Map()
}

function cached<T>(store: Map<string, Entry<T>>, key: string, load: () => Promise<T>): Promise<T> {
  const hit = store.get(key)
  if (hit?.promise) return hit.promise
  if (hit?.value !== undefined && Date.now() - hit.at < FRESH_MS) return Promise.resolve(hit.value)
  const promise = load().then(value => { store.set(key, { at: Date.now(), value }); return value })
    .catch(error => { store.delete(key); throw error })
  store.set(key, { at: Date.now(), value: hit?.value, promise })
  return promise
}

/** Last value even when stale, so a revisit paints immediately while it refreshes. */
export function peekCodeSummaries(params: LibraryCodeParams): CodeSummaries | null {
  return summaries.get(JSON.stringify(params))?.value ?? null
}

export function getCodeSummaries(params: LibraryCodeParams): Promise<CodeSummaries> {
  const clean = Object.fromEntries(Object.entries(params).filter(([, value]) => value !== '' && value !== undefined))
  return cached(summaries, JSON.stringify(params), () => api.get('/api/v1/dives/library/codes', { params: clean }).then(response => response.data))
}

export function peekCodeAttempts(code: string, scope: string): Attempt[] | null {
  return codeAttempts.get(JSON.stringify([code.toUpperCase(), scope]))?.value ?? null
}

/** Every Library attempt of one exact code (oldest first), with thumbnails, through the bounded Library pages. */
export function getCodeAttempts(code: string, scope: string): Promise<Attempt[]> {
  const exact = code.toUpperCase()
  return cached(codeAttempts, JSON.stringify([exact, scope]), async () => {
    const items: Attempt[] = []
    let cursor: string | null = null
    do {
      const response: { data: { items: Attempt[]; next_cursor: string | null } } = await api.get('/api/v1/dives/library', {
        params: { limit: 100, diver_scope: scope, code_prefix: exact, ...(cursor ? { cursor } : {}) },
      })
      items.push(...response.data.items.filter(item => item.dive_code.toUpperCase() === exact))
      cursor = response.data.next_cursor
    } while (cursor)
    return items.sort((a, b) => Date.parse(a.dive_datetime) - Date.parse(b.dive_datetime) || a.id - b.id)
  })
}
