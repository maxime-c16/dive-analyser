export type RepresentativeRole = 'low' | 'median' | 'high'
export type RepresentativeState =
  | 'ready'
  | 'partial'
  | 'missing'
  | 'unavailable'
  | 'replacement_available'
  | 'replacement_exhausted'

export type RepresentativeAttempt = {
  id: number
  dive_code: string
  video_uuid: string
  dive_datetime: string
  performance: string
  score_10: number
  height: string
  platform_type: string
  position: string | null
  is_sync: boolean
  modifiers: string[]
  diver: { id: number; display_name: string } | null
}

export type RepresentativeCard = {
  role: RepresentativeRole
  label: string
  selection: { id: number | null; version: number; reason: string }
  attempt: RepresentativeAttempt
  media: {
    state: RepresentativeState
    poster_url: string | null
    playback_url: string | null
    renditions: Record<string, {
      status: string
      entry_id: number | null
      playback_url: string | null
      size_bytes: number | null
      failure?: { code: string; message: string; detail: string; retryable: boolean } | null
    }>
    failure?: { code: string; message: string; detail: string; retryable: boolean } | null
  }
  replacement: { available: boolean; candidate_count: number; state: string }
  note: string
}

export type RepresentativeGallery = {
  summary: {
    canonical_dive_codes: number
    representatives: number
    ready: number
    partial: number
    missing: number
    unavailable: number
    replacement_available: number
    replacement_exhausted: number
    codes_fully_ready: number
    codes_partially_ready: number
    codes_zero_ready: number
    poster_ready: number
    proxy_ready: number
  }
  dives: Array<{
    dive_code: string
    coverage: {
      poster_ready: number
      proxy_ready: number
      total: number
      poster: number
      proxy_360p: number
      fully_ready: boolean
    }
    representatives: RepresentativeCard[]
  }>
}

export type RepresentativeCoverage = {
  summary: {
    codes: { total: number; fully_ready: number; partially_ready: number; zero_ready: number }
    representatives: {
      total: number
      ready: number
      partial: number
      missing: number
      replacement_available: number
      replacement_exhausted: number
    }
    renditions: { poster_ready: number; proxy_ready: number }
    zero_ready_categories: Record<string, number>
    failure_breakdown: Record<string, number>
  }
  zero_ready_codes: Array<{
    dive_code: string
    category: 'A' | 'B' | 'C' | 'D'
    attempts: number
    valid_photos_uuids: number
    candidates_never_attempted: number
    known_placeholder_failures: number
    replacement_candidates: number
    viable_replacement_candidates: number
    score_band_coverage: string[]
    media_viability: Record<string, number>
  }>
  read_only: boolean
}

export type MacMediaStatus = {
  photos_access_status: 'ok' | 'permission_required' | 'denied' | 'unknown'
  last_successful_media_job_at: string | null
  last_permission_error_at: string | null
  last_materialization_success_at: string | null
  last_error_code: string | null
  last_error_at: string | null
  generated_at: string
  source: string
}

export type ReplacementCandidate = {
  candidate: RepresentativeAttempt
  similarity: {
    height_match: boolean
    diver_match: boolean
    sync_match: boolean
    modifier_match: boolean
    performance_match: boolean
    score_distance: number
  }
  ready_renditions: string[]
  score_band: RepresentativeRole
  reason: string
  materialization_history: {
    successful: boolean
    attempt_count: number
    last_error_code: string | null
  }
  media_viability:
    | 'ready'
    | 'previously_successful'
    | 'untested'
    | 'retryable_failure'
    | 'known_placeholder_failure'
    | 'permanently_unavailable'
}

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    throw new Error(payload?.detail || `Request failed (${response.status})`)
  }
  return response.json()
}

export function getRepresentatives(params = new URLSearchParams()): Promise<RepresentativeGallery> {
  const query = params.toString()
  return json(`/api/v1/media/representatives${query ? `?${query}` : ''}`)
}

export function getRepresentativeCoverage(params = new URLSearchParams()): Promise<RepresentativeCoverage> {
  const query = params.toString()
  return json(`/api/v1/media/representatives/coverage${query ? `?${query}` : ''}`)
}

export function getMacMediaStatus(): Promise<MacMediaStatus> {
  return json('/api/v1/media/mac/status')
}

export function getReplacementCandidates(diveCode: string, role: RepresentativeRole, params = new URLSearchParams()): Promise<{ dive_code: string; role: RepresentativeRole; candidates: ReplacementCandidate[] }> {
  const scoped = new URLSearchParams()
  const diverScope = params.get('diver_scope')
  const diverId = params.get('diver_id')
  if (diverScope) scoped.set('diver_scope', diverScope)
  if (diverId) scoped.set('diver_id', diverId)
  const query = scoped.toString()
  return json(`/api/v1/media/representatives/${encodeURIComponent(diveCode)}/${role}/replacement-candidates${query ? `?${query}` : ''}`)
}

export function replaceRepresentative(
  diveCode: string,
  role: RepresentativeRole,
  replacementDiveId: number,
  prepare = false,
  params = new URLSearchParams(),
): Promise<{ selection_id: number; jobs: Array<{ id: number; rendition: string; created: boolean; status: string }> }> {
  const diverScope = params.get('diver_scope') || 'self'
  const diverId = params.get('diver_id')
  return json(`/api/v1/media/representatives/${encodeURIComponent(diveCode)}/${role}/replace`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      replacement_dive_id: replacementDiveId,
      prepare,
      renditions: ['poster', 'proxy_360p'],
      diver_scope: diverId ? 'selected' : diverScope,
      diver_id: diverId ? Number(diverId) : null,
    }),
  })
}
