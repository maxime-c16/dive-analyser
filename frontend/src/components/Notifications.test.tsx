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
  dive_date?: string | null
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

  it('states the real session date on a late-synced video row only', async () => {
    // A sync can land days after the session (profil 5): when the server
    // resolved the dive's real date, the row names that session day —
    // formatted in UTC (naive date part, noon anchor) so the displayed
    // day is the dive's own day, never the browser's local shift of the
    // ...Z timestamp (23:30Z stays "Oct 18" even where the local day is
    // already the 19th).
    rows = [{ ...unreadRow, type: 'new_video', title: '102B is ready', created_at: '2026-10-29T18:40:00Z', dive_date: '2026-10-18T23:30:00Z' }]
    renderPage()
    expect(await screen.findByText('102B is ready')).toBeInTheDocument()
    expect(screen.getByText('Dive of Oct 18, 2026')).toBeInTheDocument()
  })

  it('adds no session label when the video arrived on its dive day', async () => {
    rows = [{ ...unreadRow, type: 'new_video', title: '102B is ready', created_at: '2026-10-29T18:40:00Z', dive_date: '2026-10-29T00:00:00Z' }]
    renderPage()
    expect(await screen.findByText('102B is ready')).toBeInTheDocument()
    expect(screen.queryByText(/^Dive of/)).not.toBeInTheDocument()
  })

  it('keeps non-video rows plain (no session-date line)', async () => {
    rows = [{ ...unreadRow }]
    renderPage()
    await screen.findByText('New comment on 103B')
    expect(screen.queryByText(/^Dive of/)).not.toBeInTheDocument()
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

  it('keeps the rebased cursor when a continuation launched before the arrival resolves', async () => {
    pagingStub()
    const intact = vi.mocked(fetch).getMockImplementation()!
    renderPage()
    await screen.findByText('New video synced #60')
    // The first continuation (anchored on 11 from head 60–11) stalls on the
    // wire…
    const pending: Array<(response: Response) => void> = []
    vi.mocked(fetch).mockImplementation((input, init) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.includes('before_id')) return new Promise<Response>(r => { pending.push(r) })
      return intact(input, init)
    })
    fireEvent.click(screen.getByRole('button', { name: 'Show older notifications' }))
    expect(pending).toHaveLength(1)
    // …and notification 61 arrives first: the fresh head covers 61–12, the
    // stale request loses its ownership, and the control returns to its
    // actionable label (the rebase lifted its fence).
    allIds.push(61)
    window.dispatchEvent(new Event('focus'))
    expect(await screen.findByText('New video synced #61')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Show older notifications' })).toBeInTheDocument()
    // The late response (rows 10–1, has_more=false) resolves afterwards: it
    // must write NOTHING — the cursor stays aligned to the fresh head's
    // deepest row (rebased to 12), so the displaced row 11 stays reachable
    // and no has_more=false can hide the range.
    await act(async () => {
      pending[0](lateContinuation(10, 1, false))
    })
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

  it('keeps the newer continuation busy while an older one lands out of order', async () => {
    pagingStub()
    const intact = vi.mocked(fetch).getMockImplementation()!
    renderPage()
    await screen.findByText('New video synced #60')
    const pending: Array<(response: Response) => void> = []
    vi.mocked(fetch).mockImplementation((input, init) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.includes('before_id')) return new Promise<Response>(r => { pending.push(r) })
      return intact(input, init)
    })
    // A (pre-rebase) is launched…
    fireEvent.click(screen.getByRole('button', { name: 'Show older notifications' }))
    await waitFor(() => expect(pending).toHaveLength(1))
    // …a rebasing refresh invalidates it…
    allIds.push(61)
    window.dispatchEvent(new Event('focus'))
    expect(await screen.findByText('New video synced #61')).toBeInTheDocument()
    // …and B is launched with the rebased anchor. A finally lands BEFORE
    // B: B still owns the loading state — the busy label must hold and the
    // stale finally must neither re-enable nor duplicate a fence.
    fireEvent.click(screen.getByRole('button', { name: 'Show older notifications' }))
    await waitFor(() => expect(pending).toHaveLength(2))
    expect(screen.getByRole('button', { name: 'Loading…' })).toBeInTheDocument()
    await act(async () => {
      pending[0](lateContinuation(10, 1, false))
    })
    // FinA may not hand the control back while B is on the wire.
    expect(screen.getByRole('button', { name: 'Loading…' })).toBeInTheDocument()
    // B answers: its rows land exactly once, the end is reached.
    await act(async () => {
      pending[1](lateContinuation(11, 1, false))
    })
    expect(await screen.findByText('New video synced #11')).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: 'Show older notifications' })).toBeNull(),
    )
    expect(screen.getAllByText('New video synced #5')).toHaveLength(1)
  })

  function lateContinuation(from: number, to: number, hasMore: boolean): Response {
    const items = Array.from({ length: from - to + 1 }, (_, index) => ({
      id: from - index,
      type: 'new_video',
      title: `New video synced #${from - index}`,
      body: null,
      dive_id: from - index,
      read_at: null,
      created_at: '2026-10-29T08:00:00Z',
    }))
    return { ok: true, json: async () => ({ items, unread_count: allIds.length, has_more: hasMore }) } as Response
  }

  it('never fakes a continuation when switching All and Unread without an arrival', async () => {
    // 41–60 read, 1–40 unread. The All stream holds 60–11 (has_more true at
    // the head boundary 11); the unread stream ends at 40 and its own probe
    // honestly reports has_more=false. A filter switch moves the anchor
    // (11 → 40) without announcing any arrival: the switch must not rebase,
    // and the server truth owns the continuation control.
    const rows = Array.from({ length: 60 }, (_, index) => {
      const id = 60 - index
      return { id, type: 'new_video', title: `New video synced #${id}`, body: null, dive_id: id, read_at: id >= 41 ? '2026-10-05T08:00:00Z' : null, created_at: '2026-10-29T08:00:00Z' }
    })
    const stub = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method) return { ok: true, json: async () => ({}) } as Response
      const url = typeof input === 'string' ? input : String(input)
      const query = new URLSearchParams(url.split('?')[1] ?? '')
      const unreadOnly = query.get('unread_only') === 'true'
      const anchorRaw = query.get('before_id')
      const anchor = anchorRaw === null ? NaN : Number(anchorRaw)
      const pool = rows.filter(row => (unreadOnly ? row.read_at === null : true)).sort((a, b) => b.id - a.id)
      const offered = Number.isNaN(anchor) ? pool.slice(0, 50) : pool.filter(row => row.id < anchor).slice(0, 50)
      const beyond = Number.isNaN(anchor) ? (unreadOnly ? [] as typeof rows : rows) : pool.filter(row => row.id < anchor)
      return {
        ok: true,
        json: async () => ({ items: offered, unread_count: rows.filter(row => row.read_at === null).length, has_more: beyond.length > offered.length }),
      } as Response
    })
    vi.stubGlobal('fetch', stub)
    renderPage()
    await screen.findByText('New video synced #60')
    expect(screen.getByRole('button', { name: 'Show older notifications' })).toBeInTheDocument()
    // Establish a continuation first (the page after 11 reaches the end in
    // All mode): consumed, the control hides.
    await userEvent.click(screen.getByRole('button', { name: 'Show older notifications' }))
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: 'Show older notifications' })).toBeNull(),
    )
    // Switch All → Unread without any arrival (anchor would jump 11 → 40).
    fireEvent.click(screen.getByRole('button', { name: /Unread \(40\)/ }))
    expect(await screen.findByText('New video synced #40')).toBeInTheDocument()
    // The rebased-phantom would resurrect the control while the unread
    // probe said the list is complete — it must stay hidden.
    expect(screen.queryByRole('button', { name: 'Show older notifications' })).toBeNull()
    // Back to All: the provider page re-owns the truth and the control
    // returns for what the provider probe says remains.
    fireEvent.click(screen.getByRole('button', { name: 'Show all' }))
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Show older notifications' })).toBeInTheDocument(),
    )
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
      calendar_name: 'Groupe A',
      calendar_kind: 'group',
      starts_at: '2026-10-22T17:00:00Z',
      start_date: null,
      all_day: false,
      venue_name: 'Piscine Maurice Thorez',
      status: 'scheduled',
      event_cancelled: false,
      changes: [
        { kinds: ['time_changed', 'venue_changed'], old_start: '2026-10-21T17:00:00Z', new_start: '2026-10-22T17:00:00Z' },
      ],
      total: 3,
      total_exact: true,
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
    expect((text.match(/Piscine Maurice Thorez/g) ?? []).length).toBe(1) // named once, not repeated by the context line
    expect(text).toContain('+2 more sessions')
    expect(text).toContain('Groupe A') // the group calendar's name, not just "something changed"
    expect(text).toMatch(/07:00 PM.*→.*07:00 PM/) // 17:00Z shown in the event timezone (Europe/Paris)
    expect(screen.getByRole('link', { name: 'Open event' })).toHaveAttribute('href', '/calendar/o/12')
  })

  it('shows where and when on a reminder row', async () => {
    rows = [{
      ...moved,
      id: 10,
      type: 'calendar_reminder',
      title: 'Groupe A training',
      calendar: {
        ...moved.calendar!,
        kind: 'reminder',
        changes: [],
        total: 0,
      },
    }]
    renderPage()
    expect(await screen.findByText('Tomorrow · Groupe A training')).toBeInTheDocument()
    const text = screen.getByText(/Piscine Maurice Thorez/).textContent ?? ''
    expect(text).toContain('Groupe A · Piscine Maurice Thorez')
    expect(text).toMatch(/07:00 PM/) // the session's start in the event timezone
  })

  it('never presents an undercounted merge as an exact number', async () => {
    rows = [{ ...moved, id: 11, calendar: { ...moved.calendar!, total_exact: false } }]
    renderPage()
    expect(await screen.findByText(/Event changed · Groupe A training/)).toBeInTheDocument()
    const text = screen.getByText(/Moved:/).textContent ?? ''
    expect(text).toContain('and more sessions') // no fake "+2" — the merge could not count the union
    expect(text).not.toContain('+2 more sessions')
  })

  it('keeps cancellation wording to its true scope', async () => {
    // One session of the event cancelled: the row is about that session.
    rows = [{
      ...moved,
      id: 12,
      type: 'calendar_change',
      title: 'Groupe A training',
      calendar: {
        ...moved.calendar!,
        kind: 'cancellation',
        status: 'cancelled',
        event_cancelled: false,
        changes: [],
        total: 0,
      },
    }]
    renderPage()
    expect(await screen.findByText('Cancelled · Groupe A training')).toBeInTheDocument()
    const text = screen.getByText(/Session cancelled/).textContent ?? ''
    expect(text).toContain('Session cancelled') // the session, not "This event is cancelled."
    expect(text).not.toContain('This event is cancelled')
  })

  it('downgrades a partial cancellation whose own session is still on', async () => {
    rows = [{
      ...moved,
      id: 13,
      type: 'calendar_change',
      title: 'Groupe A training',
      calendar: {
        ...moved.calendar!,
        kind: 'cancellation',
        status: 'scheduled',
        event_cancelled: false,
        changes: [{ kinds: ['time_changed'], old_start: '2026-10-21T17:00:00Z', new_start: '2026-10-22T17:00:00Z' }],
        total: 2,
      },
    }]
    renderPage()
    expect(await screen.findByText('Event changed · Groupe A training')).toBeInTheDocument()
    const text = screen.getByText(/Moved:/).textContent ?? ''
    expect(text).not.toContain('Session cancelled')
    expect(text).not.toContain('This event is cancelled')
  })

  it('keeps a date-only all-day value on the UTC calendar in any timezone', async () => {
    rows = [{
      ...moved,
      id: 15,
      type: 'calendar_reminder',
      title: 'Club camp',
      calendar: {
        ...moved.calendar!,
        kind: 'reminder',
        event_title: 'Club camp',
        timezone: 'Pacific/Kiritimati', // UTC+14: noon UTC is already tomorrow there
        starts_at: null,
        start_date: '2026-10-22',
        all_day: true,
        changes: [],
        total: 0,
      },
    }]
    renderPage()
    expect(await screen.findByText(/Club camp/)).toBeInTheDocument()
    const text = screen.getByText(/Piscine Maurice Thorez/).textContent ?? ''
    expect(text).toContain('Thu, Oct 22') // the local date, never shifted to Fri, Oct 23
  })

  it('formats each endpoint of a timed <-> all-day move with its own shape', async () => {    rows = [{
      ...moved,
      id: 14,
      calendar: {
        ...moved.calendar!,
        kind: 'change',
        changes: [{
          kinds: ['time_changed'],
          old_start: '2026-10-21T17:00:00Z',
          old_all_day: false,
          new_start: '2026-10-22T00:00:00Z', // local midnight (Europe/Paris)
          new_all_day: true,
        }],
        total: 1,
      },
    }]
    renderPage()
    expect(await screen.findByText(/Event changed · Groupe A training/)).toBeInTheDocument()
    const text = screen.getByText(/Moved:/).textContent ?? ''
    expect(text).toMatch(/07:00 PM.*→/) // the old timed endpoint keeps its time
    // The moved line only (before the context and when lines): its new
    // endpoint is a date, not a time.
    const movedLine = text.split(' · ')[0] ?? ''
    const to = movedLine.split('→')[1] ?? ''
    expect(to).not.toMatch(/:/)
  })

  it('redacts an alert whose event is no longer visible (no title, no link)', async () => {
    rows = [{ ...redacted }]
    renderPage()
    expect(await screen.findByText('This calendar notification is no longer available to you.')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Calendar change' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Open event' })).toBeNull()
  })
})
