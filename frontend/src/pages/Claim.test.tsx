import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import Claim from './Claim'
import { peekClaim, redeemClaim } from '../services/depositsApi'

const refresh = vi.fn().mockResolvedValue(undefined)
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ refresh }) }))
vi.mock('../services/depositsApi', async original => ({
  ...await original<typeof import('../services/depositsApi')>(),
  peekClaim: vi.fn(), redeemClaim: vi.fn(),
}))
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(peekClaim).mockResolvedValue({ valid: true, batch_id: 'b', diver_id: 7, diver_name: 'Alice', pending: 2 })
  vi.mocked(redeemClaim).mockResolvedValue({ batch_id: 'b', diver_id: 7 })
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
})
function renderClaim(download = false) {
  render(<React.StrictMode><MemoryRouter initialEntries={[`/claim#t=token${download ? '&action=download' : ''}`]}><Routes>
    <Route path="/claim" element={<Claim />} />
    <Route path="/deposits/:batchId" element={<p>Download destination</p>} />
  </Routes></MemoryRouter></React.StrictMode>)
}
it('keeps review links read-only until the user clicks', async () => {
  renderClaim()
  expect(await screen.findByRole('button', { name: 'Pick up my dives' })).toBeInTheDocument()
  expect(redeemClaim).not.toHaveBeenCalled()
})
it('redeems the download action once even in StrictMode', async () => {
  renderClaim(true)
  expect(await screen.findByText('Download destination')).toBeInTheDocument()
  expect(redeemClaim).toHaveBeenCalledTimes(1)
  expect(refresh).toHaveBeenCalledTimes(1)
})
it('waits for visibility before consuming a download token', async () => {
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' })
  renderClaim(true)
  await screen.findByRole('button', { name: 'Save & download all clips' })
  expect(redeemClaim).not.toHaveBeenCalled()
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
  document.dispatchEvent(new Event('visibilitychange'))
  await waitFor(() => expect(redeemClaim).toHaveBeenCalledTimes(1))
})
