import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import AdminDiverInvites from './AdminDiverInvites'

const directory = [
  { diver_id: 10, display_name: 'Aqua', canonical_name: 'aqua', active: true, bound_to_user: true, has_live_invite: false },
  { diver_id: 11, display_name: 'Beth', canonical_name: 'beth', active: true, bound_to_user: false, has_live_invite: false },
  { diver_id: 12, display_name: 'Cleo', canonical_name: 'cleo', active: true, bound_to_user: false, has_live_invite: true },
]

const liveInvites = [
  {
    invite_id: 44,
    diver_id: 12,
    diver_name: 'Cleo',
    status: 'live',
    created_at: '2026-10-01T10:00:00',
    expires_at: '2026-10-08T10:00:00',
    used_at: null,
    revoked_at: null,
    created_by_user_id: 1,
    user_id: null,
  },
]

function mockFetch(options: { created?: Record<string, unknown>; fail?: boolean } = {}) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    if (options.fail) return Response.json({ detail: 'boom' }, { status: 500 })
    if (method === 'POST' && url.includes('/invites')) {
      return Response.json(
        {
          invite_id: 99,
          diver_id: 11,
          diver_name: 'Beth',
          status: 'live',
          invite_url: 'https://dive.test/invite#t=secret-token',
          email_sent: null,
          email_error: null,
          created_at: '2026-10-02T09:00:00',
          expires_at: '2026-10-09T09:00:00',
          used_at: null,
          revoked_at: null,
          created_by_user_id: 1,
          user_id: null,
          ...options.created,
        },
        { status: 201 },
      )
    }
    if (method === 'DELETE' && url.includes('/api/v1/admin/invites/')) {
      return Response.json({ invite_id: 44, diver_id: 12, diver_name: 'Cleo', status: 'revoked' })
    }
    if (url.includes('/api/v1/admin/invites')) {
      return Response.json({ invites: liveInvites, total: 1, limit: 100, offset: 0 })
    }
    if (url.includes('/api/v1/admin/divers')) {
      return Response.json({ divers: directory, total: directory.length, limit: 200, offset: 0 })
    }
    return Response.json({ detail: 'unexpected' }, { status: 500 })
  })
}

beforeEach(() => {
  vi.restoreAllMocks()
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: { writeText: vi.fn().mockResolvedValue(undefined) },
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

function rowOf(name: string) {
  // Scope to the unclaimed-diver list: names also appear in the table below.
  return within(screen.getByRole('list')).getByText(name).closest('li') as HTMLElement
}

describe('AdminDiverInvites', () => {
  it('offers a link only for diver names no account owns yet', async () => {
    mockFetch()
    render(<AdminDiverInvites />)
    await screen.findByText('Beth')
    // Aqua already has an account: no invite action, and it is not listed.
    expect(screen.queryByText('Aqua')).not.toBeInTheDocument()
    expect(within(rowOf('Beth')).getByRole('button', { name: /create link/i })).toBeInTheDocument()
    expect(within(rowOf('Cleo')).getByRole('button', { name: /create link/i })).toBeInTheDocument()
  })

  it('shows the minted link once, with a copy action', async () => {
    mockFetch()
    render(<AdminDiverInvites />)
    await screen.findByText('Beth')
    fireEvent.click(within(rowOf('Beth')).getByRole('button', { name: /create link/i }))
    const panel = await screen.findByText(/link ready for beth/i)
    expect(panel).toBeInTheDocument()
    expect(screen.getByText(/https:\/\/dive\.test\/invite#t=secret-token/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /copy link/i }))
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith('https://dive.test/invite#t=secret-token'))
  })

  it('warns that the link is shown once and keeps the mailer error visible', async () => {
    mockFetch({ created: { email_sent: false, email_error: 'email not configured' } })
    render(<AdminDiverInvites />)
    fireEvent.change(screen.getByLabelText(/email the link to/i), { target: { value: 'lea@example.test' } })
    await screen.findByText('Beth')
    fireEvent.click(within(rowOf('Beth')).getByRole('button', { name: /create link/i }))
    expect(await screen.findByText(/only time the link is shown/i)).toBeInTheDocument()
    expect(screen.getByText(/email not configured/i)).toBeInTheDocument()
  })

  it('lists outstanding invitations and revokes them', async () => {
    const fetch = mockFetch()
    render(<AdminDiverInvites />)
    const table = await screen.findByRole('table')
    expect(within(table).getByText('Cleo')).toBeInTheDocument()
    expect(within(table).getByText('live')).toBeInTheDocument()
    fireEvent.click(within(table).getByRole('button', { name: /revoke/i }))
    await waitFor(() =>
      expect(fetch.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(true),
    )
  })

  it('surfaces a failed request instead of showing an empty list', async () => {
    mockFetch({ fail: true })
    render(<AdminDiverInvites />)
    expect(await screen.findByRole('alert')).toHaveTextContent('boom')
  })
})
