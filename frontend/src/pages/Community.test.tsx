import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { within } from '@testing-library/dom'
import { MemoryRouter } from 'react-router-dom'
import { I18nProvider } from '../i18n/I18nProvider'
import Community from './Community'

vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { user_id: 1 } }) }))
const fanny = { user_id: 2, display_name: 'Fanny', handle: 'fanny_dive', bio: 'Training for the next meet', avatar_url: null }
function response(data: unknown, ok = true) { return Promise.resolve({ ok, status: ok ? 200 : 500, json: async () => data } as Response) }
function renderPage() { render(<I18nProvider><MemoryRouter><Community /></MemoryRouter></I18nProvider>) }
afterEach(() => { vi.restoreAllMocks() })
const board = { period: 'week', start: '', end: '', members: [] }
/** Routes the directory, and the leaderboard to an empty board unless given. */
function api(directory: (url: string) => unknown, leaderboard: unknown = board) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation(input => response(String(input).includes('/leaderboard') ? leaderboard : directory(String(input))))
}

describe('Community discovery', () => {
  it('sorts peers into divers and other members, leaving out you and accounts on your own diver', async () => {
    const recent = new Date(Date.now() - 3 * 86_400_000).toISOString()
    api(() => ({ items: [
      { ...fanny, accessible_dive_count: 32, latest_dive_at: recent },
      { ...fanny, user_id: 3, display_name: 'Alex', accessible_dive_count: 0, latest_dive_at: null },
      { ...fanny, user_id: 1, display_name: 'Me', accessible_dive_count: 90, latest_dive_at: recent },
      { ...fanny, user_id: 4, display_name: 'Twin', accessible_dive_count: 90, latest_dive_at: recent, linked: true },
    ], next_after: null }))
    renderPage()
    const divers = await screen.findByRole('region', { name: /Divers/ })
    expect(divers).toHaveTextContent(/32 shared dives/)
    expect(screen.getByRole('region', { name: /Other members/ })).toHaveTextContent('Alex')
    expect(screen.getByRole('region', { name: /Recently active/ })).toHaveTextContent('Fanny')
    expect(screen.queryByText('Me')).not.toBeInTheDocument()
    expect(screen.queryByText('Twin')).not.toBeInTheDocument()
  })

  it('ranks the most active members on a podium, you highlighted, your own diver left out', async () => {
    const member = (user_id: number, display_name: string, attempts: number) => ({ user_id, display_name, handle: null, avatar_url: null, attempts, sessions: 1, codes: 1, median: null, delta: null, streak_weeks: 1, last_attempt_at: null })
    api(() => ({ items: [{ ...fanny, accessible_dive_count: 3 }, { ...fanny, user_id: 4, display_name: 'Twin', linked: true }], next_after: null }),
      { ...board, members: [member(4, 'Twin', 50), member(2, 'Fanny', 12), member(1, 'Me', 8)] })
    renderPage()
    const podium = await screen.findByRole('list', { name: 'Podium' })
    expect(podium).toHaveTextContent('Fanny')
    expect(podium).toHaveTextContent('You')
    expect(podium).not.toHaveTextContent('Twin')
  })

  it('searches names/handles and links to the selected member profile', async () => {
    const fetchMock = api(url => ({ items: url.includes('q=%40fanny') ? [fanny] : [], next_after: null }))
    renderPage()
    const user = userEvent.setup()
    // The search field carries an accessible name (sr-only label), like the
    // Library's "Search dives" — a placeholder alone would announce nothing.
    const search = screen.getByRole('searchbox', { name: 'Search by name or @handle' })
    await user.type(search, '@fanny')
    expect(await screen.findByRole('link', { name: /Fanny/ })).toHaveAttribute('href', '/users/2')
    expect(screen.getByRole('link', { name: 'My profile' })).toHaveAttribute('href', '/users/1')
    expect(fetchMock).toHaveBeenLastCalledWith('/api/v1/users?q=%40fanny', expect.objectContaining({ credentials: 'same-origin' }))
  })

  it('names member cards as "name, facts" instead of welded segments', async () => {
    const recent = new Date(Date.now() - 19 * 86_400_000).toISOString()
    api(() => ({ items: [
      { ...fanny, user_id: 2, display_name: 'Louis', accessible_dive_count: 2, latest_dive_at: recent },
    ], next_after: null }))
    renderPage()
    // Vertically stacked words are one computed name for screen readers:
    // "Louis" and "2 shared dives" must be separated, not "Louis2 shared
    // dives · 19 days ago".
    const card = await screen.findByRole('link', { name: /Louis @fanny_dive\s*,\s*2 shared dives/ })
    expect(card.getAttribute('href')).toBe('/users/2')
    expect(card).toHaveTextContent(/19 days ago/)
  })

  it('separates the name and age on recently active story cards', async () => {
    const recent = new Date(Date.now() - 19 * 86_400_000).toISOString()
    api(() => ({ items: [{ ...fanny, user_id: 2, accessible_dive_count: 5, latest_dive_at: recent }], next_after: null }))
    renderPage()
    expect(await screen.findByRole('link', { name: /Fanny\s*,\s*\d+ days?/ })).toBeInTheDocument()
  })

  it('offers a working retry when initial discovery fails', async () => {
    let fail = true
    vi.spyOn(globalThis, 'fetch').mockImplementation(input => String(input).includes('/leaderboard') ? response(board)
      : fail ? (fail = false, response({}, false)) : response({ items: [fanny], next_after: null }))
    renderPage()
    await screen.findByRole('alert')
    await userEvent.setup().click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByRole('link', { name: /Fanny/ })).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
  })

  it('a restart discards a stale continuation served into the fresh page', async () => {
    let hold: ((value: Response | PromiseLike<Response>) => void) | null = null
    let directoryCalls = 0
    let searchFails = false
    vi.spyOn(globalThis, 'fetch').mockImplementation(input => {
      const url = new URL(String(input), 'http://test')
      if (url.pathname.includes('/leaderboard')) return response(board)
      if (url.pathname.includes('/directory')) {
        directoryCalls += 1
        if (directoryCalls === 1) {
          return response({ items: [fanny], next_after: 2, has_more: true, totals: { members: 2, divers: 1, others: 1, recent: 0 } })
        }
        if (url.searchParams.get('after')) {
          return new Promise(resolve => { hold = resolve })
        }
        return response({ items: [{ ...fanny, user_id: 3, display_name: 'Bill' }], next_after: null, has_more: false, totals: { members: 2, divers: 1, others: 1, recent: 0 } })
      }
      if (searchFails && new URLSearchParams(url.search).get('q')) return response({}, false)
      return response({ items: new URLSearchParams(url.search).get('q') ? [fanny] : [], next_after: null })
    })
    renderPage()
    expect(await screen.findByRole('link', { name: /Fanny/ })).toBeInTheDocument()
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Show the remaining 1 member' }))
    await waitFor(() => expect(hold).not.toBeNull())
    // Force an error elsewhere, then Retry: both loads re-run (the directory
    // generation moves) while the old continuation is still on the wire.
    searchFails = true
    await user.type(screen.getByRole('searchbox'), 'a')
    const alert = await screen.findByRole('alert')
    searchFails = false
    await user.click(within(alert).getByRole('button', { name: 'Retry' }))
    // Clear the search field so the directory sections come back (the retry
    // already re-keyed both loads while the continuation was on the wire).
    await user.clear(screen.getByRole('searchbox'))
    // The retried first page replaces the list with its own truth…
    expect(await screen.findByRole('link', { name: /Bill/ })).toBeInTheDocument()
    // …and the in-flight continuation landed after: without the generation
    // guard it would append Fanny a second time and install its cursor.
    await act(async () => {
      hold!(response({ items: [{ ...fanny, user_id: 2, display_name: 'Alex' }], next_after: null, has_more: false }))
    })
    expect(screen.queryByRole('link', { name: /^Alex$/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Show the remaining 2 members' })).not.toBeInTheDocument()
  })

  it('keeps you on the board with a zero score and pages search results', async () => {
    const member = (user_id: number, display_name: string, attempts: number) => ({ user_id, display_name, handle: null, avatar_url: null, attempts, sessions: 1, codes: 1, median: null, delta: null, streak_weeks: 1, last_attempt_at: null })
    api(url => url.includes('q=') && url.includes('after=')
      ? { items: [{ ...fanny, user_id: 3, display_name: 'Alex' }], next_after: null }
      : url.includes('q=')
        ? { items: [fanny], next_after: 2 }
        : { items: [], next_after: null },
      { ...board, members: [member(2, 'Fanny', 12), member(1, 'Me', 0)] })
    renderPage()
    expect(await screen.findByRole('list', { name: 'Podium' })).toHaveTextContent('You')
    const user = userEvent.setup()
    await user.type(screen.getByRole('searchbox'), 'a')
    await screen.findByRole('link', { name: /Fanny/ })
    await user.click(screen.getByRole('button', { name: 'Load more members' }))
    expect(await screen.findByRole('link', { name: /Alex/ })).toBeInTheDocument()
  })

  it('retries a failed search instead of leaving it loading', async () => {
    let fail = true
    vi.spyOn(globalThis, 'fetch').mockImplementation(input => {
      const url = String(input)
      if (url.includes('/leaderboard')) return response(board)
      if (url.includes('q=fanny') && fail) { fail = false; return response({}, false) }
      return response({ items: url.includes('q=fanny') ? [fanny] : [], next_after: null })
    })
    renderPage()
    const user = userEvent.setup()
    await user.type(screen.getByRole('searchbox'), 'fanny')
    await screen.findByRole('alert')
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByRole('link', { name: /Fanny/ })).toBeInTheDocument()
  })

  it('re-enables paging when the query changes during a load-more', async () => {
    let release!: (value: unknown) => void
    const gate = new Promise(resolve => { release = resolve })
    vi.spyOn(globalThis, 'fetch').mockImplementation(input => {
      const url = new URL(String(input), 'http://test')
      if (url.pathname.includes('/leaderboard')) return response(board)
      if (url.searchParams.get('q') && url.searchParams.get('after')) return gate.then(() => response({ items: [{ ...fanny, user_id: 3, display_name: 'Alex' }], next_after: null }))
      const q = url.searchParams.get('q')
      return response({ items: q ? [fanny] : [], next_after: q ? 2 : null })
    })
    renderPage()
    const user = userEvent.setup()
    await user.type(screen.getByRole('searchbox'), 'a')
    await screen.findByRole('link', { name: /Fanny/ })
    await user.click(screen.getByRole('button', { name: 'Load more members' }))
    // The query changes while the page is in flight; the stale page lands after.
    await user.type(screen.getByRole('searchbox'), 'b')
    release(undefined)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Load more members' })).toBeEnabled())
  })

  it('loads the directory in one bounded page and continues explicitly', async () => {
    let splice = 0
    api(url => url.includes('/directory')
      ? (splice === 0
        ? (splice = 1, { items: [{ ...fanny, accessible_dive_count: 12 }], next_after: 2, has_more: true, totals: { members: 2, divers: 2, others: 0, recent: 1 } })
        : { items: [{ ...fanny, user_id: 3, display_name: 'Alex', handle: 'alex' }], next_after: null, has_more: false, totals: { members: 2, divers: 2, others: 0, recent: 1 } })
      : { items: [], next_after: null })
    renderPage()
    expect(await screen.findByRole('link', { name: /Fanny/ })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: /Divers/ })).toHaveTextContent('2')
    expect(screen.getByRole('button', { name: 'Show the remaining 1 member' })).toBeInTheDocument()
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Show the remaining 1 member' }))
    expect(await screen.findByRole('link', { name: /Alex/ })).toBeInTheDocument()
    // Every page is loaded exactly once: no sequential walk, no silent gap.
    expect(screen.queryByRole('button', { name: /Show the remaining/ })).not.toBeInTheDocument()
  })
})
