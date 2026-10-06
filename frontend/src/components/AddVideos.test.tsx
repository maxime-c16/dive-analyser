import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import AddVideos from './AddVideos'
import { api } from '../services/api'
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { display_name: 'Bob', divers: [{ diver_id: 4, access_kind: 'OWNER' }] } }) }))
vi.mock('../services/api', () => ({ api: { post: vi.fn() } }))
URL.createObjectURL = vi.fn(() => 'blob:preview')
URL.revokeObjectURL = vi.fn()

function select() {
  fireEvent.change(screen.getByLabelText('Select videos'), { target: { files: [new File(['video'], 'one.mov', { type: 'video/quicktime' }), new File(['video'], 'two.mp4', { type: 'video/mp4' })] } })
  fireEvent.change(screen.getByLabelText('Code'), { target: { value: '103B' } })
}

describe('browser clip stack', () => {
  it('saves each clip privately under its owner and advances only after success', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: {} })
    render(<AddVideos onAdded={vi.fn()} />)
    select()
    expect(screen.getByText('Video 1 / 2')).toBeInTheDocument()
    fireEvent.click(screen.getByText('Save and next'))
    await waitFor(() => expect(screen.getByText('Video 2 / 2')).toBeInTheDocument())
    const body = vi.mocked(api.post).mock.calls[0][1] as FormData
    expect(body.get('diver_id')).toBe('4')
    expect(body.get('visibility')).toBe('private')
    expect(body.get('dive_code')).toBe('103B')
    fireEvent.change(screen.getByLabelText('Code'), { target: { value: '101C' } })
    fireEvent.click(screen.getByText('Save and finish'))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })
  it('keeps a failed clip and reuses the upload identity on retry', async () => {
    vi.mocked(api.post).mockReset().mockRejectedValueOnce(new Error('offline')).mockResolvedValue({ data: {} })
    render(<AddVideos onAdded={vi.fn()} />)
    select()
    fireEvent.click(screen.getByText('Save and next'))
    await screen.findByRole('alert')
    expect(screen.getByText('Video 1 / 2')).toBeInTheDocument()
    const first = vi.mocked(api.post).mock.calls[0][1] as FormData
    fireEvent.click(screen.getByText('Save and next'))
    await screen.findByText('Video 2 / 2')
    expect((vi.mocked(api.post).mock.calls[1][1] as FormData).get('upload_id')).toBe(first.get('upload_id'))
  })
})

describe('evaluation request in the import flow', () => {
  it('sends evaluation_requested false by default and never a prompt', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: {} })
    render(<AddVideos onAdded={vi.fn()} />)
    select()
    fireEvent.click(screen.getByText('Save and next'))
    await screen.findByText('Video 2 / 2')
    const body = vi.mocked(api.post).mock.calls[0][1] as FormData
    expect(body.get('evaluation_requested')).toBe('false')
    expect(body.get('evaluation_prompt')).toBeNull()
  })

  it('requests an evaluation with its optional prompt without touching other clip fields', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: {} })
    render(<AddVideos onAdded={vi.fn()} />)
    select()
    fireEvent.change(screen.getByLabelText('Notes'), { target: { value: 'personal note' } })
    fireEvent.click(screen.getByLabelText('Request community evaluation'))
    fireEvent.change(screen.getByLabelText('Comment for the jury'), { target: { value: 'Judge the entry' } })
    fireEvent.click(screen.getByText('Save and next'))
    await screen.findByText('Video 2 / 2')
    const body = vi.mocked(api.post).mock.calls[0][1] as FormData
    expect(body.get('evaluation_requested')).toBe('true')
    expect(body.get('evaluation_prompt')).toBe('Judge the entry')
    expect(body.get('notes')).toBe('personal note')
    expect(body.get('visibility')).toBe('private')
  })
})

it('accepts armstand codes in the browser form', async () => {
  vi.mocked(api.post).mockReset().mockResolvedValue({ data: {} })
  render(<AddVideos onAdded={vi.fn()} />)
  select()
  const code = screen.getByLabelText('Code') as HTMLInputElement
  fireEvent.change(code, { target: { value: '6031B' } })
  expect(code.checkValidity()).toBe(false)
  fireEvent.change(code, { target: { value: '603B' } })
  expect(code.checkValidity()).toBe(true)
  fireEvent.click(screen.getByText('Save and next'))
  await screen.findByText('Video 2 / 2')
  expect((vi.mocked(api.post).mock.calls[0][1] as FormData).get('dive_code')).toBe('603B')
})
