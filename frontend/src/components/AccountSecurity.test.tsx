import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import AccountSecurity from './AccountSecurity'
beforeEach(() => { vi.restoreAllMocks() })
it('confirms a single session revocation and keeps the session on failure', async () => {
  const fetch = vi.spyOn(globalThis,'fetch').mockImplementation(async (_,init) => init?.method === 'DELETE' ? Response.json({ detail:'Unable to revoke session' },{status:503}) : Response.json({ sessions:[{session_id:7,created_at:'2026-01-01T00:00:00Z',last_used_at:null,expires_at:'2026-12-01T00:00:00Z'}],total:1 }))
  render(<AccountSecurity accountId={2} section="security" self={false} onRefresh={vi.fn()} />)
  fireEvent.click(await screen.findByRole('button',{name:'Sign out',exact:true}))
  expect(fetch.mock.calls.some(([,init])=>init?.method==='DELETE')).toBe(false)
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button',{name:'Confirm'}))
  await waitFor(()=>expect(screen.getAllByRole('alert')[0]).toHaveTextContent('Unable to revoke session'))
  expect(screen.getByText('Session #7')).toBeInTheDocument()
  expect(screen.getByRole('dialog')).toBeInTheDocument()
})
it('labels role changes separately from diver grants in historical events', async () => {
  vi.spyOn(globalThis,'fetch').mockResolvedValue(Response.json({events:[{event_id:1,event_type:'ownership_granted',actor:'admin:4',created_at:'2026-01-01T00:00:00Z',diver_id:null,details:{new_role:'administrator'}}],total:1}))
  render(<AccountSecurity accountId={2} section="history" self={false} onRefresh={vi.fn()} />)
  expect(await screen.findByText('Role changed to administrator')).toBeInTheDocument()
  expect(screen.getByText(/Administrator #4/)).toBeInTheDocument()
})
