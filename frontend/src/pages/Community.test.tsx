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

describe('Community discovery', () => {
  it('shows accessible dive summaries and a useful empty state', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => response({ items: [
      { ...fanny, accessible_dive_count: 32, latest_dive_at: '2026-03-24T12:00:00Z' },
      { ...fanny, user_id: 3, display_name: 'Alex', accessible_dive_count: 0, latest_dive_at: null },
    ], next_after: null }))
    renderPage()
    expect(await screen.findByText('32 shared dives')).toBeInTheDocument()
    expect(screen.getByText('No shared dives yet')).toBeInTheDocument()
    expect(document.querySelector('time')).toHaveAttribute('datetime', '2026-03-24T12:00:00Z')
  })

  it('searches names/handles and links to the selected member profile', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(input => response({ items: String(input).includes('q=%40fanny') ? [fanny] : [], next_after: null }))
    renderPage()
    const user = userEvent.setup()
    await user.type(screen.getByRole('searchbox'), '@fanny')
    expect(await screen.findByRole('link', { name: /Fanny/ })).toHaveAttribute('href', '/users/2')
    expect(screen.getByRole('link', { name: 'My profile' })).toHaveAttribute('href', '/users/1')
    expect(fetchMock).toHaveBeenLastCalledWith('/api/v1/users?q=%40fanny', expect.objectContaining({ credentials: 'same-origin' }))
  })

  it('offers a working retry when initial discovery fails', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementationOnce(() => response({}, false)).mockImplementation(() => response({ items: [fanny], next_after: null }))
    renderPage()
    await screen.findByRole('alert')
    await userEvent.setup().click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByRole('link', { name: /Fanny/ })).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
  })

  it('appends another page without discarding the first results', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(input => response(String(input).includes('after=2')
      ? { items: [{ ...fanny, user_id: 3, display_name: 'Alex', handle: 'alex' }], next_after: null }
      : { items: [fanny], next_after: 2 }))
    renderPage()
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Load more members' }))
    expect(await screen.findByRole('link', { name: /Alex/ })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Fanny/ })).toBeInTheDocument()
  })
})
