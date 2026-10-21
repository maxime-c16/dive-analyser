import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { is_admin: true, divers: [{ diver_id: 1, access_kind: 'OWNER' }] } }) }))

import RepresentativeMedia, { proxyDisplayStatus } from './RepresentativeMedia'
import { getMacMediaStatus, getRepresentativeCoverage, getReplacementCandidates, getRepresentatives, replaceRepresentative } from '../services/representativeMediaApi'

vi.mock('../services/representativeMediaApi', () => ({
  getRepresentatives: vi.fn(),
  getRepresentativeCoverage: vi.fn(),
  getMacMediaStatus: vi.fn(),
  getReplacementCandidates: vi.fn(),
  replaceRepresentative: vi.fn(async () => ({ selection_id: 1, jobs: [] })),
}))

const rep = (code: string, role: 'low' | 'median' | 'high', state = 'ready') => ({
  role,
  label: role === 'median' ? 'Typical' : role[0].toUpperCase() + role.slice(1),
  selection: { id: null, version: 1, reason: 'initial_manifest' },
  attempt: { id: role === 'low' ? 1 : role === 'median' ? 2 : role === 'high' ? 3 : 1, dive_code: code, video_uuid: `${code}-${role}`, dive_datetime: '2026-01-01T10:00:00', performance: role === 'low' ? 'B' : role === 'median' ? 'M' : 'G', score_10: role === 'low' ? 2 : role === 'median' ? 4.5 : 7, height: '1m', platform_type: 'springboard', position: code.slice(-1), is_sync: false, modifiers: [], diver: { id: 1, display_name: 'Maxime' } },
  media: { state, proxy_rendition: state === 'ready' ? 'proxy_720p' : null, poster_url: state === 'ready' ? '/poster.jpg' : null, playback_url: state === 'ready' ? '/proxy.mp4' : null, renditions: { poster: { status: state === 'ready' ? 'ready' : 'unavailable', entry_id: null, playback_url: null, size_bytes: null, failure: state === 'ready' ? null : { code: 'materialization_only_placeholders', message: 'Photos did not provide a usable video file for this attempt.', detail: 'The export contained only placeholder files.', retryable: false } }, proxy_720p: { status: state === 'ready' ? 'ready' : 'unavailable', entry_id: null, playback_url: null, size_bytes: null, failure: null }, proxy_360p: { status: state === 'ready' ? 'ready' : 'unavailable', entry_id: null, playback_url: null, size_bytes: null, failure: null } }, failure: state === 'ready' ? null : { code: 'materialization_only_placeholders', message: 'Photos did not provide a usable video file for this attempt.', detail: 'The export contained only placeholder files.', retryable: false } },
  replacement: { available: state !== 'ready', candidate_count: state === 'ready' ? 0 : 1, state: state === 'ready' ? 'exhausted' : 'available' },
  note: 'Selected from the recorded score distribution',
})

const payload = {
  summary: { canonical_dive_codes: 2, representatives: 6, ready: 3, partial: 0, missing: 0, unavailable: 3, replacement_available: 3, replacement_exhausted: 0, codes_fully_ready: 1, codes_partially_ready: 0, codes_zero_ready: 1, poster_ready: 3, proxy_ready: 3 },
  dives: [
    { dive_code: '103B', coverage: { poster_ready: 3, proxy_ready: 3, total: 3, poster: 1, proxy_360p: 1, fully_ready: true }, representatives: [rep('103B', 'low'), rep('103B', 'median'), rep('103B', 'high')] },
    { dive_code: '103C', coverage: { poster_ready: 0, proxy_ready: 0, total: 3, poster: 0, proxy_360p: 0, fully_ready: false }, representatives: [rep('103C', 'low', 'replacement_available'), rep('103C', 'median', 'replacement_available'), rep('103C', 'high', 'replacement_available')] },
  ],
}

const coveragePayload = {
  summary: {
    codes: { total: 2, fully_ready: 1, partially_ready: 0, zero_ready: 1 },
    representatives: { total: 6, ready: 3, partial: 0, missing: 0, replacement_available: 3, replacement_exhausted: 0 },
    renditions: { poster_ready: 3, proxy_ready: 3 },
    zero_ready_categories: { A: 1 },
    failure_breakdown: { materialization_only_placeholders: 3 },
  },
  zero_ready_codes: [{ dive_code: '103C', category: 'A', attempts: 3, valid_photos_uuids: 3, candidates_never_attempted: 1, known_placeholder_failures: 2, replacement_candidates: 1, viable_replacement_candidates: 1, score_band_coverage: ['low', 'median', 'high'], media_viability: { untested: 1 } }],
  read_only: true,
}

function renderPage() {
  return render(<MemoryRouter initialEntries={['/media/representatives']}><Routes><Route path="/media/representatives" element={<RepresentativeMedia />} /></Routes></MemoryRouter>)
}

describe('RepresentativeMedia', () => {
  beforeEach(() => {
    vi.mocked(getRepresentatives).mockResolvedValue(payload as any)
    vi.mocked(getRepresentativeCoverage).mockResolvedValue(coveragePayload as any)
    vi.mocked(getMacMediaStatus).mockResolvedValue({ photos_access_status: 'ok', last_successful_media_job_at: '2026-01-01T10:00:00', last_permission_error_at: null, last_materialization_success_at: '2026-01-01T10:00:00', last_error_code: null, last_error_at: null, generated_at: '2026-01-01T10:00:00', source: 'media_job_history' })
    vi.mocked(getReplacementCandidates).mockResolvedValue({ dive_code: '103C', role: 'median', candidates: [{ candidate: { id: 42, dive_code: '103C', video_uuid: 'candidate', dive_datetime: '2026-01-02T10:00:00', performance: 'M', score_10: 4.5, height: '1m', platform_type: 'springboard', position: 'C', is_sync: false, modifiers: [], diver: { id: 1, display_name: 'Maxime' } }, similarity: { height_match: true, diver_match: true, sync_match: true, modifier_match: true, performance_match: true, score_distance: 0 }, ready_renditions: [], score_band: 'median', reason: 'media_viability_then_context_and_score', materialization_history: { successful: false, attempt_count: 0, last_error_code: null }, media_viability: 'untested' }] } as any)
  })

  it('groups exact dive codes and labels low typical high', async () => {
    renderPage()
    expect(await screen.findByRole('link', { name: '103C' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '103B' })).toBeInTheDocument()
    expect(screen.getAllByText('Typical').length).toBeGreaterThan(0)
    expect(screen.getByText('A 1 · B 0 · C 0 · D 0')).toBeInTheDocument()
    expect(screen.getByText('ok')).toBeInTheDocument()
    expect(screen.getByText('Poster 0/3 · Video 0/3')).toBeInTheDocument()
  })

  it('shows unavailable reason and bounded replacement without passive POST', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch')
    renderPage()
    expect((await screen.findAllByText('Photos did not provide a usable video file for this attempt.')).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/Find a replacement/).length).toBeGreaterThan(0)
    expect(screen.queryByText(/Prepare All/i)).not.toBeInTheDocument()
    expect(fetchSpy.mock.calls.filter(([, init]) => (init as RequestInit)?.method === 'POST')).toHaveLength(0)
    await userEvent.click(screen.getAllByRole('button', { name: 'Find replacement' })[0])
    expect(await screen.findByText('Replacement candidates')).toBeInTheDocument()
    expect(screen.getByText(/untested/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Use without preparing' }))
    await waitFor(() => expect(replaceRepresentative).toHaveBeenCalledWith('103C', 'low', 42, false, expect.any(URLSearchParams)))
  })

  it('shows queued then failed 720p job state before missing 360p', async () => {
    // Queued 720p with no 360p entry must read as queued, not missing.
    const queued = { ...rep('103B', 'median', 'partial'), media: { state: 'partial', proxy_rendition: null, poster_url: '/poster.jpg', playback_url: null, renditions: { poster: { status: 'ready', entry_id: 1, playback_url: '/poster.jpg', size_bytes: 10, failure: null }, proxy_720p: { status: 'queued', entry_id: null, playback_url: null, size_bytes: null, failure: null }, proxy_360p: { status: 'missing', entry_id: null, playback_url: null, size_bytes: null, failure: null } }, failure: null } }
    vi.mocked(getRepresentatives).mockResolvedValue({ ...payload, dives: [{ dive_code: '103B', coverage: { poster_ready: 1, proxy_ready: 0, total: 1, poster: 1, proxy_360p: 0, fully_ready: false }, representatives: [queued] }] } as any)
    renderPage()
    expect(await screen.findByText('queued')).toBeInTheDocument()
    expect(screen.queryByText('missing')).not.toBeInTheDocument()
  })

  it('shows ready fallback 360p while 720p upgrade failed', async () => {
    const fallback = { ...rep('103B', 'median', 'ready'), media: { state: 'ready', proxy_rendition: 'proxy_360p', poster_url: '/poster.jpg', playback_url: '/proxy360.mp4', renditions: { poster: { status: 'ready', entry_id: 1, playback_url: '/poster.jpg', size_bytes: 10, failure: null }, proxy_720p: { status: 'failed', entry_id: null, playback_url: null, size_bytes: null, failure: { code: 'osxphotos_export_failed', message: 'The Photos export did not complete.', detail: 'A bounded single-asset export failed or was interrupted.', retryable: true } }, proxy_360p: { status: 'ready', entry_id: 2, playback_url: '/proxy360.mp4', size_bytes: 100, failure: null } }, failure: { code: 'osxphotos_export_failed', message: 'The Photos export did not complete.', detail: 'A bounded single-asset export failed or was interrupted.', retryable: true } } }
    vi.mocked(getRepresentatives).mockResolvedValue({ ...payload, dives: [{ dive_code: '103B', coverage: { poster_ready: 1, proxy_ready: 1, total: 1, poster: 1, proxy_360p: 1, fully_ready: true }, representatives: [fallback] }] } as any)
    renderPage()
    // The proxy cell reports the playable fallback as ready, not the failure.
    expect((await screen.findAllByText('ready')).length).toBeGreaterThan(0)
    expect(screen.getByText('The Photos export did not complete.')).toBeInTheDocument()
  })
})

describe('proxyDisplayStatus', () => {
  const rendition = (status: string) => ({ status, entry_id: null, playback_url: null, size_bytes: null, failure: null })

  it('prefers ready 720p, then ready 360p', () => {
    expect(proxyDisplayStatus({ poster: rendition('ready'), proxy_720p: rendition('ready'), proxy_360p: rendition('missing') })).toBe('ready')
    expect(proxyDisplayStatus({ poster: rendition('ready'), proxy_720p: rendition('failed'), proxy_360p: rendition('ready') })).toBe('ready')
  })

  it('shows queued or failed 720p before missing 360p', () => {
    expect(proxyDisplayStatus({ poster: rendition('ready'), proxy_720p: rendition('queued'), proxy_360p: rendition('missing') })).toBe('queued')
    expect(proxyDisplayStatus({ poster: rendition('ready'), proxy_720p: rendition('failed'), proxy_360p: rendition('missing') })).toBe('failed')
  })

  it('falls back to the 360p state when 720p is missing', () => {
    expect(proxyDisplayStatus({ poster: rendition('ready'), proxy_720p: rendition('missing'), proxy_360p: rendition('failed') })).toBe('failed')
    expect(proxyDisplayStatus({ poster: rendition('ready'), proxy_720p: rendition('missing'), proxy_360p: rendition('missing') })).toBe('missing')
  })
})
