import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import TechniqueComparison from './TechniqueComparison'
import '../../i18n'
const post = vi.fn()
vi.mock('../../services/api', () => ({ api: { post: (...a: unknown[]) => post(...a) } }))
const props = { base: '/api/v1/technique-history/1/7', context: { code: '5132D' }, pair: [1,2], revision: 2, onTrack: vi.fn() }
beforeEach(() => post.mockReset())
it('does not replace a failed comparison with invented zero coverage or no-data conclusions', async () => {
  post.mockRejectedValue({ response: { status: 503 } })
  render(<TechniqueComparison {...props} />)
  await screen.findByRole('alert')
  expect(screen.queryByText(/0 \/ 0/)).not.toBeInTheDocument()
  expect(screen.queryByText('No comparable rated attempts')).not.toBeInTheDocument()
  post.mockResolvedValueOnce({ data: { items: [{ modifiers: '', left_scored: 1, right_scored: 1, left_eligible:1, right_eligible:1 }], next: null } })
    .mockResolvedValue({ data: { sides: [0,1].map(side => ({ side, label: `Cue ${side}`, eligible:1, scored:1, sessions:1, median:7, recorded_matching:1, recorded_conflicting:0, inferred_only:0, mixed_unknown:0 })), excluded:{}, recorded_eligible:2 } })
  fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
  expect((await screen.findAllByText('Cue 0')).length).toBeGreaterThan(0)
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})
it('shows a singleton as one rating and pluralizes its session count', async () => {
  post.mockResolvedValueOnce({data:{items:[{modifiers:'',left_scored:1,right_scored:1,left_eligible:1,right_eligible:1}],next:null}}).mockResolvedValue({data:{sides:[0,1].map(side=>({side,label:`Cue ${side}`,eligible:1,scored:1,sessions:1,median:7,recorded_matching:1,recorded_conflicting:0,inferred_only:0,mixed_unknown:0})),excluded:{},recorded_eligible:2}})
  render(<TechniqueComparison {...props}/>);expect((await screen.findAllByText('1 rating: 7.0')).length).toBe(2)
  expect(screen.getAllByText('1 / 1 scored · 1 session')).toHaveLength(2)
  expect(screen.queryByText('median')).not.toBeInTheDocument()
})
it('preserves the named period on an empty comparison side', async () => {
  post.mockResolvedValueOnce({data:{items:[{modifiers:'',left_scored:0,right_scored:1,left_eligible:0,right_eligible:1}],next:null}}).mockResolvedValue({data:{labels:['Earlier cue','Later cue'],sides:[{side:1,label:'Later cue',eligible:1,scored:1,sessions:1,median:7,recorded_matching:1,recorded_conflicting:0,inferred_only:0,mixed_unknown:0}],excluded:{},recorded_eligible:1}})
  render(<TechniqueComparison {...props}/>);expect(await screen.findByRole('heading',{name:'Earlier cue'})).toBeInTheDocument()
  expect(screen.getByText('0 / 0 scored · 0 sessions')).toBeInTheDocument()
})
