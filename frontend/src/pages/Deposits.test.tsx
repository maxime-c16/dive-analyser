import React from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { render, screen } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import Deposits from './Deposits'
import { PendingBanner } from './Dives'
import { useAuth, type AuthUser } from '../contexts/AuthContext'
import { getBatch, listPendingBatches } from '../services/depositsApi'

vi.mock('../contexts/AuthContext', () => ({ useAuth: vi.fn() }))
vi.mock('../services/depositsApi', async (original) => ({
  ...await original<typeof import('../services/depositsApi')>(),
  listPendingBatches: vi.fn(), getBatch: vi.fn(),
}))
const admin = { user_id: 1, is_admin: true, divers: [{ diver_id: 1, access_kind: 'OWNER' }, { diver_id: 2, access_kind: 'VIEWER' }] } as AuthUser
const batch = { batch_id: 'fanny', diver_id: 2, diver_name: 'FANNY', total: 6, pending: 6, first_created: null }

beforeEach(() => {
  vi.mocked(useAuth).mockReturnValue({ user: admin, checking: false, refresh: vi.fn(), signOut: vi.fn() })
  vi.mocked(listPendingBatches).mockResolvedValue([batch])
  vi.mocked(getBatch).mockResolvedValue({ ...batch, dives: [{ id: 10, diver_id: 2, dive_code: '103B', height: '1m', performance: 'G' } as any] })
})

it('labels an admin’s other-diver batches as awaiting the owner', async () => {
  render(<MemoryRouter><Deposits /></MemoryRouter>)
  expect(await screen.findByText('Awaiting acceptance by FANNY')).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Pending dive batches' })).toBeInTheDocument()
  expect(screen.queryByText('Pick up your dives')).not.toBeInTheDocument()
})

function review() {
  render(<MemoryRouter initialEntries={['/deposits/fanny?diver=2']}><Routes>
    <Route path="/deposits/:batchId" element={<Deposits />} />
  </Routes></MemoryRouter>)
}

it('hides acceptance controls for an admin who does not own the diver', async () => {
  review()
  expect(await screen.findByText('Awaiting acceptance by FANNY')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Accept all' })).not.toBeInTheDocument()
  expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Edit' })).toBeInTheDocument()
})

it('keeps pickup and acceptance available for the actual owner', async () => {
  vi.mocked(useAuth).mockReturnValue({ user: { ...admin, is_admin: false, divers: [{ diver_id: 2, access_kind: 'OWNER' }] }, checking: false, refresh: vi.fn(), signOut: vi.fn() })
  review()
  expect(await screen.findByRole('button', { name: 'Accept all' })).toBeInTheDocument()
  expect(screen.getByRole('checkbox')).toBeInTheDocument()
})

it('counts only owned clips in the library pickup banner', async () => {
  vi.mocked(listPendingBatches).mockResolvedValue([batch, { ...batch, batch_id: 'mine', diver_id: 1, pending: 2 }])
  render(<MemoryRouter><PendingBanner /></MemoryRouter>)
  expect(await screen.findByText('2 new clip(s) to pick up')).toBeInTheDocument()
  expect(screen.queryByText('8 new clip(s) to pick up')).not.toBeInTheDocument()
})
