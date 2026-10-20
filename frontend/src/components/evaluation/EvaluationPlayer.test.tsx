import { fireEvent, render, screen, waitFor } from '@testing-library/react'
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
  const { container } = render(<EvaluationPlayer requestId={7} />)
  await waitFor(() => expect(container.querySelector('video')?.getAttribute('src')).toContain('rendition=proxy_720p'))
  fireEvent.click(screen.getByRole('button', { name: /quality/i }))
  fireEvent.error(container.querySelector('video')!)
  expect(screen.getByRole('alert')).toBeInTheDocument()
  expect(container.querySelector('video')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Play a lower-quality preview' }))
  expect(container.querySelector('video')?.getAttribute('src')).toContain('rendition=proxy_720p')
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
