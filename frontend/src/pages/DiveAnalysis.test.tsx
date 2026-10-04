import React from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import DiveAnalysis, { filtersFromSearchParams, parseAttemptParam } from './DiveAnalysis'
import { getDiveAnalysis, type BreakdownRow, type DiveAnalysis as AnalysisData } from '../services/diveAnalysisApi'

vi.mock('../services/diveAnalysisApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/diveAnalysisApi')>()
  return { ...actual, getDiveAnalysis: vi.fn(), getDivers: vi.fn(async () => [{ id: 1, display_name: 'Maxime', canonical_name: 'maxime', is_primary_user: true, active: true }, { id: 2, display_name: 'Paul', canonical_name: 'paul', is_primary_user: false, active: true }]), getTrainingPeriods: vi.fn(async () => [{ id: 4, name: 'Summer', period_type: 'season', start_date: '2026-06-01', end_date: '2026-08-31' }]) }
})
vi.mock('../services/representativeMediaApi', () => ({
  getRepresentatives: vi.fn(async () => ({ summary: { canonical_dive_codes: 1, representatives: 1, ready: 1, partial: 0, missing: 0, unavailable: 0, replacement_available: 0, replacement_exhausted: 0, codes_fully_ready: 1, codes_partially_ready: 0, codes_zero_ready: 0, poster_ready: 1, proxy_ready: 1, fully_ready: true }, dives: [{ dive_code: '103B', coverage: { poster_ready: 1, proxy_ready: 1, total: 1, poster: 1, proxy_360p: 1, fully_ready: true }, representatives: [{ role: 'median', label: 'Typical', selection: { id: null, version: 1, reason: 'initial_manifest' }, attempt: { id: 1, dive_code: '103B', video_uuid: 'uuid-1', dive_datetime: '2026-01-01T10:00:00', performance: 'G', score_10: 7, height: '1m', platform_type: 'springboard', position: 'B', is_sync: false, modifiers: ['DB'], diver: { id: 1, display_name: 'Maxime' } }, media: { state: 'ready', poster_url: '/poster.jpg', playback_url: '/proxy.mp4', renditions: { poster: { status: 'ready', entry_id: 1, playback_url: '/poster.jpg', size_bytes: 10 }, proxy_360p: { status: 'ready', entry_id: 2, playback_url: '/proxy.mp4', size_bytes: 20 } } }, replacement: { available: false, candidate_count: 0, state: 'exhausted' }, note: 'Selected from the recorded score distribution' }] }] })),
}))
vi.mock('../services/personalDiveValueApi', () => ({
  getPersonalDiveValues: vi.fn(async () => ({ version: 'v1', dive_code: '103B', values: [{ attempt_id: 1, version: 'v1', value: 84, execution: { score: 7, scale: '0_10' }, difficulty: { official_dd: 1.5, reference_dd: 1.6, beta: 0.3 }, components: {}, primary_signal: 'Breakthrough', confidence: { level: 'medium', same_dive_support: 6, reasons: [] }, caveats: [], history_cutoff: '2026-01-01T10:00:00', calculated_at: '2026-01-01T10:00:00' }] })),
  getPersonalDiveValue: vi.fn(async () => ({ attempt_id: 1, version: 'v1', value: 84, execution: { score: 7, scale: '0_10' }, difficulty: { official_dd: 1.5, reference_dd: 1.6, beta: 0.3 }, components: { technical: { raw_value: .7, normalized_value: .7, weight: .35, weighted_contribution: 10 }, same_dive_relative: { raw_value: .5, normalized_value: .5, weight: .25, weighted_contribution: 5, support: 6, percentile: 80 }, breakthrough: { raw_value: 1, normalized_value: 1, weight: .15, weighted_contribution: 10, reason: 'personal_best' } }, primary_signal: 'Breakthrough', confidence: { level: 'medium', same_dive_support: 6, reasons: [] }, caveats: [], history_cutoff: '2026-01-01T10:00:00', calculated_at: '2026-01-01T10:00:00' })),
  getPersonalDiveValuePatterns: vi.fn(async () => ({ version: 'v1', attempt_id: 1, matches: [] })),
}))
vi.mock('../components/DiveVideoPlayer', () => ({ default: ({ videoUuid }: { videoUuid: string }) => <div>Player {videoUuid}</div> }))

const attempt = (id: number, score: number, modifiers: string[] = []) => ({ id, dive_code: '103B', dive_datetime: `2026-0${id}-01T10:00:00`, performance: score >= 7 ? 'G' : 'M', performance_numeric: score, phase1_performance: id === 2 ? null : 'G', phase1_numeric: id === 2 ? null : 7, phase2_performance: 'M', phase2_numeric: 4.5, rolling_median: score, height: id === 1 ? '1m' : '3m', platform_type: 'springboard', position: 'B', is_sync: id === 2, modifiers, diver: { id: id === 2 ? 2 : 1, display_name: id === 2 ? 'Paul' : 'Maxime', is_primary_user: id !== 2 }, legacy_person_name: null, session_id: id, official_dd: 1.5, dd_adjusted_execution: score * 1.5, dd_reference: 'test', raw_caption: `103B ${modifiers.join(' ')}`, notes: null, video_uuid: `uuid-${id}`, training_periods: [{ id: 4, name: 'Summer', period_type: 'season' }], media: { status: 'missing', poster_url: null, playback_url: null, can_request: true, job_id: null, job_error: null } })
const summary = { attempt_count: 2, session_count: 2, scored_attempt_count: 2, unscored_attempt_count: 0, average: 5.75, median: 5.75, minimum: 4.5, maximum: 7, standard_deviation: 1.25, q1: 4.5, q3: 7, iqr: 2.5, success_rate: 50, success_threshold: 'G', weighting_mode: 'attempt_weighted', dd_defined_attempt_count: 2, dd_coverage_rate: 100, average_dd: 1.5, median_dd: 1.5, max_dd: 1.5, dd_adjusted_execution_average: 8.63, dd_adjusted_execution_median: 8.63, dd_reference: 'test', best_attempt_id: 1, worst_attempt_id: 2, first_attempt_at: '2026-01-01T10:00:00', last_attempt_at: '2026-02-01T10:00:00' }
const group = (context: string, count = 2): BreakdownRow => ({ ...summary, context, context_id: null, attempt_count: count, sample_label: count <= 2 ? 'insufficient' : 'exploratory' })
const payload: AnalysisData = { generated_at: '2026-07-10T10:00:00', analytics_version: '2.0', dive_code: '103B', weighting_mode: 'attempt_weighted', sample: summary, summary, trend: { direction: 'stable', slope_per_30_days: 0, confidence: 'insufficient', reason: null }, comparison: { current: summary, previous: summary, previous_range: { date_from: '2025-11-01', date_to: '2025-12-31' } }, breakdowns: { modifier: [group('No modifiers'), group('DB', 1)], height: [group('1m', 1), group('3m', 1)], position: [group('B')], sync: [group('Individual', 1), group('SYNC', 1)], diver: [group('Maxime', 1), group('Paul', 1)], training_period: [group('Summer')] }, phases: { total_attempts: 2, phases: { phase1: { available_count: 1, missing_count: 1, summary: { median: 7 }, previous_summary: { median: 4.5 }, distribution: { G: 1 }, points: [{ attempt_id: 1, dive_datetime: '2026-01-01T10:00:00', score: 7, rolling_median: 7 }] }, phase2: { available_count: 2, missing_count: 0, summary: { median: 4.5 }, previous_summary: { median: 4.5 }, distribution: { M: 2 }, points: [{ attempt_id: 1, dive_datetime: '2026-01-01T10:00:00', score: 4.5, rolling_median: 4.5 }, { attempt_id: 2, dive_datetime: '2026-02-01T10:00:00', score: 4.5, rolling_median: 4.5 }] } } }, training_periods: [{ id: 4, name: 'Summer', period_type: 'season', start_date: '2026-06-01', end_date: '2026-08-31' }], insights: [{ type: 'stable', tone: 'neutral', confidence: 'insufficient', title: 'Not enough comparable attempts', message: 'Descriptive only.', evidence: {} }], attempts: [attempt(1, 7, ['DB']), attempt(2, 4.5)], observability: { cache: 'miss', query_ms: 4, calculation_ms: 2, total_ms: 8, result_attempts: 2 } }
const densePayload: AnalysisData = { ...payload, sample: { ...summary, attempt_count: 130, session_count: 26 }, summary: { ...summary, attempt_count: 130, session_count: 26 }, attempts: Array.from({ length: 130 }, (_, index) => attempt((index % 8) + 1, 4 + (index % 5), index % 9 === 0 ? ['DB'] : [])).map((item, index) => ({ ...item, id: index + 1, session_id: Math.floor(index / 5) + 1, dive_datetime: `2026-${String((index % 6) + 1).padStart(2, '0')}-${String((index % 24) + 1).padStart(2, '0')}T10:00:00` })) }

function Location() { return <output data-testid="location">{useLocation().search}</output> }
function LibraryMarker() { return <><div data-testid="library">Library</div><Location /></> }
function renderPage(entry: string | { pathname: string; search: string; state?: unknown } = '/dives/analysis/103B') { return render(<MemoryRouter initialEntries={[entry]}><Routes><Route path="/dives/analysis/:diveCode" element={<><DiveAnalysis /><Location /></>} /><Route path="/dives" element={<LibraryMarker />} /></Routes></MemoryRouter>) }
// UI-U7: secondary analysis lives behind collapsed sections that mount only
// after the aggregate result arrives; wait for data, then open one.
async function openSection(name: string | RegExp) {
  await screen.findByTestId('analysis-key-summary')
  await userEvent.click(screen.getByRole('button', { name }))
}

describe('Per-dive intelligence V2', () => {
  beforeEach(() => { vi.mocked(getDiveAnalysis).mockResolvedValue(payload) })
  it('hydrates canonical route and URL filters', async () => { renderPage('/dives/analysis/103B?modifiers=DB&modifier_mode=all&diver_ids=1'); expect(await screen.findByRole('heading', { name: '103B' })).toBeInTheDocument(); expect(filtersFromSearchParams(new URLSearchParams('modifiers=DB&diver_ids=1')).diver_ids).toEqual([1]) })
  it('defaults to my dives and makes all divers explicit', async () => { renderPage(); await openSection(/^Filters/); expect(screen.getByLabelText('Diver scope')).toHaveValue('self'); await userEvent.selectOptions(screen.getByLabelText('Diver scope'), 'all'); await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('diver_scope=all')) })
  it('changing weighting updates the URL and request', async () => { renderPage(); await openSection(/^Filters/); await screen.findByLabelText('Analysis weighting'); await userEvent.selectOptions(screen.getByLabelText('Analysis weighting'), 'sessions'); await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('weighting=sessions')); const calls = vi.mocked(getDiveAnalysis).mock.calls; expect(calls[calls.length - 1]?.[1].weighting).toBe('sessions') })
  it('modifier buttons update URL without submitting media jobs', async () => { const fetchSpy = vi.spyOn(globalThis, 'fetch'); renderPage(); await openSection(/^Filters/); await screen.findByText('Progression'); await userEvent.click(screen.getByRole('button', { name: 'DB' })); expect(screen.getByTestId('location')).toHaveTextContent('modifiers=DB'); expect(fetchSpy.mock.calls.some(([url, init]) => String(url).includes('/media/') && (init as RequestInit)?.method === 'POST')).toBe(false) })
  it('supports any all and none modifier modes', () => { expect(filtersFromSearchParams(new URLSearchParams('modifier_mode=any')).modifier_mode).toBe('any'); expect(filtersFromSearchParams(new URLSearchParams('modifier_mode=all')).modifier_mode).toBe('all'); expect(filtersFromSearchParams(new URLSearchParams('modifier_mode=none')).modifier_mode).toBe('none') })
  it('chart point opens its exact attempt', async () => { renderPage(); await openSection(/^Progression/); const point = await screen.findByLabelText(/1 Jan 2026.*score 7.0/); fireEvent.click(point); expect(screen.getByRole('heading', { name: '103B · 7.0' })).toBeInTheDocument(); expect(screen.getByText('Player uuid-1')).toBeInTheDocument() })
  it('keyboard attempt row opens exact attempt', async () => { renderPage(); await openSection(/^Attempts to review/); await screen.findByText('Progression'); const rows = screen.getAllByRole('row'); const sourceRow = rows.find((row) => row.textContent?.includes('1 Jan 2026')); fireEvent.keyDown(sourceRow!, { key: 'Enter' }); expect(screen.getByRole('heading', { name: '103B · 7.0' })).toBeInTheDocument() })
  it('shows structured straight-jump error clearly', async () => { vi.mocked(getDiveAnalysis).mockRejectedValue(new Error('Straight jumps are excluded from performance analytics.')); renderPage('/dives/analysis/100B'); expect(await screen.findByRole('alert')).toHaveTextContent('Straight jumps are excluded') })
  it('uses normalized diver IDs and training period IDs', async () => { renderPage(); await openSection(/^Filters/); await screen.findByText('Progression'); await userEvent.selectOptions(screen.getByLabelText('Diver scope'), 'selected'); await userEvent.selectOptions(screen.getByLabelText('Selected divers'), '2'); await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('diver_ids=2')); await userEvent.selectOptions(screen.getByLabelText('Training period'), '4'); expect(screen.getByTestId('location')).toHaveTextContent('training_period_ids=4') })
  it('reports missing phase values instead of zero', async () => { renderPage(); await openSection(/^Phase analysis/); expect(await screen.findByText('1 scored · 1 missing')).toBeInTheDocument() })
  it('uses natural position names while retaining canonical filter values', async () => {
    renderPage()
    await openSection(/^Filters/)
    const position = await screen.findByLabelText('Position')
    expect(position).toHaveTextContent('Pike')
    expect(position).toHaveTextContent('Tuck')
    await userEvent.selectOptions(position, 'B')
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('position=B'))
    expect(screen.getByText('Pike')).toBeInTheDocument()
  })
  it('shows comparison small-sample labels', async () => { renderPage(); await openSection(/^Comparison/); await screen.findByText('Context breakdown'); expect(screen.getAllByText('Insufficient').length).toBeGreaterThan(0) })
  it('shows representative attempts without preparing media', async () => { const fetchSpy = vi.spyOn(globalThis, 'fetch'); renderPage(); await openSection(/^Representative attempts/); expect(await screen.findByText('Representative attempts')).toBeInTheDocument(); expect(screen.getByText('Typical')).toBeInTheDocument(); expect(fetchSpy.mock.calls.filter(([url, init]) => String(url).includes('/media/') && (init as RequestInit)?.method === 'POST')).toHaveLength(0) })
  it('renders passive attempts without creating any media request', async () => { const fetchSpy = vi.spyOn(globalThis, 'fetch'); renderPage(); await screen.findByText('Progression'); expect(fetchSpy.mock.calls.filter(([url, init]) => String(url).includes('/media/') && (init as RequestInit)?.method === 'POST')).toHaveLength(0) })
  it('labels rolling median and keeps raw attempts as scatter points', async () => { renderPage(); await openSection(/^Progression/); expect((await screen.findAllByText('Rolling 5-attempt median')).length).toBeGreaterThan(0); expect(screen.getAllByTestId('rolling-median-line').length).toBeGreaterThan(0); expect(screen.getAllByTestId('attempt-progression-chart')[0].querySelectorAll('circle').length).toBeGreaterThan(0) })
  it('defaults dense datasets to session summary and can switch to all attempts', async () => { vi.mocked(getDiveAnalysis).mockResolvedValue(densePayload); renderPage(); await openSection(/^Progression/); expect(await screen.findByLabelText('Chart view')).toHaveValue('session'); await userEvent.selectOptions(screen.getByLabelText('Chart view'), 'attempts'); expect(screen.getByTestId('location')).toHaveTextContent('chart_view=attempts') })
  it('renders a min median max range for adaptive time periods when range view is selected', async () => { renderPage(); await openSection(/^Progression/); await screen.findByText('Progression'); await userEvent.selectOptions(screen.getByLabelText('Chart view'), 'range'); expect(screen.getByTestId('location')).toHaveTextContent('chart_view=range'); expect(await screen.findAllByTestId('session-range')).toHaveLength(2); expect(screen.getByText('One vertical range per adaptive time period · select a median to open an exact attempt')).toBeInTheDocument() })
  it('keeps the analysis mounted when presentation-only chart controls change', async () => {
    renderPage()
    await openSection(/^Progression/)
    await openSection(/^Phase analysis/)
    const requestCount = vi.mocked(getDiveAnalysis).mock.calls.length
    await userEvent.selectOptions(screen.getByLabelText('Chart view'), 'range')
    await userEvent.selectOptions(screen.getByLabelText('Split progression by'), 'height')
    await userEvent.selectOptions(screen.getByLabelText('Phase chart view'), 'session')
    expect(vi.mocked(getDiveAnalysis)).toHaveBeenCalledTimes(requestCount)
    expect(screen.getByText('Progression')).toBeInTheDocument()
  })
  it('offers the same range view for phase timelines using their parent sessions', async () => { renderPage(); await openSection(/^Phase analysis/); await screen.findByText('Phase analysis'); await userEvent.selectOptions(screen.getByLabelText('Phase chart view'), 'range'); expect(screen.getByTestId('location')).toHaveTextContent('phase_view=range'); expect((await screen.findAllByTestId('session-range')).length).toBeGreaterThanOrEqual(3) })
  it('surfaces notable attempts without recalculating the formula in the browser', async () => { renderPage(); await openSection(/^Personal review priority/); expect(await screen.findByRole('heading', { name: 'Personal Dive Value' })).toBeInTheDocument(); expect(screen.getByText('Most notable in this view')).toBeInTheDocument() })
  it('persists split mode and exposes mixed-context groups', async () => { renderPage(); await openSection(/^Comparison/); await screen.findByText('Mixed comparison context'); await openSection(/^Progression/); await userEvent.selectOptions(screen.getByLabelText('Split progression by'), 'height'); expect(screen.getByTestId('location')).toHaveTextContent('split_by=height') })
})

describe('UI-U7 progressive disclosure and review continuity', () => {
  beforeEach(() => { vi.mocked(getDiveAnalysis).mockResolvedValue(payload) })
  it('parses the selected-attempt parameter safely', () => {
    expect(parseAttemptParam(null)).toBeNull()
    expect(parseAttemptParam('')).toBeNull()
    expect(parseAttemptParam('abc')).toBeNull()
    expect(parseAttemptParam('0')).toBeNull()
    expect(parseAttemptParam('-3')).toBeNull()
    expect(parseAttemptParam('1.5')).toBeNull()
    expect(parseAttemptParam('12abc')).toBeNull()
    expect(parseAttemptParam(' 7 ')).toBe(7)
    expect(parseAttemptParam('18')).toBe(18)
  })
  it('shows Back to Library with a code-scoped fallback when opened directly', async () => {
    renderPage()
    const back = await screen.findByTestId('analysis-back')
    expect(back).toHaveTextContent('Back to Library')
    await userEvent.click(back)
    expect(await screen.findByTestId('library')).toBeInTheDocument()
    expect(screen.getByTestId('location')).toHaveTextContent('q=103B')
  })
  it('preserves valid attempt context and returns to the exact clip', async () => {
    renderPage('/dives/analysis/103B?attempt=1')
    expect(await screen.findByTestId('analysis-attempt-context')).toHaveTextContent('This attempt')
    expect(screen.getByTestId('analysis-back')).toHaveTextContent('Back to clip')
    await userEvent.click(screen.getByTestId('analysis-back'))
    expect(await screen.findByTestId('library')).toBeInTheDocument()
    expect(screen.getByTestId('location')).toHaveTextContent('clip=1')
  })
  it('an unresolvable attempt id fails safe and never claims a clip', async () => {
    renderPage('/dives/analysis/103B?attempt=999')
    expect(await screen.findByTestId('analysis-attempt-mismatch')).toBeInTheDocument()
    expect(screen.getByTestId('analysis-back')).toHaveTextContent('Back to Library')
    expect(screen.queryByTestId('analysis-attempt-context')).not.toBeInTheDocument()
  })
  it('a non-numeric attempt parameter is ignored silently', async () => {
    renderPage('/dives/analysis/103B?attempt=abc')
    await screen.findByRole('heading', { name: '103B' })
    expect(screen.queryByTestId('analysis-attempt-mismatch')).not.toBeInTheDocument()
    expect(screen.queryByTestId('analysis-attempt-context')).not.toBeInTheDocument()
    expect(screen.getByTestId('analysis-back')).toHaveTextContent('Back to Library')
  })
  it('honors an explicit Viewer return destination', async () => {
    renderPage({ pathname: '/dives/analysis/103B', search: '?attempt=1', state: { returnTo: '/dives?q=103&view=list&clip=1' } })
    expect(await screen.findByTestId('analysis-attempt-context')).toBeInTheDocument()
    expect(screen.getByTestId('analysis-back')).toHaveTextContent('Back to clip')
    await userEvent.click(screen.getByTestId('analysis-back'))
    expect(await screen.findByTestId('library')).toBeInTheDocument()
    expect(screen.getByTestId('location')).toHaveTextContent('q=103&view=list&clip=1')
  })
  it('does not auto-open the attempt drawer from attempt context alone', async () => {
    renderPage('/dives/analysis/103B?attempt=1')
    await screen.findByTestId('analysis-attempt-context')
    expect(screen.queryByRole('heading', { name: '103B · 7.0' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Open attempt details' }))
    expect(await screen.findByRole('heading', { name: '103B · 7.0' })).toBeInTheDocument()
  })
  it('a code switch never carries the attempt across dive codes', async () => {
    renderPage('/dives/analysis/103B?attempt=1')
    await screen.findByTestId('analysis-attempt-context')
    await userEvent.clear(screen.getByLabelText('Dive code'))
    await userEvent.type(screen.getByLabelText('Dive code'), '104C')
    await userEvent.click(screen.getByRole('button', { name: 'Analyze' }))
    await waitFor(() => expect(vi.mocked(getDiveAnalysis).mock.calls[vi.mocked(getDiveAnalysis).mock.calls.length - 1]?.[0]).toBe('104C'))
    expect(screen.getByTestId('location').textContent).not.toContain('attempt')
    expect(screen.queryByTestId('analysis-attempt-context')).not.toBeInTheDocument()
  })
  it('retry re-reads the analysis without launching media work', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch')
    const callsBefore = vi.mocked(getDiveAnalysis).mock.calls.length
    vi.mocked(getDiveAnalysis).mockRejectedValueOnce(new Error('boom'))
    renderPage()
    expect(await screen.findByTestId('analysis-retry')).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('boom')
    vi.mocked(getDiveAnalysis).mockResolvedValue(payload)
    await userEvent.click(screen.getByTestId('analysis-retry'))
    expect(await screen.findByTestId('analysis-key-summary')).toBeInTheDocument()
    expect(vi.mocked(getDiveAnalysis).mock.calls.length).toBe(callsBefore + 2)
    expect(fetchSpy.mock.calls.filter(([url, init]) => String(url).includes('/media/') && (init as RequestInit)?.method === 'POST')).toHaveLength(0)
  })
  it('empty results render an honest unavailable state with no populated sections', async () => {
    const empty: AnalysisData = { ...payload, sample: { ...summary, attempt_count: 0, session_count: 0 }, summary: { ...summary, attempt_count: 0, session_count: 0, scored_attempt_count: 0 }, attempts: [] }
    vi.mocked(getDiveAnalysis).mockResolvedValue(empty)
    renderPage()
    expect(await screen.findByTestId('analysis-unavailable')).toHaveTextContent('No attempts in this view.')
    expect(screen.queryByTestId('analysis-key-summary')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Progression/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Representative attempts/ })).not.toBeInTheDocument()
  })
  it('keeps operational observability out of the user-facing page', async () => {
    renderPage()
    await screen.findByTestId('analysis-key-summary')
    expect(screen.queryByText(/Analytics 2\.0/)).not.toBeInTheDocument()
    expect(screen.queryByText(/result_attempts/)).not.toBeInTheDocument()
  })
  it('progressive sections toggle with keyboard and expose their state', async () => {
    renderPage()
    await screen.findByTestId('analysis-key-summary')
    const toggle = screen.getByRole('button', { name: /^Comparison/ })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText('Period comparison')).not.toBeInTheDocument()
    toggle.focus()
    await userEvent.keyboard('{Enter}')
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(await screen.findByText('Period comparison')).toBeInTheDocument()
    await userEvent.keyboard('{Enter}')
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
  })
  it('labels aggregate scope explicitly on first screen and in Comparison', async () => {
    renderPage()
    expect(await screen.findByTestId('analysis-scope')).toHaveTextContent('2 attempts in 2 sessions')
    expect(screen.getByTestId('analysis-key-summary')).toHaveTextContent('103B')
    expect(screen.getByRole('button', { name: /^Comparison & history/ })).toBeInTheDocument()
  })
})
