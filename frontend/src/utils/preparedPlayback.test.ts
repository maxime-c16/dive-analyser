import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { WARMUP_HOLD_MS, acquirePlaybackVideo, holdWarmup, releasePlaybackVideo, releaseWarmup, preparePlaybackWindow, resetPreparedPlayback } from './preparedPlayback'
import { getPreviewForPlayback } from './mediaPreview'
vi.mock('./mediaPreview', () => ({
  getPreviewForPlayback: vi.fn(),
  getPreview: vi.fn(async () => ({ playbackUrl: null, posterUrl: null, videoThumbUrl: null, ready: true, startRole: null })),
}))
beforeEach(() => {
  vi.useFakeTimers()
  vi.mocked(getPreviewForPlayback).mockImplementation(async uuid => ({
    playbackUrl: `/api/v1/media/revisions/${uuid}/play`, posterUrl: null, videoThumbUrl: null, ready: true, playbackResolved: true,
  }))
})
afterEach(() => { resetPreparedPlayback(); vi.useRealTimers(); vi.clearAllMocks() })
const flush = () => vi.advanceTimersByTimeAsync(0)

it('adopts the same buffered cloud video without another src assignment or load', async () => {
  preparePlaybackWindow(['next'])
  await flush()
  const video = acquirePlaybackVideo('next')
  expect(video.getAttribute('src')).toBe('/api/v1/media/revisions/next/play')
  const load = vi.spyOn(video, 'load')
  Object.defineProperty(video, 'readyState', { value: 4, configurable: true })
  releasePlaybackVideo('next', video)
  expect(acquirePlaybackVideo('next')).toBe(video)
  expect(load).not.toHaveBeenCalled()
})
it('never restarts or pauses the active source when warming changes direction', async () => {
  const current = acquirePlaybackVideo('here')
  current.src = '/current.mp4'
  const pause = vi.spyOn(current, 'pause')
  preparePlaybackWindow(['here', 'next', 'prev'])
  await flush()
  preparePlaybackWindow(['here', 'prev', 'other'])
  await flush()
  expect(current.getAttribute('src')).toBe('/current.mp4')
  expect(pause).not.toHaveBeenCalled()
})
it('bounds speculative elements and aborts obsolete native transfers', async () => {
  const create = vi.spyOn(document, 'createElement')
  preparePlaybackWindow(['a', 'b', 'c', 'd', 'e'])
  await flush()
  // Two speculative decoders: next and previous beside the active clip.
  expect(create.mock.calls.filter(([tag]) => tag === 'video')).toHaveLength(2)
  const a = acquirePlaybackVideo('a')
  releasePlaybackVideo('a', a)
  preparePlaybackWindow(['z'])
  await flush()
  expect(a.hasAttribute('src')).toBe(false)
})
it('ignores late status responses after sign-out or a changed window', async () => {
  let resolve!: (value: Awaited<ReturnType<typeof getPreviewForPlayback>>) => void
  vi.mocked(getPreviewForPlayback).mockImplementation(() => new Promise(done => { resolve = done }))
  preparePlaybackWindow(['late'])
  await flush() // the tile lookup settles; the playback status is in flight
  resetPreparedPlayback()
  const create = vi.spyOn(document, 'createElement')
  resolve({ playbackUrl: '/private.mp4', posterUrl: null, videoThumbUrl: null, ready: true })
  await flush()
  expect(create).not.toHaveBeenCalled()
})
it('expires idle videos and clears an active source at sign-out', async () => {
  preparePlaybackWindow(['a'])
  await flush()
  const a = acquirePlaybackVideo('a')
  releasePlaybackVideo('a', a)
  await vi.advanceTimersByTimeAsync(30_000)
  expect(a.hasAttribute('src')).toBe(false)
  const active = acquirePlaybackVideo('b')
  active.src = '/private.mp4'
  resetPreparedPlayback()
  expect(active.hasAttribute('src')).toBe(false)
})
it('respects data saver without blocking explicit playback', async () => {
  vi.stubGlobal('navigator', { onLine: true, connection: { saveData: true } })
  try {
    preparePlaybackWindow(['a'])
    await flush()
    expect(getPreviewForPlayback).not.toHaveBeenCalled()
    expect(acquirePlaybackVideo('a')).toBeInstanceOf(HTMLVideoElement)
  } finally { vi.unstubAllGlobals() }
})

it('keeps incoming HQ across release-before-acquire with a full four-clip window', async () => {
  const a = acquirePlaybackVideo('a')
  preparePlaybackWindow(['a', 'b', 'c', 'd'])
  await flush()
  releasePlaybackVideo('a', a)
  const b = acquirePlaybackVideo('b')
  preparePlaybackWindow(['b', 'c', 'a', 'd'])
  await flush()
  releasePlaybackVideo('b', b)
  expect(acquirePlaybackVideo('a')).toBe(a)
  preparePlaybackWindow(['a', 'x'])
  await flush()
  resetPreparedPlayback()
  expect(a.hasAttribute('src')).toBe(false)
})

it('preloads ready preview bytes while keeping original-only warming conservative', async () => {
  const create = vi.spyOn(document, 'createElement')
  vi.mocked(getPreviewForPlayback).mockImplementation(async uuid => ({
    playbackUrl: uuid === 'preview' ? '/preview.mp4' : '/original.mov',
    previewPlaybackUrl: uuid === 'preview' ? '/preview.mp4' : null,
    posterUrl: null, videoThumbUrl: null, ready: true, playbackResolved: true,
  }))
  preparePlaybackWindow(['preview', 'original'])
  await flush()
  const videos = create.mock.results.map(result => result.value).filter(value => value instanceof HTMLVideoElement) as HTMLVideoElement[]
  expect(videos.find(video => video.getAttribute('src') === '/preview.mp4')?.preload).toBe('auto')
  expect(videos.find(video => video.getAttribute('src') === '/original.mov')?.preload).toBe('metadata')
})

it('does not warm an unresolved local original after playback status fails', async () => {
  vi.mocked(getPreviewForPlayback).mockResolvedValue({ playbackUrl: '/api/v1/media/cache/42/play', posterUrl: null, videoThumbUrl: null, ready: true })
  const create = vi.spyOn(document, 'createElement')
  preparePlaybackWindow(['unresolved'])
  await flush()
  expect(create.mock.calls.filter(([tag]) => tag === 'video')).toHaveLength(0)
})

it('holds neighbor warming until the visible clip starts, bounded in time', async () => {
  const create = vi.spyOn(document, 'createElement')
  const release = holdWarmup()
  preparePlaybackWindow(['here', 'next'])
  await flush()
  expect(getPreviewForPlayback).not.toHaveBeenCalled()
  expect(create.mock.calls.filter(([tag]) => tag === 'video')).toHaveLength(0)
  release()
  await flush()
  expect(create.mock.calls.filter(([tag]) => tag === 'video')).toHaveLength(2)
  // A clip that never presents cannot block warming forever.
  resetPreparedPlayback()
  holdWarmup()
  preparePlaybackWindow(['other'])
  await flush()
  expect(getPreviewForPlayback).not.toHaveBeenCalledWith('other')
  await vi.advanceTimersByTimeAsync(WARMUP_HOLD_MS)
  expect(getPreviewForPlayback).toHaveBeenCalledWith('other')
})

it('a previous clip releasing late never ends the next clip hold', async () => {
  const releasePrevious = holdWarmup()
  const releaseNext = holdWarmup() // the next clip mounts before the old one cleans up
  preparePlaybackWindow(['next', 'after'])
  releasePrevious()
  await flush()
  expect(getPreviewForPlayback).not.toHaveBeenCalled()
  releaseNext()
  await flush()
  expect(getPreviewForPlayback).toHaveBeenCalled()
  releaseWarmup() // reset path stays callable with no hold
})

it('warmers waiting on a clip hold keep waiting when the next clip takes it over', async () => {
  const releaseOld = holdWarmup()
  preparePlaybackWindow(['next', 'after'])
  // Clip change: the old clip's cleanup releases, then the new clip holds.
  releaseOld()
  const releaseNew = holdWarmup()
  await flush()
  expect(getPreviewForPlayback).not.toHaveBeenCalled()
  releaseNew()
  await flush()
  expect(getPreviewForPlayback).toHaveBeenCalled()
})

it('measures a hinted neighbor downloading its durable Light in the background', async () => {
  const { getPreview } = await import('./mediaPreview')
  const { throughputEstimate, resetPlaybackPolicy } = await import('./playbackPolicy')
  resetPlaybackPolicy()
  vi.mocked(getPreview).mockResolvedValueOnce({ playbackUrl: '/proxy.mp4', posterUrl: null, videoThumbUrl: null, ready: true, startRole: 'light', startLightVersion: 'ffmpeg-h264-web-v2' })
  const create = vi.spyOn(document, 'createElement')
  const now = vi.spyOn(performance, 'now').mockReturnValue(0)
  preparePlaybackWindow(['neighbor'])
  await flush()
  const video = create.mock.results.map(result => result.value).find((element): element is HTMLVideoElement => element instanceof HTMLVideoElement)!
  expect(video.getAttribute('src')).toBe('/api/v1/media/neighbor/play/light')
  Object.defineProperty(video, 'duration', { configurable: true, value: 12 })
  Object.defineProperty(video, 'buffered', { configurable: true, value: { length: 1, end: () => 12, start: () => 0 } })
  now.mockReturnValue(2000) // the whole clip arrived in 2 s
  video.dispatchEvent(new Event('progress'))
  now.mockRestore()
  expect(throughputEstimate()).not.toBeNull()
})
