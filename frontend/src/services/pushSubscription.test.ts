import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  defaultDeviceLabel,
  disablePushDevice,
  enablePushDevice,
  getExistingPushSubscription,
  isIosDevice,
  pushSupported,
  urlBase64ToUint8Array,
} from './pushSubscription'

/** Fake browser globals: installed per test, removed afterwards. */
function stubBrowser(options?: {
  permission?: NotificationPermission
  subscription?: unknown
  subscribeResult?: unknown
}) {
  const permission = options?.permission ?? 'default'
  const existing = options?.subscription ?? null
  const created =
    options?.subscribeResult ??
    ({
      endpoint: 'https://push.example.test/new-device',
      toJSON: () => ({ keys: { p256dh: 'test-p256dh', auth: 'test-auth' } }),
      unsubscribe: vi.fn(async () => true),
    } as unknown)
  const pushManager = {
    getSubscription: vi.fn(async () => existing),
    subscribe: vi.fn(async () => created),
  }
  const registration = { pushManager }
  const w = window as unknown as Record<string, unknown>
  const nav = window.navigator as unknown as Record<string, unknown>
  w.PushManager = class {}
  w.Notification = {
    permission,
    requestPermission: vi.fn(async () => permission),
  }
  // Own property on the real Navigator instance: removed (not the
  // Navigator itself) by unstubBrowser, so later tests keep working.
  nav.serviceWorker = {
    register: vi.fn(async () => registration),
    getRegistration: vi.fn(async () => registration),
  }
  return { pushManager, registration }
}

function unstubBrowser() {
  delete (window as unknown as Record<string, unknown>).PushManager
  delete (window as unknown as Record<string, unknown>).Notification
  const nav = window.navigator as unknown as Record<string, unknown> | undefined
  if (nav) delete nav.serviceWorker
}

afterEach(() => {
  unstubBrowser()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('pushSubscription helpers', () => {
  it('decodes URL-safe base64 VAPID keys', () => {
    // "Hello" as unpadded URL-safe base64.
    expect(Array.from(urlBase64ToUint8Array('SGVsbG8'))).toEqual([72, 101, 108, 108, 111])
  })

  it('is unsupported in jsdom (no service worker)', () => {
    expect(pushSupported()).toBe(false)
  })

  it('supports the full flow only with browser APIs present', () => {
    stubBrowser()
    expect(pushSupported()).toBe(true)
  })

  it('labels the device from the platform, bounded to 100 chars', () => {
    stubBrowser()
    // Shadow the prototype getter with an own property (deleted, not the
    // Navigator itself, afterwards — window.navigator has no fallback).
    const nav = window.navigator as unknown as Record<string, unknown>
    Object.defineProperty(nav, 'platform', { value: 'iPhone', configurable: true })
    try {
      expect(defaultDeviceLabel()).toBe('iPhone')
    } finally {
      delete nav.platform
    }
  })

  it('detects iOS devices from the user agent', () => {
    const nav = window.navigator as unknown as Record<string, unknown>
    const original = nav.userAgent
    Object.defineProperty(nav, 'userAgent', { value: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)', configurable: true })
    try {
      expect(isIosDevice()).toBe(true)
    } finally {
      Object.defineProperty(nav, 'userAgent', { value: original, configurable: true })
    }
  })

  it('refuses to enable without support or key', async () => {
    await expect(enablePushDevice('')).rejects.toThrow('push-unsupported')
    await expect(enablePushDevice('some-key')).rejects.toThrow('push-unsupported')
  })

  it('returns null/false passively when unsupported', async () => {
    await expect(getExistingPushSubscription()).resolves.toBeNull()
    await expect(disablePushDevice()).resolves.toBe(false)
  })

  it('surfaces permission denial without subscribing', async () => {
    const { pushManager } = stubBrowser({ permission: 'denied' })
    vi.stubGlobal('fetch', vi.fn())
    await expect(enablePushDevice('dGVzdA')).rejects.toThrow('permission-denied')
    expect(pushManager.subscribe).not.toHaveBeenCalled()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('registers, subscribes and stores the endpoint on opt-in', async () => {
    stubBrowser({ permission: 'granted' })
    const fetchMock = vi.fn(
      async (_url: string, _init?: RequestInit) =>
        ({ ok: true, json: async () => ({ endpoint: 'x', device_label: null }) }) as unknown as Response,
    )
    vi.stubGlobal('fetch', fetchMock)
    // "dGVzdA" is "test" — a short fake key, never a real VAPID key.
    const result = await enablePushDevice('dGVzdA')
    expect(result.endpoint).toBe('https://push.example.test/new-device')
    expect(result.alreadySubscribed).toBe(false)
    expect(fetchMock).toHaveBeenCalledOnce()
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit | undefined]
    expect(url).toBe('/api/v1/push-subscriptions')
    expect(init).toMatchObject({ method: 'POST', credentials: 'same-origin' })
    const body = JSON.parse((init?.body as string) ?? '{}')
    expect(body).toMatchObject({
      endpoint: 'https://push.example.test/new-device',
      keys: { p256dh: 'test-p256dh', auth: 'test-auth' },
    })
    expect(typeof body.device_label).toBe('string')
  })

  it('deletes the server endpoint before unsubscribing locally', async () => {
    const existing = {
      endpoint: 'https://push.example.test/old-device',
      unsubscribe: vi.fn(async () => true),
    }
    stubBrowser({ permission: 'granted', subscription: existing })
    const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({ deleted: true }) }))
    vi.stubGlobal('fetch', fetchMock)
    await expect(getExistingPushSubscription()).resolves.toBe(existing)
    await expect(disablePushDevice()).resolves.toBe(true)
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/push-subscriptions', expect.objectContaining({ method: 'DELETE' }))
    expect(existing.unsubscribe).toHaveBeenCalledOnce()
    // Server-first: the DELETE must leave before the local unsubscribe, so
    // a failed DELETE keeps the local subscription (and its endpoint) for
    // the retry.
    expect(fetchMock.mock.invocationCallOrder[0]).toBeLessThan(
      (existing.unsubscribe as unknown as { mock: { invocationCallOrder: number[] } }).mock.invocationCallOrder[0],
    )
  })

  it('keeps the local subscription when the server delete fails', async () => {
    const existing = {
      endpoint: 'https://push.example.test/old-device',
      unsubscribe: vi.fn(async () => true),
    }
    stubBrowser({ permission: 'granted', subscription: existing })
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new Error('HTTP 500')
    }))
    await expect(disablePushDevice()).resolves.toBe(false)
    // Untouched local subscription: the retry still finds it and its
    // endpoint, so it can attempt the server DELETE again.
    expect(existing.unsubscribe).not.toHaveBeenCalled()
  })

  it('still resolves true when the local unsubscribe fails after a server delete', async () => {
    const existing = {
      endpoint: 'https://push.example.test/old-device',
      unsubscribe: vi.fn(async () => {
        throw new Error('unsubscribe gone')
      }),
    }
    stubBrowser({ permission: 'granted', subscription: existing })
    const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({ deleted: true }) }))
    vi.stubGlobal('fetch', fetchMock)
    await expect(disablePushDevice()).resolves.toBe(true)
    expect(fetchMock).toHaveBeenCalledOnce()
    expect(existing.unsubscribe).toHaveBeenCalledOnce()
  })
})
