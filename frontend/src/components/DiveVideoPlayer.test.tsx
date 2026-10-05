import React from 'react'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import DiveVideoPlayer, {
  INITIAL_STATUS_ATTEMPTS,
  LONG_PREPARATION_MS,
  MAX_POLL_FAILURES,
  MEDIA_POLL_INTERVAL_MS,
} from './DiveVideoPlayer'
import { getMediaStatus, requestMedia, type MediaStatus } from '../services/mediaApi'

vi.mock('../services/mediaApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/mediaApi')>()
  return { ...actual, getMediaStatus: vi.fn(), requestMedia: vi.fn() }
})

const missing = { video_uuid: 'uuid', status: 'missing', can_request: true, available_renditions: [], playback_url: null, poster_url: null, job: null }
const transcoding = { ...missing, status: 'transcoding', can_request: false }
const ready = { ...missing, status: 'ready', playback_url: '/cached.mp4' }
it('immersive clips attempt autoplay with sound on metadata load', async () => {
  vi.mocked(getMediaStatus).mockResolvedValue(ready)
  const playSpy = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined)
  try {
    render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="uuid" immersive />)
    const video = await screen.findByLabelText('103B 1m dive video') as HTMLVideoElement
    await waitFor(() => expect(video).toHaveAttribute('src', '/cached.mp4'))
    expect(video.autoplay).toBe(true)
    fireEvent.loadedMetadata(video)
    await waitFor(() => expect(playSpy).toHaveBeenCalled())
    // Sound stays on when the browser allows unmuted autoplay.
    expect(video.muted).toBe(false)
    expect(screen.getByRole('button', { name: 'Mute video' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Mute video' }))
    expect(video.muted).toBe(true)
    fireEvent.volumeChange(video)
    fireEvent.click(screen.getByRole('button', { name: 'Unmute video' }))
    expect(video.muted).toBe(false)
  } finally {
    playSpy.mockRestore()
  }
})
it('immersive clips fall back to muted autoplay when sound is blocked', async () => {
  vi.mocked(getMediaStatus).mockResolvedValue(ready)
  const playSpy = vi.spyOn(HTMLMediaElement.prototype, 'play')
    .mockImplementationOnce(() => Promise.reject(new DOMException('play() was blocked', 'NotAllowedError')))
    .mockResolvedValue(undefined)
  try {
    render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="uuid" immersive />)
    const video = await screen.findByLabelText('103B 1m dive video') as HTMLVideoElement
    await waitFor(() => expect(video).toHaveAttribute('src', '/cached.mp4'))
    fireEvent.loadedMetadata(video)
    // First attempt (with sound) rejected → muted retry still starts the clip.
    await waitFor(() => expect(playSpy).toHaveBeenCalledTimes(2))
    expect(video.muted).toBe(true)
    fireEvent.volumeChange(video)
    expect(screen.getByRole('button', { name: 'Unmute video' })).toBeInTheDocument()
  } finally {
    playSpy.mockRestore()
  }
})
it('immersive canplay nudges a still-paused clip', async () => {
  vi.mocked(getMediaStatus).mockResolvedValue(ready)
  const playSpy = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined)
  try {
    render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="uuid" immersive />)
    const video = await screen.findByLabelText('103B 1m dive video') as HTMLVideoElement
    await waitFor(() => expect(video).toHaveAttribute('src', '/cached.mp4'))
    fireEvent.canPlay(video)
    await waitFor(() => expect(playSpy).toHaveBeenCalled())
  } finally {
    playSpy.mockRestore()
  }
})
it('non-immersive clips never attempt autoplay', async () => {
  vi.mocked(getMediaStatus).mockResolvedValue(ready)
  const playSpy = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined)
  try {
    render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="uuid" />)
    const video = await screen.findByLabelText('103B 1m dive video') as HTMLVideoElement
    await waitFor(() => expect(video).toHaveAttribute('src', '/cached.mp4'))
    expect(video.autoplay).toBe(false)
    fireEvent.loadedMetadata(video)
    fireEvent.canPlay(video)
    await act(async () => {})
    expect(playSpy).not.toHaveBeenCalled()
  } finally {
    playSpy.mockRestore()
  }
})
beforeEach(() => { vi.mocked(getMediaStatus).mockResolvedValue(missing); vi.mocked(requestMedia).mockResolvedValue({ ...missing, status: 'queued', created_job: true }) })
afterEach(() => { vi.useRealTimers() })

it('checks status passively without creating a job', async () => { render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="uuid" />); expect(await screen.findByRole('button', { name: /Prepare clip/ })).toBeInTheDocument(); expect(getMediaStatus).toHaveBeenCalledOnce(); expect(requestMedia).not.toHaveBeenCalled() })
it('Prepare clip explicitly creates one proxy request', async () => { render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="uuid" />); await userEvent.click(await screen.findByRole('button', { name: /Prepare clip/ })); expect(requestMedia).toHaveBeenCalledOnce(); expect(requestMedia).toHaveBeenCalledWith('uuid', 'proxy_720p') })
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

// ---- U4/U5: frontend transport-failure policy ----

function flushInitialCheck() {
  return act(async () => { await vi.advanceTimersByTimeAsync(0) })
}

it('a persistent initial status failure exits loading into an actionable retryable error', async () => {
  vi.useFakeTimers()
  vi.mocked(getMediaStatus).mockRejectedValue(new Error('network down'))
  render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="uuid" />)
  await flushInitialCheck()
  await act(async () => { await vi.advanceTimersByTimeAsync(INITIAL_STATUS_ATTEMPTS * 2000) })
  const alert = screen.getByRole('alert')
  expect(alert).toHaveTextContent(/Media status check failed/)
  expect(screen.getByRole('button', { name: 'Retry status check' })).toBeInTheDocument()
  expect(screen.queryByRole('status')).not.toBeInTheDocument()
  expect(getMediaStatus).toHaveBeenCalledTimes(INITIAL_STATUS_ATTEMPTS)
})

it('the bounded retry policy is finite and deterministic', async () => {
  vi.useFakeTimers()
  vi.mocked(getMediaStatus).mockRejectedValue(new Error('network down'))
  render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="uuid" />)
  await act(async () => { await vi.advanceTimersByTimeAsync(60_000) })
  expect(getMediaStatus).toHaveBeenCalledTimes(INITIAL_STATUS_ATTEMPTS)
})

it('Retry status check re-runs the lookup and never posts a prepare request', async () => {
  vi.useFakeTimers()
  vi.mocked(getMediaStatus).mockRejectedValue(new Error('network down'))
  render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="uuid" />)
  await act(async () => { await vi.advanceTimersByTimeAsync(60_000) })
  vi.mocked(getMediaStatus).mockResolvedValue(ready)
  fireEvent.click(screen.getByRole('button', { name: 'Retry status check' }))
  await flushInitialCheck()
  expect(requestMedia).not.toHaveBeenCalled()
  expect(screen.getByLabelText('103B 1m dive video')).toHaveAttribute('src', '/cached.mp4')
})

it('a single transient poll failure preserves the last known state and recovery clears it', async () => {
  vi.useFakeTimers()
  vi.mocked(getMediaStatus)
    .mockResolvedValueOnce(transcoding)
    .mockRejectedValueOnce(new Error('network down'))
    .mockResolvedValue(transcoding)
  render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="uuid" />)
  await flushInitialCheck()
  expect(screen.getByRole('status')).toHaveTextContent('Preparing media: transcoding')
  await act(async () => { await vi.advanceTimersByTimeAsync(MEDIA_POLL_INTERVAL_MS) })
  expect(screen.getByRole('status')).toHaveTextContent('transcoding — connection interrupted')
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  await act(async () => { await vi.advanceTimersByTimeAsync(MEDIA_POLL_INTERVAL_MS) })
  expect(screen.getByRole('status')).toHaveTextContent('Preparing media: transcoding')
  expect(screen.getByRole('status').textContent).not.toContain('connection interrupted')
})

it('repeated poll failures terminalize into an actionable state and stop the automatic loop', async () => {
  vi.useFakeTimers()
  vi.mocked(getMediaStatus)
    .mockResolvedValueOnce(transcoding)
    .mockRejectedValue(new Error('network down'))
  render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="uuid" />)
  await flushInitialCheck()
  await act(async () => { await vi.advanceTimersByTimeAsync(MEDIA_POLL_INTERVAL_MS * MAX_POLL_FAILURES + 100) })
  const alert = screen.getByRole('alert')
  expect(alert).toHaveTextContent('transcoding — status checks stopped')
  expect(screen.getByRole('button', { name: 'Check status again' })).toBeInTheDocument()
  const callsAfterStop = vi.mocked(getMediaStatus).mock.calls.length
  await act(async () => { await vi.advanceTimersByTimeAsync(MEDIA_POLL_INTERVAL_MS * 4) })
  expect(vi.mocked(getMediaStatus).mock.calls.length).toBe(callsAfterStop)
})

it('Check status again recovers polling after repeated transport failures', async () => {
  vi.useFakeTimers()
  vi.mocked(getMediaStatus)
    .mockResolvedValueOnce(transcoding)
    .mockRejectedValue(new Error('network down'))
  render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="uuid" />)
  await flushInitialCheck()
  await act(async () => { await vi.advanceTimersByTimeAsync(MEDIA_POLL_INTERVAL_MS * MAX_POLL_FAILURES + 100) })
  vi.mocked(getMediaStatus).mockResolvedValue(ready)
  fireEvent.click(screen.getByRole('button', { name: 'Check status again' }))
  await flushInitialCheck()
  expect(screen.getByLabelText('103B 1m dive video')).toHaveAttribute('src', '/cached.mp4')
  expect(requestMedia).not.toHaveBeenCalled()
})

it('a legitimate long-running preparation is never marked failed and stays actionable', async () => {
  vi.useFakeTimers()
  vi.mocked(getMediaStatus).mockResolvedValue(transcoding)
  render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="uuid" />)
  await flushInitialCheck()
  expect(screen.getByRole('status')).toHaveTextContent('Preparing media: transcoding')
  await act(async () => { await vi.advanceTimersByTimeAsync(LONG_PREPARATION_MS + MEDIA_POLL_INTERVAL_MS * 2) })
  expect(screen.getByRole('status')).toHaveTextContent('Still preparing')
  expect(screen.getByRole('button', { name: 'Check status now' })).toBeInTheDocument()
  expect(screen.queryByText('No video available')).not.toBeInTheDocument()
})

it('unchanged polls do not change the announced status text', async () => {
  vi.useFakeTimers()
  vi.mocked(getMediaStatus).mockResolvedValue(transcoding)
  render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="uuid" />)
  await flushInitialCheck()
  const region = screen.getByRole('status')
  const before = region.textContent
  await act(async () => { await vi.advanceTimersByTimeAsync(MEDIA_POLL_INTERVAL_MS * 3) })
  expect(screen.getByRole('status')).toBe(region)
  expect(region.textContent).toBe(before)
})

it('double-clicking Prepare clip does not submit duplicate preparation requests', async () => {
  vi.mocked(requestMedia).mockImplementation(
    () => new Promise((resolve) => setTimeout(() => resolve({ ...missing, status: 'queued', created_job: true }), 50)),
  )
  render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="uuid" />)
  const button = await screen.findByRole('button', { name: /Prepare clip/ })
  fireEvent.click(button)
  fireEvent.click(button)
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 80)) })
  expect(requestMedia).toHaveBeenCalledTimes(1)
})

it('Retry prepare remains an explicit action and is also duplicate-guarded', async () => {
  vi.mocked(getMediaStatus).mockResolvedValue({ ...missing, status: 'failed', can_request: true, job: { id: 1, status: 'failed', rendition: 'proxy_360p', last_error: 'proxy export failed' } })
  vi.mocked(requestMedia).mockImplementation(
    () => new Promise((resolve) => setTimeout(() => resolve({ ...missing, status: 'queued', created_job: true }), 50)),
  )
  render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="uuid" />)
  const button = await screen.findByRole('button', { name: /Retry prepare/ })
  fireEvent.click(button)
  fireEvent.click(button)
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 80)) })
  expect(requestMedia).toHaveBeenCalledTimes(1)
  expect(requestMedia).toHaveBeenCalledWith('uuid', 'proxy_720p')
  expect(await screen.findByRole('status')).toHaveTextContent('Preparing media: queued')
})

it('a video decode error exposes an accessible retry that re-checks status without new jobs', async () => {
  vi.mocked(getMediaStatus).mockResolvedValue(ready)
  const loadSpy = vi.spyOn(HTMLMediaElement.prototype, 'load')
  render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="uuid" />)
  const video = await screen.findByLabelText('103B 1m dive video')
  fireEvent.error(video)
  const alert = screen.getByRole('alert')
  expect(alert).toHaveTextContent('Video failed to load')
  loadSpy.mockClear()
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  await waitFor(() => expect(getMediaStatus).toHaveBeenCalledTimes(2))
  await waitFor(() => expect(loadSpy).toHaveBeenCalled())
  expect(requestMedia).not.toHaveBeenCalled()
})

it('media readiness is announced once and preparation states use status semantics', async () => {
  vi.useFakeTimers()
  vi.mocked(getMediaStatus).mockResolvedValue(ready)
  const { rerender } = render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="uuid" />)
  await flushInitialCheck()
  expect(screen.getByRole('status')).toHaveTextContent('Media ready.')
  rerender(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="uuid" />)
  expect(screen.getByRole('status')).toHaveTextContent('Media ready.')
})

it('a status failure never destroys a previously known preparation state presentation', async () => {
  vi.useFakeTimers()
  vi.mocked(getMediaStatus)
    .mockResolvedValueOnce(transcoding)
    .mockRejectedValue(new Error('network down'))
  render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="uuid" />)
  await flushInitialCheck()
  await act(async () => { await vi.advanceTimersByTimeAsync(MEDIA_POLL_INTERVAL_MS * 2) })
  // last known state label is still visible, framed as interrupted — not failed
  expect(screen.getByRole('status').textContent).toContain('transcoding')
  expect(screen.queryByText('No video available')).not.toBeInTheDocument()
})
