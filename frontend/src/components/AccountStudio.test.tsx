import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import AccountStudio from './AccountStudio'
import type { AdminUser } from '../services/adminUsersApi'
const user: AdminUser = { user_id: 2, display_name: 'Dana', email: 'dana@example.test', is_admin: false, is_active: true, role: 'friend', created_at: null, live_sessions: 2 }
const preview = { user_id: 2, diver_id: 10, display_name: 'Aqua', currently_bound: false, proposed_bound: true, account_active: true, dive_count: 24, public_dives: 4, other_accounts: 1, before: { view: 4, manage: 0 }, after: { view: 24, manage: 24 } }
function mockFetch({ stale = false, fail = false } = {}) {
  let previewCalls = 0
  return vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input)
    if (init?.method === 'POST') return Response.json(fail ? { detail: 'Ownership could not be updated' } : { ok: true }, { status: fail ? 503 : 200 })
    if (url.includes('binding-preview')) { previewCalls++; return Response.json(stale && previewCalls > 1 ? { ...preview, other_accounts: 2 } : preview) }
    if (url.includes('access-check')) return Response.json({ user_id: 2, dive_id: 700, diver_id: 10, can_view: false, can_manage: false, account_active: true, explanation: 'Private dive requires ownership', visibility: 'private', checked_at: '2026-10-07T12:00:00Z', scope: 'Authorization only', video_authorized: false })
    if (url.includes('/admin/divers')) return Response.json({ divers: [{ diver_id: 10, display_name: 'Aqua', canonical_name: 'aqua', active: true }], total: 1 })
    return Response.json({ bindings: [], total: 0, viewable_dives: 4, manageable_dives: 0 })
  })
}
beforeEach(() => { vi.restoreAllMocks() })
describe('Production Studio', () => {
  it('resolves denied access through a real preview without mutating before confirmation', async () => {
    const fetch = mockFetch()
    render(<AccountStudio user={user} onRefresh={vi.fn().mockResolvedValue(undefined)}/>)
    fireEvent.change(screen.getByLabelText('Dive ID'), { target: { value: '700' } })
    fireEvent.click(screen.getByRole('button', { name: 'Run access check' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Preview ownership resolution' }))
    expect(await screen.findByLabelText('Ownership change preview')).toHaveTextContent('24')
    expect(fetch.mock.calls.some(([,init]) => init?.method === 'POST')).toBe(false)
    fireEvent.click(screen.getByRole('button', { name: 'Review & confirm' }))
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Confirm' }))
    await waitFor(() => expect(fetch.mock.calls.some(([,init]) => init?.method === 'POST')).toBe(true))
    expect(await screen.findByRole('status')).toHaveTextContent('Ownership updated')
    expect(screen.getByLabelText('Dive ID')).toHaveValue(700)
  })
  it('refreshes changed impact and requires a new confirmation', async () => {
    const fetch = mockFetch({ stale: true })
    render(<AccountStudio user={user} onRefresh={vi.fn()}/>)
    fireEvent.click(await screen.findByRole('button', { name: 'Preview grant' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Review & confirm' }))
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Confirm' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Access changed since this preview')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(fetch.mock.calls.some(([,init]) => init?.method === 'POST')).toBe(false)
    expect(screen.getByLabelText('Ownership change preview')).toHaveTextContent('2 other account')
  })
  it('keeps a failed change reviewable for retry', async () => {
    mockFetch({ fail: true })
    render(<AccountStudio user={user} onRefresh={vi.fn()}/>)
    fireEvent.click(await screen.findByRole('button', { name: 'Preview grant' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Review & confirm' }))
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Confirm' }))
    await waitFor(() => expect(screen.getByRole('dialog')).toHaveTextContent('Ownership could not be updated'))
    expect(screen.getByLabelText('Ownership change preview')).toBeInTheDocument()
  })
})
