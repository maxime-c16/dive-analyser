/** Activity history + member profile client (session cookies only). */

export type ActivityKind = 'dive_like' | 'comment' | 'comment_like'
export type ActivityDirection = 'sent' | 'received'
export type ActivityActor = { user_id: number | null; guest_id: number | null; display_name: string }
export type ActivityDive = {
  id: number
  dive_code: string
  dive_number: string | null
  height: string
  dive_datetime: string | null
  diver_name: string | null
}

export interface ActivityItem {
  key: string
  kind: ActivityKind
  direction: ActivityDirection
  created_at: string | null
  actor: ActivityActor
  dive: ActivityDive
  comment: { id: number; body: string } | null
}

export interface ActivityPage {
  items: ActivityItem[]
  next_before: string | null
}

export type PublicRole = 'administrator' | 'diver'

export interface MemberProfile {
  user_id: number
  display_name: string
  role: PublicRole
  is_admin: boolean
  is_self: boolean
  handle: string | null
  bio: string
  avatar_url: string | null
  joined_at: string | null
  divers: { diver_id: number; display_name: string }[]
}

async function request<T>(path: string): Promise<T> {
  const response = await fetch(path, { credentials: 'same-origin' })
  if (!response.ok) {
    let detail = ''
    try {
      const body = await response.json()
      detail = typeof body?.detail === 'string' ? body.detail : ''
    } catch {
      // Non-JSON error body: fall back to the status text.
    }
    const error = new Error(detail || `Request failed: ${response.status}`) as Error & { status?: number }
    error.status = response.status
    throw error
  }
  return response.json() as Promise<T>
}

function compose(activityPath: string, params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) search.set(key, String(value))
  }
  const suffix = search.toString()
  return suffix ? `${activityPath}?${suffix}` : activityPath
}

/** Merged history for the signed-in member. */
export function getMyActivity(options?: {
  direction?: 'all' | 'sent' | 'received'
  before?: string
  limit?: number
}): Promise<ActivityPage> {
  return request<ActivityPage>(compose('/api/v1/users/me/activity', {
    direction: options?.direction && options.direction !== 'all' ? options.direction : undefined,
    before: options?.before,
    limit: options?.limit,
  }))
}

/** Another member's actions on dives visible to me (profile page feed). */
export function getUserActivity(userId: number, options?: { before?: string; limit?: number }): Promise<ActivityPage> {
  return request<ActivityPage>(compose(`/api/v1/users/${userId}/activity`, {
    before: options?.before,
    limit: options?.limit,
  }))
}

export function getUserProfile(userId: number): Promise<MemberProfile> {
  return request<MemberProfile>(`/api/v1/users/${userId}`)
}

/** Account-aggregate diver score (0-100 composite). */
export interface DiverScore {
  score: number
  provisional: boolean
  performance: { mean_score: number | null; rating_count: number; points: number; weight: number }
  judging: { evaluated_dives: number; points: number; weight: number }
  community: { interactions: number; points: number; weight: number }
}

export function getDiverScore(): Promise<DiverScore> {
  return request<DiverScore>('/api/v1/users/me/diver-score')
}
