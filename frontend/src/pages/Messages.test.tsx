import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import '../i18n'
import Messages from './Messages'
import * as api from '../services/messagesApi'
import { searchMembers } from '../services/communityApi'
import type { Message } from '../services/messagesApi'
import { MobileShellContext } from '../navigation/mobileShellActions'
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { user_id: 1 } }) }))
vi.mock('../services/messagesApi', () => ({ getConversation: vi.fn(), listConversations: vi.fn(), getMessages: vi.fn(), acknowledgeMessages: vi.fn(), sendMessage: vi.fn(), reactToMessage: vi.fn(), startConversation: vi.fn(), startGroup: vi.fn(), leaveConversation: vi.fn() }))
vi.mock('../services/communityApi', () => ({ searchMembers: vi.fn() }))
const message: Message = { id: 7, conversation_id: 3, sender_id: 2, client_id: 'x', body: 'Hello from Fouiny', mentions: [], created_at: '2026-10-08T12:00:00Z', dive: null, receipts: [], reactions: [] }
let visible: (entries: { intersectionRatio: number }[]) => void
function show() { render(<MemoryRouter initialEntries={['/messages/3']}><Routes><Route path="/messages/:conversationId" element={<Messages />} /></Routes></MemoryRouter>) }
function showWithShell(entry: string, claim: () => () => void) {
  return render(<MobileShellContext.Provider value={{ actions: <span data-testid="shell-actions" />, claim }}><MemoryRouter initialEntries={[entry]}><Routes><Route path="/messages" element={<Messages />} /><Route path="/messages/:conversationId" element={<Messages />} /></Routes></MemoryRouter></MobileShellContext.Provider>)
}
beforeEach(() => {
  sessionStorage.clear()
  vi.resetAllMocks()
  vi.stubGlobal('IntersectionObserver', class { constructor(callback: typeof visible) { visible = callback } observe() {} disconnect() {} })
  vi.stubGlobal('crypto', { randomUUID: () => 'e75d368c-9c21-4121-9f68-0f8f24bd143a' })
  Element.prototype.scrollIntoView = vi.fn()
  vi.mocked(api.getConversation).mockResolvedValue({ id: 3, kind: 'direct', members: [{ user_id: 2, display_name: 'Fouiny', handle: null, bio: '', avatar_url: null }] })
  vi.mocked(api.listConversations).mockResolvedValue({ items: [], next_before: null })
  vi.mocked(api.getMessages).mockResolvedValue({ items: [message], next_before: null })
  vi.mocked(api.acknowledgeMessages).mockResolvedValue(undefined)
})
it('acknowledges delivery after receiving, and reading only while visible and focused', async () => {
  const focus = vi.spyOn(document, 'hasFocus').mockReturnValue(false)
  show()
  await screen.findByText(message.body)
  await waitFor(() => expect(api.acknowledgeMessages).toHaveBeenCalledWith(3, [7], false))
  await act(async () => visible([{ intersectionRatio: 1 }]))
  expect(api.acknowledgeMessages).not.toHaveBeenCalledWith(3, [7], true)
  focus.mockReturnValue(true)
  await act(async () => fireEvent(window, new Event('focus')))
  await waitFor(() => expect(api.acknowledgeMessages).toHaveBeenCalledWith(3, [7], true))
  focus.mockRestore()
})
it('keeps the draft and reuses its retry key after a failed send', async () => {
  vi.spyOn(document, 'hasFocus').mockReturnValue(false)
  vi.mocked(api.sendMessage).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({ ...message, id: 8, sender_id: 1, body: 'Hello Fanny' })
  show()
  await screen.findByText(message.body)
  const input = screen.getByRole('textbox', { name:'Your message' })
  fireEvent.change(input, { target: { value: 'Hello Fanny' } })
  fireEvent.click(screen.getByRole('button', { name: 'Send' }))
  await screen.findByRole('alert')
  expect(input).toHaveValue('Hello Fanny')
  fireEvent.click(screen.getByRole('button', { name: 'Send' }))
  await screen.findByText('Hello Fanny')
  const calls = vi.mocked(api.sendMessage).mock.calls
  expect(calls[0][1].client_id).toBe(calls[1][1].client_id)
  expect(input).toHaveValue('')
  expect(screen.getByText('Sent')).toBeInTheDocument()
})
it('reacts through the keyboard-accessible heart control', async () => {
  vi.mocked(api.reactToMessage).mockResolvedValue({ ...message, reactions: [{ user_id: 1, emoji: '❤️' }] })
  show()
  await screen.findByText(message.body)
  fireEvent.click(screen.getByRole('button', { name: 'React with a heart' }))
  await waitFor(() => expect(api.reactToMessage).toHaveBeenCalledWith(3, 7, true))
  expect(await screen.findByRole('button', { name: 'React with a heart', pressed: true })).toBeInTheDocument()
})

it('recovers a draft after leaving the conversation and clears storage on successful send', async () => {
  const view = render(<MemoryRouter initialEntries={['/messages/3']}><Routes><Route path="/messages/:conversationId" element={<Messages />} /></Routes></MemoryRouter>)
  await screen.findByText(message.body)
  fireEvent.change(screen.getByRole('textbox', { name:'Your message' }), { target: { value: 'Recovered draft' } })
  view.unmount()
  show()
  await screen.findByText(message.body)
  expect(screen.getByRole('textbox', { name:'Your message' })).toHaveValue('Recovered draft')
  vi.mocked(api.sendMessage).mockResolvedValue({ ...message, id:8, sender_id:1, body:'Recovered draft' })
  fireEvent.click(screen.getByRole('button', { name:'Send' }))
  await waitFor(() => expect(screen.getByRole('textbox', { name:'Your message' })).toHaveValue(''))
  expect(sessionStorage.getItem('message-draft:v1:1:3')).toBeNull()
})
it('clears a successful send even after the thread unmounts', async () => {
  let resolve!: (m: Message) => void
  vi.mocked(api.sendMessage).mockReturnValue(new Promise(r => { resolve = r }))
  const view = render(<MemoryRouter initialEntries={['/messages/3']}><Routes><Route path="/messages/:conversationId" element={<Messages />} /></Routes></MemoryRouter>)
  await screen.findByText(message.body)
  fireEvent.change(screen.getByRole('textbox', { name:'Your message' }), { target:{ value:'Delayed' } })
  fireEvent.click(screen.getByRole('button', { name:'Send' }))
  view.unmount()
  await act(async () => resolve({ ...message,id:8,body:'Delayed',sender_id:1 }))
  expect(sessionStorage.getItem('message-draft:v1:1:3')).toBeNull()
  show();await screen.findByText(message.body)
  expect(screen.getByRole('textbox', { name:'Your message' })).toHaveValue('')
})
it('reuses the send identity across route unmount after an uncertain failure', async () => {
  vi.mocked(api.sendMessage).mockRejectedValue(new Error('offline'))
  const view = render(<MemoryRouter initialEntries={['/messages/3']}><Routes><Route path="/messages/:conversationId" element={<Messages />} /></Routes></MemoryRouter>)
  await screen.findByText(message.body)
  fireEvent.change(screen.getByRole('textbox', { name:'Your message' }), { target:{ value:'Retry later' } })
  fireEvent.click(screen.getByRole('button', { name:'Send' }));await screen.findByRole('alert')
  const first = vi.mocked(api.sendMessage).mock.calls[0][1].client_id
  view.unmount();show();await screen.findByText(message.body)
  fireEvent.click(screen.getByRole('button', { name:'Send' }));await screen.findByRole('alert')
  expect(vi.mocked(api.sendMessage).mock.calls[1][1].client_id).toBe(first)
})
it('a late send never erases newer text typed after returning', async () => {
  let resolve!: (m: Message) => void
  vi.mocked(api.sendMessage).mockReturnValue(new Promise(r => { resolve=r }))
  const view=render(<MemoryRouter initialEntries={['/messages/3']}><Routes><Route path="/messages/:conversationId" element={<Messages />} /></Routes></MemoryRouter>)
  await screen.findByText(message.body)
  fireEvent.change(screen.getByRole('textbox',{name:'Your message'}),{target:{value:'Delayed'}})
  fireEvent.click(screen.getByRole('button',{name:'Send'}));view.unmount();show();await screen.findByText(message.body)
  fireEvent.change(screen.getByRole('textbox',{name:'Your message'}),{target:{value:'New draft'}})
  await act(async()=>resolve({...message,id:8,body:'Delayed',sender_id:1}))
  expect(screen.getByRole('textbox',{name:'Your message'})).toHaveValue('New draft')
  expect(JSON.parse(sessionStorage.getItem('message-draft:v1:1:3')!).body).toBe('New draft')
})
it('clears the restored composer when its earlier send completes after returning', async () => {
  let resolve!: (m: Message) => void
  vi.mocked(api.sendMessage).mockReturnValue(new Promise(r => { resolve=r }))
  const view=render(<MemoryRouter initialEntries={['/messages/3']}><Routes><Route path="/messages/:conversationId" element={<Messages />} /></Routes></MemoryRouter>)
  await screen.findByText(message.body)
  fireEvent.change(screen.getByRole('textbox',{name:'Your message'}),{target:{value:'Delayed'}})
  fireEvent.click(screen.getByRole('button',{name:'Send'}));view.unmount();show();await screen.findByText(message.body)
  await act(async()=>resolve({...message,id:8,body:'Delayed',sender_id:1}))
  expect(screen.getByRole('textbox',{name:'Your message'})).toHaveValue('')
})
it('clearing a failed draft starts a fresh send even when the new text is identical',async()=>{
  let key=0
  vi.stubGlobal('crypto',{randomUUID:()=>`key-${++key}`})
  vi.mocked(api.sendMessage).mockRejectedValue(new Error('uncertain'))
  show();await screen.findByText(message.body)
  const input=screen.getByRole('textbox',{name:'Your message'})
  fireEvent.change(input,{target:{value:'ok'}});fireEvent.click(screen.getByRole('button',{name:'Send'}));await screen.findByRole('alert')
  fireEvent.change(input,{target:{value:''}});fireEvent.change(input,{target:{value:'ok'}})
  fireEvent.click(screen.getByRole('button',{name:'Send'}));await waitFor(()=>expect(api.sendMessage).toHaveBeenCalledTimes(2))
  expect(vi.mocked(api.sendMessage).mock.calls[0][1].client_id).not.toBe(vi.mocked(api.sendMessage).mock.calls[1][1].client_id)
})
it('a completed late send releases its identity before identical text is sent again',async()=>{
  let resolve!:(m:Message)=>void,key=0
  vi.stubGlobal('crypto',{randomUUID:()=>`key-${++key}`})
  vi.mocked(api.sendMessage).mockReturnValueOnce(new Promise(r=>{resolve=r})).mockResolvedValueOnce({...message,id:9,sender_id:1,body:'Again'})
  const view=render(<MemoryRouter initialEntries={['/messages/3']}><Routes><Route path="/messages/:conversationId" element={<Messages />} /></Routes></MemoryRouter>)
  await screen.findByText(message.body)
  fireEvent.change(screen.getByRole('textbox',{name:'Your message'}),{target:{value:'Again'}})
  fireEvent.click(screen.getByRole('button',{name:'Send'}));view.unmount();show();await screen.findByText(message.body)
  await act(async()=>resolve({...message,id:8,sender_id:1,body:'Again'}))
  fireEvent.change(screen.getByRole('textbox',{name:'Your message'}),{target:{value:'Again'}})
  fireEvent.click(screen.getByRole('button',{name:'Send'}));await waitFor(()=>expect(api.sendMessage).toHaveBeenCalledTimes(2))
  const calls=vi.mocked(api.sendMessage).mock.calls
  expect(calls[0][1].client_id).not.toBe(calls[1][1].client_id)
})
it('abandoning and retyping identical text before an old send completes preserves the new draft',async()=>{
  let resolve!:(m:Message)=>void
  vi.mocked(api.sendMessage).mockReturnValueOnce(new Promise(r=>{resolve=r}))
  const view=render(<MemoryRouter initialEntries={['/messages/3']}><Routes><Route path="/messages/:conversationId" element={<Messages />} /></Routes></MemoryRouter>)
  await screen.findByText(message.body)
  fireEvent.change(screen.getByRole('textbox',{name:'Your message'}),{target:{value:'Again'}})
  fireEvent.click(screen.getByRole('button',{name:'Send'}));view.unmount();show();await screen.findByText(message.body)
  const input=screen.getByRole('textbox',{name:'Your message'})
  fireEvent.change(input,{target:{value:''}});fireEvent.change(input,{target:{value:'Again'}})
  await act(async()=>resolve({...message,id:8,sender_id:1,body:'Again'}))
  expect(input).toHaveValue('Again');expect(JSON.parse(sessionStorage.getItem('message-draft:v1:1:3')!).body).toBe('Again')
})
it('claims the mobile shell exactly once on a conversation page, from its header on phones', async () => {
  // Phones hide the page heading in a conversation; the conversation header
  // takes the title row, so it carries the bell and avatar instead.
  const width = window.innerWidth
  try {
    for (const viewport of [390, 1024]) {
      Object.defineProperty(window, 'innerWidth', { configurable: true, value: viewport })
      let claims = 0
      const claim = () => { claims++; return () => { claims-- } }
      const { unmount } = showWithShell('/messages/3', claim)
      await screen.findByText(message.body)
      expect(claims).toBe(1)
      const actions = screen.getByTestId('shell-actions')
      expect(Boolean(actions.closest('.msg-thread-head'))).toBe(viewport < 768)
      unmount()
    }
  } finally {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: width })
  }
})
it('claims the mobile shell in the inbox', async () => {
  let claims = 0
  const claim = () => { claims++; return () => { claims-- } }
  showWithShell('/messages', claim)
  await screen.findByRole('heading', { level: 1 })
  expect(claims).toBe(1)
  expect(screen.getByTestId('shell-actions')).toBeInTheDocument()
})
it('leaving a group drops it from the inbox instead of keeping a clickable dead row', async () => {
  const group = { id: 9, kind: 'group' as const, title: 'Cliff crew', members: [
    { user_id: 2, display_name: 'Fouiny', handle: null, bio: '', avatar_url: null },
    { user_id: 3, display_name: 'Fanny', handle: null, bio: '', avatar_url: null },
  ], updated_at: '2026-10-08T12:00:00Z', unread_count: 0, latest: null }
  vi.mocked(api.getConversation).mockResolvedValue(group)
  vi.mocked(api.listConversations).mockResolvedValue({ items: [group], next_before: null })
  vi.mocked(api.getMessages).mockResolvedValue({ items: [], next_before: null })
  vi.mocked(api.leaveConversation).mockResolvedValue(undefined)
  const confirm = window.confirm
  window.confirm = vi.fn(() => true)
  try {
    render(<MemoryRouter initialEntries={['/messages/9']}><Routes><Route path="/messages" element={<Messages />} /><Route path="/messages/:conversationId" element={<Messages />} /></Routes></MemoryRouter>)
    // Header and inbox row both show the group name.
    await waitFor(() => expect(screen.getAllByText('Cliff crew')).toHaveLength(2))
    fireEvent.click(screen.getByRole('button', { name: /cliff crew/i }))
    fireEvent.click(screen.getByRole('button', { name: 'Leave group' }))
    // The server no longer lists the departed group; the refresh merge alone would keep it.
    vi.mocked(api.listConversations).mockResolvedValue({ items: [], next_before: null })
    await waitFor(() => expect(api.leaveConversation).toHaveBeenCalledWith(9))
    await waitFor(() => expect(screen.queryByRole('link', { name: /cliff crew/i })).toBeNull())
    expect(await screen.findByText('No conversations yet.')).toBeInTheDocument()
  } finally {
    window.confirm = confirm
  }
})
it('caps group selection at 15 others and explains the limit', async () => {
  const members = Array.from({ length: 16 }, (_, i) => ({ user_id: 10 + i, display_name: `Diver${i}`, handle: null, bio: '', avatar_url: null }))
  vi.mocked(api.listConversations).mockResolvedValue({ items: [], next_before: null })
  vi.mocked(searchMembers).mockResolvedValue({ items: members, next_after: null })
  vi.mocked(api.startGroup).mockResolvedValue({ id: 11 })
  render(<MemoryRouter initialEntries={['/messages']}><Routes><Route path="/messages" element={<Messages />} /></Routes></MemoryRouter>)
  await screen.findByRole('heading', { level: 1 })
  fireEvent.click(screen.getAllByRole('button', { name: 'New' })[0])
  fireEvent.click(screen.getByRole('button', { name: 'New group' }))
  for (let i = 0; i < 16; i++) fireEvent.click(await screen.findByRole('button', { name: `Diver${i}` }))
  // The 16th pick is ignored: 15 chips, the limit hint, create counting 16 people total.
  await waitFor(() => expect(screen.getAllByRole('button', { name: /remove diver/i })).toHaveLength(15))
  expect(screen.getByText('Groups hold up to 16 people')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Create group · 16 people' }))
  await waitFor(() => expect(api.startGroup).toHaveBeenCalledTimes(1))
  expect(vi.mocked(api.startGroup).mock.calls[0][0]).toHaveLength(15)
})
