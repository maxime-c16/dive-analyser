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
  | 'milestone'
  | 'sync_error'
  | 'guest_activity'

export type AppNotification = {
  id: number
  type: string
  title: string
  body: string | null
  dive_id: number | null
  read_at: string | null
  created_at: string | null
}

export type NotificationList = {
  items: AppNotification[]
  unread_count: number
}

export type NotificationPrefs = Record<string, boolean>

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

export async function getNotificationPrefs(): Promise<NotificationPrefs> {
  const data = (await readJson(
    await fetch('/api/v1/notification-prefs', {
      credentials: 'same-origin',
      cache: 'no-store',
    }),
  )) as { prefs: NotificationPrefs }
  return data.prefs && typeof data.prefs === 'object' ? data.prefs : {}
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
