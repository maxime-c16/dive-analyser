import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import AdminUsers from './AdminUsers'
import { roleLabel, roleTitle } from '../services/adminUsersApi'

const adminUser = {
  user_id: 1,
  email: 'admin@example.test',
  display_name: 'Admin',
  role: 'owner',
  is_admin: true,
  is_active: true,
  diver_ids: [10],
  live_sessions: 1,
  created_at: '2026-01-01T00:00:00',
}

const diverUser = {
  user_id: 2,
  email: 'diver@example.test',
  display_name: 'Dana',
  role: 'friend',
  is_admin: false,
  is_active: true,
  diver_ids: [10],
  live_sessions: 1,
  created_at: '2026-01-02T00:00:00',
}

const divers = [
  { diver_id: 10, display_name: 'Aqua', canonical_name: 'aqua', active: true, bound_to_user: true },
]

function mockDirectory(users = [adminUser, diverUser]) {
  return { users, total: users.length, limit: 100, offset: 0 }
}

function installFetch(handler?: (url: string, init?: RequestInit) => unknown) {
  const calls: { url: string; init?: RequestInit }[] = []
  const spy = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url: unknown, init?: unknown) => {
    const href = String(url)
    calls.push({ url: href, init: init as RequestInit })
    if (handler) {
      const custom = handler(href, init as RequestInit)
      if (custom !== undefined) return new Response(JSON.stringify(custom), { status: 200 })
    }
    if (href.startsWith('/api/v1/admin/users')) {
      return new Response(JSON.stringify(mockDirectory()), { status: 200 })
    }
    if (href === '/api/v1/admin/divers') {
      return new Response(JSON.stringify({ divers }), { status: 200 })
    }
    return new Response('{}', { status: 404 })
  })
  return { spy, calls }
}

beforeEach(() => {
  vi.restoreAllMocks()
})

describe('role labels', () => {
  it('maps is_admin to the two public roles', () => {
    expect(roleLabel({ is_admin: true })).toBe('administrator')
    expect(roleLabel({ is_admin: false })).toBe('diver')
    expect(roleTitle({ is_admin: true })).toBe('Administrator')
    expect(roleTitle({ is_admin: false })).toBe('Diver')
  })
})

describe('AdminUsers', () => {
  it('lists users with Administrator and Diver badges', async () => {
    installFetch()
    render(<AdminUsers currentUserId={1} />)
    expect(await screen.findByText('admin@example.test')).toBeInTheDocument()
    expect(screen.getByText('diver@example.test')).toBeInTheDocument()
    expect(screen.getByText('Administrator')).toBeInTheDocument()
    expect(screen.getByText('Diver')).toBeInTheDocument()
  })

  it('searches by name or email', async () => {
    const { calls } = installFetch()
    render(<AdminUsers currentUserId={1} />)
    await screen.findByText('diver@example.test')
    calls.length = 0
    fireEvent.change(screen.getByLabelText('Search users'), { target: { value: 'diver' } })
    fireEvent.keyDown(screen.getByLabelText('Search users'), { key: 'Enter' })
    await waitFor(() =>
      expect(calls.some(c => c.url.includes('/api/v1/admin/users') && c.url.includes('q=diver'))).toBe(true),
    )
  })

  it('filters by disabled status', async () => {
    const { calls } = installFetch()
    render(<AdminUsers currentUserId={1} />)
    await screen.findByText('diver@example.test')
    calls.length = 0
    fireEvent.change(screen.getByLabelText('Filter by status'), { target: { value: 'disabled' } })
    await waitFor(() =>
      expect(calls.some(c => c.url.includes('is_active=false'))).toBe(true),
    )
  })

  it('disables an account and reports sign-out', async () => {
    const { calls } = installFetch((url, init) => {
      if (url === '/api/v1/admin/users/2' && init?.method === 'PATCH') {
        return { ...diverUser, is_active: false, revoked_sessions: 1 }
      }
      return undefined
    })
    render(<AdminUsers currentUserId={1} />)
    await screen.findByText('diver@example.test')
    fireEvent.click(screen.getAllByRole('button', { name: 'Manage' })[1])
    fireEvent.click(await screen.findByRole('button', { name: 'Disable account' }))
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('disabled and signed out'))
    const patch = calls.find(c => c.url === '/api/v1/admin/users/2' && c.init?.method === 'PATCH')
    expect(JSON.parse(String(patch?.init?.body))).toMatchObject({ is_active: false })
  })

  it('rejects short passwords in the create form without calling the API', async () => {
    const { calls } = installFetch()
    render(<AdminUsers currentUserId={1} />)
    await screen.findByText('diver@example.test')
    fireEvent.click(screen.getByRole('button', { name: 'New user' }))
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'new@example.test' } })
    fireEvent.change(screen.getByLabelText(/Password/), { target: { value: 'short' } })
    fireEvent.click(screen.getByRole('button', { name: /Create user/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent('at least 10 characters')
    expect(calls.some(c => c.init?.method === 'POST' && c.url === '/api/v1/admin/users')).toBe(false)
  })

  it('requires a diver binding when creating an administrator', async () => {
    const { calls } = installFetch()
    render(<AdminUsers currentUserId={1} />)
    await screen.findByText('diver@example.test')
    fireEvent.click(screen.getByRole('button', { name: 'New user' }))
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'boss@example.test' } })
    fireEvent.change(screen.getByLabelText(/Password/), { target: { value: 'brand-new-password-99' } })
    fireEvent.change(screen.getByLabelText('Role'), { target: { value: 'administrator' } })
    fireEvent.click(screen.getByRole('button', { name: /Create user/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent('needs a diver binding')
    expect(calls.some(c => c.init?.method === 'POST' && c.url === '/api/v1/admin/users')).toBe(false)
  })

  it('hides self-lockout actions for your own account', async () => {
    installFetch()
    render(<AdminUsers currentUserId={1} />)
    await screen.findByText('admin@example.test')
    fireEvent.click(screen.getAllByRole('button', { name: 'Manage' })[0])
    const section = await screen.findByRole('region', { name: 'Manage admin@example.test' })
    expect(within(section).queryByRole('button', { name: 'Disable account' })).not.toBeInTheDocument()
    expect(within(section).queryByLabelText('New password')).not.toBeInTheDocument()
    expect(within(section).getByText('You cannot remove your own administrator role.')).toBeInTheDocument()
  })

  it('resets a password and reports revoked sessions', async () => {
    installFetch((url, init) => {
      if (url === '/api/v1/admin/users/2/reset-password' && init?.method === 'POST') {
        return { ok: true, revoked_sessions: 2 }
      }
      return undefined
    })
    render(<AdminUsers currentUserId={1} />)
    await screen.findByText('diver@example.test')
    fireEvent.click(screen.getAllByRole('button', { name: 'Manage' })[1])
    fireEvent.change(await screen.findByLabelText('New password'), { target: { value: 'brand-new-password-99' } })
    fireEvent.click(screen.getByRole('button', { name: 'Reset' }))
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('2 session(s) signed out'))
  })

  it('binds and unbinds divers', async () => {
    const { calls } = installFetch((url, init) => {
      if (url === '/api/v1/admin/users/2/divers' && init?.method === 'POST') {
        return { ok: true, bound: true, noop: false }
      }
      return undefined
    })
    render(<AdminUsers currentUserId={1} />)
    await screen.findByText('diver@example.test')
    fireEvent.click(screen.getAllByRole('button', { name: 'Manage' })[1])
    fireEvent.click(await screen.findByRole('button', { name: 'Unbind' }))
    await waitFor(() =>
      expect(calls.some(c => c.url === '/api/v1/admin/users/2/divers/10' && c.init?.method === 'DELETE')).toBe(true),
    )
  })
})
