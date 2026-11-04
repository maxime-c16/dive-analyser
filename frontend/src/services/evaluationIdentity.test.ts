import { expect, it, vi } from 'vitest'
import { api } from './api'
import { getAutomaticScores, loadAutomaticIdentities } from './evaluationApi'

vi.mock('./api', () => ({ api: { get: vi.fn() } }))

it('hydrates only the current score page with at most four reads and preserves scores on an identity failure', async () => {
  const items = Array.from({ length: 20 }, (_, i) => ({ dive_id: i + 1, mean_score: i, excluded: i % 2 === 0 }))
  let active = 0, peak = 0
  vi.mocked(api.get).mockImplementation(async (url) => {
    if (url === '/api/v1/evaluations/automatic/mine') return { data: { items, total: 9000 } }
    active++; peak = Math.max(peak, active)
    await new Promise(resolve => setTimeout(resolve, 1))
    active--
    if (url === '/api/v1/dives/3') throw new Error('unavailable')
    return { data: { id: Number(String(url).split('/').pop()), dive_datetime: '2026-10-18T17:23:24' } }
  })
  const page = await getAutomaticScores(40)
  expect(api.get).toHaveBeenCalledWith('/api/v1/evaluations/automatic/mine', { params: { offset: 40, limit: 20 } })
  expect(api.get).toHaveBeenCalledTimes(1)
  await loadAutomaticIdentities(page.items, (id, identity) => { const row = page.items.find(row => row.dive_id === id); if (row) row.identity = identity })
  expect(api.get).toHaveBeenCalledTimes(21)
  expect(peak).toBe(4)
  expect(page.total).toBe(9000)
  expect(page.items[0].identity?.id).toBe(1)
  expect(page.items[2]).toEqual({ dive_id: 3, mean_score: 2, excluded: true })
  expect(page.items[19].identity?.id).toBe(20)
})

it('stops scheduling identity reads after the page is abandoned', async () => {
  vi.clearAllMocks()
  const controller = new AbortController()
  const pending: Array<() => void> = []
  vi.mocked(api.get).mockImplementation(() => new Promise(resolve => pending.push(() => resolve({ data: { id: 1 } }))))
  const receive = vi.fn()
  const items = Array.from({ length: 20 }, (_, i) => ({ dive_id: i + 1 }))
  const work = loadAutomaticIdentities(items as Parameters<typeof loadAutomaticIdentities>[0], receive, controller.signal)
  expect(api.get).toHaveBeenCalledTimes(4)
  controller.abort()
  pending.forEach(resolve => resolve())
  await work
  expect(receive).not.toHaveBeenCalled()
  expect(api.get).toHaveBeenCalledTimes(4)
})
