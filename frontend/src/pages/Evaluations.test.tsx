import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import Evaluations from './Evaluations'
import type { EvaluationOverview } from '../services/evaluationApi'

vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { user_id: 1 } }) }))
vi.mock('../components/evaluation/EvaluationSpaces', () => ({ OwnedRequests: () => <p>Owned</p>, MyJudgements: () => <p>History list</p> }))
vi.mock('../components/evaluation/AutomaticScores', () => ({ default: () => <p>Community list</p> }))
vi.mock('../components/evaluation/JurySession', () => ({
  default: (props: { automatic?: boolean; daily?: boolean; resumeStackId?: number; doneBefore?: number; onDone: () => void }) =>
    <div>Session {JSON.stringify({ automatic: !!props.automatic, daily: props.daily, resume: props.resumeStackId, before: props.doneBefore })}<button onClick={props.onDone}>Leave</button></div>,
}))
vi.mock('../services/evaluationApi', () => ({ getEvaluationOverview: vi.fn() }))
import { getEvaluationOverview } from '../services/evaluationApi'

const stack = { stack_id: 7, daily: true, total: 3, judged: 1, skipped: 0, remaining: 2 }
const vote = { dive_id: 5, dive_code: '107B', height: '3m', diver: 'Sasa', score_half_steps: 13, panel_mean: 5.5, panel_count: 2 }
function overview(today: Partial<EvaluationOverview['today']>, extra: Partial<EvaluationOverview> = {}): EvaluationOverview {
  return {
    today: { date: '2026-10-09', resets_at: '2026-10-10T00:00:00Z', daily: null, resume: null, judged_today: 0, votes: [], ...today },
    requests_pending: 0, judged_total: 0, judge: { compared: 0, bias: null, streak: 0 }, ...extra,
  }
}
const renderAt = (url = '/evaluations') => render(<MemoryRouter initialEntries={[url]}><Evaluations /></MemoryRouter>)

beforeEach(() => { vi.clearAllMocks() })

it('opens straight into today’s first dive without a start button', async () => {
  vi.mocked(getEvaluationOverview).mockResolvedValue(overview({}))
  renderAt()
  expect(await screen.findByText(/"automatic":true,"daily":true,"before":0/)).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /start/i })).not.toBeInTheDocument()
})

it('resumes the open selection, then stays paused on the table once closed', async () => {
  vi.mocked(getEvaluationOverview).mockResolvedValue(overview({ daily: stack, resume: stack, judged_today: 1, votes: [vote] }))
  renderAt()
  expect(await screen.findByText(/"resume":7,"before":1/)).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Leave' }))
  expect(await screen.findByText('Paused · 2 left today')).toBeInTheDocument()
  expect(screen.queryByText(/Session/)).not.toBeInTheDocument()  // no bounce back into the stage
  expect(getEvaluationOverview).toHaveBeenCalledTimes(2)
  fireEvent.click(screen.getByRole('button', { name: 'Back to the board' }))
  expect(await screen.findByText(/"resume":7/)).toBeInTheDocument()
})

it('lays today’s cards on the table with the judge’s style, streak and next hand', async () => {
  vi.mocked(getEvaluationOverview).mockResolvedValue(overview(
    { daily: { ...stack, judged: 3, remaining: 0 }, judged_today: 3, votes: [vote, { ...vote, dive_id: 6, panel_mean: null, panel_count: 0 }] },
    { requests_pending: 2, judged_total: 24, judge: { compared: 12, bias: 1.1, streak: 4 } },
  ))
  renderAt()
  expect(await screen.findByRole('heading', { name: 'Rip entry. ✓' })).toBeInTheDocument()
  expect(screen.getByText('Panel 5.5')).toBeInTheDocument()
  expect(screen.getByText('+1.0')).toBeInTheDocument()
  expect(screen.getByText('First judge')).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Generous judge' })).toBeInTheDocument()
  expect(screen.getByText('4-day streak')).toBeInTheDocument()
  expect(screen.getByRole('timer')).toHaveTextContent(/\d\d:\d\d:\d\d/)
  expect(screen.getByText('2 dive(s) waiting for your score.')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: /Deal 3 more/ }))
  expect(await screen.findByText(/"automatic":true,"daily":false/)).toBeInTheDocument()
})

it('keeps the judging style hidden until enough dives are compared', async () => {
  vi.mocked(getEvaluationOverview).mockResolvedValue(overview({ daily: { ...stack, judged: 3, remaining: 0 } }, { judge: { compared: 1, bias: -2.5, streak: 0 } }))
  renderAt()
  expect(await screen.findByRole('heading', { name: 'Judging style: still warming up' })).toBeInTheDocument()
  expect(screen.getByText(/Judge 2 more dive/)).toBeInTheDocument()
  expect(screen.queryByText(/streak/)).not.toBeInTheDocument()
})

it('maps the previous tab links onto the three tabs', async () => {
  vi.mocked(getEvaluationOverview).mockResolvedValue(overview({}))
  renderAt('/evaluations?tab=judgements')
  expect(await screen.findByText('History list')).toBeInTheDocument()
  expect(screen.getByRole('tab', { name: 'History' })).toHaveAttribute('aria-selected', 'true')
  await waitFor(() => expect(getEvaluationOverview).not.toHaveBeenCalled())
})
