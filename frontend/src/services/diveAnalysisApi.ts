import { takeIntentData, warmIntentData } from './intentCache'

export type ModifierMode = 'any' | 'all' | 'none'
export type Weighting = 'attempts' | 'sessions'
export type ContextDimension = 'modifier' | 'height' | 'position' | 'sync' | 'diver' | 'training_period'

export type DiveAnalysisFilters = {
  date_from?: string; date_to?: string; height?: string; platform_type?: string; position?: string
  modifiers?: string[]; modifier_mode?: ModifierMode; is_sync?: boolean; diver_scope?: 'self' | 'all' | 'selected'; diver_ids?: number[]
  performance?: string[]; session_id?: number; training_period_ids?: number[]
  success_threshold?: 'M' | 'G' | 'P'; weighting?: Weighting
}

export type Diver = { id: number; display_name: string; canonical_name: string; is_primary_user: boolean; active: boolean }
export type TrainingPeriod = { id: number; name: string; period_type: string; start_date: string; end_date: string; description?: string | null; active?: boolean }
export type AttemptMedia = { status: string; poster_url: string | null; playback_url: string | null; can_request: boolean; job_id: number | null; job_error: string | null }

export type DiveAttempt = {
  id: number; dive_code: string; dive_datetime: string; performance: string; performance_numeric: number
  phase1_performance: string | null; phase1_numeric: number | null; phase2_performance: string | null; phase2_numeric: number | null
  rolling_median: number | null; height: string; platform_type: string; position: string | null; is_sync: boolean
  modifiers: string[]; diver: { id: number; display_name: string; is_primary_user: boolean } | null
  legacy_person_name: string | null; session_id: number; official_dd: number | null; dd_reference: string | null; raw_caption: string | null; notes: string | null
  video_uuid: string | null; training_periods: Array<{ id: number; name: string; period_type: string }>; media: AttemptMedia
}

export type AnalysisSummary = {
  attempt_count: number; session_count: number; scored_attempt_count: number; unscored_attempt_count: number
  average: number | null; median: number | null; minimum: number | null; maximum: number | null
  standard_deviation: number | null; q1: number | null; q3: number | null; iqr: number | null
  success_rate: number | null; success_threshold: string; weighting_mode: string
  dd_defined_attempt_count: number; dd_coverage_rate: number | null; average_dd: number | null; median_dd: number | null; max_dd: number | null
  dd_reference: string
  best_attempt_id: number | null; worst_attempt_id: number | null; first_attempt_at: string | null; last_attempt_at: string | null
}

export type BreakdownRow = AnalysisSummary & { context: string; context_id: number | null; sample_label: 'no_data' | 'insufficient' | 'exploratory' | 'moderate_sample' | 'stronger_descriptive_sample' }
export type PhaseSeries = { available_count: number; missing_count: number; summary: Record<string, number | null>; previous_summary: Record<string, number | null>; distribution: Record<string, number>; points: Array<{ attempt_id: number; dive_datetime: string; score: number; rolling_median: number | null }> }

export type DiveAnalysis = {
  generated_at: string; analytics_version: string; dive_code: string; weighting_mode: string
  sample: Pick<AnalysisSummary, 'attempt_count' | 'session_count' | 'scored_attempt_count' | 'unscored_attempt_count' | 'first_attempt_at' | 'last_attempt_at'>
  summary: AnalysisSummary; trend: { direction: string; slope_per_30_days: number | null; confidence: string; reason: string | null }
  comparison: { current: AnalysisSummary; previous: AnalysisSummary | null; previous_range: { date_from: string; date_to: string } | null }
  breakdowns: Record<ContextDimension, BreakdownRow[]>
  phases: { total_attempts: number; phases: { phase1: PhaseSeries; phase2: PhaseSeries } }
  training_periods: TrainingPeriod[]
  insights: Array<{ type: string; tone: string; confidence: string; title: string; message: string; evidence: Record<string, unknown> }>
  attempts: DiveAttempt[]
  observability: { cache: 'hit' | 'miss'; query_ms: number; calculation_ms: number; total_ms: number; result_attempts: number }
}

export function serializeAnalysisFilters(filters: DiveAnalysisFilters): URLSearchParams {
  const params = new URLSearchParams()
  Object.entries(filters).forEach(([key, value]) => {
    if (value === undefined || value === '' || value === null) return
    if (Array.isArray(value)) value.forEach((item) => params.append(key, String(item)))
    else params.set(key, String(value))
  })
  return params
}

function analysisIntentKey(diveCode: string, filters: DiveAnalysisFilters): string {
  return JSON.stringify(['dive-analysis', diveCode.toUpperCase(), serializeAnalysisFilters(filters).toString()])
}

async function fetchAnalysis(diveCode: string, filters: DiveAnalysisFilters): Promise<DiveAnalysis> {
  const response = await fetch(`/api/v1/dive-analysis/${encodeURIComponent(diveCode.toUpperCase())}?${serializeAnalysisFilters(filters)}`)
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    const detail = payload?.detail
    throw new Error(typeof detail === 'string' ? detail : detail?.message || `Request failed (${response.status})`)
  }
  return response.json()
}

async function json<T>(url: string): Promise<T> {
  const response = await fetch(url)
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    const detail = payload?.detail
    throw new Error(typeof detail === 'string' ? detail : detail?.message || `Request failed (${response.status})`)
  }
  return response.json()
}

export function getDiveAnalysis(diveCode: string, filters: DiveAnalysisFilters): Promise<DiveAnalysis> {
  return takeIntentData(analysisIntentKey(diveCode, filters), () => fetchAnalysis(diveCode, filters))
}

export function warmDiveAnalysis(diveCode: string, filters: DiveAnalysisFilters): void {
  warmIntentData(analysisIntentKey(diveCode, filters), () => fetchAnalysis(diveCode, filters))
}

export function defaultAnalysisFilters(diverScope: 'self' | 'all' = 'self'): DiveAnalysisFilters {
  return { diver_scope: diverScope, modifier_mode: 'any', success_threshold: 'G', weighting: 'attempts' }
}
export function getDivers(): Promise<Diver[]> { return json('/api/v1/divers') }
export function getTrainingPeriods(): Promise<TrainingPeriod[]> { return json('/api/v1/training-periods') }
