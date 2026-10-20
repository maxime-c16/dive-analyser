import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import ClipEvaluation from './ClipEvaluation'
import type { DiveEvaluation } from '../../services/evaluationApi'
import type { Attempt } from '../../utils/attemptPresentation'

vi.mock('../../services/api', () => ({ api: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }))
import { api } from '../../services/api'

const dive = { id: 7, dive_code: '5122D', video_uuid: 'v', diver_id: 2, can_manage: false } as Attempt
const base: DiveEvaluation = { dive_id: 7, state: 'open', circuit: 'request', prompt: 'Watch the entry', results: null, my_rating: null }
const panel = (mine: number) => ({
  request_id: 1, rating_count: 2, mean_score: 7,
  ratings: [
    { id: 9, score_half_steps: mine, author: 'Me', comment: null, created_at: '' },
    { id: 3, score_half_steps: 13, author: 'Léa', comment: 'Clean entry', created_at: '' },
  ],
  my_rating: { id: 9, request_id: 1, evaluator_user_id: 1, score_half_steps: mine, comment: null, created_at: '' },
})

it('an open dive shows the prompt and confirms a half-point score once', async () => {
  const onRated = vi.fn()
  vi.mocked(api.post).mockResolvedValueOnce({ data: { circuit: 'request', rating: panel(15).my_rating, results: panel(15) } })
  render(<ClipEvaluation attempt={dive} evaluation={base} error={false} onReload={() => {}} onRated={onRated} />)
  expect(screen.getByText(/Watch the entry/)).toBeInTheDocument()
  expect(screen.getByText('Requested evaluation')).toBeInTheDocument()
  const confirm = screen.getByRole('button', { name: 'Confirm my score' })
  expect(confirm).toBeDisabled()
  await userEvent.click(screen.getByRole('button', { name: '7 out of 10' }))
  await userEvent.click(screen.getByRole('button', { name: '+ ½' }))
  await userEvent.type(screen.getByRole('textbox'), 'Nice')
  await userEvent.click(screen.getByRole('button', { name: 'Confirm 7.5' }))
  expect(api.post).toHaveBeenCalledWith('/api/v1/dives/7/evaluation/ratings', { score_half_steps: 15, comment: 'Nice' })
  expect(onRated).toHaveBeenCalledWith(expect.objectContaining({ state: 'rated', circuit: 'request' }))
})

it('a stored vote shows the jury and peer remarks, without a keypad', () => {
  const results = panel(15)
  render(<ClipEvaluation attempt={dive} evaluation={{ ...base, state: 'rated', circuit: 'automatic', results, my_rating: results.my_rating }}
    error={false} onReload={() => {}} onRated={() => {}} />)
  expect(screen.getByText('Community score · provisional')).toBeInTheDocument()
  expect(screen.queryByRole('group')).toBeNull()
  expect(screen.getByText('average · 2 judge(s)')).toBeInTheDocument()
  expect(screen.getByText(/Clean entry/)).toBeInTheDocument()
})

it('owners and closed dives never get a keypad', () => {
  const { rerender } = render(<ClipEvaluation attempt={dive} evaluation={{ ...base, state: 'owner', circuit: null }} error={false} onReload={() => {}} onRated={() => {}} />)
  expect(screen.getByText('You cannot score your own dive.')).toBeInTheDocument()
  expect(screen.queryByRole('group')).toBeNull()
  rerender(<ClipEvaluation attempt={dive} evaluation={{ ...base, state: 'closed', circuit: null }} error={false} onReload={() => {}} onRated={() => {}} />)
  expect(screen.getByText('This dive is not open to scores.')).toBeInTheDocument()
})

it('a conflicting vote reloads the server state instead of failing silently', async () => {
  const onReload = vi.fn()
  vi.mocked(api.post).mockRejectedValueOnce({ response: { status: 409 } })
  render(<ClipEvaluation attempt={dive} evaluation={{ ...base, prompt: null }} error={false} onReload={onReload} onRated={() => {}} />)
  await userEvent.click(screen.getByRole('button', { name: '6 out of 10' }))
  await userEvent.click(screen.getByRole('button', { name: 'Confirm 6.0' }))
  expect(onReload).toHaveBeenCalled()
})
