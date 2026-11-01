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
