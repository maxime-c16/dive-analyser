/**
 * Community evaluation API (issue #66; extended by #67 sessions/ratings).
 * Types are the server contracts: the same shapes the backend endpoints
 * return, kept in one place for the owner toggle (ticket 1) and the
 * Évaluations flows (tickets 2–3).
 */

export const EVALUATION_PROMPT_MAX = 1000
export const EVALUATION_COMMENT_MAX = 2000

/** Owner-only summary of a dive's single evaluation request (null = none). */
export type EvaluationRequestSummary = {
  id: number
  dive_id: number
  active: boolean
  prompt: string | null
  created_at: string
  updated_at: string
}

/**
 * Evaluation media transport (stable contract agreed with ticket 3). URLs are
 * authenticated, account-scoped endpoints — never presigned links — and only
 * resolve while the request is active.
 */
export type EvaluationMediaStatus = {
  request_id: number
  dive_id: number
  video_uuid: string
  status: 'ready' | 'preparing' | 'missing'
  /** Rendition actually chosen by the server's HQ contract. */
  rendition?: string | null
  poster_url: string | null
  playback_url: string | null
  /** Ready renditions of THIS request's media (incl. poster). */
  available_renditions: string[]
}

import { api } from './api'

export async function putEvaluationRequest(
  diveId: number,
  body: { active: boolean; prompt?: string | null },
): Promise<EvaluationRequestSummary> {
  const { data } = await api.put(`/api/v1/dives/${diveId}/evaluation-request`, body)
  return data
}

export async function getEvaluationRequest(diveId: number): Promise<EvaluationRequestSummary | null> {
  const { data } = await api.get(`/api/v1/dives/${diveId}/evaluation-request`)
  return data
}

export async function getEvaluationMediaStatus(requestId: number): Promise<EvaluationMediaStatus> {
  const { data } = await api.get(`/api/v1/evaluations/requests/${requestId}/media/status`)
  return data
}

/**
 * Playback URL with an explicit rendition choice (the status payload's
 * `available_renditions` list is authoritative). The default (no param)
 * keeps the established HQ contract order server-side.
 */
export function evaluationPlaybackUrl(requestId: number, rendition?: string): string {
  const base = `/api/v1/evaluations/requests/${requestId}/media/play`
  return rendition ? `${base}?rendition=${encodeURIComponent(rendition)}` : base
}

export async function prepareEvaluationMedia(requestId: number): Promise<
  EvaluationMediaStatus & { created_jobs: string[]; reused_jobs: string[] }
> {
  const { data } = await api.post(`/api/v1/evaluations/requests/${requestId}/media/prepare`)
  return data
}

// ---------------------------------------------------------------------------
// Jury sessions, queue, ratings and history (ticket 2 contracts)
// ---------------------------------------------------------------------------

export const QUEUE_BATCH_MAX = 20
export const QUEUE_BATCH_DEFAULT = 5
export const SESSION_TTL_MS = 24 * 60 * 60_000

export type EvaluationSession = {
  session_id: number
  expires_at: string
  created: boolean
}

export type QueueDivePayload = {
  id: number
  video_uuid: string
  dive_code: string
  height: string
  platform_type: string
  owner_display_name?: string | null
}

export type QueueMediaPayload = {
  status: 'ready' | 'preparing' | 'missing'
  poster_url: string | null
  playback_url: string | null
}

/** Fresh batch item: full payload. Retry item: plus `unavailable` (and no
 * media/dive when the request became unavailable). */
export type QueueItem = {
  request_id: number
  dive_id: number
  prompt: string | null
  dive: QueueDivePayload
  media: QueueMediaPayload
  unavailable?: boolean
}

export type QueueUnavailableItem = {
  request_id: number
  dive_id: number
  unavailable: true
}

export type QueueBatch = {
  batch_id: string
  items: Array<QueueItem | QueueUnavailableItem>
  has_more: boolean
}

export type RatingRecord = {
  id: number
  request_id: number
  evaluator_user_id: number
  score_half_steps: number // 0–20; display /2 → 0–10 by half points
  comment: string | null
  created_at: string
}

/** Panel = the current votes of the request (owner or judged member). */
export type JuryResults = {
  request_id: number
  rating_count: number
  mean_score: number | null // 0–10, null when no vote yet
  ratings: Array<{
    id: number
    score_half_steps: number
    author?: string | null
    comment: string | null
    created_at: string
  }>
  my_rating: RatingRecord | null
}

export type SubmissionResponse = {
  rating: RatingRecord
  results: JuryResults
}

export type OwnerRequestSummary = {
  request_id: number
  dive_id: number
  active: boolean
  prompt: string | null
  created_at: string
  updated_at: string
  dive: {
    id: number
    video_uuid: string | null
    dive_code: string
    height: string
    platform_type: string
    owner_display_name: string | null
  }
  rating_count: number
  mean_score: number | null
}

export type OwnedPage = {
  items: OwnerRequestSummary[]
  total: number
  limit: number
  offset: number
}

/** Own vote history: frozen dive context, never a media URL. */
export type MyRatingItem = {
  request_id: number
  dive: {
    dive_code: string
    height: string
    platform_type: string
    dive_name: string
  }
  score_half_steps: number
  comment: string | null
  created_at: string
  rating_count: number
  mean_score: number | null
}

export type MyRatingsPage = {
  items: MyRatingItem[]
  total: number
  limit: number
  offset: number
}

export const EVALUATION_CLOSED = 'EVALUATION_CLOSED'
export const RATING_ALREADY_SUBMITTED = 'RATING_ALREADY_SUBMITTED'
export const SELF_EVALUATION = 'SELF_EVALUATION'
export const SESSION_EXPIRED = 'SESSION_EXPIRED'

export async function createSession(clientSessionId: string): Promise<EvaluationSession> {
  const { data } = await api.post('/api/v1/evaluations/sessions', { client_session_id: clientSessionId })
  return data
}

export async function getQueue(
  sessionId: number,
  batchId: string,
  limit: number = QUEUE_BATCH_DEFAULT,
): Promise<QueueBatch> {
  const { data } = await api.get(`/api/v1/evaluations/sessions/${sessionId}/queue`, {
    params: { batch_id: batchId, limit },
  })
  return data
}

export async function skipRequest(sessionId: number, requestId: number): Promise<void> {
  await api.post(`/api/v1/evaluations/sessions/${sessionId}/skip`, { request_id: requestId })
}

export async function submitRating(
  requestId: number,
  scoreHalfSteps: number,
  comment?: string | null,
): Promise<SubmissionResponse> {
  const { data } = await api.post(`/api/v1/evaluations/${requestId}/ratings`, {
    score_half_steps: scoreHalfSteps,
    comment: comment ?? undefined,
  })
  return data
}

export async function getResults(requestId: number, limit = 50, offset = 0): Promise<JuryResults> {
  const { data } = await api.get(`/api/v1/evaluations/${requestId}/results`, { params: { limit, offset } })
  return data
}

export async function getOwnedRequests(limit = 10, offset = 0): Promise<OwnedPage> {
  const { data } = await api.get('/api/v1/evaluations/mine', { params: { limit, offset } })
  return data
}

export async function getMyRatings(limit = 10, offset = 0): Promise<MyRatingsPage> {
  const { data } = await api.get('/api/v1/evaluations/my-ratings', { params: { limit, offset } })
  return data
}

/**
 * Contract fixtures for the Évaluations UI (ticket 3). These are EXAMPLE data
 * documented as types, never user-facing values and never rendered as real
 * results.
 */
export const EVALUATION_FIXTURES = {
  queueBatch: {
    batch_id: 'f1d7dd32-8a8f-4a2b-a90f-3c95ce7099ad',
    items: [
      {
        request_id: 12,
        dive_id: 34,
        prompt: 'Judge the entry and the opening. Personal note for context: none.',
        dive: {
          id: 34,
          video_uuid: '7f0f3ab4-9f47-5a2b-8d1e-9d5f7a1b2c3d',
          dive_code: '107B',
          height: '3m',
          platform_type: 'springboard',
          owner_display_name: 'Claire',
        },
        media: {
          status: 'ready' as const,
          poster_url: '/api/v1/evaluations/requests/12/media/poster',
          playback_url: '/api/v1/evaluations/requests/12/media/play',
        },
      },
      {
        request_id: 13,
        dive_id: 34,
        unavailable: true as const,
      },
    ],
    has_more: true,
  },
  submission: {
    rating: {
      id: 99,
      request_id: 12,
      evaluator_user_id: 2,
      score_half_steps: 13,
      comment: 'Great hurdle, quiet entry.',
      created_at: '2026-10-06T12:00:00',
    },
    results: {
      request_id: 12,
      rating_count: 3,
      mean_score: 6.5,
      ratings: [
        { id: 91, score_half_steps: 10, author: 'Bob', comment: 'Solid flight', created_at: '2026-10-06T11:00:00' },
        { id: 92, score_half_steps: 8, author: 'Zoé', comment: null, created_at: '2026-10-06T11:30:00' },
      ],
      my_rating: null,
    },
  },
  owned: {
    items: [
      {
        request_id: 12,
        dive_id: 34,
        active: true,
        prompt: 'Judge the entry',
        created_at: '2026-10-06T09:00:00',
        updated_at: '2026-10-06T09:00:00',
        dive: { id: 34, video_uuid: 'abcd', dive_code: '107B', height: '3m', platform_type: 'springboard', owner_display_name: null },
        rating_count: 3,
        mean_score: 6.5,
      },
    ],
    total: 1,
    limit: 10,
    offset: 0,
  },
}
