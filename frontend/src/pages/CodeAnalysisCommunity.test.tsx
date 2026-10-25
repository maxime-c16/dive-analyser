import React from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import CodeAnalysis from './CodeAnalysis'
import { getCodeAttempts, getCodeSummaries } from '../services/codeSummariesApi'
import { getCodeCommunity } from '../services/codeCommunityApi'

vi.mock('../services/codeSummariesApi', () => ({
  getCodeAttempts: vi.fn(), getCodeSummaries: vi.fn(),
  peekCodeAttempts: vi.fn(() => null), peekCodeSummaries: vi.fn(() => null), clearCodeSummaryCache: vi.fn(),
}))
vi.mock('../services/codeCommunityApi', () => ({
  getCodeCommunity: vi.fn(), clearCodeCommunityCache: vi.fn(),
}))
vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({
    user: {
      user_id: 1, email: 'me@example.com', display_name: 'Me', role: 'owner', is_admin: false,
      divers: [{ diver_id: 1, access_kind: 'OWNER' }],
    },
    checking: false, refresh: vi.fn(), signOut: vi.fn(),
  }),
}))
vi.mock('../components/clip-viewer/ClipViewer', () => ({
  default: () => null,
}))

const day = (offset: number) => new Date(Date.now() - offset * 86_400_000).toISOString().slice(0, 19)
const attempt = (id: number, diver_id: number, performance: string, offset: number) => ({
  id, diver_id, dive_code: '5122D', performance, performance_numeric: 0, height: '1m',
  dive_datetime: day(offset), session_id: id, is_lineup: false, is_sync: false,
  platform_type: 'springboard', position: 'D', official_dd: 1.9, video_uuid: `uuid-${id}`,
})
// My four Ms (4.5) plus another diver's four Ps (10): "you" stays 4.5 only
// when the ranking ignores attempts on divers I do not own.
const attempts = [
  attempt(1, 1, 'M', 40), attempt(2, 1, 'M', 30), attempt(3, 1, 'M', 20), attempt(4, 1, 'M', 10),
  attempt(5, 2, 'P', 40), attempt(6, 2, 'P', 30), attempt(7, 2, 'P', 20), attempt(8, 2, 'P', 10),
]
const members = [{
  diver_id: 2, name: 'LEO', account: null, attempt_count: 4, scored_count: 4,
  median: 10, q1: 10, q3: 10, last_attempt_at: day(10), series: [10, 10, 10], best: null,
}]

beforeEach(() => {
  vi.mocked(getCodeAttempts).mockResolvedValue(attempts as never)
  vi.mocked(getCodeSummaries).mockResolvedValue({ generated_at: day(0), codes: [], activity: {} } as never)
  vi.mocked(getCodeCommunity).mockResolvedValue({ dive_code: '5122D', members, hidden_count: 0 } as never)
})

it('ranks only my own divers’ attempts as "you" against the community', async () => {
  render(<MemoryRouter initialEntries={['/dives/analysis/5122D']}><Routes>
    <Route path="/dives/analysis/:diveCode" element={<CodeAnalysis />} />
  </Routes></MemoryRouter>)
  expect(await screen.findByRole('heading', { name: '5122D' })).toBeInTheDocument()
  // The fetch carries a viewer key: the response omits my divers.
  expect(getCodeCommunity).toHaveBeenCalledWith('5122D', '', expect.any(String))
  await userEvent.click(await screen.findByRole('button', { name: /Compare with Leo/ }))
  expect(screen.getByText('vs 4.5 for you')).toBeInTheDocument()
})
