import type { MemberIdentity } from './communityApi'
import type { Mention } from '../components/mentions/mentionValue'
export type Message = {
  id: number; conversation_id: number; sender_id: number | null; client_id: string
  body: string; mentions: Mention[]; created_at: string
  dive: { available: boolean; id?: number; dive_code?: string; height?: string; poster_url?: string | null } | null
  receipts: { user_id: number; delivered_at: string | null; read_at: string | null }[]
  reactions: { user_id: number; emoji: string }[]
}
export type Conversation = { id: number; kind: 'direct' | 'group'; members: MemberIdentity[]; updated_at?: string; unread_count?: number; latest?: Message | null }
async function request<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(`/api/v1/messages${path}`, { credentials: 'same-origin', cache: 'no-store', method,
    ...(body === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }) })
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response.status === 204 ? undefined as T : response.json()
}
export const startConversation = (user_id: number) => request<{ id: number }>('/conversations', 'POST', { user_id })
export const listConversations = (before?: string) => request<{ items: Conversation[]; next_before: string | null }>(`/conversations${before ? `?before=${encodeURIComponent(before)}` : ''}`)
export const getUnreadCount = () => request<{ unread_count: number }>('/unread-count')
export const getConversation = (id: number) => request<Conversation>(`/conversations/${id}`)
export const getMessages = (id: number, before?: number) => request<{ items: Message[]; next_before: number | null }>(`/conversations/${id}/messages${before ? `?before=${before}` : ''}`)
export const sendMessage = (id: number, value: { client_id: string; body?: string; mentions?: Mention[]; dive_id?: number }) => request<Message>(`/conversations/${id}/messages`, 'POST', value)
export const acknowledgeMessages = (id: number, message_ids: number[], read: boolean) => request<void>(`/conversations/${id}/receipts`, 'POST', { message_ids, read })
export const reactToMessage = (id: number, message: number, reacted: boolean) => request<Message>(`/conversations/${id}/messages/${message}/reaction`, 'PUT', { reacted })
