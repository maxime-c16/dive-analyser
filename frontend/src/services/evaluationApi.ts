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
  poster_url: string | null
  playback_url: string | null
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

export async function prepareEvaluationMedia(requestId: number): Promise<
  EvaluationMediaStatus & { created_jobs: string[]; reused_jobs: string[] }
> {
  const { data } = await api.post(`/api/v1/evaluations/requests/${requestId}/media/prepare`)
  return data
}
