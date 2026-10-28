import type { SessionVideoInfo } from '../../services/sessionVideosApi'

/** MIME + RFC 6381 codec of the stored original (video track only). */
export function videoContentType(info: Pick<SessionVideoInfo, 'codec_string'>): string | null {
  return info.codec_string ? `video/mp4; codecs="${info.codec_string}"` : null
}

type Capabilities = { decodingInfo?: (config: MediaDecodingConfiguration) => Promise<{ supported: boolean }> }

/**
 * Can this device decode the original? MediaCapabilities when present, else
 * canPlayType. Unknown codec → true: the runtime frame check decides.
 */
export async function canDecode(
  info: SessionVideoInfo,
  capabilities: Capabilities | undefined = (typeof navigator !== 'undefined' ? navigator.mediaCapabilities : undefined),
  probe: () => HTMLVideoElement = () => document.createElement('video'),
): Promise<boolean> {
  const contentType = videoContentType(info)
  if (!contentType) return true
  if (capabilities?.decodingInfo && info.width && info.height) {
    try {
      const result = await capabilities.decodingInfo({
        type: 'file',
        video: { contentType, width: info.width, height: info.height, bitrate: info.bit_rate || 10_000_000, framerate: info.fps || 30 },
      })
      return result.supported
    } catch { /* Fall back to canPlayType. */ }
  }
  try { return probe().canPlayType(contentType) !== '' } catch { return true }
}

/**
 * Frames actually rendered once playback has advanced? Chrome may play the
 * audio of an undecodable video over a black frame.
 */
export function framesRendered(video: HTMLVideoElement): boolean {
  if (video.videoWidth === 0) return false
  const quality = typeof video.getVideoPlaybackQuality === 'function' ? video.getVideoPlaybackQuality() : null
  const frames = quality?.totalVideoFrames ?? (video as unknown as { webkitDecodedFrameCount?: number }).webkitDecodedFrameCount
  return frames === undefined || frames > 0
}
