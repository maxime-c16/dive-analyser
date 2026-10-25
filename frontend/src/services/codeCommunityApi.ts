import { api } from './api'
import type { AvatarHud } from '../components/MemberAvatar'
import type { Attempt } from '../utils/attemptPresentation'

export type CommunityAccount = { user_id: number; display_name: string; avatar_url: string | null; avatar_hud?: AvatarHud }
export type CommunityMember = {
  diver_id: number
  name: string
  account: CommunityAccount | null
  attempt_count: number
  scored_count: number
  median: number
  q1: number
  q3: number
  last_attempt_at: string
  /** Rolling median (window 5) over the newest 40 graded attempts, oldest first. */
  series: number[]
  best: Attempt | null
}
/** Divers with at least three graded public attempts on the code; the rest are only counted. */
export type CodeCommunity = { dive_code: string; members: CommunityMember[]; hidden_count: number }

const FRESH_MS = 60_000
const cache = new Map<string, { at: number; promise: Promise<CodeCommunity> }>()

/** `height` follows the page's height filter: 1m and 3m are not compared with each other. */
export function getCodeCommunity(code: string, height = ''): Promise<CodeCommunity> {
  const key = `${code}|${height}`
  const hit = cache.get(key)
  if (hit && Date.now() - hit.at < FRESH_MS) return hit.promise
  const promise = api.get(`/api/v1/dives/library/codes/${encodeURIComponent(code)}/community`, { params: height ? { height } : {} }).then(response => response.data as CodeCommunity)
  promise.catch(() => cache.delete(key))
  cache.set(key, { at: Date.now(), promise })
  return promise
}
