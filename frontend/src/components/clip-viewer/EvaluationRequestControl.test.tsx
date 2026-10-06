import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import EvaluationRequestControl from './EvaluationRequestControl'
import type { Attempt } from '../../utils/attemptPresentation'
import type { EvaluationMediaStatus } from '../../services/evaluationApi'

vi.mock('../../services/evaluationApi', () => ({
  EVALUATION_PROMPT_MAX: 1000,
  putEvaluationRequest: vi.fn(),
  getEvaluationRequest: vi.fn(),
  getEvaluationMediaStatus: vi.fn(),
  prepareEvaluationMedia: vi.fn(),
}))

import {
  getEvaluationMediaStatus,
  prepareEvaluationMedia,
  putEvaluationRequest,
} from '../../services/evaluationApi'

const attempt: Attempt = {
  id: 7,
  diver_id: 2,
  dive_code: '101B',
  performance: 'G',
  performance_numeric: 3,
  height: '3m',
  dive_datetime: '2026-10-04T10:00:00',
  session_id: 1,
  is_lineup: false,
  is_sync: false,
  platform_type: 'springboard',
  official_dd: 1.5,
  visibility: 'private',
  can_manage: true,
  video_uuid: 'video-7',
}

const readyStatus: EvaluationMediaStatus = {
  request_id: 3,
  dive_id: 7,
  video_uuid: 'video-7',
  status: 'ready',
  poster_url: '/poster',
  playback_url: '/play',
  available_renditions: ['proxy_720p', 'poster'],
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(getEvaluationMediaStatus).mockResolvedValue(readyStatus)
})

it('activates from the Library and reveals the jury comment', async () => {
  vi.mocked(putEvaluationRequest).mockResolvedValue({
    id: 3, dive_id: 7, active: true, prompt: 'Focus on the entry', created_at: 'x', updated_at: 'y',
  })
  const onUpdate = vi.fn()
  render(<EvaluationRequestControl attempt={attempt} onUpdate={onUpdate} />)
  expect(screen.queryByLabelText('Comment for the jury (optional)')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('switch'))
  await waitFor(() => expect(putEvaluationRequest).toHaveBeenCalledWith(7, { active: true, prompt: undefined }))
  expect(onUpdate).toHaveBeenCalledWith(expect.objectContaining({
    evaluation_request: expect.objectContaining({ active: true, prompt: 'Focus on the entry' }),
  }))
  await waitFor(() => expect(screen.getByLabelText('Comment for the jury (optional)')).toBeInTheDocument())
  expect(screen.getByLabelText('Comment for the jury (optional)')).toHaveValue('Focus on the entry')
})

it('saves the comment explicitly, one request per save, without clearing other state', async () => {
  vi.mocked(putEvaluationRequest).mockResolvedValue({
    id: 3, dive_id: 7, active: true, prompt: 'Entry power', created_at: 'x', updated_at: 'y',
  })
  const onUpdate = vi.fn()
  render(<EvaluationRequestControl attempt={{ ...attempt, evaluation_request: { id: 3, dive_id: 7, active: true, prompt: null, created_at: 'x', updated_at: 'y' } }} onUpdate={onUpdate} />)
  const textarea = screen.getByLabelText('Comment for the jury (optional)')
  await userEvent.type(textarea, 'Entry power')
  expect(putEvaluationRequest).not.toHaveBeenCalled() // typing alone never saves
  await userEvent.click(screen.getByRole('button', { name: 'Save comment' }))
  await waitFor(() => expect(putEvaluationRequest).toHaveBeenCalledWith(7, { active: true, prompt: 'Entry power' }))
  expect(onUpdate).toHaveBeenCalledWith(expect.objectContaining({
    evaluation_request: expect.objectContaining({ prompt: 'Entry power' }),
  }))
})

it('deactivates without sending the prompt so the stored text survives', async () => {
  vi.mocked(putEvaluationRequest).mockResolvedValue({
    id: 3, dive_id: 7, active: false, prompt: 'Kept', created_at: 'x', updated_at: 'y',
  })
  const onUpdate = vi.fn()
  render(<EvaluationRequestControl attempt={{ ...attempt, evaluation_request: { id: 3, dive_id: 7, active: true, prompt: 'Kept', created_at: 'x', updated_at: 'y' } }} onUpdate={onUpdate} />)
  await userEvent.click(screen.getByRole('switch'))
  await waitFor(() => expect(putEvaluationRequest).toHaveBeenCalledWith(7, { active: false }))
  expect(onUpdate).toHaveBeenCalledWith(expect.objectContaining({
    evaluation_request: expect.objectContaining({ active: false, prompt: 'Kept' }),
  }))
})

it('keeps state and shows a retry hint on update failure', async () => {
  vi.mocked(putEvaluationRequest).mockRejectedValue(new Error('denied'))
  const onUpdate = vi.fn()
  render(<EvaluationRequestControl attempt={attempt} onUpdate={onUpdate} />)
  await userEvent.click(screen.getByRole('switch'))
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Could not update the evaluation request. Try again.'))
  expect(onUpdate).not.toHaveBeenCalled()
  expect(screen.getByRole('switch')).not.toBeChecked()
})

it('shows the preparation state with retry for an active request whose media is not ready', async () => {
  vi.mocked(getEvaluationMediaStatus).mockResolvedValue({
    ...readyStatus, status: 'missing', poster_url: null, playback_url: null,
  })
  vi.mocked(prepareEvaluationMedia).mockResolvedValue({ ...readyStatus, created_jobs: ['proxy_720p'], reused_jobs: [] })
  render(<EvaluationRequestControl attempt={{ ...attempt, evaluation_request: { id: 3, dive_id: 7, active: true, prompt: null, created_at: 'x', updated_at: 'y' } }} onUpdate={vi.fn()} />)
  await screen.findByText('Video in preparation.')
  await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
  await waitFor(() => expect(prepareEvaluationMedia).toHaveBeenCalledWith(3))
  await waitFor(() => expect(getEvaluationMediaStatus).toHaveBeenCalledWith(3))
})

it('stays hidden for dives without a video', () => {
  render(<EvaluationRequestControl attempt={{ ...attempt, video_uuid: null }} onUpdate={vi.fn()} />)
  expect(screen.queryByRole('switch')).not.toBeInTheDocument()
})
