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
  // it (FIFO, pending included). The evicted walk must stop at the page
  // boundary and NEVER write back — the old code walked to its cap and
  // reinserted, both leaking the bound under rapid code switches.
  const callsByCode = new Map<string, number>()
  let gateUsed = false
  let releaseA!: (value: unknown) => void
  vi.mocked(api.get).mockImplementation(async (_url, config) => {
    const params = (config?.params ?? {}) as { code_prefix?: string; cursor?: string }
    const code = params.code_prefix ?? '?'
    callsByCode.set(code, (callsByCode.get(code) ?? 0) + 1)
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
  // Release the held page: the walk lands it, then the liveness stops it.
  releaseA!({ data: { items: [{ id: 2, dive_code: '599D', dive_datetime: '2026-01-02T00:00:00Z' }], next_cursor: 'cursor-599D-2' } })
  await inFlight
  // The old code walked to its 10-page cap here (callsByCode 10) and
  // reinserted (peek non-null): both leak the bounded cap.
  expect(callsByCode.get('599D')).toBe(2)
  expect(peekCodeAttempts('599D', 'all', 'viewer-a')).toBeNull()
})
