/**
 * Deposit-batch review client ("Récupérer mes plongeons").
 *
 * Same-origin fetch with session cookies. The backend owns batch state;
 * this module only transports it. Claim links are public (magic token),
 * everything else requires a live session.
 */

export type PendingBatch = {
  batch_id: string
  diver_id: number | null
  diver_name: string | null
  total: number
  pending: number
  first_created: string | null
}

export type ReviewDive = {
  id: number
  batch_id: string | null
  diver_id: number | null
  dive_code: string
  height: string
  performance: string
  phase1_performance: string | null
  phase2_performance: string | null
  dive_datetime: string | null
  video_uuid: string | null
  notes: string | null
  visibility: string
  accepted_at: string | null
  pending_acceptance: boolean
  deposited_by: string | null
  evaluator_note: string | null
}

export type BatchDetail = {
  batch_id: string
  diver_id: number | null
  diver_name: string | null
  dives: ReviewDive[]
}

async function readJson(response: Response): Promise<unknown> {
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response.json()
}

export async function listPendingBatches(): Promise<PendingBatch[]> {
  const data = (await readJson(
    await fetch('/api/v1/deposits/pending', {
      credentials: 'same-origin',
      cache: 'no-store',
    }),
  )) as { batches?: unknown }
  return Array.isArray(data.batches) ? (data.batches as PendingBatch[]) : []
}

function diverQuery(diverId?: number | null): string {
  return diverId == null ? '' : `?diver_id=${encodeURIComponent(String(diverId))}`
}

/** In-app review route. A batch can span divers, so the link names the diver. */
export function batchReviewPath(batchId: string, diverId?: number | null): string {
  const base = `/deposits/${encodeURIComponent(batchId)}`
  return diverId == null ? base : `${base}?diver=${encodeURIComponent(String(diverId))}`
}

export async function getBatch(batchId: string, diverId?: number | null): Promise<BatchDetail> {
  const data = (await readJson(
    await fetch(`/api/v1/deposits/batches/${encodeURIComponent(batchId)}${diverQuery(diverId)}`, {
      credentials: 'same-origin',
      cache: 'no-store',
    }),
  )) as BatchDetail
  return data
}

export async function acceptBatch(
  batchId: string,
  diveIds?: number[],
  diverId?: number | null,
): Promise<{ batch_id: string; accepted: number[] }> {
  const data = (await readJson(
    await fetch(`/api/v1/deposits/batches/${encodeURIComponent(batchId)}/accept${diverQuery(diverId)}`, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(diveIds && diveIds.length > 0 ? { dive_ids: diveIds } : {}),
    }),
  )) as { batch_id: string; accepted: number[] }
  return data
}

export async function editPendingDive(
  diveId: number,
  patch: { dive_code?: string; height?: string; notes?: string | null },
): Promise<ReviewDive> {
  const data = (await readJson(
    await fetch(`/api/v1/deposits/dives/${diveId}`, {
      method: 'PATCH',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    }),
  )) as ReviewDive
  return data
}

export function claimTokenFromHash(hash: string): string {
  const match = /#t=([^&]+)/.exec(hash || '')
  return match ? decodeURIComponent(match[1]) : ''
}

export async function peekClaim(
  token: string,
): Promise<{ valid: boolean; batch_id: string; diver_id: number | null; diver_name: string | null; pending: number }> {
  const data = (await readJson(
    await fetch('/api/v1/deposits/claim/peek', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token }),
    }),
  )) as { valid: boolean; batch_id: string; diver_id: number | null; diver_name: string | null; pending: number }
  return data
}

export async function redeemClaim(token: string): Promise<{ batch_id: string; diver_id: number | null }> {
  const data = (await readJson(
    await fetch('/api/v1/deposits/claim/redeem', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token }),
    }),
  )) as { batch_id: string; diver_id: number | null }
  return data
}

export async function getBatchEmailPref(): Promise<boolean> {
  try {
    const data = (await readJson(
      await fetch('/api/v1/deposits/email-pref', {
        credentials: 'same-origin',
        cache: 'no-store',
      }),
    )) as { enabled?: unknown }
    return data.enabled !== false
  } catch {
    return true
  }
}

export async function setBatchEmailPref(enabled: boolean): Promise<boolean> {
  const data = (await readJson(
    await fetch('/api/v1/deposits/email-pref', {
      method: 'PUT',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled }),
    }),
  )) as { enabled?: unknown }
  return data.enabled !== false
}

export type HeldEmail = {
  id: number
  batch_id: string
  diver_id: number
  diver_name: string | null
  recipient_name: string | null
  recipient_email: string | null
  clips: number
  queued_at: string | null
}

/** Admin: batch emails parked until someone confirms them. */
export async function listHeldEmails(): Promise<HeldEmail[]> {
  const data = (await readJson(
    await fetch('/api/v1/deposits/outbox/held', { credentials: 'same-origin', cache: 'no-store' }),
  )) as { emails?: unknown }
  return Array.isArray(data.emails) ? (data.emails as HeldEmail[]) : []
}

async function heldAction(action: 'release' | 'discard', ids?: number[]): Promise<number> {
  const data = (await readJson(
    await fetch(`/api/v1/deposits/outbox/${action}`, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(ids && ids.length > 0 ? { ids } : {}),
    }),
  )) as { released?: number; discarded?: number }
  return data.released ?? data.discarded ?? 0
}

/** No ids = every held email. */
export const releaseHeldEmails = (ids?: number[]) => heldAction('release', ids)
export const discardHeldEmails = (ids?: number[]) => heldAction('discard', ids)
