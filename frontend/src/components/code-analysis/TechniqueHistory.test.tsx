import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import TechniqueHistory from './TechniqueHistory'
import '../../i18n'
const get = vi.fn(), post = vi.fn()
vi.mock('../../services/api', () => ({ api: { get: (...args: unknown[]) => get(...args), post: (...args: unknown[]) => post(...args) } }))
const context = { code: '103', apparatus: 'springboard', height: '3', position: 'B', sync: false }
beforeEach(() => { get.mockReset(); post.mockReset() })
it('previews before save and keeps the immutable anchor rather than display date', async () => {
  get.mockImplementation((url: string) => Promise.resolve({ data: url.endsWith('/tracks') ? { items: [{ id: 7, name: 'General', revision: 2 }] } : { items: [], revision: 2 } }))
  post.mockImplementation((url: string, body: unknown) => Promise.resolve({ data: url.endsWith('/attempts') ? { revision: 2, items: [{ dive_code: '103', id: 11, dive_datetime: '2026-02-01', history_occurred_at: '2026-01-01', state: 'unrecorded', source: 'unrecorded' }], next: null } : { change: body } }))
  render(<TechniqueHistory diver={1} context={context} />)
  await screen.findByText(/2026-02-01 · #11/)
  fireEvent.change(screen.getByLabelText(/^Technique$/), { target: { value: 'New cue' } })
  fireEvent.change(screen.getByLabelText(/Starting attempt|Premier essai/), { target: { value: '11' } })
  fireEvent.click(screen.getByRole('button', { name: /Preview|Prévisualiser/ }))
  await waitFor(() => expect(post).toHaveBeenCalledWith('/technique-history/1/7/preview', expect.objectContaining({ anchor_id: 11, start_at: '2026-01-01', revision: 2 })))
  expect(post.mock.calls.some(([url]) => url.endsWith('/changes'))).toBe(false)
})
it('ignores private data returned after switching diver', async () => {
  let finish: (value: unknown) => void = () => {}
  get.mockImplementation((url: string) => url.includes('/1/') ? new Promise(resolve => { finish = resolve }) : Promise.resolve({ data: { items: [] } }))
  const { rerender } = render(<TechniqueHistory diver={1} context={context} />)
  rerender(<TechniqueHistory diver={2} context={context} />)
  finish({ data: { items: [{ id: 7, name: 'Private hurdle' }] } })
  await waitFor(() => expect(screen.queryByText('Private hurdle')).not.toBeInTheDocument())
})
