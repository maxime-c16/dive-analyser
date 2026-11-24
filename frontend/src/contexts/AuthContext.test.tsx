import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { AuthProvider, useAuth } from './AuthContext'
import { takeBootstrapSeed } from '../services/bootstrap'

vi.mock('../navigation/sessionContext', () => ({ clearNavigationSession: vi.fn() }))
vi.mock('../services/libraryCache', () => ({ clearLibraryCache: vi.fn() }))
vi.mock('../services/codeSummariesApi', () => ({ clearCodeSummaryCache: vi.fn() }))
vi.mock('../services/codeCommunityApi', () => ({ clearCodeCommunityCache: vi.fn() }))
vi.mock('../services/intentCache', () => ({ clearIntentData: vi.fn() }))
vi.mock('../utils/playbackWarming', () => ({ resetPlaybackWarming: vi.fn() }))

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: Error) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

const account = (id: number) => ({ user_id: id, email: `${id}@example.test`, role: 'friend', divers: [] })
// Serves both shapes: /bootstrap nests identity under `me`, /auth/me is flat.
const body = (id: number) => ({ ...account(id), me: account(id) })
const response = (id: number) => ({ ok: true, json: async () => body(id) }) as Response

function Probe() {
  const auth = useAuth()
  return <>
    <output aria-label="account">{auth.user?.user_id ?? 'signed out'}</output>
    <output aria-label="checking">{String(auth.checking)}</output>
    <button onClick={() => void auth.refresh()}>Refresh</button>
    <button onClick={() => void auth.signOut()}>Sign out</button>
  </>
}

beforeEach(() => { vi.stubGlobal('fetch', vi.fn()) })
afterEach(() => { vi.unstubAllGlobals() })

it.each(['success', 'denial', 'transport error'] as const)(
  'keeps the newer account when an older refresh finishes with %s', async outcome => {
    const old = deferred<Response>()
    vi.mocked(fetch).mockReturnValueOnce(old.promise).mockResolvedValueOnce(response(2))
    render(<AuthProvider><Probe /></AuthProvider>)
    await act(async () => { fireEvent.click(screen.getByText('Refresh')) })
    expect(screen.getByLabelText('account')).toHaveTextContent('2')
    await act(async () => {
      if (outcome === 'transport error') old.reject(new Error('offline'))
      else old.resolve(outcome === 'denial' ? { ok: false, status: 401 } as Response : response(1))
    })
    expect(screen.getByLabelText('account')).toHaveTextContent('2')
    expect(screen.getByLabelText('checking')).toHaveTextContent('false')
  },
)

it('ignores a superseded refresh even when its response body finishes last', async () => {
  const late = deferred<ReturnType<typeof body>>()
  vi.mocked(fetch).mockResolvedValueOnce({ ok: true, json: () => late.promise } as Response)
    .mockResolvedValueOnce(response(2))
  render(<AuthProvider><Probe /></AuthProvider>)
  await act(async () => {})
  await act(async () => { fireEvent.click(screen.getByText('Refresh')) })
  await act(async () => { late.resolve(body(1)) })
  expect(screen.getByLabelText('account')).toHaveTextContent('2')
})

it('queues a refresh issued during a pending logout until the logout settles', async () => {
  const staleRefresh = deferred<Response>()
  const logout = deferred<Response>()
  vi.mocked(fetch).mockResolvedValueOnce(response(1)).mockReturnValueOnce(staleRefresh.promise)
    .mockReturnValueOnce(logout.promise).mockResolvedValueOnce(response(2))
  render(<AuthProvider><Probe /></AuthProvider>)
  await act(async () => {})
  expect(screen.getByLabelText('account')).toHaveTextContent('1')
  // A refresh started before logout becomes stale once logout begins.
  await act(async () => { fireEvent.click(screen.getByText('Refresh')) })
  await act(async () => { fireEvent.click(screen.getByText('Sign out')) })
  await act(async () => { staleRefresh.resolve(response(1)) })
  expect(screen.getByLabelText('account')).toHaveTextContent('signed out')
  // A login's refresh during the pending logout waits: no /me is issued
  // while the logout response is still in flight, so Login.tsx cannot
  // navigate while `user` is still null.
  await act(async () => { fireEvent.click(screen.getByText('Refresh')) })
  expect(fetch).toHaveBeenCalledTimes(3)
  await act(async () => { logout.resolve({ ok: true } as Response) })
  expect(fetch).toHaveBeenCalledTimes(4)
  expect(fetch).toHaveBeenLastCalledWith('/api/v1/bootstrap', { credentials: 'same-origin' })
  await act(async () => {})
  expect(screen.getByLabelText('account')).toHaveTextContent('2')
})

it('shares one logout request between concurrent sign-out calls', async () => {
  const logout = deferred<Response>()
  vi.mocked(fetch).mockResolvedValueOnce(response(1)).mockReturnValueOnce(logout.promise)
  render(<AuthProvider><Probe /></AuthProvider>)
  await act(async () => {})
  expect(screen.getByLabelText('account')).toHaveTextContent('1')
  await act(async () => {
    fireEvent.click(screen.getByText('Sign out'))
    fireEvent.click(screen.getByText('Sign out'))
  })
  expect(vi.mocked(fetch).mock.calls.filter(([url]) => url === '/api/v1/auth/logout')).toHaveLength(1)
  await act(async () => { logout.resolve({ ok: true } as Response) })
  expect(screen.getByLabelText('account')).toHaveTextContent('signed out')
})

it('starts a session with one bootstrap read and seeds the shell once', async () => {
  vi.mocked(fetch).mockResolvedValueOnce({ ok: true, json: async () => ({
    me: account(7), messages_unread: { unread_count: 3 }, notifications: { items: [], unread_count: 0, has_more: false },
  }) } as Response)
  render(<AuthProvider><Probe /></AuthProvider>)
  await act(async () => {})
  expect(screen.getByLabelText('account')).toHaveTextContent('7')
  expect(fetch).toHaveBeenCalledTimes(1)
  expect(fetch).toHaveBeenCalledWith('/api/v1/bootstrap', { credentials: 'same-origin' })
  expect(takeBootstrapSeed('messages_unread', 8)).toBeUndefined()
  expect(takeBootstrapSeed('messages_unread', 7)).toEqual({ unread_count: 3 })
  expect(takeBootstrapSeed('messages_unread', 7)).toBeUndefined()
  expect(takeBootstrapSeed('achievements_unseen', 7)).toBeUndefined()
})

it('falls back to /auth/me when the backend has no bootstrap route', async () => {
  vi.mocked(fetch).mockResolvedValueOnce({ ok: false, status: 404 } as Response)
    .mockResolvedValueOnce({ ok: true, json: async () => account(4) } as Response)
  render(<AuthProvider><Probe /></AuthProvider>)
  await act(async () => {})
  expect(screen.getByLabelText('account')).toHaveTextContent('4')
  expect(vi.mocked(fetch).mock.calls.map(([url]) => url)).toEqual(['/api/v1/bootstrap', '/api/v1/auth/me'])
  expect(takeBootstrapSeed('notifications', 4)).toBeUndefined()
})

it('refreshes a signed-in identity without re-reading the shell', async () => {
  vi.mocked(fetch).mockResolvedValueOnce(response(1)).mockResolvedValueOnce({ ok: true, json: async () => account(1) } as Response)
  render(<AuthProvider><Probe /></AuthProvider>)
  await act(async () => {})
  await act(async () => { fireEvent.click(screen.getByText('Refresh')) })
  expect(vi.mocked(fetch).mock.calls.map(([url]) => url)).toEqual(['/api/v1/bootstrap', '/api/v1/auth/me'])
  expect(screen.getByLabelText('account')).toHaveTextContent('1')
})
