import React from 'react'
import { MemoryRouter } from 'react-router-dom'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import Router from './router'

vi.mock('./contexts/AuthContext', () => ({
  AuthProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useAuth: () => ({
    user: { user_id: 1, email: 'test@example.com' },
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
    return Promise.resolve({ data: [] })
  })
})

afterEach(() => {
  vi.clearAllMocks()
})

describe('minimal IA routing', () => {
  it('root resolves to the Library', async () => {
    renderAt('/')
    expect(await screen.findByRole('heading', { name: 'Library', level: 1 })).toBeInTheDocument()
  })

  it('/dashboard resolves to the Dashboard (secondary, not home)', async () => {
    renderAt('/dashboard')
    expect(await screen.findByRole('heading', { name: 'Training Dashboard' })).toBeInTheDocument()
  })

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

  it('secondary destinations stay in navigation', async () => {
    renderAt('/dives')
    await screen.findByRole('heading', { name: 'Library', level: 1 })
    for (const label of ['Overview', 'Journey', 'Analytics', 'Representatives', 'Sessions']) {
      expect(screen.getByRole('link', { name: label })).toBeInTheDocument()
    }
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
      '/competitions',
    ]) {
      const { unmount } = renderAt(path)
      await screen.findByRole('navigation', { name: 'Primary navigation' })
      expect(screen.queryByText('Page not found')).not.toBeInTheDocument()
      unmount()
    }
  })

  it('unknown URLs render a usable recovery page instead of an empty shell', async () => {
    renderAt('/nonexistent-route-xyz')
    expect(
      await screen.findByRole('heading', { name: 'Page not found' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Back to Library' })).toBeInTheDocument()
  })
})
