import React from 'react'
import { Link, MemoryRouter, Route, Routes } from 'react-router-dom'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { I18nProvider } from '../i18n/I18nProvider'
import { MessagesUnreadBadge, MessagesUnreadProvider, useMessagesUnread, useMessagesUnreadAria } from './MessagesUnread'

vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({ user: { user_id: 7, email: 'alex@example.com', is_admin: false } }),
}))

const UNREAD_URL = '/api/v1/messages/unread-count'

let unreadTotal: number

function jsonResponse(payload: unknown) {
  return { ok: true, json: async () => payload } as Response
}

function stubUnread() {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.startsWith(UNREAD_URL)) return jsonResponse({ unread_count: unreadTotal })
      throw new Error(`unexpected ${url}`)
    }),
  )
}

function Probe() {
  const aria = useMessagesUnreadAria()
  const { unreadCount, refresh } = useMessagesUnread()
  return (
    <>
      <Link to="/messages" aria-label={aria} data-testid="messages-link">Messages</Link>
      <MessagesUnreadBadge />
      <span data-testid="unread-count">{unreadCount}</span>
      <button type="button" onClick={refresh}>Resync</button>
    </>
  )
}

function renderAt(path: string) {
  return render(
    <I18nProvider>
      <MemoryRouter initialEntries={[path]}>
        <MessagesUnreadProvider>
          <Routes>
            <Route path="/dives" element={<Probe />} />
            <Route path="/messages" element={<Probe />} />
          </Routes>
        </MessagesUnreadProvider>
      </MemoryRouter>
    </I18nProvider>,
  )
}

beforeEach(() => {
  unreadTotal = 3
  stubUnread()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('MessagesUnread badge', () => {
  it('shows the server total and labels the nav link', async () => {
    renderAt('/dives')
    const badge = await screen.findByTestId('messages-unread-badge')
    expect(badge).toHaveTextContent('3')
    expect(screen.getByTestId('messages-link')).toHaveAttribute('aria-label', 'Messages, 3 unread')
    expect(screen.getByTestId('unread-count')).toHaveTextContent('3')
    expect(vi.mocked(fetch).mock.calls.map(([input]) => String(input))).toContain(UNREAD_URL)
  })

  it('discards the badge while the Messages tab is being read', async () => {
    renderAt('/messages')
    await waitFor(() => expect(screen.getByTestId('unread-count')).toHaveTextContent('3'))
    expect(screen.queryByTestId('messages-unread-badge')).toBeNull()
    expect(screen.getByTestId('messages-link')).not.toHaveAttribute('aria-label')
  })

  it('clears the badge once a refresh sees the messages read', async () => {
    renderAt('/dives')
    expect(await screen.findByTestId('messages-unread-badge')).toHaveTextContent('3')
    // The thread wrote its read receipts; the resync reflects them.
    unreadTotal = 0
    fireEvent.click(screen.getByRole('button', { name: 'Resync' }))
    await waitFor(() => expect(screen.queryByTestId('messages-unread-badge')).toBeNull())
    expect(screen.getByTestId('unread-count')).toHaveTextContent('0')
  })

  it('caps the pill at 99+', async () => {
    unreadTotal = 120
    renderAt('/dives')
    expect(await screen.findByTestId('messages-unread-badge')).toHaveTextContent('99+')
  })

  it('trusts the aggregate for counts beyond five inbox pages', async () => {
    // 260 unread conversations sit past the 5 x 50 rows a client could page.
    unreadTotal = 260
    renderAt('/dives')
    expect(await screen.findByTestId('unread-count')).toHaveTextContent('260')
    expect(screen.getByTestId('messages-unread-badge')).toHaveTextContent('99+')
  })

  it('stays quiet (no badge, no crash) when the inbox is unreachable', async () => {
    vi.mocked(fetch).mockRejectedValue(new Error('down'))
    renderAt('/dives')
    await waitFor(() => expect(fetch).toHaveBeenCalled())
    expect(screen.queryByTestId('messages-unread-badge')).toBeNull()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByTestId('messages-link')).not.toHaveAttribute('aria-label')
  })

  it('never lets a superseded response restore a cleared count', async () => {
    let release!: (response: Response) => void
    const hanging = new Promise<Response>(resolve => { release = resolve })
    let calls = 0
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      // The first (initial) load hangs; any later refresh answers immediately.
      if (String(input).includes(UNREAD_URL) && ++calls === 1) return hanging
      return Promise.resolve(jsonResponse({ unread_count: 0 }))
    }))
    renderAt('/dives')
    fireEvent.click(screen.getByRole('button', { name: 'Resync' }))
    await waitFor(() => expect(vi.mocked(fetch).mock.calls.length).toBeGreaterThanOrEqual(2))
    await waitFor(() => expect(screen.getByTestId('unread-count')).toHaveTextContent('0'))
    // The stale response lands afterwards with unread messages: it must be dropped.
    await act(async () => { release(jsonResponse({ unread_count: 9 })) })
    expect(screen.getByTestId('unread-count')).toHaveTextContent('0')
    expect(screen.queryByTestId('messages-unread-badge')).toBeNull()
  })
})
