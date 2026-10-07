import { MemoryRouter } from 'react-router-dom'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import Admin from './Admin'
import { getOperationsStatus } from '../services/operationsApi'

vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { user_id: 1 } }) }))
vi.mock('../components/AdminUsers', () => ({ default: () => <div>User directory</div> }))
vi.mock('../services/operationsApi', () => ({ getOperationsStatus: vi.fn() }))

beforeEach(() => {
  vi.useFakeTimers()
  vi.mocked(getOperationsStatus).mockReset()
  // An in-flight expensive snapshot; it must not be requested for Users.
  vi.mocked(getOperationsStatus).mockImplementation(() => new Promise(() => {}))
})
afterEach(() => { vi.useRealTimers() })

describe('Administration status loading', () => {
  it('does not fetch or poll the hidden System tab', async () => {
    render(<MemoryRouter><Admin /></MemoryRouter>)
    expect(screen.getByText('User directory')).toBeInTheDocument()
    await act(() => vi.advanceTimersByTimeAsync(45_000))
    expect(getOperationsStatus).not.toHaveBeenCalled()
  })

  it('loads System on demand and cancels when returning to Users', async () => {
    render(<MemoryRouter><Admin /></MemoryRouter>)
    fireEvent.click(screen.getByRole('button', { name: 'System' }))
    expect(getOperationsStatus).toHaveBeenCalledTimes(1)
    const signal = vi.mocked(getOperationsStatus).mock.calls[0][0]!
    expect(signal.aborted).toBe(false)
    fireEvent.click(screen.getByRole('button', { name: 'Users' }))
    expect(signal.aborted).toBe(true)
    await act(() => vi.advanceTimersByTimeAsync(45_000))
    expect(getOperationsStatus).toHaveBeenCalledTimes(1)
    expect(screen.getByText('User directory')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'System' }))
    expect(getOperationsStatus).toHaveBeenCalledTimes(2)
  })

  it('waits for a slow snapshot to finish before scheduling the next poll', async () => {
    let reject!: (reason: Error) => void
    vi.mocked(getOperationsStatus).mockImplementation(() => new Promise((_, r) => { reject = r }))
    render(<MemoryRouter><Admin /></MemoryRouter>)
    fireEvent.click(screen.getByRole('button', { name: 'System' }))
    await act(() => vi.advanceTimersByTimeAsync(45_000))
    expect(getOperationsStatus).toHaveBeenCalledTimes(1)
    await act(async () => { reject(new Error('Temporary failure')) })
    await act(() => vi.advanceTimersByTimeAsync(15_000))
    expect(getOperationsStatus).toHaveBeenCalledTimes(2)
    fireEvent.click(screen.getByRole('button', { name: 'Users' }))
    await act(async () => { reject(new Error('Cancelled request')) })
    await act(() => vi.advanceTimersByTimeAsync(30_000))
    expect(getOperationsStatus).toHaveBeenCalledTimes(2)
  })

  it('shares cancellation and serialization between manual refresh and polling', async () => {
    let reject!: (reason: Error) => void
    vi.mocked(getOperationsStatus).mockImplementation(() => new Promise((_, r) => { reject = r }))
    render(<MemoryRouter><Admin /></MemoryRouter>)
    fireEvent.click(screen.getByRole('button', { name: 'System' }))
    const signal = vi.mocked(getOperationsStatus).mock.calls[0][0]!
    await act(async () => { reject(new Error('Initial snapshot failed')) })
    fireEvent.click(screen.getByRole('button', { name: 'Refresh' }))
    expect(getOperationsStatus).toHaveBeenCalledTimes(2)
    expect(vi.mocked(getOperationsStatus).mock.calls[1][0]).toBe(signal)
    await act(() => vi.advanceTimersByTimeAsync(30_000))
    expect(getOperationsStatus).toHaveBeenCalledTimes(2)
    await act(async () => { reject(new Error('Manual snapshot failed')) })
    await act(() => vi.advanceTimersByTimeAsync(15_000))
    expect(getOperationsStatus).toHaveBeenCalledTimes(3)
    fireEvent.click(screen.getByRole('button', { name: 'Refresh' }))
    expect(getOperationsStatus).toHaveBeenCalledTimes(3)
    fireEvent.click(screen.getByRole('button', { name: 'Users' }))
    expect(signal.aborted).toBe(true)
    await act(async () => { reject(new Error('Cancelled poll')) })
    await act(() => vi.advanceTimersByTimeAsync(30_000))
    expect(getOperationsStatus).toHaveBeenCalledTimes(3)
  })

})
