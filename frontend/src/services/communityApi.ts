import type { MemberProfile } from './activityApi'
import type { AvatarHud } from '../components/MemberAvatar'

export type MemberIdentity = Pick<MemberProfile, 'user_id' | 'display_name' | 'handle' | 'bio' | 'avatar_url' | 'avatar_hud'>
export type MemberSummary = MemberIdentity & { accessible_dive_count?: number; latest_dive_at?: string | null }
export type ProfileDive = { id: number; dive_code: string; height: string; dive_datetime: string; visibility: 'public' | 'private'; poster_url: string | null }
export type DivePage = { items: ProfileDive[]; next_before: string | null }

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api/v1/users${path}`, { credentials: 'same-origin', ...options })
  if (!response.ok) {
    const error = new Error(`Request failed: ${response.status}`) as Error & { status: number }
    error.status = response.status
    throw error
  }
  return response.status === 204 ? undefined as T : response.json()
}

export function searchMembers(q: string, after?: number, signal?: AbortSignal): Promise<{ items: MemberSummary[]; next_after: number | null }> {
  const params = new URLSearchParams({ q })
  if (after) params.set('after', String(after))
  return request(`?${params}`, { signal })
}
export function getProfileDives(id: number, before?: string): Promise<DivePage> {
  return request(`/${id}/dives${before ? `?before=${encodeURIComponent(before)}` : ''}`)
}
export function saveProfile(data: { display_name: string; handle: string | null; bio: string }): Promise<MemberIdentity> {
  return request('/me/profile', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) })
}
export function uploadAvatar(file: File): Promise<MemberIdentity> {
  return request('/me/avatar', { method: 'PUT', headers: { 'Content-Type': file.type || 'application/octet-stream' }, body: file })
}
export function removeAvatar(): Promise<void> {
  return request('/me/avatar', { method: 'DELETE' })
}

export function saveAvatarStyle(avatar_hud: AvatarHud): Promise<MemberIdentity> {
  return request('/me/avatar-style', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ avatar_hud }) })
}
