import { api } from './api'

export type SessionVideoInfo = {
  id: number
  session_id: number | null
  filename: string
  recorded_at: string | null
  recorded_date: string | null
  duration_seconds: number | null
  size_bytes: number | null
  codec_string: string | null
  audio_codec_string: string | null
  video_codec: string | null
  color_transfer: string | null
  width: number | null
  height: number | null
  fps: number | null
  bit_rate: number | null
  poster_url?: string
  animated_url?: string
  hidden?: boolean
  can_share: boolean
}

export type SharedSessionVideo = SessionVideoInfo & SharedTrainingSession & {
  guest_id: number
  guest_name: string
  video_url: string
  download_url: string
}

export const sessionVideoPaths = (id: number) => ({
  play: `/api/v1/session-videos/${id}/play`,
  download: `/api/v1/session-videos/${id}/download`,
  report: `/api/v1/session-videos/${id}/playback-issues`,
  shares: `/api/v1/session-videos/${id}/shares`,
})

export async function listSessionVideos(): Promise<SessionVideoInfo[]> {
  const { data } = await api.get<{ items: SessionVideoInfo[] }>('/api/v1/session-videos')
  return data.items
}

export async function getSessionVideo(id: number): Promise<SessionVideoInfo> {
  const { data } = await api.get<SessionVideoInfo>(`/api/v1/session-videos/${id}`)
  return data
}

// StrictMode replays effects: share the in-flight exchange so one page load
// never installs two guest identities.
const pendingVisits = new Map<string, Promise<SharedSessionVideo>>()
export function visitSharedSession(shareId: string, token: string): Promise<SharedSessionVideo> {
  const key = `${shareId}#${token}`
  const existing = pendingVisits.get(key)
  if (existing) return existing
  const request = api.post<SharedSessionVideo>(`/api/v1/shared-dives/sessions/${shareId}/visit`, null, { headers: { 'X-Dive-Share': token } })
    .then(({ data }) => data)
    .finally(() => pendingVisits.delete(key))
  pendingVisits.set(key, request)
  return request
}

export function reportPlaybackIssue(url: string, reason: 'unsupported' | 'no_frames' | 'error'): void {
  api.post(url, { reason }).catch(() => { /* Counting is best-effort. */ })
}

export function formatBytes(bytes: number | null, locale: string): string {
  if (!bytes) return ''
  const fr = locale.startsWith('fr')
  const [value, unit] = bytes >= 1e9 ? [bytes / 1e9, fr ? 'Go' : 'GB'] : [bytes / 1e6, fr ? 'Mo' : 'MB']
  return `${new Intl.NumberFormat(locale, { maximumFractionDigits: value >= 10 ? 0 : 1 }).format(value)} ${unit}`
}

export function formatDuration(seconds: number | null): string {
  if (!seconds) return ''
  const minutes = Math.round(seconds / 60)
  return minutes >= 60 ? `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, '0')}` : `${minutes} min`
}

export function formatSessionDate(video: SessionVideoInfo, locale: string): string {
  const day = video.recorded_date ? new Date(`${video.recorded_date}T12:00:00`) : null
  return day ? new Intl.DateTimeFormat(locale, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }).format(day) : video.filename
}

export type SharedTrainingSession = {
  title?: string | null; can_manage?: boolean; session_id: number; date: string; videos: SessionVideoInfo[]; video_count: number;
  total_duration: number; total_bytes: number; has_more: boolean; next_video_id?: number | null
}
export async function getTrainingSession(id: number): Promise<SharedTrainingSession> {
  return (await api.get(`/api/v1/shared-sessions/${id}`)).data
}
export async function trainingSessions(before?: number): Promise<{items: SharedTrainingSession[]; next_cursor: number | null}> {
  return (await api.get('/api/v1/shared-sessions', {params: {before}})).data
}
