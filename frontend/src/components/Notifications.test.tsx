import React from 'react'
import { MemoryRouter } from 'react-router-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { I18nProvider } from '../i18n/I18nProvider'
import { NotificationsButton, NotificationsProvider } from './Notifications'
import NotificationsPage from '../pages/Notifications'

vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({ user: { user_id: 7, email: 'alex@example.com', is_admin: false } }),
}))

type Row = {
  id: number
  type: string
  title: string
  body: string | null
  dive_id: number | null
  read_at: string | null
  created_at: string
}

const unreadRow: Row = {
  id: 3,
  type: 'new_comment',
  title: 'New comment on 103B',
  body: 'Nice entry!',
  dive_id: 7,
  read_at: null,
  created_at: '2026-10-06T08:00:00Z',
}

const readRow: Row = {
  id: 2,
  type: 'milestone',
  title: 'Personal best: 103B',
  body: null,
  dive_id: null,
  read_at: '2026-10-05T08:00:00Z',
  created_at: '2026-10-05T08:00:00Z',
}

let rows: Row[]

function stubInbox() {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.startsWith('/api/v1/notifications/') && url.endsWith('/read')) {
        const id = Number(url.split('/')[4])
        rows = rows.map(row => (row.id === id ? { ...row, read_at: '2026-10-06T09:00:00Z' } : row))
        return { ok: true, json: async () => rows.find(row => row.id === id) } as Response
      }
      if (url === '/api/v1/notifications/read-all') {
        rows = rows.map(row => (row.read_at ? row : { ...row, read_at: '2026-10-06T09:00:00Z' }))
        return { ok: true, json: async () => ({ marked: 1 }) } as Response
      }
      if (url.startsWith('/api/v1/notifications')) {
        return {
          ok: true,
          json: async () => ({
            items: [...rows].sort((a, b) => b.id - a.id),
            unread_count: rows.filter(row => !row.read_at).length,
          }),
        } as Response
      }
      throw new Error(`unexpected ${init?.method ?? 'GET'} ${url}`)
    }),
  )
}

function renderBell() {
  return render(
    <I18nProvider>
      <MemoryRouter>
        <NotificationsProvider>
          <NotificationsButton />
        </NotificationsProvider>
      </MemoryRouter>
    </I18nProvider>,
  )
}

function renderPage() {
  return render(
    <I18nProvider>
      <MemoryRouter>
        <NotificationsProvider>
          <NotificationsPage />
        </NotificationsProvider>
      </MemoryRouter>
    </I18nProvider>,
  )
}

beforeEach(() => {
  localStorage.clear()
  rows = [{ ...unreadRow }, { ...readRow }]
  stubInbox()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('NotificationsButton', () => {
  it('shows the unread count badge with an accessible label', async () => {
    renderBell()
    const link = await screen.findByRole('link', { name: 'Open notifications, 1 unread' })
    expect(link).toHaveAttribute('href', '/notifications')
    expect(screen.getByTestId('notifications-badge')).toHaveTextContent('1')
  })

  it('hides the badge when everything is read', async () => {
    rows = [{ ...readRow }]
    renderBell()
    const link = await screen.findByRole('link', { name: 'Open notifications' })
    expect(link).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByTestId('notifications-badge')).toBeNull())
  })

  it('stays quiet (no badge, no crash) when the inbox is unreachable', async () => {
    vi.mocked(fetch).mockRejectedValue(new Error('down'))
    renderBell()
    const link = await screen.findByRole('link', { name: 'Open notifications' })
    expect(link).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})

describe('Notifications page', () => {
  it('lists newest first with a deep link to the dive', async () => {
    renderPage()
    expect(await screen.findByText('New comment on 103B')).toBeInTheDocument()
    expect(screen.getByText('Personal best: 103B')).toBeInTheDocument()
    const diveLink = screen.getByRole('link', { name: 'Open dive' })
    expect(diveLink).toHaveAttribute('href', '/dives?clip=7')
  })

  it('filters to unread only', async () => {
    renderPage()
    await screen.findByText('New comment on 103B')
    fireEvent.click(screen.getByRole('button', { name: /Unread \(1\)/ }))
    expect(screen.getByText('New comment on 103B')).toBeInTheDocument()
    expect(screen.queryByText('Personal best: 103B')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Show all' }))
    expect(screen.getByText('Personal best: 103B')).toBeInTheDocument()
  })

  it('fetches unread_only from the server when the unread filter is active', async () => {
    renderPage()
    await screen.findByText('New comment on 103B')
    fireEvent.click(screen.getByRole('button', { name: /Unread \(1\)/ }))
    await waitFor(() => {
      const urls = vi.mocked(fetch).mock.calls.map(([input]) =>
        typeof input === 'string' ? input : input.toString(),
      )
      expect(urls.some(url => url.includes('unread_only=true'))).toBe(true)
    })
  })

  it('marks one notification read', async () => {
    renderPage()
    await screen.findByText('New comment on 103B')
    fireEvent.click(screen.getByRole('button', { name: 'Mark as read' }))
    await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/v1/notifications/3/read', expect.anything()))
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Mark as read' })).not.toBeInTheDocument())
  })

  it('marks everything read (read rows stay visible under Show all)', async () => {
    renderPage()
    await screen.findByText('New comment on 103B')
    fireEvent.click(screen.getByRole('button', { name: 'Mark all as read' }))
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith('/api/v1/notifications/read-all', expect.anything()),
    )
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: 'Mark as read' })).not.toBeInTheDocument(),
    )
    fireEvent.click(screen.getByRole('button', { name: /Unread \(0\)/ }))
    expect(screen.getByText('You are all caught up.')).toBeInTheDocument()
  })

  it('shows an empty state when the inbox has no rows', async () => {
    rows = []
    renderPage()
    expect(await screen.findByText('No notifications yet.')).toBeInTheDocument()
  })

  it('shows an error with retry when loading fails', async () => {
    vi.mocked(fetch).mockRejectedValue(new Error('down'))
    renderPage()
    expect(await screen.findByText('Notifications could not be loaded.')).toBeInTheDocument()
    stubInbox()
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByText('New comment on 103B')).toBeInTheDocument()
  })
})
