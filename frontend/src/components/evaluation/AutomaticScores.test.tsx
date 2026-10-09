import i18n from '../../i18n'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import AutomaticScores from './AutomaticScores'
import { getAutomaticScores, setAutomaticExclusion } from '../../services/evaluationApi'
vi.mock('../../services/evaluationApi', () => ({ getAutomaticScores: vi.fn(), setAutomaticExclusion: vi.fn() }))
beforeEach(() => { vi.clearAllMocks() })
it('keeps the exclusion state unchanged on failure and only confirms after persistence', async () => {
  vi.mocked(getAutomaticScores).mockResolvedValue({ items: [{ dive_id: 1, dive_code: '101B', height: '3m', excluded: false, rating_count: 2, mean_score: 6.5, provisional: true }], total: 1 })
  vi.mocked(setAutomaticExclusion).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce()
  render(<AutomaticScores />)
  const toggle = await screen.findByRole('switch', { name: 'Exclude from automatic selections' })
  fireEvent.click(toggle)
  await screen.findByRole('alert')
  expect(toggle).toBeChecked()
  await waitFor(() => expect(toggle).not.toBeDisabled())
  fireEvent.click(toggle)
  expect(await screen.findByRole('switch', { name: 'Include in automatic selections' })).not.toBeChecked()
  expect(setAutomaticExclusion).toHaveBeenLastCalledWith(1, true)
  expect(screen.getByText(/6.5.*2 reviewers.*provisional/)).toBeInTheDocument()
})
it('fetches the next page without dropping the public-dive explanation', async () => {
  vi.mocked(getAutomaticScores).mockResolvedValueOnce({ items: Array.from({ length: 20 }, (_, n) => ({ dive_id: n + 1, dive_code: '101B', height: '3m', excluded: false, rating_count: 0, mean_score: null, provisional: true })), total: 21 })
    .mockResolvedValueOnce({ items: [{ dive_id: 21, dive_code: '103B', height: '3m', excluded: true, rating_count: 0, mean_score: null, provisional: true }], total: 21 })
  render(<AutomaticScores />)
  fireEvent.click(await screen.findByRole('button', { name: 'Show more' }))
  await screen.findByText('103B · 3m')
  expect(screen.getByRole('switch', { name: 'Include in automatic selections' })).not.toBeChecked()
  expect(getAutomaticScores).toHaveBeenLastCalledWith(20)
  expect(screen.getByText(/Public dives can be selected automatically/)).toBeInTheDocument()
})

it('sorts the loaded page by score or by judges without refetching', async () => {
  vi.mocked(getAutomaticScores).mockResolvedValue({ items: [
    { dive_id: 1, dive_code: '101B', height: '1m', excluded: false, rating_count: 1, mean_score: 9, provisional: true },
    { dive_id: 2, dive_code: '203C', height: '3m', excluded: false, rating_count: 4, mean_score: 5.5, provisional: true },
    { dive_id: 3, dive_code: '5231D', height: '3m', excluded: false, rating_count: 0, mean_score: null, provisional: true },
  ], total: 3 })
  render(<AutomaticScores />)
  await screen.findByText('101B · 1m')
  const order = () => screen.getAllByText(/ · \dm$/).map(node => node.textContent)
  expect(order()).toEqual(['101B · 1m', '203C · 3m', '5231D · 3m'])
  fireEvent.click(screen.getByRole('button', { name: 'Most judged' }))
  expect(order()).toEqual(['203C · 3m', '101B · 1m', '5231D · 3m'])
  fireEvent.click(screen.getByRole('button', { name: 'Top score' }))
  expect(order()[0]).toBe('101B · 1m')
  expect(getAutomaticScores).toHaveBeenCalledTimes(1)
})

it('uses French decimal commas in both the scoreboard tiles and accessible summaries', async () => {
  vi.mocked(getAutomaticScores).mockResolvedValue({ items: [{ dive_id: 1, dive_code: '101B', height: '3m', excluded: false, rating_count: 2, mean_score: 6.5, provisional: true }], total: 1 })
  await act(async () => { await i18n.changeLanguage('fr') })
  try {
    const { container } = render(<AutomaticScores />)
    expect(await screen.findByText(/6,5.*2 évaluateurs.*provisoire/)).toBeInTheDocument()
    await waitFor(() => expect(container.querySelector('.eval-flap')).toHaveTextContent('6,5'))
    expect(container.querySelector('.eval-flap [data-char="dot"]')).toHaveTextContent(',')
    await act(async () => { await i18n.changeLanguage('en') })
    expect(screen.getByText(/6.5.*2 reviewers.*provisional/)).toBeInTheDocument()
    await waitFor(() => expect(container.querySelector('.eval-flap')).toHaveTextContent('6.5'))
  } finally { await act(async () => { await i18n.changeLanguage('en') }) }
})
