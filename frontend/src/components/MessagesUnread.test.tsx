import React from 'react'
import { Link, MemoryRouter, Route, Routes } from 'react-router-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { I18nProvider } from '../i18n/I18nProvider'
import { MessagesUnreadBadge, MessagesUnreadProvider, useMessagesUnread, useMessagesUnreadAria } from './MessagesUnread'

vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({ user: { user_id: 7, email: 'alex@example.com', is_admin: false } }),
}))

type Row = { id: number; unread_count?: number }

let conversations: Row[]

function stubInbox() {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.startsWith('/api/v1/messages/conversations')) {
        return { ok: true, json: async () => ({ items: conversations, next_before: null }) } as Response
      }
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
  conversations = [{ id: 1, unread_count: 2 }, { id: 2, unread_count: 1 }, { id: 3 }]
  stubInbox()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('MessagesUnread badge', () => {
  it('totals unread conversations and labels the nav link', async () => {
    renderAt('/dives')
    const badge = await screen.findByTestId('messages-unread-badge')
    expect(badge).toHaveTextContent('3')
    expect(screen.getByTestId('messages-link')).toHaveAttribute('aria-label', 'Messages, 3 unread')
    expect(screen.getByTestId('unread-count')).toHaveTextContent('3')
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
    conversations = [{ id: 1 }, { id: 2 }, { id: 3 }]
    fireEvent.click(screen.getByRole('button', { name: 'Resync' }))
    await waitFor(() => expect(screen.queryByTestId('messages-unread-badge')).toBeNull())
    expect(screen.getByTestId('unread-count')).toHaveTextContent('0')
  })

  it('caps the pill at 99+', async () => {
    conversations = [{ id: 1, unread_count: 120 }]
    renderAt('/dives')
    expect(await screen.findByTestId('messages-unread-badge')).toHaveTextContent('99+')
  })

  it('stays quiet (no badge, no crash) when the inbox is unreachable', async () => {
    vi.mocked(fetch).mockRejectedValue(new Error('down'))
    renderAt('/dives')
    await waitFor(() => expect(fetch).toHaveBeenCalled())
    expect(screen.queryByTestId('messages-unread-badge')).toBeNull()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByTestId('messages-link')).not.toHaveAttribute('aria-label')
  })
})
