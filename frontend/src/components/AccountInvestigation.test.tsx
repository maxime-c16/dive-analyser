import { act, fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import AccountInvestigation from './AccountInvestigation'
it('separates public viewing from management and clears stale results on resource change', async () => {
  vi.spyOn(globalThis,'fetch').mockResolvedValue(Response.json({user_id:2,dive_id:5,diver_id:10,visibility:'public',account_active:true,can_view:true,can_manage:false,video_authorized:true,explanation:'Public viewing does not grant management.',checked_at:'2026-10-07T12:00:00Z',scope:'Authorization only.'}))
  render(<AccountInvestigation accountId={2} />)
  fireEvent.change(screen.getByLabelText('Dive ID'),{target:{value:'5'}})
  fireEvent.click(screen.getByRole('button',{name:'Run access check'}))
  expect(await screen.findByText('Public viewing does not grant management.')).toBeInTheDocument()
  expect(screen.getByText('Denied')).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Dive ID'),{target:{value:'6'}})
  expect(screen.queryByText('Public viewing does not grant management.')).not.toBeInTheDocument()
  vi.restoreAllMocks()
})

it('ignores a pending diagnostic after ownership changes and keeps the dive ready to recheck', async () => {
  let complete!: (response: Response) => void
  vi.spyOn(globalThis,'fetch').mockImplementation(() => new Promise<Response>(resolve => { complete = resolve }))
  const view = render(<AccountInvestigation accountId={2} refreshToken={0}/>)
  fireEvent.change(screen.getByLabelText('Dive ID'), { target: { value: '700' } })
  fireEvent.click(screen.getByRole('button', { name: 'Run access check' }))
  view.rerender(<AccountInvestigation accountId={2} refreshToken={1}/>)
  await act(async () => complete(Response.json({ explanation: 'Outdated access result', can_view: false, can_manage: false })))
  expect(screen.queryByText('Outdated access result')).not.toBeInTheDocument()
  expect(screen.getByLabelText('Dive ID')).toHaveValue(700)
  expect(screen.getByRole('button', { name: 'Run access check' })).toBeEnabled()
  vi.restoreAllMocks()
})
