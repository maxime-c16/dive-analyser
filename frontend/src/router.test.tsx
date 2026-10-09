import React from 'react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import Router, { CompetitionsRedirect, breadcrumbTrail } from './router'

const role = vi.hoisted(() => ({ isAdmin: true }))

vi.mock('./contexts/AuthContext', () => ({
  AuthProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useAuth: () => ({
    user: { user_id: 1, email: 'test@example.com', is_admin: role.isAdmin, divers: [{ diver_id: 1, access_kind: 'OWNER' }] },
    checking: false,
    refresh: async () => {},
  }),
}))

vi.mock('./hooks/useSyncStatus', () => ({
  useSyncStatus: () => ({ currentSync: null, isConnected: false }),
}))

vi.mock('./services/api', () => ({ api: { get: vi.fn().mockResolvedValue({ data: [] }) } }))
vi.mock('./services/mediaApi', () => ({
  getMediaStatus: vi.fn().mockResolvedValue({ poster_url: null, playback_url: null }),
}))
vi.mock('./components/DiveVideoPlayer', () => ({
  default: ({ videoUuid }: { videoUuid: string }) => <div>Native player {videoUuid}</div>,
}))

import { api } from './services/api'

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Router />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  role.isAdmin = true;
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === '/api/v1/journey') {
      return Promise.resolve({
        data: {
          overview: { total_dives: 0, unique_dive_combinations: 0, days_of_training: 0 },
          growth: { improvement: 0, trajectory: 'plateauing' },
          psychological: {},
        },
      })
    }
    if (url === '/api/v1/dd/overview') {
      return Promise.resolve({ data: { timeline: [], inventory: [], height_breakdown: [], undefined_reasons: [], reference: { label: '' }, summary: { attempt_count: 0, defined_attempt_count: 0, undefined_attempt_count: 0, unique_dive_count: 0, median_dd: null, max_dd: null, legacy_mismatch_count: 0 } } })
    }
    return Promise.resolve({ data: [] })
  })
})

afterEach(() => {
  vi.clearAllMocks()
})

// Cold lazy-route imports (charts, transformed by Vitest) can take well over
// 5s on the shared 2-CPU server while the gate runs next to production.
const LAZY_ROUTE_WAIT = 20_000
const LAZY_ROUTE_TEST_TIMEOUT = 30_000

describe('minimal IA routing', () => {
  it('root resolves to the Library', async () => {
    renderAt('/')
    expect(await screen.findByRole('heading', { name: 'Library', level: 1 })).toBeInTheDocument()
  })

  it('/dashboard resolves to the Dashboard (secondary, not home)', async () => {
    renderAt('/dashboard')
    expect(screen.getByRole('status')).toHaveTextContent('Loading page')
    // The cold dynamic import includes chart modules transformed by Vitest.
    expect(await screen.findByRole('heading', { name: 'Training Dashboard' }, { timeout: LAZY_ROUTE_WAIT })).toBeInTheDocument()
  }, LAZY_ROUTE_TEST_TIMEOUT)

  it('Library is the primary navigation destination', async () => {
    renderAt('/dives')
    await screen.findByRole('heading', { name: 'Library', level: 1 })
    const primaryNav = screen.getByRole('navigation', { name: 'Primary navigation' })
    expect(primaryNav).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: 'Library' }).length).toBeGreaterThan(0)
  })

  it('P5 canary harness and Competitions alias are absent from normal navigation', async () => {
    renderAt('/dives')
    await screen.findByRole('heading', { name: 'Library', level: 1 })
    expect(screen.queryByRole('link', { name: 'Player canary' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Competitions' })).not.toBeInTheDocument()
  })

  it('admin review destinations are collapsed until explicitly opened', async () => {
    renderAt('/dives')
    await screen.findByRole('heading', { name: 'Library', level: 1 })
    const toggle = screen.getByRole('button', { name: 'Review' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('navigation', { name: 'Secondary navigation' })).not.toBeInTheDocument()
    await userEvent.click(toggle)
    for (const label of ['Overview', 'Journey', 'Analytics', 'Representatives', 'Sessions']) {
      expect(screen.getByRole('link', { name: label })).toBeInTheDocument()
    }
    await userEvent.click(toggle)
    expect(screen.queryByRole('link', { name: 'Overview' })).not.toBeInTheDocument()
  })

  it('regular divers see the four primary destinations and no admin menus', async () => {
    role.isAdmin = false
    renderAt('/dives')
    await screen.findByRole('heading', { name: 'Library', level: 1 })
    const nav = screen.getByRole('navigation', { name: 'Primary navigation' })
    expect(within(nav).getAllByRole('link').map(link => link.textContent)).toEqual(['Library', 'Messages', 'Community', 'Evaluations'])
    expect(screen.queryByRole('button', { name: 'Review' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Operations' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Account navigation' }))
    expect(screen.queryByRole('navigation', { name: 'Secondary navigation' })).not.toBeInTheDocument()
  })

  it.each(['/dashboard', '/journey', '/analytics', '/sessions', '/media/representatives', '/media/p5-canary', '/media/recall', '/admin', '/admin/users/2', '/competitions'])('redirects a regular diver opening %s to the Library', async (path) => {
    role.isAdmin = false
    renderAt(path)
    expect(await screen.findByRole('heading', { name: 'Library', level: 1 })).toBeInTheDocument()
  })

  it('operational destinations live behind a collapsed disclosure', async () => {
    renderAt('/dives')
    await screen.findByRole('heading', { name: 'Library', level: 1 })
    expect(screen.queryByRole('link', { name: 'Media recall' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Operations' }))
    expect(screen.getByRole('link', { name: 'Media recall' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'System' })).toBeInTheDocument()
  })

  it('secondary routes remain reachable', async () => {
    for (const path of [
      '/journey',
      '/analytics',
      '/sessions',
      '/media/representatives',
      '/media/recall',
      '/admin',
      '/media/p5-canary',
    ]) {
      const { unmount } = renderAt(path)
      await screen.findByRole('navigation', { name: 'Primary navigation' })
      expect(screen.queryByText('Page not found')).not.toBeInTheDocument()
      unmount()
    }
  })

  it('/competitions is a compatibility redirect to /journey, not a page', async () => {
    renderAt('/competitions')
    // The redirect lands on Journey (no duplicate Competitions destination).
    expect(
      await screen.findByRole('heading', { name: 'Your Diving Journey' }, { timeout: LAZY_ROUTE_WAIT }),
    ).toBeInTheDocument()
    expect(screen.queryByText('Page not found')).not.toBeInTheDocument()
  }, LAZY_ROUTE_TEST_TIMEOUT)

  it('/competitions preserves the query string across the redirect', () => {
    function LocationProbe() {
      const location = useLocation()
      return <div data-testid="location">{`${location.pathname}${location.search}`}</div>
    }
    render(
      <MemoryRouter initialEntries={['/competitions?scope=all']}>
        <Routes>
          <Route path="/competitions" element={<CompetitionsRedirect />} />
          <Route path="/journey" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>,
    )
    expect(screen.getByTestId('location')).toHaveTextContent('/journey?scope=all')
  })

  it('breadcrumbs reflect user-visible IA, not router hierarchy', () => {
    const t = (key: string) => key
    expect(breadcrumbTrail('/dives', t)).toEqual([{ labelKey: 'nav.dives' }])
    expect(breadcrumbTrail('/journey', t)).toEqual([{ labelKey: 'nav.journey' }])
    // Deep analysis paths link back to the Library, not to /dives/analysis.
    expect(breadcrumbTrail('/dives/analysis/5210D', t)).toEqual([
      { labelKey: 'nav.dives', href: '/dives' },
      { label: '5210D breadcrumbs.analysis' },
    ])
    // Media routes have no fake intermediate "Media" parent link.
    expect(breadcrumbTrail('/media/representatives', t)).toEqual([
      { labelKey: 'nav.representatives' },
    ])
    expect(breadcrumbTrail('/media/recall', t)).toEqual([{ labelKey: 'nav.mediaRecall' }])
    expect(breadcrumbTrail('/media/p5-canary', t)).toEqual([{ labelKey: 'nav.playerCanary' }])
    // Unknown paths render a single harmless crumb, never a dead hierarchy.
    expect(breadcrumbTrail('/nonexistent-route-xyz', t)).toEqual([
      { label: 'nonexistent route xyz' },
    ])
  })

  it('unknown URLs render a usable recovery page instead of an empty shell', async () => {
    renderAt('/nonexistent-route-xyz')
    expect(
      await screen.findByRole('heading', { name: 'Page not found' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Back to Library' })).toBeInTheDocument()
  })
})

// ---- Unread messages badge on the Messages nav ----

describe('messages unread badge', () => {
  function stubMessagesInbox() {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.includes('/api/v1/messages/conversations')) {
        return { ok: true, json: async () => ({ items: [{ id: 1, kind: 'direct', members: [], unread_count: 2 }, { id: 2, kind: 'direct', members: [], unread_count: 1 }], next_before: null }) } as Response
      }
      if (url.includes('/api/v1/updates')) {
        return { ok: true, json: async () => ({ schema: 1, version: '', frontend_sha: '', notes: [] }) } as Response
      }
      if (url.includes('/api/v1/notifications')) {
        return { ok: true, json: async () => ({ items: [], unread_count: 0 }) } as Response
      }
      return { ok: true, json: async () => ({}) } as Response
    }))
  }

  it('shows the unread total on the sidebar Messages link', async () => {
    stubMessagesInbox()
    renderAt('/dives')
    const link = await screen.findByRole('link', { name: 'Messages, 3 unread' })
    expect(link).toHaveAttribute('href', '/messages')
    expect(screen.getByTestId('messages-unread-badge')).toHaveTextContent('3')
    vi.unstubAllGlobals()
  })

  it('discards the badge while the Messages tab is open', async () => {
    stubMessagesInbox()
    renderAt('/messages')
    expect(await screen.findByRole('heading', { name: 'Messages', level: 1 })).toBeInTheDocument()
    expect(screen.queryByTestId('messages-unread-badge')).toBeNull()
    expect(screen.getAllByRole('link', { name: 'Messages' }).length).toBeGreaterThan(0)
    vi.unstubAllGlobals()
  })
})

// ---- U4/U5: skip navigation + landmarks ----

it('a skip-to-main-content link precedes all content and targets the main landmark', async () => {
  renderAt('/dives')
  const skipLink = screen.getByRole('link', { name: 'Skip to main content' })
  const main = screen.getByRole('main')
  expect(main).toHaveAttribute('id', 'main-content')
  expect(main).toHaveAttribute('tabindex', '-1')
  expect(skipLink).toHaveAttribute('href', '#main-content')
  // The skip link is the first focusable element in the app shell.
  const firstFocusable = document.querySelector('a, button, input, select, textarea, [tabindex]')
  expect(firstFocusable).toBe(skipLink)
})

it('the main landmark exists exactly once in the shell', async () => {
  renderAt('/dives')
  expect(screen.getAllByRole('main')).toHaveLength(1)
})

it('mobile menu isolates the page and restores its avatar after nested update history closes', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ schema: 1, version: '', frontend_sha: '', notes: [] }) })))
  const view = renderAt('/dives')
  await screen.findByRole('heading', { name: 'Library', level: 1 })
  const trigger = screen.getByRole('button', { name: 'Account navigation' })
  await userEvent.click(trigger)
  expect(document.getElementById('main-content')?.closest('[inert]')).not.toBeNull()
  const menu = screen.getByRole('dialog')
  await userEvent.click(within(menu).getByRole('button', { name: "What's new" }))
  expect(screen.getAllByRole('dialog', { hidden: true })).toHaveLength(2)
  await userEvent.keyboard('{Escape}')
  expect(trigger).toHaveAttribute('aria-expanded', 'true')
  expect(document.body.style.overflow).toBe('hidden')
  await userEvent.keyboard('{Escape}')
  await waitFor(() => expect(trigger).toHaveFocus())
  expect(trigger).toHaveAttribute('aria-expanded', 'false')
  expect(document.getElementById('main-content')?.closest('[inert]')).toBeNull()
  view.unmount(); vi.unstubAllGlobals()
})
