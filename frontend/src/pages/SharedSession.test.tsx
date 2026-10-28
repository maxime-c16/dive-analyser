import { StrictMode } from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import SharedSession from './SharedSession'
import { api } from '../services/api'

vi.mock('../services/api', () => ({ api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() } }))
const token = 's'.repeat(43)
const video = {
  id: 3, session_id: 9, filename: 'IMG_2651.MOV', recorded_at: null, recorded_date: '2026-10-17', duration_seconds: 1936.8,
  size_bytes: 3338404955, codec_string: 'hvc1.2.4.L123.B0', audio_codec_string: 'mp4a.40.2', video_codec: 'hevc',
  color_transfer: 'arib-std-b67', width: 1920, height: 1080, fps: 59.97, bit_rate: 13789351, can_share: false,
  guest_id: 8, guest_name: 'Dobby', video_url: '/api/v1/shared-dives/sessions/7/video', download_url: '/api/v1/shared-dives/sessions/7/download',
}
const page = (path = `/share/session/7#${token}`) => <MemoryRouter initialEntries={[path]}><Routes><Route path="/share/session/:shareId" element={<SharedSession />} /></Routes></MemoryRouter>

beforeEach(() => {
  vi.clearAllMocks()
  Object.defineProperty(window.navigator, 'mediaCapabilities', { value: { decodingInfo: async () => ({ supported: true }) }, configurable: true })
})

it('exchanges the fragment secret once and plays the guest stream', async () => {
  vi.mocked(api.post).mockResolvedValue({ data: video })
  const { container } = render(<StrictMode>{page()}</StrictMode>)
  expect(await screen.findByText('32 min · 3.3 GB')).toBeInTheDocument()
  expect(api.post).toHaveBeenCalledTimes(1)
  expect(api.post).toHaveBeenCalledWith('/api/v1/shared-dives/sessions/7/visit', null, { headers: { 'X-Dive-Share': token } })
  await waitFor(() => expect(container.querySelector('video')).toHaveAttribute('src', video.video_url))
  expect(api.get).not.toHaveBeenCalled()
})

it('rejects a link without its secret before any request', async () => {
  render(page('/share/session/7'))
  expect(await screen.findByRole('alert')).toHaveTextContent('invalid')
  expect(api.post).not.toHaveBeenCalled()
})

it('reports a revoked link as unavailable', async () => {
  vi.mocked(api.post).mockRejectedValue(new Error('404'))
  render(page())
  expect(await screen.findByRole('alert')).toHaveTextContent('unavailable')
})
