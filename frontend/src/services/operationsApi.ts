export type OperationsStatus = {
  generated_at: string
  read_only: true
  application: { status: string; api_title: string; api_version: string; personal_dive_value_enabled: boolean }
  dependencies: { database: string; media_agents: string; active_media_jobs: number }
  agents: Array<{
    agent_id: string; hostname: string; active: boolean; leasing_enabled: boolean; capabilities: string[]
    photos_access_status: string; heartbeat_state: 'current' | 'stale' | 'never_seen'
    last_seen_at?: string | null; last_successful_photos_query_at?: string | null
    internal_free_bytes?: number | null
    storage_status?: { internal?: { free_bytes?: number; warning?: boolean; historical_recall_paused?: boolean; automatic_recall_paused?: boolean; processing_stopped?: boolean }; managed_sources?: { total_bytes?: number; quota_bytes?: number; quota_exceeded?: boolean; permanent_bytes?: number; recent_bytes?: number; temporary_bytes?: number; diagnostic_bytes?: number; quarantine_bytes?: number } } | null
  }>
  media: {
    cache: Array<{ rendition: string; status: string; count: number; bytes: number }>
    jobs_by_status: Record<string, number>
    jobs_by_rendition: Array<{ rendition: string; status: string; count: number }>
    active_jobs: Array<{ id: number; rendition: string; status: string; claimed_by?: string | null; progress: number; updated_at: string }>
  }
  catalog: {
    summary: { catalog_revision?: number | null; total: number; eligibility: Record<string, number>; media: Record<string, number> }
    latest_catalog_run: RunSummary | null
    latest_population_run: PopulationRunSummary | null
    latest_resolution_upgrade: UpgradeRunSummary | null
  }
  workflows: OperationalWorkflow[]
  representatives: {
    codes: { total: number; fully_ready: number; partially_ready: number; zero_ready: number }
    representatives: { total: number; ready: number; partial: number; missing: number; replacement_available: number; replacement_exhausted: number }
    renditions: { poster_ready: number; proxy_ready: number }
    zero_ready_categories: Record<string, number>
    failure_breakdown: Record<string, number>
  }
}

type RunSummary = { id: number; status: string; pause_reason?: string | null; last_error?: string | null; updated_at?: string | null }
type PopulationRunSummary = RunSummary & { stage: number; total_items: number; completed_items: number; ready_items: number; partial_items: number; unavailable_items: number; skipped_items: number }
type UpgradeRunSummary = RunSummary & { target_rendition: string; scope: string; total_items: number; completed_items: number; upgraded_items: number; failed_items: number; skipped_pinned_items: number }
export type OperationalWorkflow = { kind: string; label: string; id: number; status: string; target_rendition?: string | null; total_items: number; completed_items: number; ready_items: number; unavailable_items: number; skipped_items: number; pause_reason?: string | null; last_error?: string | null; updated_at?: string | null }

export async function getOperationsStatus(signal?: AbortSignal): Promise<OperationsStatus> {
  const response = await fetch('/api/v1/operations/status', { signal })
  if (!response.ok) throw new Error(`operations status failed: ${response.status}`)
  return response.json()
}
