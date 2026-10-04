import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import MediaRecall from './MediaRecall'
import { getCatalogSummary, getLatestCatalogRun, getMediaAgents, getRecallManifest, planCatalogPopulation, planRecallBatch, recallOne, startCatalog } from '../services/mediaRecallApi'

vi.mock('../services/mediaRecallApi', () => ({ getMediaAgents: vi.fn(), getRecallManifest: vi.fn(), getLatestCatalogRun: vi.fn(), getCatalogSummary: vi.fn(), planCatalogPopulation: vi.fn(), startCatalog: vi.fn(), planRecallBatch: vi.fn(), recallOne: vi.fn() }))

describe('MediaRecall', () => {
  beforeEach(() => {
    vi.mocked(getMediaAgents).mockResolvedValue([{ agent_id: 'mac-media-01', hostname: 'mac-server.local', active: true, leasing_enabled: false, capabilities: ['poster', 'proxy_360p'], photos_access_status: 'permission_required', vault_mounted: true, internal_free_bytes: 50 * 1024 ** 3, storage_status: { internal: { free_bytes: 50 * 1024 ** 3, historical_recall_paused: false, automatic_recall_paused: false, processing_stopped: false }, managed_sources: { total_bytes: 0, quota_bytes: 20 * 1024 ** 3, permanent_bytes: 0, recent_bytes: 0 } } }] as any)
    vi.mocked(getRecallManifest).mockResolvedValue([{ video_uuid: 'uuid', dive_id: 1, dive_code: '103B', date: '2026-01-01T10:00:00', diver: 'Maxime', role: 'median', priority: 30, priority_class: 'representative_typical', reason: 'zero_or_partial_typical_representative', media_readiness: { poster: 'missing', proxy_360p: 'missing' }, source_readiness: 'missing', known_failure_history: [] }] as any)
    vi.mocked(getLatestCatalogRun).mockResolvedValue(null)
    vi.mocked(getCatalogSummary).mockResolvedValue({ catalog_revision: null, total: 0, eligibility: {}, media: {}, poster: {}, proxy_360p: {}, exclusions: {}, photos_local_state: {}, read_only: true })
  })

  it('loads status and bounded manifest without creating jobs', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch')
    render(<MemoryRouter><MediaRecall /></MemoryRouter>)
    expect((await screen.findAllByText('103B')).length).toBeGreaterThan(0)
    expect(screen.getByText(/Recall remains disabled while Photos access is permission_required/)).toBeInTheDocument()
    expect(recallOne).not.toHaveBeenCalled()
    expect(fetchSpy.mock.calls.filter(([, init]) => (init as RequestInit)?.method === 'POST')).toHaveLength(0)
    expect(screen.queryByText(/Prepare all/i)).not.toBeInTheDocument()
    expect(startCatalog).not.toHaveBeenCalled()
  })

  it('shows a storage-blocked dry-run population plan without creating media', async () => {
    vi.mocked(getCatalogSummary).mockResolvedValue({ catalog_revision: 1, total: 100, eligibility: { eligible: 80, excluded: 20 }, media: { ready: 10 }, poster: {}, proxy_360p: {}, exclusions: {}, photos_local_state: {} })
    vi.mocked(planCatalogPopulation).mockResolvedValue({ dry_run: true, total_eligible_assets: 80, already_fully_ready: 10, poster_only: 2, fully_missing: 68, retryable: 0, priority_counts: {}, estimated_mac_rolling_peak_bytes: 1_250_000_000, estimated_debian_cache_growth_bytes: 1_000_000, current_free_bytes: 31 * 1024 ** 3, projected_free_bytes_at_peak: 30 * 1024 ** 3, blocked_reasons: ['free_space_below_new_recall_gate'], execution_allowed: false, jobs_created: 0, recalls_created: 0, source_files_created: 0 })
    render(<MemoryRouter><MediaRecall /></MemoryRouter>)
    const button = await screen.findByRole('button', { name: 'Plan population' })
    button.click()
    expect(await screen.findByText(/Paused: free space below new recall gate/)).toBeInTheDocument()
    expect(recallOne).not.toHaveBeenCalled()
  })

  it('plans a bounded batch without passive work', async () => {
    vi.mocked(planRecallBatch).mockResolvedValue({ dry_run: true, priority: 'zero_ready_typical', items: [], estimated_temporary_peak_bytes: 0, current_free_bytes: 50, projected_free_bytes: 50, quota_result: 'ok', blocked_items: [], jobs_created: 0, recalls_created: 0 })
    render(<MemoryRouter><MediaRecall /></MemoryRouter>)
    const button = await screen.findByRole('button', { name: 'Plan bounded batch' })
    button.click()
    expect(await screen.findByText('Gate')).toBeInTheDocument()
    expect(recallOne).not.toHaveBeenCalled()
  })
})
