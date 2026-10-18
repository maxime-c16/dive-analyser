// Calendar API client (server authority: backend/app/api/v1/calendar.py).
// Every response is account-scoped and served with Cache-Control: no-store;
// nothing here is cached across accounts.

export type Kind = 'club' | 'group' | 'personal' | 'federal'
export type Audience = 'group' | 'club' | 'community' | 'invited'
export type EventType = 'training' | 'camp' | 'outing' | 'competition' | 'other'
export type Interest = 'interested' | 'maybe' | 'declined'
export type Role = 'member' | 'coach' | 'manager'

export interface EventSummary {
  id: number; calendar_id: number; calendar_kind: Kind; club_id: number | null; event_type: EventType
  audience: Audience; status: 'draft' | 'published' | 'cancelled'; title: string; timezone: string; version: number
  calendar_name: string | null; training_group_id: number | null
}
export interface Occurrence {
  id: number; occurrence_key: string; status: 'scheduled' | 'cancelled'; is_all_day: boolean
  starts_at: string | null; ends_at: string | null; start_date: string | null; end_date: string | null
  venue_name: string | null; version: number; event: EventSummary; my_interest: Interest | null
  my_absence_reported: boolean; local_date: string; local_start: string | null; local_end: string | null
  imported: boolean
}
export interface Resource {
  id: number; kind: string; label: string; url: string | null; deadline_kind: string | null; due_at: string | null
  edition_label: string | null; source_verified_at: string | null
}
export interface Change { kind: 'time_changed' | 'venue_changed' | 'cancelled'; at: string; fields: string[] }
export interface OccurrenceDetail extends Occurrence {
  resources: Resource[]; description: string; venue_address: string | null; map_url: string | null
  can_edit: boolean; can_report_absence: boolean; following: boolean; my_invitation: string | null
  organizer_name: string | null; changes: Change[]
}
export interface EventDetail extends EventSummary {
  description: string; venue_name: string | null; venue_address: string | null; map_url: string | null
  organizer_user_id: number | null; organizer_name: string | null; my_invitation: string | null
  resources: Resource[]; occurrences: Occurrence[]; following: boolean; can_edit: boolean; changes: Change[]
}
export interface CalendarInfo {
  id: number; kind: Kind; name: string; club_id: number | null; training_group_id: number | null
  following: boolean; can_publish: boolean; allowed_audiences: Audience[]
}
export interface Group { id: number; club_id: number; slug: string; name: string }
export interface MyClub {
  club: { id: number; slug: string; name: string; short_name: string | null; timezone: string }
  membership: { id: number; role: Role; can_publish: boolean; can_assign_groups: boolean; source: string }
  group: Group | null; self_declared: boolean
}
export interface RosterEntry {
  user_id: number; display_name: string; role: Role; group_id: number | null; membership_id: number | null
  can_publish: boolean | null; can_assign_groups: boolean | null; self_declared: boolean | null
  group_since: string | null
}
export interface Roster {
  club_id: number; my_role: Role | null; can_assign_groups: boolean; can_manage_members: boolean
  groups: Group[]; items: RosterEntry[]
}
export interface Invitation { user_id: number; display_name: string; status: string; responded_at: string | null }
export interface LinkableDive { id: number; dive_code: string; dive_datetime: string; linked: boolean }
export interface When {
  all_day: boolean; start_local?: string; end_local?: string; start_date?: string; end_date?: string
}
export interface EventInput {
  calendar_id: number | null; event_type: EventType; audience: Audience; status: 'draft' | 'published'
  title: string; description: string; venue_name: string | null; venue_address: string | null
  map_url: string | null; timezone: string; when: When
}

export class CalendarError extends Error {
  constructor(public status: number, public code: string, message: string) { super(message) }
}

const BASE = '/api/v1/calendar'

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(BASE + path, {
    credentials: 'same-origin', cache: 'no-store', ...init,
    headers: { ...(init.body ? { 'Content-Type': 'application/json' } : {}), ...(init.headers || {}) },
  })
  if (response.status === 204) return undefined as T
  const data = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = data?.detail
    const code = typeof detail === 'object' && detail?.code ? detail.code : `http_${response.status}`
    const message = typeof detail === 'object' && detail?.message ? detail.message : typeof detail === 'string' ? detail : ''
    throw new CalendarError(response.status, code, message)
  }
  return data as T
}
const json = (method: string, body?: unknown): RequestInit => ({ method, body: body === undefined ? undefined : JSON.stringify(body) })

export const calendarApi = {
  me: () => request<{ clubs: MyClub[] }>('/me'),
  calendars: () => request<{ items: CalendarInfo[] }>('/calendars'),
  async occurrences(from: string, to: string, signal?: AbortSignal): Promise<Occurrence[]> {
    // Follow keyset cursors so a busy month is never silently truncated.
    const items: Occurrence[] = []
    let cursor: string | null = null
    for (let page = 0; page < 10; page++) {
      const q = new URLSearchParams({ from, to, limit: '200' })
      if (cursor) q.set('cursor', cursor)
      const data: { items: Occurrence[]; next_cursor: string | null } = await request(`/occurrences?${q}`, { signal })
      items.push(...data.items)
      cursor = data.next_cursor
      if (!cursor) break
    }
    return items
  },
  occurrence: (id: number) => request<OccurrenceDetail>(`/occurrences/${id}`),
  event: (id: number) => request<EventDetail>(`/events/${id}`),
  createEvent: (input: EventInput, idempotencyKey: string) =>
    request<EventDetail>('/events', { ...json('POST', input), headers: { 'Idempotency-Key': idempotencyKey } }),
  updateEvent: (id: number, body: Partial<EventInput> & { expected_version: number; status?: 'published' }) =>
    request<EventDetail>(`/events/${id}`, json('PATCH', body)),
  cancelEvent: (id: number, expected_version: number) => request<EventDetail>(`/events/${id}/cancel`, json('POST', { expected_version })),
  updateOccurrence: (id: number, body: { expected_version: number; when?: When; venue_name?: string | null }) =>
    request<OccurrenceDetail>(`/occurrences/${id}`, json('PATCH', body)),
  cancelOccurrence: (id: number, expected_version: number) =>
    request<OccurrenceDetail>(`/occurrences/${id}/cancel`, json('POST', { expected_version })),
  setInterest: (id: number, state: Interest | null) => request<OccurrenceDetail>(`/occurrences/${id}/interest`, json('PUT', { state })),
  setAbsence: (id: number, absent: boolean) => request<OccurrenceDetail>(`/occurrences/${id}/absence`, json('PUT', { absent })),
  followEvent: (id: number, on: boolean) => request<void>(`/events/${id}/follow`, { method: on ? 'PUT' : 'DELETE' }),
  followCalendar: (id: number, on: boolean) => request<void>(`/calendars/${id}/follow`, { method: on ? 'PUT' : 'DELETE' }),
  invitations: (eventId: number) => request<{ items: Invitation[] }>(`/events/${eventId}/invitations`),
  invite: (eventId: number, user_ids: number[]) => request<{ items: Invitation[] }>(`/events/${eventId}/invitations`, json('POST', { user_ids })),
  revoke: (eventId: number, userId: number) => request<{ items: Invitation[] }>(`/events/${eventId}/invitations/${userId}/revoke`, json('POST')),
  respond: (eventId: number, status: 'accepted' | 'declined') => request<EventDetail>(`/events/${eventId}/invitation`, json('PUT', { status })),
  dives: (occurrenceId: number) => request<{ items: LinkableDive[] }>(`/occurrences/${occurrenceId}/dives`),
  linkDive: (occurrenceId: number, diveId: number, on: boolean) =>
    request<{ items: LinkableDive[] }>(`/occurrences/${occurrenceId}/dives/${diveId}`, { method: on ? 'PUT' : 'DELETE' }),
  roster: (clubId: number) => request<Roster>(`/clubs/${clubId}/members`),
  clubResources: (clubId: number) => request<Resource[]>(`/clubs/${clubId}/resources`),
  assignGroup: (clubId: number, user_id: number, group_id: number | null, effective_from: string) =>
    request<unknown>(`/clubs/${clubId}/group-assignment`, json('PUT', { user_id, group_id, effective_from })),
  updateMembership: (clubId: number, membershipId: number, body: { role?: Role; can_publish?: boolean; can_assign_groups?: boolean }) =>
    request<unknown>(`/clubs/${clubId}/memberships/${membershipId}`, json('PATCH', body)),
  endMembership: (clubId: number, membershipId: number) => request<unknown>(`/clubs/${clubId}/memberships/${membershipId}/end`, json('POST')),
  leaveClub: (clubId: number) => request<unknown>(`/clubs/${clubId}/leave`, json('POST')),
}

export interface SignupClub { id: number; name: string; short_name: string | null }

/** Clubs selectable at signup; [] when the calendar feature is off (404). */
export async function signupClubs(): Promise<SignupClub[]> {
  try {
    const response = await fetch('/api/v1/auth/signup-clubs', { credentials: 'same-origin' })
    if (!response.ok) return []
    const data = await response.json()
    return Array.isArray(data) ? data : []
  } catch { return [] }
}

export function newIdempotencyKey(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `k-${Date.now()}-${Math.random().toString(36).slice(2)}`
}
