import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import EvaluationPlayer from './EvaluationPlayer'
import { getEvaluationMediaStatus, prepareEvaluationMedia } from '../../services/evaluationApi'
vi.mock('../../services/evaluationApi', async importOriginal => ({
  ...await importOriginal<typeof import('../../services/evaluationApi')>(),
  getEvaluationMediaStatus: vi.fn(), prepareEvaluationMedia: vi.fn(),
}))
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(prepareEvaluationMedia).mockRejectedValue(new Error('Unavailable'))
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue()
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {})
})
it('keeps initial playback and quality switching on the automatic transport', async () => {
  vi.mocked(getEvaluationMediaStatus).mockResolvedValue({ request_id: 7, dive_id: 7, video_uuid: 'clip', status: 'ready', rendition: 'proxy_720p', poster_url: null, playback_url: '/api/v1/evaluations/automatic/7/media/play', available_renditions: ['original', 'proxy_720p'] })
  const { container } = render(<EvaluationPlayer requestId={7} automatic />)
  await waitFor(() => expect(container.querySelector('video')?.getAttribute('src')).toBe('/api/v1/evaluations/automatic/7/media/play?rendition=proxy_720p'))
  expect(getEvaluationMediaStatus).toHaveBeenCalledWith(7, true)
  fireEvent.click(screen.getByRole('button', { name: /quality/i }))
  expect(container.querySelector('video')?.getAttribute('src')).toBe('/api/v1/evaluations/automatic/7/media/play?rendition=original')
  expect(prepareEvaluationMedia).not.toHaveBeenCalled()
})
it('warms the current automatic proxy through the automatic preparation endpoint', async () => {
  const status = { request_id: 7, dive_id: 7, video_uuid: 'clip', status: 'ready' as const, rendition: 'proxy_360p', poster_url: null, playback_url: '/api/v1/evaluations/automatic/7/media/play', available_renditions: ['proxy_360p'] }
  vi.mocked(getEvaluationMediaStatus).mockResolvedValue(status)
  vi.mocked(prepareEvaluationMedia).mockResolvedValue({ ...status, created_jobs: [], reused_jobs: [] })
  render(<EvaluationPlayer requestId={7} automatic />)
  await waitFor(() => expect(prepareEvaluationMedia).toHaveBeenCalledWith(7, true))
})
it('adds prepared quality choices without replacing the playing video', async () => {
  const proxy = { request_id: 7, dive_id: 7, video_uuid: 'clip', status: 'ready' as const, rendition: 'proxy_360p', poster_url: null, playback_url: '/api/v1/evaluations/automatic/7/media/play', available_renditions: ['proxy_360p'] }
  vi.mocked(getEvaluationMediaStatus).mockResolvedValueOnce(proxy).mockResolvedValue({ ...proxy, rendition: 'proxy_720p', available_renditions: ['proxy_720p'] })
  vi.mocked(prepareEvaluationMedia).mockResolvedValue({ ...proxy, created_jobs: [], reused_jobs: [] })
  const { container } = render(<EvaluationPlayer requestId={7} automatic />)
  await waitFor(() => expect(prepareEvaluationMedia).toHaveBeenCalled())
  const video = container.querySelector('video')!
  await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument(), { timeout: 3500 })
  expect(container.querySelector('video')).toBe(video)
  expect(video.getAttribute('src')).toContain('rendition=proxy_360p')
})
it('clears the upgrading hint when the bounded HQ wait expires', async () => {
  const clock = vi.spyOn(Date, 'now').mockReturnValue(0)
  const proxy = { request_id: 7, dive_id: 7, video_uuid: 'clip', status: 'ready' as const, rendition: 'proxy_360p', poster_url: null, playback_url: '/api/v1/evaluations/automatic/7/media/play', available_renditions: ['proxy_360p'] }
  vi.mocked(getEvaluationMediaStatus).mockResolvedValue(proxy)
  vi.mocked(prepareEvaluationMedia).mockResolvedValue({ ...proxy, created_jobs: [], reused_jobs: [] })
  const { container } = render(<EvaluationPlayer requestId={7} automatic />)
  await waitFor(() => expect(screen.getByRole('status')).toBeInTheDocument())
  clock.mockReturnValue(90_001)
  await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument(), { timeout: 3500 })
  expect(container.querySelector('video')?.getAttribute('src')).toContain('rendition=proxy_360p')
})
it('routes replay and play through the judging transition while paused', async () => {
  vi.mocked(getEvaluationMediaStatus).mockResolvedValue({ request_id: 7, dive_id: 7, video_uuid: 'clip', status: 'ready', rendition: 'original', poster_url: null, playback_url: '/play', available_renditions: ['original', 'proxy_720p'] })
  const onReplay = vi.fn()
  render(<EvaluationPlayer requestId={7} paused onReplay={onReplay} />)
  fireEvent.click(await screen.findByRole('button', { name: /replay/i }))
  fireEvent.click(screen.getByRole('button', { name: /^play$/i }))
  expect(onReplay).toHaveBeenCalledTimes(2)
  expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled()
})
it('offers an explicit labelled preview when the original cannot decode', async () => {
  vi.mocked(getEvaluationMediaStatus).mockResolvedValue({ request_id: 7, dive_id: 7, video_uuid: 'clip', status: 'ready', rendition: 'original', poster_url: null, playback_url: '/play', available_renditions: ['original', 'proxy_720p'] })
  const onFailure = vi.fn()
  const { container } = render(<EvaluationPlayer requestId={7} watching onFailure={onFailure} />)
  await waitFor(() => expect(container.querySelector('video')?.getAttribute('src')).toContain('rendition=proxy_720p'))
  fireEvent.loadedData(container.querySelector('video')!)
  fireEvent.click(screen.getByRole('button', { name: /quality/i }))
  fireEvent.error(container.querySelector('video')!)
  expect(screen.getByRole('alert')).toBeInTheDocument()
  expect(onFailure).not.toHaveBeenCalled()
  expect(container.querySelector('video')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Play a lower-quality preview' }))
  expect(container.querySelector('video')?.getAttribute('src')).toContain('rendition=proxy_720p')
  fireEvent.error(container.querySelector('video')!)
  await waitFor(() => expect(onFailure).toHaveBeenCalledOnce())
})
it('promotes the buffered video and replays without fetching or replacing it', async () => {
  vi.mocked(getEvaluationMediaStatus).mockResolvedValue({ request_id: 7, dive_id: 7, video_uuid: 'clip', status: 'ready', rendition: 'original', poster_url: null, playback_url: '/play', available_renditions: ['original', 'proxy_720p'] })
  const onBuffered = vi.fn()
  const { container, rerender } = render(<EvaluationPlayer requestId={7} preloadOnly paused onBuffered={onBuffered} />)
  await waitFor(() => expect(container.querySelector('video')).not.toBeNull())
  const video = container.querySelector('video')!
  expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled()
  fireEvent.loadedData(video)
  expect(onBuffered).toHaveBeenCalledOnce()
  rerender(<EvaluationPlayer requestId={7} onBuffered={onBuffered} />)
  expect(container.querySelector('video')).toBe(video)
  expect(getEvaluationMediaStatus).toHaveBeenCalledOnce()
  video.currentTime = 5
  rerender(<EvaluationPlayer requestId={7} replayToken={1} onBuffered={onBuffered} />)
  expect(video.currentTime).toBe(0)
  expect(container.querySelector('video')).toBe(video)
  expect(getEvaluationMediaStatus).toHaveBeenCalledOnce()
})
it('does not enqueue media preparation for the upcoming clip', async () => {
  vi.mocked(prepareEvaluationMedia).mockRejectedValue(new Error('Unavailable'))
  vi.mocked(getEvaluationMediaStatus).mockResolvedValue({ request_id: 8, dive_id: 8, video_uuid: 'next', status: 'ready', rendition: 'proxy_360p', poster_url: null, playback_url: '/play', available_renditions: ['proxy_360p'] })
  const { container, rerender } = render(<EvaluationPlayer requestId={8} preloadOnly paused />)
  await waitFor(() => expect(container.querySelector('video')).not.toBeNull())
  expect(prepareEvaluationMedia).not.toHaveBeenCalled()
  rerender(<EvaluationPlayer requestId={8} />)
  await waitFor(() => expect(prepareEvaluationMedia).toHaveBeenCalledWith(8, false))
})

it('uses ready queue metadata immediately without an additional status round trip', async () => {
  const initialMedia = { request_id: 7, dive_id: 7, video_uuid: 'clip', status: 'ready' as const, rendition: 'original', poster_url: '/poster', playback_url: '/play', available_renditions: ['original', 'proxy_720p'] }
  const { container } = render(<EvaluationPlayer requestId={7} initialMedia={initialMedia} />)
  expect(container.querySelector('video')?.getAttribute('src')).toContain('rendition=proxy_720p')
  expect(container.querySelector('video')?.getAttribute('poster')).toBe('/poster')
  expect(getEvaluationMediaStatus).not.toHaveBeenCalled()
  expect(prepareEvaluationMedia).not.toHaveBeenCalled()
})

it('keeps a presented original unchanged when a late preview preparation finishes', async () => {
  const original = { request_id: 7, dive_id: 7, video_uuid: 'clip', status: 'ready' as const, rendition: 'original', poster_url: null, playback_url: '/play', available_renditions: ['original', 'proxy_360p'] }
  let finish!: (value: Awaited<ReturnType<typeof prepareEvaluationMedia>>) => void
  vi.mocked(getEvaluationMediaStatus).mockResolvedValue(original)
  vi.mocked(prepareEvaluationMedia).mockReturnValue(new Promise(resolve => { finish = resolve }))
  const { container } = render(<EvaluationPlayer requestId={7} />)
  await waitFor(() => expect(container.querySelector('video')).not.toBeNull())
  fireEvent.click(screen.getByRole('button', { name: /quality/i }))
  const video = container.querySelector('video')!
  fireEvent.loadedData(video)
  fireEvent.playing(video)
  // Even an ended/paused video can have readyState drop during a later stall.
  // Once a frame has been exposed, background work cannot change its source.
  finish({ ...original, rendition: 'proxy_720p', available_renditions: ['original', 'proxy_720p'], created_jobs: [], reused_jobs: [] })
  await waitFor(() => expect(screen.getByRole('button', { name: /quality/i })).toBeInTheDocument())
  expect(container.querySelector('video')).toBe(video)
  expect(video.getAttribute('src')).toContain('rendition=original')
  fireEvent.click(screen.getByRole('button', { name: /quality/i }))
  expect(container.querySelector('video')?.getAttribute('src')).toContain('rendition=proxy_720p')
})

it('waits for a queued preview instead of playing the catalog-ready cloud original', async () => {
  const original = { request_id: 7, dive_id: 7, video_uuid: 'clip', status: 'ready' as const, rendition: 'original', poster_url: null, playback_url: '/play', available_renditions: ['original'] }
  let prepared = false
  vi.mocked(getEvaluationMediaStatus).mockImplementation(async () => prepared ? { ...original, available_renditions: ['original', 'proxy_720p'] } : original)
  vi.mocked(prepareEvaluationMedia).mockResolvedValue({ ...original, created_jobs: ['proxy_720p'], reused_jobs: [] })
  const onFailure = vi.fn()
  const { container } = render(<EvaluationPlayer requestId={7} watching onFailure={onFailure} />)
  await waitFor(() => expect(prepareEvaluationMedia).toHaveBeenCalledOnce())
  expect(container.querySelector('video')).toBeNull()
  expect(onFailure).not.toHaveBeenCalled()
  prepared = true
  await waitFor(() => expect(container.querySelector('video')?.getAttribute('src')).toContain('rendition=proxy_720p'), { timeout: 3500 })
  expect(onFailure).not.toHaveBeenCalled()
})

it('plays a cached original if preparation confirms no preview job is needed', async () => {
  const original = { request_id: 7, dive_id: 7, video_uuid: 'clip', status: 'ready' as const, rendition: 'original', poster_url: null, playback_url: '/play', available_renditions: ['original'] }
  vi.mocked(getEvaluationMediaStatus).mockResolvedValue(original)
  vi.mocked(prepareEvaluationMedia).mockResolvedValue({ ...original, created_jobs: [], reused_jobs: [] })
  const { container } = render(<EvaluationPlayer requestId={7} />)
  await waitFor(() => expect(container.querySelector('video')?.getAttribute('src')).toContain('rendition=original'))
})

it('does not report missing media as a playback failure while its preparation is running', async () => {
  const missing = { request_id: 7, dive_id: 7, video_uuid: 'clip', status: 'missing' as const, rendition: null, poster_url: null, playback_url: null, available_renditions: [] }
  vi.mocked(getEvaluationMediaStatus).mockResolvedValue(missing)
  vi.mocked(prepareEvaluationMedia).mockResolvedValue({ ...missing, status: 'ready', rendition: 'proxy_720p', playback_url: '/play', available_renditions: ['proxy_720p'], created_jobs: [], reused_jobs: [] })
  const onFailure = vi.fn()
  const { container } = render(<EvaluationPlayer requestId={7} watching onFailure={onFailure} />)
  await waitFor(() => expect(container.querySelector('video')).not.toBeNull())
  expect(onFailure).not.toHaveBeenCalled()
})

it('keeps an anticipated preparation alive when the worker queue exceeds ninety seconds', async () => {
  const clock = vi.spyOn(Date, 'now').mockReturnValue(0)
  const original = { request_id: 7, dive_id: 7, video_uuid: 'clip', status: 'ready' as const, rendition: 'original', poster_url: null, playback_url: '/play', available_renditions: ['original'] }
  let ready = false
  vi.mocked(getEvaluationMediaStatus).mockImplementation(async () => ready ? { ...original, available_renditions: ['original', 'proxy_720p'] } : original)
  vi.mocked(prepareEvaluationMedia).mockResolvedValue({ ...original, created_jobs: ['proxy_720p'], reused_jobs: [] })
  const onFailure = vi.fn()
  const { container } = render(<EvaluationPlayer requestId={7} preloadOnly paused onFailure={onFailure} />)
  await waitFor(() => expect(prepareEvaluationMedia).toHaveBeenCalledOnce())
  clock.mockReturnValue(90_001)
  await waitFor(() => expect(vi.mocked(getEvaluationMediaStatus).mock.calls.length).toBeGreaterThanOrEqual(3), { timeout: 3500 })
  expect(onFailure).not.toHaveBeenCalled()
  expect(container.querySelector('video')).toBeNull()
  ready = true
  await waitFor(() => expect(container.querySelector('video')?.getAttribute('src')).toContain('rendition=proxy_720p'), { timeout: 3500 })
  expect(onFailure).not.toHaveBeenCalled()
})

it('recovers a hidden preview automatically and reports failure only after exhausting ready renditions', async () => {
  vi.mocked(getEvaluationMediaStatus).mockResolvedValue({ request_id: 7, dive_id: 7, video_uuid: 'clip', status: 'ready', rendition: 'original', poster_url: null, playback_url: '/play', available_renditions: ['original', 'proxy_720p', 'proxy_360p'] })
  const onFailure = vi.fn()
  const onPrepared = vi.fn()
  const { container } = render(<EvaluationPlayer requestId={7} preloadOnly paused onFailure={onFailure} onPrepared={onPrepared} />)
  await waitFor(() => expect(container.querySelector('video')?.getAttribute('src')).toContain('rendition=proxy_720p'))
  fireEvent.error(container.querySelector('video')!)
  expect(container.querySelector('video')?.getAttribute('src')).toContain('rendition=proxy_360p')
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(onFailure).not.toHaveBeenCalled()
  onPrepared.mockClear()
  fireEvent.error(container.querySelector('video')!)
  expect(container.querySelector('video')?.getAttribute('src')).toContain('rendition=original')
  expect(onPrepared).toHaveBeenCalledOnce()
  expect(onFailure).not.toHaveBeenCalled()
  fireEvent.error(container.querySelector('video')!)
  await waitFor(() => expect(onFailure).toHaveBeenCalledOnce())
})

it('allows an oversized streaming preview to advance without hidden loadeddata', async () => {
  vi.stubGlobal('URL', Object.assign(class extends URL {}, { createObjectURL: vi.fn(), revokeObjectURL: vi.fn() }))
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('large', { headers: { 'content-length': String(17 * 1024 * 1024) } })))
  try {
    vi.mocked(getEvaluationMediaStatus).mockResolvedValue({ request_id: 7, dive_id: 7, video_uuid: 'clip', status: 'ready', rendition: 'proxy_720p', poster_url: null, playback_url: '/play', available_renditions: ['proxy_720p'] })
    const onPrepared = vi.fn()
    const onBuffered = vi.fn()
    const { container } = render(<EvaluationPlayer requestId={7} preloadOnly paused onPrepared={onPrepared} onBuffered={onBuffered} />)
    await waitFor(() => expect(container.querySelector('video')?.getAttribute('src')).toContain('rendition=proxy_720p'))
    expect(onPrepared).toHaveBeenCalled()
    expect(onBuffered).not.toHaveBeenCalled()
    expect(URL.createObjectURL).not.toHaveBeenCalled()
  } finally {
    vi.unstubAllGlobals()
  }
})

it.each(['decoded', 'exhausted'] as const)('tries remaining renditions after a first-frame timeout (%s)', async outcome => {
  vi.useFakeTimers()
  try {
    const onFailure = vi.fn()
    const initialMedia = { request_id: 7, dive_id: 7, video_uuid: 'clip', status: 'ready' as const, rendition: 'proxy_720p', poster_url: null, playback_url: '/play', available_renditions: ['original', 'proxy_720p', 'proxy_360p'] }
    const { container } = render(<EvaluationPlayer requestId={7} initialMedia={initialMedia} watching onFailure={onFailure} />)
    expect(container.querySelector('video')?.getAttribute('src')).toContain('rendition=proxy_720p')
    await act(async () => { await vi.advanceTimersByTimeAsync(20_000) })
    expect(container.querySelector('video')?.getAttribute('src')).toContain('rendition=proxy_360p')
    expect(onFailure).not.toHaveBeenCalled()
    if (outcome === 'decoded') {
      fireEvent.loadedData(container.querySelector('video')!)
      await act(async () => { await vi.advanceTimersByTimeAsync(60_000) })
      expect(container.querySelector('video')?.getAttribute('src')).toContain('rendition=proxy_360p')
      expect(onFailure).not.toHaveBeenCalled()
    } else {
      await act(async () => { await vi.advanceTimersByTimeAsync(20_000) })
      expect(container.querySelector('video')?.getAttribute('src')).toContain('rendition=original')
      expect(onFailure).not.toHaveBeenCalled()
      await act(async () => { await vi.advanceTimersByTimeAsync(20_000) })
      expect(onFailure).toHaveBeenCalledOnce()
    }
  } finally {
    vi.useRealTimers()
  }
})

it('uses newly ready renditions when the existing first-frame timer expires', async () => {
  vi.useFakeTimers()
  try {
    const initialMedia = { request_id: 7, dive_id: 7, video_uuid: 'clip', status: 'ready' as const, rendition: 'proxy_360p', poster_url: null, playback_url: '/play', available_renditions: ['proxy_360p'] }
    let finish!: (value: Awaited<ReturnType<typeof prepareEvaluationMedia>>) => void
    vi.mocked(prepareEvaluationMedia).mockReturnValue(new Promise(resolve => { finish = resolve }))
    const onFailure = vi.fn()
    const { container } = render(<EvaluationPlayer requestId={7} initialMedia={initialMedia} watching onFailure={onFailure} />)
    await act(async () => { finish({ ...initialMedia, available_renditions: ['proxy_360p', 'proxy_720p'], created_jobs: [], reused_jobs: [] }) })
    expect(container.querySelector('video')?.getAttribute('src')).toContain('rendition=proxy_360p')
    await act(async () => { await vi.advanceTimersByTimeAsync(20_000) })
    expect(container.querySelector('video')?.getAttribute('src')).toContain('rendition=proxy_720p')
    expect(onFailure).not.toHaveBeenCalled()
  } finally {
    vi.useRealTimers()
  }
})

it('recovers a stalled preview download through the next ready rendition', async () => {
  vi.useFakeTimers()
  vi.stubGlobal('URL', Object.assign(class extends URL {}, { createObjectURL: vi.fn(() => 'blob:recovered-preview'), revokeObjectURL: vi.fn() }))
  vi.stubGlobal('fetch', vi.fn().mockImplementationOnce(() => new Promise(() => {})).mockResolvedValueOnce(new Response(new Uint8Array([1, 2, 3]))))
  let dispose = () => {}
  try {
    const initialMedia = { request_id: 7, dive_id: 7, video_uuid: 'clip', status: 'ready' as const, rendition: 'proxy_720p', poster_url: null, playback_url: '/play', available_renditions: ['proxy_720p', 'proxy_360p'] }
    const onFailure = vi.fn()
    const { container, unmount } = render(<EvaluationPlayer requestId={7} initialMedia={initialMedia} watching onFailure={onFailure} />)
    dispose = unmount
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000) })
    expect(fetch).toHaveBeenCalledTimes(2)
    expect(vi.mocked(fetch).mock.calls[1][0]).toContain('rendition=proxy_360p')
    expect(container.querySelector('video')).toHaveAttribute('src', 'blob:recovered-preview')
    expect(onFailure).not.toHaveBeenCalled()
  } finally {
    dispose()
    vi.useRealTimers()
    vi.unstubAllGlobals()
  }
})

it('keeps room playback on its scoped transport and starts at the server deadline', async () => {
  vi.useFakeTimers()
  const now = Date.now() / 1000
  const { container, unmount } = render(<EvaluationPlayer roomMedia={{ src: '/api/v1/rooms/K7QX/media/1/video', poster: '/api/v1/rooms/K7QX/media/1/poster', startsAt: now + 3, serverOffset: 0 }} />)
  const video = container.querySelector('video')!
  expect(video.getAttribute('src')).toBe('/api/v1/rooms/K7QX/media/1/video')
  expect(getEvaluationMediaStatus).not.toHaveBeenCalled()
  expect(prepareEvaluationMedia).not.toHaveBeenCalled()
  await act(async () => { vi.advanceTimersByTime(2999) })
  expect(video.play).not.toHaveBeenCalled()
  await act(async () => { vi.advanceTimersByTime(1) })
  expect(video.play).toHaveBeenCalledTimes(1)
  unmount()
  vi.useRealTimers()
})

it('reports room readiness without starting playback while the server is loading', async () => {
  vi.useFakeTimers()
  const onRoomReady = vi.fn(), onEnded = vi.fn()
  const media = { src: '/api/v1/rooms/ABCD/media/1/video', poster: '', startsAt: 0, serverOffset: 0 }
  const { container, rerender, unmount } = render(<EvaluationPlayer roomMedia={media} onRoomReady={onRoomReady} onEnded={onEnded} />)
  const video = container.querySelector('video')!
  fireEvent.canPlayThrough(video)
  expect(onRoomReady).toHaveBeenCalledTimes(1)
  await act(async () => { vi.advanceTimersByTime(15000) })
  expect(video.play).not.toHaveBeenCalled()
  Object.defineProperty(video, 'duration', { configurable: true, value: 60 })
  rerender(<EvaluationPlayer roomMedia={{ ...media, startsAt: Date.now()/1000 - 30 }} onEnded={onEnded} />)
  fireEvent.loadedMetadata(video)
  await act(async () => { vi.advanceTimersByTime(1) })
  expect(video.currentTime).toBe(0)
  expect(video.play).toHaveBeenCalledTimes(1)
  fireEvent.ended(video)
  expect(onEnded).toHaveBeenCalledTimes(1)
  // Clock snapshots do not replay or seek the same video.
  rerender(<EvaluationPlayer roomMedia={{ ...media, startsAt: Date.now()/1000 - 30, serverOffset: 2 }} />)
  await act(async () => { vi.advanceTimersByTime(1) })
  expect(video.play).toHaveBeenCalledTimes(1)
  unmount()
  vi.useRealTimers()
})
