export type MediaRendition = 'poster' | 'proxy_360p' | 'proxy_720p'

export type MediaStatus = {
  video_uuid: string
  status: string
  can_request: boolean
  preferred_rendition?: string | null
  available_renditions: string[]
  playback_url?: string | null
  poster_url?: string | null
  cache_entries?: Array<{
    id: number
    rendition: string
    playback_url?: string | null
  }>
  job?: {
    id: number
    status: string
    rendition: string
    progress?: number
    last_error?: string | null
  } | null
}

export type MediaRequestResult = MediaStatus & {
  media_key?: string
  created_job?: boolean
  reused_job?: boolean
  cache_hit?: boolean
}

export async function getMediaStatus(videoUuid: string): Promise<MediaStatus> {
  const response = await fetch(`/api/v1/media/${videoUuid}/status`)
  if (!response.ok) {
    throw new Error(`media status failed: ${response.status}`)
  }
  return response.json()
}

export async function requestMedia(
  videoUuid: string,
  rendition: MediaRendition,
): Promise<MediaRequestResult> {
  const response = await fetch(`/api/v1/media/${videoUuid}/request`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ rendition, reason: 'user_view' }),
  })
  if (!response.ok) {
    throw new Error(`media request failed: ${response.status}`)
  }
  return response.json()
}

/**
 * The source a player opens with. Never the 360p preview when an HQ source
 * exists: a ready 720p proxy (faststart, opens instantly) wins, otherwise the
 * status' own choice — the verified original, or the best cached rendition.
 * The 360p plays only when it is the sole source; the HQ poster covers the
 * original's start-up instead of a low-resolution first frame.
 */
export function getPlaybackUrlFromStatus(status: MediaStatus, preferInstantHq = false): string | null {
  if (preferInstantHq) {
    const hq = status.cache_entries?.find(item => item.rendition === 'proxy_720p' && item.playback_url)
    if (hq?.playback_url) return hq.playback_url
  }
  return status.playback_url || null
}

export function getPosterUrlFromStatus(status: MediaStatus): string | null {
  return status.poster_url || null
}
