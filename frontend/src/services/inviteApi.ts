/** Public client for diver invitation links (/invite#t=…).
 *
 * The token lives in the URL FRAGMENT so it never reaches nginx access logs
 * or the slow-request logger; it is posted in the body, exactly like the
 * deposit-batch claim link. The peek call is read-only (email prefetchers
 * must not burn the link); only the explicit submit redeems it.
 */

async function readJson(response: Response): Promise<unknown> {
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response.json()
}

export function inviteTokenFromHash(hash: string): string {
  const match = /#t=([^&]+)/.exec(hash || '')
  return match ? decodeURIComponent(match[1]) : ''
}

export interface InvitePreview {
  valid: boolean
  diver_id: number
  diver_name: string | null
  expires_at: string | null
}

export async function peekInvite(token: string): Promise<InvitePreview> {
  return (await readJson(
    await fetch('/api/v1/auth/invite/peek', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token }),
    }),
  )) as InvitePreview
}

export interface InviteRegistration {
  user_id: number
  email: string
  role: string
  diver_id: number
}

export interface InviteRegistrationError {
  /** HTTP status of the refusal (404 / 409 / 422 / 429 / 403). */
  status: number
  detail: string
  /** Stable machine-readable reason from the API. */
  code?: string
}

export async function registerWithInvite(
  token: string,
  body: { email: string; password: string; display_name?: string },
): Promise<InviteRegistration> {
  const response = await fetch('/api/v1/auth/register-invite', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token, ...body }),
  })
  if (!response.ok) {
    let detail = ''
    let code: string | undefined
    try {
      const payload = (await response.json()) as { detail?: unknown; code?: unknown }
      detail = typeof payload?.detail === 'string' ? payload.detail : ''
      code = typeof payload?.code === 'string' ? payload.code : undefined
    } catch {
      // Non-JSON error body: fall back to the status text.
    }
    const error: InviteRegistrationError = {
      status: response.status,
      detail: detail || `Request failed: ${response.status}`,
      code,
    }
    throw error
  }
  return (await response.json()) as InviteRegistration
}
