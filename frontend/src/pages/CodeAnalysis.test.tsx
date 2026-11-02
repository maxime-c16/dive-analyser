import React from 'react'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import CodeAnalysis from './CodeAnalysis'
import { getCodeAttemptsResult, getCodeSummaries } from '../services/codeSummariesApi'

vi.mock('../services/codeSummariesApi', () => ({
  getCodeAttempts: vi.fn(), getCodeSummaries: vi.fn(),
  getCodeAttemptsResult: vi.fn(() => Promise.resolve({ items: [], capped: false })),
  peekCodeAttemptsResult: vi.fn(() => null), peekCodeAttempts: vi.fn(() => null), peekCodeSummaries: vi.fn(() => null), clearCodeSummaryCache: vi.fn(),
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
  vi.mocked(getCodeAttemptsResult).mockResolvedValue({ items: attempts as never, capped: false })
  vi.mocked(getCodeSummaries).mockResolvedValue({ generated_at: day(0), codes: [], activity: {} } as never)
})

it('summarises every attempt of the code and highlights the dive it came from', async () => {
  renderPage('/dives/analysis/5122D?attempt=6')
  expect(await screen.findByRole('heading', { name: '5122D' })).toBeInTheDocument()
  expect(getCodeAttemptsResult).toHaveBeenCalledWith('5122D', 'self', null, null)
  expect(screen.getByText(/12 attempts · 6 sessions/)).toBeInTheDocument()
  const focus = screen.getByText(/This dive/).closest('button')!
  expect(within(focus).getByText('10.0')).toBeInTheDocument()
  expect(within(focus).getByText('#1 of 12')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /Best/ })).toBeInTheDocument()
})

it('a capped diver view omits the cross-population denominator', async () => {
  // In diver view the summaries' attempt_count covers the whole scope, not
  // the selected diver: the capped notice must NOT claim "N of 12" — it
  // uses the count-free wording instead.
  vi.mocked(getCodeAttemptsResult).mockResolvedValue({
    items: attempts.slice(0, 4) as never,
    capped: true,
  })
  renderPage('/dives/analysis/5122D?diver=9')
  expect(await screen.findByRole('heading', { name: '5122D' })).toBeInTheDocument()
  expect(screen.queryByText(/\d+ attempts shown \(of /)).not.toBeInTheDocument()
  expect(screen.getByText('History capped to the newest attempts window for this view.')).toBeInTheDocument()
})

it('a capped all-divers view stays count-free until the matching summary arrives', async () => {
  // While the per-code summary is pending (here it answers OTHER codes
  // only) the bounded items slice must never pose as the history total:
  // count-free capped notice, no falsified denominator (finding 2f038074:
  // the old items.length fallback claimed "of 80" for a period slice).
  vi.mocked(getCodeAttemptsResult).mockResolvedValue({ items: attempts.slice(0, 6) as never, capped: true })
  vi.mocked(getCodeSummaries).mockResolvedValue({ generated_at: day(0), codes: [{ dive_code: 'OTHER99', attempt_count: 1200 } as never], activity: {} } as never)
  renderPage('/dives/analysis/5122D')
  expect(await screen.findByRole('heading', { name: '5122D' })).toBeInTheDocument()
  expect(screen.queryByText(/attempts shown \(of \d+/)).not.toBeInTheDocument()
  // The count-free wording carries the cap (sample tooltip), never a slice
  // posing as the total.
  expect(screen.getByTitle('History capped to the newest attempts window for this view.')).toBeInTheDocument()
})

it('an item-empty period with a missing summary shows no falsified denominator either', async () => {
  // The empty-period case had the old fallback claim "of 0" while the code
  // holds more than 1,000 attempts: unknown until the summary matches.
  vi.mocked(getCodeAttemptsResult).mockResolvedValue({ items: attempts.slice(0, 6) as never, capped: true })
  vi.mocked(getCodeSummaries).mockResolvedValue({ generated_at: day(0), codes: [], activity: {} } as never)
  renderPage('/dives/analysis/5122D?month=1999-01')
  expect(await screen.findByRole('heading', { name: '5122D' })).toBeInTheDocument()
  expect(screen.queryByText(/attempts shown \(of \d+/)).not.toBeInTheDocument()
  expect(screen.getByText('History capped to the newest attempts window for this view.')).toBeInTheDocument()
})

it('the denominator appears only once the per-code summary resolves, not before', async () => {
  // A held-pending summary asks for the count-free notice; when THIS
  // code's summary lands, the real total takes its place — no believable
  // "of slice" while pending, no "of 0" on an empty period.
  vi.mocked(getCodeAttemptsResult).mockResolvedValue({ items: attempts.slice(0, 6) as never, capped: true })
  let release!: (value?: unknown) => void
  vi.mocked(getCodeSummaries).mockImplementation(() => new Promise(resolve => { release = resolve }) as never)
  renderPage('/dives/analysis/5122D')
  await waitFor(() => expect(screen.getByTitle('History capped to the newest attempts window for this view.')).toBeInTheDocument())
  expect(screen.queryByText(/attempts shown \(of \d+/)).not.toBeInTheDocument()
  // THIS code's summary lands: the real denominator switches in.
  release!({ generated_at: day(0), codes: [{ dive_code: '5122D', attempt_count: 1200 } as never], activity: {} } as never)
  expect(await screen.findByText(/6 attempts shown \(of 1200/)).toBeInTheDocument()
})
it('a capped all-divers view takes the real denominator once the matching summary lands', async () => {
  vi.mocked(getCodeAttemptsResult).mockResolvedValue({ items: attempts.slice(0, 6) as never, capped: true })
  vi.mocked(getCodeSummaries).mockResolvedValue({ generated_at: day(0), codes: [{ dive_code: '5122D', attempt_count: 1200 } as never], activity: {} } as never)
  renderPage('/dives/analysis/5122D')
  expect(await screen.findByText(/6 attempts shown \(of 1200/)).toBeInTheDocument()
  expect(screen.queryByText('History capped to the newest attempts window for this view.')).not.toBeInTheDocument()
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
  vi.mocked(getCodeAttemptsResult).mockResolvedValue({ items: [
    ...attempts,
    { id: 13, dive_code: '5122D', performance: '', performance_numeric: 0, height: '1m', dive_datetime: day(1), session_id: 7, is_lineup: false, is_sync: false, platform_type: 'springboard', position: 'D', official_dd: 1.9, video_uuid: 'uuid-13' },
  ] as never, capped: false })
  renderPage('/dives/analysis/5122D')
  expect(await screen.findByRole('heading', { name: '5122D' })).toBeInTheDocument()
  // Counts still cover every attempt; scores only the twelve graded ones.
  expect(screen.getByText(/13 attempts · 7 sessions/)).toBeInTheDocument()
  expect(screen.getByText('5.2')).toBeInTheDocument()
  expect(screen.getByText('42%')).toBeInTheDocument()
  // The newest dive is ungraded, so the Latest representative falls back to
  // the newest graded dive (id 12, an M) instead of showing a 0.0 score.
  const latestRep = screen.getByRole('button', { name: /Latest/ })
  expect(within(latestRep).getByText('4.5')).toBeInTheDocument()
  expect(within(latestRep).queryByText('0.0')).toBeNull()
})
