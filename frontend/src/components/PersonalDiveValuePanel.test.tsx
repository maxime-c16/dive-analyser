import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import PersonalDiveValuePanel from './PersonalDiveValuePanel'

vi.mock('../services/personalDiveValueApi', () => ({
  getPersonalDiveValue: vi.fn(async () => ({ attempt_id: 4, version: 'v1', value: 84, execution: { score: 7, scale: '0_10' }, difficulty: { official_dd: 1.8, reference_dd: 1.6, beta: .3 }, components: { technical: { raw_value: .7, normalized_value: .7, weight: .35, weighted_contribution: 12.3 }, same_dive_relative: { raw_value: .5, normalized_value: .5, weight: .25, weighted_contribution: 8.2, support: 2, percentile: null }, breakthrough: { raw_value: 1, normalized_value: 1, weight: .15, weighted_contribution: 12.1, reason: 'personal_best' } }, primary_signal: 'Breakthrough', confidence: { level: 'low', same_dive_support: 2, reasons: [] }, caveats: ['Personal review-priority signal; not an official score.'], history_cutoff: '2026-02-01T10:00:00', calculated_at: '2026-02-01T10:00:00' })),
  getPersonalDiveValuePatterns: vi.fn(async () => ({ version: 'v1', attempt_id: 4, matches: [{ attempt_id: 1, dive_code: '103B', session_id: 1, dive_datetime: '2026-01-01T10:00:00', height: '1m', is_sync: false, modifiers: [], trailing_scores: [4, 5, 7], current_trailing_scores: [7, 5, 4], score_distance: 1, context_penalty: 0, similarity_distance: 1, evidence: 'Historical similarity, not prediction.' }] })),
}))

describe('PersonalDiveValuePanel', () => {
  it('shows an explainable provisional value and historical match', async () => {
    render(<PersonalDiveValuePanel attemptId={4} onOpenAttempt={vi.fn()} />)
    expect(await screen.findByText('Personal Dive Value')).toBeInTheDocument()
    expect(screen.getByText('84')).toBeInTheDocument()
    expect(screen.getByText(/Emerging · 2 prior/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /show explanation/i }))
    expect(screen.getByText('What contributed')).toBeInTheDocument()
    expect(screen.getByText('Closest previous pattern')).toBeInTheDocument()
    expect(screen.getByText('Historical similarity, not prediction.')).toBeInTheDocument()
  })

  it('handles unavailable scalar without a generic error', async () => {
    const api = await import('../services/personalDiveValueApi')
    vi.mocked(api.getPersonalDiveValue).mockResolvedValueOnce({ attempt_id: 5, version: 'v1', value: null, execution: { score: 7, scale: '0_10' }, difficulty: { official_dd: null, reference_dd: 1.6, beta: .3 }, components: {}, primary_signal: null, confidence: { level: 'undefined', same_dive_support: 0, reasons: [] }, caveats: [], history_cutoff: '2026-02-01T10:00:00', calculated_at: '2026-02-01T10:00:00' })
    render(<PersonalDiveValuePanel attemptId={5} />)
    await waitFor(() => expect(screen.getByText('Official DD is not defined for this attempt, so a personal value is not shown.')).toBeInTheDocument())
  })
})
