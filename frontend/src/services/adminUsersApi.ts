/** Administrator user-management client. Two roles only: administrator or diver. */

export type StoredRole = 'owner' | 'friend'
export type PublicRole = 'administrator' | 'diver'

import type { AvatarIdentity } from '../components/MemberAvatar'
export interface AdminUser extends AvatarIdentity {
  user_id: number
  email: string
  display_name: string
  role: StoredRole
  is_admin: boolean
  is_active: boolean
  live_sessions: number
  created_at: string | null
  revoked_sessions?: number
  /** Directory rows carry this; the manage panel loads the id list via getUser. */
  diver_count?: number
  /** Present on detail/create/update payloads only (capped list). */
  diver_ids?: number[]
  /** Total binding count on detail payloads; >= diver_ids.length. */
  diver_binding_total?: number
}

export interface AdminDiver {
  diver_id: number
  display_name: string
  canonical_name: string
  active: boolean
  bound_to_user: boolean
}

export interface AdminUserList {
  users: AdminUser[]
  total: number
  limit: number
  offset: number
}

/** Public role label. is_admin is the source of truth, never the stored role. */
export function roleLabel(user: Pick<AdminUser, 'is_admin'>): PublicRole {
  return user.is_admin ? 'administrator' : 'diver'
}

export function roleTitle(user: Pick<AdminUser, 'is_admin'>): string {
  return user.is_admin ? 'Administrator' : 'Diver'
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!response.ok) {
    let detail = ''
    try {
      const body = await response.json()
      detail = typeof body?.detail === 'string' ? body.detail : ''
    } catch {
      // Non-JSON error body: fall back to the status text.
    }
    throw new Error(detail || `Request failed: ${response.status}`)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export function listUsers(params?: {
  q?: string
  is_active?: boolean
  limit?: number
  offset?: number
}): Promise<AdminUserList> {
  const search = new URLSearchParams()
  if (params?.q?.trim()) search.set('q', params.q.trim())
  if (params?.is_active !== undefined) search.set('is_active', String(params.is_active))
  if (params?.limit !== undefined) search.set('limit', String(params.limit))
  if (params?.offset !== undefined) search.set('offset', String(params.offset))
  const suffix = search.toString()
  return request<AdminUserList>(`/api/v1/admin/users${suffix ? `?${suffix}` : ''}`)
}

export function getUser(userId: number): Promise<AdminUser> {
  return request<AdminUser>(`/api/v1/admin/users/${userId}`)
}

export function createUser(body: {
  email: string
  display_name?: string
  role: PublicRole
  password: string
  diver_id?: number
}): Promise<AdminUser> {
  return request<AdminUser>('/api/v1/admin/users', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function updateUser(
  userId: number,
  body: { display_name?: string; email?: string; role?: PublicRole; is_active?: boolean },
): Promise<AdminUser> {
  return request<AdminUser>(`/api/v1/admin/users/${userId}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

export function resetPassword(userId: number, newPassword: string): Promise<{ ok: true; revoked_sessions: number }> {
  return request(`/api/v1/admin/users/${userId}/reset-password`, {
    method: 'POST',
    body: JSON.stringify({ new_password: newPassword }),
  })
}

export function revokeSessions(userId: number): Promise<{ ok: true; revoked_sessions: number }> {
  return request(`/api/v1/admin/users/${userId}/revoke-sessions`, { method: 'POST' })
}

export function bindDiver(userId: number, diverId: number): Promise<{ ok: true; bound: boolean; noop: boolean }> {
  return request(`/api/v1/admin/users/${userId}/divers`, {
    method: 'POST',
    body: JSON.stringify({ diver_id: diverId }),
  })
}

export function unbindDiver(userId: number, diverId: number): Promise<{ ok: true; bound: boolean; noop: boolean }> {
  return request(`/api/v1/admin/users/${userId}/divers/${diverId}`, { method: 'DELETE' })
}

export interface AdminDiverList {
  divers: AdminDiver[]
  total: number
  limit: number
  offset: number
}

/** Bounded page of the diver directory (default: first 200). */
export function listDivers(params?: { limit?: number; offset?: number }): Promise<AdminDiverList> {
  const search = new URLSearchParams()
  if (params?.limit !== undefined) search.set('limit', String(params.limit))
  if (params?.offset !== undefined) search.set('offset', String(params.offset))
  const suffix = search.toString()
  return request<AdminDiverList>(`/api/v1/admin/divers${suffix ? `?${suffix}` : ''}`)
}

const DIVER_PAGE_SIZE = 200

/** Full diver directory for the binding UI, paged through the reported total.
 *
 * Every page is bounded (200 rows); the loop ends when the loaded count
 * reaches the reported total or a page comes back short (offset past the
 * last row), so it always terminates.
 */
export async function listAllDivers(): Promise<AdminDiver[]> {
  const all: AdminDiver[] = []
  let offset = 0
  for (;;) {
    const chunk = await listDivers({ limit: DIVER_PAGE_SIZE, offset })
    all.push(...chunk.divers)
    const total = chunk.total ?? all.length
    if (all.length >= total || chunk.divers.length < DIVER_PAGE_SIZE) break
    offset += DIVER_PAGE_SIZE
  }
  return all
}

export interface AccountSession { session_id: number; created_at: string; expires_at: string; last_used_at: string | null }
export interface AccountAuditEvent { event_id: number; event_type: string; actor: string; diver_id: number | null; created_at: string; details: { new_role?: string; revoked_sessions?: number; session_id?: number; fields?: string[] } }
export function listAccountSessions(userId: number, offset = 0): Promise<{ sessions: AccountSession[]; total: number }> {
  return request(`/api/v1/admin/users/${userId}/sessions?limit=50&offset=${offset}`)
}
export function revokeAccountSession(userId: number, sessionId: number): Promise<{ revoked_sessions: number }> {
  return request(`/api/v1/admin/users/${userId}/sessions/${sessionId}`, { method: 'DELETE' })
}
export function listAccountHistory(userId: number, eventType = '', offset = 0): Promise<{ events: AccountAuditEvent[]; total: number }> {
  const params = new URLSearchParams({ limit: '50', offset: String(offset) }); if (eventType) params.set('event_type', eventType)
  return request(`/api/v1/admin/users/${userId}/history?${params}`)
}

export interface AccountAccessCheck { user_id: number; dive_id: number; diver_id: number | null; visibility: string; account_active: boolean; can_view: boolean; can_manage: boolean; video_authorized: boolean | null; explanation: string; checked_at: string; scope: string }
export function checkAccountAccess(userId: number, diveId: number): Promise<AccountAccessCheck> {
  return request(`/api/v1/admin/users/${userId}/access-check?dive_id=${diveId}`)
}

export interface AccountStudio { bindings: { diver_id: number; display_name: string; dive_count: number }[]; total: number; viewable_dives: number; manageable_dives: number }
export interface BindingPreview { user_id: number; diver_id: number; display_name: string; currently_bound: boolean; proposed_bound: boolean; account_active: boolean; dive_count: number; public_dives: number; other_accounts: number; before: { view: number; manage: number }; after: { view: number; manage: number } }
export function getAccountStudio(userId: number, offset = 0): Promise<AccountStudio> {
  return request(`/api/v1/admin/users/${userId}/access-studio?limit=50&offset=${offset}`)
}
export function previewBinding(userId: number, diverId: number, bound: boolean): Promise<BindingPreview> {
  return request(`/api/v1/admin/users/${userId}/binding-preview?diver_id=${diverId}&bound=${bound}`)
}
