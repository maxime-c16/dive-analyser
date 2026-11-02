import { afterEach, expect, it, vi } from 'vitest'
import { api } from './api'
import {
  clearCodeSummaryCache, getCodeAttempts, getCodeAttemptsResult, getCodeSummaries,
  peekCodeAttempts, peekCodeSummaries,
} from './codeSummariesApi'

vi.mock('./api', () => ({ api: { get: vi.fn() } }))

const page = (items: unknown[]) => ({ items, next_cursor: null })

afterEach(() => {
  clearCodeSummaryCache()
  vi.mocked(api.get).mockReset()
})

it('shares one attempts fetch per code, scope and viewer', async () => {
  vi.mocked(api.get).mockResolvedValue({ data: page([]) })
  await getCodeAttempts('5122D', 'all', 'viewer-a')
  await getCodeAttempts('5122D', 'all', 'viewer-a')
  expect(api.get).toHaveBeenCalledTimes(1)
})

it('never serves the previous account’s attempts to the next viewer', async () => {
  const mine = [{ id: 1, dive_code: '5122D', visibility: 'private' }]
  vi.mocked(api.get).mockResolvedValue({ data: page(mine) })
  await expect(getCodeAttempts('5122D', 'all', 'viewer-a')).resolves.toEqual(mine)
  // Same code and scope, different account: refetch, and no stale peek.
  vi.mocked(api.get).mockResolvedValue({ data: page([]) })
  expect(peekCodeAttempts('5122D', 'all', 'viewer-b')).toBeNull()
  await expect(getCodeAttempts('5122D', 'all', 'viewer-b')).resolves.toEqual([])
  expect(api.get).toHaveBeenCalledTimes(2)
})

it('scopes code summaries to the viewer too', async () => {
  vi.mocked(api.get).mockResolvedValue({ data: { codes: [] } })
  const params = { diver_scope: 'all' }
  await getCodeSummaries(params, 'viewer-a')
  expect(peekCodeSummaries(params, 'viewer-b')).toBeNull()
  await getCodeSummaries(params, 'viewer-b')
  expect(api.get).toHaveBeenCalledTimes(2)
})

it('keeps walking pages until the catalog truly ends (no silent truncation)', async () => {
  // next_cursor stays present through the last page only when the server
  // says more exist: the loop must trust the cursor, not a page count.
  const attemptItem = (index: number) => ({ id: index, dive_code: '5122D', dive_datetime: `2026-01-0${(index % 9) + 1}T00:00:00Z` })
  let pageCalls = 0
  vi.mocked(api.get).mockImplementation(async () => {
    pageCalls += 1
    return { data: { items: [attemptItem(pageCalls)], next_cursor: pageCalls < 3 ? 'cursor' : null } }
  })
  await expect(getCodeAttempts('5122D', 'all', 'viewer-a')).resolves.toHaveLength(3)
  expect(api.get).toHaveBeenCalledTimes(3)
})

it('stops at a bounded newest window and reports the cap instead of lying', async () => {
  let pageCalls = 0
  vi.mocked(api.get).mockImplementation(async () => {
    pageCalls += 1
    return { data: { items: [{ id: pageCalls, dive_code: '5122D', dive_datetime: '2026-01-01T00:00:00Z' }], next_cursor: 'cursor' } }
  })
  const result = await getCodeAttemptsResult('5122D', 'all', 'viewer-a')
  expect(pageCalls).toBe(10) // MAX_ATTEMPT_PAGES, one probe per page.
  expect(result.capped).toBe(true)
  expect(result.items).toHaveLength(10)
})

it('an evicted in-flight walk stops deepening and never reinserts its result', async () => {
  // Walk A goes in flight (its second page is held); 16 later walks evict
  // it (FIFO, pending included). Eviction ABORTS the in-flight request at
  // the transport (axios signal): the held page's signal is already aborted
  // BEFORE its release, the walk stops at the page boundary (never walks to
  // its 10-page cap) and NEVER writes back — the old code kept the request
  // live, walked to the cap and reinserted, all three leaking the bound.
  const callsByCode = new Map<string, number>()
  const signalsByCode = new Map<string, AbortSignal>()
  let gateUsed = false
  let releaseA!: (value: unknown) => void
  vi.mocked(api.get).mockImplementation(async (_url, config) => {
    const params = (config?.params ?? {}) as { dive_code?: string; cursor?: string }
    const signal = (config as { signal?: AbortSignal } | undefined)?.signal
    const code = params.dive_code ?? '?'
    callsByCode.set(code, (callsByCode.get(code) ?? 0) + 1)
    if (signal) signalsByCode.set(code, signal)
    if (code === '599D' && params.cursor && !gateUsed) { gateUsed = true; return new Promise(resolve => { releaseA = resolve }) }
    return { data: { items: [{ id: 1, dive_code: code, dive_datetime: '2026-01-01T00:00:00Z' }], next_cursor: `cursor-${code}` } }
  })
  const inFlight = getCodeAttemptsResult('599D', 'all', 'viewer-a')
  // Sixteen later walks settle instantly; the 16-entry cap evicts the
  // oldest = the pending walk A (its page-2 response is still held).
  for (let index = 0; index < 16; index++) {
    await getCodeAttemptsResult(`5${index}1D`, 'all', 'viewer-a')
  }
  expect(callsByCode.get('599D')).toBe(2)
  // The eviction aborted the held request AT THE TRANSPORT (before its
  // release — the old code's signal stayed live here).
  expect(signalsByCode.get('599D')?.aborted).toBe(true)
  // Releasing the held page resolves it; the walk still stops (dead).
  releaseA!({ data: { items: [{ id: 2, dive_code: '599D', dive_datetime: '2026-01-02T00:00:00Z' }], next_cursor: 'cursor-599D-2' } })
  await inFlight
  // The old code walked to its 10-page cap here (callsByCode 10) and
  // reinserted (peek non-null): both leak the bounded cap.
  expect(callsByCode.get('599D')).toBe(2)
  expect(peekCodeAttempts('599D', 'all', 'viewer-a')).toBeNull()
})

it('asks the server for the EXACT code so same-prefix siblings cannot crowd the bounded window', async () => {
  // The 100-per-page / 10-page cap must bind THIS code's own rows: the walk
  // filters the exact code server-side (dive_code) BEFORE the paging
  // window — a code_prefix search could fill the window with sibling
  // codes (201AB for 201A) and evict the exact attempts (finding
  // b3ec9b9b).
  const paramsSent: Array<Record<string, unknown>> = []
  vi.mocked(api.get).mockImplementation(async (_url, config) => {
    paramsSent.push({ ...(config?.params ?? {}) } as Record<string, unknown>)
    return {
      data: {
        items: [
          { id: 1, dive_code: '201AB', dive_datetime: '2026-01-01T00:00:00Z' },
          { id: 2, dive_code: '201A', dive_datetime: '2026-01-02T00:00:00Z' },
        ],
        next_cursor: null,
      },
    }
  })
  const result = await getCodeAttemptsResult('201A', 'all', 'viewer-a')
  // Every page asked for the exact code — never a prefix search.
  expect(paramsSent).toHaveLength(1)
  expect(paramsSent[0].dive_code).toBe('201A')
  expect('code_prefix' in paramsSent[0]).toBe(false)
  // The display only keeps this code's own rows (defense in depth).
  expect(result.items.map(item => item.dive_code)).toEqual(['201A'])
})

it('an evicted pending full-summary request aborts at the transport and never lands in cache', async () => {
  // The full-summary read is cached like the attempts walk: eviction of a
  // pending entry ABORTS its in-flight api.get at the transport (finding
  // a7a6e37f: the old code left the request live and kept its rows), and
  // a settled-but-dead response never writes back into the bounded cache.
  const empty = { data: { generated_at: '2026-11-02T00:00:00Z', codes: [], activity: { current: {}, previous: {}, months: [], weeks: [] } } }
  let release!: (value?: unknown) => void
  const signals: AbortSignal[] = []
  vi.mocked(api.get).mockImplementation((_url, config) => {
    const params = (config?.params ?? {}) as Record<string, unknown>
    if (params.page === undefined) {
      // The FIRST full-summary request is held pending…
      const signal = (config as { signal?: AbortSignal } | undefined)?.signal
      if (signal) signals.push(signal)
      return new Promise<unknown>(resolve => { release = resolve })
    }
    // …every later summary answers instantly.
    return Promise.resolve({ data: JSON.parse(JSON.stringify(empty.data)) })
  })
  const inFlight = getCodeSummaries({ diver_scope: 'all' }, 'viewer-a')
  // Sixteen later summaries settle instantly; the 16-entry cap evicts the
  // oldest = the pending first summary (its transport signal aborts NOW).
  for (let index = 0; index < 16; index++) {
    await getCodeSummaries({ diver_scope: 'all', page: index }, 'viewer-b')
  }
  // The signal EXISTS and aborted before the held response is released —
  // the old code (no signal forwarded) leaves this array empty.
  expect(signals.length).toBe(1)
  expect(signals[0].aborted).toBe(true)
  release!(JSON.parse(JSON.stringify(empty.data)))
  await inFlight
  // The dead response never reinserts.
  expect(peekCodeSummaries({ diver_scope: 'all' }, 'viewer-a')).toBeNull()
})
