import { act, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { useState } from 'react'
import { expect, it, vi } from 'vitest'
import MentionComposer from './MentionComposer'
import MentionText from './MentionText'
import { editMentionValue, mentionPayload } from './mentionValue'
import type { MentionValue } from './mentionValue'
import { searchMembers } from '../../services/communityApi'
vi.mock('../../services/communityApi', () => ({ searchMembers: vi.fn() }))
const member = { user_id: 15, display_name: 'Fouiny', handle: null, bio: '', avatar_url: null }
function Composer({ allowMentions = true }: { allowMentions?: boolean }) {
  const [value, setValue] = useState<MentionValue>({ body: '', mentions: [] })
  return <><label htmlFor="compose">Comment</label><MentionComposer id="compose" placeholder="Comment" value={value} onChange={setValue} allowMentions={allowMentions} /><output>{JSON.stringify(mentionPayload(value))}</output></>
}
it('selects a real identity with keyboard and sends code-point offsets', async () => {
  vi.mocked(searchMembers).mockResolvedValue({ items: [member], next_after: null })
  render(<Composer />)
  const input = screen.getByLabelText('Comment')
  fireEvent.change(input, { target: { value: '🌊 @Fan', selectionStart: 7 } })
  await screen.findByRole('option', { name: 'Fouiny' })
  fireEvent.keyDown(input, { key: 'Enter' })
  expect(input).toHaveValue('🌊 @Fouiny ')
  expect(screen.getByText((_, element) => element?.tagName === 'OUTPUT').textContent).toContain('"start":2,"end":9')
  fireEvent.change(input, { target: { value: '🌊 @Fanny ', selectionStart: 10 } })
  expect(screen.getByText((_, element) => element?.tagName === 'OUTPUT').textContent).toContain('"mentions":[]')
})
it('shifts mentions when editing before them and drops edited labels', () => {
  const value = { body: '@Fouiny wow', mentions: [{ user_id: 15, start: 0, end: 7 }] }
  expect(editMentionValue(value, 'Hi @Fouiny wow').mentions).toEqual([{ user_id: 15, start: 3, end: 10 }])
  expect(editMentionValue(value, '@Fouin wow').mentions).toEqual([])
})
it('renders stable profile links with Unicode text', () => {
  render(<MemoryRouter><MentionText body="🌊 @Fouiny!" mentions={[{ user_id: 15, start: 2, end: 9 }]} /></MemoryRouter>)
  expect(screen.getByRole('link', { name: '@Fouiny' })).toHaveAttribute('href', '/users/15')
})
it('does not expose directory autocomplete to guests', async () => {
  vi.mocked(searchMembers).mockClear()
  render(<Composer allowMentions={false} />)
  fireEvent.change(screen.getByLabelText('Comment'), { target: { value: '@Fan', selectionStart: 4 } })
  await act(async () => new Promise(resolve => setTimeout(resolve, 220)))
  expect(searchMembers).not.toHaveBeenCalled()
  expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
})
