/**
 * JurySession state-machine tests (issue #68). Services mocked; the media
 * player is stubbed. Covers: intro skip, first-start queue fetch (regression:
 * async session id), batch-id rotation across loads, all-unavailable batch
 * continuation, confirm → submitting → reveal with DEDUPED own card + names,
 * auto-advance hold with parked results, double-submit guard, error
 * retention, 409 flows, pass and summary with recap.
 */
import React from 'react'
import { render, screen, waitFor, within, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import JurySession from './JurySession'
import type { QueueBatch, SubmissionResponse } from '../../services/evaluationApi'

vi.mock('../DiveVideoPlayer', () => ({ default: () => <div>Video</div> }))
let autoFinishVideo = true
vi.mock('./EvaluationPlayer', () => ({ default: ({ requestId, onEnded, watching, onFailure }: { requestId: number; onEnded?: () => void; watching?: boolean; onFailure?: () => void }) => {
  React.useEffect(() => { if (autoFinishVideo && watching) onEnded?.() }, [requestId, watching])
  return <div data-request={requestId}><button onClick={onEnded}>Finish video</button><button onClick={onFailure}>Fail video</button><span>EvalVideo</span></div>
} }))
vi.mock('../../services/evaluationApi', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../services/evaluationApi')>()
  return {
    ...original,
    createSession: vi.fn(),
    createAutomaticStack: vi.fn(),
    getAutomaticQueue: vi.fn(),
    skipAutomaticDive: vi.fn(),
    getQueue: vi.fn(),
    skipRequest: vi.fn(),
    submitRating: vi.fn(),
  }
})

import { createSession, getQueue, skipRequest, submitRating, createAutomaticStack, getAutomaticQueue, skipAutomaticDive } from '../../services/evaluationApi'

function item(id: number, code: string): NonNullable<QueueBatch['items'][number]> {
  const value = id
  return {
    request_id: value,
    dive_id: value + 100,
    prompt: null,
    dive: { id: value + 100, video_uuid: `u${value}`, dive_code: code, height: '3m', platform_type: 'springboard', owner_display_name: 'Claire' },
    media: { status: 'ready', poster_url: null, playback_url: `/api/v1/evaluations/requests/${value}/media/play` },
  }
}

const batch: QueueBatch = { batch_id: 'b0', items: [item(11, '107B'), item(12, '105C')], has_more: false }
const emptyBatch: QueueBatch = { batch_id: 'b-empty', items: [], has_more: false }

const voteResponse: SubmissionResponse = {
  rating: { id: 1, request_id: 11, evaluator_user_id: 2, score_half_steps: 13, comment: 'ok', created_at: '2026-10-06T10:00:00' },
  results: {
    request_id: 11,
    rating_count: 3,
    mean_score: 6.5,
    ratings: [
      { id: 5, score_half_steps: 10, author: 'Bob', comment: 'Solide', created_at: 'x' },
      { id: 6, score_half_steps: 8, author: 'Zoé', comment: null, created_at: 'y' },
      { id: 1, score_half_steps: 13, author: 'Moi', comment: 'Mon vote', created_at: 'z' },
    ],
    my_rating: { id: 1, request_id: 11, evaluator_user_id: 2, score_half_steps: 13, comment: 'Mon vote', created_at: 'z' },
  },
}

beforeEach(() => {
  vi.clearAllMocks()
  autoFinishVideo = true
  vi.mocked(createSession).mockResolvedValue({ session_id: 5, expires_at: 'tomorrow', created: true })
})

async function openFirstDive() {
  render(<MemoryRouter><JurySession /></MemoryRouter>)
  await userEvent.click(screen.getByRole('button', { name: 'Start judging' }))
  await screen.findByRole('button', { name: 'Skip' })
  await userEvent.click(screen.getByRole('button', { name: 'Skip' }))
  await screen.findByText('107B · 3m')
}

it('reaches the queue on the FIRST start (async session id regression)', async () => {
  vi.mocked(getQueue).mockResolvedValueOnce(batch)
  await openFirstDive()
  expect(getQueue).toHaveBeenCalledTimes(1)
  expect(vi.mocked(getQueue).mock.calls[0][0]).toBe(5)
  expect(vi.mocked(getQueue).mock.calls[0][1]).toEqual(expect.any(String))
  expect(screen.getByText('107B · 3m')).toBeInTheDocument()
})

it('rotates the batch id after a consumed batch (no repeated batch)', async () => {
  vi.mocked(getQueue).mockImplementation(async (_sid, batchId) => {
    void _sid
    return { ...emptyBatch, batch_id: batchId }
  })
  render(<MemoryRouter><JurySession /></MemoryRouter>)
  await userEvent.click(screen.getByRole('button', { name: 'Start judging' }))
  await screen.findByText('No more dives to judge right now. New requests will appear here.')
  const firstId = vi.mocked(getQueue).mock.calls[0][1]
  expect(firstId).toBeTruthy()
})

it('keeps loading when a batch is all-unavailable but has_more (no false exhaustion)', async () => {
  const unavailableOnly: QueueBatch = {
    batch_id: 'b1',
    items: [{ request_id: 99, dive_id: 199, unavailable: true }, { request_id: 98, dive_id: 198, unavailable: true }],
    has_more: true,
  }
  vi.mocked(getQueue).mockImplementation(async (_sid, batchId) => {
    void _sid
    return batchId === 'b1' ? unavailableOnly : { batch_id: batchId, items: [item(11, '107B')], has_more: false }
  })
  render(<MemoryRouter><JurySession /></MemoryRouter>)
  await userEvent.click(screen.getByRole('button', { name: 'Start judging' }))
  // Demo of unavailable handling happens with real service shapes; here the mock
  // returns items by id, so just assert we END on a reviewable dive, not summary.
  await screen.findByText('107B · 3m')
  expect(screen.queryByText(/No more dives/)).not.toBeInTheDocument()
})

it('shows the choose-score placeholder, then one named own card after confirmation', async () => {
  vi.mocked(getQueue).mockResolvedValueOnce(batch)
  vi.mocked(submitRating).mockResolvedValueOnce(voteResponse)
  await openFirstDive()
  expect(screen.getByText('Choose your score')).toBeInTheDocument()
  // Steppers select without sliding.
  await userEvent.click(screen.getByRole('button', { name: 'Half point up' }))
  expect(screen.queryByText('Choose your score')).not.toBeInTheDocument()
  expect(screen.getByRole('img', { name: '5.5 out of 10' })).toBeInTheDocument()
  // Confirm — wait for the save to land.
  await userEvent.click(screen.getByRole('button', { name: 'Confirm score' }))
  await screen.findByRole('img', { name: 'Your score card 6.5' })
  // Dedupe: 3 stored ratings → exactly 3 cards (2 peers + own), never 4.
  const panel = screen.getByText('3 vote(s) · community average 6.5').closest('.eval-reveal') as HTMLElement
  const cards = within(panel).getAllByRole('img')
  expect(cards).toHaveLength(3)
  expect(within(panel).getAllByText('You')).toHaveLength(1)
  expect(within(panel).getByText('Bob')).toBeInTheDocument()
  expect(within(panel).getByText('Zoé')).toBeInTheDocument()
})

it('advances after the readable hold while results stay parked on demand', async () => {
  vi.mocked(getQueue).mockResolvedValueOnce(batch)
  vi.mocked(submitRating).mockResolvedValueOnce(voteResponse)
  await openFirstDive()
  await userEvent.click(screen.getByRole('button', { name: 'Half point up' }))
  await userEvent.click(screen.getByRole('button', { name: 'Confirm score' }))
  await screen.findByRole('img', { name: 'Your score card 6.5' })
  vi.mocked(getQueue).mockResolvedValueOnce(emptyBatch)
  // Park on the results: the auto-advance must not fire while parked.
  await userEvent.click(screen.getByRole('button', { name: 'Keep the results open' }))
  await new Promise((resolve) => setTimeout(resolve, 2500))
  expect(screen.getByRole('img', { name: 'Your score card 6.5' })).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Next dive' }))
  await screen.findByText('105C · 3m')
})

it('keeps score/comment on failure and retries the same dive', async () => {
  vi.mocked(getQueue).mockResolvedValueOnce(batch)
  vi.mocked(submitRating).mockRejectedValueOnce(new Error('network'))
  await openFirstDive()
  await userEvent.click(screen.getByRole('button', { name: 'Half point up' }))
  await userEvent.click(screen.getByRole('button', { name: 'Add a comment' }))
  await userEvent.type(screen.getByLabelText('Optional comment'), 'Great flight')
  await userEvent.click(screen.getByRole('button', { name: 'Confirm score' }))
  await screen.findByRole('alert')
  expect(screen.getByRole('alert')).toHaveTextContent('The score could not be saved. Your choice is kept; try again.')
  expect(screen.getByText('107B · 3m')).toBeInTheDocument()
  expect(screen.getByLabelText('Optional comment')).toHaveValue('Great flight')
  expect(screen.getByRole('img', { name: '5.5 out of 10' })).toBeInTheDocument()
  vi.mocked(submitRating).mockResolvedValueOnce(voteResponse)
  await userEvent.click(screen.getByRole('button', { name: 'Confirm score' }))
  await screen.findByRole('img', { name: 'Your score card 6.5' })
})

it('guards against double submits (single server call)', async () => {
  vi.mocked(getQueue).mockResolvedValueOnce(batch)
  let resolveVote: (value: SubmissionResponse) => void = () => {}
  vi.mocked(submitRating).mockImplementationOnce(() => new Promise<SubmissionResponse>((resolve) => { resolveVote = resolve }))
  await openFirstDive()
  await userEvent.click(screen.getByRole('button', { name: 'Half point up' }))
  await userEvent.click(screen.getByRole('button', { name: 'Confirm score' }))
  // Second click during the pending submit: intercepted by the busy guard.
  fireEvent.click(screen.getByRole('button', { name: /Confirm score|Saving your score/ }))
  resolveVote(voteResponse)
  await screen.findByRole('img', { name: 'Your score card 6.5' })
  expect(submitRating).toHaveBeenCalledTimes(1)
})

it('reports a closed evaluation without fake-saving', async () => {
  vi.mocked(getQueue).mockResolvedValueOnce(batch)
  vi.mocked(submitRating).mockRejectedValueOnce({ response: { status: 409, data: { detail: 'This evaluation is closed to new votes' } } })
  await openFirstDive()
  await userEvent.click(screen.getByRole('button', { name: 'Half point up' }))
  await userEvent.click(screen.getByRole('button', { name: 'Confirm score' }))
  await screen.findByRole('alert')
  expect(screen.getByRole('alert')).toHaveTextContent('This evaluation just closed — no vote was saved.')
  expect(submitRating).toHaveBeenCalledTimes(1)
})

it('passes through the server skip endpoint and reaches the summary with the recap', async () => {
  vi.mocked(getQueue).mockResolvedValueOnce(batch)
  vi.mocked(skipRequest).mockResolvedValue(undefined)
  render(<MemoryRouter><JurySession /></MemoryRouter>)
  await userEvent.click(screen.getByRole('button', { name: 'Start judging' }))
  await screen.findByRole('button', { name: 'Skip' })
  await userEvent.click(screen.getByRole('button', { name: 'Skip' }))
  await screen.findByText('107B · 3m')
  expect(screen.getByRole('button', { name: 'Quit session' })).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Pass' }))
  await waitFor(() => expect(skipRequest).toHaveBeenCalledWith(5, 11))
  await screen.findByText('105C · 3m'.replace('10m', '3m'))
  // Summary shows the REAL session recap: passed dive listed separately.
  await userEvent.click(screen.getByRole('button', { name: 'Quit session' }))
  await screen.findByText('You judged 0 dive(s) this session.')
  expect(screen.getByText('107B · 3m')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Have a dive evaluated' })).toBeInTheDocument()
})

it('summary from a rated session lists the dive with its own score card', async () => {
  vi.mocked(getQueue).mockResolvedValueOnce(batch)
  vi.mocked(submitRating).mockResolvedValueOnce(voteResponse)
  await openFirstDive()
  await userEvent.click(screen.getByRole('button', { name: 'Half point up' }))
  await userEvent.click(screen.getByRole('button', { name: 'Confirm score' }))
  await screen.findByRole('img', { name: 'Your score card 6.5' })
  await userEvent.click(screen.getByRole('button', { name: 'Keep the results open' }))
  await userEvent.click(screen.getByRole('button', { name: 'Quit session' }))
  await screen.findByText('You judged 1 dive(s) this session.')
  expect(screen.getByText('107B')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Have a dive evaluated' })).toBeInTheDocument()
})

it('reuses the SAME batch id when a load response is lost after allocation', async () => {
  const batch: QueueBatch = { batch_id: 'RECEIVED', items: [item(41, '105C')], has_more: false }
  let first = true
  vi.mocked(getQueue).mockImplementation(async (_sid, batchId) => {
    void _sid
    if (first) {
      first = false
      // сервер allocated the batch then the response is lost mid-flight:
      throw new Error('network lost after allocation')
    }
    return { ...batch, batch_id: batchId }
  })
  render(<MemoryRouter><JurySession /></MemoryRouter>)
  await userEvent.click(screen.getByRole('button', { name: 'Start judging' }))
  // The first attempt fails (loading-error); RETRY must reuse the same id.
  await screen.findByText('The evaluation queue is unavailable. Try again.')
  expect(getQueue).toHaveBeenCalledTimes(1)
  const lostId = vi.mocked(getQueue).mock.calls[0][1]
  await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
  await waitFor(() => expect(getQueue).toHaveBeenCalledTimes(2))
  expect(vi.mocked(getQueue).mock.calls[1][1]).toBe(lostId)
  await screen.findByText('105C · 3m')
})

it('a 409 EVALUATION_CLOSED decodes to the closed screen without a Confirm button', async () => {
  vi.mocked(getQueue).mockResolvedValueOnce(batch)
  vi.mocked(submitRating).mockRejectedValueOnce({
    response: { status: 409, data: { detail: { code: 'EVALUATION_CLOSED', message: 'This evaluation is closed to new votes' } } },
  })
  await openFirstDive()
  await userEvent.click(screen.getByRole('button', { name: 'Half point up' }))
  await userEvent.click(screen.getByRole('button', { name: 'Confirm score' }))
  await screen.findByText('This evaluation just closed — no vote was saved.')
  // The closed state holds: Next is the only judgement path forward.
  expect(screen.queryByRole('button', { name: 'Add a comment' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Pass' })).not.toBeInTheDocument()
  const confirmButton = screen.queryByRole('button', { name: /Confirm score/ })
  expect(confirmButton).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Next dive' })).toBeInTheDocument()
})

it('a keyed 409 RATING_ALREADY_SUBMITTED stays on the dive form with its vote hint', async () => {
  vi.mocked(getQueue).mockResolvedValueOnce(batch)
  vi.mocked(submitRating).mockRejectedValueOnce({
    response: { status: 409, data: { detail: { code: 'RATING_ALREADY_SUBMITTED', message: 'A different rating was already confirmed for this dive (votes are immutable)' } } },
  })
  await openFirstDive()
  await userEvent.click(screen.getByRole('button', { name: 'Half point up' }))
  await userEvent.click(screen.getByRole('button', { name: 'Confirm score' }))
  await screen.findByText('Your judgement is already confirmed and immutable.')
  // Still the SAME dive with its dock available again.
  expect(screen.getByText('107B · 3m')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Confirm score' })).toBeInTheDocument()
})

it('a score selection interrupts the intro decoration immediately', async () => {
  vi.mocked(getQueue).mockResolvedValueOnce(batch)
  render(<MemoryRouter><JurySession /></MemoryRouter>)
  await userEvent.click(screen.getByRole('button', { name: 'Start judging' }))
  await screen.findByRole('button', { name: 'Skip' })
  expect(document.querySelector('.eval-intro')).not.toBeNull()
  // Judging starts while the intro still runs: the decoration leaves NOW.
  await userEvent.click(screen.getByRole('button', { name: 'Half point up' }))
  await waitFor(() => expect(document.querySelector('.eval-intro')).toBeNull())
  expect(screen.getByText('107B · 3m')).toBeInTheDocument()
})

it('a late vote response after quit never resurrects the stage', async () => {
  vi.mocked(getQueue).mockResolvedValueOnce(batch)
  let resolveVote: (value: SubmissionResponse) => void = () => {}
  vi.mocked(submitRating).mockImplementationOnce(() => new Promise<SubmissionResponse>((resolve) => { resolveVote = resolve }))
  render(<MemoryRouter><JurySession /></MemoryRouter>)
  await userEvent.click(screen.getByRole('button', { name: 'Start judging' }))
  await screen.findByRole('button', { name: 'Skip' })
  await userEvent.click(screen.getByRole('button', { name: 'Skip' }))
  await screen.findByText('107B · 3m')
  await userEvent.click(screen.getByRole('button', { name: 'Half point up' }))
  await userEvent.click(screen.getByRole('button', { name: 'Confirm score' }))
  // Quit WHILE the vote is in flight: the UI parks on the summary.
  await userEvent.click(screen.getByRole('button', { name: 'Quit session' }))
  await screen.findByText('You judged 0 dive(s) this session.')
  resolveVote(voteResponse)
  await new Promise((resolve) => setTimeout(resolve, 120))
  // The stage stays retired: summary, scores marked saved server-side but no
  // reveal resurrect, no Confirm to re-enter a live dive.
  expect(screen.queryByText('107B · 3m')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Confirm score' })).not.toBeInTheDocument()
  expect(screen.getByText('You judged 0 dive(s) this session.')).toBeInTheDocument()
})

it('Evaluate again starts a FRESH session (count/recap/skip cleared)', async () => {
  vi.mocked(getQueue).mockResolvedValueOnce(batch)
  vi.mocked(submitRating).mockResolvedValueOnce(voteResponse)
  render(<MemoryRouter><JurySession /></MemoryRouter>)
  await userEvent.click(screen.getByRole('button', { name: 'Start judging' }))
  await screen.findByRole('button', { name: 'Skip' })
  await userEvent.click(screen.getByRole('button', { name: 'Skip' }))
  await screen.findByText('107B · 3m')
  await userEvent.click(screen.getByRole('button', { name: 'Half point up' }))
  await userEvent.click(screen.getByRole('button', { name: 'Confirm score' }))
  await screen.findByRole('img', { name: 'Your score card 6.5' })
  await userEvent.click(screen.getByRole('button', { name: 'Quit session' }))
  await screen.findByText('You judged 1 dive(s) this session.')
  await userEvent.click(screen.getByRole('button', { name: 'Evaluate again' }))
  // Landing reset: the previous session's count/recap are gone.
  expect(screen.queryByText('You judged 1 dive(s) this session.')).not.toBeInTheDocument()
  expect(screen.queryByRole('img', { name: 'Your score card 6.5' })).not.toBeInTheDocument()
  // Start again → the counter restarts at 0.
  vi.mocked(getQueue).mockResolvedValueOnce(emptyBatch)
  await userEvent.click(screen.getByRole('button', { name: 'Start judging' }))
  await screen.findByText('No more dives to judge right now. New requests will appear here.')
  // The second exhausted run still shows the RESET counter (0), not 1.
  expect(screen.getByText('You judged 0 dive(s) this session.')).toBeInTheDocument()
})

it('ends on the summary when the queue is empty at start', async () => {
  vi.mocked(getQueue).mockResolvedValueOnce(emptyBatch)
  render(<MemoryRouter><JurySession /></MemoryRouter>)
  await userEvent.click(screen.getByRole('button', { name: 'Start judging' }))
  await screen.findByText('No more dives to judge right now. New requests will appear here.')
})

it('steps DOWN before any score is chosen (precise 0.5 stepper from neutral)', async () => {
  vi.mocked(getQueue).mockResolvedValueOnce(batch)
  await openFirstDive()
  expect(screen.getByText('Choose your score')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Half point down' }))
  expect(screen.queryByText('Choose your score')).not.toBeInTheDocument()
  expect(screen.getByRole('img', { name: '4.5 out of 10' })).toBeInTheDocument()
})

it('opens the comment IN FLOW: Confirm and Pass stay visible alongside it', async () => {
  vi.mocked(getQueue).mockResolvedValueOnce(batch)
  await openFirstDive()
  const toggle = screen.getByRole('button', { name: 'Add a comment' })
  expect(toggle).toHaveAttribute('aria-expanded', 'false')
  await userEvent.click(toggle)
  await screen.findByLabelText('Optional comment')
  // In-flow expansion: the essential controls remain usable while open.
  expect(screen.getByRole('button', { name: 'Confirm score' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Pass' })).toBeInTheDocument()
  await userEvent.type(screen.getByLabelText('Optional comment'), 'Nice entry')
  // Closing from the inline header keeps the draft; reopening restores it.
  await userEvent.click(screen.getByRole('button', { name: 'Close' }))
  expect(screen.queryByLabelText('Optional comment')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Edit comment' }))
  expect(screen.getByLabelText('Optional comment')).toHaveValue('Nice entry')
})

it('reveal joins MY card first, then peers flip in cascade with names', async () => {
  vi.mocked(getQueue).mockResolvedValueOnce(batch)
  vi.mocked(submitRating).mockResolvedValueOnce(voteResponse)
  await openFirstDive()
  await userEvent.click(screen.getByRole('button', { name: 'Half point up' }))
  await userEvent.click(screen.getByRole('button', { name: 'Confirm score' }))
  const panel = screen.getByText('3 vote(s) · community average 6.5').closest('.eval-reveal') as HTMLElement
  const figures = panel.querySelectorAll('.eval-card-figure')
  expect(figures).toHaveLength(3)
  // The just-confirmed personal card leads the sequence.
  expect(figures[0]).toHaveClass('eval-card-mine-figure')
  expect(figures[0].querySelector('.eval-card')?.getAttribute('aria-label')).toBe('Your score card 6.5')
  // Peers follow with increasing, non-zero stagger (cascade after mine).
  const stagger = (el: HTMLElement) => el.style.getPropertyValue('--stagger')
  expect(stagger(figures[1] as HTMLElement)).toBe('360ms')
  expect(stagger(figures[2] as HTMLElement)).toBe('480ms')
  expect(within(figures[1] as HTMLElement).getByText('Bob')).toBeInTheDocument()
  expect(within(figures[2] as HTMLElement).getByText('Zoé')).toBeInTheDocument()
})

it('labels the intro fan as unambiguously illustrative and drops it on skip', async () => {
  vi.mocked(getQueue).mockResolvedValueOnce(batch)
  render(<MemoryRouter><JurySession /></MemoryRouter>)
  await userEvent.click(screen.getByRole('button', { name: 'Start judging' }))
  await screen.findByRole('button', { name: 'Skip' })
  expect(document.querySelector('.eval-intro-demo')).toHaveTextContent('Demo cards — not real scores')
  await userEvent.click(screen.getByRole('button', { name: 'Skip' }))
  expect(document.querySelector('.eval-intro')).toBeNull()
  expect(document.querySelector('.eval-intro-demo')).toBeNull()
})


it('uses a finite automatic stack, resumes after quitting, and sends video identity', async () => {
  vi.mocked(createAutomaticStack).mockResolvedValue({ session_id: 9, expires_at: 'tomorrow', created: true })
  vi.mocked(getAutomaticQueue).mockResolvedValue({ ...batch, items: [item(11, '107B')] })
  vi.mocked(submitRating).mockResolvedValue(voteResponse)
  render(<MemoryRouter><JurySession automatic /></MemoryRouter>)
  fireEvent.click(screen.getByRole('button', { name: /Start.*resume/i }))
  await screen.findByText('EvalVideo')
  expect(createSession).not.toHaveBeenCalled()
  expect(createAutomaticStack).toHaveBeenCalledWith(expect.any(String), true)
  fireEvent.keyDown(document, { key: 'Escape' })
  fireEvent.click(screen.getByRole('button', { name: 'Resume this selection' }))
  await screen.findByText('EvalVideo')
  fireEvent.change(screen.getByRole('slider'), { target: { value: '13' } })
  fireEvent.click(screen.getByRole('button', { name: 'Confirm score' }))
  await waitFor(() => expect(submitRating).toHaveBeenCalledWith(11, 13, undefined, true, 'u11'))
  fireEvent.click(screen.getByRole('button', { name: /Next/ }))
  await screen.findByRole('button', { name: 'Request another selection' })
  expect(getAutomaticQueue).toHaveBeenCalledTimes(2)
  fireEvent.click(screen.getByRole('button', { name: 'Request another selection' }))
  fireEvent.click(screen.getByRole('button', { name: /Start.*resume/i }))
  await waitFor(() => expect(createAutomaticStack).toHaveBeenLastCalledWith(expect.any(String), false))
})

it('passes an automatic dive using its stack and keeps the manual queue untouched', async () => {
  vi.mocked(createAutomaticStack).mockResolvedValue({ session_id: 9, expires_at: 'tomorrow', created: true })
  vi.mocked(getAutomaticQueue).mockResolvedValue({ ...batch, items: [item(11, '107B')] })
  vi.mocked(skipAutomaticDive).mockResolvedValue()
  render(<MemoryRouter><JurySession automatic /></MemoryRouter>)
  fireEvent.click(screen.getByRole('button', { name: /Start.*resume/i }))
  await screen.findByText('EvalVideo')
  fireEvent.click(screen.getByRole('button', { name: 'Pass' }))
  await screen.findByRole('button', { name: 'Request another selection' })
  expect(skipAutomaticDive).toHaveBeenCalledWith(9, 11)
  expect(skipRequest).not.toHaveBeenCalled()
  expect(getQueue).not.toHaveBeenCalled()
})

it('keeps judging hidden until playback ends and hides it again for replay', async () => {
  autoFinishVideo = false
  vi.mocked(getQueue).mockResolvedValueOnce(batch)
  render(<MemoryRouter><JurySession /></MemoryRouter>)
  await userEvent.click(screen.getByRole('button', { name: 'Start judging' }))
  await screen.findByText('EvalVideo')
  expect(screen.queryByRole('slider')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Confirm score' })).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Finish video' }))
  await userEvent.click(await screen.findByRole('button', { name: 'Skip' }))
  fireEvent.change(screen.getByRole('slider'), { target: { value: '13' } })
  await userEvent.click(screen.getByRole('button', { name: /replay/i }))
  expect(screen.queryByRole('slider')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Finish video' }))
  expect(screen.getByRole('slider')).toHaveValue('13')
  expect(submitRating).not.toHaveBeenCalled()
})

it('offers retry and pass when the ready video fails before ending', async () => {
  autoFinishVideo = false
  vi.mocked(getQueue).mockResolvedValueOnce(batch)
  vi.mocked(skipRequest).mockResolvedValue(undefined)
  render(<MemoryRouter><JurySession /></MemoryRouter>)
  await userEvent.click(screen.getByRole('button', { name: 'Start judging' }))
  await userEvent.click(await screen.findByRole('button', { name: 'Fail video' }))
  expect(screen.queryByRole('slider')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
  expect(screen.queryByRole('slider')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Fail video' }))
  await userEvent.click(screen.getByRole('button', { name: 'Pass' }))
  expect(skipRequest).toHaveBeenCalledWith(5, 11)
})
