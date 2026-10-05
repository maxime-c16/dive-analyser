/** Administrator user-management client. Two roles only: administrator or diver. */

export type StoredRole = 'owner' | 'friend'
export type PublicRole = 'administrator' | 'diver'

export interface AdminUser {
  user_id: number
  email: string
  display_name: string
  role: StoredRole
  is_admin: boolean
  is_active: boolean
  diver_ids: number[]
  live_sessions: number
  created_at: string | null
  revoked_sessions?: number
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
const DIVER_MAX_PAGES = 5

/** Full diver directory for the binding UI, paged through boundedly. */
export async function listAllDivers(): Promise<AdminDiver[]> {
  const all: AdminDiver[] = []
  for (let page = 0; page < DIVER_MAX_PAGES; page += 1) {
    const chunk = await listDivers({ limit: DIVER_PAGE_SIZE, offset: page * DIVER_PAGE_SIZE })
    all.push(...chunk.divers)
    const total = chunk.total ?? all.length
    if (all.length >= total || chunk.divers.length < DIVER_PAGE_SIZE) break
  }
  return all
}
