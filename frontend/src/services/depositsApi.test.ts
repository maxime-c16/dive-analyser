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

  it('peeks and redeems claims via POST bodies (token never in the URL)', async () => {
    const { claimTokenFromHash, peekClaim, redeemClaim } = await import('./depositsApi')
    expect(claimTokenFromHash('#t=tok123')).toBe('tok123')
    expect(claimTokenFromHash('')).toBe('')
    mockFetch(() => ({ batch_id: 'b1' }))
    await peekClaim('tok')
    const [peekUrl, peekInit] = vi.mocked(fetch).mock.calls[0]
    expect(peekUrl).toBe('/api/v1/deposits/claim/peek')
    expect(peekInit).toMatchObject({ method: 'POST' })
    expect(JSON.parse(peekInit?.body as string)).toEqual({ token: 'tok' })
    await redeemClaim('tok')
    const [url, init] = vi.mocked(fetch).mock.calls[1]
    expect(url).toBe('/api/v1/deposits/claim/redeem')
    expect(init).toMatchObject({ method: 'POST' })
    expect(init).not.toMatchObject({ credentials: 'same-origin' })
  })

  it('scopes review and accept calls to the diver and builds diver-aware links', async () => {
    const { acceptBatch, batchReviewPath, getBatch } = await import('./depositsApi')
    expect(batchReviewPath('b1', 7)).toBe('/deposits/b1?diver=7')
    expect(batchReviewPath('b1', null)).toBe('/deposits/b1')
    mockFetch(() => ({ batch_id: 'b1', accepted: [] }))
    await getBatch('b1', 7)
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe('/api/v1/deposits/batches/b1?diver_id=7')
    await acceptBatch('b1', undefined, 7)
    expect(vi.mocked(fetch).mock.calls[1][0]).toBe('/api/v1/deposits/batches/b1/accept?diver_id=7')
  })

  it('lists, releases and discards held emails (admin confirm)', async () => {
    const { discardHeldEmails, listHeldEmails, releaseHeldEmails } = await import('./depositsApi')
    mockFetch(() => ({ emails: [{ id: 3, diver_name: 'Alice', clips: 2 }] }))
    await expect(listHeldEmails()).resolves.toEqual([{ id: 3, diver_name: 'Alice', clips: 2 }])
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe('/api/v1/deposits/outbox/held')
    mockFetch((url, init) => {
      expect(url).toBe('/api/v1/deposits/outbox/release')
      expect(JSON.parse(init?.body as string)).toEqual({ ids: [3] })
      return { released: 1 }
    })
    await expect(releaseHeldEmails([3])).resolves.toBe(1)
    mockFetch((url, init) => {
      expect(url).toBe('/api/v1/deposits/outbox/discard')
      expect(JSON.parse(init?.body as string)).toEqual({})
      return { discarded: 4 }
    })
    await expect(discardHeldEmails()).resolves.toBe(4)
  })

  it('defaults the batch email pref to on when the call fails', async () => {
    const { getBatchEmailPref } = await import('./depositsApi')
    vi.mocked(fetch).mockResolvedValue({ ok: false, status: 500 } as Response)
    await expect(getBatchEmailPref()).resolves.toBe(true)
  })
})
