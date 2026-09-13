import React from 'react'
import { BrowserRouter } from 'react-router-dom'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import Dives from './Dives'

vi.mock('../services/api', () => ({ api: { get: vi.fn() } }))
vi.mock('../services/mediaApi', () => ({ getMediaStatus: vi.fn().mockResolvedValue({ poster_url: null, playback_url: null }) }))
vi.mock('../components/DiveVideoPlayer', () => ({ default: ({ videoUuid }: { videoUuid: string }) => <div>Native player {videoUuid}</div> }))

import { api } from '../services/api'
import { getMediaStatus } from '../services/mediaApi'

const dive = (id: number, code: string, diverId: number, options: Partial<Record<string, unknown>> = {}) => ({
  id, dive_code: code, diver_id: diverId, performance: 'G', performance_numeric: 3, height: '1m', dive_datetime: `2026-07-${String((id % 28) + 1).padStart(2, '0')}T10:00:00`, session_id: 1, is_lineup: false, is_sync: false, platform_type: 'springboard', position: code.slice(-1), official_dd: 1.5, phase1_performance: 'G', phase2_performance: 'G', raw_caption: `${code} G/G`, video_uuid: `uuid-${id}`, ...options,
})

const divers = [
  { id: 1, display_name: 'Maxime', is_primary_user: true },
  { id: 2, display_name: 'Paul', is_primary_user: false },
]

function mockDives(count: number, smackFrom = Number.POSITIVE_INFINITY) {
  return Array.from({ length: count }, (_, index) => {
    const id = index + 1
    return dive(id, '103B', 1, { raw_caption: id >= smackFrom ? '103B G/G SMACK' : '103B G/G' })
  })
}

function renderAt(url: string) {
  window.history.replaceState(null, '', url)
  return render(
    <BrowserRouter>
      <Dives />
    </BrowserRouter>,
  )
}

beforeEach(() => {
  window.history.replaceState(null, '', '/')
  vi.mocked(getMediaStatus).mockResolvedValue({ poster_url: null, playback_url: null } as any)
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === '/api/v1/divers') return Promise.resolve({ data: divers })
    return Promise.resolve({ data: mockDives(3) })
  })
})

it('opening a clip pushes one history entry and preserves query params', async () => {
  renderAt('/dives?q=103&view=list')
  const cards = await screen.findAllByRole('button', { name: /Open 103B attempt/ })
  const lengthBefore = window.history.length
  await userEvent.click(cards[0])
  expect(await screen.findByRole('dialog')).toBeInTheDocument()
  expect(window.location.search).toBe('?q=103&view=list&clip=1')
  expect(window.history.length).toBe(lengthBefore + 1)
})

it('reloading a URL with a selected clip reopens the reader', async () => {
  renderAt('/dives?clip=2')
  const dialog = await screen.findByRole('dialog')
  expect(dialog).toBeInTheDocument()
  expect(screen.getByText('Native player uuid-2')).toBeInTheDocument()
})

it('invalid or stale clip identity fails safely and keeps the Library usable', async () => {
  renderAt('/dives?clip=999')
  await screen.findAllByRole('button', { name: /Open 103B attempt/ })
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  await waitFor(() => expect(window.location.search).not.toContain('clip='))
  expect((await screen.findAllByRole('button', { name: /Open 103B attempt/ })).length).toBeGreaterThan(0)
})

it('Next and Previous update the selected clip without history spam', async () => {
  renderAt('/dives?scope=all')
  const cards = await screen.findAllByRole('button', { name: /Open 103B attempt/ })
  const lengthBefore = window.history.length
  await userEvent.click(cards[0])
  expect(await screen.findByText('Native player uuid-1')).toBeInTheDocument()
  expect(window.history.length).toBe(lengthBefore + 1)

  await userEvent.click(screen.getByRole('button', { name: 'Next' }))
  expect(await screen.findByText('Native player uuid-2')).toBeInTheDocument()
  expect(window.location.search).toBe('?scope=all&clip=2')
  expect(window.history.length).toBe(lengthBefore + 1)

  await userEvent.click(screen.getByRole('button', { name: 'Previous' }))
  expect(await screen.findByText('Native player uuid-1')).toBeInTheDocument()
  expect(window.location.search).toBe('?scope=all&clip=1')
  expect(window.history.length).toBe(lengthBefore + 1)
})

it('browser Back closes the reader before leaving the Library', async () => {
  renderAt('/dives?q=103&view=list')
  const cards = await screen.findAllByRole('button', { name: /Open 103B attempt/ })
  await userEvent.click(cards[0])
  expect(await screen.findByRole('dialog')).toBeInTheDocument()
  window.history.back()
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(window.location.pathname).toBe('/dives')
  expect(window.location.search).toBe('?q=103&view=list')
})

it('the close control removes clip state without adding history noise', async () => {
  renderAt('/dives?scope=all')
  const cards = await screen.findAllByRole('button', { name: /Open 103B attempt/ })
  await userEvent.click(cards[0])
  expect(await screen.findByRole('dialog')).toBeInTheDocument()
  const lengthAfterOpen = window.history.length
  await userEvent.click(screen.getByRole('button', { name: 'Close attempt' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(window.location.search).toBe('?scope=all')
  expect(window.history.length).toBe(lengthAfterOpen)
})

it(
  'expanded result depth survives the clip loop; filter changes still reset it',
  async () => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === '/api/v1/divers') return Promise.resolve({ data: divers })
      return Promise.resolve({ data: mockDives(120, 61) })
    })
    renderAt('/dives?scope=all')
    const showMore = () => screen.queryByRole('button', { name: 'Show 48 more attempts' })
    await screen.findAllByRole('button', { name: /Open 103B attempt/ })
    for (let i = 0; i < 3 && showMore(); i += 1) {
      await userEvent.click(showMore()!)
    }
    await waitFor(() => expect(showMore()).not.toBeInTheDocument())

    const cards = screen.getAllByRole('button', { name: /Open 103B attempt/ })
    await userEvent.click(cards[0])
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Close attempt' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(showMore()).not.toBeInTheDocument()

    const search = screen.getByRole('textbox', { name: 'Search dives' })
    await userEvent.type(search, 'smack')
    await waitFor(() => expect(showMore()).toBeInTheDocument(), { timeout: 4000 })
  },
  20000,
)

it('an empty result set is distinct from a failure and offers Clear filters', async () => {
  renderAt('/dives?scope=all')
  await screen.findAllByRole('button', { name: /Open 103B attempt/ })
  const search = screen.getByRole('textbox', { name: 'Search dives' })
  await userEvent.type(search, 'zzz')
  expect(await screen.findByText('No attempts match this search.')).toBeInTheDocument()
  expect(screen.queryByText('The dive library could not be loaded.')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: /Clear filters/ }))
  expect(await screen.findAllByRole('button', { name: /Open 103B attempt/ })).toHaveLength(6)
})

it('a library load failure exposes what failed and a working Retry', async () => {
  vi.mocked(api.get).mockRejectedValueOnce(new Error('network down'))
  renderAt('/dives')
  expect(await screen.findByText('The dive library could not be loaded.')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
  expect((await screen.findAllByRole('button', { name: /Open 103B attempt/ })).length).toBeGreaterThan(0)
  expect(screen.queryByText('The dive library could not be loaded.')).not.toBeInTheDocument()
})
