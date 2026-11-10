import React from 'react'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi, type Mock } from 'vitest'
import DiveVideoPlayer, {
  INITIAL_STATUS_ATTEMPTS,
  LONG_PREPARATION_MS,
  MAX_AUTO_RECOVERIES,
  STATUS_DEFER_MS,
  MAX_POLL_FAILURES,
  MEDIA_POLL_INTERVAL_MS,
} from './DiveVideoPlayer'
import { getMediaStatus, requestMedia, type MediaStatus } from '../services/mediaApi'
import { getPreview, getPreviewForPlayback, resetMediaPreviews } from '../utils/mediaPreview'
import { getQualityPreference, recordThroughput, resetPlaybackPolicy, throughputEstimate } from '../utils/playbackPolicy'

vi.mock('../services/mediaApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/mediaApi')>()
  return { ...actual, getMediaStatus: vi.fn(), requestMedia: vi.fn() }
})

const missing = { video_uuid: 'uuid', status: 'missing', can_request: true, available_renditions: [], playback_url: null, poster_url: null, job: null }
const transcoding = { ...missing, status: 'transcoding', can_request: false }
const ready = { ...missing, status: 'ready', playback_url: '/cached.mp4' }

// Drives the loadeddata/readyState fallback to a presented first frame
// (HAVE_CURRENT_DATA + one compositor frame), revealing the cover and the
// transport affordances.
async function presentFirstFrame(video: HTMLVideoElement) {
  Object.defineProperty(video, 'readyState', { configurable: true, value: HTMLMediaElement.HAVE_CURRENT_DATA })
  fireEvent.loadedData(video)
  await act(async () => {
    await new Promise((resolve) => requestAnimationFrame(() => resolve(null)))
  })
}

// jsdom has no PointerEvent; the gesture layer reads isPrimary/pointerId.
class Pointer extends MouseEvent {
  isPrimary: boolean
  pointerId: number
  constructor(type: string, init: PointerEventInit = {}) {
    super(type, init)
    this.isPrimary = init.isPrimary ?? true
    this.pointerId = init.pointerId ?? 1
  }
}

/** Open the quality menu and pick one rendition by its visible name. */
function chooseQuality(name: string) {
  fireEvent.click(screen.getByRole('button', { name: 'Change video quality' }))
  fireEvent.click(screen.getByRole('menuitemradio', { name }))
}

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
    await presentFirstFrame(video)
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
    await presentFirstFrame(video)
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
it('immersive canplay never overrides an intentional pause', async () => {
  vi.mocked(getMediaStatus).mockResolvedValue(ready)
  const playSpy = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined)
  try {
    render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="uuid" immersive />)
    const video = await screen.findByLabelText('103B 1m dive video') as HTMLVideoElement
    await waitFor(() => expect(video).toHaveAttribute('src', '/cached.mp4'))
    fireEvent.loadedMetadata(video)
    await waitFor(() => expect(playSpy).toHaveBeenCalled())
    fireEvent.play(video)
    fireEvent.pause(video)
    playSpy.mockClear()
    // A later canplay (e.g. after seeking) must not resume playback.
    fireEvent.canPlay(video)
    await act(async () => {})
    expect(playSpy).not.toHaveBeenCalled()
  } finally {
    playSpy.mockRestore()
  }
})

it('forwards the immersive HUD signals up to the viewer', async () => {
  vi.mocked(getMediaStatus).mockResolvedValue(ready)
  const playSpy = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined)
  const pausedSpy = vi.fn()
  const pressSpy = vi.fn()
  vi.stubGlobal('PointerEvent', Pointer)
  try {
    render(
      <DiveVideoPlayer
        diveCode="103B"
        height="1m"
        videoUuid="uuid"
        immersive
        onHudPauseChange={pausedSpy}
        onHudPressChange={pressSpy}
      />,
    )
    const video = await screen.findByLabelText('103B 1m dive video') as HTMLVideoElement
    await waitFor(() => expect(video).toHaveAttribute('src', '/cached.mp4'))
    // Mounting the transport announces the controlling element's initial
    // paused state, and every later real transition follows through.
    await waitFor(() => expect(pausedSpy).toHaveBeenCalledWith(true))
    Object.defineProperty(video, 'paused', { configurable: true, get: () => false })
    fireEvent.play(video)
    expect(pausedSpy).toHaveBeenLastCalledWith(false)
    Object.defineProperty(video, 'paused', { configurable: true, get: () => true })
    fireEvent.pause(video)
    expect(pausedSpy).toHaveBeenLastCalledWith(true)
    // The 2× hold surfaces as a press on the HUD channel, and releases.
    const surface = screen.getByRole('button', { name: 'Play video' })
    fireEvent.pointerDown(surface, { button: 0 })
    await act(async () => {
      await new Promise((resolve) => window.setTimeout(resolve, 380))
    })
    expect(pressSpy).toHaveBeenLastCalledWith(true)
    fireEvent.pointerUp(surface)
    expect(pressSpy).toHaveBeenLastCalledWith(false)
    // The press changed no playback state: the pause channel is untouched.
    expect(pausedSpy).toHaveBeenLastCalledWith(true)
  } finally {
    playSpy.mockRestore()
  }
})

// The gesture overlay and the transport row share one paused state read
// from the live element: whichever of play/pause/external interplay
// happens, both aria labels must name the action available NOW, never a
// stale "Pause video" over a paused element.
it('both play/pause labels follow the real element state, including external changes', async () => {
  vi.mocked(getMediaStatus).mockResolvedValue(ready)
  const playSpy = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined)
  try {
    render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="ui-labels" immersive />)
    const video = await screen.findByLabelText('103B 1m dive video') as HTMLVideoElement
    await waitFor(() => expect(video).toHaveAttribute('src', '/cached.mp4'))
    await presentFirstFrame(video)
    // At mount the element is genuinely paused: the offered action is play.
    expect(screen.getByRole('button', { name: 'Play video' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Resume playback' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Pause video' })).not.toBeInTheDocument()

    // Playback starts (own toggle or autoplay): both labels flip to pause.
    Object.defineProperty(video, 'paused', { configurable: true, get: () => false })
    fireEvent.play(video)
    expect(screen.queryByRole('button', { name: 'Play video' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Resume playback' })).not.toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Pause video' })).toHaveLength(2)

    // Paused again — this time from an external cause (background tab, other
    // control): the labels must name the resume action again.
    Object.defineProperty(video, 'paused', { configurable: true, get: () => true })
    fireEvent.pause(video)
    expect(screen.getByRole('button', { name: 'Play video' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Resume playback' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Pause video' })).not.toBeInTheDocument()

    // A paint without state change (scrub, mute flip) never contradicts it.
    fireEvent.volumeChange(video)
    expect(screen.getByRole('button', { name: 'Resume playback' })).toBeInTheDocument()
  } finally {
    playSpy.mockRestore()
  }
})

it('switching clips rebinds the transport to the new element and its state', async () => {
  vi.mocked(getMediaStatus).mockImplementation(async (uuid: string) => ({
    ...ready,
    video_uuid: uuid,
    playback_url: `/cached-${uuid}.mp4`,
  }))
  const playSpy = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined)
  try {
    // The viewer keys the whole player per attempt, so a clip switch
    // remounts everything over a fresh pooled element.
    function PlayerHost({ uuid }: { uuid: string }) {
      return <DiveVideoPlayer key={uuid} diveCode="103B" height="1m" videoUuid={uuid} immersive />
    }
    const view = render(<PlayerHost uuid="clip-swap-a" />)
    const video = await screen.findByLabelText('103B 1m dive video') as HTMLVideoElement
    await waitFor(() => expect(video).toHaveAttribute('src', '/cached-clip-swap-a.mp4'))
    await presentFirstFrame(video)
    Object.defineProperty(video, 'paused', { configurable: true, get: () => false })
    fireEvent.play(video)
    expect(screen.getAllByRole('button', { name: 'Pause video' })).toHaveLength(2)

    // A sibling clip opens: the player element changes entirely. The
    // fresh element resumes paused, so the labels must follow IT — not
    // keep "Pause video" carried from the previous element.
    view.rerender(<PlayerHost uuid="clip-swap-b" />)
    const nextVideo = await screen.findByLabelText('103B 1m dive video') as HTMLVideoElement
    expect(nextVideo).not.toBe(video)
    await waitFor(() => expect(nextVideo).toHaveAttribute('src', '/cached-clip-swap-b.mp4'))
    await presentFirstFrame(nextVideo)
    expect(screen.getByRole('button', { name: 'Play video' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Resume playback' })).toBeInTheDocument()

    // Events from the retired element never drive the new transport.
    fireEvent.play(video)
    fireEvent.timeUpdate(video)
    expect(screen.getByRole('button', { name: 'Resume playback' })).toBeInTheDocument()
    // ...while the controlling (new) element still commands the labels.
    Object.defineProperty(nextVideo, 'paused', { configurable: true, get: () => false })
    fireEvent.play(nextVideo)
    expect(screen.getAllByRole('button', { name: 'Pause video' })).toHaveLength(2)
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
beforeEach(() => { resetPlaybackPolicy(); vi.mocked(getMediaStatus).mockResolvedValue(missing); vi.mocked(requestMedia).mockResolvedValue({ ...missing, status: 'queued', created_job: true }) })
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })

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

it('keeps polling while retrieving a source, then plays the prepared clip', async () => {
  vi.useFakeTimers()
  vi.mocked(getMediaStatus)
    .mockResolvedValueOnce({ ...missing, status: 'materializing' })
    .mockResolvedValue(ready)
  render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="uuid" />)
  await flushInitialCheck()
  expect(screen.getByRole('status')).toHaveTextContent('Preparing media: retrieving source video')
  expect(screen.queryByRole('button', { name: 'Prepare clip' })).not.toBeInTheDocument()
  await act(async () => { await vi.advanceTimersByTimeAsync(MEDIA_POLL_INTERVAL_MS) })
  expect(screen.getByLabelText('103B 1m dive video')).toHaveAttribute('src', '/cached.mp4')
  expect(requestMedia).not.toHaveBeenCalled()
})

it('shows a retrieval failure after an active preparation without silently resetting it', async () => {
  vi.useFakeTimers()
  vi.mocked(getMediaStatus)
    .mockResolvedValueOnce({ ...missing, status: 'materializing' })
    .mockResolvedValue({ ...missing, status: 'unavailable', job: {
      id: 1, status: 'unavailable', rendition: 'proxy_720p', last_error: 'source retrieval failed',
    } })
  render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="uuid" />)
  await flushInitialCheck()
  await act(async () => { await vi.advanceTimersByTimeAsync(MEDIA_POLL_INTERVAL_MS) })
  expect(screen.getByRole('alert')).toHaveTextContent('source retrieval failed')
  expect(screen.getByRole('button', { name: 'Retry prepare' })).toBeInTheDocument()
  expect(requestMedia).not.toHaveBeenCalled()
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

it('an original-only clip honestly shows original quality with an explicit prepare action', async () => {
  vi.mocked(getMediaStatus).mockResolvedValue(ready)
  render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="uuid" />)
  await screen.findByLabelText('103B 1m dive video')
  // The viewer keeps the playable original, but says so — and offers an
  // explicit compatible preparation instead of hiding it.
  expect(screen.getByText('Original')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: /Prepare clip/ }))
  expect(requestMedia).toHaveBeenCalledWith('uuid', 'proxy_720p')
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

// ---- Fast path: the shared preview cache seeds instant open/swipe ----

async function seedPreviewCache(uuid: string, playbackUrl: string | null, resolved = true) {
  resetMediaPreviews()
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ [uuid]: { status: 'ready', poster_url: '/seeded.jpg', playback_url: playbackUrl } }),
  }))
  if (resolved && playbackUrl) vi.mocked(getMediaStatus).mockResolvedValueOnce({ ...ready, playback_url: playbackUrl, poster_url: '/seeded.jpg' })
  const previews = [resolved ? getPreviewForPlayback(uuid) : getPreview(uuid)]
  await act(async () => { await vi.advanceTimersByTimeAsync(50) })
  return Promise.all(previews)
}

it('a seeded preview starts playback immediately without waiting for its own status GET', async () => {
  vi.useFakeTimers()
  vi.stubGlobal('fetch', vi.fn()) // batch lookup already consumed by the seeding helper
  await seedPreviewCache('seed-playback', '/seeded.mp4')
  // The authoritative status lookup stays pending: playback must not wait on it.
  vi.mocked(getMediaStatus).mockImplementation(() => new Promise(() => {}))
  render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="seed-playback" />)
  const video = screen.getByLabelText('103B 1m dive video') as HTMLVideoElement
  expect(video).toHaveAttribute('src', '/seeded.mp4')
  expect(video).toHaveAttribute('poster', '/seeded.jpg')
  // No checking spinner: bytes request is already underway.
  expect(screen.queryByRole('status', { name: 'Checking…' })).not.toBeInTheDocument()
})

it('an authoritative not-cached answer still overrides a seeded playback', async () => {
  vi.useFakeTimers()
  await seedPreviewCache('seed-playback', '/seeded.mp4')
  vi.mocked(getMediaStatus).mockResolvedValue(missing)
  render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="seed-playback" />)
  const video = screen.getByLabelText('103B 1m dive video')
  expect(video).toHaveAttribute('src', '/seeded.mp4')
  await flushInitialCheck()
  expect(screen.getByRole('status')).toHaveTextContent('Clip not cached')
})

it('status never reaching a verdict cannot strand seeded playback into an unreachable overlay', async () => {
  vi.useFakeTimers()
  await seedPreviewCache('seed-playback', '/seeded.mp4')
  vi.mocked(getMediaStatus).mockRejectedValue(new Error('network down'))
  render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="seed-playback" />)
  await act(async () => { await vi.advanceTimersByTimeAsync(INITIAL_STATUS_ATTEMPTS * 2000) })
  // Transport failure after a seeded playback keeps the actionable retry
  // affordance, but the seeded video remains in place instead of going dark.
  expect(screen.getByLabelText('103B 1m dive video')).toHaveAttribute('src', '/seeded.mp4')
  expect(screen.getByRole('button', { name: 'Retry status check' })).toBeInTheDocument()
})

it('a preview known to lack playback never fakes a ready clip', async () => {
  vi.useFakeTimers()
  await seedPreviewCache('poster-only-uuid', null)
  vi.mocked(getMediaStatus).mockImplementation(() => new Promise(() => {}))
  render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="poster-only-uuid" />)
  const video = screen.getByLabelText('103B 1m dive video')
  expect(video).not.toHaveAttribute('src')
  expect(video).toHaveAttribute('poster', '/seeded.jpg')
})

// ---- Incoming-clip cover: first paint through first presented frame ----
//
// The cover is the issue #57 guarantee: a known poster never disappears into
// black before the incoming video presents its real first frame, across
// synchronous seeds, source switches (A→B→A), decode retries and poster
// failures — with stale frame callbacks unable to reveal another generation.

async function seedPreviewNow(uuid: string, playbackUrl: string | null, posterUrl: string | null = '/seeded.jpg') {
  resetMediaPreviews()
  vi.stubGlobal('fetch', vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
    if (String(input).includes('/api/v1/media/status/batch')) {
      return {
        ok: true,
        json: async () => ({
          [uuid]: { status: playbackUrl ? 'ready' : 'missing', poster_url: posterUrl, playback_url: playbackUrl },
        }),
      }
    }
    return { ok: true, body: null, json: async () => ({}) }
  }))
  if (playbackUrl) vi.mocked(getMediaStatus).mockResolvedValueOnce({ ...ready, playback_url: playbackUrl, poster_url: posterUrl })
  await act(async () => { await getPreviewForPlayback(uuid) })
}

const cover = () => document.querySelector('[data-testid="clip-cover"]')
const coverImg = () => document.querySelector('[data-testid="clip-cover"] img')

interface FrameStub {
  request: Mock<[cb: (now: number) => void], number>
  cancel: Mock<[handle: number], void>
  callbacks: Array<((now: number) => void) | null>
  cancelled: number[]
  restore: () => void
}

/** Feature-detect override: makes the environment look like iOS Safari. */
function stubFrameCallbacks(): FrameStub {
  const callbacks: Array<((now: number) => void) | null> = []
  const cancelled: number[] = []
  const request = vi.fn((cb: (now: number) => void) => {
    callbacks.push(cb)
    return callbacks.length
  })
  const cancel = vi.fn((handle: number) => { cancelled.push(handle) })
  const proto = HTMLVideoElement.prototype as unknown as Record<string, unknown>
  const previous = {
    r: Object.getOwnPropertyDescriptor(proto, 'requestVideoFrameCallback'),
    c: Object.getOwnPropertyDescriptor(proto, 'cancelVideoFrameCallback'),
  }
  Object.defineProperty(proto, 'requestVideoFrameCallback', { configurable: true, value: request })
  Object.defineProperty(proto, 'cancelVideoFrameCallback', { configurable: true, value: cancel })
  return {
    request, cancel, callbacks, cancelled,
    restore() {
      if (previous.r) Object.defineProperty(proto, 'requestVideoFrameCallback', previous.r)
      else delete proto.requestVideoFrameCallback
      if (previous.c) Object.defineProperty(proto, 'cancelVideoFrameCallback', previous.c)
      else delete proto.cancelVideoFrameCallback
    },
  }
}

it('the first client paint adopts the seeded playback and poster under its cover', async () => {
  await seedPreviewNow('ssr-seed', '/seeded.mp4')
  vi.mocked(getMediaStatus).mockImplementation(() => new Promise(() => {}))
  const { container } = render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="ssr-seed" immersive />)
  const video = container.querySelector('video')!
  expect(video).toHaveAttribute('src', '/seeded.mp4')
  expect(video).toHaveAttribute('poster', '/seeded.jpg')
  expect(coverImg()).toHaveAttribute('src', '/seeded.jpg')
  expect(screen.queryByText('Checking…')).not.toBeInTheDocument()
})

it('a poster-only seed holds the cover through the initial status lookup', async () => {
  await seedPreviewNow('checking-cover', null, '/seeded.jpg')
  vi.mocked(getMediaStatus).mockImplementation(() => new Promise(() => {}))
  render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="checking-cover" immersive />)
  expect(coverImg()).toHaveAttribute('src', '/seeded.jpg')
  expect(screen.getByText('Loading video')).toBeInTheDocument()
})

it('metadata and canplay never reveal the cover; a decodable first frame does', async () => {
  await seedPreviewNow('frame-delay', '/seeded.mp4')
  vi.mocked(getMediaStatus).mockImplementation(() => new Promise(() => {}))
  render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="frame-delay" immersive />)
  const video = screen.getByLabelText('103B 1m dive video') as HTMLVideoElement
  expect(coverImg()).toHaveAttribute('src', '/seeded.jpg')
  fireEvent.loadedMetadata(video)
  fireEvent.canPlay(video)
  await act(async () => {})
  expect(cover()).toBeInTheDocument()
  await presentFirstFrame(video)
  expect(cover()).not.toBeInTheDocument()
})

it('an element that already holds decodable data reveals without waiting for an event', async () => {
  await seedPreviewNow('data-ready', '/seeded.mp4')
  vi.mocked(getMediaStatus).mockImplementation(() => new Promise(() => {}))
  const descriptor = Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype, 'readyState')
  Object.defineProperty(HTMLMediaElement.prototype, 'readyState', {
    configurable: true,
    get: () => HTMLMediaElement.HAVE_CURRENT_DATA,
  })
  try {
    render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="data-ready" immersive />)
    await act(async () => {
      await new Promise((resolve) => requestAnimationFrame(() => resolve(null)))
    })
    expect(cover()).not.toBeInTheDocument()
  } finally {
    if (descriptor) Object.defineProperty(HTMLMediaElement.prototype, 'readyState', descriptor)
  }
})

it('rVFC reveals the first frame; source switches cancel stale callbacks across A→B→A', async () => {
  await seedPreviewNow('rvfc-switch', '/a.mp4')
  vi.useFakeTimers()
  const frame = stubFrameCallbacks()
  const registeredHandles = () => frame.request.mock.results.map((r) => r.value)
  const fireActive = async () => {
    const registered = frame.callbacks.filter(Boolean) as Array<(now: number) => void>
    const active = registered[registered.length - 1]
    await act(async () => { active(0) })
  }
  const fireAllButActive = async () => {
    const registered = frame.callbacks.filter(Boolean) as Array<(now: number) => void>
    for (const cb of registered.slice(0, -1)) await act(async () => { cb(0) })
  }
  try {
    vi.mocked(getMediaStatus)
      .mockResolvedValueOnce({ ...missing, status: 'ready', playback_url: '/a.mp4', poster_url: '/poster.jpg' })
      .mockResolvedValueOnce({ ...missing, status: 'ready', playback_url: '/b.mp4', poster_url: '/poster.jpg' })
      .mockResolvedValue({ ...missing, status: 'ready', playback_url: '/a.mp4', poster_url: '/poster.jpg' })
    render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="rvfc-switch" immersive />)
    const video = screen.getByLabelText('103B 1m dive video') as HTMLVideoElement
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    expect(video).toHaveAttribute('src', '/a.mp4')
    expect(coverImg()).toHaveAttribute('src', '/poster.jpg')
    await fireActive()
    expect(cover()).not.toBeInTheDocument()

    // Entering the decode-error state restarts nothing behind the overlay:
    // no new callback registration, no element reload.
    const handlesBeforeError = registeredHandles().length
    fireEvent.error(video)
    expect(registeredHandles().length).toBe(handlesBeforeError)
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    expect(video).toHaveAttribute('src', '/b.mp4')
    // The cover holds again IMMEDIATELY, before any frame of the new source.
    expect(coverImg()).toHaveAttribute('src', '/poster.jpg')
    // Stale-safe handover: every superseded handle was cancelled, and firing
    // stale callbacks never reveals the active source's cover.
    expect(frame.cancelled).toEqual(expect.arrayContaining(registeredHandles().slice(0, -1)))
    await fireAllButActive()
    expect(cover()).toBeInTheDocument()
    await fireActive()
    expect(cover()).not.toBeInTheDocument()

    // A→B→A: returning to an earlier URL is a fresh load generation; the
    // presentation earned by /b.mp4 cannot satisfy the new /a.mp4 cycle.
    fireEvent.error(video)
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    expect(video).toHaveAttribute('src', '/a.mp4')
    expect(cover()).toBeInTheDocument()
    expect(frame.cancelled).toEqual(expect.arrayContaining(registeredHandles().slice(0, -1)))
    await fireAllButActive()
    expect(cover()).toBeInTheDocument()
    await fireActive()
    expect(cover()).not.toBeInTheDocument()
  } finally {
    vi.useRealTimers()
    frame.restore()
  }
})

it('an unfired frame callback cannot strand the cover once decodable data lands', async () => {
  await seedPreviewNow('rvfc-stuck', '/seeded.mp4')
  vi.mocked(getMediaStatus).mockImplementation(() => new Promise(() => {}))
  const frame = stubFrameCallbacks()
  try {
    render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="rvfc-stuck" immersive />)
    const video = screen.getByLabelText('103B 1m dive video') as HTMLVideoElement
    expect(frame.request).toHaveBeenCalledTimes(1)
    expect(cover()).toBeInTheDocument()
    // The single registered frame callback never fires (blocked autoplay,
    // background tab, browser quirk) — the loadeddata backstop on the rVFC
    // path must still drop the cover, or the poster freezes over the clip.
    await presentFirstFrame(video)
    expect(frame.callbacks.filter(Boolean)).toHaveLength(1)
    expect(cover()).not.toBeInTheDocument()
  } finally {
    frame.restore()
  }
})

it('real playback always drops the cover even when every frame signal failed', async () => {
  await seedPreviewNow('playing-stuck', '/seeded.mp4')
  vi.mocked(getMediaStatus).mockImplementation(() => new Promise(() => {}))
  const frame = stubFrameCallbacks()
  try {
    render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="playing-stuck" immersive />)
    const video = screen.getByLabelText('103B 1m dive video') as HTMLVideoElement
    expect(cover()).toBeInTheDocument()
    // No frame callback fired, no decodable-data event arrived — yet the
    // element plays. A playing video presents frames by definition, so the
    // cover must go and the transport must come back.
    fireEvent.playing(video)
    await act(async () => {})
    expect(frame.callbacks.filter(Boolean)).toHaveLength(1)
    expect(cover()).not.toBeInTheDocument()
    expect(document.querySelector('.clip-transport')).not.toBeNull()
    expect(document.querySelector('.clip-progress')).not.toBeNull()
  } finally {
    frame.restore()
  }
})

it('an autoplay attempt aborted by a source switch never steals sound', async () => {
  await seedPreviewNow('abort-mute', '/a.mp4')
  const abortError = new DOMException(
    'The play() request was interrupted by a new load request',
    'AbortError',
  )
  const playSpy = vi.spyOn(HTMLMediaElement.prototype, 'play')
    .mockImplementationOnce(() => Promise.reject(abortError))
    .mockResolvedValue(undefined)
  try {
    vi.mocked(getMediaStatus).mockResolvedValue({ ...missing, status: 'ready', playback_url: '/b.mp4', poster_url: '/poster.jpg' })
    render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="abort-mute" immersive />)
    const video = await screen.findByLabelText('103B 1m dive video') as HTMLVideoElement
    await waitFor(() => expect(video).toHaveAttribute('src', '/b.mp4'))
    fireEvent.loadedMetadata(video)
    await waitFor(() => expect(playSpy).toHaveBeenCalled())
    await act(async () => {})
    // Interrupted, not blocked: the fresh load's own handlers start the
    // clip, so there is no muted fallback and no retry storm.
    expect(playSpy).toHaveBeenCalledTimes(1)
    expect(video.muted).toBe(false)
  } finally {
    playSpy.mockRestore()
  }
})

it('mounting a seeded clip never restarts the element', async () => {
  await seedPreviewNow('no-reload', '/seeded.mp4')
  vi.mocked(getMediaStatus).mockResolvedValue({ ...missing, status: 'ready', playback_url: '/seeded.mp4', poster_url: '/poster.jpg' })
  const loadSpy = vi.spyOn(HTMLMediaElement.prototype, 'load')
  try {
    render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="no-reload" immersive />)
    const video = await screen.findByLabelText('103B 1m dive video')
    expect(video).toHaveAttribute('src', '/seeded.mp4')
    await presentFirstFrame(video as HTMLVideoElement)
    await act(async () => {})
    // Seeding, authoritative revalidation with the same URL, and first-frame
    // presentation all ride the element's own resource selection: no
    // explicit restart that would abort the native load and its autoplay.
    expect(loadSpy).not.toHaveBeenCalled()
    expect(cover()).not.toBeInTheDocument()
  } finally {
    loadSpy.mockRestore()
  }
})

it('the first gesture after a muted fallback restores sound', async () => {
  await seedPreviewNow('gesture-unmute', '/seeded.mp4')
  vi.mocked(getMediaStatus).mockImplementation(() => new Promise(() => {}))
  const playSpy = vi.spyOn(HTMLMediaElement.prototype, 'play')
    .mockImplementationOnce(() => Promise.reject(new DOMException('play() was blocked', 'NotAllowedError')))
    .mockResolvedValue(undefined)
  try {
    render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="gesture-unmute" immersive />)
    const video = screen.getByLabelText('103B 1m dive video') as HTMLVideoElement
    fireEvent.loadedMetadata(video)
    await waitFor(() => expect(video.muted).toBe(true))
    await waitFor(() => expect(playSpy).toHaveBeenCalledTimes(2))
    await act(async () => {})
    // The fallback sticks by itself (the scrolled-to dives stay silent
    // bug) — the first tap brings sound back automatically.
    fireEvent.pointerDown(document.body)
    await waitFor(() => expect(video.muted).toBe(false))
  } finally {
    playSpy.mockRestore()
  }
})

it('a manual unmute disarms gesture restoration', async () => {
  await seedPreviewNow('manual-unmute', '/seeded.mp4')
  vi.mocked(getMediaStatus).mockImplementation(() => new Promise(() => {}))
  const playSpy = vi.spyOn(HTMLMediaElement.prototype, 'play')
    .mockImplementationOnce(() => Promise.reject(new DOMException('play() was blocked', 'NotAllowedError')))
    .mockResolvedValue(undefined)
  try {
    render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="manual-unmute" immersive />)
    const video = screen.getByLabelText('103B 1m dive video') as HTMLVideoElement
    fireEvent.loadedMetadata(video)
    await waitFor(() => expect(video.muted).toBe(true))
    await act(async () => {})
    // The viewer unmutes from the transport: restoration stands down and a
    // later gesture must not replay or re-mute anything.
    await act(async () => {
      video.muted = false
      fireEvent.volumeChange(video)
    })
    fireEvent.pointerDown(document.body)
    await act(async () => {})
    expect(video.muted).toBe(false)
    expect(playSpy).toHaveBeenCalledTimes(2)
  } finally {
    playSpy.mockRestore()
  }
})

it('a tap on the mute control keeps its own toggle semantics', async () => {
  await seedPreviewNow('control-tap', '/seeded.mp4')
  vi.mocked(getMediaStatus).mockImplementation(() => new Promise(() => {}))
  const playSpy = vi.spyOn(HTMLMediaElement.prototype, 'play')
    .mockImplementationOnce(() => Promise.reject(new DOMException('play() was blocked', 'NotAllowedError')))
    .mockResolvedValue(undefined)
  try {
    render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="control-tap" immersive />)
    const video = screen.getByLabelText('103B 1m dive video') as HTMLVideoElement
    fireEvent.loadedMetadata(video)
    await waitFor(() => expect(video.muted).toBe(true))
    await presentFirstFrame(video)
    const unmute = await screen.findByRole('button', { name: 'Unmute video' })
    // The capture-phase restoration must not pre-empt the explicit control:
    // pointerdown on Unmute leaves the element muted so its click toggles
    // to unmuted instead of back to muted.
    fireEvent.pointerDown(unmute)
    await act(async () => {})
    expect(video.muted).toBe(true)
    // …and its click toggles straight to unmuted.
    fireEvent.click(unmute)
    expect(video.muted).toBe(false)
  } finally {
    playSpy.mockRestore()
  }
})

it('gestures on other controls still restore sound', async () => {
  await seedPreviewNow('other-control', '/seeded.mp4')
  vi.mocked(getMediaStatus).mockImplementation(() => new Promise(() => {}))
  const playSpy = vi.spyOn(HTMLMediaElement.prototype, 'play')
    .mockImplementationOnce(() => Promise.reject(new DOMException('play() was blocked', 'NotAllowedError')))
    .mockResolvedValue(undefined)
  try {
    render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="other-control" immersive />)
    const video = screen.getByLabelText('103B 1m dive video') as HTMLVideoElement
    fireEvent.loadedMetadata(video)
    await waitFor(() => expect(video.muted).toBe(true))
    await presentFirstFrame(video)
    // Only the sound toggle itself is exempt: a gesture starting on any
    // other control (here the transport play button) restores sound.
    const playToggle = document.querySelector('.clip-transport button') as Element
    fireEvent.pointerDown(playToggle)
    await waitFor(() => expect(video.muted).toBe(false))
  } finally {
    playSpy.mockRestore()
  }
})

it('a status-driven source switch holds the cover until the new source presents', async () => {
  await seedPreviewNow('status-switch', '/a.mp4')
  vi.useFakeTimers()
  const frame = stubFrameCallbacks()
  const fireActive = async () => {
    const registered = frame.callbacks.filter(Boolean) as Array<(now: number) => void>
    const active = registered[registered.length - 1]
    await act(async () => { active(0) })
  }
  const fireAllButActive = async () => {
    const registered = frame.callbacks.filter(Boolean) as Array<(now: number) => void>
    for (const cb of registered.slice(0, -1)) await act(async () => { cb(0) })
  }
  try {
    // The authoritative lookup fails terminally: the seeded playback stays
    // playable, and the manual retry is the only status path forward.
    vi.mocked(getMediaStatus).mockRejectedValue(new Error('network down'))
    render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="status-switch" immersive />)
    const video = screen.getByLabelText('103B 1m dive video') as HTMLVideoElement
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000) })
    expect(video).toHaveAttribute('src', '/a.mp4')
    expect(screen.getByRole('button', { name: 'Retry status check' })).toBeInTheDocument()
    await fireActive()
    expect(cover()).not.toBeInTheDocument()

    // Retry: the authoritative answer switches the source to /b.mp4.
    vi.mocked(getMediaStatus).mockReset()
    vi.mocked(getMediaStatus).mockResolvedValue({ ...missing, status: 'ready', playback_url: '/b.mp4', poster_url: '/poster.jpg' })
    fireEvent.click(screen.getByRole('button', { name: 'Retry status check' }))
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    expect(video).toHaveAttribute('src', '/b.mp4')
    // Held synchronously with the switch — before any frame of /b.mp4.
    expect(coverImg()).toHaveAttribute('src', '/poster.jpg')
    // Stale callbacks of /a.mp4 can never drop the cover of /b.mp4.
    await fireAllButActive()
    expect(cover()).toBeInTheDocument()
    await fireActive()
    expect(cover()).not.toBeInTheDocument()
  } finally {
    vi.useRealTimers()
    frame.restore()
  }
})

it('a same-URL decode retry opens a new generation with a real element restart', async () => {
  await seedPreviewNow('retry-same', '/same.mp4')
  vi.mocked(getMediaStatus).mockResolvedValue({ ...missing, status: 'ready', playback_url: '/same.mp4', poster_url: '/poster.jpg' })
  const loadSpy = vi.spyOn(HTMLMediaElement.prototype, 'load')
  render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="retry-same" immersive />)
  const video = screen.getByLabelText('103B 1m dive video') as HTMLVideoElement
  await presentFirstFrame(video)
  expect(cover()).not.toBeInTheDocument()
  const loadsAfterPresent = loadSpy.mock.calls.length

  // Entering the decode-error state restarts nothing behind the overlay.
  fireEvent.error(video)
  expect(loadSpy).toHaveBeenCalledTimes(loadsAfterPresent)
  expect(screen.getByRole('alert')).toHaveTextContent('Video unavailable')
  // The deliberate retry re-opens the gate with a real load() restart, even
  // though the URL is unchanged, and the cover holds until re-presentation.
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
  await act(async () => {})
  expect(loadSpy.mock.calls.length).toBeGreaterThan(loadsAfterPresent)
  expect(coverImg()).toHaveAttribute('src', '/poster.jpg')
  await presentFirstFrame(video)
  expect(cover()).not.toBeInTheDocument()
})

it('a failed poster image degrades to an honest non-black placeholder', async () => {
  await seedPreviewNow('poster-fail', '/seeded.mp4', '/broken.jpg')
  vi.mocked(getMediaStatus).mockImplementation(() => new Promise(() => {}))
  render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="poster-fail" immersive />)
  fireEvent.error(coverImg() as Element)
  expect(cover()?.querySelector('.clip-cover-empty')).not.toBeNull()
  expect(coverImg()).toBeNull()
})

it('a ready clip without any poster shows the placeholder instead of black', async () => {
  await seedPreviewNow('poster-missing', '/seeded.mp4', null)
  vi.mocked(getMediaStatus).mockImplementation(() => new Promise(() => {}))
  render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="poster-missing" immersive />)
  expect(cover()?.querySelector('.clip-cover-empty')).not.toBeNull()
  expect(coverImg()).toBeNull()
})

it('non-immersive players never render the incoming-clip cover', async () => {
  vi.mocked(getMediaStatus).mockResolvedValue(ready)
  render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="uuid" />)
  await screen.findByLabelText('103B 1m dive video')
  await act(async () => {})
  expect(cover()).toBeNull()
})

it('play/scrub affordances wait for the presented frame while gestures stay live', async () => {
  await seedPreviewNow('affordance-gate', '/seeded.mp4')
  vi.mocked(getMediaStatus).mockImplementation(() => new Promise(() => {}))
  render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="affordance-gate" immersive />)
  // Gesture capture stays mounted for the pager handoff over the cover…
  expect(document.querySelector('.clip-gesture')).not.toBeNull()
  // …but the 0 / 0s transport, scrub bar and play indicator wait for readiness.
  expect(document.querySelector('.clip-transport')).toBeNull()
  expect(document.querySelector('.clip-progress')).toBeNull()
  expect(document.querySelector('.clip-play-indicator')).toBeNull()
  const video = screen.getByLabelText('103B 1m dive video') as HTMLVideoElement
  await presentFirstFrame(video)
  expect(document.querySelector('.clip-transport')).not.toBeNull()
  expect(document.querySelector('.clip-progress')).not.toBeNull()
  expect(document.querySelector('.clip-play-indicator')).not.toBeNull()
})

it('starts on the preview and only loads the original after an explicit quality choice', async () => {
  vi.mocked(getMediaStatus).mockResolvedValue({ ...ready, full_quality_url: '/camera-hlg.mov', playback_url: '/camera-hlg.mov', preview_url: '/sdr-720.mp4' })
  render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="preview-first" immersive />)
  const video = await screen.findByLabelText('103B 1m dive video')
  await waitFor(() => expect(video).toHaveAttribute('src', '/sdr-720.mp4'))
  chooseQuality('Original')
  expect(video).toHaveAttribute('src', '/camera-hlg.mov')
  fireEvent.error(video)
  fireEvent.click(screen.getByRole('button', { name: 'Play a lower-quality preview' }))
  expect(video).toHaveAttribute('src', '/sdr-720.mp4')
})

it.each(['/api/v1/media/revisions/42/play', '/api/v1/media/cache/42/play'])('resolves an unresolved tile original before starting its preview (%s)', async url => {
  vi.useFakeTimers()
  await seedPreviewCache('cloud-seed', url, false)
  let finish!: (status: MediaStatus) => void
  vi.mocked(getMediaStatus).mockReturnValue(new Promise(resolve => { finish = resolve }))
  render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="cloud-seed" immersive />)
  const video = screen.getByLabelText('103B 1m dive video')
  expect(video).not.toHaveAttribute('src')
  await act(async () => { finish({ ...ready, playback_url: url, full_quality_url: url, preview_url: '/resolved-preview.mp4' }) })
  expect(video).toHaveAttribute('src', '/resolved-preview.mp4')
})

it('keeps a presented seeded preview when status discovers a higher preview quality', async () => {
  vi.useFakeTimers()
  await seedPreviewCache('stable-seed', '/sdr-360.mp4')
  let resolve!: (status: MediaStatus) => void
  vi.mocked(getMediaStatus).mockReturnValue(new Promise(done => { resolve = done }))
  render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="stable-seed" immersive />)
  const video = screen.getByLabelText('103B 1m dive video') as HTMLVideoElement
  Object.defineProperty(video, 'readyState', { configurable: true, value: 2 })
  fireEvent.loadedData(video)
  await act(async () => { await vi.advanceTimersByTimeAsync(32) })
  await act(async () => { resolve({ ...ready, full_quality_url: '/original.mov', preview_url: '/sdr-720.mp4', cache_entries: [{ id: 1, rendition: 'proxy_360p', playback_url: '/sdr-360.mp4' }, { id: 2, rendition: 'proxy_720p', playback_url: '/sdr-720.mp4' }] }) })
  expect(video).toHaveAttribute('src', '/sdr-360.mp4')
})

it('keeps seeded quality choices and preview recovery when status revalidation fails', async () => {
  vi.useFakeTimers()
  resetMediaPreviews()
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ 'seed-quality': { status: 'ready', playback_url: '/api/v1/media/cache/42/play', poster_url: '/poster.jpg' } }) }))
  vi.mocked(getMediaStatus).mockResolvedValueOnce({ ...ready, playback_url: '/api/v1/media/cache/42/play', full_quality_url: '/original.mov', preview_url: '/preview.mp4' })
  const resolved = getPreviewForPlayback('seed-quality')
  await act(async () => { await vi.advanceTimersByTimeAsync(50); await resolved })
  vi.mocked(getMediaStatus).mockRejectedValue(new Error('status offline'))
  render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="seed-quality" immersive />)
  const video = screen.getByLabelText('103B 1m dive video')
  expect(video).toHaveAttribute('src', '/preview.mp4')
  expect(screen.getByRole('button', { name: 'Change video quality' })).toBeInTheDocument()
  await act(async () => { await vi.advanceTimersByTimeAsync(INITIAL_STATUS_ATTEMPTS * 2000) })
  chooseQuality('Original')
  expect(video).toHaveAttribute('src', '/original.mov')
  fireEvent.error(video)
  fireEvent.click(screen.getByRole('button', { name: 'Play a lower-quality preview' }))
  expect(video).toHaveAttribute('src', '/preview.mp4')
})

it('starts locally and offers Preview, Light, HQ and Original as explicit choices', async () => {
  const derivativeReady = {
    ...missing,
    status: 'ready',
    playback_url: '/api/v1/media/revisions/9/play',
    preview_url: '/local.mp4',
    cache_entries: [{ id: 7, rendition: 'proxy_720p', playback_url: '/local.mp4' }],
    full_quality_url: '/api/v1/media/revisions/9/play',
    poster_url: '/api/v1/media/revisions/4/play',
    derivatives: {
      source_revision_id: 1,
      transform_version: 'ffmpeg-h264-web-v1',
      start: 'light',
      recommended: 'hq',
      hq: { state: 'ready', playback_url: '/api/v1/media/revisions/2/play', revision_id: 2, aliased_to: null },
      light: { state: 'ready', playback_url: '/api/v1/media/revisions/3/play', revision_id: 3, aliased_to: null },
      poster: { state: 'ready', playback_url: '/api/v1/media/revisions/4/play', revision_id: 4, aliased_to: null },
    },
  }
  vi.mocked(getMediaStatus).mockResolvedValue(derivativeReady)
  render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="uuid" />)
  const video = await screen.findByLabelText('103B 1m dive video') as HTMLVideoElement
  await waitFor(() => expect(video).toHaveAttribute('src', '/local.mp4'))
  const toggle = screen.getByRole('button', { name: 'Change video quality' })
  expect(toggle).toHaveTextContent('Preview')
  fireEvent.click(toggle)
  expect(screen.getAllByRole('menuitemradio').map(item => item.textContent)).toEqual(['Preview', 'Light', 'HQ', 'Original'])
  expect(screen.getByRole('menuitemradio', { name: 'Preview' })).toHaveAttribute('aria-checked', 'true')
  fireEvent.click(screen.getByRole('menuitemradio', { name: 'Light' }))
  await waitFor(() => expect(video).toHaveAttribute('src', '/api/v1/media/revisions/3/play'))
  expect(toggle).toHaveTextContent('Light')
  chooseQuality('HQ')
  await waitFor(() => expect(video).toHaveAttribute('src', '/api/v1/media/revisions/2/play'))
  expect(toggle).toHaveTextContent('HQ')
  chooseQuality('Original')
  await waitFor(() => expect(video).toHaveAttribute('src', '/api/v1/media/revisions/9/play'))
  expect(toggle).toHaveTextContent('Original')
  chooseQuality('Preview')
  await waitFor(() => expect(video).toHaveAttribute('src', '/local.mp4'))
  // Quality switches never create preparation jobs.
  expect(requestMedia).not.toHaveBeenCalled()
})

it('a failed HQ derivative falls back to the durable light preview', async () => {
  const derivativeReady = {
    ...missing,
    status: 'ready',
    playback_url: '/api/v1/media/revisions/9/play',
    preview_url: '/api/v1/media/revisions/3/play',
    full_quality_url: '/api/v1/media/revisions/9/play',
    poster_url: '/api/v1/media/revisions/4/play',
    derivatives: {
      source_revision_id: 1,
      transform_version: 'ffmpeg-h264-web-v1',
      start: 'light',
      recommended: 'hq',
      hq: { state: 'ready', playback_url: '/api/v1/media/revisions/2/play', revision_id: 2, aliased_to: null },
      light: { state: 'ready', playback_url: '/api/v1/media/revisions/3/play', revision_id: 3, aliased_to: null },
      poster: { state: 'ready', playback_url: '/api/v1/media/revisions/4/play', revision_id: 4, aliased_to: null },
    },
  }
  vi.mocked(getMediaStatus).mockResolvedValue(derivativeReady)
  render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="uuid" />)
  const video = await screen.findByLabelText('103B 1m dive video') as HTMLVideoElement
  await waitFor(() => expect(video).toHaveAttribute('src', '/api/v1/media/revisions/3/play'))
  chooseQuality('HQ')
  await waitFor(() => expect(video).toHaveAttribute('src', '/api/v1/media/revisions/2/play'))
  // The HQ bytes fail to decode: the player offers the durable light
  // preview (no re-request, no jump to the camera original).
  fireEvent.error(video)
  fireEvent.click(await screen.findByRole('button', { name: 'Play a lower-quality preview' }))
  await waitFor(() => expect(video).toHaveAttribute('src', '/api/v1/media/revisions/3/play'))
  expect(requestMedia).not.toHaveBeenCalled()
})

it('derivative posters ride the authenticated revision route with an honest fallback', async () => {
  const derivativeReady = {
    ...missing,
    status: 'ready',
    playback_url: '/api/v1/media/revisions/9/play',
    preview_url: '/api/v1/media/revisions/3/play',
    full_quality_url: '/api/v1/media/revisions/9/play',
    poster_url: '/api/v1/media/revisions/4/play',
    derivatives: {
      source_revision_id: 1,
      transform_version: 'ffmpeg-h264-web-v1',
      start: 'light',
      recommended: 'hq',
      hq: { state: 'ready', playback_url: '/api/v1/media/revisions/2/play', revision_id: 2, aliased_to: null },
      light: { state: 'ready', playback_url: '/api/v1/media/revisions/3/play', revision_id: 3, aliased_to: null },
      poster: { state: 'ready', playback_url: '/api/v1/media/revisions/4/play', revision_id: 4, aliased_to: null },
    },
  }
  vi.mocked(getMediaStatus).mockResolvedValue(derivativeReady)
  const playSpy = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined)
  try {
    render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="uuid" immersive />)
    const video = await screen.findByLabelText('103B 1m dive video') as HTMLVideoElement
    // The poster is the authenticated revision route (cookies apply), not
    // a signed URL: the <video> poster and the cover <img> share it.
    await waitFor(() => expect(video).toHaveAttribute('poster', '/api/v1/media/revisions/4/play'))
    const img = document.querySelector('[data-testid="clip-cover"] img')
    expect(img).toHaveAttribute('src', '/api/v1/media/revisions/4/play')
    // A poster that fails to load degrades to an honest placeholder.
    fireEvent.error(img as Element)
    expect(document.querySelector('[data-testid="clip-cover"] .clip-cover-empty')).not.toBeNull()
  } finally {
    playSpy.mockRestore()
  }
})

it('keeps a presented local seed when durable Light becomes available', async () => {
  vi.useFakeTimers()
  await seedPreviewCache('legacy-durable', '/sdr-360.mp4')
  let resolve!: (status: MediaStatus) => void
  vi.mocked(getMediaStatus).mockReturnValue(new Promise(done => { resolve = done }))
  render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="legacy-durable" />)
  const video = screen.getByLabelText('103B 1m dive video') as HTMLVideoElement
  expect(video).toHaveAttribute('src', '/sdr-360.mp4')
  Object.defineProperty(video, 'readyState', { configurable: true, value: 2 })
  fireEvent.loadedData(video)
  await act(async () => { await vi.advanceTimersByTimeAsync(32) })
  const durable = {
    ...ready,
    video_uuid: 'legacy-durable',
    playback_url: '/sdr-360.mp4',
    preview_url: '/sdr-360.mp4',
    full_quality_url: '/original.mov',
    cache_entries: [{ id: 1, rendition: 'proxy_360p', playback_url: '/sdr-360.mp4' }],
    derivatives: {
      source_revision_id: 1,
      transform_version: 'ffmpeg-h264-web-v1',
      start: 'light',
      recommended: 'hq',
      hq: { state: 'ready', playback_url: '/api/v1/media/revisions/2/play', revision_id: 2, aliased_to: null },
      light: { state: 'ready', playback_url: '/api/v1/media/revisions/3/play', revision_id: 3, aliased_to: null },
      poster: { state: 'missing', playback_url: null, revision_id: null, aliased_to: null },
    },
  }
  await act(async () => { resolve(durable) })
  expect(video).toHaveAttribute('src', '/sdr-360.mp4')
})

it('keeps an explicit HQ choice and never auto-upgrades light to HQ', async () => {
  const durable = {
    ...missing,
    video_uuid: 'explicit-hq',
    status: 'ready',
    playback_url: '/api/v1/media/revisions/9/play',
    preview_url: '/api/v1/media/revisions/3/play',
    full_quality_url: '/api/v1/media/revisions/9/play',
    poster_url: null,
    derivatives: {
      source_revision_id: 1,
      transform_version: 'ffmpeg-h264-web-v1',
      start: 'light',
      recommended: 'hq',
      hq: { state: 'ready', playback_url: '/api/v1/media/revisions/2/play', revision_id: 2, aliased_to: null },
      light: { state: 'ready', playback_url: '/api/v1/media/revisions/3/play', revision_id: 3, aliased_to: null },
      poster: { state: 'missing', playback_url: null, revision_id: null, aliased_to: null },
    },
  }
  vi.mocked(getMediaStatus).mockResolvedValue(durable)
  const { rerender } = render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="explicit-hq" />)
  const video = await screen.findByLabelText('103B 1m dive video') as HTMLVideoElement
  await waitFor(() => expect(video).toHaveAttribute('src', '/api/v1/media/revisions/3/play'))
  await presentFirstFrame(video)
  vi.mocked(getMediaStatus).mockResolvedValue({ ...durable })
  rerender(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="explicit-hq" immersive />)
  const immersiveVideo = await screen.findByLabelText('103B 1m dive video') as HTMLVideoElement
  await waitFor(() => expect(immersiveVideo).toHaveAttribute('src', '/api/v1/media/revisions/3/play'))
  chooseQuality('HQ')
  await waitFor(() => expect(immersiveVideo).toHaveAttribute('src', '/api/v1/media/revisions/2/play'))
  await presentFirstFrame(immersiveVideo)
  vi.mocked(getMediaStatus).mockResolvedValue({ ...durable })
  rerender(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="explicit-hq" />)
  const back = await screen.findByLabelText('103B 1m dive video') as HTMLVideoElement
  await waitFor(() => expect(back).toHaveAttribute('src', '/api/v1/media/revisions/2/play'))
  expect(requestMedia).not.toHaveBeenCalled()
})

it('keeps HQ decode fallback on durable light across revalidation', async () => {
  const durable = {
    ...missing,
    video_uuid: 'hq-fallback',
    status: 'ready',
    playback_url: '/api/v1/media/revisions/9/play',
    preview_url: '/api/v1/media/revisions/3/play',
    full_quality_url: '/api/v1/media/revisions/9/play',
    poster_url: null,
    derivatives: {
      source_revision_id: 1,
      transform_version: 'ffmpeg-h264-web-v1',
      start: 'light',
      recommended: 'hq',
      hq: { state: 'ready', playback_url: '/api/v1/media/revisions/2/play', revision_id: 2, aliased_to: null },
      light: { state: 'ready', playback_url: '/api/v1/media/revisions/3/play', revision_id: 3, aliased_to: null },
      poster: { state: 'missing', playback_url: null, revision_id: null, aliased_to: null },
    },
  }
  vi.mocked(getMediaStatus).mockResolvedValue(durable)
  const { rerender } = render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="hq-fallback" />)
  const video = await screen.findByLabelText('103B 1m dive video') as HTMLVideoElement
  await waitFor(() => expect(video).toHaveAttribute('src', '/api/v1/media/revisions/3/play'))
  chooseQuality('HQ')
  await waitFor(() => expect(video).toHaveAttribute('src', '/api/v1/media/revisions/2/play'))
  fireEvent.error(video)
  fireEvent.click(await screen.findByRole('button', { name: 'Play a lower-quality preview' }))
  await waitFor(() => expect(video).toHaveAttribute('src', '/api/v1/media/revisions/3/play'))
  await presentFirstFrame(video)
  vi.mocked(getMediaStatus).mockResolvedValue({ ...durable })
  rerender(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="hq-fallback" immersive />)
  const again = await screen.findByLabelText('103B 1m dive video') as HTMLVideoElement
  await waitFor(() => expect(again).toHaveAttribute('src', '/api/v1/media/revisions/3/play'))
  expect(requestMedia).not.toHaveBeenCalled()
})

it('hands a presented legacy seed to durable light with zero original/cache backend data', async () => {
  vi.useFakeTimers()
  await seedPreviewCache('zero-cache-durable', '/sdr-360.mp4')
  vi.useRealTimers()
  let resolve!: (status: MediaStatus) => void
  vi.mocked(getMediaStatus).mockReturnValue(new Promise(done => { resolve = done }))
  const { rerender } = render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="zero-cache-durable" />)
  const video = screen.getByLabelText('103B 1m dive video') as HTMLVideoElement
  expect(video).toHaveAttribute('src', '/sdr-360.mp4')
  await presentFirstFrame(video)
  // Actual backend shape after the authoritative-starter fix: no backbone
  // original, zero legacy cache entries, durable light ready.
  const durableZeroCache = {
    ...missing,
    video_uuid: 'zero-cache-durable',
    status: 'ready',
    playback_url: '/api/v1/media/revisions/3/play',
    preview_url: '/api/v1/media/revisions/3/play',
    full_quality_url: null,
    poster_url: null,
    cache_entries: [],
    job: null,
    derivatives: {
      source_revision_id: 1,
      transform_version: 'ffmpeg-h264-web-v1',
      start: 'light',
      recommended: 'hq',
      hq: { state: 'missing', playback_url: null, revision_id: null, aliased_to: null },
      light: { state: 'ready', playback_url: '/api/v1/media/revisions/3/play', revision_id: 3, aliased_to: null },
      poster: { state: 'missing', playback_url: null, revision_id: null, aliased_to: null },
    },
  }
  await act(async () => { resolve(durableZeroCache) })
  await waitFor(() => expect(video).toHaveAttribute('src', '/api/v1/media/revisions/3/play'))
  await presentFirstFrame(video)
  // Repeated status (revalidation) in both call patterns stays on the
  // durable starter: no flip back to the legacy seed, no invented upgrade.
  vi.mocked(getMediaStatus).mockResolvedValue({ ...durableZeroCache })
  rerender(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="zero-cache-durable" immersive />)
  const immersiveVideo = await screen.findByLabelText('103B 1m dive video') as HTMLVideoElement
  await waitFor(() => expect(immersiveVideo).toHaveAttribute('src', '/api/v1/media/revisions/3/play'))
  vi.mocked(getMediaStatus).mockResolvedValue({ ...durableZeroCache })
  rerender(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="zero-cache-durable" />)
  const back = await screen.findByLabelText('103B 1m dive video') as HTMLVideoElement
  await waitFor(() => expect(back).toHaveAttribute('src', '/api/v1/media/revisions/3/play'))
  expect(requestMedia).not.toHaveBeenCalled()
})

it('keeps an advertised local proxy across durable status revalidation', async () => {
  vi.useFakeTimers()
  await seedPreviewCache('mixed-legacy-playback', '/sdr-360.mp4')
  vi.useRealTimers()
  let resolve!: (status: MediaStatus) => void
  vi.mocked(getMediaStatus).mockReturnValue(new Promise(done => { resolve = done }))
  const { rerender } = render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="mixed-legacy-playback" immersive />)
  const video = screen.getByLabelText('103B 1m dive video') as HTMLVideoElement
  expect(video).toHaveAttribute('src', '/sdr-360.mp4')
  await presentFirstFrame(video)
  // Pre-fix backend shape: no backbone original, one legacy cached proxy,
  // and the mixed playback_url is that same proxy while durable light is
  // ready. The player must not preserve the mixed URL — only the actual
  // durable role URL wins.
  const mixedLegacy = {
    ...missing,
    video_uuid: 'mixed-legacy-playback',
    status: 'ready',
    playback_url: '/sdr-360.mp4',
    preview_url: '/api/v1/media/revisions/3/play',
    full_quality_url: null,
    poster_url: null,
    cache_entries: [{ id: 1, rendition: 'proxy_360p', playback_url: '/sdr-360.mp4' }],
    job: null,
    derivatives: {
      source_revision_id: 1,
      transform_version: 'ffmpeg-h264-web-v1',
      start: 'light',
      recommended: 'hq',
      hq: { state: 'missing', playback_url: null, revision_id: null, aliased_to: null },
      light: { state: 'ready', playback_url: '/api/v1/media/revisions/3/play', revision_id: 3, aliased_to: null },
      poster: { state: 'missing', playback_url: null, revision_id: null, aliased_to: null },
    },
  }
  await act(async () => { resolve(mixedLegacy) })
  await waitFor(() => expect(video).toHaveAttribute('src', '/sdr-360.mp4'))
  await presentFirstFrame(video)
  vi.mocked(getMediaStatus).mockResolvedValue({ ...mixedLegacy })
  rerender(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="mixed-legacy-playback" />)
  const back = await screen.findByLabelText('103B 1m dive video') as HTMLVideoElement
  await waitFor(() => expect(back).toHaveAttribute('src', '/sdr-360.mp4'))
  expect(requestMedia).not.toHaveBeenCalled()
})

it('leaves a genuine legacy-only presented preview unchanged', async () => {
  vi.useFakeTimers()
  await seedPreviewCache('genuine-legacy', '/sdr-360.mp4')
  vi.useRealTimers()
  let resolve!: (status: MediaStatus) => void
  vi.mocked(getMediaStatus).mockReturnValue(new Promise(done => { resolve = done }))
  render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="genuine-legacy" />)
  const video = screen.getByLabelText('103B 1m dive video') as HTMLVideoElement
  expect(video).toHaveAttribute('src', '/sdr-360.mp4')
  await presentFirstFrame(video)
  const legacyOnly = {
    ...missing,
    video_uuid: 'genuine-legacy',
    status: 'ready',
    playback_url: '/sdr-360.mp4',
    preview_url: '/sdr-360.mp4',
    full_quality_url: '/original.mov',
    poster_url: null,
    cache_entries: [{ id: 1, rendition: 'proxy_360p', playback_url: '/sdr-360.mp4' }],
    job: null,
    derivatives: {
      source_revision_id: 1,
      transform_version: 'ffmpeg-h264-web-v1',
      start: 'original',
      recommended: 'original',
      hq: { state: 'missing', playback_url: null, revision_id: null, aliased_to: null },
      light: { state: 'missing', playback_url: null, revision_id: null, aliased_to: null },
      poster: { state: 'missing', playback_url: null, revision_id: null, aliased_to: null },
    },
  }
  await act(async () => { resolve(legacyOnly) })
  await waitFor(() => expect(video).toHaveAttribute('src', '/sdr-360.mp4'))
  expect(requestMedia).not.toHaveBeenCalled()
})

// ---- Playback continuity: quality switches, recovery and late responses ----

const durableChoices = (uuid: string): MediaStatus => ({
  ...missing,
  video_uuid: uuid,
  status: 'ready',
  playback_url: '/api/v1/media/revisions/9/play',
  preview_url: '/api/v1/media/revisions/3/play',
  full_quality_url: '/api/v1/media/revisions/9/play',
  poster_url: null,
  derivatives: {
    source_revision_id: 1,
    transform_version: 'ffmpeg-h264-web-v1',
    start: 'light',
    recommended: 'hq',
    hq: { state: 'ready', playback_url: '/api/v1/media/revisions/2/play', revision_id: 2, aliased_to: null },
    light: { state: 'ready', playback_url: '/api/v1/media/revisions/3/play', revision_id: 3, aliased_to: null },
    poster: { state: 'missing', playback_url: null, revision_id: null, aliased_to: null },
  },
})

/** jsdom media elements have no clock: give one a position and state. */
function setMediaState(video: HTMLVideoElement, state: { time?: number; paused?: boolean; duration?: number; error?: number | null; readyState?: number }) {
  if (state.time !== undefined) {
    let time = state.time
    Object.defineProperty(video, 'currentTime', { configurable: true, get: () => time, set: value => { time = value } })
  }
  if (state.paused !== undefined) Object.defineProperty(video, 'paused', { configurable: true, value: state.paused })
  if (state.duration !== undefined) Object.defineProperty(video, 'duration', { configurable: true, value: state.duration })
  if (state.error !== undefined) Object.defineProperty(video, 'error', { configurable: true, value: state.error === null ? null : { code: state.error } })
  if (state.readyState !== undefined) Object.defineProperty(video, 'readyState', { configurable: true, value: state.readyState })
}

it('switching quality keeps the paused moment instead of restarting the clip', async () => {
  vi.mocked(getMediaStatus).mockResolvedValue(durableChoices('keep-paused'))
  const play = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined)
  const pause = vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {})
  try {
    render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="keep-paused" immersive />)
    const video = await screen.findByLabelText('103B 1m dive video') as HTMLVideoElement
    await waitFor(() => expect(video).toHaveAttribute('src', '/api/v1/media/revisions/3/play'))
    await presentFirstFrame(video)
    fireEvent.play(video)
    setMediaState(video, { time: 6.3, paused: true, readyState: 4 })
    fireEvent.pause(video)
    play.mockClear()
    // Assigning a new src empties the element (HAVE_NOTHING) synchronously.
    setMediaState(video, { readyState: 0 })
    chooseQuality('HQ')
    await waitFor(() => expect(video).toHaveAttribute('src', '/api/v1/media/revisions/2/play'))
    setMediaState(video, { time: 0, duration: 12.5, readyState: 1 })
    fireEvent.loadedMetadata(video)
    expect(video.currentTime).toBe(6.3)
    expect(pause).toHaveBeenCalled()
    expect(play).not.toHaveBeenCalled()
    // A later canplay (seek, buffer) must not resume what the viewer paused.
    fireEvent.canPlay(video)
    expect(play).not.toHaveBeenCalled()
  } finally {
    play.mockRestore()
    pause.mockRestore()
  }
})

it('switching quality while playing resumes at the same moment', async () => {
  vi.mocked(getMediaStatus).mockResolvedValue(durableChoices('keep-playing'))
  const play = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined)
  try {
    render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="keep-playing" />)
    const video = await screen.findByLabelText('103B 1m dive video') as HTMLVideoElement
    await waitFor(() => expect(video).toHaveAttribute('src', '/api/v1/media/revisions/3/play'))
    fireEvent.play(video)
    setMediaState(video, { time: 4.2, paused: false, readyState: 4 })
    chooseQuality('Original')
    await waitFor(() => expect(video).toHaveAttribute('src', '/api/v1/media/revisions/9/play'))
    play.mockClear()
    setMediaState(video, { time: 0, duration: 12.5, readyState: 1 })
    fireEvent.loadedMetadata(video)
    expect(video.currentTime).toBe(4.2)
    expect(play).toHaveBeenCalledTimes(1)
  } finally {
    play.mockRestore()
  }
})

it('reloads an expired or dropped source in place, then admits the failure', async () => {
  vi.mocked(getMediaStatus).mockResolvedValue(durableChoices('grant-expiry'))
  const load = vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => {})
  try {
    render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="grant-expiry" immersive />)
    const video = await screen.findByLabelText('103B 1m dive video') as HTMLVideoElement
    await waitFor(() => expect(video).toHaveAttribute('src', '/api/v1/media/revisions/3/play'))
    await presentFirstFrame(video)
    fireEvent.play(video)
    load.mockClear()
    for (let attempt = 1; attempt <= MAX_AUTO_RECOVERIES; attempt += 1) {
      setMediaState(video, { time: 8, paused: true, error: 2 })
      fireEvent.error(video)
      expect(load).toHaveBeenCalledTimes(attempt)
      expect(screen.queryByRole('alert')).not.toBeInTheDocument()
      // The reloaded source lands on the same moment.
      setMediaState(video, { time: 0, duration: 12.5, error: null, readyState: 1 })
      fireEvent.loadedMetadata(video)
      expect(video.currentTime).toBe(8)
      expect(screen.getByText('Loading video')).toBeInTheDocument()
      // Ready again while paused: no play event, yet the loading layer clears.
      fireEvent.canPlay(video)
      expect(screen.queryByText('Loading video')).not.toBeInTheDocument()
    }
    setMediaState(video, { time: 8, paused: true, error: 2 })
    fireEvent.error(video)
    expect(load).toHaveBeenCalledTimes(MAX_AUTO_RECOVERIES)
    expect(await screen.findByRole('alert')).toHaveTextContent('Video unavailable')
  } finally {
    load.mockRestore()
  }
})

it('a source that never decoded reports unsupported media at once', async () => {
  vi.mocked(getMediaStatus).mockResolvedValue(durableChoices('never-decoded'))
  const load = vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => {})
  try {
    render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="never-decoded" immersive />)
    const video = await screen.findByLabelText('103B 1m dive video') as HTMLVideoElement
    await waitFor(() => expect(video).toHaveAttribute('src', '/api/v1/media/revisions/3/play'))
    load.mockClear()
    setMediaState(video, { error: 4 })
    fireEvent.error(video)
    expect(load).not.toHaveBeenCalled()
    expect(await screen.findByRole('alert')).toBeInTheDocument()
  } finally {
    load.mockRestore()
  }
})

it('manual retry keeps the chosen quality and position', async () => {
  vi.mocked(getMediaStatus).mockResolvedValue(durableChoices('retry-keeps'))
  render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="retry-keeps" />)
  const video = await screen.findByLabelText('103B 1m dive video') as HTMLVideoElement
  await waitFor(() => expect(video).toHaveAttribute('src', '/api/v1/media/revisions/3/play'))
  chooseQuality('HQ')
  await waitFor(() => expect(video).toHaveAttribute('src', '/api/v1/media/revisions/2/play'))
  setMediaState(video, { duration: 12.5, readyState: 1 })
  fireEvent.loadedMetadata(video)
  setMediaState(video, { time: 5, paused: true, error: 3 })
  fireEvent.error(video)
  fireEvent.click(await screen.findByRole('button', { name: 'Try again' }))
  await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
  expect(video).toHaveAttribute('src', '/api/v1/media/revisions/2/play')
  setMediaState(video, { time: 0, duration: 12.5, error: null, readyState: 1 })
  fireEvent.loadedMetadata(video)
  expect(video.currentTime).toBe(5)
})

it('a preparation request that resolves after the viewer moved on is ignored', async () => {
  vi.mocked(getMediaStatus).mockImplementation(async uuid => (uuid === 'clip-a' ? { ...missing, video_uuid: 'clip-a' } : { ...ready, video_uuid: 'clip-b', playback_url: '/clip-b.mp4' }))
  let finish!: (status: MediaStatus) => void
  vi.mocked(requestMedia).mockReturnValue(new Promise(resolve => { finish = resolve }) as ReturnType<typeof requestMedia>)
  const { rerender } = render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="clip-a" />)
  fireEvent.click(await screen.findByRole('button', { name: /Prepare clip/ }))
  rerender(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="clip-b" />)
  const video = await screen.findByLabelText('103B 1m dive video')
  await waitFor(() => expect(video).toHaveAttribute('src', '/clip-b.mp4'))
  await act(async () => { finish({ ...ready, video_uuid: 'clip-a', playback_url: '/clip-a.mp4' }) })
  expect(video).toHaveAttribute('src', '/clip-b.mp4')
})

it('the quality menu closes on Escape without reaching the viewer', async () => {
  vi.mocked(getMediaStatus).mockResolvedValue(durableChoices('menu-escape'))
  const viewerKeys = vi.fn()
  render(<div onKeyDown={event => viewerKeys(event.key)}><DiveVideoPlayer diveCode="103B" height="1m" videoUuid="menu-escape" immersive /></div>)
  const trigger = await screen.findByRole('button', { name: 'Change video quality' })
  fireEvent.click(trigger)
  const menu = screen.getByRole('menu')
  // The viewer defaults to Auto, which names the rendition it is playing.
  expect(screen.getByRole('menuitemradio', { name: 'Auto · Light' })).toHaveFocus()
  fireEvent.keyDown(menu, { key: 'ArrowDown' })
  expect(screen.getByRole('menuitemradio', { name: 'Light' })).toHaveFocus()
  fireEvent.keyDown(menu, { key: 'Escape' })
  expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  expect(trigger).toHaveFocus()
  expect(viewerKeys).not.toHaveBeenCalled()
})

it('a quality switch whose request drops recovers to the moment before the switch', async () => {
  vi.mocked(getMediaStatus).mockResolvedValue(durableChoices('switch-drop'))
  const load = vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => {})
  const pause = vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {})
  try {
    render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="switch-drop" immersive />)
    const video = await screen.findByLabelText('103B 1m dive video') as HTMLVideoElement
    await waitFor(() => expect(video).toHaveAttribute('src', '/api/v1/media/revisions/3/play'))
    await presentFirstFrame(video)
    fireEvent.play(video)
    setMediaState(video, { time: 7.1, paused: true, readyState: 4 })
    fireEvent.pause(video)
    setMediaState(video, { readyState: 0 })
    chooseQuality('HQ')
    await waitFor(() => expect(video).toHaveAttribute('src', '/api/v1/media/revisions/2/play'))
    // The new source's request fails before metadata; the emptied element
    // reads 0 but the viewer was at 7.1.
    setMediaState(video, { time: 0, error: 2 })
    fireEvent.error(video)
    expect(load).toHaveBeenCalled()
    setMediaState(video, { duration: 12.5, error: null, readyState: 1 })
    fireEvent.loadedMetadata(video)
    expect(video.currentTime).toBe(7.1)
    expect(pause).toHaveBeenCalled()
  } finally {
    load.mockRestore()
    pause.mockRestore()
  }
})

// ---- Auto quality: role start, remembered choice, background HQ, stalls ----

/** Library tile says the durable Light is ready (batch `start_role`). */
async function seedLightHint(uuid: string, version = 'ffmpeg-h264-web-v2') {
  resetMediaPreviews()
  vi.stubGlobal('fetch', vi.fn().mockImplementation(async () => ({
    ok: true,
    json: async () => ({ [uuid]: { status: 'ready', poster_url: '/seeded.jpg', playback_url: '/proxy.mp4', start_role: 'light', start_light_version: version } }),
  })))
  await act(async () => { await getPreview(uuid) })
}

it('starts on the durable Light by role, without waiting for status, and keeps it', async () => {
  await seedLightHint('role-start')
  let finish!: (status: MediaStatus) => void
  vi.mocked(getMediaStatus).mockReturnValue(new Promise(done => { finish = done }))
  render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="role-start" immersive />)
  const video = screen.getByLabelText('103B 1m dive video') as HTMLVideoElement
  expect(video).toHaveAttribute('src', '/api/v1/media/role-start/play/light')
  await presentFirstFrame(video) // the status lookup waits for the first frame
  await waitFor(() => expect(getMediaStatus).toHaveBeenCalled())
  await act(async () => { finish({ ...durableChoices('role-start'), preview_url: '/proxy.mp4' }) })
  // Same bytes as the status Light URL: never reloaded under another URL.
  expect(video).toHaveAttribute('src', '/api/v1/media/role-start/play/light')
  fireEvent.click(screen.getByRole('button', { name: 'Change video quality' }))
  expect(screen.getByRole('menuitemradio', { name: 'Auto · Light' })).toHaveAttribute('aria-checked', 'true')
})

it('a stale Light hint falls back to the status source without an error card', async () => {
  await seedLightHint('stale-hint')
  vi.mocked(getMediaStatus).mockResolvedValue({ ...ready, video_uuid: 'stale-hint', playback_url: '/proxy.mp4', preview_url: '/proxy.mp4' })
  render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="stale-hint" immersive />)
  const video = screen.getByLabelText('103B 1m dive video') as HTMLVideoElement
  expect(video).toHaveAttribute('src', '/api/v1/media/stale-hint/play/light')
  setMediaState(video, { error: 4 })
  fireEvent.error(video)
  setMediaState(video, { error: null })
  await waitFor(() => expect(video).toHaveAttribute('src', '/proxy.mp4'))
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

it('a weak network starts on the small proxy instead of Light', async () => {
  recordThroughput(1.5)
  await seedLightHint('weak-net')
  vi.mocked(getMediaStatus).mockResolvedValue({ ...durableChoices('weak-net'), preview_url: '/proxy.mp4' })
  render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="weak-net" immersive />)
  const video = screen.getByLabelText('103B 1m dive video')
  expect(video).not.toHaveAttribute('src', '/api/v1/media/weak-net/play/light')
  await waitFor(() => expect(video).toHaveAttribute('src', '/proxy.mp4'))
})

it('a manual quality sticks to the next dive; Auto hands control back', async () => {
  vi.mocked(getMediaStatus).mockImplementation(async uuid => durableChoices(uuid))
  const { rerender } = render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="pick-a" immersive />)
  const first = await screen.findByLabelText('103B 1m dive video')
  await waitFor(() => expect(first).toHaveAttribute('src', '/api/v1/media/revisions/3/play'))
  chooseQuality('HQ')
  await waitFor(() => expect(first).toHaveAttribute('src', '/api/v1/media/revisions/2/play'))
  rerender(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="pick-b" immersive />)
  const second = await screen.findByLabelText('103B 1m dive video')
  await waitFor(() => expect(second).toHaveAttribute('src', '/api/v1/media/revisions/2/play'))
  chooseQuality('Auto · HQ')
  expect(getQualityPreference()).toBe('auto')
})

/** The off-screen HQ element the player prepared, if any. */
function backgroundVideo(create: { mock: { results: Array<{ value: unknown }> } }, src: string) {
  return create.mock.results.map(result => result.value).find(
    (element): element is HTMLVideoElement => element instanceof HTMLVideoElement && element.getAttribute('src') === src,
  )
}

it('prepares HQ off-screen with headroom and swaps it in on pause at the same frame', async () => {
  recordThroughput(40)
  vi.mocked(getMediaStatus).mockResolvedValue(durableChoices('bg-pause'))
  const create = vi.spyOn(document, 'createElement')
  const pause = vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {})
  const play = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined)
  try {
    render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="bg-pause" immersive />)
    const active = await screen.findByLabelText('103B 1m dive video') as HTMLVideoElement
    await waitFor(() => expect(active).toHaveAttribute('src', '/api/v1/media/revisions/3/play'))
    await presentFirstFrame(active)
    const next = await waitFor(() => {
      const element = backgroundVideo(create, '/api/v1/media/revisions/2/play')
      expect(element).toBeDefined()
      return element!
    })
    expect(next.isConnected).toBe(false)
    expect(next.muted).toBe(true)
    // The viewer is still playing Light: nothing swaps mid-motion.
    setMediaState(active, { time: 4.5, paused: false, readyState: 4 })
    setMediaState(next, { time: 0, readyState: 4, duration: 12.5 })
    fireEvent(next, new Event('canplaythrough'))
    expect(active.isConnected).toBe(true)
    // Pausing hands the frame to the buffered HQ element.
    setMediaState(active, { paused: true })
    fireEvent.pause(active)
    // The prepared element seeks to the paused frame first.
    expect(next.currentTime).toBe(4.5)
    expect(next.isConnected).toBe(false)
    fireEvent(next, new Event('seeked'))
    await waitFor(() => expect(next.isConnected).toBe(true))
    expect(active.isConnected).toBe(false)
    expect(next.currentTime).toBe(4.5)
    expect(next.getAttribute('aria-label')).toBe('103B 1m dive video')
    expect(active.hasAttribute('src')).toBe(false) // the Light decoder is released
    expect(document.querySelector('[data-testid="clip-cover"]')).toBeNull()
    // The viewer paused: the adopted HQ element must stay paused.
    fireEvent.canPlay(next)
    expect(play.mock.instances).not.toContain(next)
    fireEvent.click(screen.getByRole('button', { name: 'Change video quality' }))
    expect(screen.getByRole('menuitemradio', { name: 'Auto · HQ' })).toHaveAttribute('aria-checked', 'true')
  } finally {
    create.mockRestore()
    pause.mockRestore()
    play.mockRestore()
  }
})

it('swaps prepared HQ in on the loop restart, or keeps Light when play is refused', async () => {
  recordThroughput(40)
  vi.mocked(getMediaStatus).mockResolvedValue(durableChoices('bg-loop'))
  const create = vi.spyOn(document, 'createElement')
  const play = vi.spyOn(HTMLMediaElement.prototype, 'play').mockRejectedValue(new DOMException('blocked', 'NotAllowedError'))
  try {
    render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="bg-loop" immersive />)
    const active = await screen.findByLabelText('103B 1m dive video') as HTMLVideoElement
    await waitFor(() => expect(active).toHaveAttribute('src', '/api/v1/media/revisions/3/play'))
    await presentFirstFrame(active)
    const next = await waitFor(() => backgroundVideo(create, '/api/v1/media/revisions/2/play')!)
    setMediaState(active, { time: 12.4, paused: false, readyState: 4 })
    setMediaState(next, { time: 0, readyState: 4, duration: 12.5 })
    fireEvent(next, new Event('canplaythrough'))
    expect(active.isConnected).toBe(true) // playing: wait for a boundary
    fireEvent.timeUpdate(active)
    setMediaState(active, { time: 0.05 })
    fireEvent.timeUpdate(active)
    await act(async () => {})
    // Autoplay refused for the new element: Light keeps playing, HQ released.
    expect(active.isConnected).toBe(true)
    expect(next.hasAttribute('src')).toBe(false)
  } finally {
    create.mockRestore()
    play.mockRestore()
  }
})

it('no background HQ without measured headroom', async () => {
  vi.mocked(getMediaStatus).mockResolvedValue(durableChoices('bg-none'))
  const create = vi.spyOn(document, 'createElement')
  try {
    render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="bg-none" immersive />)
    const active = await screen.findByLabelText('103B 1m dive video') as HTMLVideoElement
    await waitFor(() => expect(active).toHaveAttribute('src', '/api/v1/media/revisions/3/play'))
    await presentFirstFrame(active)
    await act(async () => {})
    expect(backgroundVideo(create, '/api/v1/media/revisions/2/play')).toBeUndefined()
  } finally {
    create.mockRestore()
  }
})

it('repeated stalls step Auto down one rendition at the same moment', async () => {
  // A capped (v2) Light: a safe blind start, so the clip begins on Light.
  vi.mocked(getMediaStatus).mockResolvedValue({ ...durableChoices('stalls'), preview_url: '/proxy.mp4', cache_entries: [{ id: 1, rendition: 'proxy_720p', playback_url: '/proxy.mp4' }], derivatives: { ...durableChoices('stalls').derivatives!, transform_version: 'ffmpeg-h264-web-v2' } })
  render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="stalls" immersive />)
  const video = await screen.findByLabelText('103B 1m dive video') as HTMLVideoElement
  await waitFor(() => expect(video).toHaveAttribute('src', '/api/v1/media/revisions/3/play'))
  await presentFirstFrame(video)
  // readyState 0: assigning the lower source empties the element (as in browsers).
  setMediaState(video, { time: 3, paused: false, readyState: 0 })
  for (let stall = 0; stall < 2; stall += 1) {
    fireEvent.waiting(video)
    fireEvent.playing(video)
  }
  await waitFor(() => expect(video).toHaveAttribute('src', '/proxy.mp4'))
  setMediaState(video, { time: 0, duration: 12.5, readyState: 1 })
  fireEvent.loadedMetadata(video)
  expect(video.currentTime).toBe(3)
  expect(throughputEstimate()).not.toBeNull()
})

it('swaps prepared HQ in from its first frame when the loop restarts', async () => {
  recordThroughput(40)
  vi.mocked(getMediaStatus).mockResolvedValue(durableChoices('bg-loop-ok'))
  const create = vi.spyOn(document, 'createElement')
  const play = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined)
  try {
    render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="bg-loop-ok" immersive />)
    const active = await screen.findByLabelText('103B 1m dive video') as HTMLVideoElement
    await waitFor(() => expect(active).toHaveAttribute('src', '/api/v1/media/revisions/3/play'))
    await presentFirstFrame(active)
    const next = await waitFor(() => backgroundVideo(create, '/api/v1/media/revisions/2/play')!)
    setMediaState(active, { time: 12.4, paused: false, readyState: 4 })
    setMediaState(next, { time: 0, readyState: 4, duration: 12.5 })
    fireEvent(next, new Event('canplaythrough'))
    fireEvent.timeUpdate(active)
    setMediaState(active, { time: 0.05 })
    fireEvent.timeUpdate(active)
    await waitFor(() => expect(next.isConnected).toBe(true))
    expect(play.mock.instances).toContain(next)
    expect(active.isConnected).toBe(false)
  } finally {
    create.mockRestore()
    play.mockRestore()
  }
})

it('climbs from the proxy to Light when the network sustains Light but not HQ', async () => {
  recordThroughput(1)
  vi.mocked(getMediaStatus).mockResolvedValue({ ...durableChoices('climb'), preview_url: '/proxy.mp4', cache_entries: [{ id: 1, rendition: 'proxy_720p', playback_url: '/proxy.mp4' }] })
  const create = vi.spyOn(document, 'createElement')
  try {
    const { rerender } = render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="climb" immersive />)
    const active = await screen.findByLabelText('103B 1m dive video') as HTMLVideoElement
    await waitFor(() => expect(active).toHaveAttribute('src', '/proxy.mp4'))
    await presentFirstFrame(active)
    recordThroughput(20)
    recordThroughput(20) // ~13 Mbps: Light yes (≥4), HQ no (<19.4)
    rerender(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="climb" immersive />)
    await waitFor(() => expect(backgroundVideo(create, '/api/v1/media/revisions/3/play')).toBeDefined())
    expect(backgroundVideo(create, '/api/v1/media/revisions/2/play')).toBeUndefined()
  } finally {
    create.mockRestore()
  }
})

it('from the proxy, Auto climbs to Light first even with HQ headroom', async () => {
  recordThroughput(1)
  vi.mocked(getMediaStatus).mockResolvedValue({ ...durableChoices('one-step'), preview_url: '/proxy.mp4', cache_entries: [{ id: 1, rendition: 'proxy_720p', playback_url: '/proxy.mp4' }] })
  const create = vi.spyOn(document, 'createElement')
  try {
    const { rerender } = render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="one-step" immersive />)
    const active = await screen.findByLabelText('103B 1m dive video') as HTMLVideoElement
    await waitFor(() => expect(active).toHaveAttribute('src', '/proxy.mp4'))
    await presentFirstFrame(active)
    for (let sample = 0; sample < 6; sample += 1) recordThroughput(80)
    rerender(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="one-step" immersive />)
    await waitFor(() => expect(backgroundVideo(create, '/api/v1/media/revisions/3/play')).toBeDefined())
    expect(backgroundVideo(create, '/api/v1/media/revisions/2/play')).toBeUndefined()
  } finally {
    create.mockRestore()
  }
})

it('a legacy 360p proxy is measured at its own bitrate, not the 720p one', async () => {
  vi.mocked(getMediaStatus).mockResolvedValue({ ...ready, video_uuid: 'p360', playback_url: '/p360.mp4', preview_url: '/p360.mp4', cache_entries: [{ id: 1, rendition: 'proxy_360p', playback_url: '/p360.mp4' }] })
  const now = vi.spyOn(performance, 'now').mockReturnValue(0)
  try {
    render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="p360" immersive />)
    const video = await screen.findByLabelText('103B 1m dive video') as HTMLVideoElement
    await waitFor(() => expect(video).toHaveAttribute('src', '/p360.mp4'))
    await presentFirstFrame(video)
    setMediaState(video, { duration: 10 })
    Object.defineProperty(video, 'buffered', { configurable: true, value: { length: 1, end: () => 10, start: () => 0 } })
    now.mockReturnValue(1000) // 10 s of media buffered in 1 s
    fireEvent(video, new Event('progress'))
    expect(throughputEstimate()).toBeCloseTo(10 * 0.25)
  } finally {
    now.mockRestore()
  }
})

it('an uncapped v1 Light never starts blind: the proxy starts until the network is known', async () => {
  await seedLightHint('v1-blind', 'ffmpeg-h264-web-v1')
  const v1 = { ...durableChoices('v1-blind'), preview_url: '/proxy.mp4', derivatives: { ...durableChoices('v1-blind').derivatives!, transform_version: 'ffmpeg-h264-web-v1' } }
  vi.mocked(getMediaStatus).mockResolvedValue(v1)
  render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="v1-blind" immersive />)
  const video = screen.getByLabelText('103B 1m dive video')
  expect(video).not.toHaveAttribute('src', '/api/v1/media/v1-blind/play/light')
  await waitFor(() => expect(video).toHaveAttribute('src', '/proxy.mp4'))
})

it('a measured network with headroom for the v1 Light starts on it', async () => {
  recordThroughput(12) // ≥ 1.5 × 6.4 Mbps
  await seedLightHint('v1-fast', 'ffmpeg-h264-web-v1')
  vi.mocked(getMediaStatus).mockReturnValue(new Promise(() => {}))
  render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="v1-fast" immersive />)
  expect(screen.getByLabelText('103B 1m dive video')).toHaveAttribute('src', '/api/v1/media/v1-fast/play/light')
})

it('a 3–6 Mbps network starts the v1 Light clip on the proxy (no stall-prone start)', async () => {
  recordThroughput(5)
  await seedLightHint('v1-mid', 'ffmpeg-h264-web-v1')
  vi.mocked(getMediaStatus).mockReturnValue(new Promise(() => {}))
  render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="v1-mid" immersive />)
  expect(screen.getByLabelText('103B 1m dive video')).not.toHaveAttribute('src', '/api/v1/media/v1-mid/play/light')
})

it('a speed sample from elsewhere (neighbor or proxy download) re-evaluates Auto without a re-render', async () => {
  recordThroughput(1)
  vi.mocked(getMediaStatus).mockResolvedValue({ ...durableChoices('notify'), preview_url: '/proxy.mp4', cache_entries: [{ id: 1, rendition: 'proxy_720p', playback_url: '/proxy.mp4' }] })
  const create = vi.spyOn(document, 'createElement')
  try {
    render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="notify" immersive />)
    const active = await screen.findByLabelText('103B 1m dive video') as HTMLVideoElement
    await waitFor(() => expect(active).toHaveAttribute('src', '/proxy.mp4'))
    await presentFirstFrame(active)
    expect(backgroundVideo(create, '/api/v1/media/revisions/3/play')).toBeUndefined()
    // No rerender: only the shared estimate changes, as a neighbor's download would.
    act(() => { for (let sample = 0; sample < 4; sample += 1) recordThroughput(20) })
    await waitFor(() => expect(backgroundVideo(create, '/api/v1/media/revisions/3/play')).toBeDefined())
  } finally {
    create.mockRestore()
  }
})

it('a clip started by role asks for its status only after the first frame', async () => {
  await seedLightHint('defer-status')
  vi.mocked(getMediaStatus).mockResolvedValue({ ...durableChoices('defer-status'), preview_url: '/proxy.mp4' })
  render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="defer-status" immersive />)
  const video = screen.getByLabelText('103B 1m dive video') as HTMLVideoElement
  expect(video).toHaveAttribute('src', '/api/v1/media/defer-status/play/light')
  await act(async () => {})
  expect(getMediaStatus).not.toHaveBeenCalled()
  await presentFirstFrame(video)
  await waitFor(() => expect(getMediaStatus).toHaveBeenCalledWith('defer-status'))
  expect(video).toHaveAttribute('src', '/api/v1/media/defer-status/play/light')
})

it('a role-started clip that never presents still gets its status after a bounded wait', async () => {
  await seedLightHint('defer-timeout')
  vi.useFakeTimers()
  vi.mocked(getMediaStatus).mockResolvedValue({ ...durableChoices('defer-timeout'), preview_url: '/proxy.mp4' })
  render(<DiveVideoPlayer diveCode="103B" height="1m" videoUuid="defer-timeout" immersive />)
  await act(async () => { await vi.advanceTimersByTimeAsync(STATUS_DEFER_MS - 100) })
  expect(getMediaStatus).not.toHaveBeenCalled()
  await act(async () => { await vi.advanceTimersByTimeAsync(200) })
  expect(getMediaStatus).toHaveBeenCalledWith('defer-timeout')
})
