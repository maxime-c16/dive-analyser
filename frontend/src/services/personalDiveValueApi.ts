export type PersonalValueComponent = {
  raw_value: number
  normalized_value: number
  weight: number
  weighted_contribution: number
  support?: number
  percentile?: number | null
  reason?: string | null
}

export type PersonalDiveValue = {
  version: string
  attempt_id: number
  value: number | null
  execution: { score: number; scale: string }
  difficulty: { official_dd: number | null; reference_dd: number; beta: number }
  components: Record<string, PersonalValueComponent>
  contextual_value?: number
  execution_guard?: number
  primary_signal: string | null
  confidence: { level: 'high' | 'medium' | 'low' | 'undefined'; same_dive_support: number; reasons: string[] }
  caveats: string[]
  history_cutoff: string
  calculated_at: string
}

export type HistoricalPattern = {
  attempt_id: number
  dive_code: string
  session_id: number
  dive_datetime: string
  height: string
  is_sync: boolean
  modifiers: string[]
  trailing_scores: number[]
  current_trailing_scores: number[]
  score_distance: number
  context_penalty: number
  similarity_distance: number
  evidence: string
}

type ApiError = Error & { status?: number; code?: string }

async function json<T>(url: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(url, { signal })
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    const detail = payload?.detail
    const error = new Error(typeof detail === 'string' ? detail : detail?.message || `Request failed (${response.status})`) as ApiError
    error.status = response.status
    error.code = detail?.code
    throw error
  }
  return response.json() as Promise<T>
}

export function getPersonalDiveValue(attemptId: number, signal?: AbortSignal) {
  return json<PersonalDiveValue>(`/api/v1/dives/${attemptId}/personal-value?version=v1`, signal)
}

export function getPersonalDiveValuePatterns(attemptId: number, signal?: AbortSignal) {
  return json<{ version: string; attempt_id: number; matches: HistoricalPattern[] }>(`/api/v1/dives/${attemptId}/personal-value/patterns?version=v1&limit=3`, signal)
}

export function getPersonalDiveValues(diveCode: string, limit = 250, signal?: AbortSignal) {
  return json<{ version: string; dive_code: string; values: PersonalDiveValue[] }>(`/api/v1/dive-analysis/${encodeURIComponent(diveCode)}/personal-values?version=v1&limit=${Math.min(250, Math.max(1, limit))}`, signal)
}

export function getRecentPersonalDiveValues(limit = 60, signal?: AbortSignal) {
  return json<{ version: string; values: Array<PersonalDiveValue & { dive_code: string; dive_datetime: string }> }>(`/api/v1/personal-dive-value/recent?version=v1&limit=${Math.min(100, Math.max(1, limit))}`, signal)
}
