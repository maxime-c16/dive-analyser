import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import SessionVideoPage, { SessionVideoList } from './SessionVideos'
import { api } from '../services/api'

vi.mock('../services/api', () => ({ api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() } }))
const video = {
  id: 3, session_id: 9, filename: 'IMG_2651.MOV', recorded_at: null, recorded_date: '2026-10-17', duration_seconds: 1936.8,
  size_bytes: 3338404955, codec_string: 'hvc1.2.4.L123.B0', audio_codec_string: 'mp4a.40.2', video_codec: 'hevc',
  color_transfer: 'arib-std-b67', width: 1920, height: 1080, fps: 59.97, bit_rate: 13789351, can_share: true,
}

beforeEach(() => {
  vi.clearAllMocks()
  Object.defineProperty(window.navigator, 'mediaCapabilities', { value: { decodingInfo: async () => ({ supported: true }) }, configurable: true })
  vi.mocked(api.get).mockImplementation(async url => {
    if (url === '/api/v1/session-videos') return { data: { items: [video], has_more: false } }
    if (url === '/api/v1/session-videos/3') return { data: video }
    if (url === '/api/v1/session-videos/3/shares') return { data: { active_count: 0 } }
    throw new Error(`unexpected ${url}`)
  })
})

it('lists sessions linking to their page', async () => {
  render(<MemoryRouter><SessionVideoList /></MemoryRouter>)
  const link = await screen.findByRole('link', { name: /32 min · 3.3 GB/ })
  expect(link).toHaveAttribute('href', '/session-videos/3')
})

it('plays the member stream and lets the owner share through the session endpoints', async () => {
  const { container } = render(<MemoryRouter initialEntries={['/session-videos/3']}><Routes><Route path="/session-videos/:videoId" element={<SessionVideoPage />} /></Routes></MemoryRouter>)
  await waitFor(() => expect(container.querySelector('video')).toHaveAttribute('src', '/api/v1/session-videos/3/play'))
  expect(screen.getByRole('button', { name: 'Share session' })).toBeInTheDocument()
  await waitFor(() => expect(api.get).toHaveBeenCalledWith('/api/v1/session-videos/3/shares'))
})

it('hides sharing from members who do not own the session', async () => {
  vi.mocked(api.get).mockResolvedValue({ data: { ...video, can_share: false } })
  const { container } = render(<MemoryRouter initialEntries={['/session-videos/3']}><Routes><Route path="/session-videos/:videoId" element={<SessionVideoPage />} /></Routes></MemoryRouter>)
  await waitFor(() => expect(container.querySelector('video')).not.toBeNull())
  expect(screen.queryByRole('button', { name: 'Share session' })).not.toBeInTheDocument()
})
