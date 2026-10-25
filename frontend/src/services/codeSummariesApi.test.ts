import { afterEach, expect, it, vi } from 'vitest'
import { api } from './api'
import {
  clearCodeSummaryCache, getCodeAttempts, getCodeSummaries,
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
