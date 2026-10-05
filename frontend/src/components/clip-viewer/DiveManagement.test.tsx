import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import DiveManagement from './DiveManagement'
import DiveVisibilityControl from './DiveVisibilityControl'
import ClipViewer from './ClipViewer'
import { MemoryRouter } from 'react-router-dom'
import type { Attempt } from '../../utils/attemptPresentation'
import api from '../../services/api'

vi.mock('../../services/api', () => { const api = { get: vi.fn(), put: vi.fn(), delete: vi.fn() }; return { default: api, api } })
vi.mock('../DiveVideoPlayer', () => ({ default: () => <div>Video</div> }))
const attempt: Attempt = { id: 7, dive_code: '101B', performance: 'G', performance_numeric: 3, height: '3m', dive_datetime: '2026-10-04T10:00:00', session_id: 1, is_lineup: false, is_sync: false, platform_type: 'springboard', official_dd: 1.5, visibility: 'public', can_manage: true, notes: 'My note' }
beforeEach(() => { vi.clearAllMocks(); vi.mocked(api.get).mockResolvedValue({ data: { liked: false, like_count: 0, comment_count: 0 } }) })

it('saves personal notes and updates the reader only after success', async () => {
  const onUpdate = vi.fn()
  vi.mocked(api.put).mockResolvedValue({ data: { ...attempt, notes: 'New note' } })
  render(<DiveManagement attempt={attempt} onUpdate={onUpdate} onDelete={vi.fn()} />)
  await userEvent.clear(screen.getByLabelText('Personal notes'))
  await userEvent.type(screen.getByLabelText('Personal notes'), 'New note')
  await userEvent.click(screen.getByRole('button', { name: 'Save changes' }))
  await waitFor(() => expect(api.put).toHaveBeenCalledWith('/api/v1/dives/7', expect.objectContaining({ notes: 'New note' })))
  expect(onUpdate).toHaveBeenCalledWith(expect.objectContaining({ notes: 'New note' }))
  expect(screen.getByRole('status')).toHaveTextContent('Dive saved.')
})

it('requires a second confirmation before deleting and keeps the reader on failure', async () => {
  const onDelete = vi.fn()
  vi.mocked(api.delete).mockRejectedValue(new Error('denied'))
  render(<DiveManagement attempt={attempt} onUpdate={vi.fn()} onDelete={onDelete} />)
  await userEvent.click(screen.getByRole('button', { name: 'Delete dive' }))
  expect(api.delete).not.toHaveBeenCalled()
  await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
  expect(screen.queryByRole('button', { name: 'Confirm deletion' })).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Delete dive' }))
  await userEvent.click(screen.getByRole('button', { name: 'Confirm deletion' }))
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('could not be deleted'))
  expect(onDelete).not.toHaveBeenCalled()
})

it('hides management controls for another member’s public dive', () => {
  render(<MemoryRouter><ClipViewer attempt={{ ...attempt, can_manage: false }} attempts={[attempt]} onClose={vi.fn()} onMove={vi.fn()} playbackRate={1} onPlaybackRateChange={vi.fn()} onUpdate={vi.fn()} onDelete={vi.fn()} /></MemoryRouter>)
  expect(screen.queryByRole('button', { name: 'Manage dive' })).not.toBeInTheDocument()
  expect(screen.getByText('Public dive')).toBeInTheDocument()
})


it('changes visibility directly from the compact control and retains it on failure', async () => {
  const onUpdate = vi.fn()
  vi.mocked(api.put).mockRejectedValue(new Error('denied'))
  render(<DiveVisibilityControl attempt={attempt} onUpdate={onUpdate} />)
  await userEvent.selectOptions(screen.getByLabelText('Dive visibility'), 'private')
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Could not save.'))
  expect(onUpdate).not.toHaveBeenCalled()
  expect(screen.getByLabelText('Dive visibility')).toHaveValue('public')
  vi.mocked(api.put).mockResolvedValue({ data: { ...attempt, visibility: 'private' } })
  await userEvent.selectOptions(screen.getByLabelText('Dive visibility'), 'private')
  await waitFor(() => expect(onUpdate).toHaveBeenCalledWith(expect.objectContaining({ visibility: 'private' })))
  expect(api.put).toHaveBeenLastCalledWith('/api/v1/dives/7', { visibility: 'private' })
})
