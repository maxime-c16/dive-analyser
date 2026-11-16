import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import TechniqueHistory from './TechniqueHistory'
import '../../i18n'
const get = vi.fn(), post = vi.fn()
vi.mock('../../services/api', () => ({ api: { get: (...args: unknown[]) => get(...args), post: (...args: unknown[]) => post(...args) } }))
const setupProps=vi.fn()
vi.mock('./TechniqueSetup',()=>({default:(props:any)=>{setupProps(props);return <div>Setup open</div>}}))
vi.mock('./TechniqueTrackChart', () => ({ default: () => <div>Technique score chart</div> }))
vi.mock('./TechniqueComparison', () => ({ default: ({ pair }: { pair: number[] }) => <div>Comparing {pair.join(' and ')}</div> }))
const context = { code: '5132D', apparatus: 'springboard', height: '1m', position: 'D', sync: false }
const episodes = [
  { id: 1, label: 'Original cue', start_at: '2026-07-01T10:00:00', end_at: '2026-08-12T10:00:00', scope: '5132D', technique_id: 1 },
  { id: 2, label: 'Later initiation', start_at: '2026-08-12T10:00:00', end_at: null, scope: '5132D', technique_id: 2 },
]
beforeEach(() => {
  get.mockReset(); post.mockReset()
  get.mockImplementation((url: string) => Promise.resolve({ data: url.endsWith('/preferences') ? { timezone: 'UTC' } : url.endsWith('/tracks') ? { items: [{ id: 7, name: 'Twisting technique', revision: 2 }], next: null } : { items: episodes, revision: 2, next: null } }))
  post.mockImplementation((url: string, body: unknown) => Promise.resolve({ data: url.endsWith('/attempts') ? { revision: 2, items: [{ dive_code: '5132D', id: 11, dive_datetime: '2026-02-01T10:00:00', history_occurred_at: '2026-01-01T10:00:00', state: 'unrecorded', source: 'unrecorded' }], next: null } : { change: body, counts: { affected: 10, explicit_preserved: 2 } } }))
})
it('opens on the timeline, keeping forms and bulk controls out of the reading journey', async () => {
  const { container } = render(<TechniqueHistory diver={1} context={context} />)
  await screen.findByText('Later initiation')
  expect(screen.getAllByText(/12 Aug 2026/).length).toBeGreaterThan(0)
  expect(screen.getByText('Technique score chart')).toBeInTheDocument()
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  expect(screen.queryByText('Select page')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument()
  expect(container.textContent).not.toContain('2026-08-12T')
})
it('reviews before saving and uses the immutable selected attempt instead of its display date', async () => {
  render(<TechniqueHistory diver={1} context={context} />)
  await screen.findByText('Later initiation')
  fireEvent.click(screen.getByRole('button', { name: 'Manage history' })); fireEvent.click(screen.getByRole('button', { name: 'Enter a date' }))
  const dialog = await screen.findByRole('dialog')
  fireEvent.change(within(dialog).getByLabelText('What changed?'), { target: { value: 'New cue' } })
  fireEvent.change(within(dialog).getByLabelText('Starting attempt'), { target: { value: '11' } })
  fireEvent.click(within(dialog).getByRole('button', { name: 'Review change' }))
  await waitFor(() => expect(post).toHaveBeenCalledWith('/api/v1/technique-history/1/7/preview', expect.objectContaining({ anchor_id: 11, start_at: '2026-01-01T10:00:00', revision: 2 })))
  expect(post.mock.calls.some(([url]) => url.endsWith('/changes'))).toBe(false)
  fireEvent.click(await within(dialog).findByRole('button', { name: 'Save change' }))
  await waitFor(() => expect(post.mock.calls.some(([url]) => url.endsWith('/changes'))).toBe(true))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
})
it('compares two explicitly named periods and returns to the timeline', async () => {
  render(<TechniqueHistory diver={1} context={context} />)
  await screen.findByText('Later initiation')
  fireEvent.click(screen.getByRole('button', { name: 'Compare' }))
  expect(screen.getByText('Comparing 1 and 2')).toBeInTheDocument()
  expect(screen.getByLabelText('Earlier period')).toHaveValue('1')
  expect(screen.getByLabelText('Later period')).toHaveValue('2')
  fireEvent.click(screen.getByRole('button', { name: 'Done' }))
  expect(screen.getByText('Later initiation')).toBeInTheDocument()
  expect(screen.queryByText('Comparing 1 and 2')).not.toBeInTheDocument()
})
it('cancels a change without writing it', async () => {
  render(<TechniqueHistory diver={1} context={context} />)
  await screen.findByText('Later initiation')
  fireEvent.click(screen.getByRole('button', { name: 'Manage history' })); fireEvent.click(screen.getByRole('button', { name: 'Enter a date' }))
  fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Cancel' }))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(post.mock.calls.some(([url]) => url.endsWith('/changes'))).toBe(false)
})
it('ignores private data returned after switching diver', async () => {
  let finish: (value: unknown) => void = () => {}
  get.mockImplementation((url: string) => url.includes('/1/') ? new Promise(resolve => { finish = resolve }) : Promise.resolve({ data: { items: [], next: null } }))
  const { rerender } = render(<TechniqueHistory diver={1} context={context} />)
  rerender(<TechniqueHistory diver={2} context={context} />)
  finish({ data: { items: [{ id: 7, name: 'Private hurdle' }] } })
  await waitFor(() => expect(screen.queryByText('Private hurdle')).not.toBeInTheDocument())
})
it('keeps existing notes and scope constraints when editing a period', async () => {
  get.mockImplementation((url: string) => Promise.resolve({ data: url.endsWith('/preferences') ? { timezone: 'UTC' } : url.endsWith('/tracks') ? { items: [{ id: 7, name: 'Twisting technique', revision: 2 }], next: null } : { items: [{ ...episodes[1], notes: 'Keep my coaching cue', position: 'D', sync: false }], revision: 2, next: null } }))
  render(<TechniqueHistory diver={1} context={context} />)
  fireEvent.click(await screen.findByRole('button', { name: /Later initiation/ }))
  fireEvent.click(screen.getByRole('button', { name: 'Edit' }))
  const dialog = await screen.findByRole('dialog')
  expect(within(dialog).getByLabelText('Notes')).toHaveValue('Keep my coaching cue')
  fireEvent.click(within(dialog).getByRole('button', { name: 'Review change' }))
  await waitFor(() => expect(post).toHaveBeenCalledWith('/api/v1/technique-history/1/7/preview', expect.objectContaining({ episode_id: 2, notes: 'Keep my coaching cue', constrain_position: true, constrain_sync: true })))
})
it('preserves the saved identity until a different technique is explicitly selected',async()=>{
  render(<TechniqueHistory diver={1} context={context}/>);fireEvent.click(await screen.findByRole('button',{name:/Later initiation/}));fireEvent.click(screen.getByRole('button',{name:'Edit'}))
  const dialog=await screen.findByRole('dialog')
  expect(within(dialog).getByLabelText('What changed?')).toHaveAttribute('readonly')
  fireEvent.click(within(dialog).getByRole('button',{name:'Use a different technique'}))
  expect(within(dialog).getByLabelText('What changed?')).not.toHaveAttribute('readonly')
})

it('defaults a newly recorded context to the viewed position and individual/synchronized condition',async()=>{
 setupProps.mockClear();render(<TechniqueHistory diver={1} context={context}/>);await screen.findByText('Later initiation')
 fireEvent.click(screen.getByRole('button',{name:'Fill in my history'}));await screen.findByText('Setup open')
 expect(setupProps).toHaveBeenLastCalledWith(expect.objectContaining({constrainPosition:true,constrainSync:true,context:expect.objectContaining({sync:false,position:'D'})}))
})
