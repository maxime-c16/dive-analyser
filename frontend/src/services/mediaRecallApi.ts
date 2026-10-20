import { requestMedia } from './mediaApi'

export type MediaAgentStatus = {
  agent_id: string
  hostname: string
  active: boolean
  leasing_enabled: boolean
  capabilities: string[]
  photos_access_status: 'ok' | 'permission_required' | 'denied' | 'query_timeout' | 'library_unavailable' | 'sync_incomplete' | 'unknown'
  last_successful_photos_query_at?: string | null
  last_permission_error_at?: string | null
  last_query_timeout_at?: string | null
  internal_free_bytes?: number | null
  vault_volume_uuid?: string | null
  vault_free_bytes?: number | null
  vault_mounted: boolean
  last_seen_at?: string | null
  storage_status?: StorageStatus | null
}

export type StorageStatus = {
  internal: { free_bytes: number; projected_free_bytes: number; warning: boolean; historical_recall_paused: boolean; automatic_recall_paused: boolean; processing_stopped: boolean }
  managed_sources: { total_bytes: number; quota_bytes: number; quota_exceeded: boolean; permanent_bytes: number; recent_bytes: number; temporary_bytes: number; diagnostic_bytes: number; quarantine_bytes: number }
}

export type RecallItem = {
  video_uuid: string
  canonical_video_uuid: string
  agent_local_uuid?: string | null
  dive_id: number
  dive_code: string
  date: string
  caption?: string | null
  diver?: string | null
  height?: string | null
  role?: 'low' | 'median' | 'high' | null
  priority: number
  priority_class: string
  reason: string
  media_readiness: { poster: string; proxy_720p?: string; proxy_360p: string; proxy?: string }
  source_readiness: string
  known_failure_history: string[]
  estimated_source_bytes?: number | null
  estimated_peak_bytes: number
  expected_retention_class: string
  storage_gate: Record<string, boolean | number>
}

export type RecallBatchPlan = { dry_run: true; priority: string; items: RecallItem[]; estimated_temporary_peak_bytes: number; current_free_bytes: number; projected_free_bytes: number; quota_result: string; blocked_items: string[]; jobs_created: 0; recalls_created: 0 }

export type CatalogRun = {
  id: number; agent_id: string; status: string; catalog_revision: number; checkpoint: number
  observed_count: number; eligible_count: number; excluded_count: number; error_count: number
  photos_library_bytes_start?: number | null; photos_library_bytes_end?: number | null
  free_bytes_start?: number | null; free_bytes_end?: number | null; pause_reason?: string | null
  last_error?: string | null; started_at?: string | null; completed_at?: string | null; created_at: string
}

export type CatalogSummary = {
  catalog_revision?: number | null; total: number; eligibility: Record<string, number>
  media: Record<string, number>; poster: Record<string, number>; proxy_720p?: Record<string, number>; proxy_360p: Record<string, number>; proxy?: Record<string, number>
  exclusions: Record<string, number>; photos_local_state: Record<string, number>; read_only?: boolean
}

export type CatalogPopulationPlan = {
  dry_run: true; total_eligible_assets: number; already_fully_ready: number; poster_only: number
  fully_missing: number; retryable: number; priority_counts: Record<string, number>
  estimated_mac_rolling_peak_bytes: number; estimated_debian_cache_growth_bytes: number
  current_free_bytes: number; projected_free_bytes_at_peak: number; blocked_reasons: string[]
  execution_allowed: boolean; jobs_created: 0; recalls_created: 0; source_files_created: 0
}

export async function getMediaAgents(): Promise<MediaAgentStatus[]> {
  const response = await fetch('/api/v1/media/agents')
  if (!response.ok) throw new Error(`media agents failed: ${response.status}`)
  return (await response.json()).agents
}

export async function getRecallManifest(limit = 25): Promise<RecallItem[]> {
  const response = await fetch(`/api/v1/media/recall-manifest?limit=${limit}`)
  if (!response.ok) throw new Error(`recall manifest failed: ${response.status}`)
  return (await response.json()).items
}

export async function recallOne(item: RecallItem) {
  return requestMedia(item.video_uuid, 'poster')
}

export async function planRecallBatch(priority = 'zero_ready_typical', limit = 6): Promise<RecallBatchPlan> {
  const response = await fetch('/api/v1/media/recall-batches/plan', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ priority, limit, dry_run: true }),
  })
  if (!response.ok) throw new Error(`recall plan failed: ${response.status}`)
  return response.json()
}

export async function getLatestCatalogRun(): Promise<CatalogRun | null> {
  const response = await fetch('/api/v1/media/catalog/runs/latest')
  if (!response.ok) throw new Error(`catalog run failed: ${response.status}`)
  return response.json()
}

export async function getCatalogSummary(): Promise<CatalogSummary> {
  const response = await fetch('/api/v1/media/catalog/summary')
  if (!response.ok) throw new Error(`catalog summary failed: ${response.status}`)
  return response.json()
}

export async function startCatalog(): Promise<CatalogRun> {
  const response = await fetch('/api/v1/media/catalog/runs', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ agent_id: 'mac-media-01' }),
  })
  if (!response.ok) throw new Error(`catalog start failed: ${response.status}`)
  return response.json()
}

export async function planCatalogPopulation(): Promise<CatalogPopulationPlan> {
  const response = await fetch('/api/v1/media/catalog/population-plan', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scope: 'all_eligible_captioned', dry_run: true }),
  })
  if (!response.ok) throw new Error(`catalog population plan failed: ${response.status}`)
  return response.json()
}
