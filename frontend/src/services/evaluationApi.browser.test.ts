import { beforeEach, expect, it, vi } from 'vitest'
import { api } from './api'
import { getAutomaticScores } from './evaluationApi'
vi.mock('./api', () => ({ api:{ get:vi.fn(), put:vi.fn() } }))
beforeEach(() => { vi.clearAllMocks() })
it('sends the collection filters and page to the server', async () => {
  vi.mocked(api.get).mockResolvedValue({ data:{ items:[], total:0, filter_version:1 } })
  await getAutomaticScores(20, { search:'203C', height:'3m', date_from:'2026-01-01T00:00:00', score_state:'scored', sort:'top' })
  expect(api.get).toHaveBeenCalledWith('/api/v1/evaluations/automatic/mine', { params:{ offset:20, limit:20, search:'203C', height:'3m', date_from:'2026-01-01T00:00:00', score_state:'scored', sort:'top' } })
})
it('rejects silently ignored filters from an older server', async () => {
  vi.mocked(api.get).mockResolvedValue({ data:{ items:[], total:20 } })
  await expect(getAutomaticScores(0, { search:'203C' })).rejects.toThrow('filters unavailable')
  await expect(getAutomaticScores(0, { sort:'top' })).rejects.toThrow('filters unavailable')
})
it('can still display an unfiltered legacy page during a rolling deployment', async () => {
  vi.mocked(api.get).mockResolvedValue({ data:{ items:[], total:0 } })
  await expect(getAutomaticScores()).resolves.toEqual({ items:[], total:0 })
})
it('omits a cleared date rather than sending an invalid empty datetime', async () => {
  vi.mocked(api.get).mockResolvedValue({ data:{ items:[], total:0, filter_version:1 } })
  await getAutomaticScores(0, { date_from:'' })
  expect(api.get).toHaveBeenCalledWith('/api/v1/evaluations/automatic/mine', { params:{ offset:0, limit:20 } })
})
