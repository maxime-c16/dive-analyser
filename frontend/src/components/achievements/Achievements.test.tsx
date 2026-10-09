import { MemoryRouter } from 'react-router-dom'
import { act, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n/I18nProvider'
import { ACHIEVEMENTS_CHECK_EVENT } from '../../services/achievementsApi'
import AchievementToaster from './AchievementToaster'
import AchievementsPanel from './AchievementsPanel'

vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({ user: { user_id: 7, email: 'alex@example.com', is_admin: false } }),
}))

type Handler = (url: string, init?: RequestInit) => unknown
function stubApi(handler: Handler) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const body = handler(String(input), init)
    return { ok: true, status: body === undefined ? 204 : 200, json: async () => body } as Response
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

const renderWithApp = (ui: React.ReactNode) =>
  render(<I18nProvider><MemoryRouter>{ui}</MemoryRouter></I18nProvider>)

beforeEach(() => {
  localStorage.setItem('dive-analyser.language', 'en')
})
afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('AchievementToaster', () => {
  it('celebrates an unseen unlock once and marks it seen', async () => {
    let unseen = [{ key: 'first_comment', unlocked_at: '2026-10-09T10:00:00Z' }]
    const fetchMock = stubApi((url, init) => {
      if (url.endsWith('/me/achievements/seen')) {
        unseen = []
        return undefined
      }
      expect(init?.method ?? 'GET').toBe('GET')
      return { items: unseen }
    })
    renderWithApp(<AchievementToaster />)
    expect(await screen.findByRole('status')).toHaveTextContent('First comment')
    expect(screen.getByRole('link', { name: 'See my achievements' })).toHaveAttribute('href', '/users/7?tab=achievements')
    const seen = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/seen'))
    expect(JSON.parse(String(seen?.[1]?.body))).toEqual({ keys: ['first_comment'] })
    // A re-check does not replay what was already shown.
    await act(async () => { window.dispatchEvent(new Event(ACHIEVEMENTS_CHECK_EVENT)) })
    expect(screen.getAllByRole('status')).toHaveLength(1)
  })

  it('groups several unlocks and ignores keys this build does not know', async () => {
    stubApi(url => (url.endsWith('/seen') ? undefined : {
      items: [
        { key: 'profile_photo', unlocked_at: '2026-10-09T10:00:00Z' },
        { key: 'profile_bio', unlocked_at: '2026-10-09T10:00:01Z' },
        { key: 'from_the_future', unlocked_at: '2026-10-09T10:00:02Z' },
      ],
    }))
    renderWithApp(<AchievementToaster />)
    const toast = await screen.findByRole('status')
    expect(toast).toHaveTextContent('2 achievements unlocked')
    expect(toast).toHaveTextContent('Picture perfect')
    expect(toast).toHaveTextContent('Say something')
    expect(toast).not.toHaveTextContent('from_the_future')
  })

  it('stays silent when nothing is unseen', async () => {
    const fetchMock = stubApi(() => ({ items: [] }))
    renderWithApp(<AchievementToaster />)
    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    expect(screen.queryByRole('status')).toBeNull()
  })
})

describe('AchievementsPanel', () => {
  it('shows locked entries with progress on my own profile and marks them seen', async () => {
    const fetchMock = stubApi(() => ({
      total: 2,
      unlocked: 1,
      items: [
        { key: 'first_comment', category: 'community', unlocked: true, unlocked_at: '2026-10-09T10:00:00Z', seen: false, target: 1, progress: 1 },
        { key: 'comments_10', category: 'community', unlocked: false, unlocked_at: null, seen: true, target: 10, progress: 4 },
      ],
    }))
    renderWithApp(<AchievementsPanel userId={7} isSelf />)
    expect(await screen.findByTestId('achievements-summary')).toHaveTextContent('1 of 2 unlocked')
    expect(screen.getByText('Regular voice').closest('li')).toHaveAttribute('data-unlocked', 'false')
    expect(screen.getByText('4/10')).toBeInTheDocument()
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/seen'))).toBe(true))
  })

  it('shows only unlocked achievements on someone else’s profile', async () => {
    const fetchMock = stubApi(() => ({
      total: 17,
      unlocked: 1,
      items: [{ key: 'first_like', category: 'community', unlocked_at: '2026-10-09T10:00:00Z' }],
    }))
    renderWithApp(<AchievementsPanel userId={9} isSelf={false} />)
    expect(await screen.findByText('First like')).toBeInTheDocument()
    expect(screen.queryByText('Regular voice')).toBeNull()
    expect(String(fetchMock.mock.calls[0][0])).toBe('/api/v1/users/9/achievements')
  })

  it('says so when another member has nothing yet', async () => {
    stubApi(() => ({ total: 17, unlocked: 0, items: [] }))
    renderWithApp(<AchievementsPanel userId={9} isSelf={false} />)
    expect(await screen.findByText('No achievements unlocked yet.')).toBeInTheDocument()
  })
})
