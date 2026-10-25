import { afterEach, expect, it, vi } from 'vitest'
import { api } from './api'
import { clearCodeCommunityCache, getCodeCommunity } from './codeCommunityApi'

vi.mock('./api', () => ({ api: { get: vi.fn() } }))

const payload = { dive_code: '101C', members: [], hidden_count: 0 }

afterEach(() => {
  clearCodeCommunityCache()
  vi.mocked(api.get).mockReset()
})

it('shares one fetch per code, height and viewer', async () => {
  vi.mocked(api.get).mockResolvedValue({ data: payload })
  const first = getCodeCommunity('101C', '', 'viewer-a')
  const second = getCodeCommunity('101C', '', 'viewer-a')
  await expect(first).resolves.toEqual(payload)
  await expect(second).resolves.toEqual(payload)
  expect(api.get).toHaveBeenCalledTimes(1)
})

it('refetches for another viewer because the response omits their own divers', async () => {
  vi.mocked(api.get).mockResolvedValue({ data: payload })
  await getCodeCommunity('101C', '', 'viewer-a')
  await getCodeCommunity('101C', '', 'viewer-b')
  expect(api.get).toHaveBeenCalledTimes(2)
})

it('drops failures and cleared entries so the next read retries', async () => {
  vi.mocked(api.get).mockRejectedValueOnce(new Error('offline'))
  await expect(getCodeCommunity('101C', '', 'viewer-a')).rejects.toThrow('offline')
  vi.mocked(api.get).mockResolvedValue({ data: payload })
  await expect(getCodeCommunity('101C', '', 'viewer-a')).resolves.toEqual(payload)
  clearCodeCommunityCache()
  await getCodeCommunity('101C', '', 'viewer-a')
  expect(api.get).toHaveBeenCalledTimes(3)
})
