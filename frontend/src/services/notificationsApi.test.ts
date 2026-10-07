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

describe('notificationsApi', () => {
  it('lists with unread_only and limit, same-origin credentials', async () => {
    const { listNotifications } = await import('./notificationsApi')
    mockFetch(() => ({ items: [], unread_count: 0 }))
    await listNotifications({ unreadOnly: true, limit: 10 })
    expect(fetch).toHaveBeenCalledOnce()
    const [url, init] = vi.mocked(fetch).mock.calls[0]
    expect(url).toBe('/api/v1/notifications?unread_only=true&limit=10')
    expect(init).toMatchObject({ credentials: 'same-origin' })
  })

  it('lists with the default limit when no options are given', async () => {
    const { listNotifications } = await import('./notificationsApi')
    const items = [{ id: 1, type: 'milestone', title: 'PB', body: '', dive_id: null, read_at: null, created_at: null }]
    mockFetch(() => ({ items, unread_count: 1 }))
    await expect(listNotifications()).resolves.toEqual({ items, unread_count: 1 })
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe('/api/v1/notifications?limit=50')
  })

  it('marks one notification read via POST', async () => {
    const { markNotificationRead } = await import('./notificationsApi')
    const row = { id: 3, type: 'new_comment', title: 'Hi', body: null, dive_id: 7, read_at: '2026-10-06T00:00:00Z', created_at: null }
    mockFetch(() => row)
    await expect(markNotificationRead(3)).resolves.toEqual(row)
    expect(fetch).toHaveBeenCalledWith('/api/v1/notifications/3/read', {
      method: 'POST',
      credentials: 'same-origin',
    })
  })

  it('marks everything read via POST', async () => {
    const { markAllNotificationsRead } = await import('./notificationsApi')
    mockFetch(() => ({ marked: 4 }))
    await expect(markAllNotificationsRead()).resolves.toEqual({ marked: 4 })
    expect(fetch).toHaveBeenCalledWith('/api/v1/notifications/read-all', {
      method: 'POST',
      credentials: 'same-origin',
    })
  })

  it('reads and writes prefs (explicit defaults to [] when absent)', async () => {
    const { getNotificationPrefs, setNotificationPref } = await import('./notificationsApi')
    mockFetch((url, init) => {
      if (init?.method === 'PUT') {
        expect(url).toBe('/api/v1/notification-prefs')
        expect(init.headers).toMatchObject({ 'Content-Type': 'application/json' })
        return JSON.parse(init.body as string)
      }
      return { prefs: { milestone: true, guest_activity: false } }
    })
    await expect(getNotificationPrefs()).resolves.toEqual({
      prefs: { milestone: true, guest_activity: false },
      explicit: [],
    })
    await expect(setNotificationPref('guest_activity', true)).resolves.toEqual({
      type: 'guest_activity',
      enabled: true,
    })
  })

  it('forwards the server explicit override list when present', async () => {
    const { getNotificationPrefs } = await import('./notificationsApi')
    mockFetch(() => ({ prefs: { milestone: false }, explicit: ['milestone', 'new_comment'] }))
    await expect(getNotificationPrefs()).resolves.toEqual({
      prefs: { milestone: false },
      explicit: ['milestone', 'new_comment'],
    })
  })

  it('throws on HTTP errors', async () => {
    const { listNotifications } = await import('./notificationsApi')
    vi.mocked(fetch).mockResolvedValue({ ok: false, status: 401 } as Response)
    await expect(listNotifications()).rejects.toThrow('HTTP 401')
  })

  it('reads push config (empty publicKey when server push is off)', async () => {
    const { getPushConfig } = await import('./notificationsApi')
    mockFetch(() => ({ publicKey: '' }))
    await expect(getPushConfig()).resolves.toEqual({ publicKey: '' })
    expect(fetch).toHaveBeenCalledWith('/api/v1/push-config', {
      credentials: 'same-origin',
      cache: 'no-store',
    })
  })

  it('saves and deletes push subscriptions with same-origin credentials', async () => {
    const { savePushSubscription, deletePushSubscription } = await import('./notificationsApi')
    const input = {
      endpoint: 'https://push.example.test/device',
      keys: { p256dh: 'fake-p256dh', auth: 'fake-auth' },
      device_label: 'test device',
    }
    mockFetch((url, init) => {
      if (url === '/api/v1/push-subscriptions' && init?.method === 'POST') {
        expect(JSON.parse(init.body as string)).toEqual(input)
        return { endpoint: input.endpoint, device_label: 'test device' }
      }
      if (url === '/api/v1/push-subscriptions' && init?.method === 'DELETE') {
        expect(JSON.parse(init.body as string)).toEqual({ endpoint: input.endpoint })
        return { deleted: true }
      }
      throw new Error(`unexpected ${init?.method} ${url}`)
    })
    await expect(savePushSubscription(input)).resolves.toEqual({
      endpoint: input.endpoint,
      device_label: 'test device',
    })
    await expect(deletePushSubscription(input.endpoint)).resolves.toEqual({ deleted: true })
  })
})
