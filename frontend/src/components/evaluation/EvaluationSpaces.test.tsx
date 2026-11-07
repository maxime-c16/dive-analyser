import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { MyJudgements, OwnedRequests, othersMean } from './EvaluationSpaces'
import { getMyRatings, getResults, getOwnedRequests } from '../../services/evaluationApi'
import { MemoryRouter } from 'react-router-dom'

vi.mock('../../services/evaluationApi', () => ({ getMyRatings: vi.fn(), getResults: vi.fn(), getOwnedRequests: vi.fn() }))
vi.mock('../DiveThumbnail', () => ({ default:() => <span>Preview</span> }))
beforeEach(() => { vi.clearAllMocks() })

it('connects an accessible requested evaluation to its exact video and date', async () => {
  const request = { request_id:1, dive_id:3045, active:true, prompt:'Entry', created_at:'', updated_at:'', rating_count:2, mean_score:3,
    dive:{ id:3045, video_uuid:'video', dive_code:'103B', height:'3m', platform_type:'springboard', owner_display_name:null, dive_datetime:'2026-11-04T18:27:00' } }
  vi.mocked(getOwnedRequests).mockResolvedValue({ items:[request, { ...request, request_id:2, dive_id:3046, active:false }], total:2, offset:0, limit:10 })
  const { container } = render(<MemoryRouter><OwnedRequests /></MemoryRouter>)
  expect(await screen.findByRole('link', { name:'103B' })).toHaveAttribute('href','/dives?clip=3045&scope=all')
  expect(screen.getAllByRole('link')).toHaveLength(1)
  expect(container.querySelector('time')).toHaveAttribute('datetime','2026-11-04T18:27:00')
})

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


it('announces the new history page and focuses its first day after paging', async () => {
  vi.mocked(getMyRatings).mockResolvedValueOnce({ items:[row(1,0)], total:11, limit:10, offset:0 })
    .mockResolvedValueOnce({ items:[row(2,1)], total:11, limit:10, offset:10 })
  render(<MyJudgements />)
  await screen.findByRole('heading', { name:'Today' })
  fireEvent.click(screen.getByRole('button', { name:'Next page' }))
  const first = await screen.findByRole('heading', { name:'Yesterday' })
  expect(first).toHaveFocus()
  expect(screen.getByText('Page 2 of 2')).toBeInTheDocument()
  expect(getMyRatings).toHaveBeenLastCalledWith(10,10)
})


it('ignores an older page response after the requested URL page changes', async () => {
  let resolveFirst!: (value: Awaited<ReturnType<typeof getMyRatings>>) => void
  vi.mocked(getMyRatings).mockImplementationOnce(() => new Promise(resolve => { resolveFirst = resolve }) as ReturnType<typeof getMyRatings>)
    .mockResolvedValueOnce({ items:[row(2,1)], total:20, limit:10, offset:10 })
  const { rerender } = render(<MyJudgements page={1} onPage={() => {}} />)
  rerender(<MyJudgements page={2} onPage={() => {}} />)
  await screen.findByRole('heading', { name:'Yesterday' })
  await act(async () => resolveFirst({ items:[row(1,0)], total:20, limit:10, offset:0 }))
  expect(screen.getByText('Page 2 of 2')).toBeInTheDocument()
  expect(screen.queryByRole('heading', { name:'Today' })).not.toBeInTheDocument()
})


it('retries the page requested by the URL after a loading failure', async () => {
  vi.mocked(getMyRatings).mockRejectedValueOnce(new Error('offline'))
    .mockResolvedValueOnce({ items:[row(2,1)], total:20, limit:10, offset:10 })
  render(<MyJudgements page={2} onPage={() => {}} />)
  fireEvent.click(await screen.findByRole('button', { name:'Retry' }))
  await screen.findByText('Page 2 of 2')
  expect(getMyRatings).toHaveBeenLastCalledWith(10,10)
})
