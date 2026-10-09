import { mentionPayload, emptyMentionValue, type MentionValue } from '../components/mentions/mentionValue'
const key = (account: number, conversation: number) => `message-draft:v1:${account}:${conversation}`
export function readMessageDraft(account: number | undefined, conversation: number): MentionValue {
  if (!account) return emptyMentionValue()
  try {
    const value = JSON.parse(sessionStorage.getItem(key(account, conversation)) || 'null')
    if (!value || typeof value.body !== 'string' || value.body.length > 10000 || !Array.isArray(value.mentions)) return emptyMentionValue()
    return { body: value.body, mentions: value.mentions.filter((m: MentionValue['mentions'][number]) => m && Number.isSafeInteger(m.user_id) && m.user_id > 0 && Number.isInteger(m.start) && Number.isInteger(m.end) && m.start >= 0 && m.end > m.start && m.end <= value.body.length) }
  } catch { return emptyMentionValue() }
}
export function saveMessageDraft(account: number | undefined, conversation: number, value: MentionValue) {
  if (!account) return
  try {
    if (!value.body) { sessionStorage.removeItem(key(account, conversation)); discardPendingSend(account, conversation) }
    else sessionStorage.setItem(key(account, conversation), JSON.stringify(value))
  } catch { /* Optional session recovery; never block typing. */ }
}

export type PendingSend = { value: string; key: string }
const pendingKey = (account: number, conversation: number) => `${key(account, conversation)}:send`
export function readPendingSend(account: number | undefined, conversation: number): PendingSend | null {
  if (!account) return null
  try {
    const value = JSON.parse(sessionStorage.getItem(pendingKey(account, conversation)) || 'null')
    return value && typeof value.value === 'string' && typeof value.key === 'string' ? value : null
  } catch { return null }
}
export function savePendingSend(account: number | undefined, conversation: number, value: PendingSend) {
  if (!account) return
  try { sessionStorage.setItem(pendingKey(account, conversation), JSON.stringify(value)) } catch { /* Retry key stays in memory if storage is denied. */ }
}
/** A send can finish after leaving the thread. Clear only its own draft, so
 * edits in a newly mounted composer are never erased by that late response. */
export function completePendingSend(account: number | undefined, conversation: number, sent: PendingSend) {
  if (!account) return
  try {
    if (readPendingSend(account, conversation)?.key === sent.key) {
      if (JSON.stringify(mentionPayload(readMessageDraft(account, conversation))) === sent.value) sessionStorage.removeItem(key(account, conversation))
      sessionStorage.removeItem(pendingKey(account, conversation))
    }
  } catch { /* Optional recovery storage. */ }
  window.dispatchEvent(new CustomEvent('message-draft-sent', { detail: { account, conversation, value: sent.value, key: sent.key } }))
}

export function discardPendingSend(account: number | undefined, conversation: number) {
  if (!account) return
  try { sessionStorage.removeItem(pendingKey(account, conversation)) } catch { /* Optional recovery storage. */ }
}
