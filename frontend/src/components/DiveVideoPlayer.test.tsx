import React from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import DiveVideoPlayer from './DiveVideoPlayer'
import { getMediaStatus, requestMedia } from '../services/mediaApi'

vi.mock('../services/mediaApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/mediaApi')>()
  return { ...actual, getMediaStatus: vi.fn(), requestMedia: vi.fn() }
})

const missing = { video_uuid: 'uuid', status: 'missing', can_request: true, available_renditions: [], playback_url: null, poster_url: null, job: null }
beforeEach(() => { vi.mocked(getMediaStatus).mockResolvedValue(missing); vi.mocked(requestMedia).mockResolvedValue({ ...missing, status: 'queued', created_job: true }) })

it('checks status passively without creating a job', async () => { render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="uuid" />); expect(await screen.findByRole('button', { name: /Prepare clip/ })).toBeInTheDocument(); expect(getMediaStatus).toHaveBeenCalledOnce(); expect(requestMedia).not.toHaveBeenCalled() })
it('Prepare clip explicitly creates one proxy request', async () => { render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="uuid" />); await userEvent.click(await screen.findByRole('button', { name: /Prepare clip/ })); expect(requestMedia).toHaveBeenCalledOnce(); expect(requestMedia).toHaveBeenCalledWith('uuid', 'proxy_360p') })
it('uses only native controls once a clip is playable', async () => { vi.mocked(getMediaStatus).mockResolvedValue({ ...missing, status: 'ready', playback_url: '/cached.mp4', poster_url: '/poster.jpg' }); render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="uuid" />); const video = await screen.findByLabelText('103B 1m dive video'); expect(video).toHaveAttribute('controls'); expect(screen.queryByRole('slider')).not.toBeInTheDocument(); expect(screen.queryByRole('button', { name: /pause|mute/i })).not.toBeInTheDocument() })
it('applies the requested playback rate to the video element', async () => {
  vi.mocked(getMediaStatus).mockResolvedValue({ ...missing, status: 'ready', playback_url: '/cached.mp4' })
  render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="uuid" playbackRate={0.5} />)
  const video = (await screen.findByLabelText('103B 1m dive video')) as HTMLVideoElement
  expect(video.playbackRate).toBe(0.5)
})
it('defaults to 1x when no rate is requested', async () => {
  vi.mocked(getMediaStatus).mockResolvedValue({ ...missing, status: 'ready', playback_url: '/cached.mp4' })
  render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="uuid" />)
  const video = (await screen.findByLabelText('103B 1m dive video')) as HTMLVideoElement
  expect(video.playbackRate).toBe(1)
})
