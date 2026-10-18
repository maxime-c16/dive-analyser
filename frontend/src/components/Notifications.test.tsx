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
  calendar?: Record<string, unknown>
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

  it('refetches unread_only when the provider poll refreshes', async () => {
    renderPage()
    await screen.findByText('New comment on 103B')
    fireEvent.click(screen.getByRole('button', { name: /Unread \(1\)/ }))
    const unreadCalls = () =>
      vi
        .mocked(fetch)
        .mock.calls.filter(([input]) =>
          (typeof input === 'string' ? input : input.toString()).includes('unread_only=true'),
        ).length
    await waitFor(() => expect(unreadCalls()).toBeGreaterThanOrEqual(1))
    const before = unreadCalls()
    // Same path as the 60s poll: the provider reloads, bumps its tick, and
    // the filtered page replays its unread_only fetch.
    window.dispatchEvent(new Event('focus'))
    await waitFor(() => expect(unreadCalls()).toBeGreaterThan(before))
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

describe('Calendar alerts in the inbox (Task05)', () => {
  const moved: Row = {
    id: 9,
    type: 'calendar_change',
    title: 'Groupe A training',
    body: null,
    dive_id: null,
    read_at: null,
    created_at: '2026-10-20T08:00:00Z',
    calendar: {
      redacted: false,
      kind: 'change',
      event_id: 4,
      occurrence_id: 12,
      url: '/calendar/o/12',
      event_title: 'Groupe A training',
      timezone: 'Europe/Paris',
      starts_at: '2026-10-22T17:00:00Z',
      start_date: null,
      all_day: false,
      venue_name: 'Piscine Maurice Thorez',
      status: 'scheduled',
      changes: [
        { kinds: ['time_changed', 'venue_changed'], old_start: '2026-10-21T17:00:00Z', new_start: '2026-10-22T17:00:00Z' },
      ],
      total: 3,
    },
  }
  const redacted: Row = {
    id: 8,
    type: 'calendar_change',
    title: 'Calendar update',
    body: null,
    dive_id: null,
    read_at: null,
    created_at: '2026-10-19T08:00:00Z',
    calendar: { redacted: true },
  }

  it('renders what changed with an authorized deep link to the session', async () => {
    rows = [{ ...moved }]
    renderPage()
    expect(await screen.findByText('Event changed · Groupe A training')).toBeInTheDocument()
    const text = screen.getByText(/Moved:/).textContent ?? ''
    expect(text).toContain('Place changed: Piscine Maurice Thorez')
    expect(text).toContain('+2 more sessions')
    expect(text).toMatch(/07:00 PM.*→.*07:00 PM/) // 17:00Z shown in the event timezone (Europe/Paris)
    expect(screen.getByRole('link', { name: 'Open event' })).toHaveAttribute('href', '/calendar/o/12')
  })

  it('redacts an alert whose event is no longer visible (no title, no link)', async () => {
    rows = [{ ...redacted }]
    renderPage()
    expect(await screen.findByText('This calendar notification is no longer available to you.')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Calendar change' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Open event' })).toBeNull()
  })
})
