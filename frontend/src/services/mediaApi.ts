export type MediaRendition = 'poster' | 'proxy_360p' | 'proxy_720p'

export type DerivativeRole = 'hq' | 'light' | 'poster'

export type DerivativeRoleStatus = {
  state: string
  playback_url?: string | null
  revision_id?: number | null
  aliased_to?: string | null
}

export type DerivativeStatusBlock = {
  source_revision_id?: number | null
  transform_version?: string | null
  start?: string | null
  recommended?: string | null
  hq: DerivativeRoleStatus
  light: DerivativeRoleStatus
  poster: DerivativeRoleStatus
}

export type MediaStatus = {
  video_uuid: string
  status: string
  can_request: boolean
  preferred_rendition?: string | null
  available_renditions: string[]
  playback_url?: string | null
  poster_url?: string | null
  full_quality_url?: string | null
  preview_url?: string | null
  derivatives?: DerivativeStatusBlock | null
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

/** Ready durable-derivative playback URL for one role (D5 read contract).

Only a `ready` role (distinct bytes or an honest small-source HQ alias)
resolves: every other ledger state reports no URL and the player keeps
its legacy fallback. Never invents a URL. */
export function getDerivativePlaybackUrl(status: MediaStatus, role: DerivativeRole): string | null {
  const entry = status.derivatives?.[role]
  if (!entry || entry.state !== 'ready' || !entry.playback_url) return null
  return entry.playback_url
}

/** Ready durable-derivative poster URL, or null (legacy poster stays). */
export function getDerivativePosterUrl(status: MediaStatus): string | null {
  return getDerivativePlaybackUrl(status, 'poster')
}

/** Ordered explicit quality choices: starter light, HQ, camera original.

Only proven URLs are listed, so the player toggle never offers a choice
it cannot play. With a ready light the starter is light; with no light
but a ready HQ the starter is HQ and the legacy preview stays out (it is
not a current proof). HQ may honestly alias light for small sources
(same bytes, no upscale); the label stays HQ. */
export function getQualityChoices(status: MediaStatus): Array<{ key: string; label: string; url: string }> {
  const choices: Array<{ key: string; label: string; url: string }> = []
  const light = getDerivativePlaybackUrl(status, 'light')
  const hq = getDerivativePlaybackUrl(status, 'hq')
  const preview = getPreviewPlaybackUrl(status)
  if (light) {
    choices.push({ key: 'light', label: 'Light', url: light })
  } else if (hq) {
    choices.push({ key: 'hq', label: 'HQ', url: hq })
  } else if (preview) {
    choices.push({ key: 'preview', label: 'Preview', url: preview })
  }
  if (light && hq && hq !== light) {
    choices.push({ key: 'hq', label: 'HQ', url: hq })
  }
  const original = getOriginalPlaybackUrl(status)
  if (original && !choices.some(choice => choice.url === original)) {
    choices.push({ key: 'original', label: 'Original', url: original })
  }
  const playback = status.playback_url
  if (playback && !choices.some(choice => choice.url === playback)) {
    choices.push({ key: 'playback', label: 'Playback', url: playback })
  }
  return choices
}
/** Ready browser previews avoid large/HDR camera originals on startup. */
export function getPreviewPlaybackUrl(status: MediaStatus): string | null {
  return status.preview_url
    || status.cache_entries?.find(entry => entry.rendition === 'proxy_720p' && entry.playback_url)?.playback_url
    || status.cache_entries?.find(entry => entry.rendition === 'proxy_360p' && entry.playback_url)?.playback_url
    || null
}

export function getOriginalPlaybackUrl(status: MediaStatus): string | null {
  const previews = [status.preview_url, ...status.cache_entries?.filter(entry => entry.rendition.startsWith('proxy_')).map(entry => entry.playback_url) || []]
  return status.full_quality_url
    || status.cache_entries?.find(entry => entry.rendition === 'original' && entry.playback_url)?.playback_url
    || (!previews.includes(status.playback_url) ? status.playback_url : null)
    || null
}

export function getPlaybackUrlFromStatus(status: MediaStatus, _preferInstantHq = false): string | null {
  // Durable-first starter: ready light (fast first frame), else ready HQ
  // (HQ-only clips have no light proof), else the legacy preview chain,
  // else the camera original. With no derivatives block this is exactly
  // the legacy preview-first order.
  return (
    getDerivativePlaybackUrl(status, 'light')
    || getDerivativePlaybackUrl(status, 'hq')
    || getPreviewPlaybackUrl(status)
    || getOriginalPlaybackUrl(status)
    || status.playback_url
    || null
  )
}

export function getPosterUrlFromStatus(status: MediaStatus): string | null {
  return status.poster_url || null
}
