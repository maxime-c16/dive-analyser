import { api } from './api'

export interface SeriesClip { id: number; video_uuid: string; date: string; mean_score: number | null; performance_score?: number | null; rating_count: number; url: string }
export interface SeriesChoice { code: string; clip_id: number | null; dd?: number | null; clip?: SeriesClip | null }
export interface SeriesSlot extends SeriesChoice { alternatives: SeriesChoice[] }
export type SeriesClipPolicy = 'best' | 'recent'
export interface SeriesSheet {
  clip_policy?: SeriesClipPolicy
  id: number; title: string; height: string; event_id: number | null; version: number; can_edit: boolean
  updated_at: string; slot_count: number; total_slots?: number; shared_with: { id: number; name: string }[]
  slots: SeriesSlot[]; dd_reference: string
}
export interface SeriesInput { clip_policy?: SeriesClipPolicy; title: string; height: string; event_id: number | null; slots: SeriesSlot[] }
const choice = (c: SeriesChoice) => ({ code: c.code.trim().toUpperCase(), clip_id: c.clip_id })
function payload(s: SeriesInput): SeriesInput {
  return { clip_policy: s.clip_policy ?? 'best', title: s.title, height: s.height, event_id: s.event_id,
    slots: s.slots.map(s => ({ ...choice(s), alternatives: s.alternatives.filter(a => a.code.trim()).map(choice) })) }
}
export const seriesApi = {
  list: (eventId?: number, offset = 0) => api.get<SeriesSheet[]>('/api/v1/series', { params: { event_id: eventId, offset } }).then(r => r.data),
  get: (id: number) => api.get<SeriesSheet>(`/api/v1/series/${id}`).then(r => r.data),
  create: (s: SeriesInput) => api.post<SeriesSheet>('/api/v1/series', payload(s)).then(r => r.data),
  save: (s: SeriesSheet) => api.put<SeriesSheet>(`/api/v1/series/${s.id}`, { ...payload(s), expected_version: s.version }).then(r => r.data),
  clips: (code: string, height: string, policy: SeriesClipPolicy = 'best') => api.get<SeriesClip[]>('/api/v1/series/clips', { params: { code, height, policy } }).then(r => r.data),
  share: (s: SeriesSheet, ids: number[]) => api.put<SeriesSheet>(`/api/v1/series/${s.id}/sharing`, { expected_version: s.version, user_ids: ids }).then(r => r.data),
}

export const seriesClipScore = (clip: SeriesClip) => clip.mean_score ?? clip.performance_score ?? null
