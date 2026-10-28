/**
 * In-app notification inbox client (PR2).
 *
 * Same-origin fetch with session cookies, mirroring the fediverse settings
 * calls in Account.tsx. The backend (PR1) owns types, defaults and state;
 * this module only transports them.
 */

export type NotificationType =
  | 'new_video'
  | 'video_ready'
  | 'new_comment'
  | 'comment_reply'
  | 'direct_message'
  | 'milestone'
  | 'sync_error'
  | 'guest_activity'
  | 'calendar_invitation'
  | 'calendar_change'
  | 'calendar_reminder'
  | 'calendar_group_reminder'
  | 'calendar_follow'

/** Calendar alert view, resolved by the server for the reader at read time.
 * `redacted` rows carry no title, details or link (access was lost). */
export type CalendarNotificationView =
  | { redacted: true }
  | {
      redacted: false
      kind: 'invitation' | 'change' | 'cancellation' | 'reminder' | 'new_event'
      event_id: number
      occurrence_id: number
      url: string
      event_title: string
      timezone: string
      starts_at: string | null
      start_date: string | null
      all_day: boolean
      venue_name: string | null
      status: 'scheduled' | 'cancelled'
      changes: { kinds: string[]; old_start: string | null; new_start: string | null }[]
      total: number
    }

export type AppNotification = {
  id: number
  type: string
  title: string
  body: string | null
  session_id?: number | null
  conversation_id?: number | null
  dive_id: number | null
  calendar?: CalendarNotificationView
  read_at: string | null
  created_at: string | null
}

export type NotificationList = {
  items: AppNotification[]
  unread_count: number
}

export type NotificationPrefs = Record<string, boolean>

export type NotificationPrefsResult = {
  prefs: NotificationPrefs
  explicit: string[]
}

async function readJson(response: Response): Promise<unknown> {
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response.json()
}

export async function listNotifications(options?: {
  unreadOnly?: boolean
  limit?: number
}): Promise<NotificationList> {
  const params = new URLSearchParams()
  if (options?.unreadOnly) params.set('unread_only', 'true')
  params.set('limit', String(options?.limit ?? 50))
  const query = params.toString()
  const data = (await readJson(
    await fetch(`/api/v1/notifications${query ? `?${query}` : ''}`, {
      credentials: 'same-origin',
      cache: 'no-store',
    }),
  )) as NotificationList
  return {
    items: Array.isArray(data.items) ? data.items : [],
    unread_count: typeof data.unread_count === 'number' ? data.unread_count : 0,
  }
}

export async function markNotificationRead(id: number): Promise<AppNotification> {
  const data = (await readJson(
    await fetch(`/api/v1/notifications/${id}/read`, {
      method: 'POST',
      credentials: 'same-origin',
    }),
  )) as AppNotification
  return data
}

export async function markAllNotificationsRead(): Promise<{ marked: number }> {
  const data = (await readJson(
    await fetch('/api/v1/notifications/read-all', {
      method: 'POST',
      credentials: 'same-origin',
    }),
  )) as { marked: number }
  return { marked: typeof data.marked === 'number' ? data.marked : 0 }
}

export async function getNotificationPrefs(): Promise<NotificationPrefsResult> {
  const data = (await readJson(
    await fetch('/api/v1/notification-prefs', {
      credentials: 'same-origin',
      cache: 'no-store',
    }),
  )) as { prefs?: NotificationPrefs; explicit?: unknown }
  const prefs = data.prefs && typeof data.prefs === 'object' ? data.prefs : {}
  // `explicit` is additive (PR71 review): older servers omit it, in which
  // case callers fall back to the pre-explicit migration behaviour.
  const explicit = Array.isArray(data.explicit)
    ? data.explicit.filter((entry): entry is string => typeof entry === 'string')
    : []
  return { prefs, explicit }
}

export async function setNotificationPref(
  type: string,
  enabled: boolean,
): Promise<{ type: string; enabled: boolean }> {
  const data = (await readJson(
    await fetch('/api/v1/notification-prefs', {
      method: 'PUT',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type, enabled }),
    }),
  )) as { type: string; enabled: boolean }
  return data
}

/**
 * Web Push device subscriptions (PR3). Same-origin session transport, like
 * the inbox calls above. The backend owns VAPID state; `publicKey` is ""
 * when push is disabled server-side.
 */
export type PushConfig = {
  publicKey: string
}

export type PushSubscriptionInput = {
  endpoint: string
  keys: { p256dh: string; auth: string }
  device_label?: string
}

export async function getPushConfig(): Promise<PushConfig> {
  const data = (await readJson(
    await fetch('/api/v1/push-config', {
      credentials: 'same-origin',
      cache: 'no-store',
    }),
  )) as { publicKey?: unknown }
  return { publicKey: typeof data.publicKey === 'string' ? data.publicKey : '' }
}

export async function savePushSubscription(
  input: PushSubscriptionInput,
): Promise<{ endpoint: string; device_label: string | null }> {
  const data = (await readJson(
    await fetch('/api/v1/push-subscriptions', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    }),
  )) as { endpoint: string; device_label: string | null }
  return data
}

export async function deletePushSubscription(endpoint: string): Promise<{ deleted: boolean }> {
  const data = (await readJson(
    await fetch('/api/v1/push-subscriptions', {
      method: 'DELETE',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ endpoint }),
    }),
  )) as { deleted: boolean }
  return data
}
