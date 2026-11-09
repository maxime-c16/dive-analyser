import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import TechniqueSetup from './TechniqueSetup'
import '../../i18n'
const post = vi.fn(), get = vi.fn()
vi.mock('../../services/api', () => ({ api: { post: (...a: unknown[]) => post(...a), get: (...a: unknown[]) => get(...a) } }))
vi.mock('../clip-viewer/ClipViewer', () => ({ default: ({ attempt, attempts, onMove, workflow }: any) => <div><p>Viewing clip {attempt.id}</p><p>Window size {attempts.length}</p><button onClick={() => onMove(attempts[attempts.length - 1])}>Jump to last loaded clip</button><button onClick={() => onMove(attempts.find((a: any) => a.id === attempt.id + 1))}>Scroll to next clip</button>{workflow.content}</div> }))
const context = { code: '5132D', apparatus: 'springboard', height: '1m', position: 'D', sync: false }
const props = { base: '/api/v1/technique-history/1/7', context, revision: 2, constrainPosition: true, constrainSync: false, onClose: vi.fn(), onDone: vi.fn() }
const rows = [1,2,3].map(id => ({ id, session_id: 1, dive_code: '5132D', dive_datetime: `2026-08-0${id}T10:00:00`, history_occurred_at: `2026-07-0${id}T10:00:00`, performance: 'G' }))
beforeEach(() => { post.mockReset(); props.onDone.mockClear(); post.mockImplementation((url: string, body: any) => Promise.resolve({ data: url.endsWith('/attempts') ? { items: rows, revision: 2, next: null } : url.endsWith('/preview') ? { change: body, counts: { affected: 3 } } : { revision: body.revision + 1 } })) })
async function mark(label: string) {
  fireEvent.click(screen.getByRole('button', { name: 'New technique starts here' }))
  fireEvent.change(screen.getByLabelText('What changed?'), { target: { value: label } })
  fireEvent.click(screen.getByRole('button', { name: 'Keep this marker' }))
}
it('uses the viewed clip immutable anchor, preserves multiple draft markers, and reviews before writes', async () => {
  render(<TechniqueSetup {...props} />)
  await screen.findByText('Viewing clip 1')
  await mark('First cue')
  fireEvent.click(screen.getByRole('button', { name: 'Scroll to next clip' }))
  expect(screen.getByText('Viewing clip 2')).toBeInTheDocument()
  await mark('Second cue')
  expect(post.mock.calls.some(([url]) => url.endsWith('/changes'))).toBe(false)
  fireEvent.click(screen.getByRole('button', { name: 'Review markers (2)' }))
  await waitFor(() => expect(post).toHaveBeenCalledWith(`${props.base}/preview`, expect.objectContaining({ anchor_id: 2, start_at: rows[1].history_occurred_at, constrain_position: true })))
  fireEvent.click(await screen.findByRole('button', { name: 'Save changes' }))
  await waitFor(() => expect(props.onDone).toHaveBeenCalledOnce())
  const writes = post.mock.calls.filter(([url]) => url.endsWith('/changes'))
  expect(writes.map(([, body]) => [body.anchor_id, body.revision])).toEqual([[1, 2], [2, 3]])
})
it('keeps saved and unsaved markers distinct when a later boundary fails', async () => {
  const impl = post.getMockImplementation()!
  post.mockImplementation((url: string, body: any) => url.endsWith('/changes') && body.anchor_id === 2 ? Promise.reject(new Error('network')) : impl(url, body))
  render(<TechniqueSetup {...props} />)
  await screen.findByText('Viewing clip 1'); await mark('First cue')
  fireEvent.click(screen.getByRole('button', { name: 'Scroll to next clip' })); await mark('Second cue')
  fireEvent.click(screen.getByRole('button', { name: 'Review markers (2)' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Save changes' }))
  await screen.findByRole('alert')
  expect(props.onDone).not.toHaveBeenCalled()
  expect(screen.getByText('Saved changes: 1')).toBeInTheDocument()
  expect(screen.getByText('Second cue')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Review change' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Save changes' }))
  await waitFor(() => expect(post.mock.calls.filter(([url]) => url.endsWith('/changes'))).toHaveLength(3))
  expect(post.mock.calls.filter(([url, body]) => url.endsWith('/changes') && body.anchor_id === 1)).toHaveLength(1)
})
it('drops a late page response after the flow is closed', async () => {
  let resolve: (v: unknown) => void = () => {}
  post.mockReturnValue(new Promise(r => { resolve = r }))
  const view = render(<TechniqueSetup {...props} />)
  view.unmount(); resolve({ data: { items: rows, revision: 2, next: null } })
  expect(props.onDone).not.toHaveBeenCalled()
})
it('continues across pages while retaining no more than 100 clips', async () => {
  post.mockImplementation((url: string, body: any) => {
    const start = body.after || 0
    const items = Array.from({ length: 50 }, (_, i) => ({ ...rows[0], id: start + i + 1 }))
    return Promise.resolve({ data: { items, revision: 2, next: start < 100 ? start + 50 : null } })
  })
  render(<TechniqueSetup {...props} />)
  await screen.findByText('Window size 50')
  fireEvent.click(screen.getByRole('button', { name: 'Jump to last loaded clip' }))
  await screen.findByText('Window size 100')
  fireEvent.click(screen.getByRole('button', { name: 'Jump to last loaded clip' }))
  await waitFor(() => expect(post).toHaveBeenCalledWith(`${props.base}/attempts`, expect.objectContaining({ after: 100 }), expect.anything()))
  expect(screen.getByText('Window size 100')).toBeInTheDocument()
  expect(screen.getByText('Viewing clip 100')).toBeInTheDocument()
})
it('does not repeat failed prefetches indefinitely', async () => {
  post.mockResolvedValueOnce({ data: { items: rows, revision: 2, next: 3 } }).mockRejectedValue(new Error('offline'))
  render(<TechniqueSetup {...props} />)
  await screen.findByRole('alert')
  await waitFor(() => expect(post).toHaveBeenCalledTimes(2))
})
