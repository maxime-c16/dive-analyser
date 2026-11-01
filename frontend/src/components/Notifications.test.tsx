import React from 'react'
import { MemoryRouter } from 'react-router-dom'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
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

describe('Older notifications continuation (UX fix 2026-11)', () => {
  // 60 rows: ids 1..60. The provider/first page shows the 50 newest (60..11)
  // and reports one further page; continuation pages anchor on before_id.
  const allIds = Array.from({ length: 60 }, (_, index) => index + 1)

  function pagingStub() {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === 'string' ? input : input.toString()
        if (init?.method) return { ok: true, json: async () => ({}) } as Response
        const query = new URLSearchParams(url.split('?')[1] ?? '')
        const anchor = query.get('before_id')
        // The real inbox is newest first: descending id order.
        const beyond = (anchor === null ? allIds : allIds.filter(id => id < Number(anchor))).sort((a, b) => b - a)
        const offered = beyond.slice(0, Number(query.get('limit') ?? '50'))
        return {
          ok: true,
          json: async () => ({
            items: offered.map(id => ({
              id,
              type: 'new_video',
              title: `New video synced #${id}`,
              body: null,
              dive_id: id,
              read_at: null,
              created_at: '2026-10-29T08:00:00Z',
            })),
            unread_count: allIds.length,
            has_more: beyond.length > offered.length,
          }),
        } as Response
      }),
    )
  }

  it('pages the list past the first 50 rows with an explicit anchor', async () => {
    pagingStub()
    renderPage()
    expect(await screen.findByText('New video synced #60')).toBeInTheDocument()
    expect(screen.getByText('New video synced #11')).toBeInTheDocument()
    expect(screen.queryByText('New video synced #10')).not.toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Show older notifications' }),
    ).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Show older notifications' }))
    expect(await screen.findByText('New video synced #10')).toBeInTheDocument()
    expect(screen.getByText('New video synced #1')).toBeInTheDocument()
    const calls = vi.mocked(fetch).mock.calls.map(([input]) =>
      typeof input === 'string' ? input : input.toString(),
    )
    expect(calls.filter(url => url.includes('before_id=11')).length).toBeGreaterThan(0)
    // Continuation reached the true end: the control goes away.
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: 'Show older notifications' })).toBeNull(),
    )
  })

  it('ignores an old continuation response after the filter changes', async () => {
    pagingStub()
    const original = vi.mocked(fetch).getMockImplementation()!
    let finish!: (response: Response) => void
    vi.mocked(fetch).mockImplementation((input, init) => {
      if (String(input).includes('before_id')) return new Promise<Response>(resolve => { finish = resolve })
      return original(input, init)
    })
    renderPage()
    await screen.findByText('New video synced #60')
    fireEvent.click(screen.getByRole('button', { name: 'Show older notifications' }))
    fireEvent.click(screen.getByRole('button', { name: /Unread \(60\)/ }))
    await act(async () => {
      finish({ ok: true, json: async () => ({ items: [{ ...unreadRow, id: 1, title: 'Stale continuation' }], unread_count: 60, has_more: false }) } as Response)
    })
    expect(screen.queryByText('Stale continuation')).not.toBeInTheDocument()
    expect(await screen.findByRole('button', { name: 'Show older notifications' })).toBeEnabled()
  })

  it('deduplicates a continuation row moved into the first page by a refresh', async () => {
    pagingStub()
    renderPage()
    await screen.findByText('New video synced #60')
    await userEvent.click(screen.getByRole('button', { name: 'Show older notifications' }))
    allIds.splice(allIds.indexOf(60), 1)
    window.dispatchEvent(new Event('focus'))
    await waitFor(() => expect(screen.queryByText('New video synced #60')).not.toBeInTheDocument())
    expect(screen.getAllByText('New video synced #10')).toHaveLength(1)
    allIds.push(60)
  })

  it('re-reaches a row displaced by a growing first page (60–11 + 10–1, new arrival 61)', async () => {
    pagingStub()
    renderPage()
    await screen.findByText('New video synced #60')
    expect(screen.getByText('New video synced #11')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Show older notifications' }))
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: 'Show older notifications' })).toBeNull(),
    )
    // A new arrival grows the head to 61–12: row 11 no longer belongs to
    // either loaded page. The pagination control must come back instead of
    // silently leaving a hole, and the next page re-reaches the displaced row.
    allIds.push(61)
    window.dispatchEvent(new Event('focus'))
    expect(await screen.findByText('New video synced #61')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Show older notifications' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Show older notifications' }))
    expect(await screen.findByText('New video synced #11')).toBeInTheDocument()
    // Rows already loaded merge by id — each is rendered exactly once.
    expect(screen.getAllByText('New video synced #1')).toHaveLength(1)
    expect(screen.getAllByText('New video synced #10')).toHaveLength(1)
    expect(screen.getAllByText('New video synced #31')).toHaveLength(1)
  })

  it('keeps the rebased cursor when a continuation lands after the arrival', async () => {
    pagingStub()
    const intact = vi.mocked(fetch).getMockImplementation()!
    renderPage()
    await screen.findByText('New video synced #60')
    // The first continuation (anchored on 11 from head 60–11) stalls on the
    // wire…
    let release!: (response: Response) => void
    vi.mocked(fetch).mockImplementation((input, init) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.includes('before_id')) return new Promise<Response>(r => { release = r })
      return intact(input, init)
    })
    fireEvent.click(screen.getByRole('button', { name: 'Show older notifications' }))
    // …and notification 61 arrives first: the fresh head covers 61–12 and
    // the cursor re-aligns to it (61 is visible, the control stays).
    allIds.push(61)
    window.dispatchEvent(new Event('focus'))
    expect(await screen.findByText('New video synced #61')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Show older notifications' })).toBeInTheDocument()
    // The late response brings the old pages (10–1, has_more=false): the
    // rows merge, but the cursor and its flatter has_more must NOT overwrite
    // the rebase — otherwise row 11 would be unreachable forever.
    await act(async () => {
      release({
        ok: true,
        json: async () => ({
          items: Array.from({ length: 10 }, (_, index) => ({
            id: 10 - index,
            type: 'new_video',
            title: `New video synced #${10 - index}`,
            body: null,
            dive_id: 10 - index,
            read_at: null,
            created_at: '2026-10-29T08:00:00Z',
          })),
          unread_count: 61,
          has_more: false,
        }),
      } as Response)
    })
    expect(screen.getAllByText('New video synced #10')).toHaveLength(1)
    expect(screen.queryByText('New video synced #11')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Show older notifications' })).toBeInTheDocument()
    // The next page anchors past the rebased cursor: row 11 is reached, the
    // continuation reaches its true end, nothing duplicates.
    vi.mocked(fetch).mockImplementation(intact)
    await userEvent.click(screen.getByRole('button', { name: 'Show older notifications' }))
    expect(await screen.findByText('New video synced #11')).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: 'Show older notifications' })).toBeNull(),
    )
    expect(screen.getAllByText('New video synced #1')).toHaveLength(1)
  })

  it('marks a row read inside the continuation without losing it', async () => {
    pagingStub()
    renderPage()
    await screen.findByText('New video synced #60')
    await userEvent.click(screen.getByRole('button', { name: 'Show older notifications' }))
    const row = screen.getByText('New video synced #5')
    fireEvent.click(within(row.closest('article') as HTMLElement).getByRole('button', { name: 'Mark as read' }))
    await waitFor(() =>
      expect(
        within(row.closest('article') as HTMLElement).queryByRole('button', { name: 'Mark as read' }),
      ).toBeNull(),
    )
    expect(row).toBeInTheDocument()
  })

  it('no continuations are offered when the list ends inside the first page', async () => {
    rows = [{ ...unreadRow }, { ...readRow }]
    stubInbox()
    renderPage()
    await screen.findByText('New comment on 103B')
    expect(screen.queryByRole('button', { name: 'Show older notifications' })).toBeNull()
  })

  it('does not announce an unread count before the server has answered', async () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(() => {})))
    renderPage()
    // The pending filter shows "Unread" — never a default "Unread (0)"
    // that contradicts the 84-style badge while nothing has arrived.
    expect(screen.queryByRole('button', { name: /Unread \(\d+\)/ })).toBeNull()
    expect(screen.getByRole('button', { name: 'Unread' })).toBeInTheDocument()
    expect(screen.getByText('Loading notifications…')).toBeInTheDocument()
    vi.unstubAllGlobals()
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
