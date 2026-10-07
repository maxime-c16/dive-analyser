import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import AutomaticScores from './AutomaticScores'
import { getAutomaticScores, setAutomaticExclusion } from '../../services/evaluationApi'
vi.mock('../../services/evaluationApi', () => ({ getAutomaticScores: vi.fn(), setAutomaticExclusion: vi.fn() }))
beforeEach(() => { vi.clearAllMocks() })
it('keeps the exclusion state unchanged on failure and only confirms after persistence', async () => {
  vi.mocked(getAutomaticScores).mockResolvedValue({ items: [{ dive_id: 1, dive_code: '101B', height: '3m', excluded: false, rating_count: 2, mean_score: 6.5, provisional: true }], total: 1 })
  vi.mocked(setAutomaticExclusion).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce()
  render(<AutomaticScores />)
  const button = await screen.findByRole('button', { name: 'Exclude from automatic selections' })
  fireEvent.click(button)
  await screen.findByRole('alert')
  expect(button).toHaveAttribute('aria-pressed', 'false')
  await waitFor(() => expect(button).not.toBeDisabled())
  fireEvent.click(button)
  await screen.findByRole('button', { name: 'Include in automatic selections' })
  expect(setAutomaticExclusion).toHaveBeenLastCalledWith(1, true)
  expect(screen.getByText(/6.5.*2 reviewers.*provisional/)).toBeInTheDocument()
})
it('fetches the next page without dropping the public-dive explanation', async () => {
  vi.mocked(getAutomaticScores).mockResolvedValueOnce({ items: Array.from({ length: 20 }, (_, n) => ({ dive_id: n + 1, dive_code: '101B', height: '3m', excluded: false, rating_count: 0, mean_score: null, provisional: true })), total: 21 })
    .mockResolvedValueOnce({ items: [{ dive_id: 21, dive_code: '103B', height: '3m', excluded: true, rating_count: 0, mean_score: null, provisional: true }], total: 21 })
  render(<AutomaticScores />)
  fireEvent.click(await screen.findByRole('button', { name: 'Show more' }))
  await screen.findByText('103B · 3m')
  expect(getAutomaticScores).toHaveBeenLastCalledWith(20)
  expect(screen.getByText(/Public dives can be selected automatically/)).toBeInTheDocument()
})
