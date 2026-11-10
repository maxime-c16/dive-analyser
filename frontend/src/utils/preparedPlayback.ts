import { canPrefetch } from '../hooks/useNavigationIntent'
import { getPreview, getPreviewForPlayback } from './mediaPreview'
import { autoStartUrl } from './playbackPolicy'

// Keep the actual media element, not a fetch of its bytes. A revision URL
// redirects with no-store and the bucket has no CORS: fetch warming cannot
// prepare it, and a second element would need another playback grant.
// Two speculative neighbors (next/previous) beside the active clip: each one
// is a hardware decoder on phones, and the active clip may add an HQ one.
const MAX_IDLE = 2
const IDLE_TTL_MS = 30_000
interface Entry {
  uuid: string
  video: HTMLVideoElement
  active: boolean
  timer: ReturnType<typeof setTimeout> | null
}
const entries = new Map<string, Entry>()
let desired = new Set<string>()
let generation = 0
const resetListeners = new Set<() => void>()
export function onPreparedPlaybackReset(listener: () => void) {
  resetListeners.add(listener)
  return () => { resetListeners.delete(listener) }
}

function dispose(entry: Entry) {
  if (entry.timer) clearTimeout(entry.timer)
  entry.video.pause()
  entry.video.removeAttribute('src')
  entry.video.load() // Abort the resource, including any presigned transfer.
  entries.delete(entry.uuid)
}
function park(entry: Entry) {
  entry.active = false
  entry.video.autoplay = false
  entry.video.pause()
  entry.video.muted = true
  // Returning to a dive should start at its beginning, while keeping the
  // already loaded source/decoder. Never reload an unchanged src.
  if (entry.video.readyState >= 1 && entry.video.currentTime > 0) entry.video.currentTime = 0
  entry.timer = setTimeout(() => {
    if (!entry.active && entries.get(entry.uuid) === entry) {
      if (desired.has(entry.uuid) && [...entries.values()].some(item => item.active)) park(entry)
      else dispose(entry)
    }
  }, IDLE_TTL_MS)
  const idle = [...entries.values()].filter(item => !item.active)
  // React releases the outgoing clip before acquiring the incoming one.
  // During that handoff all four window entries can briefly be idle; do
  // not evict the buffered incoming HQ just before it is adopted.
  const limit = [...entries.values()].some(item => item.active) ? MAX_IDLE : MAX_IDLE + 1
  while (idle.length > limit) dispose(idle.shift()!)
}
function create(uuid: string): Entry {
  const video = document.createElement('video')
  video.preload = 'metadata'
  video.playsInline = true
  video.muted = true
  const entry: Entry = { uuid, video, active: false, timer: null }
  entries.set(uuid, entry)
  return entry
}

export function acquirePlaybackVideo(uuid: string): HTMLVideoElement {
  const previous = entries.get(uuid)
  if (previous?.video.error) dispose(previous)
  const entry = entries.get(uuid) ?? create(uuid)
  if (entry.timer) clearTimeout(entry.timer)
  entry.timer = null
  entry.active = true
  entry.video.preload = 'auto'
  return entry.video
}
/**
 * The active clip handed its slot to a prepared element (background quality
 * swap): the new element becomes the clip's pooled video and the replaced
 * one is fully released (no second decoder kept parked).
 */
export function adoptPlaybackVideo(uuid: string, previous: HTMLVideoElement, next: HTMLVideoElement) {
  const entry = entries.get(uuid)
  if (!entry || entry.video !== previous) {
    releaseDetached(previous)
    return
  }
  releaseDetached(previous)
  entry.video = next
  entry.active = true
}

/** Stop a media element and abort its transfer (presigned or not). */
export function releaseDetached(video: HTMLVideoElement) {
  video.pause()
  video.removeAttribute('src')
  video.load()
}

export function releasePlaybackVideo(uuid: string, video: HTMLVideoElement) {
  const entry = entries.get(uuid)
  if (!entry || entry.video !== video) return
  if (desired.has(uuid)) park(entry)
  else dispose(entry)
}

// Speculative work waits for the clip on screen: the single backend worker
// answers in arrival order, so neighbor status/grant lookups queued ahead of
// the visible clip's own requests delayed its first frame by seconds.
export const WARMUP_HOLD_MS = 2500
type WarmupHold = { promise: Promise<void>; resolve: () => void; owner: symbol; timer: ReturnType<typeof setTimeout> | undefined }
let warmupHold: WarmupHold | null = null

function endHold(hold: WarmupHold) {
  clearTimeout(hold.timer)
  if (warmupHold === hold) warmupHold = null
  hold.resolve()
}

/**
 * The visible clip is starting: hold neighbor warming (bounded). Returns a
 * release bound to THIS caller: a newer clip takes ownership of the hold, so
 * the previous clip's late cleanup can never release the newer clip's hold.
 */
export function holdWarmup(): () => void {
  const owner = Symbol('warmup')
  if (!warmupHold) {
    let resolve!: () => void
    const promise = new Promise<void>(done => { resolve = done })
    warmupHold = { promise, resolve, owner, timer: undefined }
  }
  const hold = warmupHold
  clearTimeout(hold.timer)
  hold.owner = owner
  hold.timer = setTimeout(() => endHold(hold), WARMUP_HOLD_MS)
  return () => {
    if (warmupHold === hold && hold.owner === owner) endHold(hold)
  }
}

/**
 * Resolve once no clip holds warming. A hold can end and a new one start in
 * the same commit (clip change): waiting warmers re-check before going on.
 */
async function waitForWarmup() {
  while (warmupHold) await warmupHold.promise
}

/** Sign-out/reset: end any hold regardless of owner. */
export function releaseWarmup() {
  if (warmupHold) endHold(warmupHold)
}

export function warmPlaybackVideo(uuid: string) {
  if (!uuid || !canPrefetch()) return
  const epoch = generation
  // A neighbor that can start on its durable Light by role needs no status
  // lookup at all: warm exactly the URL the player will start on.
  void waitForWarmup().then(() => getPreview(uuid)).then(async tile => {
    const start = autoStartUrl(uuid, tile.startRole, tile.startLightVersion)
    if (start) return { ...tile, playbackUrl: start, previewPlaybackUrl: null, playbackResolved: true }
    return getPreviewForPlayback(uuid)
  }).then(preview => {
    if (epoch !== generation || !desired.has(uuid) || !preview.playbackUrl || !preview.playbackResolved) return
    const entry = entries.get(uuid) ?? create(uuid)
    if (entry.active) return
    // Ready previews are small; anticipate bytes as well as metadata.
    // Originals retain conservative metadata-only preloading.
    entry.video.preload = preview.previewPlaybackUrl === preview.playbackUrl || preview.playbackUrl.includes('/play/light') ? 'auto' : 'metadata'
    if (entry.video.getAttribute('src') !== preview.playbackUrl) {
      entry.video.src = preview.playbackUrl
    }
    if (entry.timer) clearTimeout(entry.timer)
    park(entry)
  })
}

/** A bounded window, shared by Library intent and the open viewer. */
export function preparePlaybackWindow(uuids: string[]) {
  desired = new Set(uuids.filter(Boolean).slice(0, MAX_IDLE + 1))
  for (const entry of [...entries.values()]) {
    if (!entry.active && !desired.has(entry.uuid)) dispose(entry)
  }
  // At most three speculative decoders; the selected clip owns the fourth.
  let count = 0
  for (const uuid of desired) {
    if (entries.get(uuid)?.active) continue
    if (++count > MAX_IDLE) break
    warmPlaybackVideo(uuid)
  }
}
export function resetPreparedPlayback() {
  generation++
  releaseWarmup()
  for (const listener of [...resetListeners]) listener()
  desired.clear()
  for (const entry of [...entries.values()]) dispose(entry)
}

/** Prepare a likely first open, without stealing the viewer's live window. */
export function prepareLibraryPlayback(uuid: string, intent = false) {
  if (!uuid || [...entries.values()].some(entry => entry.active)) return
  if (!intent && desired.size >= 2) return
  preparePlaybackWindow([uuid, ...[...desired].filter(item => item !== uuid)].slice(0, 3))
}

