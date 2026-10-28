import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SessionVideoPlayer from './SessionVideoPlayer'
import { canDecode, framesRendered, videoContentType } from './playability'
import { api } from '../../services/api'
import type { SessionVideoInfo } from '../../services/sessionVideosApi'

vi.mock('../../services/api', () => ({ api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() } }))

const info: SessionVideoInfo = {
  id: 3, session_id: 9, filename: 'IMG_2651.MOV', recorded_at: '2026-10-17T11:05:10+00:00', recorded_date: '2026-10-17',
  duration_seconds: 1936.8, size_bytes: 3338404955, codec_string: 'hvc1.2.4.L123.B0', audio_codec_string: 'mp4a.40.2',
  video_codec: 'hevc', color_transfer: 'arib-std-b67', width: 1920, height: 1080, fps: 59.97, bit_rate: 13789351, can_share: false,
}
const urls = { playUrl: '/api/v1/session-videos/3/play', downloadUrl: '/api/v1/session-videos/3/download', reportUrl: '/api/v1/session-videos/3/playback-issues' }

function stubCapabilities(supported: boolean) {
  const decodingInfo = vi.fn(async () => ({ supported }))
  Object.defineProperty(window.navigator, 'mediaCapabilities', { value: { decodingInfo }, configurable: true })
  return decodingInfo
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.post).mockResolvedValue({ data: null })
})

describe('playability', () => {
  it('asks MediaCapabilities about the stored codec', async () => {
    const decodingInfo = stubCapabilities(true)
    await expect(canDecode(info)).resolves.toBe(true)
    expect(decodingInfo).toHaveBeenCalledWith({ type: 'file', video: { contentType: 'video/mp4; codecs="hvc1.2.4.L123.B0"', width: 1920, height: 1080, bitrate: 13789351, framerate: 59.97 } })
  })

  it('falls back to canPlayType', async () => {
    const probe = () => ({ canPlayType: (type: string) => (type.includes('avc1') ? 'probably' : '') }) as unknown as HTMLVideoElement
    await expect(canDecode(info, {}, probe)).resolves.toBe(false)
    await expect(canDecode({ ...info, codec_string: 'avc1.640028' }, {}, probe)).resolves.toBe(true)
    expect(videoContentType({ codec_string: null })).toBeNull()
  })

  it('treats audio over a black frame as not rendered', () => {
    const element = (width: number, frames: number) => ({ videoWidth: width, getVideoPlaybackQuality: () => ({ totalVideoFrames: frames }) }) as unknown as HTMLVideoElement
    expect(framesRendered(element(1920, 0))).toBe(false)
    expect(framesRendered(element(0, 30))).toBe(false)
    expect(framesRendered(element(1920, 30))).toBe(true)
  })
})

describe('SessionVideoPlayer', () => {
  it('plays the original when the device can decode it', async () => {
    stubCapabilities(true)
    const { container } = render(<SessionVideoPlayer info={info} {...urls} />)
    await waitFor(() => expect(container.querySelector('video')).toHaveAttribute('src', urls.playUrl))
    expect(api.post).not.toHaveBeenCalled()
  })

  it('offers only the download when the codec is unsupported, and counts it', async () => {
    stubCapabilities(false)
    const { container } = render(<SessionVideoPlayer info={info} {...urls} />)
    expect(await screen.findByText('This video doesn’t play here')).toBeInTheDocument()
    const link = screen.getByRole('link', { name: /Download · 3.3 GB/ })
    expect(link).toHaveAttribute('href', urls.downloadUrl)
    expect(container.querySelector('video')).toBeNull()
    expect(api.post).toHaveBeenCalledWith(urls.reportUrl, { reason: 'unsupported' })
  })

  it('switches to the download when no frame renders after playback starts', async () => {
    stubCapabilities(true)
    const { container } = render(<SessionVideoPlayer info={info} {...urls} />)
    await waitFor(() => expect(container.querySelector('video')).not.toBeNull())
    const video = container.querySelector('video')!
    Object.defineProperty(video, 'videoWidth', { value: 1920 })
    Object.defineProperty(video, 'getVideoPlaybackQuality', { value: () => ({ totalVideoFrames: 0 }) })
    Object.defineProperty(video, 'currentTime', { value: 2, writable: true })
    video.pause = vi.fn()
    fireEvent.timeUpdate(video)
    expect(await screen.findByText('This video doesn’t play here')).toBeInTheDocument()
    expect(api.post).toHaveBeenCalledTimes(1)
    expect(api.post).toHaveBeenCalledWith(urls.reportUrl, { reason: 'no_frames' })
  })

  it('refreshes an expired signed URL and resumes instead of giving up', async () => {
    stubCapabilities(true)
    const { container } = render(<SessionVideoPlayer info={info} {...urls} />)
    await waitFor(() => expect(container.querySelector('video')).not.toBeNull())
    const video = container.querySelector('video')!
    Object.defineProperty(video, 'error', { value: { code: 2 }, configurable: true })
    Object.defineProperty(video, 'currentTime', { value: 600, writable: true })
    fireEvent.error(video)
    await waitFor(() => expect(container.querySelector('video')).toHaveAttribute('src', `${urls.playUrl}?r=1`))
    expect(api.post).not.toHaveBeenCalled()
  })
})
