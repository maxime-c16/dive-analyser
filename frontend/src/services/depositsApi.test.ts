import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

function mockFetch(handler: (url: string, init?: RequestInit) => unknown) {
  vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString()
    const payload = handler(url, init)
    return {
      ok: true,
      json: async () => payload,
    } as Response
  })
}

describe('depositsApi', () => {
  it('lists pending batches, same-origin credentials', async () => {
    const { listPendingBatches } = await import('./depositsApi')
    mockFetch(() => ({ batches: [{ batch_id: 'b1', pending: 2 }] }))
    await expect(listPendingBatches()).resolves.toEqual([{ batch_id: 'b1', pending: 2 }])
    const [url, init] = vi.mocked(fetch).mock.calls[0]
    expect(url).toBe('/api/v1/deposits/pending')
    expect(init).toMatchObject({ credentials: 'same-origin' })
  })

  it('accepts a whole batch with an empty body when no ids are given', async () => {
    const { acceptBatch } = await import('./depositsApi')
    mockFetch((url, init) => {
      expect(url).toBe('/api/v1/deposits/batches/b1/accept')
      expect(JSON.parse(init?.body as string)).toEqual({})
      return { batch_id: 'b1', accepted: [1, 2] }
    })
    await expect(acceptBatch('b1')).resolves.toEqual({ batch_id: 'b1', accepted: [1, 2] })
  })

  it('accepts a subset when ids are given', async () => {
    const { acceptBatch } = await import('./depositsApi')
    mockFetch((url, init) => {
      expect(JSON.parse(init?.body as string)).toEqual({ dive_ids: [2] })
      return { batch_id: 'b1', accepted: [2] }
    })
    await expect(acceptBatch('b1', [2])).resolves.toEqual({ batch_id: 'b1', accepted: [2] })
  })

  it('redeems claims without session credentials', async () => {
    const { peekClaim, redeemClaim } = await import('./depositsApi')
    mockFetch(() => ({ batch_id: 'b1' }))
    await peekClaim('tok')
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe('/api/v1/deposits/claim/tok')
    await redeemClaim('tok')
    const [url, init] = vi.mocked(fetch).mock.calls[1]
    expect(url).toBe('/api/v1/deposits/claim/redeem')
    expect(init).toMatchObject({ method: 'POST' })
    expect(init).not.toMatchObject({ credentials: 'same-origin' })
  })

  it('defaults the batch email pref to on when the call fails', async () => {
    const { getBatchEmailPref } = await import('./depositsApi')
    vi.mocked(fetch).mockResolvedValue({ ok: false, status: 500 } as Response)
    await expect(getBatchEmailPref()).resolves.toBe(true)
  })
})
