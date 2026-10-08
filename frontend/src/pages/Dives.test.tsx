import React from 'react'
import { MemoryRouter } from 'react-router-dom'
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
  id, dive_code: code, diver_id: diverId, performance: 'G', performance_numeric: 3, height: '1m', dive_datetime: `2026-07-${String(id).padStart(2, '0')}T10:00:00`, session_id: 1, is_lineup: false, is_sync: false, platform_type: 'springboard', position: code.slice(-1), official_dd: 1.5, phase1_performance: 'G', phase2_performance: 'G', raw_caption: `${code} G/G`, video_uuid: `uuid-${id}`, ...options,
})

function renderPage() { return render(<MemoryRouter initialEntries={['/dives']}><Dives /></MemoryRouter>) }

beforeEach(() => {
  vi.mocked(getMediaStatus).mockResolvedValue({ poster_url: null, playback_url: null } as any)
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === '/api/v1/divers') return Promise.resolve({ data: [{ id: 1, display_name: 'Maxime', is_primary_user: true }, { id: 2, display_name: 'Paul', is_primary_user: false }] })
    return Promise.resolve({ data: [
      dive(1, '103B', 1),
      dive(2, '103C', 1, { height: '3m', is_sync: true, raw_caption: '103C G/G DB SYNC' }),
      dive(3, '103B', 2, { raw_caption: '103B G/G SD' }),
    ] })
  })
})

it('defaults to primary diver and exposes other divers only intentionally', async () => {
  renderPage()
  expect((await screen.findAllByText('103C')).length).toBeGreaterThan(0)
  const ownCodeCount = screen.getAllByText('103B').length
  await userEvent.click(screen.getByRole('button', { name: 'Community' }))
  expect((await screen.findAllByText('103B')).length).toBeGreaterThan(ownCodeCount)
})

it('filters natural search tokens and opens the exact attempt viewer', async () => {
  renderPage()
  const search = await screen.findByRole('textbox', { name: 'Search dives' })
  await userEvent.type(search, '103 3m SYNC DB')
  // The matching card is also present before filtering. Wait for the
  // nonmatching cards to disappear before inspecting or opening results.
  await waitFor(() => expect(screen.queryAllByText('103B')).toHaveLength(0))
  expect(screen.getAllByText('103C').length).toBeGreaterThan(0)
  await userEvent.click((await screen.findAllByRole('button', { name: /Open 103C attempt/ }))[0])
  expect(await screen.findByRole('dialog')).toBeInTheDocument()
  expect(document.body.style.overflow).toBe('hidden')
  expect(screen.getByText('Native player uuid-2')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Analysis' })).toHaveAttribute('href', '/dives/analysis/103C?attempt=2')
  await userEvent.click(screen.getByRole('button', { name: 'Back to Library' }))
  expect(document.body.style.overflow).toBe('')
})

// ---- U4/U5: modal isolation + focus lifecycle ----

it('the mounted Library becomes inert while the viewer is open and recovers on close', async () => {
  renderPage()
  const card = (await screen.findAllByRole('button', { name: /Open .* attempt/ }))[0]
  await userEvent.click(card)
  expect(await screen.findByRole('dialog')).toBeInTheDocument()
  expect(card.closest('[inert]')).not.toBeNull()
  await userEvent.click(screen.getByRole('button', { name: 'Back to Library' }))
  await waitFor(() => expect(card.closest('[inert]')).toBeNull())
})

it('closing the viewer returns focus to the originating Library card', async () => {
  renderPage()
  const card = (await screen.findAllByRole('button', { name: /Open 103B attempt/ }))[0]
  await userEvent.click(card)
  await screen.findByRole('dialog')
  await userEvent.click(screen.getByRole('button', { name: 'Back to Library' }))
  await waitFor(() => expect(document.activeElement).toBe(card))
})

it('closing the viewer falls back to Library search when the originating card is gone', async () => {
  renderPage()
  const search = await screen.findByRole('textbox', { name: 'Search dives' })
  await userEvent.type(search, '103C')
  const card = (await screen.findAllByRole('button', { name: /Open 103C attempt/ }))[0]
  await userEvent.click(card)
  await screen.findByRole('dialog')
  // Filter away the originating clip (103C is 3m): the viewer closes automatically.
  await userEvent.type(search, ' 1m')
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  await waitFor(() => expect(document.activeElement).toBe(search))
})

it('Library loading, empty and error states are distinguishable and announced', async () => {
  vi.mocked(api.get).mockImplementation(() => Promise.reject(new Error('network down')))
  renderPage()
  const alert = await screen.findByRole('alert')
  expect(alert).toHaveTextContent('The dive library could not be loaded.')
  expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
})

// ---- Library views: mobile clip wall + by-code summary ----

it('groups attempts per dive code and opens an attempt from its history', async () => {
  renderPage()
  await userEvent.click(await screen.findByRole('button', { name: 'Community' }))
  await userEvent.click(screen.getByRole('button', { name: 'Code view' }))
  expect(await screen.findByText(/2 attempts/)).toBeInTheDocument()
  expect(screen.getByText(/1 attempts/)).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /^Open 103B attempt$/ })).toBeNull()
  await userEvent.click(screen.getAllByRole('button', { name: /Open 103C attempt from/ })[0])
  expect(await screen.findByRole('dialog')).toBeInTheDocument()
  expect(screen.getByText('Native player uuid-2')).toBeInTheDocument()
})

it('the mobile switch toggles between the clip wall and the code summary', async () => {
  renderPage()
  const clips = await screen.findByRole('button', { name: 'Clips' })
  expect(clips).toHaveAttribute('aria-pressed', 'true')
  await userEvent.click(screen.getByRole('button', { name: 'By code' }))
  expect(screen.getByRole('button', { name: 'By code' })).toHaveAttribute('aria-pressed', 'true')
  expect((await screen.findAllByText(/attempts · last/)).length).toBe(2)
  await userEvent.click(screen.getByRole('button', { name: 'Clips' }))
  expect(screen.queryByText(/attempts · last/)).toBeNull()
})
