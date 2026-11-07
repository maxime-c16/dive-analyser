import { act, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { expect, it, vi } from 'vitest'
import Leaderboard from './Leaderboard'

it('replaces a stalled ranking with retry and recovers without leaving the page', async () => {
  vi.useFakeTimers()
  const fetcher = vi.spyOn(globalThis, 'fetch').mockImplementation((_url, options) => new Promise((_resolve, reject) => {
    options?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
  }))
  try {
    render(<MemoryRouter><Leaderboard excluded={new Set()} me={1} /></MemoryRouter>)
    expect(screen.getByRole('status')).toBeInTheDocument()
    await act(async () => { await vi.advanceTimersByTimeAsync(12_000) })
    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    fetcher.mockResolvedValue({ ok:true, status:200, json:async () => ({ period:'week', start:'', end:'', members:[{ user_id:1, display_name:'Maxime', attempts:2, streak_weeks:1, codes:1, delta:0 }] }) } as Response)
    await act(async () => { fireEvent.click(screen.getByRole('button', { name:'Retry' })) })
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByRole('list', { name:'Podium' })).toHaveTextContent('2')
  } finally { fetcher.mockRestore(); vi.useRealTimers() }
})
