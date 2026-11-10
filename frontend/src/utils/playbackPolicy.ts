/**
 * Shared clip-playback policy: which rendition starts, when HQ is worth
 * fetching, and the viewer's quality preference for this tab.
 *
 * Renditions (measured on a 60 fps pool clip): proxy ~1.1 Mbps, durable
 * Light 2.7 Mbps (v2 recipe; 6.4 Mbps for v1 packages), HQ ~12.9 Mbps.
 */

export type QualityPreference = 'auto' | 'preview' | 'light' | 'hq' | 'original'
export type PlaybackRole = 'light' | 'hq'

/** Nominal bitrates (Mbps) used to turn buffering speed into throughput. */
export const NOMINAL_MBPS: Record<'preview' | 'preview360' | 'light' | 'hq' | 'original', number> = {
  preview: 1.1,
  preview360: 0.25,
  light: 4.5,
  hq: 12.9,
  original: 18,
}
/** HQ is fetched only with this much headroom over its bitrate. */
export const HQ_REQUIRED_MBPS = NOMINAL_MBPS.hq * 1.5
/** Below this, playback starts on the small proxy instead of Light. */
export const WEAK_NETWORK_MBPS = 3

let preference: QualityPreference = 'auto'
let estimateMbps: number | null = null
const estimateListeners = new Set<() => void>()

/**
 * Re-evaluate on every new speed sample, whatever measured it (the visible
 * clip, a neighbor's background download, a proxy transfer). Returns an
 * unsubscribe.
 */
export function subscribeThroughput(listener: () => void): () => void {
  estimateListeners.add(listener)
  return () => { estimateListeners.delete(listener) }
}

export function getQualityPreference(): QualityPreference {
  return preference
}

/** A manual choice sticks for the rest of the tab; 'auto' hands control back. */
export function setQualityPreference(next: QualityPreference) {
  preference = next
}

export function roleUrl(videoUuid: string, role: PlaybackRole): string {
  return `/api/v1/media/${encodeURIComponent(videoUuid)}/play/${role}`
}

export function roleOfUrl(url: string | null | undefined): PlaybackRole | null {
  const match = url ? /\/api\/v1\/media\/[^/]+\/play\/(light|hq)$/.exec(url) : null
  return match ? (match[1] as PlaybackRole) : null
}

type NetworkInformationLike = { saveData?: boolean; effectiveType?: string; downlink?: number }

function connection(): NetworkInformationLike | undefined {
  return (navigator as Navigator & { connection?: NetworkInformationLike }).connection
}

/**
 * One throughput sample in Mbps. Transfers that finish implausibly fast
 * (cache hits) are discarded by the caller; samples are capped so one burst
 * cannot unlock HQ on its own.
 */
export function recordThroughput(mbps: number) {
  if (!Number.isFinite(mbps) || mbps <= 0) return
  const sample = Math.min(mbps, 100)
  estimateMbps = estimateMbps === null ? sample : estimateMbps * 0.6 + sample * 0.4
  for (const listener of [...estimateListeners]) listener()
}

export function throughputEstimate(): number | null {
  return estimateMbps
}

/** The browser's own downlink estimate (Chrome caps it at 10 Mbps), if any. */
function downlinkHint(): number | null {
  const downlink = connection()?.downlink
  return typeof downlink === 'number' && downlink > 0 ? downlink : null
}

/**
 * Measure a media element's real buffering: media seconds buffered per wall
 * second, times the rendition's bitrate, sampled once when the file is fully
 * buffered or after 4 s. Fills faster than 0.3 s are cache hits, not network.
 * Returns a cleanup.
 */
export function sampleBuffering(video: HTMLVideoElement, mbps: number): () => void {
  let started = performance.now()
  let sampled = false
  const onLoadStart = () => { started = performance.now(); sampled = false }
  const onProgress = () => {
    if (sampled || !Number.isFinite(video.duration) || video.duration <= 0 || !video.buffered?.length) return
    const end = video.buffered.end(video.buffered.length - 1)
    const wall = (performance.now() - started) / 1000
    if (end < video.duration - 0.25 && wall < 4) return
    sampled = true
    if (wall < 0.3) return
    recordThroughput((end / wall) * mbps)
  }
  video.addEventListener('loadstart', onLoadStart)
  video.addEventListener('progress', onProgress)
  return () => {
    video.removeEventListener('loadstart', onLoadStart)
    video.removeEventListener('progress', onProgress)
  }
}

/**
 * A finished same-origin media download (proxy video, poster): exact bytes
 * over body-transfer time. Cache hits (no transferred bytes) and small files
 * (dominated by latency) are not network samples.
 */
export function recordResourceTiming(entry: Pick<PerformanceResourceTiming, 'name' | 'transferSize' | 'encodedBodySize' | 'responseStart' | 'responseEnd'>) {
  if (!/\/api\/v1\/media\/cache\/\d+\/play/.test(entry.name)) return false
  const seconds = (entry.responseEnd - entry.responseStart) / 1000
  if (!entry.transferSize || entry.encodedBodySize < 200_000 || seconds < 0.05) return false
  recordThroughput((entry.encodedBodySize * 8) / seconds / 1e6)
  return true
}

let resourceObserver: PerformanceObserver | null = null
/** Feed same-origin media downloads into the estimate (once per page). */
export function observeMediaTransfers() {
  if (resourceObserver || typeof PerformanceObserver === 'undefined') return
  try {
    resourceObserver = new PerformanceObserver(list => {
      for (const entry of list.getEntries() as PerformanceResourceTiming[]) recordResourceTiming(entry)
    })
    resourceObserver.observe({ type: 'resource', buffered: true })
  } catch {
    resourceObserver = null
  }
}

export function networkIsWeak(): boolean {
  const info = connection()
  if (info?.saveData) return true
  if (info?.effectiveType && ['slow-2g', '2g', '3g'].includes(info.effectiveType)) return true
  return estimateMbps !== null && estimateMbps < WEAK_NETWORK_MBPS
}

/** Light bitrate of a package version: v1 was uncapped (6.4 Mbps measured). */
export function lightMbpsForVersion(version: string | null | undefined): number {
  return version === 'ffmpeg-h264-web-v1' || !version ? 6.4 : 2.7
}

/**
 * Whether Auto may START on a rendition of this bitrate. With a measured
 * (or browser-reported) speed, require 1.5× headroom. Without any, only the
 * capped Light is a safe blind start; an uncapped v1 Light starts on the
 * proxy until the network is known.
 */
export function canStartOn(mbps: number): boolean {
  const info = connection()
  if (info?.saveData) return false
  if (info?.effectiveType && ['slow-2g', '2g', '3g'].includes(info.effectiveType)) return false
  const known = estimateMbps ?? downlinkHint()
  if (known === null) return mbps <= 3
  return known >= mbps * 1.5
}

/** Devices where a second (HQ) decoder is not worth the memory. */
export function constrainedDevice(): boolean {
  const memory = (navigator as Navigator & { deviceMemory?: number }).deviceMemory
  return Boolean(connection()?.saveData) || (typeof memory === 'number' && memory <= 2)
}

/** Auto may prepare a rendition in the background only with measured headroom. */
export function canAffordRate(mbps: number): boolean {
  const known = estimateMbps ?? downlinkHint()
  return preference === 'auto' && !networkIsWeak() && !constrainedDevice()
    && known !== null && known >= mbps * 1.5
}

export function canAffordHq(): boolean {
  return canAffordRate(NOMINAL_MBPS.hq)
}

/**
 * The source a clip should start on before its status is known: the durable
 * Light by role when the library hinted it is ready and nothing argues
 * against it, else null (status-driven start, usually the small proxy).
 */
export function autoStartUrl(
  videoUuid: string,
  startRole: string | null | undefined,
  lightVersion?: string | null,
): string | null {
  if (!videoUuid || startRole !== 'light') return null
  if (preference !== 'auto' && preference !== 'light') return null
  if (preference === 'auto' && !canStartOn(lightMbpsForVersion(lightVersion))) return null
  return roleUrl(videoUuid, 'light')
}

/** Tests only. */
export function resetPlaybackPolicy() {
  preference = 'auto'
  estimateMbps = null
  estimateListeners.clear()
}
