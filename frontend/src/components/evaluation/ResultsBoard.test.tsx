import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import ResultsBoard from './ResultsBoard'
import { getResults, type JuryResults } from '../../services/evaluationApi'
vi.mock('../../services/evaluationApi', () => ({ getResults: vi.fn() }))
const ratings = Array.from({ length: 60 }, (_, id) => ({ id: id + 1, score_half_steps: 14, author: `Judge ${id + 1}`, comment: null, created_at: 'now' }))
const results: JuryResults = { request_id: 7, rating_count: 60, mean_score: 7, ratings: ratings.slice(0, 50), my_rating: null }
beforeEach(() => { vi.clearAllMocks() })
it('keeps all-panel aggregates while paging and loads the remaining notes on the correct transport', async () => {
  vi.mocked(getResults).mockResolvedValue({ ...results, ratings: ratings.slice(50) })
  const { container } = render(<ResultsBoard results={results} score={14} automatic />)
  expect(container.querySelectorAll('.eval-results-peers .eval-card')).toHaveLength(4)
  expect(screen.getByText('60 vote(s) · community average 7.0')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: /60 scores/ }))
  const dialog = screen.getByRole('dialog')
  expect(within(dialog).getAllByRole('img')).toHaveLength(50)
  fireEvent.click(within(dialog).getByRole('button', { name: 'Show more' }))
  await waitFor(() => expect(within(dialog).getAllByRole('img')).toHaveLength(60))
  expect(getResults).toHaveBeenCalledWith(7, 50, 50, true)
  fireEvent.click(within(dialog).getByRole('button', { name: 'Close' }))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})
it('keeps loaded scores and the offset after an offline continuation', async () => {
  vi.mocked(getResults).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({ ...results, ratings: ratings.slice(50) })
  render(<ResultsBoard results={results} score={14} automatic={false} />)
  fireEvent.click(screen.getByRole('button', { name: /60 scores/ }))
  const dialog = screen.getByRole('dialog')
  fireEvent.click(within(dialog).getByRole('button', { name: 'Show more' }))
  await within(dialog).findByRole('alert')
  expect(within(dialog).getAllByRole('img')).toHaveLength(50)
  fireEvent.click(within(dialog).getByRole('button', { name: 'Retry' }))
  await waitFor(() => expect(within(dialog).getAllByRole('img')).toHaveLength(60))
  expect(getResults).toHaveBeenLastCalledWith(7, 50, 50, false)
})
