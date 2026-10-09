import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import HeldBatchEmails from './HeldBatchEmails'

const held = [
  { id: 1, batch_id: 'b', diver_id: 7, diver_name: 'Alice', recipient_name: 'Alice', recipient_email: 'alice@example.test', clips: 3, queued_at: '2026-10-09T10:00:00' },
]

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn())
})
afterEach(() => {
  vi.unstubAllGlobals()
})

describe('HeldBatchEmails', () => {
  it('shows held emails and confirms one with a single click', async () => {
    let current = held
    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/outbox/release')) {
        expect(JSON.parse(init?.body as string)).toEqual({ ids: [1] })
        current = []
        return { ok: true, json: async () => ({ released: 1 }) } as Response
      }
      return { ok: true, json: async () => ({ emails: current }) } as Response
    })
    render(<HeldBatchEmails />)
    expect(await screen.findByText(/Alice · 3 clips/)).toBeTruthy()
    fireEvent.click(screen.getAllByRole('button', { name: /^Send$/ })[0])
    await waitFor(() => expect(screen.getByText(/No email is waiting/)).toBeTruthy())
    expect(screen.getByText(/1 email\(s\) confirmed/)).toBeTruthy()
  })

  it('shows an empty state when nothing is held', async () => {
    vi.mocked(fetch).mockResolvedValue({ ok: true, json: async () => ({ emails: [] }) } as Response)
    render(<HeldBatchEmails />)
    expect(await screen.findByText(/No email is waiting/)).toBeTruthy()
  })
})
