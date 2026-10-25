import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
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
    expect(screen.getByRole('region', { name: 'Recently active' })).toHaveTextContent('Fanny')
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
    await user.type(screen.getByRole('searchbox'), '@fanny')
    expect(await screen.findByRole('link', { name: /Fanny/ })).toHaveAttribute('href', '/users/2')
    expect(screen.getByRole('link', { name: 'My profile' })).toHaveAttribute('href', '/users/1')
    expect(fetchMock).toHaveBeenLastCalledWith('/api/v1/users?q=%40fanny', expect.objectContaining({ credentials: 'same-origin' }))
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

  it('keeps you on the board with a zero score and pages search results', async () => {
    const member = (user_id: number, display_name: string, attempts: number) => ({ user_id, display_name, handle: null, avatar_url: null, attempts, sessions: 1, codes: 1, median: null, delta: null, streak_weeks: 1, last_attempt_at: null })
    api(url => url.includes('after=2')
      ? { items: [{ ...fanny, user_id: 3, display_name: 'Alex' }], next_after: null }
      : { items: [fanny], next_after: 2 },
      { ...board, members: [member(2, 'Fanny', 12), member(1, 'Me', 0)] })
    renderPage()
    expect(await screen.findByRole('list', { name: 'Podium' })).toHaveTextContent('You')
    const user = userEvent.setup()
    await user.type(screen.getByRole('searchbox'), 'a')
    await screen.findByRole('link', { name: /Fanny/ })
    await user.click(screen.getByRole('button', { name: 'Load more members' }))
    expect(await screen.findByRole('link', { name: /Alex/ })).toBeInTheDocument()
  })

  it('reads every directory page before sorting it', async () => {
    api(url => url.includes('after=2')
      ? { items: [{ ...fanny, user_id: 3, display_name: 'Alex', handle: 'alex' }], next_after: null }
      : { items: [fanny], next_after: 2 })
    renderPage()
    expect(await screen.findByRole('link', { name: /Alex/ })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Fanny/ })).toBeInTheDocument()
  })
})
