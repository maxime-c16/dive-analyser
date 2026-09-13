import React from 'react'
import { MemoryRouter } from 'react-router-dom'
import { render, screen } from '@testing-library/react'
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
  await userEvent.click(screen.getByRole('button', { name: 'Everyone' }))
  expect((await screen.findAllByText('103B')).length).toBeGreaterThan(ownCodeCount)
})

it('filters natural search tokens and opens the exact attempt viewer', async () => {
  renderPage()
  const search = await screen.findByRole('textbox', { name: 'Search dives' })
  await userEvent.type(search, '103 3m SYNC DB')
  expect((await screen.findAllByText('103C')).length).toBeGreaterThan(0)
  expect(screen.queryAllByText('103B')).toHaveLength(0)
  await userEvent.click((await screen.findAllByRole('button', { name: /Open 103C attempt/ }))[0])
  expect(await screen.findByRole('dialog')).toBeInTheDocument()
  expect(document.body.style.overflow).toBe('hidden')
  expect(screen.getByText('Native player uuid-2')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Analysis' })).toHaveAttribute('href', '/dives/analysis/103C')
  await userEvent.click(screen.getByRole('button', { name: 'Back to Library' }))
  expect(document.body.style.overflow).toBe('')
})
