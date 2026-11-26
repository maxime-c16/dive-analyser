import { api } from './api'

export type ClipTriageSessionCounts = {
  pending: number
  kept: number
  incomplete: number
  rejected: number
  total: number
  latest_detector: string | null
  latest_version: string | null
}

export type ClipTriageSessionSummary = {
  session_id: number
  date: string
  title: string | null
  pending: number
  incomplete: number
  extracting: number
  published: number
  rejected: number
}

export type ClipTriageSummary = {
  can_manage: boolean
  pending_count: number
  incomplete_count: number
  extracting_count: number
  published_count: number
  rejected_count: number
  sessions: ClipTriageSessionSummary[]
  sessions_total?: number
  sessions_has_more?: boolean
  sessions_next_offset?: number | null
}

export type TriageDiver = {
  id: number
  display_name: string
  is_own: boolean
  has_account: boolean
  suggested: boolean
}

export type ClipCandidate = {
  id: number
  session_video_id: number
  session_id: number | null
  session_date: string | null
  session_title: string | null
  video_filename: string
  video_duration_seconds: number | null
  video_codec_string: string | null
  video_audio_codec_string: string | null
  video_color_transfer: string | null
  video_play_url: string
  video_download_url: string
  video_poster_url: string
  start_s: number
  end_s: number
  trimmed_start_s: number | null
  trimmed_end_s: number | null
  effective_start_s: number
  effective_end_s: number
  duration_s: number
  confidence: number | null
  detector_label: string | null
  detector_name: string | null
  detector_version: string | null
  triage_status: 'pending' | 'kept' | 'rejected'
  reject_reason: string | null
  skipped_at: string | null
  diver_id: number | null
  diver_name: string | null
  dive_code: string | null
  height: string | null
  performance: string | null
  phase1_performance: string | null
  phase2_performance: string | null
  notes: string | null
  visibility: 'private' | 'public'
  metadata_complete: boolean
  publish_requested: boolean
  extraction_status: 'none' | 'queued' | 'claimed' | 'extracting' | 'ready' | 'published' | 'failed'
  extraction_error: string | null
  cut_revision: number
  dive_id: number | null
  published_at: string | null
  updated_at: string | null
}

export type ClipRunInfo = {
  id: number
  session_video_id: number
  detector_name: string
  detector_version: string
  submitted_count: number
  created_count: number
  deduped_count: number
  kept_matches: number
  rejected_matches: number
  pending_matches: number
  precision: number | null
  recall: number | null
  created_at: string
}

export type CandidatePatch = {
  triage_status?: 'pending' | 'kept' | 'rejected'
  reject_reason?: 'false_positive' | 'duplicate' | 'incomplete' | 'other'
  skip?: boolean
  confirm_publish?: boolean
  trimmed_start_s?: number | null
  trimmed_end_s?: number | null
  diver_id?: number | null
  dive_code?: string | null
  height?: string | null
  performance?: string | null
  phase1_performance?: string | null
  phase2_performance?: string | null
  notes?: string | null
  visibility?: 'private' | 'public'
}

export async function getClipTriageSummary(signal?: AbortSignal): Promise<ClipTriageSummary> {
  const { data } = await api.get<ClipTriageSummary>('/api/v1/clip-triage/summary', { signal })
  return data
}

export async function listClipTriageSessions(
  params: { q?: string; limit?: number; offset?: number },
  signal?: AbortSignal,
): Promise<{
  items: ClipTriageSessionSummary[]
  total: number
  has_more: boolean
  next_offset: number | null
}> {
  const clean: Record<string, string | number> = {}
  if (params.q && params.q.trim()) clean.q = params.q.trim()
  if (params.limit != null) clean.limit = params.limit
  if (params.offset != null) clean.offset = params.offset
  const { data } = await api.get('/api/v1/clip-triage/sessions', { params: clean, signal })
  return data
}

export async function listClipTriageCandidates(
  params: {
    tab?: 'pending' | 'incomplete' | 'recent' | 'all'
    session_id?: number | null
    session_video_id?: number | null
    limit?: number
    offset?: number
    exclude_ids?: number[]
    cursor?: string | null
  },
  signal?: AbortSignal,
): Promise<{
  items: ClipCandidate[]
  has_more: boolean
  next_offset: number | null
  next_cursor?: string | null
  divers: TriageDiver[]
  divers_total?: number
  divers_has_more?: boolean
}> {
  const clean: Record<string, string | number> = {}
  if (params.tab) clean.tab = params.tab
  if (params.session_id != null) clean.session_id = params.session_id
  if (params.session_video_id != null) clean.session_video_id = params.session_video_id
  if (params.limit != null) clean.limit = params.limit
  if (params.cursor) {
    clean.cursor = params.cursor
  } else {
    if (params.offset != null) clean.offset = params.offset
    if (params.exclude_ids && params.exclude_ids.length > 0) {
      clean.exclude_ids = params.exclude_ids.slice(0, 100).join(',')
    }
  }
  const { data } = await api.get('/api/v1/clip-triage/candidates', { params: clean, signal })
  return data
}

export async function listClipTriageDivers(
  params: {
    q?: string
    session_id?: number | null
    limit?: number
    offset?: number
  },
  signal?: AbortSignal,
): Promise<{
  items: TriageDiver[]
  total: number
  has_more: boolean
  next_offset: number | null
}> {
  const clean: Record<string, string | number> = {}
  if (params.q && params.q.trim()) clean.q = params.q.trim()
  if (params.session_id != null) clean.session_id = params.session_id
  if (params.limit != null) clean.limit = params.limit
  if (params.offset != null) clean.offset = params.offset
  const { data } = await api.get('/api/v1/clip-triage/divers', { params: clean, signal })
  return data
}

export async function getClipTriageCandidate(
  candidateId: number,
  signal?: AbortSignal,
): Promise<ClipCandidate> {
  const { data } = await api.get<ClipCandidate>(`/api/v1/clip-triage/candidates/${candidateId}`, { signal })
  return data
}

export async function patchClipCandidate(
  candidateId: number,
  patch: CandidatePatch,
): Promise<ClipCandidate> {
  const { data } = await api.patch<ClipCandidate>(`/api/v1/clip-triage/candidates/${candidateId}`, patch)
  return data
}

export async function retryClipExtraction(candidateId: number): Promise<ClipCandidate> {
  const { data } = await api.post<ClipCandidate>(`/api/v1/clip-triage/candidates/${candidateId}/retry-extraction`)
  return data
}

export async function getVideoClipRuns(
  videoId: number,
  signal?: AbortSignal,
): Promise<{ session_video_id: number; runs: ClipRunInfo[] }> {
  const { data } = await api.get(`/api/v1/session-videos/${videoId}/clip-runs`, { signal })
  return data
}

export async function downloadVideoGroundTruth(videoId: number, filename: string): Promise<void> {
  const base = (api.defaults.baseURL || '').replace(/\/+$/, '')
  const link = document.createElement('a')
  link.href = `${base}/api/v1/session-videos/${videoId}/clip-gt/export`
  link.download = `gt-${filename.replace(/\.[^.]+$/, '')}-v${videoId}.json`
  document.body.appendChild(link)
  link.click()
  link.remove()
}

export function formatClipTime(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const rem = s % 60
  return h > 0
    ? `${h}:${String(m).padStart(2, '0')}:${String(rem).padStart(2, '0')}`
    : `${String(m).padStart(2, '0')}:${String(rem).padStart(2, '0')}`
}
