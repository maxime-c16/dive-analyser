import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import '../i18n'
import Messages from './Messages'
import * as api from '../services/messagesApi'
import type { Message } from '../services/messagesApi'
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { user_id: 1 } }) }))
vi.mock('../services/messagesApi', () => ({ getConversation: vi.fn(), listConversations: vi.fn(), getMessages: vi.fn(), acknowledgeMessages: vi.fn(), sendMessage: vi.fn(), reactToMessage: vi.fn(), startConversation: vi.fn() }))
const message: Message = { id: 7, conversation_id: 3, sender_id: 2, client_id: 'x', body: 'Hello from Fouiny', mentions: [], created_at: '2026-10-08T12:00:00Z', dive: null, receipts: [], reactions: [] }
let visible: (entries: { intersectionRatio: number }[]) => void
function show() { render(<MemoryRouter initialEntries={['/messages/3']}><Routes><Route path="/messages/:conversationId" element={<Messages />} /></Routes></MemoryRouter>) }
beforeEach(() => {
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
  const input = screen.getByLabelText('Your message')
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
