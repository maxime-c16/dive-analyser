import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import PushOptInSection from './PushOptInSection'
import * as notificationsApi from '../services/notificationsApi'

vi.mock('../services/notificationsApi', async importOriginal => {
  const original = await importOriginal<typeof notificationsApi>()
  return {
    ...original,
    getPushConfig: vi.fn(),
    savePushSubscription: vi.fn(),
    deletePushSubscription: vi.fn(),
  }
})

const mockedApi = vi.mocked(notificationsApi, true)

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
  nav.serviceWorker = {
    register: vi.fn(async () => registration),
    getRegistration: vi.fn(async () => registration),
  }
  return { pushManager }
}

beforeEach(() => {
  mockedApi.getPushConfig.mockResolvedValue({ publicKey: 'dGVzdA' })
  mockedApi.savePushSubscription.mockResolvedValue({ endpoint: 'https://push.example.test/new-device', device_label: null })
  mockedApi.deletePushSubscription.mockResolvedValue({ deleted: true })
})

afterEach(() => {
  delete (window as unknown as Record<string, unknown>).PushManager
  delete (window as unknown as Record<string, unknown>).Notification
  const nav = window.navigator as unknown as Record<string, unknown> | undefined
  if (nav) delete nav.serviceWorker
  vi.clearAllMocks()
})

describe('PushOptInSection', () => {
  it('reports unsupported without prompting when the browser has no push', async () => {
    render(<PushOptInSection />)
    expect(await screen.findByText('Push is not supported in this browser.')).toBeInTheDocument()
    // No permission prompt on render: Notification was never installed.
    expect(mockedApi.getPushConfig).not.toHaveBeenCalled()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('reports server-disabled push without prompting', async () => {
    stubBrowser()
    mockedApi.getPushConfig.mockResolvedValue({ publicKey: '' })
    render(<PushOptInSection />)
    expect(await screen.findByText('Push is not set up on the server yet.')).toBeInTheDocument()
  })

  it('opts in on explicit click only (permission requested once, endpoint stored)', async () => {
    const { pushManager } = stubBrowser({ permission: 'granted' })
    render(<PushOptInSection />)
    // Mounting alone never asks for permission.
    expect((window as unknown as { Notification: { requestPermission: () => void } }).Notification.requestPermission).not.toHaveBeenCalled()
    const enable = await screen.findByRole('button', { name: 'Enable push on this device' })
    fireEvent.click(enable)
    await waitFor(() => {
      expect(mockedApi.savePushSubscription).toHaveBeenCalledOnce()
    })
    expect(pushManager.subscribe).toHaveBeenCalledOnce()
    expect(await screen.findByText('On — this device receives push alerts.')).toBeInTheDocument()
  })

  it('explains when permission is denied', async () => {
    stubBrowser({ permission: 'denied' })
    render(<PushOptInSection />)
    const enable = await screen.findByRole('button', { name: 'Enable push on this device' })
    fireEvent.click(enable)
    expect(await screen.findByText(/Notifications are blocked for this site/)).toBeInTheDocument()
    expect(mockedApi.savePushSubscription).not.toHaveBeenCalled()
  })

  it('opts out on explicit click (unsubscribe + server delete)', async () => {
    const existing = {
      endpoint: 'https://push.example.test/old-device',
      unsubscribe: vi.fn(async () => true),
    }
    stubBrowser({ permission: 'granted', subscription: existing })
    render(<PushOptInSection />)
    const disable = await screen.findByRole('button', { name: 'Disable push on this device' })
    fireEvent.click(disable)
    await waitFor(() => {
      expect(mockedApi.deletePushSubscription).toHaveBeenCalledWith('https://push.example.test/old-device')
    })
    expect(existing.unsubscribe).toHaveBeenCalledOnce()
    expect(await screen.findByText('Off — this device gets no push alerts.')).toBeInTheDocument()
  })

  it('stays on with a visible error when the server delete fails', async () => {
    const existing = {
      endpoint: 'https://push.example.test/old-device',
      unsubscribe: vi.fn(async () => true),
    }
    stubBrowser({ permission: 'granted', subscription: existing })
    mockedApi.deletePushSubscription.mockRejectedValueOnce(new Error('HTTP 500'))
    render(<PushOptInSection />)
    const disable = await screen.findByRole('button', { name: 'Disable push on this device' })
    fireEvent.click(disable)
    // Honest opt-out: server is the source of truth, so a failed DELETE
    // keeps the toggle "on" with a retryable error instead of showing "off".
    expect(await screen.findByText('Push settings could not be changed. Try again.')).toBeInTheDocument()
    expect(await screen.findByText('On — this device receives push alerts.')).toBeInTheDocument()
    expect(screen.queryByText('Off — this device gets no push alerts.')).not.toBeInTheDocument()
    // Retry stays available.
    expect(await screen.findByRole('button', { name: 'Disable push on this device' })).toBeInTheDocument()
  })
})
