import React from 'react'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import CodeAnalysis from './CodeAnalysis'
import { getCodeAttempts, getCodeSummaries } from '../services/codeSummariesApi'

vi.mock('../services/codeSummariesApi', () => ({
  getCodeAttempts: vi.fn(), getCodeSummaries: vi.fn(),
  peekCodeAttempts: vi.fn(() => null), peekCodeSummaries: vi.fn(() => null), clearCodeSummaryCache: vi.fn(),
}))
vi.mock('../components/clip-viewer/ClipViewer', () => ({
  default: ({ attempt, onAnalyse }: { attempt: { id: number }; onAnalyse: (attempt: { id: number }) => void }) =>
    <div role="dialog">Viewer {attempt.id}<button type="button" onClick={() => onAnalyse(attempt)}>Analysis</button></div>,
}))

const day = (offset: number) => new Date(Date.now() - offset * 86_400_000).toISOString().slice(0, 19)
const performances = ['M', 'G', 'M', 'B', 'G', 'P', 'M', 'G', 'M', 'F', 'G', 'M']
const attempts = performances.map((performance, index) => ({
  id: index + 1, dive_code: '5122D', performance, performance_numeric: 0, height: index === 3 ? '3m' : '1m',
  dive_datetime: day(60 - index * 5), session_id: Math.floor(index / 2) + 1, is_lineup: false, is_sync: false,
  platform_type: 'springboard', position: 'D', official_dd: 1.9, video_uuid: `uuid-${index + 1}`,
}))

function Location() { return <output data-testid="location">{useLocation().search}</output> }
function renderPage(entry: string) {
  return render(<MemoryRouter initialEntries={[entry]}><Routes>
    <Route path="/dives/analysis/:diveCode" element={<><CodeAnalysis /><Location /></>} />
    <Route path="/dives" element={<div>Library</div>} />
  </Routes></MemoryRouter>)
}

beforeEach(() => {
  vi.mocked(getCodeAttempts).mockResolvedValue(attempts as never)
  vi.mocked(getCodeSummaries).mockResolvedValue({ generated_at: day(0), codes: [], activity: {} } as never)
})

it('summarises every attempt of the code and highlights the dive it came from', async () => {
  renderPage('/dives/analysis/5122D?attempt=6')
  expect(await screen.findByRole('heading', { name: '5122D' })).toBeInTheDocument()
  expect(getCodeAttempts).toHaveBeenCalledWith('5122D', 'self')
  expect(screen.getByText(/12 attempts · 6 sessions/)).toBeInTheDocument()
  const focus = screen.getByText(/This dive/).closest('button')!
  expect(within(focus).getByText('10.0')).toBeInTheDocument()
  expect(within(focus).getByText('#1 of 12')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /Best/ })).toBeInTheDocument()
})

it('opens the viewer over the page and its Analysis action returns to the chart on that dive', async () => {
  renderPage('/dives/analysis/5122D')
  await userEvent.click(await screen.findByRole('button', { name: /Latest/ }))
  expect(await screen.findByRole('dialog')).toHaveTextContent('Viewer 12')
  expect(screen.getByTestId('location')).toHaveTextContent('clip=12')
  await userEvent.click(screen.getByRole('button', { name: 'Analysis' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  expect(screen.getByTestId('location')).toHaveTextContent('sel=12')
})

it('height filters narrow the whole page and keep the scroll position', async () => {
  renderPage('/dives/analysis/5122D')
  await screen.findByRole('heading', { name: '5122D' })
  const scrollTo = vi.spyOn(window, 'scrollTo').mockImplementation(() => undefined)
  await userEvent.click(screen.getAllByRole('button', { name: '1m' })[0])
  expect(screen.getByTestId('location')).toHaveTextContent('h=1m')
  expect(screen.getByText(/11 attempts/)).toBeInTheDocument()
  expect(scrollTo).not.toHaveBeenCalled()
})

it('keeps an ungraded dive in counts but out of every score view', async () => {
  vi.mocked(getCodeAttempts).mockResolvedValue([
    ...attempts,
    { id: 13, dive_code: '5122D', performance: '', performance_numeric: 0, height: '1m', dive_datetime: day(1), session_id: 7, is_lineup: false, is_sync: false, platform_type: 'springboard', position: 'D', official_dd: 1.9, video_uuid: 'uuid-13' },
  ] as never)
  renderPage('/dives/analysis/5122D')
  expect(await screen.findByRole('heading', { name: '5122D' })).toBeInTheDocument()
  // Counts still cover every attempt; scores only the twelve graded ones.
  expect(screen.getByText(/13 attempts · 7 sessions/)).toBeInTheDocument()
  expect(screen.getByText('5.2')).toBeInTheDocument()
  expect(screen.getByText('42%')).toBeInTheDocument()
})
