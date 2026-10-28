import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { AuthProvider, useAuth } from './AuthContext'

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
const response = (id: number) => ({ ok: true, json: async () => account(id) }) as Response

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
  const body = deferred<ReturnType<typeof account>>()
  vi.mocked(fetch).mockResolvedValueOnce({ ok: true, json: () => body.promise } as Response)
    .mockResolvedValueOnce(response(2))
  render(<AuthProvider><Probe /></AuthProvider>)
  await act(async () => {})
  await act(async () => { fireEvent.click(screen.getByText('Refresh')) })
  await act(async () => { body.resolve(account(1)) })
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
  expect(fetch).toHaveBeenLastCalledWith('/api/v1/auth/me', { credentials: 'same-origin' })
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
