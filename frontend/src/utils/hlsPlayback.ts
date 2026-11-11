/**
 * Adaptive (HLS) clip playback.
 *
 * A clip packaged as fragmented MP4 has a master playlist at
 * /api/v1/media/{uuid}/hls.m3u8 listing its Light and HQ files by byte
 * range on B2. Apple's native player (Safari, every iOS browser) reads those
 * bytes without CORS, so it is always offered (mode "apple"). Every other
 * player (hls.js on MediaSource, Chrome's own native HLS) needs the bucket to
 * answer CORS, so it is offered only when the server says so (mode "all").
 *
 * Every pooled element gets its source through setMediaSource so that an
 * hls.js instance is created, replaced and destroyed with its element.
 */
import type Hls from 'hls.js'
import { recordThroughput } from './playbackPolicy'

export type HlsMode = 'apple' | 'all'

const HLS_PATH = /\/api\/v1\/media\/([^/?#]+)\/hls\.m3u8(?:\?|$)/

export function hlsUrl(videoUuid: string, startHq = false): string {
  return `/api/v1/media/${encodeURIComponent(videoUuid)}/hls.m3u8${startHq ? '?start=hq' : ''}`
}

export function isHlsUrl(url: string | null | undefined): boolean {
  return !!url && HLS_PATH.test(url)
}

/** Any playlist source: the adaptive master or one rendition's playlist. */
export function isPlaylistUrl(url: string | null | undefined): boolean {
  return isHlsUrl(url) || (!!url && /\/api\/v1\/media\/revisions\/\d+\/hls\.m3u8$/.test(url))
}

export function parseHlsMode(value: unknown): HlsMode | null {
  return value === 'apple' || value === 'all' ? value : null
}

let nativeSupport: boolean | null = null
/** The media element plays HLS itself. */
function nativeHls(): boolean {
  if (nativeSupport === null) {
    try {
      nativeSupport = Boolean(document.createElement('video').canPlayType('application/vnd.apple.mpegurl'))
    } catch {
      nativeSupport = false
    }
  }
  return nativeSupport
}

let appleSupport: boolean | null = null
/**
 * Apple's native player (AVFoundation): reads cross-origin segments without
 * CORS. Chrome 157 also answers canPlayType for HLS but refused the B2
 * segments (MEDIA_ERR_SRC_NOT_SUPPORTED) with and without CORS, so the vendor
 * counts and other browsers prefer hls.js.
 */
export function appleHls(): boolean {
  if (appleSupport === null) appleSupport = nativeHls() && /^Apple/.test(navigator.vendor || '')
  return appleSupport
}

type MediaSourceLike = { isTypeSupported?: (type: string) => boolean }
let mseSupport: boolean | null = null
function mseHls(): boolean {
  if (mseSupport === null) {
    const scope = window as unknown as { MediaSource?: MediaSourceLike; ManagedMediaSource?: MediaSourceLike }
    const source = scope.ManagedMediaSource ?? scope.MediaSource
    try {
      mseSupport = Boolean(source?.isTypeSupported?.('video/mp4; codecs="avc1.640028,mp4a.40.2"'))
    } catch {
      mseSupport = false
    }
  }
  return mseSupport
}

// One MediaSource failure (e.g. the bucket refused a cross-origin read)
// turns hls.js off for the rest of the tab: the next clips start on the
// progressive files instead of failing the same way.
let mseDisabled = false

/** Whether this browser can play a clip's HLS in the given server mode. */
export function canPlayHls(mode: HlsMode | null | undefined): boolean {
  if (!mode) return false
  if (appleHls()) return true
  // Elsewhere only hls.js: Chrome's own native HLS refused B2 segments even
  // with CORS, so a failed hls.js turns adaptive playback off for the tab.
  return mode === 'all' && !mseDisabled && mseHls()
}

/** hls.js plays the stream (otherwise the element does, natively). */
function usesHlsJs(): boolean {
  return !appleHls() && !mseDisabled && mseHls()
}

// ---- Element source management -----------------------------------------

type Engine = { src: string; hls: Hls | null; failed: boolean; startHq: boolean; fragments: number }
const engines = new WeakMap<HTMLVideoElement, Engine>()
let loader: Promise<typeof Hls> | null = null
function loadHls(): Promise<typeof Hls> {
  loader ??= import('hls.js').then(module => module.default)
  return loader
}

/** The logical source of an element (its playlist URL under hls.js). */
export function mediaSourceOf(video: HTMLVideoElement): string | null {
  return engines.get(video)?.src ?? video.getAttribute('src')
}

/** True when an element's hls.js engine gave up (it raised an error event). */
export function hlsEngineFailed(video: HTMLVideoElement): boolean {
  return Boolean(engines.get(video)?.failed)
}

function destroyEngine(video: HTMLVideoElement) {
  const engine = engines.get(video)
  if (!engine) return
  engines.delete(video)
  engine.hls?.destroy()
}

/** Stop an element and abort every transfer it owns. */
export function clearMediaSource(video: HTMLVideoElement) {
  destroyEngine(video)
  video.removeAttribute('src')
  video.load()
}

/** Point an element at a source; HLS goes through hls.js when not native. */
export function setMediaSource(video: HTMLVideoElement, src: string) {
  if (mediaSourceOf(video) === src) return
  destroyEngine(video)
  if (!isHlsUrl(src) || !usesHlsJs()) {
    video.src = src
    return
  }
  video.removeAttribute('src')
  const engine: Engine = { src, hls: null, failed: false, startHq: src.includes('start=hq'), fragments: 0 }
  engines.set(video, engine)
  void loadHls().then(HlsClass => {
    if (engines.get(video) !== engine) return
    if (!HlsClass.isSupported()) {
      fail(video, engine)
      return
    }
    attach(video, engine, HlsClass)
  }, () => fail(video, engine))
}

/** Reload the same source from scratch (fresh playlists, fresh grants). */
export function reloadMediaSource(video: HTMLVideoElement) {
  const engine = engines.get(video)
  if (!engine) {
    video.load()
    return
  }
  const src = engine.src
  destroyEngine(video)
  setMediaSource(video, src)
}

function fail(video: HTMLVideoElement, engine: Engine) {
  if (engines.get(video) !== engine || engine.failed) return
  engine.failed = true
  engine.hls?.destroy()
  engine.hls = null
  // Failing before any segment arrived is a capability problem (CORS,
  // codecs): stop offering hls.js. A later failure (an expired grant on a
  // long-open clip) is the player's to reload.
  if (!engine.fragments) mseDisabled = true
  video.dispatchEvent(new Event('error'))
}

function attach(video: HTMLVideoElement, engine: Engine, HlsClass: typeof Hls) {
  const hls = new HlsClass({
    // A clip is ~10–20 s: keep every lap buffered so a loop never refetches
    // or climbs back through the ladder.
    backBufferLength: 120,
    maxBufferLength: 30,
    capLevelToPlayerSize: false,
    enableWorker: true,
    // Retries are hls.js's own; a refused segment (expired grant, no CORS)
    // then surfaces once as a fatal error and the player reloads or falls
    // back to the progressive file.
  })
  engine.hls = hls
  let mediaRecoveries = 0
  hls.on(HlsClass.Events.MANIFEST_PARSED, (_event, data) => {
    const heights = data.levels.map(level => level.height || 0)
    const target = engine.startHq ? Math.max(...heights) : Math.min(...heights)
    const index = heights.indexOf(target)
    if (index >= 0) hls.startLevel = index
  })
  hls.on(HlsClass.Events.FRAG_LOADED, (_event, data) => {
    engine.fragments += 1
    const stats = data.frag.stats
    const seconds = (stats.loading.end - stats.loading.first) / 1000
    if (stats.loaded >= 200_000 && seconds >= 0.05) recordThroughput((stats.loaded * 8) / seconds / 1e6)
  })
  hls.on(HlsClass.Events.ERROR, (_event, data) => {
    if (!data.fatal || engines.get(video) !== engine) return
    if (data.type === HlsClass.ErrorTypes.MEDIA_ERROR && mediaRecoveries < 1) {
      mediaRecoveries += 1
      hls.recoverMediaError()
      return
    }
    fail(video, engine)
  })
  hls.loadSource(engine.src)
  hls.attachMedia(video)
}

/** Tests only. */
export function resetHlsPlayback(overrides: { apple?: boolean; native?: boolean; mse?: boolean } = {}) {
  nativeSupport = overrides.native ?? overrides.apple ?? null
  appleSupport = overrides.apple ?? null
  mseSupport = overrides.mse ?? null
  mseDisabled = false
  loader = null
}
