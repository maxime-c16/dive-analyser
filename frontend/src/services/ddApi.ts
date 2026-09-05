import { api } from './api'

export interface DDOverview {
  reference: { id: string; label: string; method: string; status: string }
  scope: 'self' | 'all' | 'selected_diver'
  summary: { attempt_count: number; defined_attempt_count: number; undefined_attempt_count: number; unique_dive_count: number; median_dd: number | null; max_dd: number | null; min_dd: number | null; legacy_mismatch_count: number }
  timeline: Array<{ month: string; attempt_count: number; median_dd: number; max_dd: number; min_dd: number }>
  height_breakdown: Array<{ height: string; attempt_count: number; median_dd: number; max_dd: number }>
  inventory: Array<{ dive_code: string; height: string; dd_value: number; attempt_count: number; first_attempt_at: string; last_attempt_at: string }>
  recent_attempts: Array<{ attempt_id: number; dive_code: string; height: string; dive_datetime: string; dd_value: number; stored_dd: number | null; is_sync: boolean; components: Record<string, number> }>
  undefined_reasons: Array<{ reason: string; attempt_count: number }>
}

export async function getDDOverview(scope: 'self' | 'all' = 'self') {
  const response = await api.get<DDOverview>('/api/v1/dd/overview', { params: { scope } })
  return response.data
}
