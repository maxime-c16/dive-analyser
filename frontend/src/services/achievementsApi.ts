/** Member achievements client (session cookies only). */

export type AchievementCategory = 'profile' | 'community' | 'jury' | 'dives'

export type AchievementState = {
  key: string
  category: AchievementCategory
  unlocked: boolean
  unlocked_at: string | null
  seen: boolean
  target: number
  progress: number
}

export type MyAchievements = { items: AchievementState[]; unlocked: number; total: number }
export type MemberAchievements = {
  items: { key: string; category: AchievementCategory; unlocked_at: string }[]
  unlocked: number
  total: number
}
export type UnseenAchievements = { items: { key: string; unlocked_at: string }[] }

/** Dispatched after a member action that may have unlocked something. */
export const ACHIEVEMENTS_CHECK_EVENT = 'achievements:check'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api/v1/users${path}`, { credentials: 'same-origin', cache: 'no-store', ...options })
  if (!response.ok) {
    const error = new Error(`Request failed: ${response.status}`) as Error & { status: number }
    error.status = response.status
    throw error
  }
  return response.status === 204 ? (undefined as T) : response.json()
}

export const getMyAchievements = () => request<MyAchievements>('/me/achievements')
export const getUnseenAchievements = () => request<UnseenAchievements>('/me/achievements/unseen')
export const getMemberAchievements = (userId: number) => request<MemberAchievements>(`/${userId}/achievements`)
export const markAchievementsSeen = (keys: string[] = []) =>
  request<void>('/me/achievements/seen', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ keys }),
  })

/**
 * Member writes are scattered across the app, so one wrapper around fetch
 * asks the toaster to re-check after any successful write instead of every
 * call site remembering to. Reads, auth, receipts and the achievements calls
 * themselves are ignored. Idempotent; call once at startup.
 */
const IGNORED_WRITE = /^\/api\/v1\/(?:auth\/|notifications|notification-prefs|users\/me\/achievements|messages\/.*\/receipts)/
let installed = false

export function installAchievementProbe(): void {
  if (installed || typeof window === 'undefined' || typeof window.fetch !== 'function') return
  installed = true
  const original = window.fetch.bind(window)
  let timer: number | undefined
  window.fetch = async (input, init) => {
    const response = await original(input, init)
    try {
      const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase()
      if (response.ok && method !== 'GET' && method !== 'HEAD') {
        const raw = input instanceof Request ? input.url : String(input)
        const path = new URL(raw, window.location.origin).pathname
        if (path.startsWith('/api/v1/') && !IGNORED_WRITE.test(path)) {
          window.clearTimeout(timer)
          timer = window.setTimeout(() => window.dispatchEvent(new Event(ACHIEVEMENTS_CHECK_EVENT)), 400)
        }
      }
    } catch {
      // Never let the probe affect the caller's request.
    }
    return response
  }
}
