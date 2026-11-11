import { beforeEach, expect, it, vi } from 'vitest'

type Handler = (event: string, data: unknown) => void
const instances: FakeHls[] = []
class FakeHls {
  static Events = { MANIFEST_PARSED: 'manifestParsed', FRAG_LOADED: 'fragLoaded', ERROR: 'error' }
  static ErrorTypes = { MEDIA_ERROR: 'mediaError', NETWORK_ERROR: 'networkError' }
  static supported = true
  static isSupported() { return FakeHls.supported }
  handlers = new Map<string, Handler>()
  source: string | null = null
  media: HTMLVideoElement | null = null
  destroyed = false
  recovered = 0
  startLevel = -1
  constructor(public config: Record<string, unknown>) { instances.push(this) }
  on(event: string, handler: Handler) { this.handlers.set(event, handler) }
  emit(event: string, data: unknown) { this.handlers.get(event)?.(event, data) }
  loadSource(src: string) { this.source = src }
  attachMedia(video: HTMLVideoElement) { this.media = video }
  recoverMediaError() { this.recovered += 1 }
  destroy() { this.destroyed = true }
}
vi.mock('hls.js', () => ({ default: FakeHls }))

import {
  canPlayHls, clearMediaSource, hlsEngineFailed, hlsUrl, isHlsUrl, mediaSourceOf,
  reloadMediaSource, resetHlsPlayback, setMediaSource,
} from './hlsPlayback'
import { resetPlaybackPolicy, throughputEstimate } from './playbackPolicy'

const flush = () => new Promise(resolve => setTimeout(resolve, 0))

beforeEach(() => {
  instances.length = 0
  FakeHls.supported = true
  resetPlaybackPolicy()
})

it('builds and recognizes master playlist URLs', () => {
  expect(hlsUrl('a b')).toBe('/api/v1/media/a%20b/hls.m3u8')
  expect(hlsUrl('x', true)).toBe('/api/v1/media/x/hls.m3u8?start=hq')
  expect(isHlsUrl('/api/v1/media/x/hls.m3u8?start=hq')).toBe(true)
  expect(isHlsUrl('/api/v1/media/revisions/3/hls.m3u8')).toBe(false)
  expect(isHlsUrl('/api/v1/media/x/play/light')).toBe(false)
})

it('Apple players take either mode; the others need the bucket CORS ("all")', () => {
  resetHlsPlayback({ apple: true, mse: true })
  expect(canPlayHls('apple')).toBe(true)
  expect(canPlayHls(null)).toBe(false)
  resetHlsPlayback({ apple: false, mse: true })
  expect(canPlayHls('apple')).toBe(false)
  expect(canPlayHls('all')).toBe(true)
  // Non-Apple native HLS (Chrome's) is never used: it refused B2 segments.
  resetHlsPlayback({ apple: false, native: true, mse: false })
  expect(canPlayHls('apple')).toBe(false)
  expect(canPlayHls('all')).toBe(false)
  resetHlsPlayback({ apple: false, native: false, mse: false })
  expect(canPlayHls('all')).toBe(false)
})

it('Apple native HLS is a plain src', () => {
  resetHlsPlayback({ apple: true, mse: true })
  const video = document.createElement('video')
  setMediaSource(video, hlsUrl('n'))
  expect(video.getAttribute('src')).toBe('/api/v1/media/n/hls.m3u8')
  expect(instances).toHaveLength(0)
})

it('hls.js owns the element, starts on the lowest rendition and is destroyed with it', async () => {
  resetHlsPlayback({ apple: false, mse: true })
  const video = document.createElement('video')
  setMediaSource(video, hlsUrl('m'))
  expect(mediaSourceOf(video)).toBe('/api/v1/media/m/hls.m3u8')
  expect(video.hasAttribute('src')).toBe(false)
  await flush()
  const hls = instances[0]
  expect(hls.source).toBe('/api/v1/media/m/hls.m3u8')
  expect(hls.media).toBe(video)
  hls.emit('manifestParsed', { levels: [{ height: 1280 }, { height: 1920 }] })
  expect(hls.startLevel).toBe(0)
  // Same source: nothing is rebuilt.
  setMediaSource(video, hlsUrl('m'))
  expect(instances).toHaveLength(1)
  clearMediaSource(video)
  expect(hls.destroyed).toBe(true)
  expect(mediaSourceOf(video)).toBeNull()
})

it('start=hq starts hls.js on the tallest rendition', async () => {
  resetHlsPlayback({ apple: false, mse: true })
  const video = document.createElement('video')
  setMediaSource(video, hlsUrl('h', true))
  await flush()
  instances[0].emit('manifestParsed', { levels: [{ height: 1280 }, { height: 1920 }] })
  expect(instances[0].startLevel).toBe(1)
})

it('segment downloads feed the shared network estimate', async () => {
  resetHlsPlayback({ apple: false, mse: true })
  const video = document.createElement('video')
  setMediaSource(video, hlsUrl('t'))
  await flush()
  instances[0].emit('fragLoaded', { frag: { stats: { loaded: 1_000_000, loading: { first: 0, end: 1000 } } } })
  expect(throughputEstimate()).toBeCloseTo(8)
})

it('a failure before any segment raises an error and turns hls.js off for the tab', async () => {
  resetHlsPlayback({ apple: false, mse: true })
  const video = document.createElement('video')
  const onError = vi.fn()
  video.addEventListener('error', onError)
  setMediaSource(video, hlsUrl('c'))
  await flush()
  instances[0].emit('error', { fatal: true, type: 'networkError' })
  expect(onError).toHaveBeenCalledTimes(1)
  expect(hlsEngineFailed(video)).toBe(true)
  expect(instances[0].destroyed).toBe(true)
  expect(canPlayHls('all')).toBe(false)
  // Not even through a native HLS the browser claims to have.
  resetHlsPlayback({ apple: false, native: true, mse: true })
  const other = document.createElement('video')
  setMediaSource(other, hlsUrl('c2'))
  await flush()
  instances[instances.length - 1].emit('error', { fatal: true, type: 'networkError' })
  expect(canPlayHls('all')).toBe(false)
})

it('a failure mid-play keeps hls.js available and reloads with a fresh engine', async () => {
  resetHlsPlayback({ apple: false, mse: true })
  const video = document.createElement('video')
  setMediaSource(video, hlsUrl('r'))
  await flush()
  instances[0].emit('fragLoaded', { frag: { stats: { loaded: 10, loading: { first: 0, end: 1 } } } })
  instances[0].emit('error', { fatal: true, type: 'mediaError' })
  expect(instances[0].recovered).toBe(1) // one in-place media recovery first
  instances[0].emit('error', { fatal: true, type: 'mediaError' })
  expect(canPlayHls('all')).toBe(true)
  reloadMediaSource(video)
  await flush()
  expect(instances).toHaveLength(2)
  expect(instances[1].source).toBe('/api/v1/media/r/hls.m3u8')
  expect(hlsEngineFailed(video)).toBe(false)
})

it('a source replaced before hls.js loads never attaches the stale engine', async () => {
  resetHlsPlayback({ apple: false, mse: true })
  const video = document.createElement('video')
  setMediaSource(video, hlsUrl('old'))
  setMediaSource(video, '/api/v1/media/old/play/light')
  await flush()
  expect(instances).toHaveLength(0)
  expect(video.getAttribute('src')).toBe('/api/v1/media/old/play/light')
})
