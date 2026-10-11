import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import AddVideos from './AddVideos'
import { api } from '../services/api'
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { display_name: 'Bob', divers: [{ diver_id: 4, access_kind: 'OWNER' }] } }) }))
vi.mock('../services/api', () => ({ api: { post: vi.fn(), get: vi.fn(), put: vi.fn() } }))
URL.createObjectURL = vi.fn(() => 'blob:preview')
URL.revokeObjectURL = vi.fn()

function select() {
  fireEvent.change(screen.getByLabelText('Select videos'), { target: { files: [new File(['video'], 'one.mov', { type: 'video/quicktime' }), new File(['video'], 'two.mp4', { type: 'video/mp4' })] } })
  fireEvent.change(screen.getByLabelText('Code'), { target: { value: '103B' } })
}

describe('browser clip stack', () => {
  it('saves each clip privately under its owner and advances only after success', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { status: 'ready' } })
    render(<AddVideos onAdded={vi.fn()} />)
    select()
    expect(screen.getByText('Video 1 / 2')).toBeInTheDocument()
    fireEvent.click(screen.getByText('Save and next'))
    await waitFor(() => expect(screen.getByText('Video 2 / 2')).toBeInTheDocument())
    const body = vi.mocked(api.post).mock.calls[0][1] as Record<string, any>
    expect(body['diver_id']).toBe(4)
    expect(body['visibility']).toBe('private')
    expect(body['dive_code']).toBe('103B')
    fireEvent.change(screen.getByLabelText('Code'), { target: { value: '101C' } })
    fireEvent.click(screen.getByText('Save and finish'))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })
  it('keeps a failed clip and reuses the upload identity on retry', async () => {
    vi.mocked(api.post).mockReset().mockRejectedValueOnce(new Error('offline')).mockResolvedValue({ data: { status: 'ready' } })
    render(<AddVideos onAdded={vi.fn()} />)
    select()
    fireEvent.click(screen.getByText('Save and next'))
    await screen.findByRole('alert')
    expect(screen.getByText('Video 1 / 2')).toBeInTheDocument()
    const first = vi.mocked(api.post).mock.calls[0][1] as Record<string, any>
    fireEvent.click(screen.getByText('Save and next'))
    await screen.findByText('Video 2 / 2')
    expect((vi.mocked(api.post).mock.calls[1][1] as Record<string, any>).upload_id).toBe(first['upload_id'])
  })
})

describe('evaluation request in the import flow', () => {
  it('sends evaluation_requested false by default and never a prompt', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { status: 'ready' } })
    render(<AddVideos onAdded={vi.fn()} />)
    select()
    fireEvent.click(screen.getByText('Save and next'))
    await screen.findByText('Video 2 / 2')
    const body = vi.mocked(api.post).mock.calls[0][1] as Record<string, any>
    expect(body['evaluation_requested']).toBe(false)
    expect(body['evaluation_prompt']).toBe('')
  })

  it('requests an evaluation with its optional prompt without touching other clip fields', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { status: 'ready' } })
    render(<AddVideos onAdded={vi.fn()} />)
    select()
    fireEvent.change(screen.getByLabelText('Notes'), { target: { value: 'personal note' } })
    fireEvent.click(screen.getByLabelText('Request community evaluation'))
    fireEvent.change(screen.getByLabelText('Comment for the jury'), { target: { value: 'Judge the entry' } })
    fireEvent.click(screen.getByText('Save and next'))
    await screen.findByText('Video 2 / 2')
    const body = vi.mocked(api.post).mock.calls[0][1] as Record<string, any>
    expect(body['evaluation_requested']).toBe(true)
    expect(body['evaluation_prompt']).toBe('Judge the entry')
    expect(body['notes']).toBe('personal note')
    expect(body['visibility']).toBe('private')
  })
})

it('accepts armstand codes in the browser form', async () => {
  vi.mocked(api.post).mockReset().mockResolvedValue({ data: { status: 'ready' } })
  render(<AddVideos onAdded={vi.fn()} />)
  select()
  const code = screen.getByLabelText('Code') as HTMLInputElement
  fireEvent.change(code, { target: { value: '6031B' } })
  expect(code.checkValidity()).toBe(false)
  fireEvent.change(code, { target: { value: '603B' } })
  expect(code.checkValidity()).toBe(true)
  fireEvent.click(screen.getByText('Save and next'))
  await screen.findByText('Video 2 / 2')
  expect((vi.mocked(api.post).mock.calls[0][1] as Record<string, any>).dive_code).toBe('603B')
})

it('isolates the import, confirms Escape cancellation, then restores the Add videos trigger', async () => {
  const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
  const added = vi.fn()
  render(<AddVideos onAdded={added} />)
  select()
  expect(screen.getByRole('button', { name: 'Add videos' }).closest('[inert]')).not.toBeNull()
  fireEvent.keyDown(document, { key: 'Escape' })
  expect(screen.getByRole('dialog')).toBeInTheDocument()
  expect(added).not.toHaveBeenCalled()
  fireEvent.keyDown(document, { key: 'Escape' })
  await waitFor(() => expect(screen.getByRole('button', { name: 'Add videos' })).toHaveFocus())
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(document.body.style.overflow).toBe('')
  expect(added).toHaveBeenCalledTimes(1)
  confirm.mockRestore()
})

it('does not cancel an upload in progress with Escape', async () => {
  let finish!: (value: unknown) => void
  vi.mocked(api.post).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }) as any)
  const confirm = vi.spyOn(window, 'confirm')
  render(<AddVideos onAdded={vi.fn()} />)
  select(); fireEvent.click(screen.getByText('Save and next'))
  await screen.findByRole('status')
  fireEvent.keyDown(document, { key: 'Escape' })
  expect(confirm).not.toHaveBeenCalled()
  expect(screen.getByRole('dialog')).toBeInTheDocument()
  finish({ data: { status: 'ready' } }); await screen.findByText('Video 2 / 2')
  confirm.mockRestore()
})
it('keeps the current clip visible while its durable job is processing', async () => {
  vi.mocked(api.post).mockReset().mockResolvedValue({ data: { status: 'queued' } })
  vi.mocked(api.get).mockReset().mockResolvedValue({ data: { status: 'ready', dive_id: 123 } })
  render(<AddVideos onAdded={vi.fn()} />)
  select(); fireEvent.click(screen.getByText('Save and next'))
  await screen.findByRole('status')
  expect(screen.getByText('Video 1 / 2')).toBeInTheDocument()
  await waitFor(() => expect(screen.getByText('Video 2 / 2')).toBeInTheDocument(), { timeout: 3500 })
  expect(api.get).toHaveBeenCalledWith(expect.stringMatching(/^\/api\/v1\/dives\/uploads\//))
})

it('reserves before sending raw video bytes to the authorized content route', async () => {
  vi.mocked(api.post).mockReset().mockResolvedValue({ data: { status: 'receiving' } })
  vi.mocked(api.put).mockReset().mockResolvedValue({ data: { status: 'ready' } })
  render(<AddVideos onAdded={vi.fn()} />)
  select(); fireEvent.click(screen.getByText('Save and next'))
  await screen.findByText('Video 2 / 2')
  expect(api.post).toHaveBeenCalledWith('/api/v1/dives/uploads', expect.objectContaining({ filename: 'one.mov', diver_id: 4 }))
  expect(api.put).toHaveBeenCalledWith(expect.stringMatching(/\/content$/), expect.any(File), expect.objectContaining({ headers: { 'Content-Type': 'application/octet-stream' } }))
})
