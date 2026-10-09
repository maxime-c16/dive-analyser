import { fireEvent, render, screen, within } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { MyJudgements, othersMean } from './EvaluationSpaces'
import { getMyRatings, getResults } from '../../services/evaluationApi'

vi.mock('../../services/evaluationApi', () => ({ getMyRatings: vi.fn(), getResults: vi.fn(), getOwnedRequests: vi.fn() }))
beforeEach(() => { vi.clearAllMocks() })

const now = new Date()
const iso = (daysAgo: number) => new Date(now.getTime() - daysAgo * 86_400_000).toISOString().replace('Z', '')
const row = (id: number, daysAgo: number, extra = {}) => ({
  kind: 'automatic' as const, request_id: id, dive: { dive_code: '107B', height: '3m', platform_type: 'springboard', dive_name: `Diver ${id}` },
  score_half_steps: 14, comment: null, created_at: iso(daysAgo), rating_count: 3, mean_score: 6, ...extra,
})

it('derives the other judges’ mean from the stored mean that includes mine', () => {
  expect(othersMean({ score_half_steps: 14, rating_count: 3, mean_score: 6 })).toBe(5.5)
  expect(othersMean({ score_half_steps: 14, rating_count: 1, mean_score: 7 })).toBeNull()
})

it('groups votes by day, shows the delta and opens the jury from the row', async () => {
  vi.mocked(getMyRatings).mockResolvedValue({ items: [row(1, 0), row(2, 0, { kind: 'request', rating_count: 1, mean_score: 7 }), row(3, 1)], total: 3, limit: 10, offset: 0 })
  vi.mocked(getResults).mockResolvedValue({ request_id: 1, rating_count: 2, mean_score: 6, my_rating: { id: 9, request_id: 1, evaluator_user_id: 1, score_half_steps: 14, comment: null, created_at: '' },
    ratings: [{ id: 9, score_half_steps: 14, author: 'Me', comment: null, created_at: '' }, { id: 8, score_half_steps: 10, author: 'Zoé', comment: 'Nice', created_at: '' }] })
  render(<MyJudgements />)
  expect(await screen.findByRole('heading', { name: 'Today' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Yesterday' })).toBeInTheDocument()
  expect(screen.getAllByText('+1.5')).toHaveLength(2)
  expect(screen.getByText('First judge')).toBeInTheDocument()
  expect(screen.getByText(/· request/)).toBeInTheDocument()
  const first = screen.getByRole('button', { name: /Diver 1/ })
  fireEvent.click(first)
  expect(first).toHaveAttribute('aria-expanded', 'true')
  const jury = await screen.findByText('Zoé')
  expect(getResults).toHaveBeenCalledWith(1, 50, 0, true)
  expect(within(jury.closest('ul')!).getByText('You')).toBeInTheDocument()
})

it('quotes my comment once and says when nobody else has judged yet', async () => {
  vi.mocked(getMyRatings).mockResolvedValue({ items: [row(4, 0, { comment: 'Clean entry', rating_count: 1, mean_score: 7 })], total: 1, limit: 10, offset: 0 })
  vi.mocked(getResults).mockResolvedValue({ request_id: 4, rating_count: 1, mean_score: 7, my_rating: { id: 3, request_id: 4, evaluator_user_id: 1, score_half_steps: 14, comment: 'Clean entry', created_at: '' },
    ratings: [{ id: 3, score_half_steps: 14, author: 'Me', comment: 'Clean entry', created_at: '' }] })
  render(<MyJudgements />)
  fireEvent.click(await screen.findByRole('button', { name: /Diver 4/ }))
  expect(await screen.findByText('No other judge yet — you set the bar.')).toBeInTheDocument()
  expect(screen.getAllByText(/Clean entry/)).toHaveLength(1)
})

it('prints decimals in the reader’s language', async () => {
  const { points } = await import('./JudgeTable')
  expect(points(6.5, 'fr')).toBe('6,5')
  expect(points(-0.9, 'en', true)).toBe('−0.9')
  expect(points(0, 'en', true)).toBe('=')
})

it('uses the server panel after ownership excludes my vote from the overall mean', async () => {
  vi.mocked(getMyRatings).mockResolvedValue({ items: [row(5, 0, {
    rating_count: 1, mean_score: 4, panel_count: 1, panel_mean: 4,
  })], total: 1, limit: 10, offset: 0 })
  render(<MyJudgements />)
  expect(await screen.findByText('+3.0')).toBeInTheDocument()
  expect(screen.queryByText('First judge')).not.toBeInTheDocument()
  expect(othersMean({ score_half_steps: 14, rating_count: 1, mean_score: 4, panel_mean: 4 })).toBe(4)
  expect(othersMean({ score_half_steps: 14, rating_count: 1, mean_score: 7, panel_mean: null })).toBeNull()
})
