import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import Invite from './Invite'

const refresh = vi.fn()

vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({ refresh }),
}))

function renderInvite(hash = '#t=raw-token-value') {
  return render(
    <MemoryRouter initialEntries={[`/invite${hash}`]}>
      <Routes>
        <Route path="/invite" element={<Invite />} />
        <Route path="/dives" element={<p>Library page</p>} />
        <Route path="/login" element={<p>Sign-in page</p>} />
      </Routes>
    </MemoryRouter>,
  )
}

function mockFetch(handlers: {
  peek?: () => Response
  register?: () => Response
  clubs?: () => Response
}) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    if (url.includes('/auth/invite/peek') && method === 'POST') {
      return handlers.peek ? handlers.peek() : Response.json({ valid: true, diver_id: 7, diver_name: 'Lea', expires_at: null })
    }
    if (url.includes('/auth/signup-clubs')) {
      // Calendar feature off by default: the club list answers 404.
      return handlers.clubs ? handlers.clubs() : Response.json({ detail: 'Not found' }, { status: 404 })
    }
    if (url.includes('/auth/register-invite') && method === 'POST') {
      return handlers.register ? handlers.register() : Response.json({ user_id: 3, email: 'lea@example.test', role: 'friend', diver_id: 7 }, { status: 201 })
    }
    return Response.json({ detail: 'unexpected call' }, { status: 500 })
  })
}

const fill = (label: RegExp, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } })

beforeEach(() => {
  refresh.mockReset()
  vi.restoreAllMocks()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Invite page', () => {
  it('rejects a link with no token in the fragment', async () => {
    mockFetch({})
    renderInvite('')
    expect(await screen.findByText(/invalid or has already been used/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /back to sign in/i })).toBeInTheDocument()
  })

  it('shows the invited diver once the link is previewed', async () => {
    mockFetch({})
    renderInvite()
    expect(await screen.findByText('Lea')).toBeInTheDocument()
    expect(screen.getByText(/invited to claim the dives of/i)).toBeInTheDocument()
  })

  it('marks an invalid, used or expired link without asking for anything', async () => {
    mockFetch({ peek: () => Response.json({ detail: 'Link not found', code: 'link_invalid' }, { status: 404 }) })
    renderInvite()
    expect(await screen.findByText(/invalid or has already been used/i)).toBeInTheDocument()
    expect(screen.queryByLabelText(/email/i)).not.toBeInTheDocument()
  })

  it('sends an optional self-declared club choice when the calendar offers clubs', async () => {
    const fetch = mockFetch({ clubs: () => Response.json([{ id: 4, name: 'KCPM Montreuil', short_name: 'KCPM' }]) })
    renderInvite()
    await screen.findByText('Lea')
    fill(/email/i, 'lea@example.test')
    fill(/^password/i, 'correct-horse-battery')
    fill(/confirm password/i, 'correct-horse-battery')
    fireEvent.change(await screen.findByLabelText(/^club/i), { target: { value: '4' } })
    expect(screen.getByText(/self-declared/i)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /create my account/i }))
    await waitFor(() => expect(fetch.mock.calls.some(([input]) => String(input).includes('/register-invite'))).toBe(true))
    const call = fetch.mock.calls.find(([input]) => String(input).includes('/register-invite'))!
    expect(JSON.parse(String(call[1]!.body))).toMatchObject({ club_id: 4 })
  })

  it('requires matching passwords before calling the API', async () => {
    const fetch = mockFetch({})
    renderInvite()
    await screen.findByText('Lea')
    fill(/email/i, 'lea@example.test')
    fill(/^password/i, 'correct-horse-battery')
    fill(/confirm password/i, 'different-password-value')
    fireEvent.click(screen.getByRole('button', { name: /create my account/i }))
    expect(await screen.findByText(/passwords do not match/i)).toBeInTheDocument()
    // Only the peek (and the optional club list): no account request.
    expect(fetch.mock.calls.filter(([input]) => String(input).includes('/register-invite'))).toHaveLength(0)
  })

  it('creates the account, signs in and lands on the library', async () => {
    const fetch = mockFetch({})
    renderInvite()
    await screen.findByText('Lea')
    fill(/email/i, 'lea@example.test')
    fill(/display name/i, 'Lea')
    fill(/^password/i, 'correct-horse-battery')
    fill(/confirm password/i, 'correct-horse-battery')
    fireEvent.click(screen.getByRole('button', { name: /create my account/i }))

    await waitFor(() => expect(screen.getByText('Library page')).toBeInTheDocument())
    expect(refresh).toHaveBeenCalled()
    // Exactly one registration POST, carrying the fragment token in the body
    // (never in a URL) so it cannot land in access logs. The peek POST is
    // distinguished by having no email field.
    const posts = fetch.mock.calls.filter(([, init]) => init?.method === 'POST' && String(init.body).includes('lea@example.test'))
    expect(posts).toHaveLength(1)
    expect(String(posts[0][1]?.body)).toContain('"token":"raw-token-value"')
  })

  it('explains a link that was claimed by someone else in the meantime', async () => {
    mockFetch({
      register: () => Response.json({ detail: 'These dives already belong to another account', code: 'diver_claimed' }, { status: 409 }),
    })
    renderInvite()
    await screen.findByText('Lea')
    fill(/email/i, 'lea@example.test')
    fill(/^password/i, 'correct-horse-battery')
    fill(/confirm password/i, 'correct-horse-battery')
    fireEvent.click(screen.getByRole('button', { name: /create my account/i }))
    expect(await screen.findByText(/already belong to another account/i)).toBeInTheDocument()
  })

  it('explains a duplicate email', async () => {
    mockFetch({
      register: () => Response.json({ detail: 'An account with this email already exists', code: 'email_taken' }, { status: 409 }),
    })
    renderInvite()
    await screen.findByText('Lea')
    fill(/email/i, 'taken@example.test')
    fill(/^password/i, 'correct-horse-battery')
    fill(/confirm password/i, 'correct-horse-battery')
    fireEvent.click(screen.getByRole('button', { name: /create my account/i }))
    expect(await screen.findByText(/account with this email already exists/i)).toBeInTheDocument()
  })

  it('reports a link consumed between the preview and the submit', async () => {
    mockFetch({
      register: () => Response.json({ detail: 'Link not found', code: 'link_invalid' }, { status: 404 }),
    })
    renderInvite()
    await screen.findByText('Lea')
    fill(/email/i, 'lea@example.test')
    fill(/^password/i, 'correct-horse-battery')
    fill(/confirm password/i, 'correct-horse-battery')
    fireEvent.click(screen.getByRole('button', { name: /create my account/i }))
    expect(await screen.findByText(/invalid or has already been used/i)).toBeInTheDocument()
    expect(refresh).not.toHaveBeenCalled()
  })
})
