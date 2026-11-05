import type { ReactElement } from 'react'
import { MemoryRouter } from 'react-router-dom'
import i18n from '../../i18n'
import { act, fireEvent, render as rtlRender, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import AutomaticScores from './AutomaticScores'
import { getAutomaticScores, setAutomaticExclusion } from '../../services/evaluationApi'
vi.mock('../../services/evaluationApi', () => ({ getAutomaticScores: vi.fn(), loadAutomaticIdentities: vi.fn().mockResolvedValue(undefined), setAutomaticExclusion: vi.fn() }))
function render(ui: ReactElement) { return rtlRender(<MemoryRouter>{ui}</MemoryRouter>) }
beforeEach(() => { vi.clearAllMocks() })
it('keeps the exclusion state unchanged on failure and only confirms after persistence', async () => {
  vi.mocked(getAutomaticScores).mockResolvedValue({ items: [{ dive_id: 1, dive_code: '101B', height: '3m', excluded: false, rating_count: 2, mean_score: 6.5, provisional: true }], total: 1 })
  vi.mocked(setAutomaticExclusion).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce()
  render(<AutomaticScores />)
  const toggle = await screen.findByRole('switch', { name: 'In selections' })
  fireEvent.click(toggle)
  await screen.findByRole('alert')
  expect(toggle).toBeChecked()
  await waitFor(() => expect(toggle).not.toBeDisabled())
  fireEvent.click(toggle)
  expect(await screen.findByRole('switch', { name: 'In selections' })).not.toBeChecked()
  expect(setAutomaticExclusion).toHaveBeenLastCalledWith(1, true)
  expect(screen.getByText(/6.5.*2 reviewers.*provisional/)).toBeInTheDocument()
})
it('fetches the next page without dropping the public-dive explanation', async () => {
  vi.mocked(getAutomaticScores).mockResolvedValueOnce({ items: Array.from({ length: 20 }, (_, n) => ({ dive_id: n + 1, dive_code: '101B', height: '3m', excluded: false, rating_count: 0, mean_score: null, provisional: true })), total: 21 })
    .mockResolvedValueOnce({ items: [{ dive_id: 21, dive_code: '103B', height: '3m', excluded: true, rating_count: 0, mean_score: null, provisional: true }], total: 21 })
  render(<AutomaticScores />)
  fireEvent.click(await screen.findByRole('button', { name: 'Show more' }))
  await screen.findByText('103B · 3m')
  expect(screen.getByRole('switch', { name: 'In selections' })).not.toBeChecked()
  expect(getAutomaticScores).toHaveBeenLastCalledWith(20)
  expect(screen.getByText(/Public dives can be selected automatically/)).toBeInTheDocument()
})

it('sorts the loaded page by score or by judges without refetching', async () => {
  vi.mocked(getAutomaticScores).mockResolvedValue({ items: [
    { dive_id: 1, dive_code: '101B', height: '1m', excluded: false, rating_count: 1, mean_score: 9, provisional: true },
    { dive_id: 2, dive_code: '203C', height: '3m', excluded: false, rating_count: 4, mean_score: 5.5, provisional: true },
    { dive_id: 3, dive_code: '5231D', height: '3m', excluded: false, rating_count: 0, mean_score: null, provisional: true },
  ], total: 3 })
  render(<AutomaticScores />)
  await screen.findByText('101B · 1m')
  const order = () => screen.getAllByText(/ · \dm$/).map(node => node.textContent)
  expect(order()).toEqual(['101B · 1m', '203C · 3m', '5231D · 3m'])
  fireEvent.click(screen.getByRole('button', { name: 'Most judged' }))
  expect(order()).toEqual(['203C · 3m', '101B · 1m', '5231D · 3m'])
  fireEvent.click(screen.getByRole('button', { name: 'Top score' }))
  expect(order()[0]).toBe('101B · 1m')
  expect(getAutomaticScores).toHaveBeenCalledTimes(1)
})

it('uses French decimal commas in both the visible scores and accessible summaries', async () => {
  vi.mocked(getAutomaticScores).mockResolvedValue({ items: [{ dive_id: 1, dive_code: '101B', height: '3m', excluded: false, rating_count: 2, mean_score: 6.5, provisional: true }], total: 1 })
  await act(async () => { await i18n.changeLanguage('fr') })
  try {
    const { container } = render(<AutomaticScores />)
    expect(await screen.findByText(/6,5.*2 évaluateurs.*provisoire/)).toBeInTheDocument()
    await waitFor(() => expect(container.querySelector('.eval-mean')).toHaveTextContent('6,5'))
    await act(async () => { await i18n.changeLanguage('en') })
    expect(screen.getByText(/6.5.*2 reviewers.*provisional/)).toBeInTheDocument()
    await waitFor(() => expect(container.querySelector('.eval-mean')).toHaveTextContent('6.5'))
  } finally { await act(async () => { await i18n.changeLanguage('en') }) }
})

it('distinguishes repeated codes with the actual attempt time and keeps exact clip destinations', async () => {
  vi.mocked(getAutomaticScores).mockResolvedValue({ items: [
    { dive_id: 81, dive_code: '101B', height: '1m', excluded: false, rating_count: 0, mean_score: null, provisional: true,
      identity: { id: 81, dive_datetime: '2026-10-18T17:23:24', video_uuid: null, dive_code: '101B', height: '1m', performance: 'M', performance_numeric: 5, session_id: 1, is_lineup: false, is_sync: false, platform_type: 'springboard', official_dd: 1.3 } },
    { dive_id: 82, dive_code: '101B', height: '1m', excluded: false, rating_count: 1, mean_score: 0, provisional: true,
      identity: { id: 82, dive_datetime: '2026-10-18T17:25:08', video_uuid: null, dive_code: '101B', height: '1m', performance: 'M', performance_numeric: 5, session_id: 1, is_lineup: false, is_sync: false, platform_type: 'springboard', official_dd: 1.3 } },
  ], total: 2 })
  const { container } = render(<AutomaticScores />)
  await screen.findAllByText('101B · 1m')
  expect([...container.querySelectorAll('time')].map(node => node.dateTime)).toEqual(['2026-10-18T17:23:24', '2026-10-18T17:25:08'])
  expect([...container.querySelectorAll('.eval-dive-link')].map(node => node.getAttribute('href'))).toEqual(['/dives?clip=81', '/dives?clip=82'])
  expect([...container.querySelectorAll('.eval-mean')].map(node => node.textContent)).toEqual(['0.0 / 10'])
})

it('keeps imported attempts distinct when their timestamps are identical', async () => {
  const identity = {dive_datetime:'2026-10-18T17:23:24',video_uuid:null,dive_code:'101B',height:'1m',performance:'M',performance_numeric:5,session_id:1,is_lineup:false,is_sync:false,platform_type:'springboard',official_dd:1.3} as const
  vi.mocked(getAutomaticScores).mockResolvedValue({items:[81,82].map(id=>({dive_id:id,dive_code:'101B',height:'1m',excluded:false,rating_count:0,mean_score:null,provisional:true,identity:{...identity,id}})),total:2})
  const {container}=render(<AutomaticScores/>)
  await screen.findByText('#81')
  expect(screen.getByText('#82')).toBeInTheDocument()
  expect([...container.querySelectorAll('time')].map(node=>node.textContent)).toEqual(['18 Oct 2026','18 Oct 2026'])
  expect(screen.getAllByRole('switch',{name:'In selections'}).every(node=>(node as HTMLInputElement).checked)).toBe(true)
  expect(container.querySelector('.eval-mean')).toBeNull()
})
