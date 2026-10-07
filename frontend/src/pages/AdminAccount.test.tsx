import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { AccountWorkspace } from './AdminAccount'
const account = { user_id: 2, display_name: 'Dana', email: 'dana@example.test', is_admin: false, is_active: true, role: 'friend', created_at: '2026-01-01T00:00:00', live_sessions: 2, diver_ids: [10], diver_binding_total: 1 }
function mockFetch(fail = false) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input)
    if (init?.method === 'PATCH') return Response.json(fail ? { detail: 'Email already in use' } : { ...account, ...JSON.parse(String(init.body)) }, { status: fail ? 409 : 200 })
    if (init?.method === 'DELETE') return Response.json({ ok: true })
    if (url.includes('/admin/divers')) return Response.json({ divers: [{ diver_id: 10, display_name: 'Aqua', canonical_name: 'aqua', active: true, bound_to_user: true }, { diver_id: 11, display_name: 'Beth', canonical_name: 'beth', active: true, bound_to_user: false }], total: 2 })
    return Response.json(account)
  })
}
beforeEach(() => { vi.restoreAllMocks(); sessionStorage.clear() })
describe('AccountWorkspace', () => {
  it('keeps unsaved edits after an API error and can discard them', async () => {
    mockFetch(true)
    render(<AccountWorkspace accountId={2} currentUserId={1} section="profile" onSection={vi.fn()} onBack={vi.fn()} />)
    const name = await screen.findByLabelText('Display name')
    fireEvent.change(name, { target: { value: 'Changed' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Email already in use')
    expect(name).toHaveValue('Changed')
    fireEvent.click(screen.getAllByRole('button', { name: 'Discard' })[0])
    expect(name).toHaveValue('Dana')
    expect(screen.queryByText('Unsaved changes')).not.toBeInTheDocument()
  })
  it('requires confirmation for changes that revoke sessions', async () => {
    const fetch = mockFetch()
    render(<AccountWorkspace accountId={2} currentUserId={1} section="profile" onSection={vi.fn()} onBack={vi.fn()} />)
    fireEvent.change(await screen.findByLabelText('Account status'), { target: { value: 'disabled' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))
    expect(screen.getByRole('dialog')).toHaveTextContent('signs out its sessions')
    expect(fetch.mock.calls.some(([, init]) => init?.method === 'PATCH')).toBe(false)
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Confirm' }))
    await waitFor(() => expect(fetch.mock.calls.some(([, init]) => init?.method === 'PATCH')).toBe(true))
  })
})

it('recovers unsaved profile edits after leaving and reopening the account', async () => {
  mockFetch()
  const props = { accountId: 2, currentUserId: 1, section: 'profile', onSection: vi.fn(), onBack: vi.fn() }
  const first = render(<AccountWorkspace {...props} />)
  fireEvent.change(await screen.findByLabelText('Display name'), { target: { value: 'Recovered name' } })
  first.unmount()
  render(<AccountWorkspace {...props} />)
  expect(await screen.findByLabelText('Display name')).toHaveValue('Recovered name')
  expect(screen.getByText('Unsaved changes')).toBeInTheDocument()
})
